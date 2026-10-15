"""Пауза приложений: область действия, ручное закрытие и восстановление."""

import os
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtTest import QTest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from app.models.sync_task import SyncTask
from app.services import process_pause as pause
from app.services import rclone_runner as runner_module
from app.services.rclone_runner import RcloneRunner
from app.ui.task_dialog import TaskDialog
from app.ui.main_window import MainWindow
from app.core.settings_store import SettingsStore


def record(pid, parent, executable, command=None):
    return pause.ApplicationProcess(pid, parent, str(executable),
                                    command or f'"{executable}"', pid * 100)


def wait_until(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert predicate()


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_selection_protects_self_ancestors_and_children_but_not_siblings(tmp_path):
    source = tmp_path / "portable"
    own = source / "Rclone Mega"
    records = [
        record(1, 0, tmp_path / "explorer.exe"),
        record(2, 1, own / "Rclone Mega.exe"),
        record(3, 2, own / "rclone.exe"),
        record(4, 3, tmp_path / "conhost.exe"),
        record(5, 1, source / "Telegram73" / "Telegram.exe"),
        record(6, 1, source / "Telegram29" / "Telegram.exe"),
        record(7, 1, tmp_path / "portable-other" / "app.exe"),
        record(8, 1, source / "AquaSnap" / "daemon.exe"),
        record(9, 8, source / "AquaSnap" / "helper.exe"),
    ]
    selected = pause.select_applications(records, source, own, own / "rclone.exe", 2)
    assert [p.pid for p in selected] == [5, 6, 8, 9]
    assert [p.pid for p in pause.root_applications(selected)] == [5, 6, 8]


def test_prepare_captures_parameters_before_shutdown_and_manual_retry(tmp_path, monkeypatch):
    first = record(10, 1, tmp_path / "Telegram" / "Telegram.exe", '"telegram" -profile 73')
    helper = record(11, 10, tmp_path / "Telegram" / "helper.exe")
    session = pause.ProcessPauseSession(str(tmp_path), tmp_path / "own", "rclone.exe")
    candidates = [first, helper]
    monkeypatch.setattr(session, "_candidates", lambda: list(candidates))
    monkeypatch.setattr(pause, "process_started", lambda pid: pid * 100)
    def close(processes):
        assert session.roots == [first]
        assert processes == [first]
        candidates.remove(helper)
    monkeypatch.setattr(pause, "graceful_shutdown", close)
    assert session.prepare() == [first.label]
    candidates.clear()  # Пользователь вручную закрыл Telegram.
    assert session.remaining() == []
    assert session.roots[0].command_line == '"telegram" -profile 73'


def test_missing_command_line_aborts_before_closing_anything(tmp_path, monkeypatch):
    session = pause.ProcessPauseSession(str(tmp_path), tmp_path / "own", "rclone.exe")
    monkeypatch.setattr(session, "_candidates", lambda: [
        pause.ApplicationProcess(10, 1, str(tmp_path / "app.exe"), "", 100)
    ])
    monkeypatch.setattr(pause, "graceful_shutdown", lambda _: pytest.fail("закрытие"))
    with pytest.raises(RuntimeError, match="параметры запуска"):
        session.prepare()


def test_shutdown_failure_requests_manual_close(tmp_path, monkeypatch):
    app = record(10, 1, tmp_path / "app.exe")
    session = pause.ProcessPauseSession(str(tmp_path), tmp_path / "own", "rclone.exe")
    monkeypatch.setattr(session, "_candidates", lambda: [app])
    monkeypatch.setattr(pause, "process_started", lambda pid: pid * 100)
    def denied(_):
        raise OSError("access denied")
    monkeypatch.setattr(pause, "graceful_shutdown", denied)
    assert session.prepare() == [app.label]
    assert session.roots == [app]


def test_cancel_prevents_closing_more_apps(tmp_path, monkeypatch):
    first = record(10, 1, tmp_path / "a.exe")
    second = record(20, 1, tmp_path / "b.exe")
    session = pause.ProcessPauseSession(str(tmp_path), tmp_path / "own", "rclone.exe")
    monkeypatch.setattr(session, "_candidates", lambda: [first, second])
    monkeypatch.setattr(pause, "process_started", lambda pid: pid * 100)
    closed = []
    def close(processes):
        closed.extend(processes)
        session.cancel()
    monkeypatch.setattr(pause, "graceful_shutdown", close)
    session.prepare()
    assert closed == [first]


def test_restore_two_profiles_and_no_helper_restart(tmp_path, monkeypatch):
    first = record(10, 1, tmp_path / "Telegram.exe", '"Telegram.exe" -profile 73')
    second = record(20, 1, tmp_path / "Telegram.exe", '"Telegram.exe" -profile 29')
    helper = record(11, 10, tmp_path / "helper.exe")
    session = pause.ProcessPauseSession(str(tmp_path), tmp_path / "own", "rclone.exe")
    session.roots = pause.root_applications([first, second, helper])
    monkeypatch.setattr(pause, "process_started", lambda pid: None)
    monkeypatch.setattr(pause, "snapshot_processes", lambda: [])
    monkeypatch.setattr(pause.time, "sleep", lambda _: None)
    launches = []
    def launch(command, **kwargs):
        launches.append((command, kwargs))
        return SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(pause.subprocess, "Popen", launch)
    assert session.restore() == []
    assert [call[0] for call in launches] == [first.command_line, second.command_line]
    assert all(call[1]["cwd"] == str(tmp_path) for call in launches)
    assert all(call[1]["executable"] == str(tmp_path / "Telegram.exe") for call in launches)


def test_restore_skips_still_running_and_manually_restarted_apps(tmp_path, monkeypatch):
    first = record(10, 1, tmp_path / "a.exe")
    second = record(20, 1, tmp_path / "b.exe")
    session = pause.ProcessPauseSession(str(tmp_path), tmp_path / "own", "rclone.exe")
    session.roots = [first, second]
    monkeypatch.setattr(pause, "process_started", lambda pid: 1000 if pid == 10 else None)
    monkeypatch.setattr(pause, "snapshot_processes", lambda: [
        record(21, 1, tmp_path / "b.exe", str(tmp_path / "b.exe"))
    ])
    monkeypatch.setattr(pause.subprocess, "Popen", lambda *a, **k: pytest.fail("дубль"))
    assert session.restore() == []


def test_launch_preserves_original_launcher(tmp_path):
    launcher = tmp_path / "launcher.exe"
    launcher.touch()
    process = record(10, 1, tmp_path / "runtime.exe", f'"{launcher}" --profile "one two"')
    assert pause.launch_executable(process) == str(launcher)
    assert pause.command_arguments(process.command_line)[1:] == ("--profile", "one two")


def test_restore_failure_does_not_prevent_other_apps(tmp_path, monkeypatch):
    session = pause.ProcessPauseSession(str(tmp_path), tmp_path / "own", "rclone.exe")
    session.roots = [record(10, 1, tmp_path / "a.exe"), record(20, 1, tmp_path / "b.exe")]
    monkeypatch.setattr(pause, "process_started", lambda pid: None)
    monkeypatch.setattr(pause, "snapshot_processes", lambda: [])
    monkeypatch.setattr(pause.time, "sleep", lambda _: None)
    launches = []
    def launch(command, **kwargs):
        launches.append(command)
        if len(launches) == 1:
            raise OSError("missing")
        return SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(pause.subprocess, "Popen", launch)
    assert len(session.restore()) == 1
    assert len(launches) == 2


@pytest.fixture
def guarded_runner(qt_app, monkeypatch, tmp_path):
    events = []
    session = SimpleNamespace(
        prepare=lambda: ["Telegram.exe"],
        remaining=lambda: [],
        restore=lambda: events.append("restore") or [],
        cancel=lambda: None,
    )
    monkeypatch.setattr(runner_module, "ProcessPauseSession", lambda *args: session)
    runner = RcloneRunner()
    monkeypatch.setattr(runner.process, "start", lambda *args: events.append("rclone"))
    manual, results = [], []
    runner.manual_close_required.connect(manual.append)
    runner.command_finished.connect(lambda result: (events.append("finished"), results.append(result)))
    task = SyncTask.create(name="test", source_path=str(tmp_path), remote_path="mega:test",
                           pause_applications=True)
    yield runner, task, session, events, manual, results
    if runner.is_running:
        runner.stop()
        if runner.process.state() == runner.process.ProcessState.NotRunning and not runner._terminal_emitted:
            runner._emit_finished(exit_code=-1, crashed=False)
        wait_until(qt_app, lambda: not runner.is_running)
    runner.deleteLater()
    qt_app.processEvents()


def test_manual_close_then_sync_restores_before_completion(qt_app, guarded_runner):
    runner, task, session, events, manual, results = guarded_runner
    assert runner.run_task("rclone.exe", "config", task, False)
    wait_until(qt_app, lambda: bool(manual))
    assert runner.is_running and events == []
    assert not runner.run_task("rclone.exe", "config", task, False)
    runner.retry_manual_close()
    wait_until(qt_app, lambda: events == ["rclone"])
    runner._emit_finished(exit_code=0, crashed=False)
    wait_until(qt_app, lambda: bool(results))
    assert events == ["rclone", "restore", "finished"]
    assert results[0]["success"] and not runner.is_running


def test_cancel_manual_wait_restores_without_sync(qt_app, guarded_runner):
    runner, task, session, events, manual, results = guarded_runner
    runner.run_task("rclone.exe", "config", task, False)
    wait_until(qt_app, lambda: bool(manual))
    runner.stop()
    wait_until(qt_app, lambda: bool(results))
    assert events == ["restore", "finished"]
    assert results[0]["stopped_by_user"]


@pytest.mark.parametrize("code,crashed", [(1, False), (-1, True)])
def test_rclone_error_restores_apps(qt_app, guarded_runner, code, crashed):
    runner, task, session, events, manual, results = guarded_runner
    session.prepare = lambda: []
    runner.run_task("rclone.exe", "config", task, False)
    wait_until(qt_app, lambda: events == ["rclone"])
    runner._emit_finished(exit_code=code, crashed=crashed)
    wait_until(qt_app, lambda: bool(results))
    assert events == ["rclone", "restore", "finished"]
    assert not results[0]["success"]


def test_cancel_during_prepare_waits_and_restores(qt_app, guarded_runner):
    runner, task, session, events, manual, results = guarded_runner
    release = threading.Event()
    session.prepare = lambda: release.wait(2) and []
    runner.run_task("rclone.exe", "config", task, False)
    runner.stop()
    assert runner.is_running
    release.set()
    wait_until(qt_app, lambda: bool(results))
    assert events == ["restore", "finished"]


def test_prepare_exception_after_partial_close_restores(qt_app, guarded_runner):
    runner, task, session, events, manual, results = guarded_runner
    def prepare():
        raise RuntimeError("partial close")
    session.prepare = prepare
    runner.run_task("rclone.exe", "config", task, False)
    wait_until(qt_app, lambda: bool(results))
    assert events == ["restore", "finished"]
    assert "partial close" in results[0]["summary"]


def test_restoration_errors_are_reported(qt_app, guarded_runner):
    runner, task, session, events, manual, results = guarded_runner
    session.prepare = lambda: []
    session.restore = lambda: ["Telegram.exe: missing"]
    runner.run_task("rclone.exe", "config", task, False)
    wait_until(qt_app, lambda: events == ["rclone"])
    runner._emit_finished(exit_code=0, crashed=False)
    wait_until(qt_app, lambda: bool(results))
    assert not results[0]["success"]
    assert "Telegram.exe" in results[0]["summary"]


def test_runner_stays_busy_until_restoration_finishes(qt_app, guarded_runner):
    runner, task, session, events, manual, results = guarded_runner
    session.prepare = lambda: []
    release = threading.Event()
    session.restore = lambda: release.wait(2) and []
    runner.run_task("rclone.exe", "config", task, False)
    wait_until(qt_app, lambda: events == ["rclone"])
    runner._emit_finished(exit_code=0, crashed=False)
    try:
        assert runner.is_running and not results
        assert not runner.run_task("rclone.exe", "config", task, False)
    finally:
        release.set()
    wait_until(qt_app, lambda: bool(results))
    assert not runner.is_running


def test_real_failed_to_start_restores(qt_app, monkeypatch, tmp_path):
    events, results = [], []
    session = SimpleNamespace(prepare=lambda: [], restore=lambda: events.append("restore") or [],
                              cancel=lambda: None)
    monkeypatch.setattr(runner_module, "ProcessPauseSession", lambda *args: session)
    runner = RcloneRunner()
    runner.command_finished.connect(results.append)
    task = SyncTask.create(name="test", source_path=str(tmp_path), remote_path="mega:test",
                           pause_applications=True)
    runner.run_task(str(tmp_path / "missing-rclone.exe"), "config", task, False)
    wait_until(qt_app, lambda: bool(results))
    assert events == ["restore"] and not results[0]["success"]
    assert results[0]["exit_code"] == -1
    assert not runner.is_running
    runner.deleteLater()


def test_dry_run_never_pauses_apps(qt_app, guarded_runner):
    runner, task, session, events, manual, results = guarded_runner
    session.prepare = lambda: pytest.fail("закрытие на dry-run")
    runner.run_task("rclone.exe", "config", task, True)
    runner._emit_finished(exit_code=0, crashed=False)
    assert events == ["rclone", "finished"]
    assert not manual


def test_model_and_dialog_preserve_option(qt_app, tmp_path):
    task = SyncTask.create(name="t", source_path=str(tmp_path), remote_path="mega:test")
    assert not SyncTask.from_dict(task.to_dict()).pause_applications
    signature = task.operational_signature()
    dialog = TaskDialog(task, remote_names=["mega"])
    dialog.pause_applications_checkbox.setChecked(True)
    updated = dialog.build_task(task)
    assert updated.pause_applications
    assert SyncTask.from_dict(updated.to_dict()).pause_applications
    assert updated.operational_signature() != signature
    dialog.deleteLater()


@pytest.fixture
def pause_window(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr(MainWindow, "_create_tray_icon", lambda self: setattr(self, "tray_icon", None))
    window = MainWindow(SettingsStore(tmp_path / "settings.json"))
    window.scheduler_timer.stop()
    yield window
    window._geometry_save_timer.stop()
    window.deleteLater()
    qt_app.processEvents()


@pytest.mark.parametrize("button,expected", [("Повторить", "retry"), ("Отмена", "stop")])
def test_manual_close_dialog_names_app_and_handles_choice(pause_window, qt_app, button, expected):
    events = []
    pause_window.runner = SimpleNamespace(retry_manual_close=lambda: events.append("retry"),
                                         stop=lambda: events.append("stop"))
    pause_window.command_queue.append({"kind": "task"})
    def click():
        dialog = qt_app.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        assert "Telegram.exe" in dialog.informativeText()
        next(b for b in dialog.buttons() if b.text() == button).click()
    QTimer.singleShot(0, click)
    pause_window._request_manual_close(["Telegram.exe — portable"])
    assert events == [expected]
    if expected == "stop":
        assert pause_window.command_queue == []


def test_window_exit_waits_for_restoration(pause_window, monkeypatch):
    stopped = []
    pause_window.runner = SimpleNamespace(is_running=True, stop=lambda: stopped.append(True))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    event = QCloseEvent()
    pause_window.closeEvent(event)
    assert not event.isAccepted()
    assert pause_window._close_after_stop and stopped == [True]


def test_global_setting_persists_without_changing_tasks(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    assert not store.get_pause_applications()
    task = SyncTask.create(name="t", source_path=str(tmp_path), remote_path="mega:test")
    store.set_tasks_data([task.to_dict()])
    store.set_pause_applications(True)
    store.save()
    restored = SettingsStore(path)
    assert restored.get_pause_applications()
    assert restored.get_tasks_data() == [task.to_dict()]
    restored.set_pause_applications(False)
    restored.save()
    assert not SettingsStore(path).get_pause_applications()


@pytest.mark.parametrize("global_mode,task_mode,dry_run,expected", [
    (True, False, False, True),
    (True, False, True, False),
    (False, True, False, True),
    (False, False, False, False),
])
def test_runner_combines_global_and_task_only_for_sync(
    qt_app, tmp_path, monkeypatch, global_mode, task_mode, dry_run, expected
):
    runner = RcloneRunner()
    runner.pause_all_applications = global_mode
    task = SyncTask.create(name="t", source_path=str(tmp_path), remote_path="mega:test",
                           pause_applications=task_mode)
    metadata = []
    monkeypatch.setattr(runner, "_start", lambda exe, args, meta: metadata.append(meta) or True)
    assert runner.run_task("fake-rclone", "config", task, dry_run)
    assert metadata[0]["pause_applications"] is expected
    assert task.pause_applications is task_mode
    runner.deleteLater()


def test_global_checkbox_saves_and_loads(pause_window):
    assert not pause_window.pause_applications_checkbox.isChecked()
    pause_window.pause_applications_checkbox.setChecked(True)
    assert SettingsStore(pause_window.settings_store.path).get_pause_applications()
    pause_window._load_settings_into_ui()
    assert pause_window.pause_applications_checkbox.isChecked()
    pause_window.pause_applications_checkbox.setChecked(False)
    assert not SettingsStore(pause_window.settings_store.path).get_pause_applications()


def test_queue_applies_global_setting_to_task_run(pause_window, tmp_path, monkeypatch):
    task = SyncTask.create(name="t", source_path=str(tmp_path), remote_path="mega:test")
    pause_window.tasks = [task]
    pause_window.pause_applications_checkbox.setChecked(True)
    runs = []
    fake = SimpleNamespace(is_running=False)
    fake.run_task = lambda exe, config, current, dry: runs.append(
        (fake.pause_all_applications, current.pause_applications, dry)
    )
    pause_window.runner = fake
    monkeypatch.setattr(pause_window, "_current_rclone_path", lambda: "fake-rclone")
    for dry_run in (False, True):
        pause_window.command_queue.append({"kind": "task", "task_id": task.id,
                                          "dry_run": dry_run})
        pause_window._start_next_queued_command()
    assert runs == [(True, False, False), (True, False, True)]
