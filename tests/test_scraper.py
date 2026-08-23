"""Tests for ollama_usage.scraper."""

from __future__ import annotations

import pytest

from ollama_usage.exceptions import AuthError, ParseError
from ollama_usage.scraper import parse_html, plan_display_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_html(
    plan: str = "free",
    session_pct: float = 0.0,
    session_time: str = "2026-04-04T17:00:00Z",
    weekly_pct: float = 27.9,
    weekly_time: str = "2026-04-06T00:00:00Z",
    web_search_requests: int | None = None,
    web_fetch_requests: int | None = None,
    models: list[tuple[str, int]] | None = None,
) -> str:
    """Build a minimal but realistic settings page HTML fragment."""
    segment = ""
    if web_search_requests is not None:
        segment += (
            '<button data-usage-segment data-model="web search" '
            f'data-requests="{web_search_requests}"></button>'
        )
    if web_fetch_requests is not None:
        segment += (
            '<button data-usage-segment data-model="web fetch" '
            f'data-requests="{web_fetch_requests}"></button>'
        )
    models_html = ""
    if models is not None:
        rows = "".join(
            '<span title="%s">%s</span><span class="flex-none tabular-nums"> %d requests </span>'
            % (name, name, count)
            for name, count in models
        )
        models_html = f'<div id="weekly-usage-models"><div>Models used this week</div>{rows}</div>'
    return f"""
    <span class="capitalize">{plan}</span>
    <span class="text-sm">Session usage</span>
    <span class="text-sm">{session_pct}% used</span>
    <div class="local-time" data-time="{session_time}">Resets soon</div>
    <span class="text-sm">Weekly usage</span>
    <span class="text-sm">{weekly_pct}% used</span>
    <div class="local-time" data-time="{weekly_time}">Resets soon</div>
    {segment}
    {models_html}
    """


def make_html_real(
    plan: str = "free",
    session_pct: float = 0.0,
    session_time: str = "2026-08-18T08:00:00Z",
    weekly_pct: float = 27.9,
    weekly_time: str = "2026-08-24T00:00:00Z",
    aria_labels: bool = True,
) -> str:
    """Build HTML matching the current ollama.com/settings layout.

    The visible label spans appear early in the DOM (summary), while the
    usage meters carrying the aria-labels and data-time attributes come
    later. This reproduces the bug where the weekly line showed the
    session's reset time.
    """
    def meter(label: str, pct: float, resets_at: str) -> str:
        attrs = f' aria-label="{label} {pct}% used"' if aria_labels else ""
        return (
            f'<div class="usage-meter"{attrs}>'
            f"<span>{label}</span>"
            f"<span>{pct}% used</span>"
            f'<div class="local-time" data-time="{resets_at}">Resets soon</div>'
            "</div>"
        )

    return f"""
    <span class="capitalize">{plan}</span>
    <div class="text-sm">Session usage</div>
    <div class="text-sm">{session_pct}% used</div>
    <div class="text-sm">Weekly usage</div>
    <div class="text-sm">{weekly_pct}% used</div>
    {meter("Session usage", session_pct, session_time)}
    {meter("Weekly usage", weekly_pct, weekly_time)}
    """


def make_html_reversed(
    plan: str = "free",
    session_pct: float = 0.0,
    session_time: str = "2026-04-04T17:00:00Z",
    weekly_pct: float = 27.9,
    weekly_time: str = "2026-04-06T00:00:00Z",
    web_search_requests: int | None = None,
    web_fetch_requests: int | None = None,
) -> str:
    """Build HTML with Weekly usage appearing BEFORE Session usage.

    This tests that parsing is order-independent and correctly associates
    percentages with their labeled sections.
    """
    segment = ""
    if web_search_requests is not None:
        segment += (
            '<button data-usage-segment data-model="web search" '
            f'data-requests="{web_search_requests}"></button>'
        )
    if web_fetch_requests is not None:
        segment += (
            '<button data-usage-segment data-model="web fetch" '
            f'data-requests="{web_fetch_requests}"></button>'
        )
    return f"""
    <span class="capitalize">{plan}</span>
    <span class="text-sm">Weekly usage</span>
    <span class="text-sm">{weekly_pct}% used</span>
    <div class="local-time" data-time="{weekly_time}">Resets soon</div>
    <span class="text-sm">Session usage</span>
    <span class="text-sm">{session_pct}% used</span>
    <div class="local-time" data-time="{session_time}">Resets soon</div>
    {segment}
    """


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def free_html() -> str:
    return make_html()


