import json

from app.core.settings_store import SettingsStore
from app.models.sync_task import SyncTask


def test_settings_store_creates_defaults(tmp_path):
    settings_path = tmp_path / "settings.json"
    store = SettingsStore(settings_path)

    assert store.settings["window"]["width"] > 0
    assert isinstance(store.get_rclone_path(), str)
    assert store.get_tasks_data() == []
    assert store.get_remote_names() == []
    assert store.get_selected_remote() == ""
    store.save()
    assert settings_path.exists()


def test_settings_store_replaces_legacy_bare_rclone_exe(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"rclone_path": "rclone.exe"}', encoding="utf-8")
    bundled = tmp_path / "vendor" / "rclone" / "rclone.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "app.core.settings_store.detect_default_rclone_path",
        lambda: str(bundled),
    )

    store = SettingsStore(settings_path)

    assert store.get_rclone_path() == str(bundled)


def test_settings_store_ignores_old_external_rclone_without_custom_flag(
    tmp_path,
    monkeypatch,
):
    settings_path = tmp_path / "settings.json"
    external = tmp_path / "old" / "rclone.exe"
    external.parent.mkdir()
    external.write_text("", encoding="utf-8")
    settings_path.write_text(
        json.dumps({"rclone_path": str(external)}),
        encoding="utf-8",
    )
    bundled = tmp_path / "vendor" / "rclone" / "rclone.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "app.core.settings_store.detect_default_rclone_path",
        lambda: str(bundled),
    )

    store = SettingsStore(settings_path)

    assert store.get_rclone_path() == str(bundled)
    assert store.get_use_custom_rclone() is False


def test_settings_store_preserves_explicit_custom_rclone(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    external = tmp_path / "custom" / "rclone.exe"
    external.parent.mkdir()
    external.write_text("", encoding="utf-8")
    settings_path.write_text(
        json.dumps({"rclone_path": str(external), "use_custom_rclone": True}),
        encoding="utf-8",
    )
    bundled = tmp_path / "vendor" / "rclone" / "rclone.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "app.core.settings_store.detect_default_rclone_path",
        lambda: str(bundled),
    )

    store = SettingsStore(settings_path)

    assert store.get_rclone_path() == str(external)
    assert store.get_use_custom_rclone() is True


def test_settings_store_round_trip(tmp_path):
    settings_path = tmp_path / "settings.json"
    store = SettingsStore(settings_path)
    task = SyncTask.create(
        name="Документы",
        source_path=str(tmp_path),
        remote_path="mega:PC/Docs",
        excludes=["*.tmp"],
    )

    store.set_rclone_path(r"C:\Program Files\rclone\rclone.exe", custom=True)
    store.set_tasks_data([task.to_dict()])
    store.settings["window"]["width"] = 1024
    store.save()

    reloaded = SettingsStore(settings_path)
    assert reloaded.settings["window"]["width"] == 1024
    assert reloaded.get_rclone_path().endswith("rclone.exe")
    assert reloaded.get_tasks_data()[0]["name"] == "Документы"


def test_settings_store_round_trips_startup_flags(tmp_path):
    settings_path = tmp_path / "settings.json"
    store = SettingsStore(settings_path)

    store.set_autostart_enabled(True)
    store.set_start_minimized(True)
    store.save()

    reloaded = SettingsStore(settings_path)
    assert reloaded.get_autostart_enabled() is True
    assert reloaded.get_start_minimized() is True


def test_settings_store_tracks_configured_remote_names_without_task_discovery(tmp_path):
    settings_path = tmp_path / "settings.json"
    store = SettingsStore(settings_path)
    task = SyncTask.create(
        name="Archive",
        source_path=str(tmp_path),
        remote_path="mega_2:Archive",
        use_backup_dir=True,
        backup_dir="mega_3:_deleted/Archive",
    )

    store.set_remote_names(["account", "bad name"])
    store.set_selected_remote("mega_2")
    store.set_tasks_data([task.to_dict()])
    store.save()

    reloaded = SettingsStore(settings_path)
    assert reloaded.get_remote_names() == ["account", "mega_2"]
    assert reloaded.get_selected_remote() == "mega_2"


def test_dialog_geometry_round_trip(tmp_path):
    settings_path = tmp_path / "settings.json"
    store = SettingsStore(settings_path)

    # По умолчанию позиция не задана — первый показ использует default размер.
    assert store.get_confirm_dialog_settings()["x"] is None
    assert store.get_task_dialog_settings()["x"] is None

    store.set_dialog_geometry("confirm_dialog", x=100, y=200, width=720, height=560)
    store.set_dialog_geometry("task_dialog", x=300, y=400, width=780, height=640)
    store.save()

    reloaded = SettingsStore(settings_path)
    confirm = reloaded.get_confirm_dialog_settings()
    assert (confirm["x"], confirm["y"], confirm["width"], confirm["height"]) == (
        100,
        200,
        720,
        560,
    )
    task = reloaded.get_task_dialog_settings()
    assert (task["x"], task["y"]) == (300, 400)


def test_dialog_geometry_backward_compatible_with_old_settings(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"window": {"x": 10, "y": 10, "width": 900, "height": 680}}),
        encoding="utf-8",
    )
    store = SettingsStore(settings_path)
    # Старый файл без ключей диалогов не должен ломаться.
    assert store.get_confirm_dialog_settings()["width"] == 720
    assert store.get_task_dialog_settings()["width"] == 780
    assert store.get_window_settings()["x"] == 10
