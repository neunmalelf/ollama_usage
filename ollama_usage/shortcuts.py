from collections.abc import Callable

#: Key sequences that stop the app (Ctrl+Q, with/without Shift on Windows).
QUIT_KEYS: tuple[str, ...] = ("<Control-q>", "<Control-Q>")

#: Refresh the data in the GUI window (Alt+r, both key variants).
REFRESH_KEYS: tuple[str, ...] = ("<Alt-r>", "<Alt-Key-r>")

#: Close the GUI window (Alt+o, Return or Escape).
CLOSE_KEYS: tuple[str, ...] = ("<Alt-o>", "<Alt-Key-o>", "<Return>", "<Escape>")

#: Toggle dark mode in the GUI window (Alt+d).
DARK_KEYS: tuple[str, ...] = ("<Alt-d>", "<Alt-Key-d>")


def bind_keys(target, keys: tuple[str, ...], callback: Callable) -> None:
    """Bind every ``keys`` sequence to ``callback`` on a tkinter window.

    Args:
        target:   A tkinter widget (e.g. a Tk root or Canvas) to bind on.
        keys:     Key sequences to bind, e.g. ``QUIT_KEYS``.
        callback: Callable taking the event, e.g. ``lambda _e: app._quit()``.
    """
    for key in keys:
        target.bind(key, callback)


def bind_quit(target, callback: Callable) -> None:
    """Bind every app-quit shortcut (Ctrl+Q) to ``callback`` on a tkinter window.

    Args:
        target:   A tkinter widget (e.g. a Tk root or Canvas) to bind on.
        callback: Callable taking the event, e.g. ``lambda _e: app._quit()``.
    """
    bind_keys(target, QUIT_KEYS, callback)
