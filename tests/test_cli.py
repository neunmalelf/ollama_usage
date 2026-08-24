"""Tests for ollama_usage.cli."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from ollama_usage.cli import (
    _sanitize_cookie,
    _check_alert,
    display,
    _format_time_left,
    _autorefresh_sleep,
    _next_refresh_timestamp,
    _format_remaining_compact,
    _format_countdown,
    _mini_line,
    _mini_horizontal,
    _autorefresh_sleep_mini,
    _autorefresh_sleep_horizontal,
)


# ---------------------------------------------------------------------------
# _format_time_left — reset countdown
# ---------------------------------------------------------------------------

class TestFormatTimeLeft:
    """Deterministic tests using a fixed reference 'now'."""

    def test_plain_output_without_color(self) -> None:
        from datetime import datetime, timezone, timedelta
        fixed = datetime(2026, 4, 2, 14, 18, 0, tzinfo=timezone.utc)
        with patch("ollama_usage.cli.datetime") as mock_dt:
            mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
            mock_dt.now.return_value = fixed
            mock_dt.timezone = timezone
            result = _format_time_left("2026-04-04T17:00:00Z", use_color=False)
        # Reference now -> target is exactly 2 days, 2 hours, 42 minutes later.
        assert result == " (in  2d  2h 42m)"

    def test_color_wraps_numbers_and_labels(self) -> None:
        from datetime import datetime, timezone
        from ollama_usage.cli import _ANSI
        fixed = datetime(2026, 4, 2, 14, 18, 0, tzinfo=timezone.utc)
        with patch("ollama_usage.cli.datetime") as mock_dt:
            mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
            mock_dt.now.return_value = fixed
            mock_dt.timezone = timezone
            result = _format_time_left("2026-04-04T17:00:00Z", use_color=True)
        # Days in yellow, hours in cyan, minutes in magenta; labels white.
        assert _ANSI["yellow"] + " 2" + _ANSI["reset"] + _ANSI["white"] + "d" + _ANSI["reset"] in result
        assert _ANSI["cyan"] + " 2" + _ANSI["reset"] + _ANSI["white"] + "h" + _ANSI["reset"] in result
        assert _ANSI["magenta"] + "42" + _ANSI["reset"] + _ANSI["white"] + "m" + _ANSI["reset"] in result

    def test_resets_now_when_past(self) -> None:
        assert _format_time_left("2000-01-01T00:00:00Z") == " (resets now)"

    def test_invalid_returns_empty(self) -> None:
        assert _format_time_left("not-a-date") == ""


# ---------------------------------------------------------------------------
# _sanitize_cookie — HTTP Header Injection
# ---------------------------------------------------------------------------

class TestSanitizeCookie:

    def test_strips_leading_trailing_whitespace(self) -> None:
        assert _sanitize_cookie("  abc  ") == "abc"

    def test_removes_carriage_return(self) -> None:
        # \r permet d'injecter des headers HTTP supplémentaires
        assert _sanitize_cookie("abc\rdef") == "abcdef"

    def test_removes_newline(self) -> None:
        # \n permet d'injecter des headers HTTP supplémentaires
        assert _sanitize_cookie("abc\ndef") == "abcdef"

    def test_removes_null_byte(self) -> None:
        assert _sanitize_cookie("abc\0def") == "abcdef"

    def test_removes_crlf_injection(self) -> None:
        # Cas classique d'HTTP Header Injection : \r\n
        payload = "legit\r\nX-Injected: evil"
        assert "\r" not in _sanitize_cookie(payload)
        assert "\n" not in _sanitize_cookie(payload)

    def test_valid_cookie_unchanged(self) -> None:
        # Un vrai cookie ne doit pas être altéré
        cookie = "abcdefghijklmnopqrstuvwxyz0123456789_-"
        assert _sanitize_cookie(cookie) == cookie

    def test_empty_string(self) -> None:
        assert _sanitize_cookie("") == ""

    def test_only_whitespace(self) -> None:
        assert _sanitize_cookie("   ") == ""

    def test_multiple_injections(self) -> None:
        assert _sanitize_cookie("a\r\nb\0c\rd") == "abcd"


# ---------------------------------------------------------------------------
# _check_alert — logique d'alerte quota
# ---------------------------------------------------------------------------

def make_data(session_pct: float = 0.0, weekly_pct: float = 0.0,
              web_search_requests: int | None = None,
              web_fetch_requests: int | None = None,
              models: list | None = None) -> dict:
    return {
        "plan": "free",
        "session": {"used_pct": session_pct, "resets_at": "2026-04-04T17:00:00Z"},
        "weekly":  {"used_pct": weekly_pct,  "resets_at": "2026-04-06T00:00:00Z"},
        "web_search_requests": web_search_requests,
        "web_fetch_requests": web_fetch_requests,
        "models": models,
    }


class TestCheckAlert:

    def test_no_alert_when_threshold_is_none(self) -> None:
        assert _check_alert(make_data(99.9, 99.9), None, quiet=True) is False

    def test_triggers_on_session_above_threshold(self) -> None:
        assert _check_alert(make_data(session_pct=85.0), 80.0, quiet=True) is True

    def test_triggers_on_weekly_above_threshold(self) -> None:
        assert _check_alert(make_data(weekly_pct=85.0), 80.0, quiet=True) is True

    def test_no_trigger_when_both_below(self) -> None:
        assert _check_alert(make_data(50.0, 50.0), 80.0, quiet=True) is False

    def test_exactly_at_threshold_does_not_trigger(self) -> None:
        # > threshold, pas >=
        assert _check_alert(make_data(80.0, 80.0), 80.0, quiet=True) is False

    def test_one_above_one_below_triggers(self) -> None:
        assert _check_alert(make_data(90.0, 10.0), 80.0, quiet=True) is True

    def test_quiet_suppresses_stderr_output(self, capsys) -> None:
        _check_alert(make_data(90.0), 80.0, quiet=True)
        assert capsys.readouterr().err == ""

    def test_not_quiet_prints_to_stderr(self, capsys) -> None:
        _check_alert(make_data(90.0), 80.0, quiet=False)
        assert capsys.readouterr().err != ""


# ---------------------------------------------------------------------------
# display — sortie JSON vs texte
# ---------------------------------------------------------------------------

class TestDisplay:

    def test_quiet_prints_nothing(self, capsys) -> None:
        display(make_data(50.0, 50.0), as_json=False, quiet=True)
        out, err = capsys.readouterr()
        assert out == "" and err == ""

    def test_json_output_is_valid(self, capsys) -> None:
        import json
        display(make_data(33.3, 66.6), as_json=True, quiet=False)
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["session"]["used_pct"] == 33.3
        assert parsed["weekly"]["used_pct"] == 66.6

    def test_text_output_contains_plan(self, capsys) -> None:
        display(make_data(), as_json=False, quiet=False)
        out = capsys.readouterr().out
        assert "FREE" in out

    def test_text_output_contains_percentages(self, capsys) -> None:
        display(make_data(42.0, 77.0), as_json=False, quiet=False)
        out = capsys.readouterr().out
        assert "42.0" in out
        assert "77.0" in out

    def test_text_output_omits_web_search_when_absent(self, capsys) -> None:
        display(make_data(), as_json=False, quiet=False)
        out = capsys.readouterr().out
        assert "WebSearch" not in out

    def test_text_output_shows_web_search_count_when_present(self, capsys) -> None:
        display(make_data(web_search_requests=2), as_json=False, quiet=False)
        out = capsys.readouterr().out
        assert "WebSearch" in out
        assert "2" in out
    def test_text_output_omits_web_fetch_when_absent(self, capsys) -> None:
        display(make_data(), as_json=False, quiet=False)
        out = capsys.readouterr().out
        assert "WebFetch" not in out

    def test_text_output_shows_web_fetch_count_when_present(self, capsys) -> None:
        display(make_data(web_fetch_requests=3), as_json=False, quiet=False)
        out = capsys.readouterr().out
        assert "WebFetch" in out
        assert "3" in out

    def test_text_output_shows_models_when_present(self, capsys) -> None:
        models = [
            {"name": "glm-5.2", "requests": 2},
            {"name": "deepseek-v4-flash", "requests": 60},
        ]
        display(make_data(models=models), as_json=False, quiet=False)
        out = capsys.readouterr().out
        assert "Model calls this week" in out
        assert "glm-5.2" in out
        assert "deepseek-v4-flash" in out

    def test_text_output_omits_models_when_absent(self, capsys) -> None:
        display(make_data(), as_json=False, quiet=False)
        out = capsys.readouterr().out
        assert "Models used this week" not in out


# ---------------------------------------------------------------------------
# Autorefresh interval
# ---------------------------------------------------------------------------

class TestAutorefreshInterval:
    """Vérifie que l'intervalle d'autorefresh est utilisé dans main()."""

    def _run_main_autorefresh(self, interval_arg: int) -> int:
        """Lance main() et retourne l'intervalle effectivement utilisé dans _autorefresh_sleep."""
        captured = {}

        def fake_sleep(iv):
            captured["interval"] = iv
            raise KeyboardInterrupt  # stoppe la boucle après 1 tour

        fake_data = make_data(10.0, 10.0)

        with patch("ollama_usage.cli.get_cookie_auto", return_value="fake-cookie"), \
             patch("ollama_usage.cli.get_usage", return_value=fake_data), \
             patch("ollama_usage.cli._autorefresh_sleep", side_effect=fake_sleep), \
             patch("ollama_usage.cli.sys.stdout.write"), \
             patch("sys.argv", ["ollama-usage", "--autorefresh", str(interval_arg), "--quiet"]):
            try:
                from ollama_usage.cli import main
                main()
            except SystemExit:
                pass

        return captured.get("interval", -1)

    def test_autorefresh_interval_used(self) -> None:
        assert self._run_main_autorefresh(60) == 60

    def test_autorefresh_interval_1_is_kept(self) -> None:
        assert self._run_main_autorefresh(1) == 1

    def test_autorefresh_interval_large_is_kept(self) -> None:
        assert self._run_main_autorefresh(1200) == 1200