@pytest.fixture
def pro_html() -> str:
    return make_html(plan="pro", session_pct=45.0, weekly_pct=60.0)


@pytest.fixture
def max_html() -> str:
    return make_html(plan="max", session_pct=99.9, weekly_pct=100.0)


@pytest.fixture
def full_usage_html() -> str:
    return make_html(
        plan="pro",
        session_pct=45.0,
        session_time="2026-04-05T10:00:00Z",
        weekly_pct=80.0,
        weekly_time="2026-04-07T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

class TestPlan:

    @pytest.mark.parametrize("plan", ["free", "pro", "max"])
    def test_known_plans(self, plan: str) -> None:
        assert parse_html(make_html(plan=plan))["plan"] == plan

    def test_plan_is_lowercase(self) -> None:
        # Ollama may render "Free" or "FREE" - we always return lowercase
        html = make_html(plan="FREE")
        assert parse_html(html)["plan"] == "free"

    def test_plan_present_in_output(self, free_html: str) -> None:
        assert "plan" in parse_html(free_html)

class TestPlanDisplayName:

    @pytest.mark.parametrize("key,expected", [
        ("free", "Free"), ("pro", "Pro"), ("max", "Max"),
        ("PRO", "Pro"), ("Pro", "Pro"), ("FREE", "Free"),
    ])
    def test_canonical_display_names(self, key: str, expected: str) -> None:
        assert plan_display_name(key) == expected

    def test_unknown_plan_capitalized(self) -> None:
        assert plan_display_name("custom") == "Custom"


# ---------------------------------------------------------------------------
# Session usage
# ---------------------------------------------------------------------------

class TestSessionUsage:

    @pytest.mark.parametrize("pct", [0.0, 1.5, 27.9, 50.0, 99.9, 100.0])
    def test_session_pct_values(self, pct: float) -> None:
        assert parse_html(make_html(session_pct=pct))["session"]["used_pct"] == pct

    def test_session_pct_type_is_float(self, free_html: str) -> None:
        assert isinstance(parse_html(free_html)["session"]["used_pct"], float)

    def test_session_resets_at(self, free_html: str) -> None:
        assert parse_html(free_html)["session"]["resets_at"] == "2026-04-04T17:00:00Z"

    def test_session_resets_at_is_iso8601(self, free_html: str) -> None:
        resets_at = parse_html(free_html)["session"]["resets_at"]
        # Basic ISO 8601 check
        assert "T" in resets_at
        assert resets_at.endswith("Z")

    def test_session_keys(self, free_html: str) -> None:
        assert set(parse_html(free_html)["session"].keys()) == {"used_pct", "resets_at"}

    def test_session_zero(self) -> None:
        data = parse_html(make_html(session_pct=0.0))
        assert data["session"]["used_pct"] == 0.0

    def test_session_full(self) -> None:
        data = parse_html(make_html(session_pct=100.0))
        assert data["session"]["used_pct"] == 100.0


# ---------------------------------------------------------------------------
# Weekly usage
# ---------------------------------------------------------------------------

class TestWeeklyUsage:

    @pytest.mark.parametrize("pct", [0.0, 14.3, 50.0, 99.9, 100.0])
    def test_weekly_pct_values(self, pct: float) -> None:
        assert parse_html(make_html(weekly_pct=pct))["weekly"]["used_pct"] == pct

    def test_weekly_pct_type_is_float(self, free_html: str) -> None:
        assert isinstance(parse_html(free_html)["weekly"]["used_pct"], float)

    def test_weekly_resets_at(self, free_html: str) -> None:
        assert parse_html(free_html)["weekly"]["resets_at"] == "2026-04-06T00:00:00Z"

    def test_weekly_resets_at_is_iso8601(self, free_html: str) -> None:
        resets_at = parse_html(free_html)["weekly"]["resets_at"]
        assert "T" in resets_at
        assert resets_at.endswith("Z")

    def test_weekly_keys(self, free_html: str) -> None:
        assert set(parse_html(free_html)["weekly"].keys()) == {"used_pct", "resets_at"}

    def test_weekly_zero(self) -> None:
        data = parse_html(make_html(weekly_pct=0.0))
        assert data["weekly"]["used_pct"] == 0.0

    def test_weekly_full(self) -> None:
        data = parse_html(make_html(weekly_pct=100.0))
        assert data["weekly"]["used_pct"] == 100.0


# ---------------------------------------------------------------------------
# Web search usage
# ---------------------------------------------------------------------------

class TestWebSearchUsage:

    @pytest.mark.parametrize("count", [0, 1, 2, 12, 317])
    def test_web_search_requests_values(self, count: int) -> None:
        assert (
            parse_html(make_html(web_search_requests=count))["web_search_requests"]
            == count
        )

    def test_web_search_requests_type_is_int(self) -> None:
        assert isinstance(
            parse_html(make_html(web_search_requests=2))["web_search_requests"], int
        )

    def test_web_search_sums_multiple_segments(self) -> None:
        html = (
            '<button data-usage-segment data-model="web search" data-requests="2"></button>'
            '<button data-usage-segment data-model="web search" data-requests="5"></button>'
        )
        data = parse_html(make_html() + html)
        assert data["web_search_requests"] == 7

    def test_web_search_is_none_when_absent(self) -> None:
        assert parse_html(make_html())["web_search_requests"] is None

    def test_web_search_is_none_on_free(self, free_html: str) -> None:
        assert parse_html(free_html)["web_search_requests"] is None

    def test_web_search_reversed_order(self) -> None:
        data = parse_html(make_html_reversed(web_search_requests=3))
        assert data["web_search_requests"] == 3

class TestWebFetchUsage:

    @pytest.mark.parametrize("count", [0, 1, 2, 12, 317])
    def test_web_fetch_requests_values(self, count: int) -> None:
        assert (
            parse_html(make_html(web_fetch_requests=count))["web_fetch_requests"]
            == count
        )

    def test_web_fetch_requests_type_is_int(self) -> None:
        assert isinstance(
            parse_html(make_html(web_fetch_requests=2))["web_fetch_requests"], int
        )

    def test_web_fetch_sums_multiple_segments(self) -> None:
        html = (
            '<button data-usage-segment data-model="web fetch" data-requests="2"></button>'
            '<button data-usage-segment data-model="web fetch" data-requests="5"></button>'
        )
        data = parse_html(make_html() + html)
        assert data["web_fetch_requests"] == 7

    def test_web_fetch_is_none_when_absent(self) -> None:
        assert parse_html(make_html())["web_fetch_requests"] is None

    def test_web_fetch_is_none_on_free(self, free_html: str) -> None:
        assert parse_html(free_html)["web_fetch_requests"] is None

    def test_web_fetch_reversed_order(self) -> None:
        data = parse_html(make_html_reversed(web_fetch_requests=3))
        assert data["web_fetch_requests"] == 3

    def test_web_fetch_does_not_affect_web_search(self) -> None:
        html = make_html(web_search_requests=2, web_fetch_requests=4)
        data = parse_html(html)
        assert data["web_search_requests"] == 2
        assert data["web_fetch_requests"] == 4


# ---------------------------------------------------------------------------
# Per-model request counts
# ---------------------------------------------------------------------------

class TestModels:

    def test_models_parsed(self) -> None:
        html = make_html(models=[("glm-5.2", 2), ("web search", 2), ("deepseek-v4-flash", 60)])
        data = parse_html(html)
        assert data["models"] == [
            {"name": "glm-5.2", "requests": 2},
            {"name": "web search", "requests": 2},
            {"name": "deepseek-v4-flash", "requests": 60},
        ]

    def test_models_requests_are_int(self) -> None:
        data = parse_html(make_html(models=[("glm-5.2", 2)]))
        assert isinstance(data["models"][0]["requests"], int)

    def test_models_none_when_absent(self) -> None:
        assert parse_html(make_html())["models"] is None

    def test_models_none_on_free(self, free_html: str) -> None:
        assert parse_html(free_html)["models"] is None

    def test_models_do_not_affect_quotas(self) -> None:
        html = make_html(models=[("glm-5.2", 2)], session_pct=1.5, weekly_pct=1.7)
        data = parse_html(html)
        assert data["models"][0]["requests"] == 2
        assert data["session"]["used_pct"] == 1.5
        assert data["weekly"]["used_pct"] == 1.7


# ---------------------------------------------------------------------------
# Order-independent parsing (reversed sections)
# ---------------------------------------------------------------------------

class TestReversedOrderParsing:
    """Tests that parsing correctly associates values with sections
    regardless of the order they appear in the HTML.

    This verifies the fix for a bug where weekly usage showed session values
    when the real HTML had Weekly section before Session section.
    """

    def test_session_pct_correct_when_weekly_first(self) -> None:
        """Session percentage should be correct even when Weekly appears first."""
        html = make_html_reversed(session_pct=45.0, weekly_pct=80.0)
        data = parse_html(html)
        # Session should be 45.0, not 80.0 (the weekly value)
        assert data["session"]["used_pct"] == 45.0

    def test_weekly_pct_correct_when_weekly_first(self) -> None:
        """Weekly percentage should be correct even when Weekly appears first."""
        html = make_html_reversed(session_pct=45.0, weekly_pct=80.0)
        data = parse_html(html)
        # Weekly should be 80.0, not 45.0 (the session value)
        assert data["weekly"]["used_pct"] == 80.0

    def test_session_resets_at_correct_when_weekly_first(self) -> None:
        """Session reset time should be correct even when Weekly appears first."""
        html = make_html_reversed(
            session_time="2026-04-04T17:00:00Z",
            weekly_time="2026-04-06T00:00:00Z",
        )
        data = parse_html(html)
        assert data["session"]["resets_at"] == "2026-04-04T17:00:00Z"

    def test_weekly_resets_at_correct_when_weekly_first(self) -> None:
        """Weekly reset time should be correct even when Weekly appears first."""
        html = make_html_reversed(
            session_time="2026-04-04T17:00:00Z",
            weekly_time="2026-04-06T00:00:00Z",
        )
        data = parse_html(html)
        assert data["weekly"]["resets_at"] == "2026-04-06T00:00:00Z"

    def test_reversed_full_values(self) -> None:
        """Full structure should be correct with reversed order."""
        html = make_html_reversed(
            plan="pro",
            session_pct=45.0,
            session_time="2026-04-05T10:00:00Z",
            weekly_pct=80.0,
            weekly_time="2026-04-07T00:00:00Z",
        )
        data = parse_html(html)
        assert data == {
            "plan": "pro",
            "session": {"used_pct": 45.0, "resets_at": "2026-04-05T10:00:00Z"},
            "weekly": {"used_pct": 80.0, "resets_at": "2026-04-07T00:00:00Z"},
            "web_search_requests": None,
            "web_fetch_requests": None,
            "models": None,
        }

    @pytest.mark.parametrize("session_pct,weekly_pct", [
        (0.0, 100.0),    # session empty, weekly full
        (100.0, 0.0),    # session full, weekly empty
        (50.0, 50.0),    # equal values (but still distinct)
        (99.9, 100.0),   # edge cases
    ])
    def test_reversed_various_values(self, session_pct: float, weekly_pct: float) -> None:
        """Parsing should correctly distinguish session from weekly regardless of values."""
        html = make_html_reversed(session_pct=session_pct, weekly_pct=weekly_pct)
        data = parse_html(html)
        assert data["session"]["used_pct"] == session_pct
        assert data["weekly"]["used_pct"] == weekly_pct


# ---------------------------------------------------------------------------
# Real page layout (summary labels before usage meters)
# ---------------------------------------------------------------------------

class TestRealPageLayout:
    """Regression: the weekly line showed the session's reset time.

    On the real page the visible label spans appear early in the DOM while
    the usage meters (with their own aria-labels and data-time attributes)
    come later, so the first ``data-time`` after the weekly label is the
    session's. The parser must anchor each section on its own meter.
    """

    def test_weekly_resets_at_is_not_session_resets_at(self) -> None:
        data = parse_html(make_html_real())
        assert data["weekly"]["resets_at"] == "2026-08-24T00:00:00Z"
        assert data["session"]["resets_at"] == "2026-08-18T08:00:00Z"
        assert data["weekly"]["resets_at"] != data["session"]["resets_at"]

    def test_percentages_correct(self) -> None:
        data = parse_html(make_html_real(session_pct=1.5, weekly_pct=42.3))
        assert data["session"]["used_pct"] == 1.5
        assert data["weekly"]["used_pct"] == 42.3

    def test_full_structure(self) -> None:
        data = parse_html(make_html_real(
            plan="pro",
            session_pct=45.0,
            session_time="2026-08-18T08:00:00Z",
            weekly_pct=80.0,
            weekly_time="2026-08-24T00:00:00Z",
        ))
        assert data == {
            "plan": "pro",
            "session": {"used_pct": 45.0, "resets_at": "2026-08-18T08:00:00Z"},
            "weekly": {"used_pct": 80.0, "resets_at": "2026-08-24T00:00:00Z"},
            "web_search_requests": None,
            "web_fetch_requests": None,
            "models": None,
        }

    def test_works_without_aria_labels(self) -> None:
        """Fall back to the plain label when the meters lack aria-labels."""
        data = parse_html(make_html_real(aria_labels=False))
        assert data["session"]["resets_at"] == "2026-08-18T08:00:00Z"
        assert data["weekly"]["resets_at"] == "2026-08-24T00:00:00Z"
        assert data["weekly"]["used_pct"] == 27.9


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

class TestOutputStructure:

    def test_top_level_keys(self, free_html: str) -> None:
        assert set(parse_html(free_html).keys()) == {
            "plan", "session", "weekly", "web_search_requests",
            "web_fetch_requests", "models"
        }

    def test_full_structure(self, pro_html: str) -> None:
        data = parse_html(pro_html)
        assert set(data.keys()) == {
            "plan", "session", "weekly", "web_search_requests",
            "web_fetch_requests", "models"
        }
        assert set(data["session"].keys()) == {"used_pct", "resets_at"}
        assert set(data["weekly"].keys()) == {"used_pct", "resets_at"}

    def test_returns_dict(self, free_html: str) -> None:
        assert isinstance(parse_html(free_html), dict)

    def test_full_values(self, full_usage_html: str) -> None:
        data = parse_html(full_usage_html)
        assert data == {
            "plan": "pro",
            "session": {"used_pct": 45.0, "resets_at": "2026-04-05T10:00:00Z"},
            "weekly": {"used_pct": 80.0, "resets_at": "2026-04-07T00:00:00Z"},
            "web_search_requests": None,
            "web_fetch_requests": None,
            "models": None,
        }

    def test_max_plan_full_usage(self, max_html: str) -> None:
        data = parse_html(max_html)
        assert data["plan"] == "max"
        assert data["session"]["used_pct"] == 99.9
        assert data["weekly"]["used_pct"] == 100.0


# ---------------------------------------------------------------------------
# Auth errors
# ---------------------------------------------------------------------------

class TestAuthErrors:

    @pytest.mark.parametrize("html", [
        "<html>redirecting to /login</html>",
        "<html>please sign in to continue</html>",
        "<html><body>/login?next=/settings</body></html>",
        "<html>Sign In to Ollama</html>",
    ])
    def test_auth_error_on_login_redirect(self, html: str) -> None:
        with pytest.raises(AuthError):
            parse_html(html)

    def test_auth_error_message(self) -> None:
        with pytest.raises(AuthError, match="invalid or expired"):
            parse_html("<html>/login</html>")

    def test_auth_error_is_subclass(self) -> None:
        from ollama_usage.exceptions import OllamaUsageError
        with pytest.raises(OllamaUsageError):
            parse_html("<html>/login</html>")


# ---------------------------------------------------------------------------
# Parse errors
# ---------------------------------------------------------------------------

class TestParseErrors:

    @pytest.mark.parametrize("html", [
        "",
        "   ",
        "<html><body>nothing here</body></html>",
        "<span class='capitalize'>free</span>",
    ])
    def test_parse_error_missing_data(self, html: str) -> None:
        with pytest.raises(ParseError):
            parse_html(html)

    def test_parse_error_missing_weekly_pct(self) -> None:
        html = """
        <span class="capitalize">free</span>
        <span class="text-sm">0% used</span>
        <div class="local-time" data-time="2026-04-04T17:00:00Z"></div>
        """
        with pytest.raises(ParseError, match="percentages"):
            parse_html(html)

    def test_parse_error_missing_reset_times(self) -> None:
        html = """
        <span class="capitalize">free</span>
        <span class="text-sm">0% used</span>
        <span class="text-sm">27.9% used</span>
        """
        with pytest.raises(ParseError, match="timestamps"):
            parse_html(html)

    def test_parse_error_missing_plan(self) -> None:
        html = """
        <span class="text-sm">0% used</span>
        <span class="text-sm">27.9% used</span>
        <div class="local-time" data-time="2026-04-04T17:00:00Z"></div>
        <div class="local-time" data-time="2026-04-06T00:00:00Z"></div>
        """
        with pytest.raises(ParseError, match="plan"):
            parse_html(html)

    def test_parse_error_is_subclass(self) -> None:
        from ollama_usage.exceptions import OllamaUsageError
        with pytest.raises(OllamaUsageError):
            parse_html("")

# ---------------------------------------------------------------------------
# _fetch_html - couverture réseau (lignes 52-70)
# ---------------------------------------------------------------------------

class TestFetchHtml:
    """Tests pour _fetch_html via mock urllib - couvre les chemins réseau."""

    def _make_response(self, body: str, status: int = 200):
        """Crée un faux objet response compatible urllib context manager."""
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.read.return_value = body.encode("utf-8")
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_returns_html_on_success(self) -> None:
        from unittest.mock import patch
        from ollama_usage.scraper import _fetch_html

        fake_resp = self._make_response("<html>ok</html>")
        with patch("urllib.request.urlopen", return_value=fake_resp):
            result = _fetch_html("my-cookie")
        assert result == "<html>ok</html>"

    def test_raises_network_error_on_url_error(self) -> None:
        import urllib.error
        from unittest.mock import patch
        from ollama_usage.scraper import _fetch_html
        from ollama_usage.exceptions import NetworkError

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            with pytest.raises(NetworkError, match="Failed to reach"):
                _fetch_html("my-cookie")

    def test_raises_parse_error_on_invalid_utf8(self) -> None:
        from unittest.mock import patch, MagicMock
        from ollama_usage.scraper import _fetch_html
        from ollama_usage.exceptions import ParseError

        resp = MagicMock()
        resp.read.return_value = b"\xff\xfe invalid utf8"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=resp):
            with pytest.raises(ParseError, match="UTF-8"):
                _fetch_html("my-cookie")

    def test_cookie_not_logged(self, caplog) -> None:
        """Le cookie ne doit jamais apparaître dans les logs, même en DEBUG."""
        import logging
        from unittest.mock import patch
        from ollama_usage.scraper import _fetch_html

        fake_resp = self._make_response("<html>ok</html>")
        with patch("urllib.request.urlopen", return_value=fake_resp):
            with caplog.at_level(logging.DEBUG, logger="ollama_usage.scraper"):
                _fetch_html("super-secret-cookie-value")

        for record in caplog.records:
            assert "super-secret-cookie-value" not in record.getMessage()


