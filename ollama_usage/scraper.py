"""Fetch and parse Ollama Cloud usage from ollama.com/settings."""

from __future__ import annotations

import logging
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

from ollama_usage.exceptions import AuthError, NetworkError, OllamaUsageError, ParseError

logger = logging.getLogger(__name__)

_SETTINGS_URL = "https://ollama.com/settings"
_TIMEOUT = 10  # seconds
_SSL_CONTEXT = ssl.create_default_context()

_PLAN_RE = re.compile(r'capitalize[^>]*>\s*(\w+)\s*</')
_PERCENT_RE = re.compile(r'([\d.]+)%\s*used')
_TIME_RE = re.compile(r'data-time="([^"]+)"')

# Section markers (case-insensitive).
_SESSION_MARKER = "session usage"
_WEEKLY_MARKER = "weekly usage"
# Human-readable subscription names, keyed by the lowercase plan returned by
# the page. Predefined so displays always show the canonical capitalized name
# (e.g. "Pro") regardless of the casing in the HTML.
PLAN_NAMES: dict[str, str] = {
    "free": "Free",
    "pro": "Pro",
    "max": "Max",
}


def plan_display_name(plan: str) -> str:
    """Return the canonical display name for a plan key (e.g. ``"pro"`` → ``"PRO"``)."""
    return PLAN_NAMES.get(plan.lower(), plan.capitalize() or "—").upper()

# Web search is not a % quota — it is shown as a request-count segment inside
# the usage meters, e.g. <button ... data-model="web search" data-requests="2" />.
_WEB_SEARCH_SEGMENT_RE = re.compile(
    r'data-usage-segment[^>]*data-model="web search"[^>]*data-requests="(\d+)"',
    re.IGNORECASE,
)

# Web fetch is a newer request-count stat, rendered the same way as web search.
_WEB_FETCH_SEGMENT_RE = re.compile(
    r'data-usage-segment[^>]*data-model="web fetch"[^>]*data-requests="(\d+)"',
    re.IGNORECASE,
)

# Per-model request counts in the "Models used this week" list.
# Each row: <span title="NAME">NAME</span> <span ...> N requests </span>
_MODELS_LIST_MARKER = "models used this week"
_MODEL_ITEM_RE = re.compile(
    r'title="([^"]+)"[^>]*>\s*[^<]*</span>\s*'
    r'<span[^>]*>\s*(\d+)\s*requests',
    re.IGNORECASE,
)


@dataclass
class PeriodUsage:
    used_pct: float
    resets_at: str


@dataclass
class UsageData:
    plan: str
    session: PeriodUsage
    weekly: PeriodUsage
    web_search_requests: int | None = None
    web_fetch_requests: int | None = None
    models: list[dict[str, int]] | None = None

    def to_dict(self) -> dict:
        def _period(p: PeriodUsage | None) -> dict | None:
            if p is None:
                return None
            return {"used_pct": p.used_pct, "resets_at": p.resets_at}

        return {
            "plan": self.plan,
            "session": _period(self.session),
            "weekly": _period(self.weekly),
            "web_search_requests": self.web_search_requests,
            "web_fetch_requests": self.web_fetch_requests,
            "models": self.models,
        }


# --- HTTP ---

