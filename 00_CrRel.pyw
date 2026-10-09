# -*- coding: utf-8 -*-
"""Сборка Inno Setup installer из prepared portable-папки Rclone Mega."""

from __future__ import annotations

import os
import shutil
import stat
import string
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path


APP_NAME = "Rclone Mega"
APP_PUBLISHER = "Frommer-droid"
APP_ID = "EABF8D8B-D704-4C3D-A008-7E6A9F0BCEB3"
EXE_NAME = f"{APP_NAME}.exe"

SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_DIR = SCRIPT_DIR / APP_NAME
WORK_DIR = Path(
    os.environ.get(
        "RCLONE_RELEASE_WORKDIR", str(SCRIPT_DIR / ".release-work" / "installer")
    )
)

REQUIRED_RELEASE_FILES = (
    EXE_NAME,
    "VERSION",
    "LICENSE",
    "logo.ico",
)
REQUIRED_RELEASE_DIRS = (
    "_internal",
)
RUNTIME_NOISE_FILES = (
    "settings.json",
    "rclone.conf",
    os.path.join("_internal", "vendor", "rclone", "rclone.conf"),
    "rclone-mega.log",
    "speech_history.txt",
)

ISCC_CANDIDATE_PATHS = (
    os.environ.get("INNO_SETUP_ISCC", ""),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    shutil.which("ISCC.exe") or "",
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
)


def resolve_desktop_dir() -> Path:
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(260)
        result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buffer)
        if result == 0 and buffer.value:
            return Path(buffer.value)
    except Exception:
        pass
    return Path.home() / "Desktop"


def iter_fixed_drives() -> list[Path]:
    try:
        import ctypes

        drive_type_fixed = 3
        drives: list[Path] = []
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(root) == drive_type_fixed:
                drives.append(Path(root))
        if drives:
            return drives
    except Exception:
        pass
    return [Path(r"C:\\")]


def resolve_default_install_base_dir() -> Path:
    fixed_drives = iter_fixed_drives()

    for drive in fixed_drives:
        if str(drive).upper().startswith("D:"):
            return drive / "Apps"

    for drive in fixed_drives:
        if not str(drive).upper().startswith("C:"):
            return drive / "Apps"

    return Path(r"C:\Apps")


OUTPUT_DIR = resolve_desktop_dir()
DEFAULT_INSTALL_BASE_DIR = resolve_default_install_base_dir()


def _configure_stdout() -> None:
    if sys.stdout:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def find_iscc_path() -> str:
    for path in ISCC_CANDIDATE_PATHS:
        if path and os.path.isfile(path):
            return path
    return ""


def remove_readonly(func, path, _exc_info) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception as exc:
        print(f"Не удалось удалить {path}: {exc}")


