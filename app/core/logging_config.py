# -*- coding: utf-8 -*-
"""Настройка логирования с очисткой файла при запуске."""

from __future__ import annotations

import logging

from app.core.app_config import LOG_FILE, app_root


def configure_logging() -> None:
    log_path = app_root() / LOG_FILE
    log_path.write_text("", encoding="utf-8")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
