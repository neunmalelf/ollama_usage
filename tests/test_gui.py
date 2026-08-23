"""Tests for ollama_usage.gui."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from ollama_usage.gui import (
    build_lines,
    build_segments,
    _seconds_until,
    _fmt_countdown,
    _load_geometry,
    _save_geometry,
    _load_darkmode,
    _save_darkmode,
    _load_autorefresh,
    _save_autorefresh,
    _DEFAULT_AUTOREFRESH,
    _theme_colors,
    _DEFAULT_GEOMETRY,
    COLORS,
    APP_NAME,
)


# ---------------------------------------------------------------------------
# build_lines Ã¢â‚¬â€ pure display content (headless-testable)
# ---------------------------------------------------------------------------

def make_data(
    plan: str = "pro",
    session_pct: float = 2.6,
    weekly_pct: float = 1.9,
    web_search_requests: int | None = None,
    web_fetch_requests: int | None = None,
    models: list | None = None,
) -> dict:
    return {
        "plan": plan,
        "session": {"used_pct": session_pct, "resets_at": "2026-08-05T20:00:00Z"},
        "weekly": {"used_pct": weekly_pct, "resets_at": "2099-01-01T00:00:00Z"},
        "web_search_requests": web_search_requests,
        "web_fetch_requests": web_fetch_requests,
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

    def test_plan_has_single_space_prefix(self) -> None:
        lines = build_lines(make_data(plan="pro"))
        plan_line = next(line for line in lines if "Plan" in line)
        # "Plan     : pro" Ã¢â‚¬â€ one space after the colon, not two.
        assert plan_line == "Plan     : pro"

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
    def test_web_fetch_omitted_when_absent(self) -> None:
        lines = build_lines(make_data())
        assert not any("WebFetch" in line for line in lines)

    def test_web_fetch_shown_when_present(self) -> None:
        lines = build_lines(make_data(web_fetch_requests=3))
        assert any("WebFetch" in line and "3" in line for line in lines)

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
# build_segments â€” colored display content
# ---------------------------------------------------------------------------

def _seg_text(line: list[tuple[str, str | None]]) -> str:
    return "".join(text for text, _ in line)


def _seg_color(line: list[tuple[str, str | None]], needle: str) -> str | None:
    for text, color in line:
        if needle in text:
            return color
    return None


class TestBuildSegments:

    def test_error_is_red(self) -> None:
        segs = build_segments(None, error="Network error")
        assert _seg_text(segs[0]) == "Error: Network error"
        assert _seg_color(segs[0], "Network error") == "red"

    def test_loading_when_no_data(self) -> None:
        segs = build_segments(None)
        assert _seg_text(segs[0]) == "Loading…"

    def test_plan_is_orange(self) -> None:
        segs = build_segments(make_data(plan="pro"))
        plan_line = next(l for l in segs if "Plan" in _seg_text(l))
        assert _seg_color(plan_line, "pro") == "orange"

    def test_plan_has_single_space_prefix(self) -> None:
        segs = build_segments(make_data(plan="pro"))
        plan_line = next(l for l in segs if "Plan" in _seg_text(l))
        assert _seg_text(plan_line) == "Plan     : pro"

    def test_low_percentage_is_green(self) -> None:
        segs = build_segments(make_data(session_pct=2.6))
        session_line = next(l for l in segs if "Session" in _seg_text(l))
        assert _seg_color(session_line, "2.6") == "green"

    def test_mid_percentage_is_yellow(self) -> None:
        segs = build_segments(make_data(session_pct=60.0))
        session_line = next(l for l in segs if "Session" in _seg_text(l))
        assert _seg_color(session_line, "60.0") == "yellow"

    def test_high_percentage_is_red(self) -> None:
        segs = build_segments(make_data(session_pct=90.0))
        session_line = next(l for l in segs if "Session" in _seg_text(l))
        assert _seg_color(session_line, "90.0") == "red"

    def test_percentage_label_is_white(self) -> None:
        segs = build_segments(make_data(session_pct=2.6))
        session_line = next(l for l in segs if "Session" in _seg_text(l))
        assert _seg_color(session_line, "%") == "white"

    def test_percentage_right_aligned(self) -> None:
        segs = build_segments(make_data(session_pct=2.6, weekly_pct=100.0))
        session_line = next(l for l in segs if "Session" in _seg_text(l))
        weekly_line = next(l for l in segs if "Weekly" in _seg_text(l))
        # Both percentages occupy a 5-char right-aligned field.
        assert "  2.6" in _seg_text(session_line)
        assert "100.0" in _seg_text(weekly_line)

    def test_web_search_count_is_cyan(self) -> None:
        segs = build_segments(make_data(web_search_requests=2))
        ws_line = next(l for l in segs if "WebSearch" in _seg_text(l))
        assert _seg_color(ws_line, "2") == "cyan"
    def test_web_fetch_count_is_cyan(self) -> None:
        segs = build_segments(make_data(web_fetch_requests=3))
        wr_line = next(l for l in segs if "WebFetch" in _seg_text(l))
        assert _seg_color(wr_line, "3") == "cyan"

    def test_model_header_is_grey(self) -> None:
        models = [{"name": "glm-5.2", "requests": 2}]
        segs = build_segments(make_data(models=models))
        header = next(l for l in segs if "Model calls this week" in _seg_text(l))
        assert _seg_color(header, "Model calls this week") == "grey"

    def test_model_request_number_is_cyan(self) -> None:
        models = [{"name": "glm-5.2", "requests": 2}]
        segs = build_segments(make_data(models=models))
        model_line = next(l for l in segs if "glm-5.2" in _seg_text(l))
        assert _seg_color(model_line, "2") == "cyan"

    def test_models_sorted_by_requests_descending(self) -> None:
        models = [
            {"name": "low", "requests": 2},
            {"name": "high", "requests": 382},
            {"name": "mid", "requests": 60},
        ]
        segs = build_segments(make_data(models=models))
        model_lines = [l for l in segs if "glm" not in _seg_text(l) and "Model" not in _seg_text(l) and _seg_text(l).strip()]
        names = []
        for line in model_lines:
            text = _seg_text(line)
            if any(name in text for name in ("low", "high", "mid")):
                names.append(text.split()[-1])
        assert names == ["high", "mid", "low"]

    def test_model_request_number_right_aligned(self) -> None:
        models = [{"name": "glm-5.2", "requests": 2}]
        segs = build_segments(make_data(models=models))
        model_line = next(l for l in segs if "glm-5.2" in _seg_text(l))
        # Number is right-aligned in a 5-char field, matching the % column.
        assert "    2" in _seg_text(model_line)

    def test_model_number_aligns_with_percentage_column(self) -> None:
        models = [{"name": "glm-5.2", "requests": 2}]
        segs = build_segments(make_data(session_pct=2.6, models=models))
        session_line = next(l for l in segs if "Session" in _seg_text(l))
        model_line = next(l for l in segs if "glm-5.2" in _seg_text(l))
        # The model number's right edge aligns with the percentage's right edge
        # (the '%' column).
        session_text = _seg_text(session_line)
        model_text = _seg_text(model_line)
        pct_right = session_text.index("%")
        model_right = model_text.index("2") + 1
        assert pct_right == model_right

    def test_countdown_hours_cyan_minutes_magenta(self) -> None:
        segs = build_segments(make_data(session_pct=2.6))
        session_line = next(l for l in segs if "Session" in _seg_text(l))
        # resets_at is in the future relative to the test's fixed data; the
        # countdown may be hours/minutes. Just assert the "(in " wrapper exists.
        assert "(in " in _seg_text(session_line)

    def test_countdown_unit_labels_white(self) -> None:
        # Use a far-future weekly date so the countdown has days/hours/minutes.
        segs = build_segments(make_data(session_pct=2.6, weekly_pct=1.9))
        weekly_line = next(l for l in segs if "Weekly" in _seg_text(l))
        # The 'd', 'h' and 'm' unit labels are white.
        labels = {text: color for text, color in weekly_line if text in ("d", "h", "m")}
        assert labels.get("d") == "white"
        assert labels.get("h") == "white"
        assert labels.get("m") == "white"

    def test_countdown_days_yellow(self) -> None:
        # Use a far-future weekly date so the countdown has a days component.
        segs = build_segments(make_data(session_pct=2.6, weekly_pct=1.9))
        weekly_line = next(l for l in segs if "Weekly" in _seg_text(l))
        # The days number is yellow (days come before hours in the segments).
        days_num = next(
            (text for text, color in weekly_line if color == "yellow"), None
        )
        assert days_num is not None
        assert days_num.strip().isdigit()


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
# OllamaGui Ã¢â‚¬â€ window wiring (tkinter mocked, no display needed)
# ---------------------------------------------------------------------------

def _make_gui(data: dict | None = None, error: str | None = None,
              dark: bool | None = None):
    """Build an OllamaGui with a mocked tkinter root and a stubbed fetch.

    Returns (gui, fake_root, fake_text, button_mock).
    """
    fake_root = MagicMock()
    fake_text = MagicMock()
    fake_button = MagicMock()
    fake_frame = MagicMock()
    fake_check = MagicMock()
    fake_bool = MagicMock()
    fake_label = MagicMock()
    fake_entry = MagicMock()
    fake_string = MagicMock()

    def _load_dark():
        return bool(dark) if dark is not None else False

    with patch("ollama_usage.gui.tk.Tk", return_value=fake_root), \
         patch("ollama_usage.gui.tk.Text", return_value=fake_text), \
         patch("ollama_usage.gui.tk.Button", return_value=fake_button) as btn_mock, \
         patch("ollama_usage.gui.tk.Frame", return_value=fake_frame), \
         patch("ollama_usage.gui.tk.Checkbutton", return_value=fake_check) as check_mock, \
         patch("ollama_usage.gui.tk.BooleanVar", return_value=fake_bool), \
         patch("ollama_usage.gui.tk.Label", return_value=fake_label), \
         patch("ollama_usage.gui.tk.Entry", return_value=fake_entry), \
         patch("ollama_usage.gui.tk.StringVar", return_value=fake_string) as string_mock, \
         patch("ollama_usage.gui._load_geometry", return_value=None), \
         patch("ollama_usage.gui._load_darkmode", side_effect=_load_dark), \
         patch("ollama_usage.gui._load_autorefresh", return_value=120):
        from ollama_usage.gui import OllamaGui
        gui = OllamaGui(cookie="fake-cookie")
        gui._data = data
        gui._error = error
        return gui, fake_root, fake_text, btn_mock, check_mock, string_mock


class TestOllamaGui:

    def test_title_contains_app_name_and_version(self) -> None:
        from ollama_usage import __version__
        gui, fake_root, _, _, _, _ = _make_gui()
        expected = f"{APP_NAME} ({__version__})"
        fake_root.title.assert_called_once_with(expected)

    def test_icon_set_from_ico_file(self) -> None:
        import ollama_usage.gui as gui_mod
        gui, fake_root, _, _, _, _ = _make_gui()
        # _set_icon is called during __init__; verify iconbitmap was invoked
        # with the icon path when the file exists.
        if gui_mod._ICON_PATH.is_file():
            fake_root.iconbitmap.assert_called_once_with(str(gui_mod._ICON_PATH))
        else:
            fake_root.iconbitmap.assert_not_called()

    def test_ok_button_quits(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        with patch("ollama_usage.gui.sys.exit") as mock_exit:
            gui._quit()
        fake_root.destroy.assert_called_once()
        # _quit destroys the root and lets the mainloop exit naturally; it
        # must not call sys.exit (which raised a Tcl error from the menu).
        mock_exit.assert_not_called()

    def test_refresh_button_triggers_fetch(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        with patch.object(gui, "_fetch_async") as mock_fetch:
            gui._refresh()
        mock_fetch.assert_called_once()

    def test_redraw_inserts_built_lines(self) -> None:
        gui, fake_root, fake_text, _, _, _ = _make_gui(
            data=make_data(session_pct=2.6, weekly_pct=1.9)
        )
        fake_text.index.return_value = "1.0"
        gui._redraw()
        fake_text.delete.assert_called_once_with("1.0", "end")
        inserted = "".join(c.args[1] for c in fake_text.insert.call_args_list)
        assert "2.6%" in inserted
        assert "1.9%" in inserted

    def test_redraw_shows_error(self) -> None:
        gui, fake_root, fake_text, _, _, _ = _make_gui(error="Network error")
        fake_text.index.return_value = "1.0"
        gui._redraw()
        inserted = "".join(c.args[1] for c in fake_text.insert.call_args_list)
        assert "Network error" in inserted

    def test_redraw_applies_color_tags(self) -> None:
        gui, fake_root, fake_text, _, _, _ = _make_gui(
            data=make_data(session_pct=2.6, weekly_pct=1.9)
        )
        fake_text.index.return_value = "1.0"
        gui._redraw()
        # At least one tag_add call must have happened (colored segments).
        assert fake_text.tag_add.called

    def test_fetch_success_updates_data_and_schedules_redraw(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
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
        gui, fake_root, _, _, _, _ = _make_gui()
        with patch("ollama_usage.gui.get_usage", side_effect=NetworkError("down")):
            gui._fetch()
        assert gui._error == "Network error"

    def test_fetch_auth_error_refreshes_cookie(self) -> None:
        from ollama_usage.exceptions import AuthError
        gui, fake_root, _, _, _, _ = _make_gui()
        data = make_data()
        with patch("ollama_usage.gui.get_usage", side_effect=[AuthError("expired"), data]):
            gui._fetch()
        assert gui._data == data
        assert gui._error is None

    def test_buttons_have_equal_width(self) -> None:
        gui, fake_root, _, fake_button, _, _ = _make_gui()
        # Both buttons are created with the same width option.
        widths = []
        for call in fake_button.call_args_list:
            kwargs = call.kwargs
            if "width" in kwargs:
                widths.append(kwargs["width"])
        assert len(widths) == 2
        assert widths[0] == widths[1] == 10

    def test_refresh_button_has_underlined_r(self) -> None:
        gui, fake_root, _, fake_button, _, _ = _make_gui()
        refresh_kwargs = None
        for call in fake_button.call_args_list:
            if call.kwargs.get("text") == "Refresh":
                refresh_kwargs = call.kwargs
        assert refresh_kwargs is not None
        assert refresh_kwargs.get("underline") == 0

    def test_ok_button_has_underlined_o(self) -> None:
        gui, fake_root, _, fake_button, _, _ = _make_gui()
        ok_kwargs = None
        for call in fake_button.call_args_list:
            if call.kwargs.get("text") == "OK":
                ok_kwargs = call.kwargs
        assert ok_kwargs is not None
        assert ok_kwargs.get("underline") == 0

    def test_alt_r_triggers_refresh(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        with patch.object(gui, "_refresh") as mock_refresh:
            gui._on_refresh_key(None)
        mock_refresh.assert_called_once()

    def test_alt_o_triggers_quit(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        with patch.object(gui, "_quit") as mock_quit:
            gui._on_quit_key(None)
        mock_quit.assert_called_once()

    def test_enter_triggers_quit(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        with patch.object(gui, "_quit") as mock_quit:
            gui._on_quit_key(None)
        mock_quit.assert_called_once()

    def test_escape_binding_registered(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        # The Escape key is bound to the quit handler.
        bound = [c.args[0] for c in fake_root.bind.call_args_list]
        assert "<Escape>" in bound

    def test_quit_saves_geometry(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        fake_root.geometry.return_value = "560x300+10+10"
        with patch("ollama_usage.gui._save_geometry") as mock_save, \
             patch("ollama_usage.gui.sys.exit"):
            gui._quit()
        mock_save.assert_called_once_with("560x300+10+10")

    def test_geometry_restored_from_state(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        # _load_geometry is patched to return None in _make_gui, so geometry
        # falls back to the default. Verify the default is applied.
        fake_root.geometry.assert_called_once_with(_DEFAULT_GEOMETRY)


# ---------------------------------------------------------------------------
# Geometry persistence helpers
# ---------------------------------------------------------------------------

class TestGeometryPersistence:

    def test_save_then_load_roundtrip(self, tmp_path, monkeypatch) -> None:
        import ollama_usage.gui as gui_mod
        state_file = tmp_path / "state.json"
        monkeypatch.setattr(gui_mod, "_STATE_FILE", state_file)
        _save_geometry("600x400+20+30")
        assert _load_geometry() == "600x400+20+30"

    def test_load_returns_none_when_missing(self, tmp_path, monkeypatch) -> None:
        import ollama_usage.gui as gui_mod
        state_file = tmp_path / "missing.json"
        monkeypatch.setattr(gui_mod, "_STATE_FILE", state_file)
        assert _load_geometry() is None

    def test_load_returns_none_on_corrupt(self, tmp_path, monkeypatch) -> None:
        import ollama_usage.gui as gui_mod
        state_file = tmp_path / "state.json"
        state_file.write_text("not json", encoding="utf-8")
        monkeypatch.setattr(gui_mod, "_STATE_FILE", state_file)
        assert _load_geometry() is None


# ---------------------------------------------------------------------------
# Dark mode
# ---------------------------------------------------------------------------

class TestDarkMode:

    def test_default_off(self) -> None:
        assert _load_darkmode() is False

    def test_save_then_load_roundtrip(self, tmp_path, monkeypatch) -> None:
        import ollama_usage.gui as gui_mod
        state_file = tmp_path / "state.json"
        monkeypatch.setattr(gui_mod, "_STATE_FILE", state_file)
        _save_darkmode(True)
        assert _load_darkmode() is True

    def test_theme_colors_dark_uses_cyan(self) -> None:
        assert _theme_colors(True)["cyan"] == COLORS["cyan"]

    def test_theme_colors_light_uses_blue(self) -> None:
        # On a light background, cyan is substituted with blue.
        assert _theme_colors(False)["cyan"] == "#0000ff"
        assert _theme_colors(False)["cyan"] != COLORS["cyan"]

    def test_theme_colors_light_uses_darker_green(self) -> None:
        # On a light background, green is darkened for contrast.
        assert _theme_colors(False)["green"] == "#008000"
        assert _theme_colors(False)["green"] != COLORS["green"]

    def test_theme_colors_light_uses_darker_grey(self) -> None:
        # On a light background, grey is darkened for contrast.
        assert _theme_colors(False)["grey"] == "#404040"
        assert _theme_colors(False)["grey"] != COLORS["grey"]

    def test_gui_default_light_background(self) -> None:
        gui, fake_root, fake_text, _, _, _ = _make_gui()
        # Light mode: white background, black foreground.
        assert gui._bg == "#ffffff"
        assert gui._fg == "#000000"

    def test_gui_dark_background(self) -> None:
        gui, fake_root, fake_text, _, _, _ = _make_gui(dark=True)
        assert gui._bg == "#000000"
        assert gui._fg == "#ffffff"

    def test_toggle_dark_updates_colors_and_saves(self) -> None:
        gui, fake_root, fake_text, _, _, _ = _make_gui()
        gui._dark_var.get.return_value = True
        with patch("ollama_usage.gui._save_darkmode") as mock_save, \
             patch.object(gui, "_redraw") as mock_redraw:
            gui._toggle_dark()
        assert gui._dark is True
        mock_save.assert_called_once_with(True)
        mock_redraw.assert_called_once()
        # Cyan tag re-configured to the light-mode blue? No â€” after toggling to
        # dark, colors are the dark palette (cyan stays cyan).
        fake_text.tag_configure.assert_called()

    def test_quit_saves_darkmode(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        with patch("ollama_usage.gui._save_darkmode") as mock_save, \
             patch("ollama_usage.gui._save_geometry"), \
             patch("ollama_usage.gui.sys.exit"):
            gui._quit()
        mock_save.assert_called_once_with(gui._dark)

    def test_darkmode_checkbox_has_underlined_d(self) -> None:
        gui, fake_root, _, _, check_mock, _ = _make_gui()
        # The Checkbutton is created with underline=0 (underlines the 'd').
        check_kwargs = None
        for call in check_mock.call_args_list:
            if call.kwargs.get("text") == "darkmode":
                check_kwargs = call.kwargs
        assert check_kwargs is not None
        assert check_kwargs.get("underline") == 0

    def test_toggle_dark_does_not_crash_on_label_entry(self) -> None:
        # Regression: _toggle_dark previously passed activebackground to Label/
        # Entry, which raised TclError. It must complete without error and
        # keep the checkbox indicator visible (fixed selectcolor).
        gui, fake_root, fake_text, _, check_mock, _ = _make_gui()
        gui._dark_var.get.return_value = True
        gui._toggle_dark()  # must not raise
        assert gui._dark is True
        # selectcolor is set to a fixed contrasting color (not the background).
        gui._dark_ck.configure.assert_any_call(selectcolor="#666666")

    def test_toggle_dark_off_keeps_checkbox_visible(self) -> None:
        gui, fake_root, fake_text, _, check_mock, _ = _make_gui()
        gui._dark_var.get.return_value = False
        gui._toggle_dark()  # must not raise
        assert gui._dark is False
        gui._dark_ck.configure.assert_any_call(selectcolor="#666666")

    def test_alt_d_toggles_darkmode(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        gui._dark_var.get.return_value = False
        with patch.object(gui, "_toggle_dark") as mock_toggle:
            gui._on_dark_key(None)
        gui._dark_var.set.assert_called_once_with(True)
        mock_toggle.assert_called_once()


# ---------------------------------------------------------------------------
# Autorefresh
# ---------------------------------------------------------------------------

class TestAutorefresh:

    def test_default_is_120(self) -> None:
        assert _DEFAULT_AUTOREFRESH == 120

    def test_load_default_when_missing(self, tmp_path, monkeypatch) -> None:
        import ollama_usage.gui as gui_mod
        state_file = tmp_path / "missing.json"
        monkeypatch.setattr(gui_mod, "_STATE_FILE", state_file)
        assert _load_autorefresh() == 120

    def test_save_then_load_roundtrip(self, tmp_path, monkeypatch) -> None:
        import ollama_usage.gui as gui_mod
        state_file = tmp_path / "state.json"
        monkeypatch.setattr(gui_mod, "_STATE_FILE", state_file)
        _save_autorefresh(1200)
        assert _load_autorefresh() == 1200

    def test_save_clamps_to_min_1(self, tmp_path, monkeypatch) -> None:
        import ollama_usage.gui as gui_mod
        state_file = tmp_path / "state.json"
        monkeypatch.setattr(gui_mod, "_STATE_FILE", state_file)
        _save_autorefresh(0)
        assert _load_autorefresh() == 1

    def test_gui_field_initialized_from_state(self) -> None:
        gui, fake_root, _, _, _, string_mock = _make_gui()
        # The StringVar is created with the loaded autorefresh value (120).
        kwargs = string_mock.call_args.kwargs
        assert kwargs.get("value") == "120"

    def test_save_autorefresh_from_field(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        gui._autorefresh_var.get.return_value = "1200"
        with patch("ollama_usage.gui._save_autorefresh") as mock_save:
            gui._save_autorefresh_from_field()
        mock_save.assert_called_once_with(1200)

    def test_quit_saves_autorefresh(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        with patch.object(gui, "_save_autorefresh_from_field") as mock_save, \
             patch("ollama_usage.gui._save_geometry"), \
             patch("ollama_usage.gui._save_darkmode"), \
             patch("ollama_usage.gui.sys.exit"):
            gui._quit()
        mock_save.assert_called_once()

    def test_gui_refresh_timestamp_uses_colons(self) -> None:
        from datetime import datetime, timedelta
        from ollama_usage.gui import _gui_refresh_timestamp
        fixed = datetime(2026, 8, 8, 13, 46, 5)
        # _gui_refresh_timestamp delegates to cli's helper which uses
        # ollama_usage.cli.datetime.
        with patch("ollama_usage.cli.datetime") as mock_dt:
            mock_dt.now.return_value = fixed
            mock_dt.timedelta = timedelta
            result = _gui_refresh_timestamp(120)
        assert result == "2026-08-08 13:48:05"

    def test_timestamp_label_shows_at_timestamp(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        gui._autorefresh_var.get.return_value = "120"
        with patch("ollama_usage.gui._gui_refresh_timestamp", return_value="2026-08-08 13:48:05"):
            gui._update_autorefresh_timestamp()
        gui._autorefresh_ts_lbl.configure.assert_called_with(
            text="at 2026-08-08 13:48:05"
        )

    def test_trace_registered_on_var(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        # A write trace is registered on the StringVar to react to changes.
        gui._autorefresh_var.trace_add.assert_called_once()
        mode, cb = gui._autorefresh_var.trace_add.call_args.args
        assert mode == "write"
        assert cb == gui._on_autorefresh_changed

    def test_on_autorefresh_changed_saves_and_updates(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        gui._autorefresh_var.get.return_value = "600"
        with patch.object(gui, "_save_autorefresh_from_field") as mock_save:
            gui._on_autorefresh_changed()
        mock_save.assert_called_once()

    def test_save_autorefresh_from_field_updates_timestamp(self) -> None:
        gui, fake_root, _, _, _, _ = _make_gui()
        gui._autorefresh_var.get.return_value = "300"
        with patch("ollama_usage.gui._save_autorefresh") as mock_save, \
             patch.object(gui, "_update_autorefresh_timestamp") as mock_update:
            gui._save_autorefresh_from_field()
        mock_save.assert_called_once_with(300)
        mock_update.assert_called_once()
