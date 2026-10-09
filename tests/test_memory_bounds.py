"""Ограничение памяти на больших проверках без облачных операций."""

import json

import pytest
from PySide6.QtWidgets import QApplication

from app.core.settings_store import SettingsStore
from app.models.sync_task import SyncTask
from app.services.rclone_runner import RcloneRunner
from app.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_log_retains_recent_lines_and_bounds_long_messages(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr(MainWindow, "_create_tray_icon", lambda self: setattr(self, "tray_icon", None))
    window = MainWindow(SettingsStore(tmp_path / "settings.json"))
    window.scheduler_timer.stop()
    for index in range(12000):
        window._append_log(f"file-{index}: copied")
    window._append_log("x" * 100000)
    text = window.log_view.toPlainText()
    assert window.log_view.blockCount() <= 2000
    assert "file-0:" not in text
    assert "file-11999:" in text
    assert len(text.splitlines()[-1]) < 2200
    assert not window.log_view.isUndoRedoEnabled()
    window.deleteLater()
    qt_app.processEvents()


@pytest.mark.parametrize("with_stats", [False, True])
def test_large_dry_run_keeps_counts_after_detail_limit(qt_app, with_stats):
    runner = RcloneRunner()
    runner._current_meta = {"mode": "dry-run"}
    results = []
    runner.command_finished.connect(results.append)
    for index in range(15000):
        runner._handle_line(f"- file-{index}", is_error=False)
        runner._handle_line(json.dumps({"level": "notice", "msg": "Skipped delete as --dry-run is set", "object": f"file-{index}"}), is_error=True)
    if with_stats:
        runner._handle_line('{"stats":{"transfers":0,"deletes":15000}}', is_error=True)
    runner._emit_finished(exit_code=0, crashed=False)
    assert results[0]["change_candidates"] == 15000
    assert results[0]["delete_candidates"] == 15000
    assert 0 < len(results[0]["change_details"]) <= 100


def test_legacy_settings_and_model_bound_samples_without_changing_tasks(tmp_path):
    data = SyncTask(id="same", name="Mirror", source_path="D:/", remote_path="account:Backup").to_dict()
    data["last_change_candidates"] = 20000
    data["last_delete_candidates"] = 17000
    data["last_change_details"] = [f"file-{i}: changed" for i in range(20000)]
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"tasks": [data], "custom": "preserved"}), encoding="utf-8")
    store = SettingsStore(path)
    task = SyncTask.from_dict(data)
    assert len(task.last_change_details) <= 100
    assert len(store.get_tasks_data()[0]["last_change_details"]) <= 100
    task.last_change_details = data["last_change_details"]
    assert len(task.to_dict()["last_change_details"]) <= 100
    store.save()
    restored = json.loads(path.read_text(encoding="utf-8"))
    assert restored["custom"] == "preserved"
    assert restored["tasks"][0]["last_change_candidates"] == 20000
    assert restored["tasks"][0]["last_delete_candidates"] == 17000
    assert restored["tasks"][0]["id"] == "same"


def test_diagnostic_output_and_unterminated_lines_are_bounded(qt_app):
    runner = RcloneRunner()
    runner._current_meta = {"kind": "diagnostic", "diagnostic_name": "remote-quota"}
    results = []
    runner.command_finished.connect(results.append)
    for _ in range(50):
        runner._consume_output("x" * 60000 + "\n", is_error=False)
    assert sum(map(len, runner._raw_output_lines)) <= 1024 * 1024
    runner._consume_output("y" * 200000, is_error=False)
    assert len(runner._stdout_buffer) <= 65536
    runner._consume_output('continued\n{"total":100}\n', is_error=False)
    runner._emit_finished(exit_code=0, crashed=False)
    assert not results[0]["success"]
    assert results[0]["output_truncated"]


def test_combined_only_counts_beyond_sample_and_releases_completed_data(qt_app):
    runner = RcloneRunner()
    runner._current_meta = {"mode": "dry-run"}
    results = []
    runner.command_finished.connect(results.append)
    for index in range(3000):
        runner._consume_output(f"+ upload-{index}\n- delete-{index}\n", is_error=False)
    runner._emit_finished(exit_code=0, crashed=False)
    assert results[0]["change_candidates"] == 6000
    assert results[0]["delete_candidates"] == 3000
    assert len(results[0]["change_details"]) == 100
    assert runner._change_details == {}
    assert runner._last_stats == {}
    assert runner._raw_output_lines == []


def test_overlong_partial_line_is_discarded_until_next_newline(qt_app):
    runner = RcloneRunner()
    runner._current_meta = {"mode": "dry-run"}
    results = []
    runner.command_finished.connect(results.append)
    runner._consume_output("z" * 70000, is_error=False)
    runner._consume_output("+ false-change", is_error=False)
    runner._consume_output("\n+ real-change\n", is_error=False)
    runner._emit_finished(exit_code=0, crashed=False)
    assert results[0]["change_candidates"] == 1
    assert results[0]["change_details"] == [
        "real-change: есть локально, отсутствует в облаке"
    ]
    assert not results[0]["success"]


def test_confirmation_summary_counts_changes_outside_sample(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr(MainWindow, "_create_tray_icon", lambda self: setattr(self, "tray_icon", None))
    window = MainWindow(SettingsStore(tmp_path / "settings.json"))
    window.scheduler_timer.stop()
    task = SyncTask(id="one", name="Mirror", source_path="D:/", remote_path="account:Backup")
    task.last_change_candidates = 25000
    task.last_change_details = [f"file-{i}" for i in range(100)]
    assert "...ещё 24988" in window._task_change_details_text(task)
    window.deleteLater()
    qt_app.processEvents()
