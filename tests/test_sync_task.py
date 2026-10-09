import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QDialogButtonBox, QScrollArea

from app.core.settings_store import SettingsStore
from app.models.sync_task import SyncTask
from app.services.rclone_config import RcloneBatchConfigResult, RcloneConfigResult
from app.services.rclone_runner import (
    DEFAULT_EXCLUDES,
    RcloneRunner,
    build_sync_args,
    with_config_args,
)
from app.ui.main_window import MainWindow
from app.ui.task_dialog import TaskDialog


def _qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_window_saves_frame_position_and_native_geometry(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    window = MainWindow(store)
    window.show()
    app.processEvents()
    window.move(30, 40)
    app.processEvents()
    position = window.pos()
    window._save_geometry()
    saved = SettingsStore(store.path).get_window_settings()
    assert (saved["x"], saved["y"]) == (position.x(), position.y())
    assert saved["geometry"] == bytes(window.saveGeometry().toBase64()).decode("ascii")
    window.scheduler_timer.stop()
    window.close()


def test_window_restores_native_geometry_before_legacy_coordinates(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    window = MainWindow(store)
    window.show()
    app.processEvents()
    window.move(10, 20)
    app.processEvents()
    window._save_geometry()
    window.scheduler_timer.stop()
    window.close()
    # Устаревшие координаты не должны переопределять сохранённую геометрию Qt.
    store.get_window_settings().update(x=5000, y=5000)
    restored = MainWindow(store)
    assert restored.pos().x() < 5000
    assert restored.pos().y() < 5000
    assert restored.settings_store.get_window_settings()["geometry"]
    restored.scheduler_timer.stop()
    restored.close()


def test_sync_task_round_trip_and_runtime_reset(tmp_path):
    task = SyncTask.create(
        name="Фото",
        source_path=str(tmp_path),
        remote_path="mega:PC/Photos",
        use_backup_dir=True,
        backup_dir="mega:_deleted/Photos",
        excludes=["Thumbs.db", "*.tmp"],
        filter_rules=[
            "+ /Soft/Allowed/**",
            "- /Soft/**",
        ],
        interval_minutes=30,
        scheduled_time="03:15",
    )
    task.last_dry_run_at = "2026-04-24T09:00:00"

    restored = SyncTask.from_dict(task.to_dict())
    assert restored.name == "Фото"
    assert restored.excludes == ["Thumbs.db", "*.tmp"]
    assert restored.filter_rules == ["+ /Soft/Allowed/**", "- /Soft/**"]
    assert restored.scheduled_time == "03:15"
    assert restored.interval_label() == "Каждые 30 мин., от 03:15"
    assert not restored.needs_first_dry_run()
    restored.last_change_details = ["aliases.ps1: отличается от облака"]
    assert SyncTask.from_dict(restored.to_dict()).last_change_details == [
        "aliases.ps1: отличается от облака"
    ]

    restored.reset_runtime_state()
    assert restored.needs_first_dry_run()
    assert restored.last_status == "Требуется проверка"


def test_build_sync_args_contains_safety_flags(tmp_path):
    task = SyncTask.create(
        name="Docs",
        source_path=str(tmp_path),
        remote_path="mega:PC/Docs",
        max_delete=15,
        use_backup_dir=True,
        backup_dir="mega:_deleted/Docs",
        excludes=["*.tmp", "Thumbs.db"],
    )

    args = build_sync_args(task, dry_run=True)

    assert args[:3] == ["sync", str(tmp_path), "mega:PC/Docs"]
    assert "--dry-run" in args
    assert "--combined" in args
    assert args[args.index("--combined") + 1] == "-"
    assert "--use-json-log" in args
    assert "-P" not in args
    assert "--stats" in args
    assert args[args.index("--stats") + 1] == "1s"
    assert "--max-delete" in args
    assert "15" in args
    assert "--backup-dir" in args
    assert "mega:_deleted/Docs" in args
    assert "--exclude" not in args
    assert args.count("--filter") == len(DEFAULT_EXCLUDES)


def test_hard_delete_defaults_and_persistence(tmp_path):
    task = SyncTask.create(
        name="Mirror", source_path=str(tmp_path), remote_path="mega:Mirror"
    )
    assert not task.hard_delete
    assert not SyncTask.from_dict({}).hard_delete
    original_signature = task.operational_signature()
    task.hard_delete = True
    assert SyncTask.from_dict(task.to_dict()).hard_delete
    assert original_signature != task.operational_signature()


def test_hard_delete_args_keep_dry_run_and_backup_behavior(tmp_path):
    task = SyncTask.create(
        name="Mirror", source_path=str(tmp_path), remote_path="mega:Mirror"
    )
    assert "--mega-hard-delete=false" in build_sync_args(task, dry_run=False)
    task.hard_delete = True
    for dry_run in (True, False):
        args = build_sync_args(task, dry_run=dry_run)
        assert "--mega-hard-delete=true" in args
        assert ("--dry-run" in args) == dry_run
        assert args[args.index("--max-delete") + 1] == "20"
    task.use_backup_dir = True
    task.backup_dir = "mega:_backup"
    args = build_sync_args(task, dry_run=False)
    assert args[args.index("--backup-dir") + 1] == task.backup_dir


def test_task_dialog_hard_delete_create_and_edit(tmp_path):
    app = _qt_app()
    dialog = TaskDialog(remote_names=["mega"])
    assert not dialog.hard_delete_checkbox.isChecked()
    dialog.name_edit.setText("Mirror")
    dialog.source_edit.setText(str(tmp_path))
    dialog.remote_edit.setText("mega:Mirror")
    dialog.hard_delete_checkbox.setChecked(True)
    created = dialog.build_task()
    assert created.hard_delete
    restored = TaskDialog(task=SyncTask.from_dict(created.to_dict()))
    assert restored.hard_delete_checkbox.isChecked()
    restored.hard_delete_checkbox.setChecked(False)
    edited = restored.build_task(existing=created)
    assert edited.id == created.id
    assert not edited.hard_delete
    assert app is not None
    dialog.close()
    restored.close()


def test_edit_task_saves_hard_delete_and_requires_rescan(tmp_path, monkeypatch):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["mega"])
    store.set_selected_remote("mega")
    task = SyncTask.create(
        name="Mirror", source_path=str(tmp_path), remote_path="mega:Mirror"
    )
    task.last_dry_run_at = "2026-10-04T10:00:00"
    store.set_tasks_data([task.to_dict()])
    window = MainWindow(store)
    window._select_task_by_id(task.id)

    def accept_with_hard_delete(dialog):
        dialog.hard_delete_checkbox.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TaskDialog, "exec", accept_with_hard_delete)
    window._edit_selected_task()
    saved = SyncTask.from_dict(store.get_tasks_data()[0])
    assert saved.hard_delete
    assert saved.needs_first_dry_run()
    assert saved.last_status == "Требуется проверка"
    assert app is not None
    window.scheduler_timer.stop()
    window.close()


