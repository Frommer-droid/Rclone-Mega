# -*- coding: utf-8 -*-
"""Глобальная темная QSS-тема."""

from __future__ import annotations


COLORS = {
    "bg_main": "#141C24",
    "bg_panel": "#1B2632",
    "bg_card": "#0D141B",
    "accent": "#35D0BA",
    "button": "#4E79D8",
    "button_warn": "#C96E4E",
    "text": "#F2F7FA",
    "muted": "#9CB1C2",
    "border": "#2E4355",
}


def build_stylesheet() -> str:
    return f"""
    QWidget {{
        background-color: {COLORS["bg_main"]};
        color: {COLORS["text"]};
        font-family: "Aptos", "Segoe UI", sans-serif;
        font-size: 11pt;
    }}
    QMainWindow {{
        background-color: {COLORS["bg_main"]};
    }}
    QGroupBox {{
        border: 1px solid {COLORS["border"]};
        border-radius: 10px;
        margin-top: 12px;
        padding: 14px;
        background-color: {COLORS["bg_panel"]};
        font-weight: 700;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
    }}
    QLabel#titleLabel {{
        color: {COLORS["accent"]};
        font-size: 18pt;
        font-weight: 700;
    }}
    QLabel#mutedLabel {{
        color: {COLORS["muted"]};
    }}
    QLabel#statusBadge {{
        background-color: {COLORS["bg_card"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 8px;
        padding: 4px 10px;
        min-height: 0;
        max-height: 28px;
    }}
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QComboBox,
    QSpinBox,
    QTableWidget {{
        background-color: {COLORS["bg_card"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 8px;
        selection-background-color: {COLORS["button"]};
        selection-color: {COLORS["text"]};
    }}
    QComboBox {{
        padding: 4px 28px 4px 8px;
    }}
    QComboBox QAbstractItemView {{
        min-width: 112px;
        background-color: {COLORS["bg_card"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        selection-background-color: {COLORS["button"]};
        selection-color: {COLORS["text"]};
    }}
    QHeaderView::section {{
        background-color: {COLORS["bg_panel"]};
        color: {COLORS["muted"]};
        border: none;
        border-bottom: 1px solid {COLORS["border"]};
        padding: 8px;
        font-weight: 700;
    }}
    QPushButton {{
        background-color: {COLORS["button"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["button"]};
        border-radius: 8px;
        padding: 8px 14px;
    }}
    QPushButton:hover {{
        background-color: #5B8BEF;
        border-color: #5B8BEF;
    }}
    QPushButton:disabled {{
        background-color: #394652;
        color: #8FA2B2;
        border-color: #394652;
    }}
    QPushButton#dangerButton {{
        background-color: {COLORS["button_warn"]};
        border-color: {COLORS["button_warn"]};
    }}
    QPushButton#dangerButton:hover {{
        background-color: #DE7F5F;
        border-color: #DE7F5F;
    }}
    QPushButton#dangerButton:disabled {{
        background-color: #A75F49;
        color: #101820;
        border-color: #A75F49;
    }}
    QCheckBox {{
        spacing: 8px;
    }}
    QStatusBar {{
        background-color: {COLORS["bg_panel"]};
        border-top: 1px solid {COLORS["border"]};
    }}
    QProgressBar {{
        background-color: {COLORS["bg_card"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 6px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {COLORS["accent"]};
        border-radius: 6px;
    }}
    QSplitter#contentSplitter::handle:vertical {{
        background-color: {COLORS["border"]};
        margin: 2px 20px;
        border-radius: 3px;
    }}
    QSplitter#contentSplitter::handle:vertical:hover {{
        background-color: {COLORS["accent"]};
    }}
    """
