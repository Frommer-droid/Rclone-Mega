"""Account filtering and sequential batch approval without cloud operations."""

import pytest
from types import SimpleNamespace
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core.settings_store import SettingsStore
from app.models.sync_task import SyncTask
from app.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr(
        MainWindow, "_create_tray_icon", lambda self: setattr(self, "tray_icon", None)
    )
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["first", "second"])
    store.set_selected_remote("second")
    store.set_tasks_data(
        [
            SyncTask(
                id="one",
                name="One",
                source_path=str(tmp_path),
                remote_path="first:Backup/One",
            ).to_dict(),
            SyncTask(
                id="two",
                name="Two",
                source_path=str(tmp_path),
                remote_path="second:Backup/Two",
            ).to_dict(),
            SyncTask(
                name="Three",
                id="three",
                source_path=str(tmp_path),
                remote_path="first:Backup/Three",
            ).to_dict(),
            SyncTask(
                name="Disabled",
                id="disabled",
                source_path=str(tmp_path),
                remote_path="second:Backup/Disabled",
                enabled=False,
            ).to_dict(),
        ]
    )
    widget = MainWindow(store)
    widget.scheduler_timer.stop()
    monkeypatch.setattr(widget, "_start_next_queued_command", lambda: None)
    yield widget
    widget._geometry_save_timer.stop()
    widget.deleteLater()
    qt_app.processEvents()


def test_overview_default_and_account_column(window):
    assert window.remote_combo.currentText() == "Все аккаунты"
    assert window.table.rowCount() == 4
    assert window.table.item(1, 2).text() == "second"
    assert window.table.item(1, 2).toolTip() == "second:Backup/Two"
    assert window._current_remote_name() == ""
    assert window.settings_store.get_selected_remote() == "second"


def table_task_ids(window):
    return [
        window.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        for row in range(window.table.rowCount())
    ]