def test_build_sync_args_uses_ordered_filters_when_filter_rules_are_configured(
    tmp_path,
):
    task = SyncTask.create(
        name="Docs",
        source_path=str(tmp_path),
        remote_path="mega:PC/Docs",
        excludes=["*.tmp"],
        filter_rules=[
            "+ /Soft/Allowed/**",
            "+ /Soft/AlsoAllowed/**",
        ],
    )

    args = build_sync_args(task, dry_run=True)

    assert "--exclude" not in args
    filters = [
        args[index + 1]
        for index, value in enumerate(args)
        if value == "--filter"
    ]
    assert filters == [f"- {pattern}" for pattern in DEFAULT_EXCLUDES] + [
        "+ /Soft/Allowed/**",
        "+ /Soft/AlsoAllowed/**",
        "- /**",
    ]


def test_build_sync_args_keeps_explicit_filter_excludes_without_implicit_rule(
    tmp_path,
):
    task = SyncTask.create(
        name="Docs",
        source_path=str(tmp_path),
        remote_path="mega:PC/Docs",
        filter_rules=[
            "+ /Soft/Allowed/**",
            "- /Soft/**",
        ],
    )

    args = build_sync_args(task, dry_run=True)
    filters = [
        args[index + 1]
        for index, value in enumerate(args)
        if value == "--filter"
    ]

    assert filters == [f"- {pattern}" for pattern in DEFAULT_EXCLUDES] + [
        "+ /Soft/Allowed/**",
        "- /Soft/**",
    ]


def test_with_config_args_prefixes_rclone_config_path():
    args = with_config_args(["version"], r"D:\Apps\Rclone Mega\rclone.conf")

    assert args == ["--config", r"D:\Apps\Rclone Mega\rclone.conf", "version"]


