"""Centralized keyboard shortcuts shared across the Ollama usage app.

All bindings live here so a shortcut is defined and bound in one place and
reused by every window (widget, GUI, ...) instead of being repeated inline.
"""

from __future__ import annotations

#: Key sequences that stop the app (Ctrl+Q, with/without Shift on Windows).
QUIT_KEYS: tuple[str, ...] = ("<Control-q>", "<Control-Q>")


def bind_quit(target, callback) -> None:
    """Bind every app-quit shortcut to ``callback`` on a tkinter window.

    Args:
        target:   A tkinter widget (e.g. a Tk root or Canvas) to bind on.
        callback: Callable taking the event, e.g. ``lambda _e: app._quit()``.
    """
    for key in QUIT_KEYS:
        target.bind(key, callback)
