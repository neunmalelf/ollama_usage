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


@dataclass
class PeriodUsage:
    used_pct: float
    resets_at: str


@dataclass
class UsageData:
    plan: str
    session: PeriodUsage
    weekly: PeriodUsage

    def to_dict(self) -> dict:
        return {
            "plan": self.plan,
            "session": {
                "used_pct": self.session.used_pct,
                "resets_at": self.session.resets_at,
            },
            "weekly": {
                "used_pct": self.weekly.used_pct,
                "resets_at": self.weekly.resets_at,
            },
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
    match = re.search(r'capitalize[^>]*>\s*(\w+)\s*</', html)
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
    session_pos = html.lower().find("session usage")
    weekly_pos = html.lower().find("weekly usage")
    
    if session_pos == -1 and weekly_pos == -1:
        # Fallback to position-based extraction if sections not found
        matches = re.findall(r'([\d.]+)%\s*used', html)
        times = re.findall(r'data-time="([^"]+)"', html)
        if len(matches) < 2:
            raise ParseError(f"Expected 2 usage percentages, found {len(matches)}.")
        if len(times) < 2:
            raise ParseError(f"Expected 2 reset timestamps, found {len(times)}.")
        return float(matches[0]), float(matches[1]), times[0], times[1]
    
    # Extract percentage and time after each section marker
    def extract_after(pos: int, label: str) -> tuple[float, str]:
        # Find the next "% used" after this position
        pct_match = re.search(r'([\d.]+)%\s*used', html[pos:])
        if not pct_match:
            raise ParseError(f"Could not find {label} usage percentage.")
        # Find the next data-time after this position
        time_match = re.search(r'data-time="([^"]+)"', html[pos:])
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


def parse_html(html: str) -> dict:
    """Parse the settings page HTML and return a usage dict."""
    _check_auth(html)
    plan = _extract_plan(html)
    session_pct, weekly_pct, session_time, weekly_time = _extract_usage(html)
    logger.debug("Parsing HTML...")
    logger.debug("Parsed: plan=%s session=%.1f%% weekly=%.1f%%", plan, session_pct, weekly_pct)
    return UsageData(
        plan=plan,
        session=PeriodUsage(used_pct=session_pct, resets_at=session_time),
        weekly=PeriodUsage(used_pct=weekly_pct, resets_at=weekly_time),
    ).to_dict()


# --- Public API ---

def get_usage(cookie: str) -> dict:
    """Fetch and return Ollama Cloud usage for the given session cookie."""
    html = _fetch_html(cookie)
    return parse_html(html)