"""Global scale model, persistence, geometry policy and full-width columns."""

import json

import pytest
from PySide6.QtWidgets import QApplication

from app.core.settings_store import SettingsStore
from app.services.table_columns import distribute_width, resize_within_width
from app.services.ui_scale_service import resolve_ui_scale, target_window_size
from app.ui.main_window import MainWindow
from app.ui.task_dialog import TaskDialog
from app.ui.theme import build_stylesheet


@pytest.mark.parametrize(
    "screen,delta,expected",
    [
        ((2560, 1440, 96), 0, (100, 100)),
        ((1280, 720, 96), 0, (70, 70)),
        ((1280, 720, 96), -50, (70, 35)),
        ((2560, 1440, 96), 50, (100, 150)),
        ((5120, 2880, 96), 50, (200, 300)),
        ((1280, 720, 192), 0, (100, 100)),
    ],
)
def test_owner_scale_formula(screen, delta, expected):
    state = resolve_ui_scale(*screen, delta)
    assert (state.auto_percent, state.final_percent) == expected
    assert state.scale_factor == state.final_percent / 100


@pytest.mark.parametrize(
    "data,delta",
    [
        ({}, 0),
        ({"ui_scale_percent": 130}, 30),
        ({"ui_scale_delta_percent": 900}, 50),
        ({"ui_scale_delta_percent": "bad"}, 0),
        ({"ui_scale_delta_percent": -100}, -50),
    ],
)
def test_scale_settings_migration_and_roundtrip(tmp_path, data, delta):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    store = SettingsStore(path)
    assert store.settings["ui_scale_mode"] == "auto"
    assert store.settings["ui_scale_delta_percent"] == delta
    store.save()
    assert SettingsStore(path).settings["ui_scale_delta_percent"] == delta


def test_qss_scales_controls_fonts_and_indicators():
    normal, large = build_stylesheet(), build_stylesheet(1.5)
    assert "font-size: 10pt" in normal and "font-size: 15pt" in large
    assert "width: 16px" in normal and "width: 24px" in large
    assert "padding: 6px 12px" in normal and "padding: 9px 18px" in large
    assert target_window_size(900, 700, 1.5, 1200, 900) == (1200, 900)


@pytest.mark.parametrize("total", [250, 500, 900, 1500])
def test_columns_fill_viewport_and_drag_never_changes_total(total):
    widths = distribute_width(total, [240, 80, 150, 100, 120, 130], 36)
    assert sum(widths) == total
    for column in range(6):
        for requested in (0, 100, 9999):
            result = resize_within_width(widths, column, requested, 36)
            assert sum(result) == total
            assert min(result) >= 36


def test_manual_scale_changes_layout_dialogs_rows_and_retains_columns(
    tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        MainWindow, "_create_tray_icon", lambda self: setattr(self, "tray_icon", None)
    )
    window = MainWindow(SettingsStore(tmp_path / "settings.json"))
    window.scheduler_timer.stop()
    window.show()
    app.processEvents()
    for delta in (-50, 0, 50, 0):
        window.ui_scale_combo.setCurrentIndex(window.ui_scale_combo.findData(delta))
        app.processEvents()
        assert window.table.horizontalHeader().length() == window.table.viewport().width()
    assert [window.ui_scale_combo.itemData(i) for i in range(11)] == list(
        range(-50, 51, 10)
    )
    initial = window._ui_scale_factor
    margin = window.centralWidget().layout().contentsMargins().left()
    dialog = TaskDialog(parent=window, remote_names=["test"])
    dialog.show()
    app.processEvents()
    window.ui_scale_combo.setCurrentIndex(window.ui_scale_combo.findData(20))
    app.processEvents()
    assert window._ui_scale_factor > initial
    assert window.centralWidget().layout().contentsMargins().left() > margin
    assert dialog.layout().contentsMargins().left() == round(
        24 * window._ui_scale_factor
    )
    assert window.table.horizontalHeader().length() == window.table.viewport().width()
    assert window.settings_store.settings["ui_scale_delta_percent"] == 20
    # Reapply the same scale: dimensions must not multiply again.
    current_margin = dialog.layout().contentsMargins().left()
    window.scale_runtime.apply("runtime")
    assert dialog.layout().contentsMargins().left() == current_margin
    resized = []
    monkeypatch.setattr(window, "resize", lambda *args: resized.append(args))
    window.scale_runtime.apply("screen-metrics")
    window.scale_runtime.apply("screen-topology")
    assert resized == []
    dialog.reject()
    window.close()
    window.deleteLater()
    app.processEvents()