@pytest.mark.parametrize("filter_rules", [[], ["+ /**"]])
def test_builtin_excludes_with_real_rclone_sync(tmp_path, filter_rules):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    excluded = [
        "__pycache__/module.pyc", "nested/__pycache__/metadata.txt",
        "module.pyc", "nested/module.pyo",
        ".pytest_cache/result.txt", "nested/.ruff_cache/result.txt",
        "nested/.mypy_cache/result.txt", "Thumbs.db", "nested/.DS_Store",
        "nested/file.tmp", "file.temp", "nested/file.swp", "~$document.docx",
    ]
    included = [
        "app.py", "nested/document.txt", ".venv/data.txt", ".git/config",
        "build/output.txt", "dist/output.txt", "app.log", "backup.bak",
    ]
    for relative in excluded + included + ["custom.ignore"]:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source data", encoding="utf-8")
    cached_remote = target / "nested/__pycache__/old.pyc"
    cached_remote.parent.mkdir(parents=True)
    cached_remote.write_text("existing excluded file", encoding="utf-8")
    stale_remote = target / "stale.txt"
    stale_remote.write_text("old data", encoding="utf-8")
    task = SyncTask.create(
        name="Local filter check", source_path=str(source), remote_path=str(target),
        excludes=["custom.ignore"], filter_rules=filter_rules,
    )
    rclone = Path(__file__).resolve().parents[1] / "vendor/rclone/rclone.exe"
    for dry_run in (True, False):
        args = build_sync_args(task, dry_run=dry_run)
        assert "--delete-excluded" not in args
        result = subprocess.run(
            [str(rclone), "--config", str(tmp_path / "unused.conf"), *args],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        assert result.returncode == 0, result.stderr
        if dry_run:
            assert stale_remote.exists()
            assert not (target / "app.py").exists()
    assert all((target / relative).is_file() for relative in included)
    assert all(not (target / relative).exists() for relative in excluded)
    assert not (target / "custom.ignore").exists()
    assert cached_remote.read_text(encoding="utf-8") == "existing excluded file"
    assert not stale_remote.exists()


def test_interval_label_formats_days_hours_and_minutes(tmp_path):
    task = SyncTask.create(
        name="Docs",
        source_path=str(tmp_path),
        remote_path="mega:PC/Docs",
        interval_minutes=24 * 60 + 2 * 60 + 5,
    )

    assert task.interval_label() == "Каждые 1 д. 2 ч. 5 мин."


def test_next_run_uses_interval_from_last_run_when_no_time_anchor(tmp_path):
    task = SyncTask.create(
        name="Docs",
        source_path=str(tmp_path),
        remote_path="mega:PC/Docs",
        interval_minutes=30,
    )
    task.last_run_finished_at = "2026-04-28T10:00:00"

    assert task.due_run_at() == datetime(2026, 4, 28, 10, 30)
    assert task.next_run_label(datetime(2026, 4, 28, 10, 20)) == "28.04.2026 10:30"


def test_next_run_uses_configured_time_anchor(tmp_path):
    task = SyncTask.create(
        name="Docs",
        source_path=str(tmp_path),
        remote_path="mega:PC/Docs",
        interval_minutes=24 * 60,
        scheduled_time="03:00",
    )
    task.last_run_finished_at = "2026-04-28T15:00:00"

    assert task.due_run_at() == datetime(2026, 4, 29, 3, 0)
    assert task.next_run_label(datetime(2026, 4, 28, 16, 0)) == "29.04.2026 03:00"
    assert task.next_run_label(datetime(2026, 4, 29, 3, 5)) == "Сейчас"


def test_next_run_requires_first_manual_check(tmp_path):
    task = SyncTask.create(
        name="Docs",
        source_path=str(tmp_path),
        remote_path="mega:PC/Docs",
        interval_minutes=24 * 60,
        scheduled_time="03:00",
    )

    assert task.due_run_at() is None
    assert task.next_run_label(datetime(2026, 4, 28, 16, 0)) == "После первой проверки"


def test_max_delete_allows_unlimited_minus_one(tmp_path):
    task = SyncTask.create(
        name="Mirror",
        source_path=str(tmp_path),
        remote_path="mega:Mirror",
        max_delete=-1,
    )

    restored = SyncTask.from_dict(task.to_dict())
    args = build_sync_args(restored, dry_run=False)

    assert restored.max_delete == -1
    assert args[args.index("--max-delete") + 1] == "-1"


def test_max_delete_clamps_values_below_unlimited(tmp_path):
    task = SyncTask.create(
        name="Mirror",
        source_path=str(tmp_path),
        remote_path="mega:Mirror",
        max_delete=-10,
    )

    restored = SyncTask.from_dict({"max_delete": -10})

    assert task.max_delete == -1
    assert restored.max_delete == -1


def test_task_dialog_accepts_unlimited_max_delete(tmp_path):
    app = _qt_app()

    dialog = TaskDialog(remote_names=["account"], default_remote_name="account")
    dialog.name_edit.setText("Mirror")
    dialog.source_edit.setText(str(tmp_path))
    dialog.remote_edit.setText("account:Mirror")
    dialog.max_delete_spin.setValue(-1)

    task = dialog.build_task()

    assert app is not None
    assert dialog.max_delete_spin.minimum() == -1
    assert task.max_delete == -1


def test_task_dialog_accepts_non_default_remote(tmp_path):
    app = _qt_app()

    dialog = TaskDialog(remote_names=["mega", "mega_2"], default_remote_name="mega_2")
    dialog.name_edit.setText("Mirror")
    dialog.source_edit.setText(str(tmp_path))
    dialog.remote_edit.setText("mega_2:Mirror")
    dialog.backup_edit.setText("mega_2:_deleted/Mirror")
    dialog.use_backup_checkbox.setChecked(True)

    task = dialog.build_task()

    assert app is not None
    assert dialog._validate_inputs() == []
    assert task.remote_path == "mega_2:Mirror"
    assert task.backup_dir == "mega_2:_deleted/Mirror"


def test_task_dialog_remote_combo_rewrites_remote_prefix(tmp_path):
    app = _qt_app()

    dialog = TaskDialog(remote_names=["mega", "mega_2"], default_remote_name="mega")
    dialog.name_edit.setText("Mirror")
    dialog.source_edit.setText(str(tmp_path))
    dialog.remote_edit.setText("mega:Mirror")

    dialog.remote_combo.setCurrentText("mega_2")

    assert app is not None
    assert dialog.remote_edit.text() == "mega_2:Mirror"


def test_task_dialog_rejects_unconfigured_remote_in_path(tmp_path):
    app = _qt_app()

    dialog = TaskDialog(remote_names=["mega"], default_remote_name="mega")
    dialog.name_edit.setText("Mirror")
    dialog.source_edit.setText(str(tmp_path))
    dialog.remote_edit.setText("unknown:Mirror")

    assert app is not None
    assert "Выберите remote из списка настроенных подключений." in dialog._validate_inputs()


def test_task_dialog_builds_interval_from_day_hour_minute_selectors(tmp_path):
    app = _qt_app()

    dialog = TaskDialog(remote_names=["account"], default_remote_name="account")
    dialog.name_edit.setText("Mirror")
    dialog.source_edit.setText(str(tmp_path))
    dialog.remote_edit.setText("account:Mirror")
    dialog.interval_days_combo.setCurrentIndex(1)
    dialog.interval_hours_combo.setCurrentIndex(2)
    dialog.interval_minutes_combo.setCurrentIndex(3)
    dialog.scheduled_time_checkbox.setChecked(True)
    dialog.scheduled_time_edit.setTime(QTime(4, 30))

    task = dialog.build_task()

    assert app is not None
    assert task.interval_minutes == 24 * 60 + 2 * 60 + 3
    assert task.scheduled_time == "04:30"


def test_task_dialog_builds_ordered_filter_rules(tmp_path):
    app = _qt_app()

    dialog = TaskDialog(remote_names=["account"], default_remote_name="account")
    dialog.name_edit.setText("Mirror")
    dialog.source_edit.setText(str(tmp_path))
    dialog.remote_edit.setText("account:Mirror")
    dialog.filter_rules_edit.setPlainText(
        "# comment\n"
        "+ /Soft/Allowed/**\n"
        "\n"
        "- /Soft/**\n"
    )

    task = dialog.build_task()

    assert app is not None
    assert task.filter_rules == ["+ /Soft/Allowed/**", "- /Soft/**"]


def test_main_window_table_has_row_action_buttons(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["mega"])
    store.set_selected_remote("mega")
    task = SyncTask.create(
        name="Mirror",
        source_path=str(tmp_path),
        remote_path="mega:Mirror",
    )
    store.set_tasks_data([task.to_dict()])

    window = MainWindow(store)
    actions_widget = window.table.cellWidget(0, 7)
    action_buttons = actions_widget.findChildren(type(window.add_button))

    assert app is not None
    assert window.table.columnCount() == 8
    assert window.table.horizontalHeaderItem(0).text() == "☑"
    assert (
        window.table.horizontalHeaderItem(0).toolTip()
        == "Отключить все задачи в текущем списке"
    )
    assert window.table.horizontalHeaderItem(2).text() == "Аккаунт"
    assert window.table.horizontalHeaderItem(3).text() == "Запуск"
    assert window.table.horizontalHeaderItem(5).text() == "След. попытка"
    assert window.table.columnWidth(0) == 52
    assert window.table.columnWidth(3) == 142
    assert window.table.columnWidth(5) == 148
    assert window.table.columnWidth(7) == 448
    assert window.table.rowHeight(0) >= 48
    assert [button.text() for button in action_buttons] == [
        "Проверить",
        "Синхронизировать",
        "Остановить",
    ]
    window.scheduler_timer.stop()
    window.close()


def test_main_window_active_header_toggles_all_tasks(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["mega"])
    store.set_selected_remote("mega")
    first = SyncTask.create(
        name="One",
        source_path=str(tmp_path),
        remote_path="mega:One",
    )
    second = SyncTask.create(
        name="Two",
        source_path=str(tmp_path),
        remote_path="mega:Two",
        enabled=False,
    )
    store.set_tasks_data([first.to_dict(), second.to_dict()])

    window = MainWindow(store)

    window._on_table_header_clicked(0)

    assert app is not None
    assert [task.enabled for task in window.tasks] == [True, True]
    assert window.table.horizontalHeaderItem(0).text() == "☑"
    assert window.table.item(0, 0).checkState() == Qt.CheckState.Checked
    assert window.table.item(1, 0).checkState() == Qt.CheckState.Checked

    window._on_table_header_clicked(0)

    assert [task.enabled for task in window.tasks] == [False, False]
    assert window.table.horizontalHeaderItem(0).text() == "☐"
    assert window.table.item(0, 0).checkState() == Qt.CheckState.Unchecked
    assert window.table.item(1, 0).checkState() == Qt.CheckState.Unchecked
    window.scheduler_timer.stop()
    window.close()


def test_main_window_filters_tasks_by_selected_remote(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["mega", "mega_2"])
    store.set_selected_remote("mega")
    store.settings["show_all_accounts"] = False
    first = SyncTask.create(
        name="One",
        source_path=str(tmp_path),
        remote_path="mega:One",
    )
    second = SyncTask.create(
        name="Two",
        source_path=str(tmp_path),
        remote_path="mega_2:Two",
    )
    store.set_tasks_data([first.to_dict(), second.to_dict()])

    window = MainWindow(store)

    assert app is not None
    assert window.table.rowCount() == 1
    assert window.table.item(0, 1).text() == "One"

    window.remote_combo.setCurrentText("mega_2")

    assert window.table.rowCount() == 1
    assert window.table.item(0, 1).text() == "Two"
    window.scheduler_timer.stop()
    window.close()


def test_check_all_queues_only_selected_remote_tasks(tmp_path, monkeypatch):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["mega", "mega_2"])
    store.set_selected_remote("mega_2")
    store.settings["show_all_accounts"] = False
    first = SyncTask.create(
        name="One",
        source_path=str(tmp_path),
        remote_path="mega:One",
    )
    second = SyncTask.create(
        name="Two",
        source_path=str(tmp_path),
        remote_path="mega_2:Two",
    )
    store.set_tasks_data([first.to_dict(), second.to_dict()])
    window = MainWindow(store)
    monkeypatch.setattr(window, "_start_next_queued_command", lambda: None)

    window._check_all_tasks()

    assert app is not None
    assert len(window.command_queue) == 1
    assert window.command_queue[0]["task_id"] == window.tasks[1].id
    window.scheduler_timer.stop()
    window.close()


