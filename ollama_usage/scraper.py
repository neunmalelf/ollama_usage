"""Fetch and parse Ollama Cloud usage from ollama.com/settings."""

from __future__ import annotations

import logging
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

from ollama_usage.exceptions import AuthError, NetworkError, ParseError

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

# Web search is not a % quota — it is shown as a request-count segment inside
# the usage meters, e.g. <button ... data-model="web search" data-requests="2" />.
_WEB_SEARCH_SEGMENT_RE = re.compile(
    r'data-usage-segment[^>]*data-model="web search"[^>]*data-requests="(\d+)"',
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
    """
    # Find positions of each section marker
    session_pos = html.lower().find(_SESSION_MARKER)
    weekly_pos = html.lower().find(_WEEKLY_MARKER)

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


def parse_html(html: str) -> dict:
    """Parse the settings page HTML and return a usage dict."""
    _check_auth(html)
    plan = _extract_plan(html)
    session_pct, weekly_pct, session_time, weekly_time = _extract_usage(html)
    web_search_requests = _extract_web_search_requests(html)
    logger.debug("Parsing HTML...")
    logger.debug(
        "Parsed: plan=%s session=%.1f%% weekly=%.1f%% web_search_requests=%s",
        plan, session_pct, weekly_pct, web_search_requests,
    )
    return UsageData(
        plan=plan,
        session=PeriodUsage(used_pct=session_pct, resets_at=session_time),
        weekly=PeriodUsage(used_pct=weekly_pct, resets_at=weekly_time),
        web_search_requests=web_search_requests,
    ).to_dict()


# --- Public API ---

def get_usage(cookie: str) -> dict:
    """Fetch and return Ollama Cloud usage for the given session cookie."""
    html = _fetch_html(cookie)
    return parse_html(html)