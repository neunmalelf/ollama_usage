"""Always-on-top desktop widget showing Ollama quota gauges.

Requires tkinter (stdlib). On minimal Linux installs:
    sudo apt install python3-tk
"""

from __future__ import annotations

import json
import logging
import pathlib
import threading
import tkinter as tk
from datetime import datetime, timezone

from typing import Callable
from ollama_usage.exceptions import NetworkError, OllamaUsageError, AuthError
from ollama_usage.scraper import get_usage, plan_display_name

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STATE_FILE = pathlib.Path.home() / ".ollama-usage-widget.json"

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "bg":     "#1e1e2e",
        "fg":     "#cdd6f4",
        "sub":    "#6c7086",
        "bar_bg": "#313244",
        "border": "#45475a",
        "green":  "#a6e3a1",
        "yellow": "#f9e2af",
        "red":    "#f38ba8",
        "orange": "#ff8700",
        "cyan":   "#89dceb",
        "magenta": "#f5c2e7",
        "white":  "#cdd6f4",
    },
    "light": {
        "bg":     "#eff1f5",
        "fg":     "#4c4f69",
        "sub":    "#9ca0b0",
        "bar_bg": "#ccd0da",
        "border": "#bcc0cc",
        "green":  "#40a02b",
        "yellow": "#df8e1d",
        "red":    "#d20f39",
        "orange": "#ff8700",
        "cyan":   "#04a5e5",
        "magenta": "#ea76cb",
        "white":  "#4c4f69",
    },
    "minimal": {
        "bg":     "#0a0a0a",
        "fg":     "#f0f0f0",
        "sub":    "#666666",
        "bar_bg": "#1a1a1a",
        "border": "#2a2a2a",
        "green":  "#00e676",
        "yellow": "#ffea00",
        "red":    "#ff1744",
        "orange": "#ff8700",
        "cyan":   "#00e5ff",
        "magenta": "#ff00ff",
        "white":  "#f0f0f0",
    },
}

#: Color name used for the plan value (shared across CLI, GUI and widget).
_PLAN_COLOR = "orange"

#: Named colors for the time components (shared across CLI, GUI and widget).
_DAYS_COLOR    = "yellow"
_HOURS_COLOR   = "cyan"
_MINUTES_COLOR = "magenta"
_SECONDS_COLOR = "magenta"
_VALUE_COLOR   = "cyan"
_LABEL_COLOR   = "white"

#: Color used for the session percentage (green, shown bold).
_SESSION_PCT_COLOR = "green"

POSITIONS = {
    "top-left":     lambda sw, sh, ww, wh: (10, 10),
    "top-right":    lambda sw, sh, ww, wh: (sw - ww - 10, 10),
    "bottom-left":  lambda sw, sh, ww, wh: (10, sh - wh - 50),
    "bottom-right": lambda sw, sh, ww, wh: (sw - ww - 10, sh - wh - 50),
}

# Widget dimensions
_W_COMPACT = (400, 30)
_W_FULL    = (240, 186)
_BAR_W     = 200
_BAR_H     = 8
_PAD       = 14
_FONT      = "Helvetica"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pct_color(pct: float, theme: dict) -> str:
    if pct < 50:
        return theme["green"]
    if pct < 80:
        return theme["yellow"]
    return theme["red"]


def _seconds_until(iso: str) -> int:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return max(0, int((dt - datetime.now(timezone.utc)).total_seconds()))
    except Exception:
        return 0


def _fmt_countdown(seconds: int) -> str:
    if seconds <= 0:
        return "now"
    h, rem = divmod(seconds, 3600)
    m, s   = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _countdown_segments(seconds: int, theme: dict) -> list[tuple[str, str]]:
    """Return the countdown as colored ``(text, color)`` segments.

    Days, hours and minutes numbers use the named time colors; the unit
    letters use the label color. Seconds are not shown for resets.
    """
    if seconds <= 0:
        return [("now", theme["sub"])]
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _   = divmod(rem, 60)
    segs: list[tuple[str, str]] = []
    if d:
        segs.append((f"{d}", theme[_DAYS_COLOR]))
        segs.append(("d", theme["sub"]))
        segs.append((" ", theme["sub"]))
    if d or h:
        segs.append((f"{h:02d}", theme[_HOURS_COLOR]))
        segs.append(("h", theme["sub"]))
        segs.append((" ", theme["sub"]))
    if m or not (d or h):
        segs.append((f"{m:02d}", theme[_MINUTES_COLOR]))
        segs.append(("m", theme["sub"]))
    return segs