def test_main_window_keeps_rclone_details_collapsed_by_default(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")

    window = MainWindow(store)

    assert app is not None
    assert window.rclone_advanced_panel.isHidden()
    assert window.advanced_rclone_button.text() == "Дополнительно"

    window.advanced_rclone_button.setChecked(True)

    assert not window.rclone_advanced_panel.isHidden()
    assert window.advanced_rclone_button.text() == "Скрыть детали"
    window.scheduler_timer.stop()
    window.close()


def test_main_window_checks_selected_remote(tmp_path, monkeypatch):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["mega", "mega_2"])
    store.set_selected_remote("mega_2")
    store.settings["show_all_accounts"] = False
    window = MainWindow(store)
    monkeypatch.setattr(window, "_start_next_queued_command", lambda: None)

    window._run_mega_check()

    assert app is not None
    assert window.command_queue[0]["args"] == ["lsd", "mega_2:"]
    assert window.command_queue[1]["args"] == ["about", "mega_2:"]
    assert window.remote_status_label.text() == "mega_2: идёт проверка…"
    window.scheduler_timer.stop()
    window.close()


def test_main_window_queues_quota_check_for_selected_remote(tmp_path, monkeypatch):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    window = MainWindow(store)
    monkeypatch.setattr(window, "_start_next_queued_command", lambda: None)

    window._request_remote_quota("account")

    assert app is not None
    assert window.command_queue[-1]["name"] == "remote-quota"
    assert window.command_queue[-1]["args"] == ["about", "account:", "--json"]
    assert window.remote_quota_bar.format() == "Квота: проверка…"
    window.scheduler_timer.stop()
    window.close()


