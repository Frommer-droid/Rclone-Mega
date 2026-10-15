"""Native widget palette and shared visual states."""

from pathlib import Path
import re
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton

from app.ui.theme.colors import THEME_COLORS

DERIVED_COLORS: dict[str, str] = {}


def enforce_button_proportions(widget) -> None:
    if isinstance(widget, (QPushButton, QToolButton)):
        widget.setMinimumWidth(max(widget.minimumWidth(), widget.minimumHeight()))


class _ButtonProportions(QObject):
    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.FontChange):
            enforce_button_proportions(watched)
        return False


def apply_theme(app: QApplication, scale_factor: float = 1.0) -> None:
    if app.property("oneDarkScaleFactor") == scale_factor:
        return
    if not app.property("oneDarkApplied"):
        app.setStyle("Fusion")
        app.setProperty("oneDarkApplied", True)
    font = QFont("Tahoma")
    font.setPointSizeF(max(3.5, round(10 * scale_factor * 2) / 2))
    app.setFont(font)
    c = THEME_COLORS
    palette = QPalette()
    for role, token in {
        QPalette.ColorRole.Window: "background",
        QPalette.ColorRole.WindowText: "text",
        QPalette.ColorRole.Base: "surface",
        QPalette.ColorRole.AlternateBase: "alternate",
        QPalette.ColorRole.Text: "text_strong",
        QPalette.ColorRole.Button: "surface_hover",
        QPalette.ColorRole.ButtonText: "text_strong",
        QPalette.ColorRole.Highlight: "selection",
        QPalette.ColorRole.HighlightedText: "text_strong",
        QPalette.ColorRole.ToolTipBase: "surface_alt",
        QPalette.ColorRole.ToolTipText: "text_strong",
        QPalette.ColorRole.PlaceholderText: "muted",
        QPalette.ColorRole.Link: "accent",
    }.items():
        palette.setColor(role, QColor(c[token]))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["disabled_text"]))
    app.setPalette(palette)
    app.setStyleSheet(build_stylesheet(scale_factor))
    app.setProperty("oneDarkScaleFactor", scale_factor)
    if not hasattr(app, "_button_proportions_filter"):
        app._button_proportions_filter = _ButtonProportions(app)
        app.installEventFilter(app._button_proportions_filter)
    for widget in app.allWidgets():
        enforce_button_proportions(widget)