def _mini_countdown_segments(seconds: int, theme: dict) -> list[tuple[str, str]]:
    """Return the countdown as ``[dd] hh:mm`` colored segments (minidisplay).

    Matches the CLI --minidisplay remaining-time format: days (when present)
    in the days color, hours in the hours color, minutes in the minutes color,
    and the ``:`` separator in the label color.
    """
    if seconds <= 0:
        return [("00:00", theme["sub"])]
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _   = divmod(rem, 60)
    segs: list[tuple[str, str]] = []
    if d:
        segs.append((f"{d}", theme[_DAYS_COLOR]))
        segs.append(("d", theme["sub"]))
        segs.append((" ", theme["sub"]))
    segs.append((f"{h:02d}", theme[_HOURS_COLOR]))
    segs.append((":", theme["sub"]))
    segs.append((f"{m:02d}", theme[_MINUTES_COLOR]))
    return segs


def _mini_segments(data: dict, theme: dict) -> list[tuple[str, str]]:
    """Return the minidisplay line as colored segments (no bars).

    ``olu (plan) s: <pct> (<left>) | w: <pct> (<left>) ws: <count> wr: <count>``
    """
    plan = plan_display_name(data.get("plan", "")) if data.get("plan") else "—"
    session = data.get("session") or {}
    weekly = data.get("weekly") or {}
    web_search = data.get("web_search_requests")
    web_fetch = data.get("web_fetch_requests")
    ws = "0" if web_search is None else str(web_search)
    wr = "0" if web_fetch is None else str(web_fetch)

    segs: list[tuple[str, str]] = []
    segs.append(("olu ", theme["sub"]))
    segs.append(("(", theme["sub"]))
    segs.append((plan, theme[_PLAN_COLOR]))
    segs.append((")", theme["sub"]))
    segs.append((" s: ", theme["sub"]))
    segs.append((f"{session.get('used_pct', 0.0):.1f}", theme[_SESSION_PCT_COLOR]))
    segs.append(("%", theme[_LABEL_COLOR]))
    segs.append((" (", theme["sub"]))
    segs.extend(_mini_countdown_segments(
        _seconds_until(session.get("resets_at", "")), theme
    ))
    segs.append((")", theme["sub"]))
    segs.append((" |", theme["sub"]))
    segs.append((" w: ", theme["sub"]))
    segs.append((f"{weekly.get('used_pct', 0.0):.1f}", _pct_color(weekly.get("used_pct", 0.0), theme)))
    segs.append(("%", theme[_LABEL_COLOR]))
    segs.append((" (", theme["sub"]))
    segs.extend(_mini_countdown_segments(
        _seconds_until(weekly.get("resets_at", "")), theme
    ))
    segs.append((")", theme["sub"]))
    segs.append((" ws: ", theme["sub"]))
    segs.append((ws, theme[_VALUE_COLOR]))
    segs.append((" wr: ", theme["sub"]))
    segs.append((wr, theme[_VALUE_COLOR]))
    return segs


def _load_state() -> dict:
    """Return the saved widget state dict, or an empty dict on failure."""
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        logger.debug("Could not load widget state: %s", _STATE_FILE)
    return {}


def _save_state(state: dict) -> None:
    """Persist the widget state (position + size) to disk."""
    try:
        _STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    except Exception:
        logger.debug("Could not save widget state: %s", _STATE_FILE)


