"""Widget-level tests: Ctrl+wheel, corner resize, cursor and persistence.

These run on the real X11 platform when DISPLAY is available and fall back to
Qt's offscreen platform in CI (see conftest.py). They exercise the same event
handlers the application uses, without the single-instance lock / event loop.
"""

import os
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt   # noqa: E402
from PySide6.QtGui import QMouseEvent, QWheelEvent             # noqa: E402
from PySide6.QtTest import QTest                                # noqa: E402
from PySide6.QtWidgets import QApplication                     # noqa: E402

import pulse_monitor as pm                                     # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture
def widget(qapp):
    try:
        os.unlink(pm.CONFIG_FILE)
    except OSError:
        pass
    w = pm.PulseWidget()
    w.move(100, 150)
    w.show()
    qapp.processEvents()
    yield w
    w.tray.hide()
    w.hide()
    w.deleteLater()
    qapp.processEvents()


def _send_wheel(w, notches, ctrl=True):
    local = QPointF(w.width() / 2, w.height() / 2)
    glob = QPointF(w.mapToGlobal(QPoint(int(w.width() / 2),
                                        int(w.height() / 2))))
    mods = Qt.ControlModifier if ctrl else Qt.NoModifier
    ev = QWheelEvent(local, glob, QPoint(0, 0), QPoint(0, int(notches * 120)),
                     Qt.NoButton, mods, Qt.NoScrollPhase, False)
    QApplication.sendEvent(w, ev)
    QApplication.processEvents()


def _settle_zoom(w, timeout=3.0):
    """Spin the event loop until the eased zoom animation reaches its target."""
    deadline = time.monotonic() + timeout
    while w._zoom_timer.isActive() and time.monotonic() < deadline:
        QTest.qWait(5)
    QApplication.processEvents()
    assert not w._zoom_timer.isActive(), "zoom animation did not settle"


def _send_move(w, local, buttons=Qt.NoButton):
    glob = w.mapToGlobal(local)
    ev = QMouseEvent(QEvent.MouseMove, QPointF(local), QPointF(glob),
                     Qt.NoButton, buttons, Qt.NoModifier)
    w.mouseMoveEvent(ev)


def _send_button(w, event_type, local, buttons):
    glob = w.mapToGlobal(local)
    ev = QMouseEvent(event_type, QPointF(local), QPointF(glob),
                     Qt.LeftButton if event_type == QEvent.MouseButtonPress
                     else Qt.NoButton, buttons, Qt.NoModifier)
    if event_type == QEvent.MouseButtonPress:
        w.mousePressEvent(ev)
    else:
        w.mouseReleaseEvent(ev)


# --------------------------------------------------------------- default size
def test_default_scale_and_geometry(widget):
    assert widget.scale == 1.0
    assert widget.size() == QSize(324, 275)
    assert widget.size() == widget._size_for_scale(1.0)


# --------------------------------------------------------------- Ctrl + wheel
def test_ctrl_wheel_steps_and_persists(widget):
    one = pm.clamp_scale(1.0 + pm.SCALE_STEP)
    two_back = pm.clamp_scale(1.0 - pm.SCALE_STEP)
    _send_wheel(widget, 1)
    _settle_zoom(widget)
    assert widget.scale == one
    assert widget.size() == widget._size_for_scale(one)
    assert pm.load_settings()["scale"] == one

    _send_wheel(widget, -2)
    _settle_zoom(widget)
    assert widget.scale == two_back
    assert widget.size() == widget._size_for_scale(two_back)


