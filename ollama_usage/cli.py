import argparse
import json
import logging
import os
import platform
import sys
import time
from datetime import datetime, timedelta, timezone
from importlib.metadata import version as get_version
from typing import Optional

from ollama_usage import __version__ as _pkg_version
from ollama_usage.cookie import (
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
from ollama_usage.scraper import get_usage

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
    """Get package version, with fallback for frozen executables."""
    try:
        return get_version("ollama-usage")
    except Exception:
        # Fallback for frozen executables where package metadata is unavailable
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


def _color_pct(pct: float) -> str:
    """Return the percentage string colored by severity and padded for right-alignment."""
    text = f"{pct:.1f}%"
    padded_text = f"{text:>6}"
    use_color = _HAS_COLOR and sys.stdout.isatty() and "NO_COLOR" not in os.environ
    if not use_color:
        return padded_text
    if pct < 50:
        color = _ANSI["green"]
    elif pct < 80:
        color = _ANSI["yellow"]
    else:
        color = _ANSI["red"]
    return color + padded_text + _ANSI["reset"]


def _color_part(value: str, color: str, use_color: bool) -> str:
    """Color a number but leave a trailing unit label white.

    ``value`` is like " 2d", " 2h" or "42m". The numeric part is wrapped in
    ``color`` and the unit letter in white when color is enabled.
    """
    if not use_color:
        return value
    return (
        _ANSI[color] + value[:-1] + _ANSI["reset"]
        + _ANSI["white"] + value[-1] + _ANSI["reset"]
    )


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
            days_str = _color_part(f"{days:>2}d", "yellow", use_color)
        else:
            days_str = "   "

        hours_str = _color_part(f"{hours:>2}h", "cyan", use_color)
        minutes_str = _color_part(f"{minutes:>2}m", "magenta", use_color)

        return f" (in {days_str} {hours_str} {minutes_str})"
    except Exception:
        return ""


def display(data: dict, as_json: bool, quiet: bool) -> None:
    if quiet:
        return
    if as_json:
        print(json.dumps(data, indent=2))
    else:
        use_color = _HAS_COLOR and sys.stdout.isatty() and "NO_COLOR" not in os.environ
        plan = data['plan']
        if use_color:
            plan = f" {_ANSI['orange']}{plan}{_ANSI['reset']}"
        print("")
        print(f"Plan     :  {plan}")
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
                count = _ANSI["cyan"] + count + _ANSI["reset"]
            print(f"WebSearch: {count} request{'s' if web_search != 1 else ''}")

        models = data.get("models")
        if models:
            header = "Model calls this week:"
            if use_color:
                header = f"{_ANSI['grey']}{header}{_ANSI['reset']}"
            print(header)
            for item in models:
                num = f"{item['requests']:>6}"
                if use_color:
                    num = _ANSI["cyan"] + num + _ANSI["reset"]
                print(f"{'':>11}{num} {item['name']}")


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
                f"next refresh in {_ANSI['cyan']}{remaining}{_ANSI['reset']}"
                f" seconds at {_ANSI['cyan']}{next_str}{_ANSI['reset']}"
            )
        else:
            line = f"next refresh in {remaining} seconds at {next_str}"
        sys.stdout.write("\r" + line + "   ")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(
        description="Display your Ollama Cloud quota usage"
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"ollama-usage {_get_version()}"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--cookie", type=str, help="Manual __Secure-session cookie")
    parser.add_argument(
        "--browser", type=str, choices=BROWSERS.keys(), help="Force a specific browser"
    )
    parser.add_argument(
        "--autorefresh",
        nargs="?",
        type=int,
        const=120,
        default=None,
        metavar="SECONDS",
        help="Refresh continuously every SECONDS seconds (default: 120). "
        "Shows a timestamp footer with the next refresh time.",
    )
    parser.add_argument(
        "--alert",
        type=float,
        metavar="PCT",
        help="Exit with code 1 if session or weekly usage exceeds PCT%%",
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
        metavar="PCT",
        help="Threshold for desktop notifications in %% (default: 80, requires --notify)",
    )
    parser.add_argument("--widget", action="store_true", help="Launch desktop widget")
    parser.add_argument(
        "--gui", action="store_true", help="Launch a simple GUI window with OK and Refresh buttons"
    )
    parser.add_argument("--theme", default="dark", choices=["dark", "light", "minimal"])
    parser.add_argument("--size", default="full", choices=["compact", "full"])
    parser.add_argument("--opacity", type=float, default=0.92, metavar="0.0-1.0")
    parser.add_argument(
        "--position",
        default="top-left",
        choices=["top-left", "top-right", "bottom-left", "bottom-right"],
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logs")
    args = parser.parse_args()

    if _HAS_COLOR:
        _enable_windows_vt()

    try:
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
            )
            return

        if args.autorefresh is not None:
            auto_interval = max(1, args.autorefresh)
            try:
                while True:
                    sys.stdout.write("\033[2J\033[H")
                    sys.stdout.flush()
                    try:
                        data = get_usage(cookie)
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
                    _autorefresh_sleep(auto_interval)
            except KeyboardInterrupt:
                print("\nStopped.")

        data = get_usage(cookie)
        display(data, args.json, args.quiet)
        if args.notify:
            check_and_notify(data, args.notify_threshold, notify_state)
        if _check_alert(data, args.alert, args.quiet):
            alert_triggered = True

        if alert_triggered:
            raise SystemExit(1)

    except OllamaUsageError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
