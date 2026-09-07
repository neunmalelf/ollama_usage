"""Per-pixel transparent desktop widget (PySide6/Qt).

Tk cannot do per-pixel transparency on X11/Wayland (``-transparentcolor`` is
a Windows-only Tk attribute), so ``--background-transparent`` uses this
Qt-based widget whenever PySide6 is importable. Colors, themes, sizes, the
text segmenting helpers and the state file are shared with the Tk widget in
:mod:`ollama_usage.widget`, so both backends stay visually identical.
"""

from __future__ import annotations

import logging
import os
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from ollama_usage.exceptions import AuthError, NetworkError, OllamaUsageError
from ollama_usage.scraper import get_usage, plan_display_name
from ollama_usage.widget import (
    _BAR_H,
    _BAR_W,
    _FONT,
    _LABEL_COLOR,
    _PAD,
    _PLAN_COLOR,
    _SESSION_PCT_COLOR,
    _TRANSPARENT_OPACITY,
    _VALUE_COLOR,
    _W_COMPACT,
    _W_FULL,
    POSITIONS,
    THEMES,
    _countdown_segments,
    _fit_compact_segments,
    _load_state,
    _mini_segments,
    _pct_color,
    _save_state,
    _seconds_until,
)

logger = logging.getLogger(__name__)


def _qcolor(color: str) -> QColor:
    return QColor(color)


def _font(point_size: int, bold: bool = False) -> QFont:
    f = QFont(_FONT, point_size)
    f.setBold(bold)
    return f


class _Callback:
    """Wrap a bound method so shiboken treats it as a generic callable.

    Nuitka-compiled methods are not CPython function objects. shiboken's
    signal machinery inspects slots with PyFunction_* APIs, which raise
    SystemError (funcobject.c:432) on them once extra packages are bundled
    (--include-package) - the menu connect then dies and the fetch timer
    never reschedules. A callable instance bypasses that inspection path
    entirely and swallows signal arguments (e.g. QAction.triggered's bool).
    """

    __slots__ = ("_fn",)

    def __init__(self, fn):
        self._fn = fn

    def __call__(self, *args, **kwargs):
        return self._fn()


