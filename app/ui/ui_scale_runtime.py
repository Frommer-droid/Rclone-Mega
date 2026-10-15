"""Apply screen-adaptive scaling and keep screen changes free of forced resize."""

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QWidget

from app.services.ui_scale_service import (
    normalize_delta,
    resolve_ui_scale,
    target_window_size,
)
from app.ui.theme import apply_theme
from app.ui.ui_scale_overrides import scale_widget_tree


class _ScaleShowRouter(QObject):
    """One application filter; route only window/menu shows to their owner."""

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.Show or not isinstance(watched, QWidget):
            return False
        if not watched.isWindow():
            return False
        owner = watched
        while owner is not None:
            runtime = getattr(owner, "scale_runtime", None)
            if runtime is not None:
                runtime.widget_shown(watched)
                break
            owner = owner.parentWidget()
        return False


class UIScaleRuntime(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.factor = 1.0
        self.state = None
        self._screen = None
        self._window_hooked = False
        self._applying = False
        app = QApplication.instance()
        if not hasattr(app, "_ui_scale_show_router"):
            app._ui_scale_show_router = _ScaleShowRouter(app)
            app.installEventFilter(app._ui_scale_show_router)
        for signal in (app.primaryScreenChanged, app.screenAdded, app.screenRemoved):
            signal.connect(self._topology_changed)

    def install_hooks(self):
        handle = self.window.windowHandle()
        if handle is not None and not self._window_hooked:
            handle.screenChanged.connect(self._screen_changed)
            self._window_hooked = True
        self._connect_screen(self.window.screen())

    def _connect_screen(self, screen):
        if screen is self._screen:
            return
        if self._screen is not None:
            for signal_name in (
                "logicalDotsPerInchChanged",
                "geometryChanged",
                "availableGeometryChanged",
            ):
                try:
                    getattr(self._screen, signal_name).disconnect(self._metrics_changed)
                except (RuntimeError, TypeError):
                    pass
        self._screen = screen
        if screen is not None:
            for signal_name in (
                "logicalDotsPerInchChanged",
                "geometryChanged",
                "availableGeometryChanged",
            ):
                getattr(screen, signal_name).connect(self._metrics_changed)

    def _screen_changed(self, screen):
        self._connect_screen(screen)
        self.apply("screen-changed")

    def _metrics_changed(self, *args):
        self.apply("screen-metrics")

    def _topology_changed(self, *args):
        self.install_hooks()
        self.apply("screen-topology")

    def set_delta(self, delta):
        self.window.settings_store.settings["ui_scale_delta_percent"] = normalize_delta(
            delta
        )
        self.apply("manual-delta")
        self.window.settings_store.save()

    def apply(self, reason="runtime"):
        if self._applying:
            return
        screen = self.window.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        settings = self.window.settings_store.settings
        state = resolve_ui_scale(
            available.width(),
            available.height(),
            screen.logicalDotsPerInch(),
            settings.get("ui_scale_delta_percent", 0),
        )
        old_factor = self.factor
        open_dialogs = [
            (widget, widget.size())
            for widget in QApplication.topLevelWidgets()
            if isinstance(widget, QDialog)
            and widget.isVisible()
            and self.window.isAncestorOf(widget)
        ]
        self.state = state
        self.factor = state.scale_factor
        settings["ui_scale_percent"] = state.final_percent
        self._applying = True
        loading_columns = self.window._loading_task_column_widths
        self.window._loading_task_column_widths = True
        try:
            apply_theme(QApplication.instance(), self.factor)
            scale_widget_tree(self.window, self.factor)
            for widget in QApplication.topLevelWidgets():
                if widget is not self.window and self.window.isAncestorOf(widget):
                    scale_widget_tree(widget, self.factor)
            self.window._ui_scale_factor = self.factor
            self.window._adapt_task_columns()
            self.window._layout_task_columns()
            if (
                reason == "manual-delta"
                and not self.window.isMaximized()
                and not self.window.isMinimized()
            ):
                width, height = target_window_size(
                    self.window.width(),
                    self.window.height(),
                    self.factor / old_factor,
                    available.width(),
                    available.height(),
                )
                self.window.resize(width, height)
                self._keep_on_screen(self.window, available)
                self.window._save_geometry()
            if reason == "manual-delta":
                for dialog, old_size in open_dialogs:
                    if not dialog.isMaximized():
                        dialog.resize(
                            *target_window_size(
                                old_size.width(),
                                old_size.height(),
                                self.factor / old_factor,
                                available.width(),
                                available.height(),
                            )
                        )
                        self._keep_on_screen(dialog, available)
            # Startup honors a restored window size; there is no automatic repositioning.
        finally:
            self.window._loading_task_column_widths = loading_columns
            self._applying = False

    @staticmethod
    def _keep_on_screen(window, available):
        frame = window.frameGeometry()
        extra_w = max(0, frame.width() - window.width())
        extra_h = max(0, frame.height() - window.height())
        window.resize(
            min(window.width(), available.width() - extra_w),
            min(window.height(), available.height() - extra_h),
        )
        frame = window.frameGeometry()
        window.move(
            max(
                available.x(),
                min(window.pos().x(), available.right() - frame.width() + 1),
            ),
            max(
                available.y(),
                min(window.pos().y(), available.bottom() - frame.height() + 1),
            ),
        )

    def scale_new_widgets(self, root):
        scale_widget_tree(root, self.factor)

    def widget_shown(self, watched):
        if self._applying:
            return
        if watched is self.window:
            self.install_hooks()
        elif isinstance(watched, (QDialog, QMenu)):
            self.scale_new_widgets(watched)
            if not watched.property("scaleSizeInitialized"):
                watched.setProperty("scaleSizeInitialized", True)
                if isinstance(watched, QDialog) and not watched.property(
                    "preserveScaleGeometry"
                ):
                    watched.resize(
                        round(watched.width() * self.factor),
                        round(watched.height() * self.factor),
                    )