def build_stylesheet(scale_factor: float = 1.0) -> str:
    c = THEME_COLORS
    assets = Path(__file__).with_name("assets").as_posix()
    stylesheet = f"""
    QWidget {{ color: {c["text"]}; font-family: "Tahoma", "Segoe UI", "Aptos"; font-size: 10pt; }}
    QMainWindow, QDialog {{ background: {c["background"]}; }}
    QLabel, QCheckBox, QWidget#rowActions {{ background: transparent; }}
    QLabel#titleLabel {{ color: {c["text_strong"]}; font-size: 18pt; font-weight: 600; }}
    QLabel#sectionTitle {{ color: {c["text_strong"]}; font-size: 12pt; font-weight: 600; }}
    QLabel#mutedLabel {{ color: {c["muted"]}; }}
    QLabel#statusBadge {{ color: {c["muted"]}; background: {c["surface"]}; border-radius: 8px; padding: 7px 12px; }}
    QGroupBox {{ background: {c["surface"]}; border: 1px solid {c["border"]}; border-radius: 10px; margin-top: 0px; padding: 14px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 5px; color: {c["text_strong"]}; }}
    QGroupBox#tasksPanel {{ padding: 0px; }}
    QLineEdit, QComboBox, QSpinBox, QTimeEdit {{ background: {c["surface"]}; color: {c["text_strong"]}; border: 1px solid {c["border"]}; border-radius: 6px; padding: 6px 10px; min-height: 20px; selection-background-color: {c["selection"]}; }}
    QComboBox {{ padding-right: 26px; }}
    QComboBox::drop-down {{ width: 22px; border: none; }}
    QComboBox::down-arrow {{ image: url("{assets}/chevron.svg"); width: 14px; height: 14px; }}
    QAbstractSpinBox {{ padding-right: 24px; }}
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 22px; border: none; background: transparent; }}
    QAbstractSpinBox::up-arrow {{ image: url("{assets}/chevron-up.svg"); width: 12px; height: 12px; }}
    QAbstractSpinBox::down-arrow {{ image: url("{assets}/chevron.svg"); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{ background: {c["surface_alt"]}; color: {c["text_strong"]}; border: 1px solid {c["border"]}; selection-background-color: {c["selection"]}; padding: 4px; }}
    QPlainTextEdit, QTextEdit, QListWidget {{ background: {c["surface"]}; color: {c["text"]}; border: 1px solid {c["border"]}; border-radius: 6px; padding: 8px; selection-background-color: {c["selection"]}; }}
    QPlainTextEdit#codeEditor {{ font-family: "Consolas"; font-size: 10pt; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QListWidget:focus {{ border-color: {c["focus"]}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QTimeEdit:disabled {{ color: {c["disabled_text"]}; border-color: {c["disabled_border"]}; }}
    QPushButton, QToolButton {{ background: {c["surface_hover"]}; color: {c["text_strong"]}; border: 1px solid {c["border"]}; border-radius: 6px; padding: 6px 12px; min-height: 20px; }}
    QPushButton:hover, QToolButton:hover {{ background: {c["primary_hover"]}; }}
    QPushButton:pressed, QToolButton:pressed {{ background: {c["surface_pressed"]}; }}
    QPushButton:checked, QToolButton:checked {{ background: {c["selection"]}; border-color: {c["accent"]}; }}
    QPushButton:focus, QToolButton:focus {{ border: 2px solid {c["focus"]}; padding: 5px 11px; }}
    QPushButton#primaryButton, QPushButton#start_btn {{ background: {c["accent"]}; color: {c["on_accent"]}; border-color: {c["accent"]}; font-weight: 600; }}
    QPushButton#primaryButton:hover, QPushButton#start_btn:hover {{ background: {c["accent_hover"]}; }}
    QPushButton#primaryButton:pressed, QPushButton#start_btn:pressed {{ background: {c["accent_pressed"]}; }}
    QPushButton#danger_btn, QToolButton#danger_btn {{ background: {c["danger_surface"]}; color: {c["danger_text"]}; border-color: {c["danger_surface"]}; }}
    QPushButton#danger_btn:hover, QToolButton#danger_btn:hover {{ border-color: {c["danger"]}; }}
    QPushButton#danger_btn:pressed, QToolButton#danger_btn:pressed {{ background: {c["surface_pressed"]}; }}
    QPushButton#success_btn {{ background: {c["success"]}; color: {c["on_accent"]}; border-color: {c["success"]}; font-weight: 600; }}
    QPushButton#success_btn:hover {{ border-color: {c["text_strong"]}; }}
    QPushButton#success_btn:pressed {{ background: {c["surface_pressed"]}; color: {c["success"]}; }}
    QPushButton:disabled, QToolButton:disabled, QPushButton#primaryButton:disabled, QPushButton#start_btn:disabled, QPushButton#danger_btn:disabled, QToolButton#danger_btn:disabled, QPushButton#success_btn:disabled {{ background: {c["disabled_background"]}; color: {c["disabled_text"]}; border-color: {c["disabled_border"]}; }}
    QToolButton#rowAction, QToolButton#runHistoryButton, QToolButton#danger_btn {{ padding: 6px; min-width: 0px; min-height: 0px; }}
    QToolButton::menu-indicator {{ width: 0px; height: 0px; }}
    QCheckBox {{ spacing: 8px; min-height: 24px; }}
    QCheckBox:disabled {{ color: {c["disabled_text"]}; }}
    QCheckBox:focus {{ color: {c["accent"]}; }}
    QCheckBox::indicator, QAbstractItemView::indicator {{ width: 16px; height: 16px;
        border: 1px solid {c["muted"]}; border-radius: 4px; background: {c["surface"]}; }}
    QCheckBox::indicator:hover, QAbstractItemView::indicator:hover {{ border-color: {c["accent"]}; }}
    QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {{
        background: {c["accent"]}; border-color: {c["accent"]}; image: url("{assets}/check.svg"); }}
    QCheckBox::indicator:disabled {{ border-color: {c["disabled_border"]}; background: {c["disabled_background"]}; }}
    QCheckBox::indicator:checked:disabled {{ background: {c["disabled_text"]}; }}
    QTableWidget {{ background: {c["surface"]}; alternate-background-color: {c["alternate"]}; border: none; gridline-color: {c["border"]}; selection-background-color: {c["selection"]}; selection-color: {c["text_strong"]}; }}
    QTableWidget::item {{ padding: 6px 10px; border-bottom: 1px solid {c["surface_alt"]}; }}
    QTableWidget::item:selected {{ background: {c["selection"]}; color: {c["text_strong"]}; }}
    QTableWidget::item:focus {{ border: 1px solid {c["focus"]}; }}
    QHeaderView::section {{ background: {c["surface_alt"]}; color: {c["muted"]}; border: none; border-bottom: 1px solid {c["border"]}; padding: 10px 8px; }}
    QHeaderView::section:hover {{ background: {c["surface_hover"]}; color: {c["text_strong"]}; }}
    QListWidget::item {{ padding: 12px 8px; border-radius: 6px; }}
    QListWidget::item:selected {{ background: {c["selection"]}; color: {c["text_strong"]}; }}
    QTabWidget::pane {{ border: 1px solid {c["border"]}; border-radius: 8px; }}
    QTabBar::tab {{ background: {c["background"]}; color: {c["muted"]}; border-bottom: 2px solid transparent; padding: 12px 16px; }}
    QTabBar::tab:selected {{ color: {c["text_strong"]}; border-bottom-color: {c["accent"]}; }}
    QTabBar::tab:hover {{ background: {c["surface_hover"]}; }}
    QTabBar::tab:disabled {{ color: {c["disabled_text"]}; }}
    QScrollArea {{ border: none; background: transparent; }}
    QStatusBar {{ background: {c["surface"]}; color: {c["muted"]}; border-top: 1px solid {c["border"]}; padding: 4px 12px; }}
    QStatusBar::item {{ border: none; }}
    QProgressBar {{ background: {c["surface_alt"]}; color: {c["text_strong"]}; border: 1px solid {c["border"]}; border-radius: 6px; text-align: center; min-height: 22px; }}
    QProgressBar::chunk {{ background: {c["primary_hover"]}; border-radius: 5px; }}
    QSplitter::handle {{ background: {c["background"]}; }}
    QSplitter::handle:hover {{ background: {c["border"]}; }}
    QMenu {{ background: {c["surface_alt"]}; color: {c["text_strong"]}; border: 1px solid {c["border"]}; padding: 6px; }}
    QMenu::item {{ padding: 8px 20px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {c["selection"]}; }}
    QMenu::item:disabled {{ color: {c["disabled_text"]}; }}
    QMenu::separator {{ background: {c["border"]}; height: 1px; margin: 6px; }}
    QToolTip {{ background: {c["surface_alt"]}; color: {c["text_strong"]}; border: 1px solid {c["border"]}; padding: 6px; }}
    QScrollBar:vertical {{ background: {c["surface"]}; width: 10px; margin: 0; }}
    QScrollBar:horizontal {{ background: {c["surface"]}; height: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {c["scrollbar"]}; min-height: 28px; border-radius: 5px; }}
    QScrollBar::handle:horizontal {{ background: {c["scrollbar"]}; min-width: 28px; border-radius: 5px; }}
    QScrollBar::handle:hover {{ background: {c["muted"]}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    """
    def scaled(match):
        value, unit = float(match[1]), match[2]
        result = (round(value * scale_factor * 2) / 2 if unit == "pt"
                  else (0 if value == 0 else max(1, round(value * scale_factor))))
        return f"{result:g}{unit}"
    return re.sub(r"(\d+(?:\.\d+)?)(px|pt)", scaled, stylesheet)