def _fetch_html(cookie: str) -> str:
    """Fetch the settings page HTML using the provided session cookie."""
    logger.debug("Fetching %s (cookie: ***)", _SETTINGS_URL)
    req = urllib.request.Request(
        _SETTINGS_URL,
        headers={
            "Cookie": f"__Secure-session={cookie}",
            "User-Agent": "Mozilla/5.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL_CONTEXT) as response:
            raw = response.read()
            try:
                html = raw.decode("utf-8")
            except UnicodeDecodeError as e:
                raise ParseError(f"Response is not valid UTF-8: {e}") from e
            logger.debug("Response received (%d chars)", len(html))
            return html
    except urllib.error.HTTPError as e:
        # 401/403 = cookie invalide ou expiré → AuthError, pas NetworkError
        if e.code in (401, 403):
            raise AuthError(
                f"Access denied (HTTP {e.code}) — cookie is invalid or expired."
            ) from e
        raise NetworkError(f"HTTP error {e.code} reaching {_SETTINGS_URL}") from e
    except urllib.error.URLError as e:
        raise NetworkError(f"Failed to reach {_SETTINGS_URL}: {e}") from e
    except OllamaUsageError:
        raise
    except Exception as e:
        raise NetworkError(f"Unexpected error fetching {_SETTINGS_URL}: {e}") from e


def _check_auth(html: str) -> None:
    """Raise AuthError if the page redirected to login."""
    logger.debug("Checking auth...")
    if "/login" in html or "sign in" in html.lower():
        logger.debug("Auth check failed — redirected to login")
        raise AuthError("Cookie is invalid or expired — please refresh it.")
    logger.debug("Auth check passed")

# --- Parsing ---

def _extract_plan(html: str) -> str:
    match = _PLAN_RE.search(html)
    if not match:
        raise ParseError("Could not extract plan from HTML.")
    return match.group(1).lower()


def _extract_usage(html: str) -> tuple[float, float, str, str]:
    """Extract session and weekly usage from labeled sections in HTML.

    This function is section-aware and does not depend on order.
    It finds each usage section by its label and extracts the corresponding
    percentage and reset time from within that section.

    The usage meters on the page carry an aria-label (e.g.
    ``aria-label="Session usage 45.0% used"``) that sits right next to the
    meter's own ``data-time`` attribute. The visible label span can appear
    earlier in the DOM (e.g. in a summary), so the LAST occurrence of each
    marker is used — that lands on the meter itself, and the ``data-time``
    found right after it belongs to that same section.
    """
    lower = html.lower()

    def locate(label: str) -> int:
        """Return the position of a usage section's meter.

        Prefer the meter's aria-label; fall back to the plain label span.
        """
        pos = lower.rfind(f'aria-label="{label}')
        if pos == -1:
            pos = lower.rfind(label)
        return pos

    # Find positions of each section marker
    session_pos = locate(_SESSION_MARKER)
    weekly_pos = locate(_WEEKLY_MARKER)

    if session_pos == -1 and weekly_pos == -1:
        # Fallback to position-based extraction if sections not found
        matches = _PERCENT_RE.findall(html)
        times = _TIME_RE.findall(html)
        if len(matches) < 2:
            raise ParseError(f"Expected 2 usage percentages, found {len(matches)}.")
        if len(times) < 2:
            raise ParseError(f"Expected 2 reset timestamps, found {len(times)}.")
        return float(matches[0]), float(matches[1]), times[0], times[1]

    # Extract percentage and time after each section marker
    def extract_after(pos: int, label: str) -> tuple[float, str]:
        # Find the next "% used" after this position using pos parameter (no slicing)
        pct_match = _PERCENT_RE.search(html, pos)
        if not pct_match:
            raise ParseError(f"Could not find {label} usage percentage.")
        # Find the next data-time after this position using pos parameter
        time_match = _TIME_RE.search(html, pos)
        if not time_match:
            raise ParseError(f"Could not find {label} reset time.")
        return float(pct_match.group(1)), time_match.group(1)

    if session_pos == -1:
        raise ParseError("Could not find 'Session usage' section in HTML.")
    if weekly_pos == -1:
        raise ParseError("Could not find 'Weekly usage' section in HTML.")

    session_pct, session_time = extract_after(session_pos, "session")
    weekly_pct, weekly_time = extract_after(weekly_pos, "weekly")

    return session_pct, weekly_pct, session_time, weekly_time


def _extract_web_search_requests(html: str) -> int | None:
    """Extract the number of web search requests reported on the page.

    Web search is rendered as a segment inside the usage meters with a
    ``data-requests`` attribute. Returns the total (summed over all meters) or
    None when no web search segment is present.
    """
    counts = _WEB_SEARCH_SEGMENT_RE.findall(html)
    if not counts:
        return None
    return sum(int(c) for c in counts)


def _extract_web_fetch_requests(html: str) -> int | None:
    """Extract the number of web fetch requests reported on the page.

    Web fetch is rendered as a segment inside the usage meters with a
    ``data-requests`` attribute (same layout as web search). Returns the total
    (summed over all meters) or None when no web fetch segment is present.
    """
    counts = _WEB_FETCH_SEGMENT_RE.findall(html)
    if not counts:
        return None
    return sum(int(c) for c in counts)


def _extract_models(html: str) -> list[dict[str, int]] | None:
    """Extract the per-model request counts from the "Models used this week" list.

    Returns a list of {"name": ..., "requests": ...} dicts, or None when the
    list is not present.
    """
    pos = html.lower().find(_MODELS_LIST_MARKER)
    if pos == -1:
        return None
    # Only look within the models list section (up to the next script tag).
    end = html.find("<script", pos)
    section = html[pos:end] if end != -1 else html[pos:]
    matches = _MODEL_ITEM_RE.findall(section)
    if not matches:
        return None
    return [
        {"name": name, "requests": int(count)}
        for name, count in matches
    ]


def parse_html(html: str) -> dict:
    """Parse the settings page HTML and return a usage dict."""
    _check_auth(html)
    plan = _extract_plan(html)
    session_pct, weekly_pct, session_time, weekly_time = _extract_usage(html)
    web_search_requests = _extract_web_search_requests(html)
    web_fetch_requests = _extract_web_fetch_requests(html)
    models = _extract_models(html)
    logger.debug("Parsing HTML...")
    logger.debug(
        "Parsed: plan=%s session=%.1f%% weekly=%.1f%% "
        "web_search_requests=%s web_fetch_requests=%s models=%s",
        plan, session_pct, weekly_pct, web_search_requests, web_fetch_requests,
        "None" if models is None else len(models),
    )
    return UsageData(
        plan=plan,
        session=PeriodUsage(used_pct=session_pct, resets_at=session_time),
        weekly=PeriodUsage(used_pct=weekly_pct, resets_at=weekly_time),
        web_search_requests=web_search_requests,
        web_fetch_requests=web_fetch_requests,
        models=models,
    ).to_dict()


# --- Public API ---

def get_usage(cookie: str) -> dict:
    """Fetch and return Ollama Cloud usage for the given session cookie."""
    html = _fetch_html(cookie)
    return parse_html(html)
