# -*- coding: utf-8 -*-
"""Русская локализация Qt/PySide6."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication

from app.core.app_config import resource_path


RUSSIAN_LOCALE = QLocale(
    QLocale.Language.Russian,
    QLocale.Country.Russia,
)


def set_russian_qt_locale() -> None:
    QLocale.setDefault(RUSSIAN_LOCALE)


def install_russian_qt_translations(app: QApplication) -> list[QTranslator]:
    """Загружает qtbase_ru.qm для стандартных меню и диалогов Qt."""

    translators: list[QTranslator] = []
    translation_dirs = (
        Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)),
        resource_path("PySide6/translations"),
        resource_path("PySide6/Qt/translations"),
        resource_path("translations"),
    )

    for translations_dir in translation_dirs:
        if not translations_dir.exists():
            continue

        translator = QTranslator(app)
        loaded = translator.load(
            RUSSIAN_LOCALE,
            "qtbase",
            "_",
            str(translations_dir),
        ) or translator.load("qtbase_ru", str(translations_dir))

        if loaded:
            app.installTranslator(translator)
            translators.append(translator)
            break

    # QTranslator должен жить столько же, сколько QApplication.
    app._russian_qt_translators = translators  # type: ignore[attr-defined]
    return translators