def check_dependencies() -> None:
    """Vérifie les packages critiques avant de lancer l'UI."""
    import importlib.util
    import platform as _platform

    system = _platform.system()
    missing = []

    if importlib.util.find_spec("cryptography") is None:
        missing.append("cryptography")

    if system == "Windows" and importlib.util.find_spec("win32crypt") is None:
        missing.append("pywin32 (pour win32crypt)")

    if missing:
        raise RuntimeError(
            f"Dépendances manquantes : {', '.join(missing)}. "
            f"Installe-les avec : pip install {' '.join(['cryptography', 'pywin32'])}"
        )


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class OllamaWidget:
    """Frameless always-on-top Tkinter widget."""

    def __init__(
        self,
        cookie: str | Callable[[], str],
        interval: int   = 30,
        theme: str      = "dark",
        size: str | None = None,
        opacity: float  = 0.92,
        position: str | None = None,
        autorefresh: bool = False,
    ) -> None:
        self._cookie_fn   = cookie if callable(cookie) else lambda: cookie
        self._cookie      = self._cookie_fn()
        self._interval    = max(10, interval)
        self._theme       = THEMES.get(theme, THEMES["dark"])
        self._size        = self._resolve_size(size)  # "compact" | "full"
        self._opacity     = max(0.1, min(1.0, opacity))
        self._position    = position   # named anchor or None (restored)
        self._autorefresh = autorefresh  # True → "A" indicator, False → "M"
        self._data: dict | None  = None
        self._error: str | None  = None
        self._after_id: str | None = None
        self._is_running: bool = True
        self._is_fetching = threading.Event()  # thread-safe (remplace le bool)
        self._drag_x = self._drag_y = 0

        self._root = tk.Tk()
        self._canvas = tk.Canvas(self._root)
        self._menu   = tk.Menu(self._root, tearoff=0)

        self._setup_window()
        self._setup_canvas()
        self._setup_menu()
        self._restore_position()
        self._fetch_async()

    # ---------------------------------------------------------------- window

    def _setup_window(self) -> None:
        r = self._root
        r.overrideredirect(True)
        r.wm_attributes("-topmost", True)
        r.wm_attributes("-alpha", self._opacity)
        r.configure(bg=self._theme["bg"])
        r.resizable(False, False)
        r.title("ollama-usage")

    def _setup_canvas(self) -> None:
        t = self._theme
        w, h = _W_FULL if self._size == "full" else _W_COMPACT
        self._root.geometry(f"{w}x{h}")

        self._canvas.destroy()
        self._canvas = tk.Canvas(
            self._root, width=w, height=h,
            bg=t["bg"],
            highlightthickness=1,
            highlightbackground=t["border"],
        )
        self._canvas.pack(fill="both", expand=True)

        # Drag bindings on both root and canvas
        for widget in (self._root, self._canvas):
            widget.bind("<ButtonPress-1>",   self._on_drag_start)
            widget.bind("<B1-Motion>",       self._on_drag_motion)
            widget.bind("<ButtonRelease-1>", self._on_drag_end)
            widget.bind("<Button-3>",        self._show_menu)
            widget.bind("<Control-q>",       lambda _e: self._quit())
            widget.bind("<Control-Q>",       lambda _e: self._quit())

    def _setup_menu(self) -> None:
        t = self._theme
        m = self._menu
        m.configure(
            bg=t["bg"], fg=t["fg"],
            activebackground=t["bar_bg"],
            activeforeground=t["fg"],
            bd=0,
        )
        m.add_command(label="⟳  Refresh now",    command=self._fetch_async)
        m.add_command(label="⇅  Toggle size",    command=self._toggle_size)
        m.add_separator()
        m.add_command(label="✕  Close",          command=self._quit)

    # ---------------------------------------------------------------- drag

    def _on_drag_start(self, event: tk.Event) -> None:
        self._drag_x = event.x_root - self._root.winfo_x()
        self._drag_y = event.y_root - self._root.winfo_y()

    def _on_drag_motion(self, event: tk.Event) -> None:
        self._root.geometry(
            f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}"
        )

    def _on_drag_end(self, _: tk.Event) -> None:
        self._save_position()

    # ---------------------------------------------------------------- position

    def _resolve_size(self, size: str | None) -> str:
        """Return the widget size, falling back to the saved size."""
        if size in ("compact", "full"):
            return size
        saved = _load_state().get("size")
        if saved in ("compact", "full"):
            return saved
        return "full"

    def _restore_position(self) -> None:
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        ww, wh = _W_FULL if self._size == "full" else _W_COMPACT

        default_x, default_y = sw - ww - 10, 10
        x, y = default_x, default_y

        if self._position and self._position in POSITIONS:
            x, y = POSITIONS[self._position](sw, sh, ww, wh)
        else:
            try:
                state = _load_state()
                saved_x = state.get("x", default_x)
                saved_y = state.get("y", default_y)
                if not isinstance(saved_x, int) or not isinstance(saved_y, int):
                    raise ValueError("State file contains non-integer coordinates")
                if 0 <= saved_x <= sw - 20 and 0 <= saved_y <= sh - 20:
                    x, y = saved_x, saved_y
            except Exception as e:
                logger.debug("Could not restore widget position: %s", e)

        self._root.geometry(f"+{x}+{y}")

    def _save_position(self) -> None:
        state = _load_state()
        state["x"] = self._root.winfo_x()
        state["y"] = self._root.winfo_y()
        state["size"] = self._size
        _save_state(state)

    # ---------------------------------------------------------------- menu / toggle

    def _show_menu(self, event: tk.Event) -> None:
        try:
            if self._root.winfo_exists():
                self._menu.tk_popup(event.x_root, event.y_root)
        except tk.TclError:
            pass
        finally:
            # Release the grab so the menu closes once an item is selected.
            try:
                self._menu.grab_release()
            except tk.TclError:
                pass

    def _toggle_size(self) -> None:
        self._size = "compact" if self._size == "full" else "full"
        self._save_position()
        self._setup_canvas()
        self._draw()

    def _quit(self) -> None:
        self._is_running = False
        try:
            self._save_position()
        except Exception:
            pass
        self._root.destroy()
    # ---------------------------------------------------------------- data

    def _fetch_async(self) -> None:
        if self._is_fetching.is_set():  # déjà en cours → on skip
            return
        self._is_fetching.set()
        if self._after_id:
            self._root.after_cancel(self._after_id)
        threading.Thread(target=self._fetch, daemon=True, name="ollama-fetch").start()

    def _fetch(self) -> None:
        try:
            self._data  = get_usage(self._cookie)
            self._error = None
        except NetworkError:
            self._error = "Network error"
        except AuthError:
            try:
                logger.info("Widget: Cookie expired. Attempting to refresh...")
                self._cookie = self._cookie_fn()
                self._data  = get_usage(self._cookie)
                self._error = None
            except Exception as refresh_exc:
                self._error = f"Auth error: {refresh_exc}"
        except OllamaUsageError as exc:
            self._error = str(exc)
        finally:
            self._is_fetching.clear()  # libère le verrou dans tous les cas
            if self._is_running:
                try:
                    self._root.after(0, self._draw)
                    self._after_id = self._root.after(
                        self._interval * 1000, self._fetch_async
                    )
                except Exception:
                    pass

    # ---------------------------------------------------------------- drawing

    def _draw(self) -> None:
        self._canvas.delete("all")
        if self._size == "compact":
            self._draw_compact()
        else:
            self._draw_full()
    def _indicator_letter(self) -> str:
        """Return the top-right status letter: "A" when autorefreshing, "M" otherwise."""
        return "A" if self._autorefresh else "M"

    def _draw_segments(
        self, c: tk.Canvas, x: int, y: int,
        segments: list[tuple[str, str]], font: tuple,
    ) -> None:
        """Render colored text segments left-to-right, advancing ``x``."""
        for text, color in segments:
            item = c.create_text(x, y, text=text, anchor="nw",
                                 fill=color, font=font)
            _, _, x2, _ = c.bbox(item)
            x = x2

    def _draw_compact(self) -> None:
        c, t   = self._canvas, self._theme
        w, h   = _W_COMPACT
        p      = 10  # padding for the compact view (room before the "M" indicator)

        if self._error or not self._data:
            msg = self._error or "Loading…"
            c.create_text(w // 2, h // 2, text=msg, anchor="center",
                          fill=t["red"] if self._error else t["sub"],
                          font=(_FONT, 9))
            return

        # Status indicator (A with --autorefresh, M otherwise) — green when
        # data is fresh, red on error.
        dot = t["green"] if self._data and not self._error else t["red"]
        c.create_text(w - p, p, text=self._indicator_letter(), anchor="ne",
                      fill=dot, font=(_FONT, 8))

        # Minidisplay line (same layout as --minidisplay, no bars)
        self._draw_segments(c, p, p, _mini_segments(self._data, t), (_FONT, 8))

    def _draw_full(self) -> None:
        c, t   = self._canvas, self._theme
        w, h   = _W_FULL
        p      = _PAD
        bw     = _BAR_W
        bh     = _BAR_H
        bar_x  = (w - bw) // 2

        # Header
        plan = plan_display_name(self._data["plan"]) if self._data else "—"
        prefix_id = c.create_text(p, p, text="ollama · ", anchor="nw",
                                  fill=t["sub"], font=(_FONT, 8))
        _, _, prefix_x2, _ = c.bbox(prefix_id)
        c.create_text(prefix_x2, p, text=plan, anchor="nw",
                      fill=t[_PLAN_COLOR], font=(_FONT, 8))
        # Status indicator (A with --autorefresh, M otherwise) — green when
        # data is fresh, red on error.
        dot = t["green"] if self._data and not self._error else t["red"]
        c.create_text(w - p, p, text=self._indicator_letter(), anchor="ne",
                      fill=dot, font=(_FONT, 8))

        if self._error or not self._data:
            msg = self._error or "Loading…"
            c.create_text(w // 2, h // 2, text=msg, anchor="center",
                          fill=t["red"] if self._error else t["sub"],
                          font=(_FONT, 9))
            return

        y = p + 22
        for label, pct, iso in [
            ("Session", self._data["session"]["used_pct"], self._data["session"]["resets_at"]),
            ("Weekly",  self._data["weekly"]["used_pct"],  self._data["weekly"]["resets_at"]),
        ]:
            bar_color = _pct_color(pct, t)
            # Session percentage is always green (bold); weekly stays severity-colored.
            pct_color = t[_SESSION_PCT_COLOR] if label == "Session" else bar_color
            secs      = _seconds_until(iso)

            # Label + percentage (the % uses the label color, with a space
            # before it so the number does not overwrite the %)
            c.create_text(bar_x,      y, text=label,       anchor="nw",
                          fill=t["fg"], font=(_FONT, 9, "bold"))
            # Number in the pct color; the " %" (space + %) overlaid in the
            # label color so the number never overwrites the %.
            c.create_text(bar_x + bw, y, text=f"{pct:.1f} %", anchor="ne",
                          fill=pct_color, font=(_FONT, 9, "bold"))
            c.create_text(bar_x + bw, y, text=" %", anchor="ne",
                          fill=t[_LABEL_COLOR], font=(_FONT, 9, "bold"))
            y += 14

            # Bar background
            c.create_rectangle(bar_x, y, bar_x + bw, y + bh,
                                fill=t["bar_bg"], outline="", width=0)
            # Bar fill
            filled = int(bw * min(pct, 100.0) / 100.0)
            if filled > 0:
                c.create_rectangle(bar_x, y, bar_x + filled, y + bh,
                                   fill=bar_color, outline="", width=0)
            y += bh + 5

            # Countdown
            prefix = c.create_text(bar_x, y, text="resets in ", anchor="nw",
                                   fill=t["sub"], font=(_FONT, 8))
            _, _, px2, _ = c.bbox(prefix)
            self._draw_segments(
                c, px2, y, _countdown_segments(secs, t), (_FONT, 8)
            )
            y += 28

        ws = self._data.get("web_search_requests")
        if ws is not None:
            self._draw_segments(
                c, bar_x, y,
                [("Web search requests: ", t["sub"]), (str(ws), t[_VALUE_COLOR])],
                (_FONT, 8),
            )

        wr = self._data.get("web_fetch_requests")
        if wr is not None:
            self._draw_segments(
                c, bar_x, y + 18,
                [("Web fetch requests:  ", t["sub"]), (str(wr), t[_VALUE_COLOR])],
                (_FONT, 8),
            )

    # ---------------------------------------------------------------- run

    def run(self) -> None:
        self._root.mainloop()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def launch_widget(
    cookie: str | Callable[[], str],
    interval: int        = 30,
    theme: str           = "dark",
    size: str            = "full",
    opacity: float       = 0.92,
    position: str | None = None,
    autorefresh: bool    = False,
) -> None:
    """
    Launch the always-on-top Ollama quota widget.

    Args:
        cookie:     __Secure-session cookie value or callable to fetch/refresh it.
        interval:   Refresh interval in seconds (min 10).
        theme:      "dark" | "light" | "minimal".
        size:       "full" (bars + countdown) | "compact" (text only).
        opacity:    Window opacity between 0.1 and 1.0.
        position:   "top-left" | "top-right" | "bottom-left" | "bottom-right"
                    or None to restore last saved position.
        autorefresh: Whether to show the "A" (autorefresh) indicator; the
                    "M" (manual) indicator is shown when False.
    """
    check_dependencies()
    try:
        import tkinter  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "tkinter is not available. "
            "On Linux, install it with: sudo apt install python3-tk"
        )

    OllamaWidget(
        cookie=cookie,
        interval=interval,
        theme=theme,
        size=size,
        opacity=opacity,
        position=position,
        autorefresh=autorefresh,
    ).run()