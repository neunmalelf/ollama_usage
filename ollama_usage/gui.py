"""Simple cross-platform GUI window showing Ollama quota usage.

Uses tkinter (Python stdlib) so it works on Windows, Linux and macOS.
On minimal Linux installs you may need:
    sudo apt install python3-tk
"""

from __future__ import annotations

import logging
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
    lines.append(f"Plan     :  {plan}")

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

        self._root = tk.Tk()
        self._root.title(title or f"{APP_NAME} ({_pkg_version})")
        self._root.resizable(True, True)
        self._root.minsize(360, 200)

        self._text = tk.Text(
            self._root,
            wrap="word",
            height=12,
            width=52,
            padx=10,
            pady=10,
            relief=tk.FLAT,
        )
        self._text.pack(fill="both", expand=True, padx=8, pady=8)

        buttons = tk.Frame(self._root)
        buttons.pack(fill="x", padx=8, pady=(0, 8))

        self._refresh_btn = tk.Button(
            buttons, text="Refresh", command=self._refresh
        )
        self._refresh_btn.pack(side="left", padx=4)

        self._ok_btn = tk.Button(buttons, text="OK", command=self._quit)
        self._ok_btn.pack(side="right", padx=4)

        self._fetch_async()

    # ---------------------------------------------------------------- data

    def _refresh(self) -> None:
        self._fetch_async()

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
        lines = build_lines(self._data, self._error)
        self._text.delete("1.0", tk.END)
        self._text.insert("1.0", "\n".join(lines))

    # ---------------------------------------------------------------- run

    def _quit(self) -> None:
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