def test_dragging_column_preserves_width_after_refresh_and_reopen(window, qt_app):
    window.resize(1280, 760)
    window.show()
    qt_app.processEvents()
    header = window.table.horizontalHeader()
    original = header.sectionSize(1)
    edge = header.sectionViewportPosition(1) + original - 1
    position = QPoint(edge, header.height() // 2)
    QTest.mousePress(header.viewport(), Qt.MouseButton.LeftButton, pos=position)
    QTest.mouseMove(header.viewport(), position + QPoint(70, 0))
    QTest.mouseRelease(header.viewport(), Qt.MouseButton.LeftButton,
                       pos=position + QPoint(70, 0))
    qt_app.processEvents()
    resized = header.sectionSize(1)
    assert resized >= original + 60
    window._refresh_table()
    assert header.sectionSize(1) == resized
    window._save_geometry()
    reopened = MainWindow(SettingsStore(window.settings_store.path))
    reopened.scheduler_timer.stop()
    reopened.show()
    qt_app.processEvents()
    assert reopened._task_column_widths == window._task_column_widths
    # Qt may clamp a restored window to a smaller test screen. Compare pixels
    # at the same viewport; at other widths the saved proportions must reflow.
    reopened.resize(window.size())
    qt_app.processEvents()
    assert abs(reopened.table.columnWidth(1) - resized) <= 2, {
        "original": window._task_column_widths, "reopened": reopened._task_column_widths,
        "viewport": (window.table.viewport().width(), reopened.table.viewport().width()),
        "factor": (window._ui_scale_factor, reopened._ui_scale_factor),
    }
    assert reopened.table.horizontalHeader().length() == reopened.table.viewport().width()
    reopened.deleteLater()
    qt_app.processEvents()


def test_autofit_shrinks_oversized_column_and_keeps_hidden_width(window, qt_app):
    window.resize(round(1000 * window._ui_scale_factor), 700)
    window.show()
    qt_app.processEvents()
    window.table.setColumnWidth(1, 700)
    original_ids = table_task_ids(window)
    window.fit_columns_button.click()
    assert 36 <= window.table.columnWidth(1) < 700
    assert table_task_ids(window) == original_ids
    assert window.table.columnWidth(7) == round(156 * window._ui_scale_factor)
    assert window.table.isColumnHidden(4)
    saved = dict(window.settings_store.get_window_settings()["task_column_widths"])
    window.resize(1500, 800)
    qt_app.processEvents()
    assert not window.table.isColumnHidden(4)
    assert window.table.horizontalHeader().length() == window.table.viewport().width()
    assert window._task_column_widths["4"] == saved["4"]
    assert all(value >= 36 for value in saved.values())


def test_autofit_sizes_window_to_contents_and_is_repeatable(window, qt_app, monkeypatch):
    window.tasks[0].name = "D — Локальные резервные копии"
    window.tasks[1].last_status = "Требуется проверка"
    window.tasks[0].last_run_finished_at = "2026-10-15T08:03:00"
    window._refresh_table()
    window.resize(2100, 760)
    window.show()
    qt_app.processEvents()
    monkeypatch.setattr(window, "screen", lambda: SimpleNamespace(
        availableGeometry=lambda: QRect(0, 0, 2800, 1600)
    ))
    height = window.height()
    window.fit_columns_button.click()
    qt_app.processEvents()
    fitted = window.width()
    assert fitted < 1600
    assert window.height() == height
    assert all(not window.table.isColumnHidden(c) for c in range(8))
    for c in range(1, 7):
        preferred = round(window._task_column_widths[str(c)] * window._ui_scale_factor)
        assert abs(window.table.columnWidth(c) - preferred) <= 2
    assert window.table.horizontalHeader().length() == window.table.viewport().width()
    window.fit_columns_button.click()
    qt_app.processEvents()
    assert abs(window.width() - fitted) <= 2
    window.table.setColumnWidth(1, window.table.columnWidth(1) + 35)
    assert window.width() == fitted
    assert window.table.horizontalHeader().length() == window.table.viewport().width()
    assert window.settings_store.get_window_settings()["task_columns_fit_content"]


def test_autofit_respects_screen_when_content_is_too_wide(window, qt_app, monkeypatch):
    window.tasks[0].name = "Очень длинное имя задачи " * 30
    window._refresh_table()
    window.resize(1500, 700)
    window.show()
    qt_app.processEvents()
    monkeypatch.setattr(window, "screen", lambda: SimpleNamespace(
        availableGeometry=lambda: QRect(0, 0, 1000, 1000)
    ))
    window.fit_columns_button.click()
    qt_app.processEvents()
    assert window.frameGeometry().width() <= 1000
    assert window.table.horizontalHeader().length() == window.table.viewport().width()


@pytest.mark.parametrize("saved", [None, [], {}, {"1": True}, {str(c): -1 for c in range(1, 7)}])
def test_invalid_saved_column_widths_fall_back_to_content(window, saved):
    window.settings_store.get_window_settings()["task_column_widths"] = saved
    window._restore_task_column_widths()
    assert window.table.columnWidth(1) >= 36
    assert len(window._task_column_widths) == 6


@pytest.mark.parametrize("column", [1, 2, 4, 6])
def test_text_column_sorting_toggles_and_preserves_task_order(window, column):
    window.tasks[0].last_mode = "sync"
    window.tasks[1].last_mode = "dry-run"
    window.tasks[0].last_status = "Успешно"
    window.tasks[1].last_status = "Ошибка"
    window._refresh_table()
    original_ids = [task.id for task in window.tasks]
    labels = {
        window.table.item(row, 0).data(Qt.ItemDataRole.UserRole):
        window.table.item(row, column).text().casefold()
        for row in range(window.table.rowCount())
    }
    for reverse in (False, True):
        window.table.horizontalHeader().sectionClicked.emit(column)
        assert table_task_ids(window) == sorted(
            original_ids, key=labels.get, reverse=reverse
        )
        assert [task.id for task in window.tasks] == original_ids
    assert window.table.horizontalHeader().isSortIndicatorShown()
    assert window.table.horizontalHeader().sortIndicatorSection() == column
    assert (
        window.table.horizontalHeader().sortIndicatorOrder()
        == Qt.SortOrder.DescendingOrder
    )


def test_date_sorting_uses_chronology_instead_of_display_text(window):
    for task, timestamp in zip(
        window.tasks,
        ["2026-11-01T08:00:00", "2026-10-09T08:00:00",
         "2025-12-31T23:00:00", "2026-10-09T07:00:00"],
    ):
        task.last_run_finished_at = timestamp
    window._on_table_header_clicked(3)
    assert table_task_ids(window) == ["three", "disabled", "two", "one"]
    window._on_table_header_clicked(3)
    assert table_task_ids(window) == ["one", "two", "disabled", "three"]
    window.tasks[0].last_run_finished_at = ""
    window.tasks[1].last_run_finished_at = "invalid"
    window._refresh_table()  # Пустые/старые некорректные даты не ломают таблицу.
    assert window.table.rowCount() == 4


def test_next_attempt_sorting_handles_dates_and_schedule_states(window):
    for task in window.tasks:
        task.enabled = True
        task.interval_minutes = 60
    window.tasks[0].last_run_finished_at = "2099-11-01T08:00:00"
    window.tasks[1].last_run_finished_at = "2099-10-09T08:00:00"
    window.tasks[2].last_run_finished_at = "2020-01-01T08:00:00"
    window.tasks[3].enabled = False
    window._on_table_header_clicked(5)
    assert table_task_ids(window) == ["three", "two", "one", "disabled"]
    window._on_table_header_clicked(5)
    assert table_task_ids(window) == ["disabled", "one", "two", "three"]


def test_sorted_rows_preserve_selection_buttons_checkboxes_and_filter(window, monkeypatch):
    window._select_task_by_id("two")
    window._on_table_header_clicked(1)
    assert window._selected_task_id() == "two"
    calls = []
    monkeypatch.setattr(window, "_check_task", calls.append)
    row = table_task_ids(window).index("three")
    window.table.cellWidget(row, 7).layout().itemAt(0).widget().click()
    assert calls == ["three"]
    window.table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
    assert not window._find_task("three").enabled
    assert window._find_task("two").enabled
    window._refresh_table()
    assert table_task_ids(window) == ["disabled", "one", "three", "two"]
    assert window._selected_task_id() == "two"
    window.remote_combo.setCurrentText("second")
    assert table_task_ids(window) == ["disabled", "two"]
    window.table.horizontalHeader().sectionClicked.emit(0)
    assert all(task.enabled for task in window._visible_tasks())
    assert window._task_sort_column == 1
    window.table.horizontalHeader().sectionClicked.emit(7)
    assert window._task_sort_column == 1


def test_real_header_click_changes_sort_direction(window, qt_app):
    window.show()
    qt_app.processEvents()
    header = window.table.horizontalHeader()
    x = header.sectionViewportPosition(1) + header.sectionSize(1) // 2
    QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(x, 10))
    assert table_task_ids(window) == ["disabled", "one", "three", "two"]
    QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(x, 10))
    assert table_task_ids(window) == ["two", "three", "one", "disabled"]
    window.hide()


