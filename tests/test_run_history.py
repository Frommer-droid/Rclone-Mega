"""Individual reports survive restart and export the selected run in full."""

import json
import sys

import pytest
from PySide6.QtWidgets import QApplication, QToolButton
from PySide6.QtTest import QTest

from app.core.run_history import RunHistory
from app.core.settings_store import SettingsStore
from app.models.sync_task import SyncTask
from app.ui.main_window import MainWindow
from app.ui.run_history_dialog import RunHistoryDialog
from app.services.rclone_runner import RcloneRunner


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def task():
    return SyncTask(
        id="one",
        name="Задача / тест",
        source_path="D:/Source",
        remote_path="account:Backup",
    )


def complete(history, output, mode="sync"):
    history.start(task(), mode, "Вручную", "rclone.exe", ["sync", "D:/Source"])
    history.append(output)
    history.finish({"summary": output, "exit_code": 1, "error_count": 1}, "Ошибка")


def test_reports_are_separate_persistent_and_export_selected_run(tmp_path):
    history = RunHistory(tmp_path / "history")
    complete(history, "первая ошибка", "dry-run")
    complete(history, "вторая ошибка")
    restored = RunHistory(history.root)
    records = restored.records("one")
    assert len(records) == 2
    assert records[0]["mode"] == "sync"
    assert records[1]["mode"] == "dry-run"
    for markdown in (False, True):
        destination = tmp_path / ("report.md" if markdown else "report.log")
        restored.export(records[1], destination, markdown)
        text = destination.read_text(encoding="utf-8")
        assert "первая ошибка" in text and "вторая ошибка" not in text
        assert "Код завершения: 1" in text
        assert "Начало:" in text and "Окончание:" in text
        assert "account:Backup" in text
    assert "/" not in history.filename(records[0], "md")


def test_preview_bounds_memory_but_export_keeps_full_output(tmp_path):
    history = RunHistory(tmp_path / "history")
    complete(history, "FIRST\n" + "line\n" * 60_000 + "LAST")
    record = history.records("one")[0]
    # Summary is small in actual runner results; replace the synthetic large one.
    record["summary"] = "Failed"
    preview = history.preview(record)
    assert "Показан конец журнала" in preview
    assert "FIRST" not in preview
    assert "LAST" in preview
    assert len(preview) < 260_000
    destination = tmp_path / "full.log"
    history.export(record, destination, False)
    assert "FIRST" in destination.read_text(encoding="utf-8")


def test_interrupted_run_and_corrupt_metadata(tmp_path):
    history = RunHistory(tmp_path)
    history.start(task(), "sync", "Вручную", "rclone.exe", [])
    history.append("Last available line")
    assert history.records("one")[0]["status"] == "Выполняется"
    restored = RunHistory(tmp_path)
    record = restored.records("one")[0]
    assert record["status"].startswith("Прервано")
    assert "Last available line" in restored.preview(record)
    bad = history.log_path(record).with_name("bad.json")
    bad.write_text('{"task_id":"one","run_id":"bad"}', encoding="utf-8")
    assert len(restored.records("one")) == 1


def test_history_write_failure_does_not_break_run(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("file", encoding="utf-8")
    history = RunHistory(blocked)
    history.start(task(), "sync", "", "rclone.exe", [])
    assert history.failure
    history.append("error")
    history.finish({"summary": "error"}, "Ошибка")
    assert history.active is None and history.failure


def test_export_cannot_overwrite_internal_history(tmp_path):
    history = RunHistory(tmp_path / "history")
    complete(history, "error")
    record = history.records("one")[0]
    before = history.log_path(record).read_bytes()
    with pytest.raises(ValueError):
        history.export(record, history.log_path(record), False)
    assert history.log_path(record).read_bytes() == before


def test_window_captures_errors_not_global_queue_messages(
    qt_app, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        MainWindow, "_create_tray_icon", lambda self: setattr(self, "tray_icon", None)
    )
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["account"])
    item = task()
    item.source_path = str(tmp_path)
    store.set_tasks_data([item.to_dict()])
    window = MainWindow(store)
    window.scheduler_timer.stop()
    window._geometry_save_timer.stop()
    monkeypatch.setattr(window, "_current_rclone_path", lambda: "fake-rclone.exe")

    def fake_run(executable, config, sync_task, dry_run):
        runner = window.runner
        runner._current_meta = {"kind": "task", "task_id": sync_task.id, "mode": "sync"}
        runner._handle_line(
            json.dumps({"level": "error", "msg": "file locked", "object": "data.bin"}),
            is_error=True,
        )
        runner._emit_finished(exit_code=1, crashed=False)
        return True

    monkeypatch.setattr(window.runner, "run_task", fake_run)
    window.command_queue.append({"kind": "task", "task_id": item.id, "dry_run": False})
    window._append_log("unrelated global message")
    window._start_next_queued_command()
    record = window.run_history.records(item.id)[0]
    assert record["status"] == "Ошибка"
    assert "file locked [data.bin]" in record["summary"]
    text = window.run_history.preview(record)
    assert "[ERROR] file locked [data.bin]" in text
    assert "unrelated global message" not in text
    assert (
        window.table.cellWidget(0, 7).findChild(QToolButton, "runHistoryButton").menu().actions()[0].text()
        == "История запусков…"
    )
    window.deleteLater()
    qt_app.processEvents()


