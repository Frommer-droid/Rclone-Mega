# -*- coding: utf-8 -*-
"""Тонкая точка входа приложения."""

from __future__ import annotations

import ctypes
import multiprocessing
import os
import sys
from pathlib import Path


def _relaunch_from_project_venv() -> None:
    if getattr(sys, "frozen", False) or sys.platform != "win32":
        return

    project_root = Path(__file__).resolve().parent
    venv_python = project_root / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        return

    current_python = Path(sys.executable).resolve()
    target_python = venv_python.resolve()
    if current_python == target_python or current_python == (
        venv_python.parent / "pythonw.exe"
    ).resolve():
        return

    os.execv(
        str(target_python),
        [str(target_python), str(Path(__file__).resolve()), *sys.argv[1:]],
    )


_relaunch_from_project_venv()

# Импорты Qt должны оставаться ниже защиты, чтобы прямой запуск глобальным
# Python сначала перезапустился из .venv до импорта PySide6.
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.app_config import APP_USER_MODEL_ID, resource_path  # noqa: E402
from app.core.localization import (  # noqa: E402
    install_russian_qt_translations,
    set_russian_qt_locale,
)
from app.core.logging_config import configure_logging  # noqa: E402
from app.core.settings_store import SettingsStore  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.styles import build_stylesheet  # noqa: E402


def set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_USER_MODEL_ID
        )
    except Exception:
        pass


def main() -> int:
    multiprocessing.freeze_support()
    set_windows_app_id()
    configure_logging()
    set_russian_qt_locale()

    qt_app = QApplication(sys.argv)
    install_russian_qt_translations(qt_app)
    qt_app.setQuitOnLastWindowClosed(True)
    qt_app.setStyleSheet(build_stylesheet())

    app_icon = None
    icon_path = resource_path("logo.ico")
    if icon_path.exists():
        app_icon = QIcon(str(icon_path))
        qt_app.setWindowIcon(app_icon)

    settings_store = SettingsStore()
    window = MainWindow(settings_store)
    if app_icon is not None:
        window.setWindowIcon(app_icon)
    window.show()
    if settings_store.get_start_minimized():
        QTimer.singleShot(0, window.hide_to_tray)
    try:
        return qt_app.exec()
    except KeyboardInterrupt:
        window.close()
        return 130


if __name__ == "__main__":
    sys.exit(main())
