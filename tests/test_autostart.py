from pathlib import Path

from app.core import autostart


def test_set_autostart_enabled_creates_shortcut_in_startup_folder(
    tmp_path, monkeypatch
):
    created_paths: list[Path] = []
    startup = tmp_path / "Startup"
    fallback = tmp_path / "FallbackStartup"

    monkeypatch.setattr(autostart, "startup_folder", lambda: startup)
    monkeypatch.setattr(autostart, "fallback_startup_folder", lambda: fallback)
    monkeypatch.setattr(autostart, "_create_shortcut", created_paths.append)

    path = autostart.set_autostart_enabled(True)

    assert path == startup / autostart.AUTOSTART_LINK_NAME
    assert created_paths == [path]


def test_set_autostart_disabled_removes_primary_and_fallback_shortcuts(
    tmp_path, monkeypatch
):
    startup = tmp_path / "Startup"
    fallback = tmp_path / "FallbackStartup"
    startup.mkdir()
    fallback.mkdir()
    primary = startup / autostart.AUTOSTART_LINK_NAME
    secondary = fallback / autostart.AUTOSTART_LINK_NAME
    primary.write_text("", encoding="utf-8")
    secondary.write_text("", encoding="utf-8")

    monkeypatch.setattr(autostart, "startup_folder", lambda: startup)
    monkeypatch.setattr(autostart, "fallback_startup_folder", lambda: fallback)

    removed_path = autostart.set_autostart_enabled(False)

    assert removed_path in {primary, secondary}
    assert not primary.exists()
    assert not secondary.exists()
