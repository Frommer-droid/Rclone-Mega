"""Account filtering and sequential batch approval without cloud operations."""

import pytest
from types import SimpleNamespace
from PySide6.QtCore import QPoint, Qt
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
