"""Simple cross-platform GUI window showing Ollama quota usage.

Uses tkinter (Python stdlib) so it works on Windows, Linux and macOS.
On minimal Linux installs you may need:
    sudo apt install python3-tk
"""

from __future__ import annotations

import json
import logging
import pathlib
import sys
import threading
import tkinter as tk
from datetime import datetime, timezone
from typing import Callable

from ollama_usage import __version__ as _pkg_version
from ollama_usage.exceptions import AuthError, NetworkError, OllamaUsageError
from ollama_usage.scraper import get_usage

logger = logging.getLogger(__name__)

APP_NAME = "ollama-usage"

# Application icon (ICO). Resolved relative to the package directory so it
# works both from a source checkout and an installed package.
_ICON_PATH = pathlib.Path(__file__).resolve().parent.parent / "icon.ico"

# State file used to persist the window size and position between runs.
_STATE_FILE = pathlib.Path.home() / ".ollama-usage-gui.json"

# Default window geometry (width x height). The width is chosen so the
# Session / Weekly lines (with their full ISO reset timestamps) are not
# truncated or wrapped.
_DEFAULT_GEOMETRY = "640x300"
_MIN_WIDTH = 360
_MIN_HEIGHT = 200

# ---------------------------------------------------------------------------
# Display content (pure, testable — no tkinter dependency)
# ---------------------------------------------------------------------------

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
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def build_lines(data: dict | None, error: str | None = None) -> list[str]:
    """Return the list of text lines to display in the GUI.

    Pure function (no tkinter) so it can be unit-tested headlessly.
    """
    if error:
        return [f"Error: {error}"]
    if not data:
        return ["Loading…"]

    lines: list[str] = []
    plan = data.get("plan", "—")
    lines.append(f"Plan     : {plan}")

    session = data.get("session") or {}
    weekly = data.get("weekly") or {}

    if session:
        pct = session.get("used_pct", 0.0)
        resets = session.get("resets_at", "")
        lines.append(
            f"Session  : {pct:.1f}% used - reset at {resets}"
            f" (in {_fmt_countdown(_seconds_until(resets))})"
        )
    if weekly:
        pct = weekly.get("used_pct", 0.0)
        resets = weekly.get("resets_at", "")
        lines.append(
            f"Weekly   : {pct:.1f}% used - reset at {resets}"
            f" (in {_fmt_countdown(_seconds_until(resets))})"
        )

    web_search = data.get("web_search_requests")
    if web_search is not None:
        lines.append(f"WebSearch: {web_search} request{'s' if web_search != 1 else ''}")

    models = data.get("models")
    if models:
        lines.append("Model calls this week:")
        for item in models:
            lines.append(f"          {item['requests']} {item['name']}")

    return lines


# ---------------------------------------------------------------------------
# Colored display content (pure, testable — no tkinter dependency)
# ---------------------------------------------------------------------------

# ANSI color names -> hex values (standard ANSI palette, matching the
# terminal version's default rendering). Used for the dark mode.
COLORS: dict[str, str] = {
    "orange":  "#ff8700",
    "green":   "#00d700",
    "yellow":  "#ffff00",
    "red":     "#ff0000",
    "cyan":    "#00ffff",
    "magenta": "#ff00ff",
    "white":   "#ffffff",
    "grey":    "#808080",
}

# On a light (white) background the cyan and white colors are hard to read,
# so they are substituted: cyan -> blue, white -> near-black, and green and
# grey are darkened for better contrast on white.
_LIGHT_COLORS: dict[str, str] = {
    **COLORS,
    "cyan":  "#0000ff",
    "white": "#1a1a1a",
    "green": "#008000",
    "grey":  "#404040",
}

#: Background / foreground colors per mode.
_BG_FG = {
    True:  {"bg": "#000000", "fg": "#ffffff"},  # dark mode
    False: {"bg": "#ffffff", "fg": "#000000"},  # light mode
}


