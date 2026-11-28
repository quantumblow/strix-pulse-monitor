"""Unit tests for the pure geometry / scale helpers behind window scaling."""

import json
import math

import pytest

pytest.importorskip("PySide6")

import pulse_monitor as pm                                     # noqa: E402
from PySide6.QtCore import QPoint                              # noqa: E402


# ---------------------------------------------------------------- scale range
def test_clamp_scale_defaults_and_bounds():
    assert pm.clamp_scale(0.1) == pm.SCALE_MIN
    assert pm.clamp_scale(9) == pm.SCALE_MAX
    assert pm.clamp_scale(1.234) == 1.23
    assert pm.clamp_scale("1.5") == 1.5
    assert pm.clamp_scale("nonsense") == pm.DEFAULT_SCALE
    assert pm.clamp_scale(None) == pm.DEFAULT_SCALE
    assert pm.clamp_scale(math.nan) == pm.DEFAULT_SCALE
    assert pm.clamp_scale(math.inf) == pm.DEFAULT_SCALE


def test_zoom_step_is_five_percent_per_notch():
    assert pm.zoomed_scale(1.0, 1) == 1.05
    assert pm.zoomed_scale(1.0, 2) == 1.10
    assert pm.zoomed_scale(2.0, -4) == 1.80
    # ... and stays inside the allowed range.
    assert pm.zoomed_scale(pm.SCALE_MAX, 1) == pm.SCALE_MAX
    assert pm.zoomed_scale(pm.SCALE_MIN, -1) == pm.SCALE_MIN


def test_font_scale_caps_at_twice_but_shrinks_with_the_window():
    assert pm.capped_font_scale(0.5) == 0.5
    assert pm.capped_font_scale(1.0) == 1.0
    assert pm.capped_font_scale(1.99) == 1.99
    assert pm.capped_font_scale(2.0) == 2.0
    assert pm.capped_font_scale(3.0) == pm.FONT_SCALE_MAX
    assert pm.capped_font_scale(4.0) == pm.FONT_SCALE_MAX
    assert pm.scaled_point_size(8, 4.0) == 16
    assert pm.scaled_point_size(8, 2.0) == 16
    assert pm.scaled_point_size(8, 0.5) == 4
    assert pm.scaled_point_size(1, 0.5) == 1.0       # never below 1 pt


# --------------------------------------------------------------- resize grip
def test_resize_grip_clamps_to_10_24_px():
    assert pm.resize_grip(0.5) == 10
    assert pm.resize_grip(1.0) == 14
    assert pm.resize_grip(1.5) == 21
    assert pm.resize_grip(2.0) == 24
    assert pm.resize_grip(4.0) == 24