def test_main_window_updates_quota_progress_from_json(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["account"])
    store.set_selected_remote("account")
    store.settings["show_all_accounts"] = False
    window = MainWindow(store)

    window._handle_diagnostic_result(
        {
            "kind": "diagnostic",
            "diagnostic_name": "remote-quota",
            "success": True,
            "args": ["--config", "rclone.conf", "about", "account:", "--json"],
            "output": (
                "2026/05/01 10:00:00 NOTICE: optional log line\n"
                "{\n"
                '  "total": 53687091200,\n'
                '  "used": 26843545600,\n'
                '  "free": 26843545600\n'
                "}\n"
            ),
            "summary": "Команда завершилась успешно.",
        }
    )

    assert app is not None
    assert window.remote_quota_bar.value() == 500
    assert window.remote_quota_bar.format() == "25.0 ГБ / 50.0 ГБ (50%)"
    window.scheduler_timer.stop()
    window.close()


def test_main_window_imports_all_remotes_from_credentials_file(tmp_path, monkeypatch):
    app = _qt_app()
    credentials_path = tmp_path / "credentials.ini"
    credentials_path.write_text(
        "[first@example.com]\n"
        "password = secret1\n"
        "\n"
        "[second@example.com]\n"
        "password = secret2\n",
        encoding="utf-8",
    )
    store = SettingsStore(tmp_path / "settings.json")
    window = MainWindow(store)
    monkeypatch.setattr(window, "_current_rclone_path", lambda **_: "rclone.exe")
    monkeypatch.setattr(window, "_queue_remote_checks", lambda remote_names: None)

    def fake_configure_mega_remotes(**_kwargs):
        return RcloneBatchConfigResult(
            True,
            ["first", "second"],
            [],
            "Настроено remote: 2.",
        )

    monkeypatch.setattr(
        "app.ui.main_window.configure_mega_remotes",
        fake_configure_mega_remotes,
    )

    result = window._import_remotes_from_credentials_file(
        credentials_path,
        show_messages=False,
    )

    assert app is not None
    assert result is True
    assert "first" in store.get_remote_names()
    assert "second" in store.get_remote_names()
    assert store.get_selected_remote() == "first"
    window.scheduler_timer.stop()
    window.close()


def test_startup_check_loads_configured_remotes_and_queues_checks(
    tmp_path,
    monkeypatch,
):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    window = MainWindow(store)
    monkeypatch.setattr(window, "_current_rclone_path", lambda **_: "rclone.exe")
    monkeypatch.setattr(window, "_start_next_queued_command", lambda: None)
    monkeypatch.setattr(
        "app.ui.main_window.list_configured_remotes",
        lambda *_args: RcloneConfigResult(True, "ok", "first:\nsecond:\n"),
    )

    window._startup_check_remotes()

    assert app is not None
    assert store.get_remote_names() == ["first", "second"]
    assert [item["args"] for item in window.command_queue] == [
        ["about", "first:"],
        ["about", "second:"],
    ]
    assert window.remote_status_label.text() == "Remote: проверка 0/2"
    window.scheduler_timer.stop()
    window.close()


