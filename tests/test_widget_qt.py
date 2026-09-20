"""Tests for the Qt transparent widget (tests need PySide6; skipped otherwise)."""

import os

import pytest

pyside6 = pytest.importorskip("PySide6")

# Paint offscreen so the tests never touch a real display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ollama_usage.widget import THEMES  # noqa: E402
from ollama_usage.widget_qt import TransparentWidget  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _sample_data() -> dict:
    return {
        "plan": "pro",
        "session": {"used_pct": 2.6, "resets_at": "2026-09-21T00:00:00Z"},
        "weekly": {"used_pct": 1.9, "resets_at": "2026-09-21T00:00:00Z"},
        "web_search_requests": 46,
        "web_fetch_requests": 0,
        "credit_balance": 4.42,
        "models": [],
    }


def _bare_widget(qapp, data: dict | None) -> TransparentWidget:
    """A TransparentWidget without __init__ (no timers, threads or window)."""
    w = TransparentWidget.__new__(TransparentWidget)
    w._theme = THEMES["dark"]
    w._size = "compact"
    w._autorefresh = True
    w._credit_alert = None
    w._data = data
    w._error = None
    return w


def test_compact_window_auto_fits(qapp):
    w = _bare_widget(qapp, _sample_data())
    w_px, _h = w._window_size()
    # The line hugs its content; the old fixed fallback width was 560.
    assert 0 < w_px < 560


def test_compact_paint_stays_inside_window(qapp, monkeypatch):
    w = _bare_widget(qapp, _sample_data())
    win_w, win_h = w._window_size()

    painted = []

    def spy_draw_text(painter, x, y, rect_w, text, color, font, align_right=False):
        painted.append((x, rect_w, text))

    monkeypatch.setattr(w, "_draw_text", spy_draw_text)

    pixmap = QPixmap(win_w, win_h)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        w._paint_compact(painter, w._theme)
    finally:
        painter.end()

    assert painted, "compact paint drew nothing"
    # Regression: with the fixed 560 px paint box the indicator letter ("A")
    # was anchored beyond the auto-fitted window and clipped off-screen.
    for x, rect_w, text in painted:
        assert x + rect_w <= win_w, (
            f"text {text!r} drawn at x={x}+{rect_w} exceeds window {win_w}"
        )