class TransparentWidget(QWidget):
    """Frameless, always-on-top widget with a fully transparent background."""

    def __init__(
        self,
        cookie_fn,
        interval: int,
        theme: str,
        size: str | None,
        opacity: float | None,
        position: str | None,
        autorefresh: bool,
    ) -> None:
        # X11BypassWindowManagerHint = override-redirect, exactly like the Tk
        # widget: KWin then honors the restored position instead of applying
        # its own placement (which had moved the window to +54/+48 px).
        super().__init__(
            None,
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.X11BypassWindowManagerHint
            | Qt.Tool,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Deliver right-clicks as plain mousePressEvents instead of letting
        # Qt convert them into QContextMenuEvent dispatch - under Nuitka the
        # compiled QContextMenuEvent path was unreliable across environments.
        self.setContextMenuPolicy(Qt.PreventContextMenu)

        # Optional event debugging: set OLLAMA_USAGE_WIDGET_DEBUG=<path> and
        # the widget appends every mouse event and menu call there.
        debug_path = os.environ.get("OLLAMA_USAGE_WIDGET_DEBUG")
        self._dbg_stream = open(debug_path, "a", encoding="utf-8") if debug_path else None

        self._cookie_fn = cookie_fn
        self._cookie = cookie_fn()
        self._interval = max(10, interval)
        self._theme = THEMES.get(theme, THEMES["dark"])
        self._size = self._resolve_size(size)  # "compact" | "full"
        self._position = position
        self._autorefresh = autorefresh
        self._data: dict | None = None
        self._error: str | None = None
        self._is_fetching = threading.Event()
        self._is_running = True

        if opacity is None:
            opacity = _TRANSPARENT_OPACITY  # --background-transparent default
        self.setWindowOpacity(max(0.1, min(1.0, opacity)))

        self._apply_size()
        self._restore_position()

        # Fetch worker + main-thread poll (mirrors the Tk widget's flow).
        self._timer = QTimer(self)
        self._timer.timeout.connect(_Callback(self._poll_fetch))

        # Same shiboken callable-overload issue as the menu: use the standard
        # activated signal instead of the activated= kwarg (which raised
        # "Exception ignored ... funcobject.c:432" in the compiled binary).
        self._shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        self._shortcut.activated.connect(_Callback(self._quit))

        self._fetch_async()
        self.show()

    # ---------------------------------------------------------------- helpers

    def _indicator_letter(self) -> str:
        return "A" if self._autorefresh else "M"

    def _resolve_size(self, size: str | None) -> str:
        if size in ("compact", "full"):
            return size
        saved = _load_state().get("size")
        if saved in ("compact", "full"):
            return saved
        return "full"

    def _apply_size(self) -> None:
        w, h = _W_FULL if self._size == "full" else _W_COMPACT
        self.setFixedSize(w, h)

    def _toggle_size(self) -> None:
        self._size = "compact" if self._size == "full" else "full"
        self._save_position()
        self._apply_size()
        # Keep the widget fully on screen after the size change.
        screen = self.screen().availableGeometry()
        x = max(0, min(self.x(), screen.right() - self.width() - 10))
        y = max(0, min(self.y(), screen.bottom() - self.height() - 10))
        self.move(x, y)
        self.update()

    # ---------------------------------------------------------------- position

    def _restore_position(self) -> None:
        screen = self.screen().availableGeometry()
        ww, wh = self.width(), self.height()
        default_x, default_y = screen.right() - ww - 10, screen.top() + 10
        x, y = default_x, default_y

        if self._position and self._position in POSITIONS:
            x, y = POSITIONS[self._position](screen.width(), screen.height(), ww, wh)
        else:
            try:
                state = _load_state()
                saved_x = state.get("x", default_x)
                saved_y = state.get("y", default_y)
                if isinstance(saved_x, str) and saved_x.lstrip("-").isdigit():
                    saved_x = int(saved_x)
                if isinstance(saved_y, str) and saved_y.lstrip("-").isdigit():
                    saved_y = int(saved_y)
                if not isinstance(saved_x, int) or not isinstance(saved_y, int):
                    raise ValueError("State file contains non-integer coordinates")
                if 0 <= saved_x <= screen.width() - 20 and 0 <= saved_y <= screen.height() - 20:
                    x, y = saved_x, saved_y
            except Exception as e:
                logger.debug("Could not restore widget position: %s", e)

        x = max(0, min(x, screen.right() - ww - 10))
        y = max(0, min(y, screen.bottom() - wh - 10))
        self.move(x, y)

    def _save_position(self) -> None:
        state = _load_state()
        state["x"] = self.x()
        state["y"] = self.y()
        state["size"] = self._size
        _save_state(state)

    # ---------------------------------------------------------------- data

    def _fetch_async(self) -> None:
        if self._is_fetching.is_set():
            return
        self._is_fetching.set()
        threading.Thread(target=self._fetch, daemon=True, name="ollama-fetch-qt").start()
        self._timer.start(50)

    def _poll_fetch(self) -> None:
        if not self._is_running:
            self._timer.stop()
            return
        if self._is_fetching.is_set():
            return
        self._timer.stop()
        self.update()
        QTimer.singleShot(self._interval * 1000, _Callback(self._fetch_async))

    def _fetch(self) -> None:
        try:
            self._data = get_usage(self._cookie)
            self._error = None
        except NetworkError:
            self._error = "Network error"
        except AuthError:
            try:
                logger.info("Widget: Cookie expired. Attempting to refresh...")
                self._cookie = self._cookie_fn()
                self._data = get_usage(self._cookie)
                self._error = None
            except Exception as refresh_exc:
                self._error = f"Auth error: {refresh_exc}"
        except OllamaUsageError as exc:
            self._error = str(exc)
        except Exception as exc:
            self._error = f"Error: {exc}"
        finally:
            self._is_fetching.clear()

    # ---------------------------------------------------------------- drawing

    def _draw_segments(self, painter: QPainter, x: int, y: int,
                       segments: list[tuple[str, str]], font: QFont) -> None:
        painter.setFont(font)
        metrics = QFontMetrics(font)
        for text, color in segments:
            painter.setPen(_qcolor(color))
            painter.drawText(x, y, metrics.height() * 4 + metrics.horizontalAdvance(text),
                             metrics.height() * 2, int(Qt.AlignLeft | Qt.AlignTop | Qt.TextSingleLine), text)
            x += metrics.horizontalAdvance(text)

    def _draw_text(self, painter: QPainter, x: int, y: int, w: int, text: str,
                   color: str, font: QFont, align_right: bool = False) -> None:
        painter.setPen(_qcolor(color))
        painter.setFont(font)
        rect_flags = int(Qt.AlignTop | Qt.TextSingleLine
                         | (Qt.AlignRight if align_right else Qt.AlignLeft))
        rect_w = max(QFontMetrics(font).horizontalAdvance(text) + 2, 1)
        # For right alignment the rect must end at x + w (e.g. the indicator
        # letter at the widget's right edge, the percentage at the bar end);
        # anchoring it at x would render the text at the left side instead.
        rect_x = x + (w - rect_w) if align_right else x
        painter.drawText(rect_x, y, rect_w, QFontMetrics(font).height() * 2, rect_flags, text)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        t = self._theme
        if self._size == "compact":
            self._paint_compact(painter, t)
        else:
            self._paint_full(painter, t)

    def _paint_compact(self, painter: QPainter, t: dict) -> None:
        w, h = _W_COMPACT
        p = 10  # padding (room before the indicator letter)

        if self._error or not self._data:
            msg = self._error or "Loading…"
            painter.setPen(_qcolor(t["red"] if self._error else t["sub"]))
            painter.setFont(_font(9))
            painter.drawText(0, 0, w, h, int(Qt.AlignCenter), msg)
            return

        indicator = self._indicator_letter()
        font = _font(8)
        metrics = QFontMetrics(font)
        # The line starts at x=p; reserve padding plus the indicator + a gap.
        max_x = w - 2 * p - metrics.horizontalAdvance(indicator) - 6
        segments = _fit_compact_segments(
            _mini_segments(self._data, t), t[_PLAN_COLOR],
            metrics.horizontalAdvance, max_x,
        )
        self._draw_segments(painter, p, p, segments, font)

        dot = t["green"] if self._data and not self._error else t["red"]
        self._draw_text(painter, 0, p, w - p, indicator, dot, _font(8), align_right=True)

    def _paint_full(self, painter: QPainter, t: dict) -> None:
        w, h = _W_FULL
        p = _PAD
        bw = _BAR_W
        bh = _BAR_H
        bar_x = (w - bw) // 2

        # Header: "ollama · " prefix, then the plan name.
        plan = plan_display_name(self._data["plan"]) if self._data else "—"
        prefix_font = _font(8)
        metrics = QFontMetrics(prefix_font)
        self._draw_text(painter, p, p, metrics.horizontalAdvance("ollama · "),
                        "ollama · ", t["sub"], prefix_font)
        prefix_x2 = p + metrics.horizontalAdvance("ollama · ")
        indicator = self._indicator_letter()
        plan_budget = (w - p - metrics.horizontalAdvance(indicator) - 6) - prefix_x2
        plan = "".join(
            text for text, _ in _fit_compact_segments(
                [(plan, t[_PLAN_COLOR])], t[_PLAN_COLOR],
                metrics.horizontalAdvance, plan_budget,
            )
        )
        self._draw_text(painter, prefix_x2, p, plan_budget, plan, t[_PLAN_COLOR], prefix_font)

        # Status indicator (A with autorefresh, M otherwise).
        dot = t["green"] if self._data and not self._error else t["red"]
        self._draw_text(painter, 0, p, w - p, indicator, dot, _font(8), align_right=True)

        if self._error or not self._data:
            msg = self._error or "Loading…"
            painter.setPen(_qcolor(t["red"] if self._error else t["sub"]))
            painter.setFont(_font(9))
            painter.drawText(0, 0, w, h, int(Qt.AlignCenter), msg)
            return

        y = p + 22
        label_font = _font(9, bold=True)
        small_font = _font(8)
        for label, pct, iso in [
            ("Session", self._data["session"]["used_pct"], self._data["session"]["resets_at"]),
            ("Weekly",  self._data["weekly"]["used_pct"],  self._data["weekly"]["resets_at"]),
        ]:
            bar_color = _pct_color(pct, t)
            pct_color = t[_SESSION_PCT_COLOR] if label == "Session" else bar_color
            secs = _seconds_until(iso)

            # Label (left) + percentage (right, overlaid " %" in label color).
            self._draw_text(painter, bar_x, y, bw, label, t["fg"], label_font)
            self._draw_text(painter, bar_x, y, bw, f"{pct:.1f} %", pct_color,
                            label_font, align_right=True)
            self._draw_text(painter, bar_x, y, bw, " %", t[_LABEL_COLOR],
                            label_font, align_right=True)
            y += 14

            # Bar background + fill.
            painter.setPen(Qt.NoPen)
            painter.setBrush(_qcolor(t["bar_bg"]))
            painter.drawRect(bar_x, y, bw, bh)
            filled = int(bw * min(pct, 100.0) / 100.0)
            if filled > 0:
                painter.setBrush(_qcolor(bar_color))
                painter.drawRect(bar_x, y, filled, bh)
            painter.setBrush(Qt.NoBrush)
            y += bh + 5

            # Countdown.
            metrics = QFontMetrics(small_font)
            self._draw_text(painter, bar_x, y, bw, "resets in ", t["sub"], small_font)
            px2 = bar_x + metrics.horizontalAdvance("resets in ")
            self._draw_segments(
                painter, px2, y, _countdown_segments(secs, t), small_font,
            )
            y += 20

        ws = self._data.get("web_search_requests")
        if ws is not None:
            self._draw_segments(
                painter, bar_x, y,
                [("Web search requests: ", t["sub"]), (str(ws), t[_VALUE_COLOR])],
                small_font,
            )

        wr = self._data.get("web_fetch_requests")
        if wr is not None:
            self._draw_segments(
                painter, bar_x, y + 18,
                [("Web fetch requests:  ", t["sub"]), (str(wr), t[_VALUE_COLOR])],
                small_font,
            )

    # ---------------------------------------------------------------- interaction

    def _dbg(self, msg: str) -> None:
        if self._dbg_stream is not None:
            self._dbg_stream.write(f"{msg}\n")
            self._dbg_stream.flush()

    def mousePressEvent(self, event) -> None:
        self._dbg(f"press button={event.button()}")
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif event.button() == Qt.RightButton:
            # With PreventContextMenu the right-click arrives here directly.
            self._show_menu(event.globalPosition().toPoint())

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # Kept as a safety net for environments where the policy conversion
        # still applies. The menu must not exec() from inside the handler
        # (nested event loop conflicts with the ongoing dispatch on X11);
        # defer it to the next event-loop iteration instead.
        pos = event.globalPos()
        QTimer.singleShot(0, _Callback(lambda: self._show_menu(pos)))

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
            self._save_position()

    def _show_menu(self, global_pos) -> None:
        self._dbg(f"menu open at {global_pos}")
        t = self._theme
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {t['bg']}; color: {t['fg']};"
            f" border: none; }}"
            f"QMenu::item:selected {{ background-color: {t['bar_bg']}; }}"
        )
        # Do NOT pass compiled methods to shiboken's connect: with extra
        # packages bundled (--include-package) it inspects slots with CPython
        # PyFunction_* APIs, which raise SystemError (funcobject.c:432) on
        # Nuitka-compiled methods and the menu never shows. _Callback wraps
        # each slot as a generic callable, which shiboken handles fine.
        act_refresh = menu.addAction("⟳  Refresh now")
        act_refresh.triggered.connect(_Callback(self._fetch_async))
        act_toggle = menu.addAction("⇅  Toggle size")
        act_toggle.triggered.connect(_Callback(self._toggle_size))
        menu.addSeparator()
        act_close = menu.addAction("✕  Close")
        act_close.triggered.connect(_Callback(self._quit))
        # popup() is non-blocking (no nested event loop) and parented to this
        # widget, so it stays alive and interactive. exec() proved unreliable
        # in the compiled binary across the bundled Qt builds.
        menu.popup(global_pos)

    def _quit(self) -> None:
        self._is_running = False
        self._timer.stop()
        try:
            self._save_position()
        except Exception:
            pass
        self.close()
        QApplication.quit()


def launch_widget_qt(
    cookie,
    interval: int = 30,
    theme: str = "dark",
    size: str | None = None,
    opacity: float | None = None,
    position: str | None = None,
    autorefresh: bool = False,
) -> None:
    """Launch the per-pixel transparent (PySide6) Ollama quota widget."""
    # The Tk widget is X11-only anyway, so run under XWayland too: absolute
    # positioning (position save/restore) only works on the xcb platform.
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    # Work in physical pixels 1:1 like Tk: the shared state file stores the
    # widget position/size in X pixels, and Qt's HiDPI scaling (e.g. the
    # 145% Plasma scale) would otherwise inflate the geometry and offset the
    # restored position.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")

    app = QApplication.instance() or QApplication([])
    cookie_fn = cookie if callable(cookie) else (lambda _c=cookie: _c)
    widget = TransparentWidget(
        cookie_fn=cookie_fn,
        interval=interval,
        theme=theme,
        size=size,
        opacity=opacity,
        position=position,
        autorefresh=autorefresh,
    )
    # Keep a reference for the lifetime of the event loop (parentless widget).
    app._ollama_widget = widget
    app.exec()