def test_main_window_toggles_log_panel(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")

    window = MainWindow(store)

    assert app is not None
    assert window.log_group.isHidden()
    assert window.log_toggle_button.text() == "Показать журнал"
    assert window.content_splitter.widget(0).title() == "Задачи синхронизации"

    window.log_toggle_button.setChecked(True)

    assert not window.log_group.isHidden()
    assert window.log_toggle_button.text() == "Скрыть журнал"
    assert store.get_window_settings()["log_visible"] is True

    window.log_toggle_button.setChecked(False)

    assert window.log_group.isHidden()
    assert window.log_toggle_button.text() == "Показать журнал"
    assert store.get_window_settings()["log_visible"] is False
    window.scheduler_timer.stop()
    window.close()


def test_tray_menu_hides_minimize_action_when_window_is_hidden(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    window = MainWindow(store)
    window._build_tray_menu()

    window.show()
    app.processEvents()
    window._update_tray_menu()

    assert app is not None
    assert window.tray_hide_action.isVisible()

    window.hide()
    app.processEvents()
    window._update_tray_menu()

    assert not window.tray_hide_action.isVisible()
    window.scheduler_timer.stop()
    window.close()


def test_main_window_log_panel_opens_without_shrinking_tasks(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    window = MainWindow(store)
    window.resize(1000, 680)
    window.show()
    app.processEvents()
    task_height = window.content_splitter.sizes()[0]
    window_height = window.height()

    window.log_toggle_button.setChecked(True)
    app.processEvents()

    assert app is not None
    assert abs(window.content_splitter.sizes()[0] - task_height) <= 2
    assert window.height() > window_height
    assert not window.log_group.isHidden()
    window.scheduler_timer.stop()
    window.close()


def test_main_window_restores_visible_log_panel(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    window_settings = store.get_window_settings()
    window_settings["log_visible"] = True
    window_settings["content_splitter_sizes"] = [500, 220]
    store.save()

    window = MainWindow(store)

    assert app is not None
    assert not window.log_group.isHidden()
    assert window.log_toggle_button.isChecked()
    assert window.log_toggle_button.text() == "Скрыть журнал"
    window.scheduler_timer.stop()
    window.close()


def test_task_dialog_can_pause_and_resume_interval(tmp_path):
    app = _qt_app()

    dialog = TaskDialog(remote_names=["account"], default_remote_name="account")
    dialog.name_edit.setText("Mirror")
    dialog.source_edit.setText(str(tmp_path))
    dialog.remote_edit.setText("account:Mirror")
    dialog.interval_days_combo.setCurrentIndex(1)

    dialog._pause_interval()
    paused = dialog.build_task()
    dialog._resume_interval()
    resumed = dialog.build_task()

    assert app is not None
    assert paused.interval_minutes == 24 * 60
    assert paused.interval_paused is True
    assert resumed.interval_minutes == 24 * 60
    assert resumed.interval_paused is False


def test_check_all_queues_dry_run_for_all_enabled_tasks(tmp_path, monkeypatch):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["mega"])
    store.set_selected_remote("mega")
    first = SyncTask.create(
        name="One",
        source_path=str(tmp_path),
        remote_path="mega:One",
    )
    second = SyncTask.create(
        name="Two",
        source_path=str(tmp_path),
        remote_path="mega:Two",
    )
    store.set_tasks_data([first.to_dict(), second.to_dict()])
    window = MainWindow(store)
    monkeypatch.setattr(window, "_start_next_queued_command", lambda: None)

    window._check_all_tasks()

    assert app is not None
    assert len(window.command_queue) == 2
    assert all(item["dry_run"] is True for item in window.command_queue)
    assert all(item["scheduled_confirmation"] is True for item in window.command_queue)
    window.scheduler_timer.stop()
    window.close()


def test_check_task_queues_confirmable_dry_run(tmp_path, monkeypatch):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["mega"])
    store.set_selected_remote("mega")
    task = SyncTask.create(
        name="Mirror",
        source_path=str(tmp_path),
        remote_path="mega:Mirror",
    )
    store.set_tasks_data([task.to_dict()])
    window = MainWindow(store)
    monkeypatch.setattr(window, "_start_next_queued_command", lambda: None)

    window._check_task(window.tasks[0].id)

    assert app is not None
    assert len(window.command_queue) == 1
    assert window.command_queue[0]["dry_run"] is True
    assert window.command_queue[0]["scheduled_confirmation"] is True
    window.scheduler_timer.stop()
    window.close()


def test_scheduler_queues_dry_run_for_interval_confirmation(tmp_path, monkeypatch):
    app = _qt_app()
    settings_path = tmp_path / "settings.json"
    store = SettingsStore(settings_path)
    store.set_remote_names(["mega"])
    store.set_selected_remote("mega")
    task = SyncTask.create(
        name="Mirror",
        source_path=str(tmp_path),
        remote_path="mega:Mirror",
        interval_minutes=1,
    )
    last_run = (datetime.now() - timedelta(minutes=2)).isoformat(timespec="seconds")
    task.last_run_finished_at = last_run
    task.last_dry_run_at = last_run
    store.set_tasks_data([task.to_dict()])

    window = MainWindow(store)
    monkeypatch.setattr(window, "_start_next_queued_command", lambda: None)

    window._check_due_tasks()

    assert app is not None
    assert len(window.command_queue) == 1
    assert window.command_queue[0]["dry_run"] is True
    assert window.command_queue[0]["scheduled_confirmation"] is True
    window.scheduler_timer.stop()
    window.close()


def test_scheduler_queues_dry_run_for_configured_time(tmp_path, monkeypatch):
    app = _qt_app()
    settings_path = tmp_path / "settings.json"
    store = SettingsStore(settings_path)
    store.set_remote_names(["mega"])
    store.set_selected_remote("mega")
    now = datetime.now()
    task = SyncTask.create(
        name="Mirror",
        source_path=str(tmp_path),
        remote_path="mega:Mirror",
        interval_minutes=24 * 60,
        scheduled_time=(now - timedelta(minutes=10)).strftime("%H:%M"),
    )
    last_run = (now - timedelta(days=1, hours=1)).isoformat(timespec="seconds")
    task.last_run_finished_at = last_run
    task.last_dry_run_at = last_run
    store.set_tasks_data([task.to_dict()])

    window = MainWindow(store)
    monkeypatch.setattr(window, "_start_next_queued_command", lambda: None)

    window._check_due_tasks()

    assert app is not None
    assert len(window.command_queue) == 1
    assert window.command_queue[0]["dry_run"] is True
    assert window.command_queue[0]["scheduled_confirmation"] is True
    window.scheduler_timer.stop()
    window.close()


def test_scheduler_skips_temporarily_paused_interval(tmp_path, monkeypatch):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["mega"])
    store.set_selected_remote("mega")
    task = SyncTask.create(
        name="Mirror",
        source_path=str(tmp_path),
        remote_path="mega:Mirror",
        interval_minutes=1,
        interval_paused=True,
    )
    last_run = (datetime.now() - timedelta(minutes=2)).isoformat(timespec="seconds")
    task.last_run_finished_at = last_run
    task.last_dry_run_at = last_run
    store.set_tasks_data([task.to_dict()])
    window = MainWindow(store)
    monkeypatch.setattr(window, "_start_next_queued_command", lambda: None)

    window._check_due_tasks()

    assert app is not None
    assert window.command_queue == []
    window.scheduler_timer.stop()
    window.close()


def test_scheduled_dry_run_without_changes_does_not_request_confirmation(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["mega"])
    store.set_selected_remote("mega")
    task = SyncTask.create(
        name="Mirror",
        source_path=str(tmp_path),
        remote_path="mega:Mirror",
    )
    store.set_tasks_data([task.to_dict()])
    window = MainWindow(store)
    task = window.tasks[0]
    task.last_mode = "dry-run"
    window._scheduled_confirmation_task_ids.add(task.id)

    window._handle_task_result(
        {
            "task_id": task.id,
            "success": True,
            "delete_candidates": 0,
            "change_candidates": 0,
            "summary": "Команда завершилась успешно.",
        }
    )

    assert app is not None
    assert task.last_status == "Без изменений"
    assert window._pending_confirmation_task_ids == []
    window.scheduler_timer.stop()
    window.close()


def test_failed_dry_run_is_not_reported_as_no_changes(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    task = SyncTask.create(
        name="Mirror",
        source_path=str(tmp_path),
        remote_path="mega:Mirror",
    )
    store.set_tasks_data([task.to_dict()])
    window = MainWindow(store)
    task = window.tasks[0]
    task.last_mode = "dry-run"

    window._handle_task_result(
        {
            "task_id": task.id,
            "success": False,
            "delete_candidates": 0,
            "change_candidates": 0,
            "summary": "rclone: missing config",
        }
    )

    assert app is not None
    assert task.last_status == "Ошибка"
    assert task.last_error == "rclone: missing config"
    assert "не нашёл изменений" not in window.log_view.toPlainText()
    window.scheduler_timer.stop()
    window.close()


def test_manual_dry_run_with_changes_requests_confirmation(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["mega"])
    store.set_selected_remote("mega")
    task = SyncTask.create(
        name="Mirror",
        source_path=str(tmp_path),
        remote_path="mega:Mirror",
    )
    store.set_tasks_data([task.to_dict()])
    window = MainWindow(store)
    task = window.tasks[0]
    task.last_mode = "dry-run"
    window._scheduled_confirmation_task_ids.add(task.id)

    window._handle_task_result(
        {
            "task_id": task.id,
            "success": True,
            "delete_candidates": 0,
            "change_candidates": 2,
            "summary": "Команда завершилась успешно.",
            "change_details": ["aliases.ps1: отличается от облака"],
        }
    )

    assert app is not None
    assert task.last_status == "Ожидает подтверждения"
    assert task.last_change_details == ["aliases.ps1: отличается от облака"]
    assert window._pending_confirmation_task_ids == [task.id]
    window.scheduler_timer.stop()
    window.close()


def test_pending_confirmation_enqueues_selected_sync_tasks(tmp_path, monkeypatch):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["mega"])
    store.set_selected_remote("mega")
    first = SyncTask.create(
        name="One",
        source_path=str(tmp_path),
        remote_path="mega:One",
    )
    second = SyncTask.create(
        name="Two",
        source_path=str(tmp_path),
        remote_path="mega:Two",
    )
    store.set_tasks_data([first.to_dict(), second.to_dict()])
    window = MainWindow(store)
    for task in window.tasks:
        task.last_status = "Ожидает подтверждения"
        task.last_change_candidates = 1
        window._pending_confirmation_task_ids.append(task.id)

    monkeypatch.setattr(window, "_select_tasks_for_sync", lambda tasks: ("sync", list(tasks)))
    monkeypatch.setattr(window, "_start_next_queued_command", lambda: None)

    window._show_pending_confirmation_if_idle()

    assert app is not None
    assert len(window.command_queue) == 2
    assert all(item["dry_run"] is False for item in window.command_queue)
    assert window._pending_confirmation_task_ids == []
    window.scheduler_timer.stop()
    window.close()


def test_sync_confirmation_dialog_scrolls_content_and_keeps_buttons_visible(
    tmp_path, monkeypatch
):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    window = MainWindow(store)
    tasks = []
    for index in range(30):
        task = SyncTask.create(
            name=f"Mirror {index}",
            source_path=str(tmp_path),
            remote_path=f"mega:Mirror-{index}",
        )
        task.last_change_candidates = 20
        task.last_change_details = [
            f"folder/file-{detail_index}.txt: отличается от облака"
            for detail_index in range(12)
        ]
        tasks.append(task)

    captured = {}

    def inspect_dialog(dialog):
        dialog.show()
        QApplication.processEvents()
        captured["dialog"] = dialog
        captured["scroll_area"] = dialog.findChild(QScrollArea)
        captured["buttons"] = dialog.findChild(QDialogButtonBox)
        captured["vertical_scroll_maximum"] = (
            captured["scroll_area"].verticalScrollBar().maximum()
        )
        captured["buttons_bottom"] = captured["buttons"].geometry().bottom()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", inspect_dialog)

    action, selected = window._select_tasks_for_sync(tasks)

    dialog = captured["dialog"]
    scroll_area = captured["scroll_area"]
    buttons = captured["buttons"]
    available_height = window.screen().availableGeometry().height()

    assert app is not None
    assert action == "defer"
    assert selected == []
    assert scroll_area is not None
    assert scroll_area.widgetResizable()
    assert len(scroll_area.widget().findChildren(QCheckBox)) == len(tasks)
    assert captured["vertical_scroll_maximum"] > 0
    assert buttons is not None
    assert not scroll_area.isAncestorOf(buttons)
    assert dialog.layout().itemAt(dialog.layout().count() - 1).widget() is buttons
    assert captured["buttons_bottom"] <= dialog.contentsRect().bottom()
    assert dialog.maximumHeight() <= int(available_height * 0.85)
    assert dialog.height() <= dialog.maximumHeight()
    window.scheduler_timer.stop()
    window.close()


def test_defer_interval_tasks_waits_until_next_interval(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["mega"])
    store.set_selected_remote("mega")
    task = SyncTask.create(
        name="Mirror",
        source_path=str(tmp_path),
        remote_path="mega:Mirror",
        interval_minutes=1,
    )
    store.set_tasks_data([task.to_dict()])
    window = MainWindow(store)
    task = window.tasks[0]
    window._pending_confirmation_task_ids.append(task.id)

    window._defer_interval_tasks([task])

    assert app is not None
    assert task.last_status == "Отложено"
    assert task.interval_paused is False
    assert window._pending_confirmation_task_ids == []
    window.scheduler_timer.stop()
    window.close()


def test_pause_interval_tasks_keeps_selected_interval_value(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["mega"])
    store.set_selected_remote("mega")
    task = SyncTask.create(
        name="Mirror",
        source_path=str(tmp_path),
        remote_path="mega:Mirror",
        interval_minutes=24 * 60,
    )
    store.set_tasks_data([task.to_dict()])
    window = MainWindow(store)
    task = window.tasks[0]
    window._pending_confirmation_task_ids.append(task.id)

    window._pause_interval_tasks([task])

    assert app is not None
    assert task.last_status == "Интервал отключен"
    assert task.interval_minutes == 24 * 60
    assert task.interval_paused is True
    assert window._pending_confirmation_task_ids == []
    window.scheduler_timer.stop()
    window.close()


def test_runner_counts_dry_run_change_candidates():
    runner = RcloneRunner()
    runner._current_meta = {"mode": "dry-run"}
    finished_events = []
    runner.command_finished.connect(finished_events.append)

    runner._handle_line(
        '{"level":"notice","msg":"Skipped copy as --dry-run is set","object":"a.txt"}',
        is_error=False,
    )

    runner._emit_finished(exit_code=0, crashed=False)

    assert finished_events[0]["change_candidates"] == 1
    assert finished_events[0]["change_details"] == ["a.txt: будет скопирован"]


def test_runner_ignores_progress_checking_lines_from_rclone_progress():
    runner = RcloneRunner()
    runner._current_meta = {"mode": "dry-run"}
    finished_events = []
    output_events = []
    runner.command_finished.connect(finished_events.append)
    runner.command_output.connect(output_events.append)

    runner._handle_line("* same.txt: checking", is_error=False)
    runner._handle_line(
        '{"level":"notice","msg":"\\nTransferred: 0 B / 0 B\\n",'
        '"stats":{"bytes":0,"checks":1,"totalChecks":1,"transfers":0}}',
        is_error=False,
    )
    runner._emit_finished(exit_code=0, crashed=False)

    assert finished_events[0]["change_candidates"] == 0
    assert finished_events[0]["change_details"] == []
    assert not any("[DRY-RUN]" in event for event in output_events)


def test_runner_hides_combined_equal_lines_from_log():
    runner = RcloneRunner()
    runner._current_meta = {"mode": "dry-run"}
    output_events = []
    runner.command_output.connect(output_events.append)

    runner._handle_line("= same.txt", is_error=False)

    assert output_events == []


def test_runner_captures_remote_quota_json_without_logging_it():
    runner = RcloneRunner()
    runner._current_meta = {
        "kind": "diagnostic",
        "diagnostic_name": "remote-quota",
    }
    finished_events = []
    output_events = []
    runner.command_finished.connect(finished_events.append)
    runner.command_output.connect(output_events.append)

    runner._handle_line('{"total":53687091200,"used":26843545600}', is_error=False)
    runner._emit_finished(exit_code=0, crashed=False)

    assert finished_events[0]["output"] == '{"total":53687091200,"used":26843545600}'
    assert output_events == []


def test_runner_stats_zero_suppresses_false_dry_run_candidates():
    runner = RcloneRunner()
    runner._current_meta = {"mode": "dry-run"}
    finished_events = []
    runner.command_finished.connect(finished_events.append)

    runner._handle_line("* stale-progress.txt: checking", is_error=False)
    runner._handle_line(
        '{"level":"notice","msg":"\\nTransferred: 0 B / 0 B\\n",'
        '"stats":{"transfers":0,"deletes":0,"deletedDirs":0,"renames":0,'
        '"serverSideCopies":0,"serverSideMoves":0}}',
        is_error=False,
    )
    runner._emit_finished(exit_code=0, crashed=False)

    assert finished_events[0]["change_candidates"] == 0
    assert finished_events[0]["delete_candidates"] == 0
    assert finished_events[0]["change_details"] == []


def test_runner_collects_combined_dry_run_details():
    runner = RcloneRunner()
    runner._current_meta = {"mode": "dry-run"}
    finished_events = []
    runner.command_finished.connect(finished_events.append)

    runner._handle_line("* aliases.ps1", is_error=False)
    runner._handle_line(
        '{"level":"notice","msg":"Skipped copy as --dry-run is set",'
        '"skipped":"copy","size":20616,"object":"aliases.ps1"}',
        is_error=False,
    )

    runner._emit_finished(exit_code=0, crashed=False)

    assert finished_events[0]["change_candidates"] == 1
    assert finished_events[0]["change_details"] == [
        "aliases.ps1: отличается от облака; будет скопирован, размер 20616 байт"
    ]


def test_confirmation_dialog_details_text_limits_long_lists(tmp_path):
    app = _qt_app()
    store = SettingsStore(tmp_path / "settings.json")
    store.set_remote_names(["mega"])
    store.set_selected_remote("mega")
    window = MainWindow(store)
    task = SyncTask.create(
        name="Mirror",
        source_path=str(tmp_path),
        remote_path="mega:Mirror",
    )
    task.last_change_candidates = 13
    task.last_change_details = [f"file-{index}.txt: отличается" for index in range(13)]

    text = window._task_change_details_text(task)

    assert app is not None
    assert "file-0.txt: отличается" in text
    assert "file-12.txt: отличается" not in text
    assert "...ещё 1" in text
    window.scheduler_timer.stop()
    window.close()


def test_runner_emit_finished_keeps_next_command_meta_intact():
    runner = RcloneRunner()
    runner._current_meta = {"kind": "task", "task_id": "first"}

    busy_events = []
    finished_events = []

    def on_busy(value):
        busy_events.append(value)

    def on_finished(result):
        finished_events.append(result)
        runner._current_meta = {"kind": "task", "task_id": "second"}

    runner.busy_changed.connect(on_busy)
    runner.command_finished.connect(on_finished)

    runner._emit_finished(exit_code=0, crashed=False)

    assert busy_events == [False]
    assert finished_events[0]["task_id"] == "first"
    assert runner._current_meta == {"kind": "task", "task_id": "second"}
