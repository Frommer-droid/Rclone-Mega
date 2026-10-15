# -*- coding: utf-8 -*-
"""Обновление portable-папки Rclone Mega."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import time
import tkinter as tk


APP_NAME = "Rclone Mega"
EXE_NAME = f"{APP_NAME}.exe"
# Может быть переопределен локально без попадания личного пути в репозиторий.
DESTINATION_PARENT = os.environ.get("RCLONE_MEGA_PORTABLE_DIR", r"C:\Portable")
REQUIRED_SOURCE_ITEMS = (
    EXE_NAME,
    "_internal",
    "VERSION",
    "logo.ico",
)
RCLONE_CONFIG_NAME = "rclone.conf"
SETTINGS_NAME = "settings.json"


def remove_readonly(func, path, _exc_info) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception as exc:
        print(f"Не удалось удалить {path}: {exc}")


def show_popup(message: str = "Готово", is_error: bool = False) -> None:
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
        width = 620 if is_error else 440
        height = 240 if is_error else 140
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


def _resolve_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def ensure_target_is_safe(target_path: str) -> None:
    parent = _resolve_path(DESTINATION_PARENT)
    target = _resolve_path(target_path)
    parent_with_sep = parent if parent.endswith(os.sep) else parent + os.sep

    if target == parent or not target.startswith(parent_with_sep):
        raise ValueError(f"Небезопасный путь назначения: {target_path}")


def validate_source_folder(source_folder: str) -> list[str]:
    missing: list[str] = []
    for item in REQUIRED_SOURCE_ITEMS:
        if not os.path.exists(os.path.join(source_folder, item)):
            missing.append(item)
    return missing


def remove_existing_folder(target_folder: str) -> bool:
    if not os.path.exists(target_folder):
        return True

    for attempt in range(1, 4):
        try:
            shutil.rmtree(target_folder, onerror=remove_readonly)
        except OSError as exc:
            print(f"Попытка удаления {attempt}/3 завершилась с ошибкой: {exc}")
        if not os.path.exists(target_folder):
            return True
        time.sleep(1)
    return not os.path.exists(target_folder)


def copy_release_folder(source_folder: str, target_folder: str) -> None:
    shutil.copytree(
        source_folder,
        target_folder,
        dirs_exist_ok=os.path.exists(target_folder),
    )


def preserve_rclone_config(
    project_root: str, target_folder: str, backup_folder: str
) -> str | None:
    candidates = (
        os.path.join(target_folder, RCLONE_CONFIG_NAME),
        os.path.join(project_root, RCLONE_CONFIG_NAME),
    )
    for candidate in candidates:
        if not os.path.isfile(candidate):
            continue
        os.makedirs(backup_folder, exist_ok=True)
        backup_path = os.path.join(backup_folder, RCLONE_CONFIG_NAME)
        shutil.copy2(candidate, backup_path)
        return backup_path
    return None


def restore_rclone_config(backup_path: str, target_folder: str) -> None:
    os.makedirs(target_folder, exist_ok=True)
    shutil.copy2(backup_path, os.path.join(target_folder, RCLONE_CONFIG_NAME))


def preserve_settings(
    project_root: str, target_folder: str, backup_folder: str
) -> str | None:
    for folder in (target_folder, os.path.join(project_root, APP_NAME), project_root):
        candidate = os.path.join(folder, SETTINGS_NAME)
        if os.path.isfile(candidate):
            backup_path = os.path.join(backup_folder, SETTINGS_NAME)
            shutil.copy2(candidate, backup_path)
            return backup_path
    return None


def restore_settings(backup_path: str | None, target_folder: str) -> None:
    if backup_path:
        os.makedirs(target_folder, exist_ok=True)
        shutil.copy2(backup_path, os.path.join(target_folder, SETTINGS_NAME))


def manage_folders() -> None:
    base_dir = os.path.abspath(os.path.dirname(__file__))
    source_folder = os.path.join(base_dir, APP_NAME)
    target_folder = os.path.join(DESTINATION_PARENT, APP_NAME)

    if not os.path.isdir(source_folder):
        show_popup(
            "Не найдена папка portable-сборки:\n"
            f"{source_folder}\n\n"
            "Сначала выполните сборку через Build_Tools/SpecCompiler.pyw.",
            is_error=True,
        )
        return

    missing = validate_source_folder(source_folder)
    if missing:
        show_popup(
            "Portable-папка неполная:\n" + "\n".join(f"- {name}" for name in missing),
            is_error=True,
        )
        return

    try:
        ensure_target_is_safe(target_folder)
    except ValueError as exc:
        show_popup(str(exc), is_error=True)
        return

    os.makedirs(DESTINATION_PARENT, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rclone-mega-portable-") as temp_dir:
        try:
            config_backup = preserve_rclone_config(base_dir, target_folder, temp_dir)
            settings_backup = preserve_settings(base_dir, target_folder, temp_dir)
        except OSError as exc:
            show_popup(f"Не удалось сохранить настройки:\n{exc}", is_error=True)
            return

        kill_process_smart(EXE_NAME, path_filter=target_folder)
        time.sleep(1)

        if not remove_existing_folder(target_folder):
            print(
                "[WARN] Не удалось полностью удалить старую portable-папку. "
                "Новая сборка будет скопирована поверх оставшихся файлов."
            )

        try:
            copy_release_folder(source_folder, target_folder)
            restore_settings(settings_backup, target_folder)
            if config_backup:
                restore_rclone_config(config_backup, target_folder)
                print(f"[OK] Восстановлен {RCLONE_CONFIG_NAME}")
            else:
                print(f"[WARN] {RCLONE_CONFIG_NAME} не найден и не был скопирован")
        except OSError as exc:
            restore_settings(settings_backup, target_folder)
            if config_backup:
                try:
                    restore_rclone_config(config_backup, target_folder)
                except OSError as restore_exc:
                    print(f"[ERROR] Не удалось восстановить rclone.conf: {restore_exc}")
            show_popup(f"Не удалось скопировать portable-папку:\n{exc}", is_error=True)
            return

    show_popup(f"Portable-папка обновлена:\n{target_folder}")


if __name__ == "__main__":
    manage_folders()
