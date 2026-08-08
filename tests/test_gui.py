"""Tests for ollama_usage.gui."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from ollama_usage.gui import build_lines, _seconds_until, _fmt_countdown, APP_NAME


# ---------------------------------------------------------------------------
# build_lines — pure display content (headless-testable)
# ---------------------------------------------------------------------------

def make_data(
    plan: str = "pro",
    session_pct: float = 2.6,
    weekly_pct: float = 1.9,
    web_search_requests: int | None = None,
    models: list | None = None,
) -> dict:
    return {
        "plan": plan,
        "session": {"used_pct": session_pct, "resets_at": "2026-08-05T20:00:00Z"},
        "weekly": {"used_pct": weekly_pct, "resets_at": "2026-08-10T00:00:00Z"},
        "web_search_requests": web_search_requests,
        "models": models,
    }


class TestBuildLines:

    def test_error_returns_error_line(self) -> None:
        lines = build_lines(None, error="Network error")
        assert lines == ["Error: Network error"]

    def test_no_data_returns_loading(self) -> None:
        assert build_lines(None) == ["Loading…"]

    def test_plan_is_shown(self) -> None:
        lines = build_lines(make_data(plan="free"))
        assert any("free" in line for line in lines)

    def test_session_and_weekly_percentages(self) -> None:
        lines = build_lines(make_data(session_pct=2.6, weekly_pct=1.9))
        text = "\n".join(lines)
        assert "2.6%" in text
        assert "1.9%" in text

    def test_web_search_omitted_when_absent(self) -> None:
        lines = build_lines(make_data())
        assert not any("WebSearch" in line for line in lines)

    def test_web_search_shown_when_present(self) -> None:
        lines = build_lines(make_data(web_search_requests=2))
        assert any("WebSearch" in line and "2" in line for line in lines)

    def test_models_shown_when_present(self) -> None:
        models = [{"name": "glm-5.2", "requests": 2}]
        lines = build_lines(make_data(models=models))
        text = "\n".join(lines)
        assert "Model calls this week" in text
        assert "glm-5.2" in text

    def test_models_omitted_when_absent(self) -> None:
        lines = build_lines(make_data())
        assert not any("Model calls this week" in line for line in lines)


# ---------------------------------------------------------------------------
# _seconds_until / _fmt_countdown
# ---------------------------------------------------------------------------

class TestCountdown:

    def test_seconds_until_past_is_zero(self) -> None:
        assert _seconds_until("2000-01-01T00:00:00Z") == 0

    def test_fmt_countdown_now(self) -> None:
        assert _fmt_countdown(0) == "now"

    def test_fmt_countdown_hours(self) -> None:
        assert _fmt_countdown(2 * 3600 + 42 * 60) == "2h 42m"

    def test_fmt_countdown_minutes(self) -> None:
        assert _fmt_countdown(90) == "1m 30s"

    def test_fmt_countdown_seconds(self) -> None:
        assert _fmt_countdown(5) == "5s"


# ---------------------------------------------------------------------------
# OllamaGui — window wiring (tkinter mocked, no display needed)
# ---------------------------------------------------------------------------

class TestOllamaGui:

    def _make_gui(self, data: dict | None = None, error: str | None = None):
        """Build an OllamaGui with a mocked tkinter root and a stubbed fetch."""
        fake_root = MagicMock()
        fake_text = MagicMock()
        fake_btn = MagicMock()
        fake_frame = MagicMock()

        with patch("ollama_usage.gui.tk.Tk", return_value=fake_root), \
             patch("ollama_usage.gui.tk.Text", return_value=fake_text), \
             patch("ollama_usage.gui.tk.Button", return_value=fake_btn), \
             patch("ollama_usage.gui.tk.Frame", return_value=fake_frame):
            from ollama_usage.gui import OllamaGui
            gui = OllamaGui(cookie="fake-cookie")
            gui._data = data
            gui._error = error
            return gui, fake_root, fake_text

    def test_title_contains_app_name_and_version(self) -> None:
        from ollama_usage import __version__
        gui, fake_root, _ = self._make_gui()
        expected = f"{APP_NAME} ({__version__})"
        fake_root.title.assert_called_once_with(expected)

    def test_ok_button_quits(self) -> None:
        gui, fake_root, _ = self._make_gui()
        with patch("ollama_usage.gui.sys.exit") as mock_exit:
            gui._quit()
        fake_root.destroy.assert_called_once()
        mock_exit.assert_called_once_with(0)

    def test_refresh_button_triggers_fetch(self) -> None:
        gui, fake_root, _ = self._make_gui()
        with patch.object(gui, "_fetch_async") as mock_fetch:
            gui._refresh()
        mock_fetch.assert_called_once()

    def test_redraw_inserts_built_lines(self) -> None:
        gui, fake_root, fake_text = self._make_gui(
            data=make_data(session_pct=2.6, weekly_pct=1.9)
        )
        gui._redraw()
        fake_text.delete.assert_called_once_with("1.0", "end")
        inserted = fake_text.insert.call_args[0][1]
        assert "2.6%" in inserted
        assert "1.9%" in inserted

    def test_redraw_shows_error(self) -> None:
        gui, fake_root, fake_text = self._make_gui(error="Network error")
        gui._redraw()
        inserted = fake_text.insert.call_args[0][1]
        assert "Network error" in inserted

    def test_fetch_success_updates_data_and_schedules_redraw(self) -> None:
        gui, fake_root, _ = self._make_gui()
        data = make_data()
        with patch("ollama_usage.gui.get_usage", return_value=data):
            gui._fetch()
        assert gui._data == data
        assert gui._error is None
        fake_root.after.assert_called_once()
        scheduled = fake_root.after.call_args[0][1]
        assert scheduled == gui._redraw

    def test_fetch_network_error_sets_error(self) -> None:
        from ollama_usage.exceptions import NetworkError
        gui, fake_root, _ = self._make_gui()
        with patch("ollama_usage.gui.get_usage", side_effect=NetworkError("down")):
            gui._fetch()
        assert gui._error == "Network error"

    def test_fetch_auth_error_refreshes_cookie(self) -> None:
        from ollama_usage.exceptions import AuthError
        gui, fake_root, _ = self._make_gui()
        data = make_data()
        with patch("ollama_usage.gui.get_usage", side_effect=[AuthError("expired"), data]):
            gui._fetch()
        assert gui._data == data
        assert gui._error is None
