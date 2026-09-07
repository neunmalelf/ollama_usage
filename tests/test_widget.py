"""Tests for ollama_usage.widget state persistence."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from ollama_usage import widget as w


# ---------------------------------------------------------------------------
# _resolve_size — size persistence
# ---------------------------------------------------------------------------

class TestResolveSize:

    def test_explicit_size_wins(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(w, "_STATE_FILE", tmp_path / "state.cfg")
        w._STATE_FILE.write_text("[widget]\nsize = compact\n", encoding="utf-8")
        assert _make_widget()._resolve_size("full") == "full"

    def test_restores_saved_size_when_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(w, "_STATE_FILE", tmp_path / "state.cfg")
        w._STATE_FILE.write_text("[widget]\nsize = compact\n", encoding="utf-8")
        assert _make_widget()._resolve_size(None) == "compact"

    def test_defaults_to_full_when_no_saved_size(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(w, "_STATE_FILE", tmp_path / "state.cfg")
        w._STATE_FILE.write_text("[widget]\nx = 1\n", encoding="utf-8")
        assert _make_widget()._resolve_size(None) == "full"


# ---------------------------------------------------------------------------
# _load_state / _save_state — roundtrip
# ---------------------------------------------------------------------------

class TestStateRoundtrip:

    def test_save_then_load(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(w, "_STATE_FILE", tmp_path / "state.json")
        w._save_state({"x": 10, "y": 20, "size": "compact"})
        assert w._load_state() == {"x": 10, "y": 20, "size": "compact"}

    def test_load_missing_returns_empty(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(w, "_STATE_FILE", tmp_path / "missing.json")
        assert w._load_state() == {}


# ---------------------------------------------------------------------------
# _restore_position — position persistence
# ---------------------------------------------------------------------------

def _make_widget(size: str = "full", position: str | None = None):
    inst = w.OllamaWidget.__new__(w.OllamaWidget)
    inst._root = MagicMock()
    inst._root.winfo_screenwidth.return_value = 1920
    inst._root.winfo_screenheight.return_value = 1080
    inst._size = size
    inst._position = position
    return inst


class TestRestorePosition:

    def test_restores_saved_position_when_no_named(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(w, "_STATE_FILE", tmp_path / "state.cfg")
        w._STATE_FILE.write_text(
            "[widget]\nx = 123\ny = 456\nsize = compact\n", encoding="utf-8"
        )
        inst = _make_widget(size="compact", position=None)
        inst._restore_position()
        inst._root.geometry.assert_called_once_with("+123+456")

    def test_named_position_overrides_saved(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(w, "_STATE_FILE", tmp_path / "state.cfg")
        w._STATE_FILE.write_text(
            "[widget]\nx = 123\ny = 456\nsize = full\n", encoding="utf-8"
        )
        inst = _make_widget(size="full", position="top-left")
        inst._restore_position()
        # top-left -> (10, 10)
        inst._root.geometry.assert_called_once_with("+10+10")

    def test_save_position_persists_xy_and_size(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(w, "_STATE_FILE", tmp_path / "state.json")
        inst = _make_widget(size="compact", position=None)
        inst._root.winfo_x.return_value = 77
        inst._root.winfo_y.return_value = 88
        inst._save_position()
        assert w._load_state() == {"x": 77, "y": 88, "size": "compact"}

# ---------------------------------------------------------------------------
# _mini_segments / _mini_countdown_segments — compact minidisplay layout
# ---------------------------------------------------------------------------

def _make_data(**overrides) -> dict:
    data = {
        "plan": "pro",
        "session": {"used_pct": 2.6, "resets_at": "2026-04-04T17:00:00Z"},
        "weekly": {"used_pct": 1.9, "resets_at": "2026-04-06T00:00:00Z"},
        "web_search_requests": 2,
        "web_fetch_requests": 0,
    }
    data.update(overrides)
    return data


class TestMiniSegments:

    def test_layout_matches_minidisplay(self) -> None:
        segs = w._mini_segments(_make_data(), w.THEMES["minimal"])
        text = "".join(t for t, _ in segs)
        assert text == "olu (PRO) s: 2.6% (00:00) | w: 1.9% (00:00) ws: 2 wr: 0"

    def test_plan_is_orange(self) -> None:
        segs = w._mini_segments(_make_data(), w.THEMES["minimal"])
        plan = next(t for t, c in segs if c == w.THEMES["minimal"][w._PLAN_COLOR])
        assert plan == "PRO"

    def test_plan_uses_canonical_display_name(self) -> None:
        segs = w._mini_segments(_make_data(plan="pro"), w.THEMES["minimal"])
        text = "".join(t for t, _ in segs)
        assert "(PRO)" in text

    def test_session_percentage_is_green(self) -> None:
        segs = w._mini_segments(
            _make_data(session={"used_pct": 90.0, "resets_at": "2026-04-04T17:00:00Z"}),
            w.THEMES["minimal"],
        )
        session_pct = next(
            t for t, c in segs if c == w.THEMES["minimal"][w._SESSION_PCT_COLOR]
        )
        assert session_pct == "90.0"

    def test_web_search_absent_shows_zero(self) -> None:
        segs = w._mini_segments(_make_data(web_search_requests=None), w.THEMES["minimal"])
        text = "".join(t for t, _ in segs)
        assert text.endswith(" ws: 0 wr: 0")

    def test_web_fetch_shown_when_present(self) -> None:
        segs = w._mini_segments(_make_data(web_fetch_requests=5), w.THEMES["minimal"])
        text = "".join(t for t, _ in segs)
        assert text.endswith(" wr: 5")

    def test_countdown_compact_format(self) -> None:
        segs = w._mini_countdown_segments(90061, w.THEMES["minimal"])
        text = "".join(t for t, _ in segs)
        assert text == "1d 01:01"

class TestCountdownSegments:

    def test_no_seconds_shown(self) -> None:
        segs = w._countdown_segments(90061, w.THEMES["minimal"])
        text = "".join(t for t, _ in segs)
        assert "s" not in text
        assert text == "1d 01h 01m"

    def test_under_a_minute_shows_zero_minutes(self) -> None:
        segs = w._countdown_segments(30, w.THEMES["minimal"])
        text = "".join(t for t, _ in segs)
        assert text == "00m"


class TestDrawFullWebSearch:

    def test_web_search_requests_label_and_value_color(self) -> None:
        inst = w.OllamaWidget.__new__(w.OllamaWidget)
        inst._canvas = MagicMock()
        inst._canvas.bbox.return_value = (0, 0, 10, 10)
        inst._theme = w.THEMES["minimal"]
        inst._size = "full"
        inst._data = {
            "plan": "pro",
            "session": {"used_pct": 2.6, "resets_at": "2026-04-04T17:00:00Z"},
            "weekly": {"used_pct": 1.9, "resets_at": "2026-04-06T00:00:00Z"},
            "web_search_requests": 7,
        }
        inst._error = None
        inst._autorefresh = False
        inst._draw_full()
        texts = []
        for call in inst._canvas.create_text.call_args_list:
            args, kwargs = call
            if kwargs.get("text") is not None:
                texts.append(kwargs["text"])
            elif len(args) > 1:
                texts.append(args[1])
        joined = "".join(texts)
        assert "Web search requests: " in joined
        assert "7" in joined
        # The number uses the value color.
        value_color = w.THEMES["minimal"][w._VALUE_COLOR]
        value_fills = [
            kwargs.get("fill")
            for call in inst._canvas.create_text.call_args_list
            for _args, kwargs in [call]
            if kwargs.get("text") == "7"
        ]
        assert value_fills and value_fills[0] == value_color
    def test_web_fetch_requests_label_and_value_color(self) -> None:
        inst = w.OllamaWidget.__new__(w.OllamaWidget)
        inst._canvas = MagicMock()
        inst._canvas.bbox.return_value = (0, 0, 10, 10)
        inst._theme = w.THEMES["minimal"]
        inst._size = "full"
        inst._data = {
            "plan": "pro",
            "session": {"used_pct": 2.6, "resets_at": "2026-04-04T17:00:00Z"},
            "weekly": {"used_pct": 1.9, "resets_at": "2026-04-06T00:00:00Z"},
            "web_fetch_requests": 4,
        }
        inst._error = None
        inst._autorefresh = False
        inst._draw_full()
        texts = []
        for call in inst._canvas.create_text.call_args_list:
            args, kwargs = call
            if kwargs.get("text") is not None:
                texts.append(kwargs["text"])
            elif len(args) > 1:
                texts.append(args[1])
        joined = "".join(texts)
        assert "Web fetch requests: " in joined
        assert "4" in joined
        value_color = w.THEMES["minimal"][w._VALUE_COLOR]
        value_fills = [
            kwargs.get("fill")
            for call in inst._canvas.create_text.call_args_list
            for _args, kwargs in [call]
            if kwargs.get("text") == "4"
        ]
        assert value_fills and value_fills[0] == value_color

class TestStatusIndicator:

    def _draw_texts(self, autorefresh: bool) -> str:
        inst = w.OllamaWidget.__new__(w.OllamaWidget)
        inst._canvas = MagicMock()
        inst._canvas.bbox.return_value = (0, 0, 10, 10)
        inst._theme = w.THEMES["minimal"]
        inst._size = "full"
        inst._data = {
            "plan": "pro",
            "session": {"used_pct": 2.6, "resets_at": "2026-04-04T17:00:00Z"},
            "weekly": {"used_pct": 1.9, "resets_at": "2026-04-06T00:00:00Z"},
            "web_search_requests": 7,
            "web_fetch_requests": 4,
        }
        inst._error = None
        inst._autorefresh = autorefresh
        inst._draw_full()
        return "".join(
            k.get("text") or ""
            for a, k in inst._canvas.create_text.call_args_list
        )

    def test_indicator_A_when_autorefresh(self) -> None:
        assert "A" in self._draw_texts(True)

    def test_indicator_M_when_manual(self) -> None:
        assert "M" in self._draw_texts(False)

    def test_compact_uses_indicator_letter(self) -> None:
        for autorefresh, expected in [(True, "A"), (False, "M")]:
            inst = w.OllamaWidget.__new__(w.OllamaWidget)
            inst._canvas = MagicMock()
            inst._canvas.bbox.return_value = (0, 0, 10, 10)
            inst._theme = w.THEMES["minimal"]
            inst._size = "compact"
            inst._data = {
                "plan": "pro",
                "session": {"used_pct": 2.6, "resets_at": "2026-04-04T17:00:00Z"},
                "weekly": {"used_pct": 1.9, "resets_at": "2026-04-06T00:00:00Z"},
                "web_search_requests": 2,
                "web_fetch_requests": 5,
            }
            inst._error = None
            inst._autorefresh = autorefresh
            inst._draw_compact()
            texts = "".join(
                k.get("text") or ""
                for a, k in inst._canvas.create_text.call_args_list
            )
            assert expected in texts

class TestCtrlQBinding:

    def test_canvas_binds_ctrl_q_to_quit(self) -> None:
        inst = w.OllamaWidget.__new__(w.OllamaWidget)
        inst._root = MagicMock()
        inst._canvas = MagicMock()
        fake_canvas = MagicMock()
        with patch("ollama_usage.widget.tk.Canvas", return_value=fake_canvas):
            inst._size = "full"
            inst._theme = w.THEMES["minimal"]
            inst._setup_canvas()
        canvas_binds = [c.args[0] for c in fake_canvas.bind.call_args_list]
        root_binds = [c.args[0] for c in inst._root.bind.call_args_list]
        assert "<Control-q>" in canvas_binds
        assert "<Control-Q>" in canvas_binds
        assert "<Control-q>" in root_binds
        assert "<Control-Q>" in root_binds

# ---------------------------------------------------------------------------
# _fit_compact_segments — compact minidisplay line fitting
# ---------------------------------------------------------------------------

def _measure_len(text: str) -> int:
    """Deterministic stand-in for font measurement (7 px per char)."""
    return len(text) * 7


class TestFitCompactSegments:

    def test_short_line_unchanged(self) -> None:
        segs = [("olu ", "g"), ("(PRO)", "o"), (" s: 2.6% (00:00)", "g")]
        out = w._fit_compact_segments(segs, "o", _measure_len, 2000)
        assert out == segs

    def test_long_plan_ellipsized_keeps_quota_values(self) -> None:
        segs = [
            ("olu ", "g"),
            ("(DEEPSEEK-V4-FLASH:CLOUD)", "o"),
            (" s: 42.1% (05:39) | w: 12.3% (2d 09:39) ws: 12 wr: 4", "g"),
        ]
        # Only the plan name overflows: give the fixed parts full room plus a
        # 100 px plan budget, so the tail must stay intact.
        fixed = sum(_measure_len(t) for t, _ in segs) - _measure_len("(DEEPSEEK-V4-FLASH:CLOUD)")
        max_width = fixed + 100
        out = w._fit_compact_segments(segs, "o", _measure_len, max_width)
        text = "".join(t for t, _ in out)
        assert "…" in text
        assert "ws: 12" in text and "wr: 4" in text
        assert sum(_measure_len(t) for t, _ in out) <= max_width

    def test_tail_truncated_when_short_plan_still_overflows(self) -> None:
        segs = [
            ("olu ", "g"),
            ("(PRO)", "o"),
            (" s: 42.1% (05:39) | w: 12.3% (2d 09:39) ws: 12 wr: 4", "g"),
        ]
        max_width = (
            _measure_len("olu ") + _measure_len("(PRO)") + _measure_len(" s: 42.1% (05:39)")
        )
        out = w._fit_compact_segments(segs, "o", _measure_len, max_width)
        text = "".join(t for t, _ in out)
        assert "…" in text
        assert sum(_measure_len(t) for t, _ in out) <= max_width


class TestCompactFitDraw:

    class _FakeFont:
        def measure(self, text: str) -> int:
            return len(text) * 7

    def _draw(self, plan: str, autorefresh: bool = True) -> list[str]:
        inst = w.OllamaWidget.__new__(w.OllamaWidget)
        inst._canvas = MagicMock()
        inst._canvas.bbox.return_value = (0, 0, 10, 10)
        inst._theme = w.THEMES["minimal"]
        inst._size = "compact"
        inst._data = {
            "plan": plan,
            "session": {"used_pct": 42.1, "resets_at": "2026-08-28T20:00:00Z"},
            "weekly": {"used_pct": 12.3, "resets_at": "2026-08-31T00:00:00Z"},
            "web_search_requests": 12,
            "web_fetch_requests": 4,
        }
        inst._error = None
        inst._autorefresh = autorefresh
        with patch("ollama_usage.widget.tkfont.Font", return_value=self._FakeFont()):
            inst._draw_compact()
        return [
            k.get("text") or ""
            for a, k in inst._canvas.create_text.call_args_list
        ]

    def test_long_plan_ellipsized_quota_values_visible(self) -> None:
        texts = self._draw("deepseek-v4-flash:cloud")
        joined = "".join(texts)
        assert "…" in joined
        assert "ws: 12" in joined
        assert "wr: 4" in joined

    def test_indicator_drawn_after_line(self) -> None:
        texts = self._draw("pro")
        assert texts[-1] == "A"


# ---------------------------------------------------------------------------
# _poll_fetch — main-thread fetch completion
# ---------------------------------------------------------------------------

class TestPollFetch:

    def _inst(self, fetching: bool):
        inst = w.OllamaWidget.__new__(w.OllamaWidget)
        inst._root = MagicMock()
        inst._canvas = MagicMock()
        inst._theme = w.THEMES["minimal"]
        inst._size = "full"
        inst._is_running = True
        inst._is_fetching = threading.Event()
        if fetching:
            inst._is_fetching.set()
        inst._interval = 30
        inst._after_id = None
        inst._draw = MagicMock()
        inst._fetch_async = MagicMock()
        return inst

    def test_poll_redraws_and_reschedules_when_done(self) -> None:
        inst = self._inst(fetching=False)
        inst._poll_fetch()
        inst._draw.assert_called_once()
        inst._root.after.assert_called_once_with(30000, inst._fetch_async)
        assert inst._after_id is not None

    def test_poll_waits_while_fetching(self) -> None:
        inst = self._inst(fetching=True)
        inst._poll_fetch()
        inst._draw.assert_not_called()
        inst._root.after.assert_called_once_with(50, inst._poll_fetch)

    def test_poll_stops_when_not_running(self) -> None:
        inst = self._inst(fetching=True)
        inst._is_running = False
        inst._poll_fetch()
        inst._root.after.assert_not_called()

    def test_fetch_async_starts_worker_and_polls(self) -> None:
        inst = self._inst(fetching=False)
        # _inst() stubs _fetch_async for the poll tests; use the real method here.
        inst._fetch_async = w.OllamaWidget._fetch_async.__get__(inst)
        with patch("ollama_usage.widget.threading.Thread") as mock_thread:
            inst._fetch_async()
        mock_thread.assert_called_once()
        assert inst._is_fetching.is_set()
        inst._root.after.assert_called_once_with(50, inst._poll_fetch)

# ---------------------------------------------------------------------------
# _setup_window / _bg_color — --background-transparent platform fallback
# ---------------------------------------------------------------------------

class TestSetupWindowTransparency:
    """``-transparentcolor`` is a Windows-only Tk attribute; everywhere else
    the widget falls back to the theme background, and the default opacity
    becomes 0.80 whenever ``--background-transparent`` is given."""

    @staticmethod
    def _wm_attributes_rejecting(attr, value=None):
        """Stand-in for a root on X11: every attribute is accepted except
        the Windows-only -transparentcolor."""
        if attr == "-transparentcolor":
            raise w.tk.TclError(f'bad attribute "{attr}"')

    def _inst(self, transparent: bool, opacity=None):
        inst = w.OllamaWidget.__new__(w.OllamaWidget)
        inst._root = MagicMock()
        inst._transparent = transparent
        inst._opacity_requested = opacity
        inst._theme = w.THEMES["minimal"]
        return inst

    @staticmethod
    def _alpha(root) -> float:
        alphas = [
            c.args[1]
            for c in root.wm_attributes.call_args_list
            if c.args and c.args[0] == "-alpha"
        ]
        assert len(alphas) == 1
        return alphas[0]

    def test_unsupported_falls_back_to_theme_bg_and_translucent_pill(self) -> None:
        inst = self._inst(transparent=True)
        inst._root.wm_attributes.side_effect = self._wm_attributes_rejecting
        inst._setup_window()
        assert inst._transparent_supported is False
        assert inst._bg_color() == w.THEMES["minimal"]["bg"]
        inst._root.configure.assert_called_once_with(bg=w.THEMES["minimal"]["bg"])
        assert self._alpha(inst._root) == w._TRANSPARENT_OPACITY

    def test_transparent_default_opacity_applies_even_when_supported(self) -> None:
        # --background-transparent implies the 0.80 default regardless of
        # whether per-pixel transparency actually works (Windows native path).
        inst = self._inst(transparent=True)
        inst._setup_window()  # MagicMock accepts -transparentcolor
        assert inst._transparent_supported is True
        assert inst._bg_color() == w._TRANSPARENT_COLOR
        assert self._alpha(inst._root) == w._TRANSPARENT_OPACITY

    def test_explicit_opacity_wins_over_fallback_default(self) -> None:
        inst = self._inst(transparent=True, opacity=0.5)
        inst._root.wm_attributes.side_effect = self._wm_attributes_rejecting
        inst._setup_window()
        assert self._alpha(inst._root) == 0.5

    def test_without_transparent_default_opacity_applies(self) -> None:
        inst = self._inst(transparent=False)
        inst._setup_window()
        assert inst._bg_color() == w.THEMES["minimal"]["bg"]
        assert self._alpha(inst._root) == w._DEFAULT_OPACITY

    def test_opacity_clamped_to_valid_range(self) -> None:
        inst = self._inst(transparent=False, opacity=5.0)
        inst._setup_window()
        assert self._alpha(inst._root) == 1.0

    def test_topmost_and_frameless_set(self) -> None:
        inst = self._inst(transparent=True)
        inst._setup_window()
        inst._root.overrideredirect.assert_called_once_with(True)
        topmost = [
            c
            for c in inst._root.wm_attributes.call_args_list
            if c.args and c.args[0] == "-topmost"
        ]
        assert topmost and topmost[0].args[1] is True

    def test_window_type_set_before_alpha(self) -> None:
        # Tk on X11 silently ignores -alpha unless -type was set first,
        # so the ordering of the wm_attributes calls is part of the contract.
        inst = self._inst(transparent=True)
        inst._setup_window()
        attrs = [c.args[0] for c in inst._root.wm_attributes.call_args_list
                 if c.args and c.args[0] in ("-type", "-alpha")]
        assert attrs.index("-type") < attrs.index("-alpha")


# ---------------------------------------------------------------------------
# launch_widget — Qt (transparent) vs Tk backend dispatch
# ---------------------------------------------------------------------------

class TestLaunchDispatch:
    """``--background-transparent`` uses the PySide6 widget when possible;
    everything else uses the Tk widget."""

    @staticmethod
    def _launch(**kwargs):
        kwargs.setdefault("cookie", "x")
        with patch("ollama_usage.widget.check_dependencies"):
            w.launch_widget(**kwargs)

    def test_transparent_uses_qt_when_supported(self) -> None:
        qt_mod = MagicMock()
        with patch.object(w, "qt_transparency_supported", return_value=True), \
             patch.dict("sys.modules", {"ollama_usage.widget_qt": qt_mod}), \
             patch.object(w, "OllamaWidget") as tk_cls:
            self._launch(background_transparent=True)
        qt_mod.launch_widget_qt.assert_called_once()
        assert qt_mod.launch_widget_qt.call_args.kwargs["cookie"] == "x"
        assert "background_transparent" not in qt_mod.launch_widget_qt.call_args.kwargs
        tk_cls.assert_not_called()

    def test_transparent_falls_back_to_tk_when_no_qt(self) -> None:
        with patch.object(w, "qt_transparency_supported", return_value=False), \
             patch.object(w, "OllamaWidget") as tk_cls:
            self._launch(background_transparent=True, theme="minimal")
        tk_cls.assert_called_once()
        self._assert_call_kwargs(tk_cls, theme="minimal",
                                 background_transparent=True)

    def test_without_transparent_always_tk(self) -> None:
        with patch.object(w, "qt_transparency_supported", return_value=True), \
             patch.object(w, "OllamaWidget") as tk_cls:
            self._launch(background_transparent=False)
        tk_cls.assert_called_once()

    @staticmethod
    def _assert_call_kwargs(mock, **expected):
        kwargs = mock.call_args.kwargs
        for key, value in expected.items():
            assert kwargs[key] == value, f"{key}: {kwargs.get(key)!r} != {value!r}"