def _theme_colors(dark: bool) -> dict[str, str]:
    """Return the color map for the given mode (dark or light)."""
    return COLORS if dark else _LIGHT_COLORS

#: Color used for a percentage value based on its severity (matches CLI).
def _pct_color_name(pct: float) -> str:
    if pct < 50:
        return "green"
    if pct < 80:
        return "yellow"
    return "red"


def _countdown_segments(seconds: int) -> list[tuple[str, str | None]]:
    """Return the countdown text as colored segments (numbers + unit labels).

    The days, hours and minutes slots are each a fixed 3-character width so the
    hours (and minutes) line up vertically between the Session and Weekly rows.
    Days number is orange, hours number cyan, minutes number magenta; the
    ``d``/``h``/``m`` unit labels are white.
    """
    if seconds <= 0:
        return [("now", None)]
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    segs: list[tuple[str, str | None]] = []

    def _slot(value: int, unit: str, color: str, show: bool) -> None:
        if show:
            segs.append((f"{value:>2}", color))
            segs.append((unit, "white"))
        else:
            segs.append(("   ", None))

    _slot(d, "d", "orange", bool(d))
    segs.append((" ", None))
    _slot(h, "h", "cyan", bool(d or h))
    segs.append((" ", None))
    _slot(m, "m", "magenta", True)
    return segs


def build_segments(
    data: dict | None, error: str | None = None
) -> list[list[tuple[str, str | None]]]:
    """Return the display content as colored segments.

    Each line is a list of ``(text, color_name)`` tuples where ``color_name``
    is a key of :data:`COLORS` or ``None`` for the default foreground.

    Pure function (no tkinter) so it can be unit-tested headlessly.
    """
    if error:
        return [[(f"Error: {error}", "red")]]
    if not data:
        return [[("Loading…", None)]]

    lines: list[list[tuple[str, str | None]]] = []
    plan = data.get("plan", "—")
    lines.append([("Plan     : ", None), (plan, "orange")])

    session = data.get("session") or {}
    weekly = data.get("weekly") or {}

    if session:
        pct = session.get("used_pct", 0.0)
        resets = session.get("resets_at", "")
        line: list[tuple[str, str | None]] = [
            ("Session  : ", None),
            (f"{pct:>5.1f}", _pct_color_name(pct)),
            ("%", "white"),
            (" used - reset at ", None),
            (resets, None),
            (" (in ", None),
        ]
        line.extend(_countdown_segments(_seconds_until(resets)))
        line.append((")", None))
        lines.append(line)

    if weekly:
        pct = weekly.get("used_pct", 0.0)
        resets = weekly.get("resets_at", "")
        line = [
            ("Weekly   : ", None),
            (f"{pct:>5.1f}", _pct_color_name(pct)),
            ("%", "white"),
            (" used - reset at ", None),
            (resets, None),
            (" (in ", None),
        ]
        line.extend(_countdown_segments(_seconds_until(resets)))
        line.append((")", None))
        lines.append(line)

    web_search = data.get("web_search_requests")
    if web_search is not None:
        lines.append(
            [
                ("WebSearch: ", None),
                (f"{web_search}", "cyan"),
                (f" request{'s' if web_search != 1 else ''}", None),
            ]
        )

    models = data.get("models")
    if models:
        lines.append([("Model calls this week:", "grey")])
        for item in sorted(models, key=lambda m: m.get("requests", 0), reverse=True):
            lines.append(
                [
                    ("           ", None),
                    (f"{item['requests']:>5}", "cyan"),
                    (f" {item['name']}", None),
                ]
            )

    return lines


# ---------------------------------------------------------------------------
# Window geometry persistence
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    """Return the saved GUI state dict, or an empty dict on failure."""
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        logger.debug("Could not load GUI state: %s", _STATE_FILE)
    return {}


def _save_state(state: dict) -> None:
    """Persist the GUI state (geometry + dark mode) to disk."""
    try:
        _STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    except Exception:
        logger.debug("Could not save GUI state: %s", _STATE_FILE)


