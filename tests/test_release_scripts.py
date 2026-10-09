import importlib.machinery
import importlib.util
from pathlib import Path


def _load_script(filename, module_name):
    script_path = Path(__file__).resolve().parents[1] / filename
    loader = importlib.machinery.SourceFileLoader(module_name, str(script_path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_installer_offers_postinstall_launch_but_skips_silent_installs():
    release_script = _load_script("00_CrRel.pyw", "rclone_mega_release")

    content = release_script.build_iss_content("0.5.2", None)

    assert "[Run]" in content
    assert 'Filename: "{app}\\{#MyAppExeName}"' in content
    assert "Flags: nowait postinstall skipifsilent" in content
    assert "unchecked" not in content


def test_post_build_preserves_caches_and_accepts_external_dist(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "rclone_post_build",
        Path(__file__).resolve().parents[1] / "Build_Tools" / "post_build.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    work = tmp_path / "work"
    cache = work / "__pycache__"
    cache.mkdir(parents=True)
    evidence = cache / "keep.pyc"
    evidence.write_bytes(b"cache")
    module.cleanup_temp_dirs(work, work, work)
    assert evidence.read_bytes() == b"cache"
    external_dist = tmp_path / "external-dist"
    app_dir = external_dist / module.APP_NAME
    app_dir.mkdir(parents=True)
    monkeypatch.setenv("RCLONE_DIST_DIR", str(external_dist))
    assert module.find_dist_app_dir(work, work) == app_dir


def test_installer_selects_install_drive_on_target_and_uses_russian():
    release_script = _load_script("00_CrRel.pyw", "rclone_mega_install_drive")
    content = release_script.build_iss_content("0.6.0", None)
    assert "DefaultDirName={code:GetDefaultInstallDir}" in content
    assert "if DirExists('D:\\') then" in content
    assert "Result := 'D:\\Apps\\'" in content
    assert "Result := 'C:\\Apps\\'" in content
    assert "ShowLanguageDialog=no" in content
    assert "LanguageDetectionMethod=none" in content


def test_portable_update_preserves_existing_rclone_config(tmp_path, monkeypatch):
    move_script = _load_script("00_Move.pyw", "rclone_mega_move_existing")
    project_root = tmp_path / "project"
    source = project_root / move_script.APP_NAME
    destination_parent = tmp_path / "portable"
    destination = destination_parent / move_script.APP_NAME
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    for name in (move_script.EXE_NAME, "VERSION", "logo.ico"):
        (source / name).write_text("new", encoding="utf-8")
    (source / "_internal").mkdir()
    (destination / "rclone.conf").write_text("target-config", encoding="utf-8")
    (destination / "settings.json").write_text("target-settings", encoding="utf-8")
    (source / "settings.json").write_text("source-settings", encoding="utf-8")
    (destination / "stale.txt").write_text("stale", encoding="utf-8")

    monkeypatch.setattr(move_script, "__file__", str(project_root / "00_Move.pyw"))
    monkeypatch.setattr(move_script, "DESTINATION_PARENT", str(destination_parent))
    monkeypatch.setattr(move_script, "kill_process_smart", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(move_script.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(move_script, "show_popup", lambda *_args, **_kwargs: None)

    move_script.manage_folders()

    assert (destination / "rclone.conf").read_text(encoding="utf-8") == "target-config"
    assert (destination / "settings.json").read_text(encoding="utf-8") == "target-settings"
    assert not (destination / "stale.txt").exists()
    assert (destination / move_script.EXE_NAME).read_text(encoding="utf-8") == "new"


def test_portable_update_uses_project_rclone_config_for_first_deploy(
    tmp_path, monkeypatch
):
    move_script = _load_script("00_Move.pyw", "rclone_mega_move_first")
    project_root = tmp_path / "project"
    source = project_root / move_script.APP_NAME
    destination_parent = tmp_path / "portable"
    destination = destination_parent / move_script.APP_NAME
    source.mkdir(parents=True)
    for name in (move_script.EXE_NAME, "VERSION", "logo.ico"):
        (source / name).write_text("new", encoding="utf-8")
    (source / "_internal").mkdir()
    (project_root / "rclone.conf").write_text("project-config", encoding="utf-8")

    monkeypatch.setattr(move_script, "__file__", str(project_root / "00_Move.pyw"))
    monkeypatch.setattr(move_script, "DESTINATION_PARENT", str(destination_parent))
    monkeypatch.setattr(move_script, "kill_process_smart", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(move_script.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(move_script, "show_popup", lambda *_args, **_kwargs: None)

    move_script.manage_folders()

    assert (destination / "rclone.conf").read_text(encoding="utf-8") == "project-config"
