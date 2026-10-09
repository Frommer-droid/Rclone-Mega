# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import os
import site
import sys
from pathlib import Path

block_cipher = None

APP_NAME = "Rclone Mega"
MAIN_SCRIPT = "rclone_mega.py"
ICON_FILE = "logo.ico"


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _configure_trusted_path(project_root: Path) -> tuple[Path, ...]:
    """Replace inherited PATH before dependency analysis.

    PyInstaller must not discover DLLs from IDEs, agents, Conda, MSYS or other
    unrelated toolchains present on the build machine.
    """
    system_root = Path(os.environ.get("SystemRoot", r"C:\\Windows"))
    candidates = (
        project_root,
        Path(sys.prefix),
        Path(sys.prefix) / "DLLs",
        Path(sys.base_prefix),
        Path(sys.base_prefix) / "DLLs",
        system_root / "System32",
    )
    trusted = tuple(path.resolve() for path in candidates if path.exists())
    os.environ["PATH"] = os.pathsep.join(str(path) for path in trusted)
    return trusted


def _validate_binary_origins(binaries, allowed_roots: tuple[Path, ...]) -> None:
    """Fail closed when Analysis collects a binary from an untrusted origin."""
    foreign = sorted(
        str(source)
        for _destination, source, _typecode in binaries
        if not any(_is_within(Path(source), root) for root in allowed_roots)
    )
    if foreign:
        raise RuntimeError(
            "PyInstaller discovered binary files outside trusted roots:\\n"
            + "\\n".join(foreign)
        )


def _normalize_msvc_runtime(binaries, pyside_root: Path) -> None:
    """Use one complete MSVC runtime set from the current PySide6 package."""
    runtime_prefixes = ("concrt140", "msvcp140", "vcruntime140")
    pyside_runtime = {
        path.name.lower(): path.resolve()
        for path in pyside_root.glob("*.dll")
        if path.name.lower().startswith(runtime_prefixes)
    }
    if not pyside_runtime:
        raise RuntimeError(f"PySide6 MSVC runtime is missing: {pyside_root}")

    destinations: set[str] = set()
    for index, (destination, source, typecode) in enumerate(binaries):
        filename = Path(destination).name.lower()
        destinations.add(destination.lower())
        replacement = pyside_runtime.get(filename)
        if replacement is not None:
            binaries[index] = (destination, str(replacement), typecode)

    for filename, source in pyside_runtime.items():
        if filename not in destinations:
            binaries.append((source.name, str(source), "BINARY"))

    invalid = sorted(
        str(source)
        for destination, source, _typecode in binaries
        if Path(destination).name.lower().startswith(runtime_prefixes)
        and Path(source).resolve() != pyside_runtime[Path(destination).name.lower()]
    )
    if invalid:
        raise RuntimeError(
            "PyInstaller MSVC runtime normalization failed:\\n" + "\\n".join(invalid)
        )


def _find_qtbase_ru_qm(project_root: Path) -> Path:
    candidates: list[Path] = []
    try:
        candidates.extend(
            Path(path) / "PySide6" / "translations" / "qtbase_ru.qm"
            for path in site.getsitepackages()
        )
    except Exception:
        pass

    try:
        user_site = site.getusersitepackages()
    except Exception:
        user_site = ""
    if user_site:
        candidates.append(Path(user_site) / "PySide6" / "translations" / "qtbase_ru.qm")

    candidates.append(
        project_root
        / ".venv"
        / "Lib"
        / "site-packages"
        / "PySide6"
        / "translations"
        / "qtbase_ru.qm"
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "Не найден qtbase_ru.qm. Убедитесь, что PySide6 установлен в проектной .venv."
    )


spec_path = Path(sys.argv[0]).resolve()
spec_dir = spec_path.parent
project_root = spec_dir.parent
script_path = project_root / MAIN_SCRIPT
icon_path = project_root / ICON_FILE
qtbase_ru_qm = _find_qtbase_ru_qm(project_root)
trusted_path_roots = _configure_trusted_path(project_root)
system_root = Path(os.environ.get("SystemRoot", r"C:\\Windows"))
allowed_binary_roots = (
    project_root.resolve(),
    Path(sys.prefix).resolve(),
    Path(sys.base_prefix).resolve(),
    system_root.resolve(),
)
pyside_root = Path(sys.prefix) / "Lib" / "site-packages" / "PySide6"

datas = [
    (str(project_root / "VERSION"), "."),
    (str(project_root / "LICENSE"), "."),
    (str(project_root / "THIRD_PARTY_NOTICES.md"), "."),
    (str(project_root / "licenses"), "licenses"),
    (str(project_root / "logo.ico"), "."),
    (str(project_root / "vendor" / "rclone"), "vendor/rclone"),
    (str(qtbase_ru_qm), "translations"),
]

a = Analysis(
    [str(script_path)],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

_validate_binary_origins(a.binaries, allowed_binary_roots)
_normalize_msvc_runtime(a.binaries, pyside_root)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon_path) if icon_path.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
