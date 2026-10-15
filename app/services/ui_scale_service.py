"""Owner's screen-adaptive UI scale model, independent of Qt."""

from dataclasses import dataclass
import math


def _number(value, default: float) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError, OverflowError):
        return default


def rounded(value: float, step: int) -> int:
    return int(math.floor(value / step + 0.5) * step)


def normalize_delta(value) -> int:
    return max(-50, min(50, rounded(_number(value, 0), 10)))


def normalize_scale_settings(settings: dict, loaded: dict | None = None) -> None:
    original = settings if loaded is None else loaded
    delta = original.get("ui_scale_delta_percent")
    if delta is None:
        delta = _number(original.get("ui_scale_percent", 100), 100) - 100
    settings.update(
        ui_scale_mode="auto",
        ui_scale_delta_percent=normalize_delta(delta),
        ui_scale_percent=max(
            35,
            min(300, rounded(_number(original.get("ui_scale_percent", 100), 100), 5)),
        ),
    )


@dataclass(frozen=True)
class UIScaleState:
    auto_percent: int
    delta_percent: int
    final_percent: int
    scale_factor: float


def resolve_ui_scale(width: float, height: float, dpi: float, delta=0) -> UIScaleState:
    dpi = max(1, _number(dpi, 96))
    ratio = min(max(1, width) * dpi / 96 / 2560, max(1, height) * dpi / 96 / 1440)
    auto = max(70, min(200, rounded(ratio * 100, 10)))
    delta = normalize_delta(delta)
    final = max(35, min(300, rounded(auto + max(auto, 100) * delta / 100, 5)))
    return UIScaleState(auto, delta, final, final / 100)


def scale_px(value: float, factor: float) -> int:
    return 0 if value == 0 else max(1, round(value * factor))


def target_window_size(width, height, ratio, available_width, available_height):
    return (
        min(round(width * ratio), available_width),
        min(round(height * ratio), available_height),
    )