def test_account_filter_persists_without_fake_remote(window):
    window.remote_combo.setCurrentText("second")
    assert [task.name for task in window._visible_tasks()] == ["Two", "Disabled"]
    assert window.sync_all_button.text() == "Зеркалировать аккаунт"
    reloaded = SettingsStore(window.settings_store.path)
    assert reloaded.settings["show_all_accounts"] is False
    window._set_remote_combo_items(
        reloaded.get_remote_names(), reloaded.get_selected_remote()
    )
    assert window.remote_combo.currentText() == "second"
    window.remote_combo.setCurrentIndex(0)
    window._save_runtime_state()
    reloaded = SettingsStore(window.settings_store.path)
    assert reloaded.settings["show_all_accounts"] is True
    assert reloaded.get_remote_names() == ["first", "second"]
    assert reloaded.get_selected_remote() == "second"


def test_batch_groups_accounts_and_checks_before_shared_approval(window):
    window._sync_all_tasks()
    tasks = [window._find_task(item["task_id"]).name for item in window.command_queue]
    assert tasks == ["One", "Three", "Two"]
    assert all(
        item["dry_run"] and item["scheduled_confirmation"]
        for item in window.command_queue
    )
    window._sync_all_tasks()
    assert len(window.command_queue) == 3


def test_filtered_batch_excludes_other_accounts_and_disabled_tasks(window):
    window.remote_combo.setCurrentText("second")
    window._sync_all_tasks()
    assert [item["task_id"] for item in window.command_queue] == [window.tasks[1].id]


def test_checks_reach_all_accounts_and_ignore_late_quota(window):
    window._run_mega_check()
    assert [item["args"] for item in window.command_queue] == [
        ["about", "first:"],
        ["about", "second:"],
    ]
    before = window.remote_quota_bar.format()
    window._handle_remote_quota_result(
        {
            "args": ["about", "second:", "--json"],
            "success": True,
            "output": '{"used": 1, "total": 100}',
        }
    )
    assert window.remote_quota_bar.format() == before


