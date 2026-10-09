# -*- coding: utf-8 -*-
"""Конфигурация приложения и helpers путей."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


APP_NAME = "Rclone Mega"
PROJECT_SLUG = "rclone-mega"
APP_USER_MODEL_ID = "frommer.rclonemega.desktop.1"
SETTINGS_FILE = "settings.json"
LOG_FILE = f"{PROJECT_SLUG}.log"
RCLONE_CONFIG_FILE = "rclone.conf"


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_path(relative_path: str) -> Path:
    candidate = app_root() / relative_path
    if candidate.exists():
        return candidate

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / relative_path
        if bundled.exists():
            return bundled

    return candidate


def bundled_rclone_path() -> Path:
    return resource_path("vendor/rclone/rclone.exe")


def rclone_config_path() -> Path:
    return app_root() / RCLONE_CONFIG_FILE


def detect_default_rclone_path() -> str:
    bundled = bundled_rclone_path()
    candidates = [
        str(bundled),
        shutil.which("rclone"),
        r"C:\Program Files\rclone\rclone.exe",
        r"C:\Program Files (x86)\rclone\rclone.exe",
    ]

    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return str(path)

    return "rclone.exe"


def read_app_version() -> str:
    version_path = app_root() / "VERSION"
    try:
        return version_path.read_text(encoding="utf-8-sig").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


APP_VERSION = read_app_version()
