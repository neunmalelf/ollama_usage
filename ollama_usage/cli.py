import argparse
import pathlib
import json
import logging
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from ollama_usage import __version__ as _pkg_version
from ollama_usage.cookie import (
    firefox_profile_diagnostics,
    get_cookie_auto,
    get_cookie_brave,
    get_cookie_chrome,
    get_cookie_edge,
    get_cookie_env,
    get_cookie_firefox,
    get_cookie_opera,
)
from ollama_usage.exceptions import (
    AuthError,  # We also need AuthError here
    NetworkError,
    OllamaUsageError,
)
from ollama_usage.notify import NotifyState, check_and_notify, notify_available
from ollama_usage.scraper import get_usage, plan_display_name

logger = logging.getLogger(__name__)

# ANSI color support (self-contained, no colorama dependency).
_ANSI = {
    "reset":   "\033[0m",
    "red":     "\033[31m",
    "green":   "\033[32m",
    "yellow":  "\033[33m",
    "cyan":    "\033[36m",
    "magenta": "\033[35m",
    "white":   "\033[37m",
    "grey":    "\033[90m",
    "orange":  "\033[38;5;208m",
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

#: Color used for decorative separators and secondary footer text.
decorator_color = "grey"

_HAS_COLOR = True


def _enable_windows_vt() -> None:
    """Enable ANSI/VT processing on Windows console stdout/stderr.

    On Windows legacy consoles ANSI escape codes print as garbage unless
    ENABLE_VIRTUAL_TERMINAL_PROCESSING is set on the console mode. This is a
    no-op (and a silent no-op) on other platforms or if the call fails.
    """
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        from ctypes import wintypes

        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        kernel32 = ctypes.windll.kernel32
        for stream in (sys.stdout, sys.stderr):
            handle = kernel32.GetStdHandle(
                wintypes.DWORD(stream is sys.stderr and -12 or -11)
            )
            mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:  # noqa: BLE001
        pass


def _get_version() -> str:
    """Get package version from the source ``__version__``.

    Prefer the source version over installed package metadata, which can be
    stale (e.g. an old ``pip install``). ``_pkg_version`` is baked in for
    frozen executables too.
    """
    return _pkg_version


def _sanitize_cookie(value: str) -> str:
    return value.strip().replace("\r", "").replace("\n", "").replace("\0", "")


BROWSERS = {
    "firefox": get_cookie_firefox,
    "chrome": get_cookie_chrome,
    "edge": get_cookie_edge,
    "brave": get_cookie_brave,
    "opera": get_cookie_opera,
}


def _use_color() -> bool:
    """Return True when ANSI color output is enabled for stdout."""
    return _HAS_COLOR and sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _color_pct(pct: float, use_color: Optional[bool] = None) -> str:
    """Return the percentage string colored by severity and padded for right-alignment.

    The number is colored by severity; the ``%`` symbol uses the label color.
    """
    text = f"{pct:.1f}%"
    padded_text = f"{text:>6}"
    if use_color is None:
        use_color = _use_color()
    if not use_color:
        return padded_text
    if pct < 50:
        color = _ANSI["green"]
    elif pct < 80:
        color = _ANSI["yellow"]
    else:
        color = _ANSI["red"]
    num = padded_text[:-1]  # number part, right-aligned (excludes the %)
    return (
        color + num + _ANSI["reset"]
        + _ANSI[_LABEL_COLOR] + "%" + _ANSI["reset"]
    )


def _format_remaining_compact(iso: str, use_color: bool = False) -> str:
    """Return remaining time as ``[dd] hh:mm`` (days omitted when zero).

    When ``use_color`` is true the days, hours and minutes numbers are colored
    with the named time colors and the ``:`` separator with the label color.
    """
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        diff = dt - datetime.now(timezone.utc)
        total_seconds = int(diff.total_seconds())
        if total_seconds <= 0:
            return "00:00"
        days, rem = divmod(total_seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        hours_str = _color_num(f"{hours:02d}", _HOURS_COLOR, use_color)
        minutes_str = _color_num(f"{minutes:02d}", _MINUTES_COLOR, use_color)
        sep = _ANSI[_LABEL_COLOR] + ":" + _ANSI["reset"] if use_color else ":"
        time_str = f"{hours_str}{sep}{minutes_str}"
        if days:
            days_str = _color_part(f"{days}d", _DAYS_COLOR, use_color)
            return f"{days_str} {time_str}"
        return time_str
    except Exception:
        return ""


def _format_countdown(seconds: int) -> str:
    """Return ``(mm:ss)`` or ``(ss)`` for the autorefresh countdown."""
    if seconds >= 60:
        minutes, secs = divmod(seconds, 60)
        return f"({minutes}:{secs:02d})"
    return f"({seconds})"


def _mini_line(data: dict, use_color: bool) -> str:
    """Build the single-line minidisplay string (no trailing newline)."""
    plan = plan_display_name(data["plan"])
    if use_color:
        plan = f"{_ANSI[_PLAN_COLOR]}{plan}{_ANSI['reset']}"
    session_pct = _color_pct(data["session"]["used_pct"], use_color)
    weekly_pct = _color_pct(data["weekly"]["used_pct"], use_color)
    session_left = _format_remaining_compact(data["session"]["resets_at"], use_color)
    weekly_left = _format_remaining_compact(data["weekly"]["resets_at"], use_color)
    web_search = data.get("web_search_requests")
    web_fetch = data.get("web_fetch_requests")
    ws = "0" if web_search is None else str(web_search)
    wr = "0" if web_fetch is None else str(web_fetch)
    if use_color:
        ws = f"{_ANSI[_VALUE_COLOR]}{ws}{_ANSI['reset']}"
        wr = f"{_ANSI[_VALUE_COLOR]}{wr}{_ANSI['reset']}"
    sep = _ANSI[decorator_color] + "|" + _ANSI["reset"] if use_color else "|"
    paren = _ANSI[decorator_color] + "(" + _ANSI["reset"] if use_color else "("
    paren_end = _ANSI[decorator_color] + ")" + _ANSI["reset"] if use_color else ")"
    return (
        f"olu {paren}{plan}{paren_end} s: {session_pct} {paren}{session_left}{paren_end}"
        f" {sep} w: {weekly_pct} {paren}{weekly_left}{paren_end}"
        f" ws: {ws} wr: {wr}"
    )


def _mini_horizontal(data: dict, use_color: bool) -> str:
    """Build the multi-line minidisplay (each info item on its own line)."""
    plan = plan_display_name(data["plan"])
    if use_color:
        plan = f"{_ANSI[_PLAN_COLOR]}{plan}{_ANSI['reset']}"
    session_pct = _color_pct(data["session"]["used_pct"], use_color)
    weekly_pct = _color_pct(data["weekly"]["used_pct"], use_color)
    session_left = _format_remaining_compact(data["session"]["resets_at"], use_color)
    weekly_left = _format_remaining_compact(data["weekly"]["resets_at"], use_color)
    web_search = data.get("web_search_requests")
    web_fetch = data.get("web_fetch_requests")
    ws = "0" if web_search is None else str(web_search)
    wr = "0" if web_fetch is None else str(web_fetch)
    if use_color:
        ws = f"{_ANSI[_VALUE_COLOR]}{ws}{_ANSI['reset']}"
        wr = f"{_ANSI[_VALUE_COLOR]}{wr}{_ANSI['reset']}"
    paren = _ANSI[decorator_color] + "(" + _ANSI["reset"] if use_color else "("
    paren_end = _ANSI[decorator_color] + ")" + _ANSI["reset"] if use_color else ")"
    return "\n".join(
        [
            f"olu {paren}{plan}{paren_end}",
            f"s: {session_pct} {paren}{session_left}{paren_end}",
            f"w: {weekly_pct} {paren}{weekly_left}{paren_end}",
            f"ws: {ws}",
            f"wr: {wr}",
        ]
    )


def _mini_display(data: dict, use_color: bool, horizontal: bool) -> str:
    """Return the single-line or multi-line minidisplay string."""
    if horizontal:
        return _mini_horizontal(data, use_color)
    return _mini_line(data, use_color)


def display(
    data: dict,
    as_json: bool,
    quiet: bool,
    minidisplay: bool = False,
    minidisplay_horizontal: bool = False,
) -> None:
    if quiet:
        return
    if as_json:
        print(json.dumps(data, indent=2))
    elif minidisplay_horizontal or minidisplay:
        # Clear the terminal first so only the minidisplay output is visible
        # (no leftover prompt). Only when stdout is a TTY.
        if sys.stdout.isatty():
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()
        print(_mini_display(data, _use_color(), minidisplay_horizontal))
    else:
        use_color = _HAS_COLOR and sys.stdout.isatty() and "NO_COLOR" not in os.environ
        plan = plan_display_name(data['plan'])
        if use_color:
            plan = f"{_ANSI[_PLAN_COLOR]}{plan}{_ANSI['reset']}"
        print("")
        print(f"Plan     : {plan}")
        print(
            f"Session  : {_color_pct(data['session']['used_pct'])} used - reset at {data['session']['resets_at']}{_format_time_left(data['session']['resets_at'], use_color)}"
        )
        print(
            f"Weekly   : {_color_pct(data['weekly']['used_pct'])} used - reset at {data['weekly']['resets_at']}{_format_time_left(data['weekly']['resets_at'], use_color)}"
        )
        web_search = data.get("web_search_requests")
        if web_search is not None:
            count = f"{web_search:>6}"
            if use_color:
                count = _ANSI[_VALUE_COLOR] + count + _ANSI["reset"]
            print(f"WebSearch: {count} request{'s' if web_search != 1 else ''}")

        web_fetch = data.get("web_fetch_requests")
        if web_fetch is not None:
            count = f"{web_fetch:>6}"
            if use_color:
                count = _ANSI[_VALUE_COLOR] + count + _ANSI["reset"]
            print(f"WebFetch : {count} request{'s' if web_fetch != 1 else ''}")

        models = data.get("models")
        if models:
            header = "Model calls this week:"
            if use_color:
                header = f"{_ANSI['grey']}{header}{_ANSI['reset']}"
            print(header)
            for item in models:
                num = f"{item['requests']:>6}"
                if use_color:
                    num = _ANSI[_VALUE_COLOR] + num + _ANSI["reset"]
                print(f"{'':>11}{num} {item['name']}")


def _color_part(value: str, color: str, use_color: bool) -> str:
    """Color a number but leave a trailing unit label white.

    ``value`` is like " 2d", " 2h" or "42m". The numeric part is wrapped in
    ``color`` and the unit letter in the label color when color is enabled.
    """
    if not use_color:
        return value
    return (
        _ANSI[color] + value[:-1] + _ANSI["reset"]
        + _ANSI[_LABEL_COLOR] + value[-1] + _ANSI["reset"]
    )


def _color_num(value: str, color: str, use_color: bool) -> str:
    """Color a plain number (no unit label) with ``color`` when enabled."""
    if not use_color:
        return value
    return _ANSI[color] + value + _ANSI["reset"]


def _format_time_left(iso: str, use_color: bool = False) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        diff = dt - datetime.now(timezone.utc)
        total_seconds = int(diff.total_seconds())
        if total_seconds <= 0:
            return " (resets now)"

        hours, rem = divmod(total_seconds, 3600)
        minutes, _ = divmod(rem, 60)

        if hours >= 24:
            days, hours = divmod(hours, 24)
            days_str = _color_part(f"{days:>2}d", _DAYS_COLOR, use_color)
        else:
            days_str = "   "

        hours_str = _color_part(f"{hours:>2}h", _HOURS_COLOR, use_color)
        minutes_str = _color_part(f"{minutes:>2}m", _MINUTES_COLOR, use_color)

        return f" (in {days_str} {hours_str} {minutes_str})"
    except Exception:
        return ""



def _check_alert(data: dict, threshold: Optional[float], quiet: bool) -> bool:
    """Return True if any quota exceeds the alert threshold."""
    if threshold is None:
        return False
    session_pct = data["session"]["used_pct"]
    weekly_pct = data["weekly"]["used_pct"]
    if session_pct > threshold or weekly_pct > threshold:
        if not quiet:
            msg = f"Warning: usage exceeds {threshold}%"
            use_color = (
                _HAS_COLOR and sys.stderr.isatty() and "NO_COLOR" not in os.environ
            )
            if use_color:
                print(_ANSI["red"] + "⚠️  " + msg + _ANSI["reset"], file=sys.stderr)
            else:
                print(f"⚠️  {msg}", file=sys.stderr)
        return True
    return False


def _next_refresh_timestamp(seconds_from_now: int) -> str:
    """Return the next-refresh timestamp as ``YYYY-MM-DD hh-mm-ss``.

    The timestamp is ``now + seconds_from_now`` and is fixed once calculated.
    Reusable by both the CLI footer and the GUI.
    """
    return (datetime.now() + timedelta(seconds=seconds_from_now)).strftime(
        "%Y-%m-%d %H-%M-%S"
    )


def _autorefresh_sleep(interval: int) -> None:
    """Sleep for ``interval`` seconds, printing a single countdown line.

    Format: ``next refresh in <N> seconds at YYYY-MM-DD hh-mm-ss``
    The seconds count and the next-refresh timestamp are shown in cyan.
    The timestamp is calculated once and stays fixed.
    """
    if not sys.stdout.isatty():
        time.sleep(interval)
        return
    use_color = _HAS_COLOR and sys.stdout.isatty() and "NO_COLOR" not in os.environ
    # Fixed timestamp: now + interval, calculated once and never changed.
    next_str = _next_refresh_timestamp(interval)
    print()  # blank line before the footer
    for remaining in range(interval, 0, -1):
        if use_color:
            line = (
                f"{_ANSI[decorator_color]}next refresh in {_ANSI['reset']}"
                f"{_ANSI['cyan']}{remaining}{_ANSI['reset']}"
                f"{_ANSI[decorator_color]} seconds at {_ANSI['reset']}"
                f"{_ANSI['cyan']}{next_str}{_ANSI['reset']}"
            )
        else:
            line = f"next refresh in {remaining} seconds at {next_str}"
        sys.stdout.write("\r" + line + "   ")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()


def _autorefresh_sleep_mini(interval: int, prefix: str) -> None:
    """Sleep for ``interval`` seconds, appending a decorator ``(mm:ss)`` countdown to ``prefix``."""
    if not sys.stdout.isatty():
        time.sleep(interval)
        return
    use_color = _use_color()
    for remaining in range(interval, 0, -1):
        countdown = _format_countdown(remaining)
        if use_color:
            countdown = f"{_ANSI[decorator_color]}{countdown}{_ANSI['reset']}"
        sys.stdout.write("\r" + prefix + " " + countdown + "   ")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()


def _autorefresh_sleep_horizontal(interval: int, block: str) -> None:
    """Sleep for ``interval`` seconds, redrawing ``block`` with a decorator ``(mm:ss)`` countdown on the ``wr:`` line."""
    if not sys.stdout.isatty():
        time.sleep(interval)
        return
    use_color = _use_color()
    for remaining in range(interval, 0, -1):
        countdown = _format_countdown(remaining)
        if use_color:
            countdown = f"{_ANSI[decorator_color]}{countdown}{_ANSI['reset']}"
        sys.stdout.write("\033[2J\033[H" + block + "  " + countdown + "   ")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


class _HelpFormatter(argparse.HelpFormatter):
    """Preserve explicit newlines in option help text."""

    def _split_lines(self, text: str, width: int) -> list[str]:
        lines: list[str] = []
        for line in text.splitlines():
            lines.extend(super()._split_lines(line, width))
        return lines

    def _fill_text(self, text: str, width: int, indent: str) -> str:
        """Wrap each line independently so epilog newlines survive.

        Lines that already fit are kept verbatim, preserving their leading
        indentation; longer lines wrap with the given indent as usual.
        """
        fill = super()._fill_text
        lines: list[str] = []
        for line in text.splitlines():
            if len(line) <= width:
                lines.append(line)
            else:
                lines.extend(fill(line, width, indent).splitlines())
        return "\n".join(lines)

class _VoiceResetTracker:
    """Speak configured texts when the session/weekly usage resets.

    A reset is detected by the ``resets_at`` timestamp changing between two
    successful fetches (the quota rolled over to a new period). The first
    fetch only establishes the baseline, so a reset that happened before the
    program started is not announced.
    """

    def __init__(self, session_text: str | None, weekly_text: str | None) -> None:
        self._session_text = session_text
        self._weekly_text = weekly_text
        self._session_reset: str | None = None
        self._weekly_reset: str | None = None

    def check(self, data: dict) -> None:
        if not self._session_text and not self._weekly_text:
            return
        session = data.get("session") or {}
        weekly = data.get("weekly") or {}
        session_reset = session.get("resets_at")
        weekly_reset = weekly.get("resets_at")

        if (
            self._session_text
            and session_reset
            and self._session_reset is not None
            and session_reset != self._session_reset
        ):
            from ollama_usage.voice import speak_async
            speak_async(self._session_text)
        if (
            self._weekly_text
            and weekly_reset
            and self._weekly_reset is not None
            and weekly_reset != self._weekly_reset
        ):
            from ollama_usage.voice import speak_async
            speak_async(self._weekly_text)

        if session_reset:
            self._session_reset = session_reset
        if weekly_reset:
            self._weekly_reset = weekly_reset


def _warn_transparent_fallback(args) -> None:
    """Print a notice when a fully transparent widget background is impossible.

    Tk's ``-transparentcolor`` is a Windows-only attribute and plain Tk has
    no per-pixel transparency on X11/Wayland; there the fully transparent
    widget needs PySide6, and without it the widget falls back to a
    translucent window. The notice must come from the original process
    (which still owns the terminal): in ``--daemon`` mode the detached
    child's stderr is /dev/null, so it would be lost.
    """
    if (
        getattr(args, "widget", False)
        and getattr(args, "background_transparent", False)
        and sys.platform != "win32"
    ):
        from ollama_usage.widget import qt_transparency_supported

        if not qt_transparency_supported():
            print(
                "Warning: --background-transparent needs PySide6 for a fully "
                "transparent background; PySide6 was not found, so the widget "
                "uses a translucent background instead. "
                "Install with: pip install PySide6",
                file=sys.stderr,
            )

def main():
    parser = argparse.ArgumentParser(
        description="Display your Ollama Cloud quota usage",
        epilog=(
            "  keyboard shortcuts:\n"
            "  Ctrl+C  stop the CLI (autorefresh, minidisplay, alert loops)\n"
            "  Ctrl+Q  close the GUI window and the desktop widget\n\n"
            "  desktop widget:\n"
            "  right-click  context menu (refresh now, toggle size, close)\n"
            "  drag         move the widget\n\n"
        ),
        formatter_class=_HelpFormatter,
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"ollama-usage {_get_version()}"
    )
    parser.add_argument(
        "--minidisplay",
        action="store_true",
        help="Single-line compact output, e.g.:\n"
        "  olu (PRO) s: 42.0%% (02:46) | w: 77.0%% (1d 06:46) ws: 2 wr: 0\n"
        "  olu = ollama usage, (PRO) = your plan name\n"
        "  s  = session usage, w = weekly usage (percent used)\n"
        "  ws = web search requests this session\n"
        "  wr = web fetch requests this session\n"
        "  remaining time is [dd] hh:mm (days omitted when zero)\n"
        "  clears the terminal before showing the line (TTY only)",
    )
    parser.add_argument(
        "--minidisplay-horizontal",
        action="store_true",
        help="Multi-line compact output, each info on its own line, e.g.:\n"
        "  olu (PRO)\n"
        "  s:  42.0%% (02:46)\n"
        "  w:  77.0%% (1d 06:46)\n"
        "  ws: 2\n"
        "  wr: 0 [auto-refresh-timer]\n"
        "  clears the terminal before showing the output (TTY only)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--cookie", type=str, help="Manual __Secure-session cookie")
    parser.add_argument(
        "--browser", type=str, choices=BROWSERS.keys(), help="Force a specific browser"
    )
    parser.add_argument(
        "--debug-firefox-profiles",
        action="store_true",
        help="Show every Firefox profile location searched, then exit",
    )
    parser.add_argument(
        "--reset-settings",
        action="store_true",
        help="Reset GUI and widget settings files, then exit",
    )
    parser.add_argument(
        "--autorefresh-off",
        action="store_true",
        help="Disable continuous refresh (single fetch). Autorefresh is on by default.",
    )
    parser.add_argument(
        "--autorefresh",
        nargs="?",
        type=int,
        const=120,
        default=120,
        metavar="SECONDS",
        help="Refresh interval in SECONDS (default: 120).\n"
        f"{_ANSI[decorator_color]}Shows a timestamp footer with the next refresh time.{_ANSI['reset']}",
    )
    parser.add_argument(
        "--alert",
        type=float,
        metavar="PERCENTAGE",
        help="Exit with code 1 if session or weekly usage exceeds PERCENTAGE (%%)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress all output — only set exit code (useful with --alert)",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Send desktop notifications when quota exceeds threshold (requires plyer)",
    )
    parser.add_argument(
        "--notify-threshold",
        type=float,
        default=80.0,
        metavar="PERCENTAGE",
        help="Threshold for desktop notifications in PERCENTAGE (%%) (default: 80, requires --notify)",
    )
    parser.add_argument(
        "--voice-info-when-session-usage-was-reset",
        nargs="?",
        const="ollama_usage the session usage has been reset",
        metavar="TEXT",
        help="Speak TEXT when the session usage resets (default: 'ollama_usage "
        "the session usage has been reset'). Requires a speech backend: "
        "espeak-ng, spd-say or festival on Linux, 'say' on macOS, PowerShell "
        "on Windows; optional high-quality neural voices via 'pip install "
        "edge-tts' or kokoro-onnx. No special hardware needed - any speakers "
        "or headphones work.",
    )
    parser.add_argument(
        "--voice-info-when-weekly-usage-was-reset",
        nargs="?",
        const="ollama_usage the weekly usage has been reset",
        metavar="TEXT",
        help="Speak TEXT when the weekly usage resets (default: 'ollama_usage "
        "the weekly usage has been reset'). Same speech backend requirements "
        "as --voice-info-when-session-usage-was-reset.",
    )
    parser.add_argument(
        "--widget",
        action="store_true",
        help="Launch desktop widget (A by default, M with --autorefresh-off; green=fresh, red=error)",
    )
    parser.add_argument(
        "--gui", action="store_true", help="Launch a simple GUI window with OK and Refresh buttons"
    )
    parser.add_argument(
        "--theme",
        default="dark",
        choices=["dark", "light", "minimal"],
        help="Defines the color scheme used together with --widget",
    )
    parser.add_argument(
        "--size", default=None, choices=["compact", "full"],
        help="Widget size (default: restore last used size)",
    )
    parser.add_argument(
        "--opacity", type=float, default=None, metavar="0.0-1.0",
        help="Widget window opacity (default: 0.92; 0.80 with --background-transparent)",
    )
    parser.add_argument(
        "--position",
        default=None,
        choices=["top-left", "top-right", "bottom-left", "bottom-right"],
        help="Widget screen corner (default: restore last used position)",
    )
    parser.add_argument(
        "--background-transparent",
        action="store_true",
        help="Widget background fully transparent (native on Windows; on "
        "Linux/macOS requires PySide6, otherwise falls back to a translucent "
        "background)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logs")
    parser.add_argument(
        "--daemon", "--damon",
        action="store_true",
        dest="daemon",
        help="Run in background (daemon) so terminal can be closed. "
        "Terminal is not blocked. Stop with: killall ollama_usage "
        "(the onefile payload shuts down a moment later)",
    )
    args = parser.parse_args()

    # When run without any argument, show help instead of traceback / obscure error
    # (user request: `ollama_usage` without params should show help, not KeyError)
    if len(sys.argv) == 1:
        parser.print_help()
        return

    # Surface the --background-transparent platform limitation before the
    # daemon spawns a detached child (whose stderr is /dev/null).
    _warn_transparent_fallback(args)
    # Handle daemon mode: spawn a detached background process so the terminal
    # can be closed.  We use subprocess.Popen instead of os.fork() to avoid
    # deadlocks in Nuitka-compiled binaries where the process is multi-threaded.
    if getattr(args, "daemon", False):
        # Build the command line for the child (everything except --daemon/--damon)
        child_args = [a for a in sys.argv[1:] if a not in ("--daemon", "--damon")]
        # Determine the right executable.
        # sys.argv[0] is the path the user invoked (the real binary).
        # On Linux, /proc/self/exe is an alternative but in Nuitka onefile
        # binaries it resolves to the extracted temp path which gets cleaned
        # up when the parent exits — so always prefer sys.argv[0].
        exe_path = pathlib.Path(sys.argv[0]).resolve()
        if exe_path.suffix in (".py", ".pyc") or "python" in exe_path.name.lower():
            # Running as `python -m ollama_usage` or `python cli.py`
            exe = [sys.executable, "-m", "ollama_usage"]
        else:
            # Nuitka binary or direct script invocation
            exe = [str(exe_path)]
        # On Windows, use CREATE_NEW_PROCESS_GROUP for detachment
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            )
        try:
            child = subprocess.Popen(
                exe + child_args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=(sys.platform != "win32"),
                creationflags=creationflags,
            )
            print(
                f"ollama_usage daemon started (pid {child.pid}) - "
                f"terminal can be closed. Stop with: killall ollama_usage"
            )
            sys.exit(0)
        except Exception as e:
            print(f"Failed to daemonize: {e}", file=sys.stderr)
            sys.exit(1)

    if _HAS_COLOR:
        _enable_windows_vt()

    try:
        if args.reset_settings:
            for name in (".ollama-usage-gui.cfg", ".ollama-usage-widget.cfg"):
                path = pathlib.Path.home() / name
                try:
                    path.unlink(missing_ok=True)
                    print(f"Reset settings: {path}")
                except OSError as exc:
                    print(f"Could not reset {path}: {exc}", file=sys.stderr)
                    raise SystemExit(1)
            return

        if args.debug_firefox_profiles:
            print("Firefox profile search paths:")
            for base, profiles in firefox_profile_diagnostics():
                status = "exists" if base.is_dir() else "missing"
                print(f"- [{status}] {base}")
                if profiles:
                    for profile in profiles:
                        print(f"    profile: {profile} (cookies.sqlite found)")
                elif base.is_dir():
                    print("    (no profile containing cookies.sqlite found)")
            return

        if args.debug:
            logging.basicConfig(
                level=logging.DEBUG,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            )

        def get_current_cookie() -> str:
            if args.cookie:
                return _sanitize_cookie(args.cookie)
            if args.browser:
                return _sanitize_cookie(BROWSERS[args.browser]())
            env_cookie = get_cookie_env()
            if env_cookie:
                return _sanitize_cookie(env_cookie)
            return _sanitize_cookie(get_cookie_auto())

        cookie = get_current_cookie()
        logger.debug("Cookie obtained (***)")

        alert_triggered = False

        notify_state = NotifyState()

        voice_tracker = _VoiceResetTracker(
            args.voice_info_when_session_usage_was_reset,
            args.voice_info_when_weekly_usage_was_reset,
        )

        if args.notify and not notify_available():
            print(
                "Warning: --notify requires plyer. Install it with: "
                "pip install ollama-usage[notify]",
                file=sys.stderr,
            )

        if args.gui:
            from ollama_usage.gui import launch_gui

            launch_gui(cookie=cookie if args.cookie else get_current_cookie)
            return

        if args.widget:
            from ollama_usage.widget import launch_widget

            launch_widget(
                cookie=cookie if args.cookie else get_current_cookie,
                interval=30,
                theme=args.theme,
                size=args.size,
                opacity=args.opacity,
                position=args.position,
                autorefresh=not args.autorefresh_off,
                background_transparent=args.background_transparent,
            )
            return

        if not args.autorefresh_off:
            auto_interval = max(1, args.autorefresh)
            mini = (args.minidisplay or args.minidisplay_horizontal) and not args.json and not args.quiet
            horizontal = bool(args.minidisplay_horizontal) and mini
            line = ""
            try:
                while True:
                    sys.stdout.write("\033[2J\033[H")
                    sys.stdout.flush()
                    try:
                        data = get_usage(cookie)
                        voice_tracker.check(data)
                        if mini:
                            line = _mini_display(data, _use_color(), horizontal)
                        else:
                            display(data, args.json, args.quiet)
                        if args.notify:
                            check_and_notify(
                                data, args.notify_threshold, notify_state
                            )
                        if _check_alert(data, args.alert, args.quiet):
                            alert_triggered = True
                    except AuthError as e:
                        if args.cookie:
                            print(f"Error: {e}", file=sys.stderr)
                            raise SystemExit(1)
                        else:
                            try:
                                logger.info(
                                    "Cookie expired/invalid. Attempting auto-refresh..."
                                )
                                cookie = get_current_cookie()
                                data = get_usage(cookie)
                                voice_tracker.check(data)
                                if mini:
                                    line = _mini_display(data, _use_color(), horizontal)
                                else:
                                    display(data, args.json, args.quiet)
                                if args.notify:
                                    check_and_notify(
                                        data, args.notify_threshold, notify_state
                                    )
                                if _check_alert(data, args.alert, args.quiet):
                                    alert_triggered = True
                            except Exception as refresh_err:
                                print(
                                    f"Cookie auto-refresh failed: {refresh_err}",
                                    file=sys.stderr,
                                )
                                raise SystemExit(1)
                    except NetworkError as e:
                        print(
                            f"Network error: {e} — retrying in {auto_interval}s",
                            file=sys.stderr,
                        )
                    if mini:
                        if horizontal:
                            _autorefresh_sleep_horizontal(auto_interval, line)
                        else:
                            _autorefresh_sleep_mini(auto_interval, line)
                    else:
                        _autorefresh_sleep(auto_interval)
            except KeyboardInterrupt:
                print("\nStopped.")
                return

        data = get_usage(cookie)
        display(
            data, args.json, args.quiet, args.minidisplay, args.minidisplay_horizontal
        )
        if args.notify:
            check_and_notify(data, args.notify_threshold, notify_state)
        if _check_alert(data, args.alert, args.quiet):
            alert_triggered = True

        if alert_triggered:
            raise SystemExit(1)

    except OllamaUsageError as e:
        print(f"Error: {e}", file=sys.stderr)
        parser.print_help(sys.stderr)
        raise SystemExit(1)
    except Exception as e:
        # Any other unexpected error (e.g. KeyError before fix) should show help, not traceback
        # Use logger for debug, but show friendly message and help for user
        logger.debug("Unexpected error", exc_info=True)
        print(f"Error: {e}", file=sys.stderr)
        parser.print_help(sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
