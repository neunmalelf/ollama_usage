"""Tests for ollama_usage.widget state persistence."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from ollama_usage import widget as w


# ---------------------------------------------------------------------------
# _resolve_size — size persistence
# ---------------------------------------------------------------------------

class TestResolveSize:

    def test_explicit_size_wins(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(w, "_STATE_FILE", tmp_path / "state.json")
        w._STATE_FILE.write_text(
            json.dumps({"size": "compact"}), encoding="utf-8"
        )
        assert _make_widget()._resolve_size("full") == "full"

    def test_restores_saved_size_when_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(w, "_STATE_FILE", tmp_path / "state.json")
        w._STATE_FILE.write_text(
            json.dumps({"size": "compact"}), encoding="utf-8"
        )
        assert _make_widget()._resolve_size(None) == "compact"

    def test_defaults_to_full_when_no_saved_size(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(w, "_STATE_FILE", tmp_path / "state.json")
        w._STATE_FILE.write_text(json.dumps({"x": 1}), encoding="utf-8")
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
        monkeypatch.setattr(w, "_STATE_FILE", tmp_path / "state.json")
        w._STATE_FILE.write_text(
            json.dumps({"x": 123, "y": 456, "size": "compact"}), encoding="utf-8"
        )
        inst = _make_widget(size="compact", position=None)
        inst._restore_position()
        inst._root.geometry.assert_called_once_with("+123+456")

    def test_named_position_overrides_saved(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(w, "_STATE_FILE", tmp_path / "state.json")
        w._STATE_FILE.write_text(
            json.dumps({"x": 123, "y": 456, "size": "full"}), encoding="utf-8"
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
    }
    data.update(overrides)
    return data


class TestMiniSegments:

    def test_layout_matches_minidisplay(self) -> None:
        segs = w._mini_segments(_make_data(), w.THEMES["minimal"])
        text = "".join(t for t, _ in segs)
        assert text == "olu (pro) s: 2.6% (00:00) | w: 1.9% (00:00) wr: 2"

    def test_plan_is_orange(self) -> None:
        segs = w._mini_segments(_make_data(), w.THEMES["minimal"])
        plan = next(t for t, c in segs if c == w.THEMES["minimal"][w._PLAN_COLOR])
        assert plan == "pro"

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
        assert text.endswith("wr: 0")

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