# ---------------------------------------------------------------------------
# get_usage - intégration scraper complet
# ---------------------------------------------------------------------------

class TestGetUsage:

    def _make_response(self, body: str):
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.read.return_value = body.encode("utf-8")
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_get_usage_returns_dict(self) -> None:
        from unittest.mock import patch
        from ollama_usage.scraper import get_usage

        html = """
        <span class="capitalize">free</span>
        <span class="text-sm">0.0% used</span>
        <span class="text-sm">33.3% used</span>
        <div class="local-time" data-time="2026-04-04T17:00:00Z"></div>
        <div class="local-time" data-time="2026-04-06T00:00:00Z"></div>
        """
        with patch("urllib.request.urlopen", return_value=self._make_response(html)):
            result = get_usage("my-cookie")

        assert result["plan"] == "free"
        assert result["session"]["used_pct"] == 0.0
        assert result["weekly"]["used_pct"] == 33.3

    def test_get_usage_propagates_network_error(self) -> None:
        import urllib.error
        from unittest.mock import patch
        from ollama_usage.scraper import get_usage
        from ollama_usage.exceptions import NetworkError

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            with pytest.raises(NetworkError):
                get_usage("my-cookie")

    def test_get_usage_propagates_auth_error(self) -> None:
        from unittest.mock import patch
        from ollama_usage.scraper import get_usage
        from ollama_usage.exceptions import AuthError

        html = "<html>redirecting to /login</html>"
        with patch("urllib.request.urlopen", return_value=self._make_response(html)):
            with pytest.raises(AuthError):
                get_usage("expired-cookie")


# ---------------------------------------------------------------------------
# __init__.py - exports publics
# ---------------------------------------------------------------------------

class TestPublicExports:

    def test_all_exceptions_importable_from_package(self) -> None:
        from ollama_usage import (
            OllamaUsageError,
            AuthError,
            ParseError,
            NetworkError,
            BrowserNotFoundError,
            UnsupportedOSError,
        )
        assert issubclass(AuthError, OllamaUsageError)
        assert issubclass(ParseError, OllamaUsageError)
        assert issubclass(NetworkError, OllamaUsageError)
        assert issubclass(BrowserNotFoundError, OllamaUsageError)
        assert issubclass(UnsupportedOSError, OllamaUsageError)

    def test_get_usage_importable_from_package(self) -> None:
        from ollama_usage import get_usage
        assert callable(get_usage)