# ---------------------------------------------------------------------------
# Output coloration and TTY checks
# ---------------------------------------------------------------------------

class TestCLIColoration:

    @patch("ollama_usage.cli.sys.stdout.isatty", return_value=False)
    @patch.dict("os.environ", {}, clear=True)
    @patch("ollama_usage.cli._HAS_COLOR", new=True)
    def test_color_disabled_on_non_tty(self, mock_isatty) -> None:
        from ollama_usage.cli import _color_pct
        assert _color_pct(50.0) == " 50.0%"

    @patch("ollama_usage.cli.sys.stdout.isatty", return_value=True)
    @patch.dict("os.environ", {"NO_COLOR": "1"})
    @patch("ollama_usage.cli._HAS_COLOR", new=True)
    def test_color_disabled_on_no_color_env(self, mock_isatty) -> None:
        from ollama_usage.cli import _color_pct
        assert _color_pct(50.0) == " 50.0%"

    @patch("ollama_usage.cli.sys.stdout.isatty", return_value=True)
    @patch.dict("os.environ", {}, clear=True)
    @patch("ollama_usage.cli._HAS_COLOR", new=True)
    def test_color_enabled_on_tty_without_no_color(self, mock_isatty) -> None:
        from ollama_usage.cli import _color_pct, _ANSI
        # When color is enabled, the number is severity-colored and the % is
        # in the label color.
        expected = (
            _ANSI["yellow"] + " 75.0" + _ANSI["reset"]
            + _ANSI["white"] + "%" + _ANSI["reset"]
        )
        assert _color_pct(75.0) == expected


