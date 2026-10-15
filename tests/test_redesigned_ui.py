"""Regression coverage for compact layouts and keyboard task operations."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton

from app.core.settings_store import SettingsStore
from app.models.sync_task import SyncTask
from app.ui.main_window import MainWindow
from app.ui.task_dialog import TaskDialog
from app.ui.theme import apply_theme


def test_compact_window_keeps_names_and_actions_reachable(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    monkeypatch.setattr(MainWindow, "_create_tray_icon",
                        lambda self: setattr(self, "tray_icon", None))
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["personal"])
    task = SyncTask.create(name="Рабочие документы", source_path=str(tmp_path),
                           remote_path="personal:Documents")
    store.set_tasks_data([task.to_dict()])
    window = MainWindow(store)
    window.scheduler_timer.stop()
    window.resize(1024, 700)
    window.show()
    app.processEvents()
    assert window.width() == 1024
    assert window.table.columnWidth(1) >= window.table.fontMetrics().horizontalAdvance(task.name) + 16
    assert window.table.horizontalScrollBar().maximum() == 0
    assert "Рабочие документы" in window.table.item(0, 1).toolTip()
    actions = window.table.cellWidget(0, 7).findChildren(QToolButton)
    assert all(button.width() >= round(32 * window._ui_scale_factor)
               and button.height() >= round(32 * window._ui_scale_factor) for button in actions), [
                   (button.width(), button.height(), window._ui_scale_factor) for button in actions]
    calls = []
    monkeypatch.setattr(window, "_check_task", calls.append)
    actions[0].setFocus()
    QTest.keyClick(actions[0], Qt.Key.Key_Space)
    assert calls == [task.id]
    window.resize(1500, 800)
    app.processEvents()
    assert not window.table.isColumnHidden(4)
    assert window.table.item(0, 0).data(Qt.ItemDataRole.UserRole) == task.id
    window.close()
    window.deleteLater()
    app.processEvents()


def test_tabbed_editor_preserves_unvisited_safety_and_filter_settings(tmp_path):
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    task = SyncTask.create(
        name="Documents", source_path=str(tmp_path), remote_path="personal:Documents",
        dry_run_first=True, pause_applications=True, hard_delete=True,
        use_backup_dir=True, backup_dir="personal:Previous",
        interval_minutes=1500, scheduled_time="10:30", interval_paused=True,
        excludes=["*.tmp"], filter_rules=["+ /Work/**", "- /**"],
    )
    dialog = TaskDialog(task, remote_names=["personal"])
    dialog.show()
    app.processEvents()
    dialog.name_edit.setText("Renamed")
    # Saving only the first tab must preserve fields on every other tab.
    rebuilt = dialog.build_task(task)
    expected = task.to_dict()
    expected["name"] = "Renamed"
    assert rebuilt.to_dict() == expected
    dialog.tabs.setCurrentIndex(2)
    app.processEvents()
    assert dialog.hard_delete_checkbox.isVisible()
    assert dialog.backup_edit.isEnabled()
    dialog.reject()
    dialog.deleteLater()
    app.processEvents()