def show_popup(message: str, is_error: bool = False) -> None:
    try:
        root = tk.Tk()
        root.attributes("-topmost", True)

        if is_error:
            root.title("Ошибка")
            bg_color = "#ffcccc"
        else:
            root.overrideredirect(True)
            bg_color = "#e6ffe6"

        root.configure(bg=bg_color)
        width = 620 if is_error else 480
        height = 240 if is_error else 150
        x = (root.winfo_screenwidth() // 2) - (width // 2)
        y = (root.winfo_screenheight() // 2) - (height // 2)
        root.geometry(f"{width}x{height}+{x}+{y}")

        label = tk.Label(
            root,
            text=message,
            font=("Segoe UI", 11),
            bg=bg_color,
            wraplength=width - 30,
        )
        label.pack(expand=True, padx=20, pady=18)

        if is_error:
            button = tk.Button(root, text="Закрыть", command=root.destroy)
            button.pack(pady=(0, 14))
        else:
            root.after(3500, root.destroy)
            root.bind("<Button-1>", lambda _event: root.destroy())
            label.bind("<Button-1>", lambda _event: root.destroy())

        root.mainloop()
    except Exception:
        print(message)


def kill_process_smart(process_name: str, path_filter: str | None = None) -> None:
    process_name_no_ext = process_name.removesuffix(".exe")

    for _attempt in range(3):
        if path_filter:
            escaped_path = path_filter.replace("'", "''")
            escaped_name = process_name_no_ext.replace("'", "''")
            ps_command = (
                f"$name = '{escaped_name}'; "
                f"$target = [System.IO.Path]::GetFullPath('{escaped_path}'); "
                "if (-not $target.EndsWith([System.IO.Path]::DirectorySeparatorChar)) "
                "{ $target += [System.IO.Path]::DirectorySeparatorChar }; "
                "Get-Process -Name $name -ErrorAction SilentlyContinue | "
                "Where-Object { $_.Path -and "
                "([System.IO.Path]::GetFullPath($_.Path)).StartsWith($target, "
                "[System.StringComparison]::OrdinalIgnoreCase) } | "
                "Stop-Process -Force"
            )
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    ps_command,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.run(
                ["taskkill", "/F", "/IM", process_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        time.sleep(0.5)


def read_version() -> str:
    version_file = SCRIPT_DIR / "VERSION"
    if not version_file.exists():
        return "0.0.0"
    version = version_file.read_text(encoding="utf-8").strip()
    return version or "0.0.0"


def get_missing_release_items(source_dir: Path) -> dict[str, list[str]]:
    missing_files = [
        name for name in REQUIRED_RELEASE_FILES if not (source_dir / name).is_file()
    ]
    missing_dirs = [
        name for name in REQUIRED_RELEASE_DIRS if not (source_dir / name).is_dir()
    ]
    return {"files": missing_files, "directories": missing_dirs}


def format_missing_release_items(missing: dict[str, list[str]]) -> str:
    lines: list[str] = []
    if missing["files"]:
        lines.append("Отсутствуют файлы:")
        lines.extend(f"- {name}" for name in missing["files"])
    if missing["directories"]:
        lines.append("Отсутствуют каталоги:")
        lines.extend(f"- {name}" for name in missing["directories"])
    return "\n".join(lines)


def prepare_release_folder(source: Path, destination: Path) -> bool:
    print(f"--- Подготовка installer staging: {source} -> {destination} ---")

    if destination.exists():
        try:
            shutil.rmtree(destination, onerror=remove_readonly)
        except Exception as exc:
            print(f"Не удалось очистить staging-каталог: {exc}")
            return False

    try:
        shutil.copytree(source, destination)
    except Exception as exc:
        print(f"Не удалось скопировать portable-папку: {exc}")
        return False

    for filename in RUNTIME_NOISE_FILES:
        file_path = destination / filename
        if file_path.exists():
            try:
                file_path.unlink()
                print(f"Удалён runtime-файл из installer staging: {filename}")
            except Exception as exc:
                print(f"Не удалось удалить {filename}: {exc}")
                return False

    return True


def build_iss_content(version: str, setup_icon: Path | None) -> str:
    setup_icon_line = (
        f'SetupIconFile="{setup_icon.as_posix()}"'
        if setup_icon and setup_icon.exists()
        else ""
    )

    template = r"""; Inno Setup script for Rclone Mega.
; Generated by 00_CrRel.pyw.

#define MyAppName "__APP_NAME__"
#define MyAppVersion "__VERSION__"
#define MyAppPublisher "__APP_PUBLISHER__"
#define MyAppExeName "__EXE_NAME__"

[Setup]
AppId={{__APP_ID__}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={code:GetDefaultInstallDir}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=no
LanguageDetectionMethod=none
ShowLanguageDialog=no
OutputDir="__OUTPUT_DIR__"
OutputBaseFilename={#MyAppName}_v{#MyAppVersion}_Setup
__SETUP_ICON_LINE__
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
VersionInfoVersion={#MyAppVersion}.0
VersionInfoTextVersion={#MyAppVersion}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} — установка
VersionInfoProductName={#MyAppName}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные значки:"

[Files]
Source: "__WORK_DIR__\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.ico"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillApp"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function GetDefaultInstallDir(Param: String): String;
begin
  if DirExists('D:\') then
    Result := 'D:\Apps\' + ExpandConstant('{#MyAppName}')
  else
    Result := 'C:\Apps\' + ExpandConstant('{#MyAppName}');
end;
"""

    return (
        template.replace("__APP_NAME__", APP_NAME)
        .replace("__VERSION__", version)
        .replace("__APP_PUBLISHER__", APP_PUBLISHER)
        .replace("__EXE_NAME__", EXE_NAME)
        .replace("__APP_ID__", APP_ID)
        .replace("__OUTPUT_DIR__", OUTPUT_DIR.as_posix())
        .replace("__WORK_DIR__", WORK_DIR.as_posix())
        .replace("__SETUP_ICON_LINE__", setup_icon_line)
    )


def compile_installer(iscc_path: str, iss_content: str, version: str) -> Path | None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    setup_name = f"{APP_NAME}_v{version}_Setup.exe"

    with tempfile.NamedTemporaryFile(
        prefix="rclone_mega_installer_",
        suffix=".iss",
        delete=False,
        mode="w",
        encoding="utf-8",
    ) as handle:
        iss_path = Path(handle.name)
        handle.write(iss_content)

    try:
        result = subprocess.run(
            [iscc_path, str(iss_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(SCRIPT_DIR),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.stdout:
            print(result.stdout)
        if result.returncode != 0:
            return None
    finally:
        try:
            iss_path.unlink(missing_ok=True)
        except Exception:
            pass

    output_path = OUTPUT_DIR / setup_name
    return output_path if output_path.exists() else None


def main() -> int:
    _configure_stdout()
    print(f"--- Создание installer для {APP_NAME} ---")

    iscc_path = find_iscc_path()
    if not iscc_path:
        show_popup(
            "Компилятор Inno Setup не найден.\n"
            "Установите Inno Setup 6 или задайте INNO_SETUP_ISCC.",
            is_error=True,
        )
        return 1

    if not SOURCE_DIR.is_dir():
        show_popup(
            "Не найдена готовая portable-папка:\n"
            f"{SOURCE_DIR}\n\n"
            "Сначала выполните сборку через Build_Tools/SpecCompiler.pyw.",
            is_error=True,
        )
        return 1

    missing = get_missing_release_items(SOURCE_DIR)
    if missing["files"] or missing["directories"]:
        show_popup(
            "Portable-папка неполная:\n" + format_missing_release_items(missing),
            is_error=True,
        )
        return 1

    kill_process_smart(EXE_NAME, path_filter=str(SOURCE_DIR))

    if not prepare_release_folder(SOURCE_DIR, WORK_DIR):
        show_popup("Не удалось подготовить staging-папку для installer.", is_error=True)
        return 1

    version = read_version()
    setup_icon = WORK_DIR / "logo.ico"
    iss_content = build_iss_content(version, setup_icon if setup_icon.exists() else None)
    installer_path = compile_installer(iscc_path, iss_content, version)
    if installer_path is None:
        show_popup("Inno Setup завершился с ошибкой.", is_error=True)
        return 1

    show_popup(f"Installer создан:\n{installer_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