def test_one_shared_confirmation_enqueues_approved_sync(window, monkeypatch):
    selected = window.tasks[:2]
    for task in selected:
        task.last_status = "Ожидает подтверждения"
        task.last_change_candidates = 1
        window._queue_pending_confirmation(task)
    confirmations = []
    monkeypatch.setattr(window, "_show_window_from_notification", lambda: None)
    monkeypatch.setattr(
        window,
        "_select_tasks_for_sync",
        lambda tasks: (confirmations.append(tasks) or "sync", tasks),
    )
    window._show_pending_confirmation_if_idle()
    assert confirmations == [selected]
    assert [item["task_id"] for item in window.command_queue] == [
        task.id for task in selected
    ]
    assert all(not item["dry_run"] for item in window.command_queue)
    assert window._pending_confirmation_task_ids == []


def test_batch_completes_sequentially_after_one_confirmation(window, monkeypatch):
    runs = []
    runner = SimpleNamespace(is_running=False)

    def run_task(_executable, _config, task, dry_run):
        assert not runner.is_running
        runner.is_running = True
        runs.append((task.id, dry_run))

    runner.run_task = run_task
    monkeypatch.setattr(window, "runner", runner)
    monkeypatch.setattr(window, "_current_rclone_path", lambda: "fake-rclone")
    monkeypatch.setattr(
        window,
        "_start_next_queued_command",
        MainWindow._start_next_queued_command.__get__(window),
    )
    monkeypatch.setattr(window, "_show_window_from_notification", lambda: None)
    approvals = []
    monkeypatch.setattr(
        window,
        "_select_tasks_for_sync",
        lambda tasks: (approvals.append(list(tasks)) or "sync", tasks),
    )
    window._sync_all_tasks()
    expected_ids = [window.tasks[index].id for index in (0, 2, 1)]
    for task_id in expected_ids:
        assert runs[-1] == (task_id, True)
        runner.is_running = False
        window._on_command_finished(
            {"task_id": task_id, "success": True, "change_candidates": 1}
        )
    assert len(approvals) == 1
    for task_id in expected_ids:
        assert runs[-1] == (task_id, False)
        runner.is_running = False
        window._on_command_finished({"task_id": task_id, "success": True})
    assert runs == [
        (task_id, mode) for mode in (True, False) for task_id in expected_ids
    ]
    assert not window.command_queue


def activate_check_runner(window, monkeypatch):
    runs = []
    runner = SimpleNamespace(is_running=False)
    def run_task(_exe, _config, task, dry_run):
        assert not runner.is_running
        runner.is_running = True
        runs.append(task.id)
        window._on_command_started({"task_id": task.id, "task_name": task.name})
        return True
    runner.run_task = run_task
    runner.stop = lambda: None
    monkeypatch.setattr(window, "runner", runner)
    monkeypatch.setattr(window, "_current_rclone_path", lambda: "fake-rclone")
    monkeypatch.setattr(window, "_start_next_queued_command",
                        MainWindow._start_next_queued_command.__get__(window))
    return runner, runs


def finish_check(window, runner, task_id, success=True, stopped=False):
    runner.is_running = False
    window._on_command_finished({"task_id": task_id, "success": success,
                                 "stopped_by_user": stopped, "change_candidates": 0})


def test_check_batch_follows_display_order_and_freezes_it(window, monkeypatch):
    runner, runs = activate_check_runner(window, monkeypatch)
    window._on_table_header_clicked(1)
    window._check_all_tasks()
    assert runs == ["one"]
    assert "Проверка 1 из 3: One" == window.status_label.text()
    assert [item["task_id"] for item in window.command_queue] == ["three", "two"]
    queued_row = next(row for row in range(window.table.rowCount())
                      if window.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == "three")
    assert window.table.item(queued_row, 6).text() == "В очереди"
    window._on_table_header_clicked(1)
    window._check_all_tasks()
    assert [item["task_id"] for item in window.command_queue] == ["three", "two"]
    finish_check(window, runner, "one", success=False)
    assert runs == ["one", "three"]
    assert window.status_label.text() == "Проверка 2 из 3: Three"
    finish_check(window, runner, "three")
    finish_check(window, runner, "two")
    assert window._check_batch is None
    assert not window.command_queue
    assert "успешно 2, с ошибками 1, пропущено 0" in window.status_label.text()
    assert window.check_all_button.isEnabled()