def test_dialog_exports_selected_run_and_cancel_is_safe(qt_app, tmp_path, monkeypatch):
    history = RunHistory(tmp_path / "history")
    complete(history, "OLD ERROR")
    complete(history, "NEW ERROR")
    dialog = RunHistoryDialog(history, "one", "Test")
    dialog.runs.setCurrentRow(1)
    destination = tmp_path / "selected.md"
    monkeypatch.setattr(
        "app.ui.run_history_dialog.QFileDialog.getSaveFileName",
        lambda *args: (str(destination), ""),
    )
    monkeypatch.setattr(
        "app.ui.run_history_dialog.QMessageBox.information", lambda *args: None
    )
    dialog.md_button.click()
    assert "OLD ERROR" in destination.read_text(encoding="utf-8")
    assert "NEW ERROR" not in destination.read_text(encoding="utf-8")
    before = destination.read_bytes()
    monkeypatch.setattr(
        "app.ui.run_history_dialog.QFileDialog.getSaveFileName", lambda *args: ("", "")
    )
    dialog.md_button.click()
    assert destination.read_bytes() == before
    dialog.deleteLater()
    qt_app.processEvents()


def test_running_report_cannot_be_exported_from_dialog(qt_app, tmp_path):
    history = RunHistory(tmp_path)
    history.start(task(), "dry-run", "", "rclone.exe", [])
    dialog = RunHistoryDialog(history, "one", "Test")
    assert not dialog.md_button.isEnabled()
    assert not dialog.log_button.isEnabled()
    dialog.deleteLater()
    qt_app.processEvents()


def test_missing_source_attempt_has_its_own_report(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr(
        MainWindow, "_create_tray_icon", lambda self: setattr(self, "tray_icon", None)
    )
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["account"])
    item = task()
    item.source_path = str(tmp_path / "missing")
    store.set_tasks_data([item.to_dict()])
    window = MainWindow(store)
    window.scheduler_timer.stop()
    window._geometry_save_timer.stop()
    monkeypatch.setattr(window, "_current_rclone_path", lambda: "fake-rclone.exe")
    window.command_queue.append({"kind": "task", "task_id": item.id, "dry_run": True})
    window._start_next_queued_command()
    record = window.run_history.records(item.id)[0]
    assert record["status"] == "Источник не найден"
    assert record["finished_at"]
    assert "Локальная папка не существует" in window.run_history.preview(record)
    window.deleteLater()
    qt_app.processEvents()


@pytest.mark.parametrize("failed_to_start", [False, True])
def test_real_process_failure_and_final_unterminated_line_are_preserved(
    qt_app, tmp_path, failed_to_start
):
    history = RunHistory(tmp_path / "history")
    runner = RcloneRunner()
    executable = str(tmp_path / "missing.exe") if failed_to_start else sys.executable
    args = (
        []
        if failed_to_start
        else ["-c", "import sys; sys.stderr.write('FINAL ERROR'); sys.exit(1)"]
    )
    history.start(task(), "sync", "Test", executable, args)
    runner.raw_output.connect(history.append)
    results = []

    def finished(result):
        history.finish(result, "Ошибка")
        results.append(result)

    runner.command_finished.connect(finished)
    runner._start(executable, args, {"kind": "task", "task_id": "one", "mode": "sync"})
    for _ in range(100):
        if results:
            break
        QTest.qWait(30)
    assert results and not results[0]["success"]
    record = RunHistory(history.root).records("one")[0]
    assert record["status"] == "Ошибка"
    text = history.preview(record)
    assert ("Ошибка запуска процесса" if failed_to_start else "FINAL ERROR") in text