def test_wheel_zoom_is_anchored_under_the_pointer(widget):
    widget.move(100, 150)
    QApplication.processEvents()
    anchor = widget.mapToGlobal(QPoint(widget.width() // 2,
                                       widget.height() // 2))
    _send_wheel(widget, 1)
    _settle_zoom(widget)
    after = widget.mapToGlobal(QPoint(widget.width() // 2,
                                      widget.height() // 2))
    assert abs(after.x() - anchor.x()) <= 2
    assert abs(after.y() - anchor.y()) <= 2


def test_wheel_zoom_with_easing_disabled(widget, monkeypatch):
    monkeypatch.setattr(pm, "ZOOM_EASE_MS", 0)
    one = pm.clamp_scale(1.0 + pm.SCALE_STEP)
    _send_wheel(widget, 1)
    assert not widget._zoom_timer.isActive()
    assert widget.scale == one
    assert widget.size() == widget._size_for_scale(one)
    assert pm.load_settings()["scale"] == one


def test_plain_wheel_does_not_zoom(widget):
    _send_wheel(widget, 3, ctrl=False)
    assert widget.scale == 1.0
    assert widget.size() == QSize(324, 275)


def test_wheel_zoom_clamps_to_limits(widget):
    _send_wheel(widget, 100)
    _settle_zoom(widget)
    assert widget.scale == pm.SCALE_MAX
    assert widget.size() == widget._size_for_scale(pm.SCALE_MAX)

    _send_wheel(widget, -200)
    _settle_zoom(widget)
    assert widget.scale == pm.SCALE_MIN
    assert widget.size() == widget._size_for_scale(pm.SCALE_MIN)


# ------------------------------------------------------------------ font cap
def test_large_scale_jump_applies_exact_size(widget):
    # A fast 4x -> 0.5x drag must not be clamped by the previous layout
    # minimum (the layout is intentionally unconstrained).
    widget._apply_scale(4.0)
    assert widget.size() == widget._size_for_scale(4.0)
    widget._apply_scale(0.5)
    assert widget.size() == widget._size_for_scale(0.5)
    widget._apply_scale(4.0)
    assert widget.size() == widget._size_for_scale(4.0)


def test_scaling_in_place_keeps_position(widget):
    widget.move(120, 140)
    QApplication.processEvents()
    widget._apply_scale(2.0)
    assert widget.pos() == QPoint(120, 140)


def test_fonts_stop_at_twice_the_size(widget):
    widget._apply_scale(4.0)
    assert widget.size() == widget._size_for_scale(4.0)
    assert widget._title.font().pointSizeF() == 20.0   # 10 pt × 2
    assert widget.sub.font().pointSizeF() == 14.0      # 7 pt × 2
    assert widget._net_label.font().pointSizeF() == 14.0

    widget._apply_scale(2.5)
    assert widget._title.font().pointSizeF() == 20.0   # still capped
    assert widget.size().width() > widget._size_for_scale(2.0).width()

    widget._apply_scale(0.5)                            # below 1× text shrinks
    assert widget._title.font().pointSizeF() == 5.0
    assert widget.sub.font().pointSizeF() == 3.5


# -------------------------------------------------------------------- cursors
def test_corner_cursors_and_body_cursor(widget):
    w, h = widget.width(), widget.height()
    _send_move(widget, QPoint(2, 2))
    assert widget.cursor().shape() == Qt.SizeFDiagCursor
    _send_move(widget, QPoint(w - 3, 2))
    assert widget.cursor().shape() == Qt.SizeBDiagCursor
    _send_move(widget, QPoint(2, h - 3))
    assert widget.cursor().shape() == Qt.SizeBDiagCursor
    _send_move(widget, QPoint(w - 3, h - 3))
    assert widget.cursor().shape() == Qt.SizeFDiagCursor
    _send_move(widget, QPoint(w // 2, h // 2))
    assert widget.cursor().shape() == Qt.SizeAllCursor


def test_pin_keeps_resize_cursor_but_shows_arrow_on_body(widget):
    widget.pinned = True
    w, h = widget.width(), widget.height()
    _send_move(widget, QPoint(w // 2, h // 2))
    assert widget.cursor().shape() == Qt.ArrowCursor
    _send_move(widget, QPoint(w - 3, h - 3))
    assert widget.cursor().shape() == Qt.SizeFDiagCursor


# --------------------------------------------------------------- corner drag
@pytest.mark.parametrize("corner,dx,dy", [
    ("bottom-right", 120, 90),
    ("top-left", -120, -90),
    ("top-right", -120, 90),
    ("bottom-left", 120, -90),
])
def test_corner_drag_scales_and_anchors_opposite_corner(widget, corner, dx, dy):
    widget._apply_scale(1.0)
    widget.move(400, 300)
    QApplication.processEvents()
    start = widget.frameGeometry()

    local = QPoint(2 if "left" in corner else widget.width() - 3,
                   2 if "top" in corner else widget.height() - 3)
    start_global = widget.mapToGlobal(local)
    _send_button(widget, QEvent.MouseButtonPress, local, Qt.LeftButton)
    assert widget._resize is not None

    target = start_global + QPoint(dx, dy)
    move_local = widget.mapFromGlobal(target)
    ev = QMouseEvent(QEvent.MouseMove, QPointF(move_local), QPointF(target),
                     Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    widget.mouseMoveEvent(ev)
    QApplication.processEvents()

    expected = pm.corner_drag_scale(corner, dx, dy, widget._base_size.width(),
                                    widget._base_size.height(), 1.0)
    assert widget.scale == expected
    assert widget.size() == widget._size_for_scale(expected)

    # The opposite corner has not moved.
    if "left" in corner:
        assert widget.x() + widget.width() == start.x() + start.width()
    else:
        assert widget.x() == start.x()
    if "top" in corner:
        assert widget.y() + widget.height() == start.y() + start.height()
    else:
        assert widget.y() == start.y()

    _send_button(widget, QEvent.MouseButtonRelease, QPoint(0, 0), Qt.NoButton)
    assert widget._resize is None
    assert pm.load_settings()["scale"] == expected


def test_pin_still_allows_zoom(widget):
    widget.pinned = True
    _send_wheel(widget, 1)
    _settle_zoom(widget)
    assert widget.scale == pm.clamp_scale(1.0 + pm.SCALE_STEP)


def test_pin_locks_moving_but_not_resizing(widget):
    widget.pinned = True
    start_pos = widget.pos()
    _send_button(widget, QEvent.MouseButtonPress,
                 QPoint(widget.width() // 2, widget.height() // 2), Qt.LeftButton)
    ev = QMouseEvent(QEvent.MouseMove,
                     QPointF(widget.width() // 2, widget.height() // 2),
                     QPointF(widget.mapToGlobal(
                         QPoint(widget.width() // 2, widget.height() // 2))
                         + QPoint(60, 60)),
                     Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    widget.mouseMoveEvent(ev)
    _send_button(widget, QEvent.MouseButtonRelease, QPoint(0, 0), Qt.NoButton)
    assert widget.pos() == start_pos

    local = QPoint(widget.width() - 3, widget.height() - 3)
    start_global = widget.mapToGlobal(local)
    _send_button(widget, QEvent.MouseButtonPress, local, Qt.LeftButton)
    target = start_global + QPoint(80, 60)
    ev = QMouseEvent(QEvent.MouseMove, QPointF(widget.mapFromGlobal(target)),
                     QPointF(target), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    widget.mouseMoveEvent(ev)
    _send_button(widget, QEvent.MouseButtonRelease, QPoint(0, 0), Qt.NoButton)
    assert widget.scale > 1.0


# --------------------------------------------------------------- persistence
def test_scale_and_position_restore_after_reload(widget, qapp):
    widget._apply_scale(1.5)
    widget.move(120, 140)
    widget._persist()

    loaded = pm.load_settings()
    assert loaded["scale"] == 1.5
    assert (loaded["x"], loaded["y"]) == (120, 140)

    w2 = pm.PulseWidget()
    try:
        assert w2.scale == 1.5
        assert w2.size() == w2._size_for_scale(1.5)
        assert w2.pos() == QPoint(120, 140)
    finally:
        w2.tray.hide()
        w2.hide()
        w2.deleteLater()
        qapp.processEvents()
