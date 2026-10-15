# -*- coding: utf-8 -*-
"""Windows autostart shortcut management."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from app.core.app_config import APP_NAME, app_root


AUTOSTART_LINK_NAME = f"{APP_NAME}.lnk"


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


FOLDERID_STARTUP = _GUID(
    0xB97D20BB,
    0xF46A,
    0x4C97,
    (ctypes.c_ubyte * 8)(0xBA, 0x10, 0x5E, 0x36, 0x08, 0x43, 0x08, 0x54),
)


def startup_folder() -> Path:
    if sys.platform == "win32":
        path_ptr = ctypes.c_void_p()
        result = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(FOLDERID_STARTUP),
            0,
            None,
            ctypes.byref(path_ptr),
        )
        if result == 0 and path_ptr.value:
            path = Path(ctypes.wstring_at(path_ptr))
            ctypes.windll.ole32.CoTaskMemFree(path_ptr)
            return path

    appdata = os.environ.get("APPDATA", "")
    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )


def fallback_startup_folder() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )


def shortcut_path() -> Path:
    return startup_folder() / AUTOSTART_LINK_NAME


def is_autostart_enabled() -> bool:
    return shortcut_path().exists() or (
        fallback_startup_folder() / AUTOSTART_LINK_NAME
    ).exists()


def set_autostart_enabled(enabled: bool) -> Path | None:
    if enabled:
        path = shortcut_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _create_shortcut(path)
        return path

    removed_path: Path | None = None
    for folder in {startup_folder(), fallback_startup_folder()}:
        path = folder / AUTOSTART_LINK_NAME
        try:
            path.unlink()
            removed_path = path
        except FileNotFoundError:
            pass
    return removed_path


def _create_shortcut(path: Path) -> None:
    target_path = Path(sys.executable).resolve()
    arguments = ""
    working_directory = app_root()

    if not getattr(sys, "frozen", False):
        target_path = Path(sys.executable).resolve()
        script_path = str(Path(sys.argv[0]).resolve())
        arguments = _quote_vbs_value(f'"{script_path}"')

    script = f"""
Set shell = CreateObject("WScript.Shell")
Set shortcut = shell.CreateShortcut("{_quote_vbs_value(str(path))}")
shortcut.TargetPath = "{_quote_vbs_value(str(target_path))}"
shortcut.Arguments = "{arguments}"
shortcut.WorkingDirectory = "{_quote_vbs_value(str(working_directory))}"
shortcut.Description = "{_quote_vbs_value(APP_NAME)}"
shortcut.Save
"""

    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".vbs",
        delete=False,
        encoding="utf-8",
    ) as handle:
        script_path = Path(handle.name)
        handle.write(script)

    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["cscript.exe", "//Nologo", str(script_path)],
            check=True,
            creationflags=creationflags,
        )
    finally:
        try:
            script_path.unlink()
        except OSError:
            pass


def _quote_vbs_value(value: str) -> str:
    return value.replace('"', '""')
