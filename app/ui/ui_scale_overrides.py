"""Scale layout/widget metrics from immutable baselines, never cumulatively."""

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QAbstractButton,
    QFormLayout,
    QLabel,
    QLayout,
    QSplitter,
    QTableWidget,
    QWidget,
)

from app.services.ui_scale_service import scale_px


def _margins(margins):
    return (margins.left(), margins.top(), margins.right(), margins.bottom())


def scale_widget_tree(root: QWidget, factor: float) -> None:
    for layout in root.findChildren(QLayout):
        base = getattr(layout, "_scale_base", None)
        if base is None:
            base = (_margins(layout.contentsMargins()), layout.spacing())
            layout._scale_base = base
            if isinstance(layout, QFormLayout):
                layout._scale_form = (
                    layout.horizontalSpacing(),
                    layout.verticalSpacing(),
                )
        layout.setContentsMargins(*(scale_px(x, factor) for x in base[0]))
        if base[1] >= 0:
            layout.setSpacing(scale_px(base[1], factor))
        if isinstance(layout, QFormLayout):
            h, v = layout._scale_form
            if h >= 0:
                layout.setHorizontalSpacing(scale_px(h, factor))
            if v >= 0:
                layout.setVerticalSpacing(scale_px(v, factor))
    for widget in [root, *root.findChildren(QWidget)]:
        base = getattr(widget, "_scale_base_metrics", None)
        if base is None:
            base = {
                "min": (widget.minimumWidth(), widget.minimumHeight()),
                "max": (widget.maximumWidth(), widget.maximumHeight()),
                "margins": _margins(widget.contentsMargins()),
            }
            if isinstance(widget, QAbstractButton):
                base["icon"] = (widget.iconSize().width(), widget.iconSize().height())
            if isinstance(widget, QLabel) and not widget.pixmap().isNull():
                base["pixmap"] = widget.pixmap()
            if isinstance(widget, QSplitter):
                base["handle"] = widget.handleWidth()
            widget._scale_base_metrics = base
        widget.setContentsMargins(*(scale_px(x, factor) for x in base["margins"]))
        # Tables/viewports manage their own geometry; top-level windows keep position/size.
        if not widget.isWindow():
            for axis, minimum, maximum in zip(
                ("Width", "Height"), base["min"], base["max"]
            ):
                lo = scale_px(minimum, factor)
                hi = scale_px(maximum, factor) if maximum < 16777215 else maximum
                getattr(widget, f"setMinimum{axis}")(0)
                getattr(widget, f"setMaximum{axis}")(hi)
                getattr(widget, f"setMinimum{axis}")(lo)
        if "icon" in base:
            widget.setIconSize(QSize(*(scale_px(x, factor) for x in base["icon"])))
        fixed = widget.property("uiScaleBaseFixed")
        if isinstance(fixed, QSize):
            widget.setFixedSize(
                scale_px(fixed.width(), factor), scale_px(fixed.height(), factor)
            )
        if "pixmap" in base:
            pixmap = base["pixmap"]
            from PySide6.QtCore import Qt

            widget.setPixmap(
                pixmap.scaled(
                    scale_px(pixmap.width(), factor),
                    scale_px(pixmap.height(), factor),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        if "handle" in base:
            if widget.objectName() == "contentSplitter":
                widget.setHandleWidth(
                    0 if widget.widget(1).isHidden() else scale_px(10, factor)
                )
            else:
                widget.setHandleWidth(scale_px(base["handle"], factor))
        if isinstance(widget, QTableWidget):
            widget.verticalHeader().setDefaultSectionSize(scale_px(48, factor))
            for row in range(widget.rowCount()):
                widget.setRowHeight(row, scale_px(48, factor))