def test_resize_corner_hit_test():
    w, h = 324, 275
    grip = pm.resize_grip(1.0)
    assert grip == 14
    assert pm.resize_corner(QPoint(0, 0), w, h, 1.0) == "top-left"
    assert pm.resize_corner(QPoint(grip - 1, grip - 1), w, h, 1.0) == "top-left"
    assert pm.resize_corner(QPoint(w - 1, 0), w, h, 1.0) == "top-right"
    assert pm.resize_corner(QPoint(0, h - 1), w, h, 1.0) == "bottom-left"
    assert pm.resize_corner(QPoint(w - 1, h - 1), w, h, 1.0) == "bottom-right"
    # Edges (not corners) and the body are drag/zoom areas.
    assert pm.resize_corner(QPoint(grip + 1, 0), w, h, 1.0) is None
    assert pm.resize_corner(QPoint(0, grip + 1), w, h, 1.0) is None
    assert pm.resize_corner(QPoint(w // 2, h // 2), w, h, 1.0) is None
    # The hit zone scales down to 10 px on a 0.5× card.
    assert pm.resize_corner(QPoint(9, 9), 162, 137, 0.5) == "top-left"
    assert pm.resize_corner(QPoint(10, 10), 162, 137, 0.5) is None


def test_corner_drag_scale_is_uniform_and_clamped():
    bw, bh = pm.BASE_WIDTH, pm.layout_metrics(1.0)["height"]
    assert bw == 324 and bh == 275
    # Dragging exactly along the diagonal doubles the scale.
    assert pm.corner_drag_scale("bottom-right", bw, bh, bw, bh, 1.0) == 2.0
    assert pm.corner_drag_scale("top-left", -bw, -bh, bw, bh, 1.0) == 2.0
    assert pm.corner_drag_scale("top-right", bw, -bh, bw, bh, 1.0) == 2.0
    assert pm.corner_drag_scale("bottom-left", -bw, bh, bw, bh, 1.0) == 2.0
    # No movement keeps the current scale.
    assert pm.corner_drag_scale("bottom-right", 0, 0, bw, bh, 1.33) == 1.33
    # Clamped at both ends.
    assert pm.corner_drag_scale("bottom-right", 9999, 9999, bw, bh, 1.0) == 4.0
    assert pm.corner_drag_scale("top-left", 9999, 9999, bw, bh, 1.0) == 0.5


def test_corner_resize_keeps_opposite_corner_anchored():
    anchor = QPoint(400, 450)
    size = (300, 250)
    assert pm.corner_resize_pos("top-left", anchor, *size) == QPoint(100, 200)
    assert pm.corner_resize_pos("top-right", anchor, *size) == QPoint(400, 200)
    assert pm.corner_resize_pos("bottom-left", anchor, *size) == QPoint(100, 450)
    assert pm.corner_resize_pos("bottom-right", anchor, *size) == QPoint(400, 450)


# ------------------------------------------------------------ layout metrics
def test_layout_metrics_scale_exactly_and_keep_aspect():
    base = pm.layout_metrics(1.0)
    assert (base["width"], base["height"]) == (324, 275)
    for scale in (0.5, 1.0, 2.0, 4.0):
        m = pm.layout_metrics(scale)
        # Width is the source of truth; height follows within one px.
        assert abs(m["width"] - pm.BASE_WIDTH * scale) <= 1
        assert abs(m["height"] - base["height"] * scale) <= 2
        # The height is the sum of the fixed rows/margins, which is what the
        # widget actually lays out (no clipping at any scale).
        assert m["height"] == (
            m["margin_top"] + m["margin_bottom"] + m["header"]
            + 6 * m["spacing"] + 4 * m["meter"] + m["net_label"] + m["net_row"])


def test_font_cap_does_not_shrink_row_geometry():
    m2 = pm.layout_metrics(2.0)
    m4 = pm.layout_metrics(4.0)
    assert m4["meter"] == 2 * m2["meter"]
    assert m4["net_row"] == 2 * m2["net_row"]
    assert m4["width"] == 2 * m2["width"]


# ------------------------------------------------------------------ settings
def _redirect_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(pm, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(pm, "CONFIG_FILE", str(tmp_path / "settings.json"))


def test_scale_roundtrips_through_settings(monkeypatch, tmp_path):
    _redirect_settings(monkeypatch, tmp_path)
    pm.save_settings({"x": 10, "y": 20, "scale": 1.75})
    loaded = pm.load_settings()
    assert loaded["scale"] == 1.75
    assert loaded["x"] == 10 and loaded["y"] == 20


def test_invalid_scale_is_ignored_or_clamped(monkeypatch, tmp_path):
    _redirect_settings(monkeypatch, tmp_path)
    path = tmp_path / "settings.json"

    path.write_text(json.dumps({"scale": 99}), encoding="utf-8")
    assert pm.load_settings()["scale"] == pm.SCALE_MAX

    path.write_text(json.dumps({"scale": 0.01}), encoding="utf-8")
    assert pm.load_settings()["scale"] == pm.SCALE_MIN

    for bad in ("2", True, None):
        path.write_text(json.dumps({"scale": bad}), encoding="utf-8")
        assert "scale" not in pm.load_settings()

    # NaN parses as a float but is not a usable scale; it falls back to 1.0.
    path.write_text(json.dumps({"scale": math.nan}), encoding="utf-8")
    assert pm.load_settings()["scale"] == pm.DEFAULT_SCALE
