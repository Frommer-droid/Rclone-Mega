"""Small consistent outline symbols rendered by Qt, with disabled variants."""

from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from app.ui.theme import THEME_COLORS

_PATHS = {
    "check": '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5m-13-10 2 2 4-4"/>',
    "sync": '<path d="M20 8a8 8 0 0 0-14-3L3 8m0-5v5h5M4 16a8 8 0 0 0 14 3l3-3m0 5v-5h-5"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "history": '<path d="M3 11a9 9 0 1 1 2 7M3 5v6h6m3-4v5l3 2"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "edit": '<path d="m15 4 5 5M4 20l5-1L20 8a2 2 0 0 0-5-5L4 14z"/>',
    "trash": '<path d="M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7"/>',
    "settings": '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',
    "log": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
}


@lru_cache(maxsize=32)
def icon(name: str, tone: str = "text") -> QIcon:
    result = QIcon()
    for mode, color in (
        (QIcon.Mode.Normal, THEME_COLORS[tone]),
        (QIcon.Mode.Disabled, THEME_COLORS["disabled_text"]),
    ):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'fill="none" stroke="{color}" stroke-width="1.7" '
            f'stroke-linecap="round" stroke-linejoin="round">{_PATHS[name]}</svg>'
        )
        pixmap = QPixmap(48, 48)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        QSvgRenderer(QByteArray(svg.encode())).render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(2)
        result.addPixmap(pixmap, mode)
    return result