# ---------------------------------------------------------------------------
# Autorefresh footer
# ---------------------------------------------------------------------------

class TestAutorefreshFooter:

    def test_next_refresh_timestamp_format(self) -> None:
        from datetime import datetime, timedelta
        fixed = datetime(2026, 8, 8, 13, 46, 5)
        with patch("ollama_usage.cli.datetime") as mock_dt:
            mock_dt.now.return_value = fixed
            mock_dt.timedelta = timedelta
            result = _next_refresh_timestamp(120)
        assert result == "2026-08-08 13-48-05"

    def test_autorefresh_sleep_on_non_tty_sleeps_once(self) -> None:
        from ollama_usage.cli import _autorefresh_sleep
        with patch("ollama_usage.cli.sys.stdout.isatty", return_value=False), \
             patch("ollama_usage.cli.time.sleep") as mock_sleep:
            _autorefresh_sleep(120)
        mock_sleep.assert_called_once_with(120)

    def test_autorefresh_sleep_writes_single_countdown_line(self, capsys) -> None:
        from datetime import datetime, timedelta
        from ollama_usage.cli import _autorefresh_sleep
        fixed = datetime(2026, 8, 8, 13, 46, 5)
        with patch("ollama_usage.cli.datetime") as mock_dt, \
             patch("ollama_usage.cli.sys.stdout.isatty", return_value=True), \
             patch("ollama_usage.cli.time.sleep"), \
             patch.dict("os.environ", {"NO_COLOR": "1"}):
            mock_dt.now.return_value = fixed
            mock_dt.timedelta = timedelta
            _autorefresh_sleep(3)
        out = capsys.readouterr().out
        # A blank line precedes the single \r-overwritten countdown line.
        # The timestamp is fixed (calculated once) and the current time is
        # never shown.
        assert out.startswith("\n")
        assert out.count("\n") == 1
        assert "next refresh in" in out
        assert "2026-08-08 13-46-08" in out
        # The current time is NOT shown.
        assert "13-46-05" not in out

    def test_autorefresh_sleep_timestamp_is_fixed(self, capsys) -> None:
        from datetime import datetime, timedelta
        from ollama_usage.cli import _autorefresh_sleep
        fixed = datetime(2026, 8, 8, 13, 46, 5)
        with patch("ollama_usage.cli.datetime") as mock_dt, \
             patch("ollama_usage.cli.sys.stdout.isatty", return_value=True), \
             patch("ollama_usage.cli.time.sleep"), \
             patch.dict("os.environ", {"NO_COLOR": "1"}):
            mock_dt.now.side_effect = [fixed, fixed, fixed]
            mock_dt.timedelta = timedelta
            _autorefresh_sleep(3)
        out = capsys.readouterr().out
        # The timestamp stays fixed across all countdown ticks (it appears on
        # each \r rewrite, but always with the same value, never advancing).
        assert "2026-08-08 13-46-08" in out
        assert "13-46-09" not in out


