# -*- coding: utf-8 -*-
"""Загрузка и сохранение settings.json."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core.app_config import SETTINGS_FILE, app_root, detect_default_rclone_path
from app.core.memory_limits import bounded_change_details


REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

DEFAULT_SETTINGS: dict[str, Any] = {
    "window": {
        "x": 120,
        "y": 120,
        "width": 900,
        "height": 680,
        "maximized": False,
    },
    "confirm_dialog": {
        "x": None,
        "y": None,
        "width": 720,
        "height": 560,
    },
    "task_dialog": {
        "x": None,
        "y": None,
        "width": 780,
        "height": 640,
    },
    "rclone_path": detect_default_rclone_path(),
    "tasks": [],
    "autostart_enabled": False,
    "start_minimized": False,
    "use_custom_rclone": False,
    "remote_names": [],
    "selected_remote": "",
    "show_all_accounts": True,
}


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_root() / SETTINGS_FILE
        self.settings = self.load()

    def load(self) -> dict[str, Any]:
        data = deepcopy(DEFAULT_SETTINGS)
        if not self.path.exists():
            return data

        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return data

        if isinstance(loaded, dict):
            self._deep_update(data, loaded)
        self._bound_task_details(data)
        return data

    def save(self) -> None:
        self._bound_task_details(self.settings)
        self.path.write_text(
            json.dumps(self.settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_window_settings(self) -> dict[str, Any]:
        window = self.settings.setdefault("window", {})
        if not isinstance(window, dict):
            window = deepcopy(DEFAULT_SETTINGS["window"])
            self.settings["window"] = window
        return window

    def get_dialog_settings(self, name: str) -> dict[str, Any]:
        defaults = DEFAULT_SETTINGS.get(name, {})
        if not isinstance(defaults, dict):
            defaults = {}
        stored = self.settings.setdefault(name, {})
        if not isinstance(stored, dict):
            stored = deepcopy(defaults)
            self.settings[name] = stored
        else:
            for key, value in defaults.items():
                stored.setdefault(key, value)
        return stored

    def set_dialog_geometry(
        self, name: str, *, x: int, y: int, width: int, height: int
    ) -> None:
        dialog = self.get_dialog_settings(name)
        dialog.update(
            {
                "x": int(x),
                "y": int(y),
                "width": int(width),
                "height": int(height),
            }
        )

    def get_confirm_dialog_settings(self) -> dict[str, Any]:
        return self.get_dialog_settings("confirm_dialog")

    def get_task_dialog_settings(self) -> dict[str, Any]:
        return self.get_dialog_settings("task_dialog")

    def get_rclone_path(self) -> str:
        if not self.get_use_custom_rclone():
            value = detect_default_rclone_path()
            self.settings["rclone_path"] = value
            return value

        value = self.settings.get("rclone_path")
        if not isinstance(value, str) or not value.strip() or value.strip() == "rclone.exe":
            value = detect_default_rclone_path()
            self.settings["rclone_path"] = value
        elif not Path(value).exists():
            detected = detect_default_rclone_path()
            if Path(detected).exists():
                value = detected
                self.settings["rclone_path"] = value
                self.settings["use_custom_rclone"] = False
        return value

    def set_rclone_path(self, value: str, *, custom: bool | None = None) -> None:
        normalized = value.strip() or detect_default_rclone_path()
        self.settings["rclone_path"] = normalized
        if custom is not None:
            self.settings["use_custom_rclone"] = bool(custom)

    def get_use_custom_rclone(self) -> bool:
        return bool(self.settings.get("use_custom_rclone", False))

    def set_use_custom_rclone(self, value: bool) -> None:
        self.settings["use_custom_rclone"] = bool(value)

    def get_tasks_data(self) -> list[dict[str, Any]]:
        tasks = self.settings.setdefault("tasks", [])
        if not isinstance(tasks, list):
            tasks = []
            self.settings["tasks"] = tasks
        return [task for task in tasks if isinstance(task, dict)]

    def set_tasks_data(self, tasks: list[dict[str, Any]]) -> None:
        self.settings["tasks"] = tasks
        self._bound_task_details(self.settings)

    @staticmethod
    def _bound_task_details(settings: dict[str, Any]) -> None:
        tasks = settings.get("tasks")
        if isinstance(tasks, list):
            for task in tasks:
                if isinstance(task, dict) and "last_change_details" in task:
                    task["last_change_details"] = bounded_change_details(
                        task["last_change_details"]
                    )

    def get_remote_names(self) -> list[str]:
        names: list[str] = []
        raw_names = self.settings.setdefault("remote_names", [])
        if not isinstance(raw_names, list):
            raw_names = []
            self.settings["remote_names"] = raw_names

        for value in raw_names:
            self._append_remote_name(names, value)

        self.settings["remote_names"] = names
        return names

    def set_remote_names(self, names: list[str]) -> None:
        normalized: list[str] = []
        for name in names:
            self._append_remote_name(normalized, name)
        self.settings["remote_names"] = normalized

    def add_remote_name(self, name: str) -> None:
        names = self.get_remote_names()
        self._append_remote_name(names, name)
        self.settings["remote_names"] = names

    def get_selected_remote(self) -> str:
        selected = self._normalize_remote_name(
            str(self.settings.get("selected_remote") or "")
        )
        remote_names = self.get_remote_names()
        if not self._is_valid_remote_name(selected) or selected not in remote_names:
            selected = remote_names[0] if remote_names else ""
        self.settings["selected_remote"] = selected
        return selected

    def set_selected_remote(self, name: str) -> None:
        normalized = self._normalize_remote_name(name)
        if not normalized:
            self.settings["selected_remote"] = ""
            return
        if not self._is_valid_remote_name(normalized):
            return
        self.settings["selected_remote"] = normalized
        self.add_remote_name(normalized)

    def get_autostart_enabled(self) -> bool:
        return bool(self.settings.get("autostart_enabled", False))

    def set_autostart_enabled(self, value: bool) -> None:
        self.settings["autostart_enabled"] = bool(value)

    def get_start_minimized(self) -> bool:
        return bool(self.settings.get("start_minimized", False))

    def set_start_minimized(self, value: bool) -> None:
        self.settings["start_minimized"] = bool(value)

    @staticmethod
    def _deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                SettingsStore._deep_update(target[key], value)
            else:
                target[key] = value

    @staticmethod
    def _normalize_remote_name(value: object) -> str:
        return str(value or "").strip().removesuffix(":").strip()

    @staticmethod
    def _is_valid_remote_name(value: str) -> bool:
        return bool(REMOTE_NAME_RE.fullmatch(value))

    @staticmethod
    def _append_remote_name(names: list[str], value: object) -> None:
        name = SettingsStore._normalize_remote_name(value)
        if SettingsStore._is_valid_remote_name(name) and name not in names:
            names.append(name)