def test_check_batch_scope_and_checked_count(window):
    assert window.check_all_button.text() == "Проверить отмеченные — 3"
    window.remote_combo.setCurrentText("second")
    assert window.check_all_button.text() == "Проверить отмеченные — 1"
    window._check_all_tasks()
    assert [item["task_id"] for item in window.command_queue] == ["two"]
    assert not window.check_all_button.isEnabled()
    window._check_all_tasks()
    assert len(window.command_queue) == 1


def test_check_batch_skips_missing_source_and_continues(window, monkeypatch, tmp_path):
    runner, runs = activate_check_runner(window, monkeypatch)
    window.tasks[0].source_path = str(tmp_path / "missing")
    window._check_all_tasks()
    assert runs == ["two"]
    finish_check(window, runner, "two")
    finish_check(window, runner, "three")
    assert "успешно 2, с ошибками 0, пропущено 1" in window.status_label.text()


def test_check_batch_skips_task_removed_after_enqueue(window, monkeypatch):
    runner, runs = activate_check_runner(window, monkeypatch)
    window._check_all_tasks()
    window.tasks = [task for task in window.tasks if task.id != "two"]
    finish_check(window, runner, "one")
    assert runs == ["one", "three"]
    finish_check(window, runner, "three")
    assert "пропущено 1" in window.status_label.text()


def test_check_batch_does_not_duplicate_existing_commands(window):
    window._enqueue_task(window.tasks[0], dry_run=True, reason="Existing check")
    window._check_all_tasks()
    assert [item["task_id"] for item in window.command_queue] == ["one", "two", "three"]
    assert window._check_batch["results"] == {"one": "skipped"}


def test_stop_all_cancels_batch_and_reports_remaining_skipped(window, monkeypatch):
    runner, runs = activate_check_runner(window, monkeypatch)
    stops = []
    runner.stop = lambda: stops.append(True)
    window._check_all_tasks()
    window._stop_all_commands()
    assert stops == [True]
    assert not window.command_queue
    finish_check(window, runner, "one", success=False, stopped=True)
    assert runs == ["one"]
    assert window._check_batch is None
    assert "успешно 0, с ошибками 0, пропущено 3" in window.status_label.text()


def test_stop_queued_check_does_not_leave_batch_pending(window, monkeypatch):
    runner, runs = activate_check_runner(window, monkeypatch)
    window._check_all_tasks()
    window._stop_task("two")
    finish_check(window, runner, "one")
    assert runs == ["one", "three"]
    finish_check(window, runner, "three")
    assert window._check_batch is None
    assert "пропущено 1" in window.status_label.text()


@pytest.mark.parametrize("diagnostic_success", [True, False])
def test_stopping_batch_during_account_diagnostic_unlocks_button(window, monkeypatch, diagnostic_success):
    runner, runs = activate_check_runner(window, monkeypatch)
    runner.is_running = True  # Startup account check occupies rclone.
    window._check_all_tasks()
    assert not window.check_all_button.isEnabled()
    assert runs == []
    window._stop_all_commands()
    assert not window.command_queue
    runner.is_running = False
    window._on_command_finished({"kind": "diagnostic", "diagnostic_name": "remote-batch-check",
                                 "success": diagnostic_success, "stopped_by_user": True,
                                 "summary": "Остановлено пользователем."})
    assert window._check_batch is None
    assert window.check_all_button.isEnabled()
    assert "пропущено 3" in window.status_label.text()
    window._check_all_tasks()
    assert runs == ["one"]


def test_missing_rclone_cancels_batch_and_unlocks_button(window, monkeypatch):
    monkeypatch.setattr(window, "_current_rclone_path", MainWindow._current_rclone_path.__get__(window))
    monkeypatch.setattr(window, "_start_next_queued_command", MainWindow._start_next_queued_command.__get__(window))
    monkeypatch.setattr("app.ui.main_window.QMessageBox.warning", lambda *args: None)
    window.rclone_path_edit.setText("missing-rclone.exe")
    window._check_all_tasks()
    assert window._check_batch is None
    assert window.check_all_button.isEnabled()
    assert "пропущено 3" in window.status_label.text()