# ---------------------------------------------------------------------------
# Minidisplay
# ---------------------------------------------------------------------------

class TestFormatRemainingCompact:

    def test_days_hours_minutes(self) -> None:
        from datetime import datetime, timezone
        fixed = datetime(2026, 4, 2, 14, 18, 0, tzinfo=timezone.utc)
        with patch("ollama_usage.cli.datetime") as mock_dt:
            mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
            mock_dt.now.return_value = fixed
            mock_dt.timezone = timezone
            result = _format_remaining_compact("2026-04-04T17:00:00Z")
        assert result == "2d 02:42"

    def test_colored_days_hours_minutes(self) -> None:
        from datetime import datetime, timezone
        from ollama_usage.cli import _ANSI
        fixed = datetime(2026, 4, 2, 14, 18, 0, tzinfo=timezone.utc)
        with patch("ollama_usage.cli.datetime") as mock_dt:
            mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
            mock_dt.now.return_value = fixed
            mock_dt.timezone = timezone
            result = _format_remaining_compact("2026-04-04T17:00:00Z", use_color=True)
        assert _ANSI["yellow"] + "2" + _ANSI["reset"] + _ANSI["white"] + "d" + _ANSI["reset"] in result
        assert _ANSI["cyan"] + "02" + _ANSI["reset"] in result
        assert _ANSI["magenta"] + "42" + _ANSI["reset"] in result

    def test_hours_minutes_no_days(self) -> None:
        from datetime import datetime, timezone
        fixed = datetime(2026, 4, 2, 14, 18, 0, tzinfo=timezone.utc)
        with patch("ollama_usage.cli.datetime") as mock_dt:
            mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
            mock_dt.now.return_value = fixed
            mock_dt.timezone = timezone
            result = _format_remaining_compact("2026-04-02T16:00:00Z")
        assert result == "01:42"

    def test_past_returns_zero(self) -> None:
        assert _format_remaining_compact("2000-01-01T00:00:00Z") == "00:00"

    def test_invalid_returns_empty(self) -> None:
        assert _format_remaining_compact("not-a-date") == ""