def _load_geometry() -> str | None:
    """Return the saved window geometry string, or None if unavailable."""
    geom = _load_state().get("geometry")
    if isinstance(geom, str) and geom:
        return geom
    return None


def _save_geometry(geometry: str) -> None:
    """Persist the current window geometry (size + position) to disk."""
    state = _load_state()
    state["geometry"] = geometry
    _save_state(state)


def _load_darkmode() -> bool:
    """Return whether dark mode was enabled last time (default: off)."""
    value = _load_state().get("darkmode")
    if isinstance(value, bool):
        return value
    return False


def _save_darkmode(dark: bool) -> None:
    """Persist the dark mode preference."""
    state = _load_state()
    state["darkmode"] = dark
    _save_state(state)


# ---------------------------------------------------------------------------
# GUI window
# ---------------------------------------------------------------------------

class OllamaGui:
    """Simple Tkinter window with an OK button and a Refresh button."""

    def __init__(
        self,
        cookie: str | Callable[[], str],
        title: str | None = None,
    ) -> None:
        self._cookie_fn = cookie if callable(cookie) else lambda: cookie
        self._cookie = self._cookie_fn()
        self._data: dict | None = None
        self._error: str | None = None
        self._is_fetching = threading.Event()
        self._dark = _load_darkmode()
        self._colors = _theme_colors(self._dark)
        self._bg, self._fg = _BG_FG[self._dark].values()

        self._root = tk.Tk()
        self._root.title(title or f"{APP_NAME} ({_pkg_version})")
        self._root.resizable(True, True)
        self._root.minsize(_MIN_WIDTH, _MIN_HEIGHT)
        self._set_icon()

        saved = _load_geometry()
        self._root.geometry(saved or _DEFAULT_GEOMETRY)

        self._text = tk.Text(
            self._root,
            wrap="word",
            height=12,
            width=80,
            padx=10,
            pady=10,
            relief=tk.FLAT,
            bg=self._bg,
            fg=self._fg,
        )
        self._text.pack(fill="both", expand=True, padx=8, pady=8)

        # Configure one text tag per color so segments can be colored.
        for name, hex_color in self._colors.items():
            self._text.tag_configure(name, foreground=hex_color)

        buttons = tk.Frame(self._root, bg=self._bg)
        buttons.pack(fill="x", padx=8, pady=(0, 8))

        # Both buttons share the same width so they line up.
        self._refresh_btn = tk.Button(
            buttons, text="Refresh", underline=0, width=10, command=self._refresh,
            bg=self._bg, fg=self._fg, activebackground=self._bg, activeforeground=self._fg,
        )
        self._refresh_btn.pack(side="left", padx=4)

        # Dark mode checkbox between the two buttons.
        self._dark_var = tk.BooleanVar(value=self._dark)
        self._dark_ck = tk.Checkbutton(
            buttons, text="darkmode", underline=0, variable=self._dark_var,
            command=self._toggle_dark, bg=self._bg, fg=self._fg,
            activebackground=self._bg, activeforeground=self._fg,
            selectcolor=self._bg,
        )
        self._dark_ck.pack(side="left", padx=4)

        self._ok_btn = tk.Button(
            buttons, text="OK", underline=0, width=10, command=self._quit,
            bg=self._bg, fg=self._fg, activebackground=self._bg, activeforeground=self._fg,
        )
        self._ok_btn.pack(side="right", padx=4)

        # Keyboard shortcuts: Alt+r to refresh, Alt+o or Enter to close,
        # Alt+d to toggle dark mode.
        self._root.bind("<Alt-r>", self._on_refresh_key)
        self._root.bind("<Alt-Key-r>", self._on_refresh_key)
        self._root.bind("<Alt-o>", self._on_quit_key)
        self._root.bind("<Alt-Key-o>", self._on_quit_key)
        self._root.bind("<Return>", self._on_quit_key)
        self._root.bind("<Escape>", self._on_quit_key)
        self._root.bind("<Alt-d>", self._on_dark_key)
        self._root.bind("<Alt-Key-d>", self._on_dark_key)

        self._fetch_async()

    # ---------------------------------------------------------------- data

    def _set_icon(self) -> None:
        """Set the window icon from icon.ico if it exists (best-effort)."""
        try:
            if _ICON_PATH.is_file():
                self._root.iconbitmap(str(_ICON_PATH))
        except Exception:
            logger.debug("Could not set window icon: %s", _ICON_PATH)

    def _refresh(self) -> None:
        self._fetch_async()

    def _on_refresh_key(self, _event: tk.Event) -> str:
        self._refresh()
        return "break"

    def _on_quit_key(self, _event: tk.Event) -> str:
        self._quit()
        return "break"

    def _on_dark_key(self, _event: tk.Event) -> str:
        self._dark_var.set(not self._dark_var.get())
        self._toggle_dark()
        return "break"

    # ---------------------------------------------------------------- theme

    def _toggle_dark(self) -> None:
        """Toggle dark mode, update colors/background and redraw."""
        self._dark = bool(self._dark_var.get())
        _save_darkmode(self._dark)
        self._colors = _theme_colors(self._dark)
        self._bg, self._fg = _BG_FG[self._dark].values()

        self._root.configure(bg=self._bg)
        self._text.configure(bg=self._bg, fg=self._fg)
        self._text.tag_config("sel", background="#3a3a3a" if self._dark else "#cce4ff")
        for name, hex_color in self._colors.items():
            self._text.tag_configure(name, foreground=hex_color)

        for widget in (self._refresh_btn, self._ok_btn, self._dark_ck):
            widget.configure(
                bg=self._bg, fg=self._fg,
                activebackground=self._bg, activeforeground=self._fg,
            )
        self._dark_ck.configure(selectcolor=self._bg)
        self._refresh_btn.master.configure(bg=self._bg)
        self._redraw()

    def _fetch_async(self) -> None:
        if self._is_fetching.is_set():
            return
        self._is_fetching.set()
        threading.Thread(target=self._fetch, daemon=True, name="ollama-gui").start()

    def _fetch(self) -> None:
        try:
            self._data = get_usage(self._cookie)
            self._error = None
        except NetworkError:
            self._error = "Network error"
        except AuthError:
            try:
                logger.info("GUI: Cookie expired. Attempting to refresh...")
                self._cookie = self._cookie_fn()
                self._data = get_usage(self._cookie)
                self._error = None
            except Exception as refresh_exc:
                self._error = f"Auth error: {refresh_exc}"
        except OllamaUsageError as exc:
            self._error = str(exc)
        finally:
            self._is_fetching.clear()
            try:
                self._root.after(0, self._redraw)
            except Exception:
                pass

    # ---------------------------------------------------------------- draw

    def _redraw(self) -> None:
        self._text.delete("1.0", tk.END)
        for line in build_segments(self._data, self._error):
            start = self._text.index("end-1c")
            for text, color in line:
                self._text.insert("end", text)
                if color:
                    end = self._text.index("end-1c")
                    self._text.tag_add(color, start, end)
                start = self._text.index("end-1c")
            self._text.insert("end", "\n")

    # ---------------------------------------------------------------- run

    def _quit(self) -> None:
        try:
            _save_geometry(self._root.geometry())
        except Exception:
            pass
        try:
            _save_darkmode(self._dark)
        except Exception:
            pass
        try:
            self._root.destroy()
        except Exception:
            pass
        sys.exit(0)

    def run(self) -> None:
        self._root.mainloop()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def launch_gui(
    cookie: str | Callable[[], str],
    title: str | None = None,
) -> None:
    """Launch the simple Ollama quota GUI window.

    Args:
        cookie: __Secure-session cookie value or callable to fetch/refresh it.
        title:  Optional window title. Defaults to "<app> (<version>)".
    """
    try:
        import tkinter  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "tkinter is not available. "
            "On Linux, install it with: sudo apt install python3-tk"
        )

    OllamaGui(cookie=cookie, title=title).run()