class TestFormatCountdown:

    def test_under_a_minute(self) -> None:
        assert _format_countdown(42) == "(42)"

    def test_over_a_minute(self) -> None:
        assert _format_countdown(125) == "(2:05)"

    def test_exactly_a_minute(self) -> None:
        assert _format_countdown(60) == "(1:00)"


class TestMiniLine:

    def test_plain_output(self) -> None:
        data = make_data(42.0, 77.0, web_search_requests=2)
        line = _mini_line(data, use_color=False)
        assert line.startswith("olu (FREE) s:  42.0% (")
        assert " | w:  77.0% (" in line
        assert " ws: 2 wr: 0" in line
    def test_web_fetch_shown_when_present(self) -> None:
        data = make_data(42.0, 77.0, web_fetch_requests=5)
        line = _mini_line(data, use_color=False)
        assert " ws: 0 wr: 5" in line

    def test_web_search_absent_shows_zero(self) -> None:
        data = make_data(42.0, 77.0)
        line = _mini_line(data, use_color=False)
        assert " ws: 0 wr: 0" in line

    def test_color_wraps_plan_and_web_search(self) -> None:
        from ollama_usage.cli import _ANSI
        data = make_data(42.0, 77.0, web_search_requests=2)
        line = _mini_line(data, use_color=True)
        assert _ANSI["orange"] + "FREE" + _ANSI["reset"] in line
        assert _ANSI["cyan"] + "2" + _ANSI["reset"] in line
        # The plan parentheses and the | separator use the decorator color.
        assert _ANSI["grey"] + "(" + _ANSI["reset"] in line
        assert _ANSI["grey"] + ")" + _ANSI["reset"] in line
        assert _ANSI["grey"] + "|" + _ANSI["reset"] in line


class TestMiniHorizontal:

    def test_plain_output(self) -> None:
        data = make_data(42.0, 77.0, web_search_requests=2)
        out = _mini_horizontal(data, use_color=False)
        lines = out.split("\n")
        assert len(lines) == 5
        assert lines[0] == "olu (FREE)"
        assert lines[1].startswith("s:  42.0% (")
        assert lines[2].startswith("w:  77.0% (")
        assert lines[3] == "ws: 2"
        assert lines[4] == "wr: 0"

    def test_web_search_absent_shows_zero(self) -> None:
        data = make_data(42.0, 77.0)
        out = _mini_horizontal(data, use_color=False)
        assert out.endswith("\nws: 0\nwr: 0")

    def test_color_wraps_plan_and_web_search(self) -> None:
        from ollama_usage.cli import _ANSI
        data = make_data(42.0, 77.0, web_search_requests=2)
        out = _mini_horizontal(data, use_color=True)
        assert _ANSI["orange"] + "FREE" + _ANSI["reset"] in out
        assert _ANSI["cyan"] + "2" + _ANSI["reset"] in out
        assert _ANSI["grey"] + "(" + _ANSI["reset"] in out
        assert _ANSI["grey"] + ")" + _ANSI["reset"] in out


class TestDisplayMinidisplay:

    def test_minidisplay_prints_single_line(self, capsys) -> None:
        display(make_data(42.0, 77.0, web_search_requests=2), as_json=False, quiet=False, minidisplay=True)
        out = capsys.readouterr().out
        assert out.count("\n") == 1
        assert out.startswith("olu (FREE) s:")

    def test_json_takes_precedence_over_minidisplay(self, capsys) -> None:
        import json
        display(make_data(42.0, 77.0), as_json=True, quiet=False, minidisplay=True)
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["session"]["used_pct"] == 42.0

    def test_horizontal_prints_multi_line(self, capsys) -> None:
        display(
            make_data(42.0, 77.0, web_search_requests=2),
            as_json=False, quiet=False, minidisplay_horizontal=True,
        )
        out = capsys.readouterr().out
        assert out.count("\n") == 5
        assert out.startswith("olu (FREE)")
        assert "\ns:  42.0% (" in out
        assert "\nws: 2\nwr: 0" in out


class TestAutorefreshSleepMini:

    def test_non_tty_sleeps_once(self) -> None:
        with patch("ollama_usage.cli.sys.stdout.isatty", return_value=False), \
             patch("ollama_usage.cli.time.sleep") as mock_sleep:
            _autorefresh_sleep_mini(120, "prefix")
        mock_sleep.assert_called_once_with(120)

    def test_writes_countdown_with_prefix(self, capsys) -> None:
        with patch("ollama_usage.cli.sys.stdout.isatty", return_value=True), \
             patch("ollama_usage.cli.time.sleep"), \
             patch.dict("os.environ", {"NO_COLOR": "1"}):
            _autorefresh_sleep_mini(3, "olu - s: x")
        out = capsys.readouterr().out
        assert "olu - s: x" in out
        assert "(3)" in out
        assert "(2)" in out
        assert "(1)" in out

    def test_countdown_is_decorator_when_colored(self, capsys) -> None:
        from ollama_usage.cli import _ANSI
        with patch("ollama_usage.cli.sys.stdout.isatty", return_value=True), \
             patch("ollama_usage.cli.time.sleep"), \
             patch.dict("os.environ", {}, clear=True):
            _autorefresh_sleep_mini(2, "prefix")
        out = capsys.readouterr().out
        assert _ANSI["grey"] + "(2)" + _ANSI["reset"] in out


class TestAutorefreshSleepHorizontal:

    def test_non_tty_sleeps_once(self) -> None:
        with patch("ollama_usage.cli.sys.stdout.isatty", return_value=False), \
             patch("ollama_usage.cli.time.sleep") as mock_sleep:
            _autorefresh_sleep_horizontal(120, "a\nb\nc\nd")
        mock_sleep.assert_called_once_with(120)

    def test_writes_block_and_countdown(self, capsys) -> None:
        block = "olu (free)\ns:  42.0% (00:00)\nw:  77.0% (00:00)\nwr: 2"
        with patch("ollama_usage.cli.sys.stdout.isatty", return_value=True), \
             patch("ollama_usage.cli.time.sleep"), \
             patch.dict("os.environ", {"NO_COLOR": "1"}):
            _autorefresh_sleep_horizontal(2, block)
        out = capsys.readouterr().out
        assert block in out
        # Countdown sits on the same line as wr:, separated by two spaces.
        assert "wr: 2  (2)" in out
        assert "wr: 2  (1)" in out

    def test_countdown_is_decorator_when_colored(self, capsys) -> None:
        from ollama_usage.cli import _ANSI
        with patch("ollama_usage.cli.sys.stdout.isatty", return_value=True), \
             patch("ollama_usage.cli.time.sleep"), \
             patch.dict("os.environ", {}, clear=True):
            _autorefresh_sleep_horizontal(2, "olu\ns: x")
        out = capsys.readouterr().out
        assert _ANSI["grey"] + "(2)" + _ANSI["reset"] in out