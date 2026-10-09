"""Fetch and parse Ollama Cloud usage from ollama.com/settings."""

from __future__ import annotations

import logging
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

from ollama_usage.exceptions import (
    AuthError,
    LayoutChangedError,
    NetworkError,
    OllamaUsageError,
    ParseError,
)

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

# The segments' anchors and the payload they must carry: a segment that is on
# the page without its count means the markup changed, and reporting 0 for it
# would silently claim "no requests in this period".
_WEB_SEARCH_ANCHOR = 'data-model="web search"'
_WEB_FETCH_ANCHOR = 'data-model="web fetch"'
_REQUESTS_ATTRIBUTE = 'data-requests="<count>"'

# Usage credit balance: the amount is the text of the element whose stable id
# is "extra-usage-balance" in the "Usage credits" section of the settings
# page, e.g. <span id="extra-usage-balance" class="...">$4.42</span>.
_CREDIT_BALANCE_ID_RE = re.compile(
    r'id="extra-usage-balance"[^>]*>\s*(.*?)\s*</span>',
    re.IGNORECASE | re.DOTALL,
)

# Older layout (page as of 2026-09): the amount was rendered right before the
# "Current balance" label, e.g. "<span>$4.51</span>Current balance"; the amount
# and the label may be separated by closing tags and whitespace.
_CREDIT_BALANCE_LABEL_RE = re.compile(
    r"([$€£]?\s*[\d.,]+)\s*(?:<[^>]*>\s*)*Current\s+balance",
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

# Anchors of the settings page this parser relies on. They are checked before
# a value is read, and they describe the page in LayoutChangedError details
# ("anchors found: ...; missing: ...").
_PAGE_ANCHORS: dict[str, re.Pattern[str]] = {
    "plan badge": re.compile(r'class="[^"]*\bcapitalize\b', re.IGNORECASE),
    "session meter": re.compile(r"session\s+usage", re.IGNORECASE),
    "weekly meter": re.compile(r"weekly\s+usage", re.IGNORECASE),
    "usage segments": re.compile(r"data-usage-segment", re.IGNORECASE),
    "credits heading": re.compile(r"<h[1-6][^>]*>\s*usage\s+credits?\b", re.IGNORECASE),
    "credits section": re.compile(r'id="extra-usage"[\s>]', re.IGNORECASE),
    "credits balance": re.compile(r'id="extra-usage-balance"', re.IGNORECASE),
    "legacy balance label": re.compile(r"current\s+balance", re.IGNORECASE),
    "models list": re.compile(r'id="weekly-usage-models"', re.IGNORECASE),
}

# Any trace of the usage-credits block: heading, container, balance element or
# the label of the older layout. When one of these is on the page the block is
# there, so its balance must be readable.
_CREDIT_BLOCK_ANCHORS = (
    "credits heading",
    "credits section",
    "credits balance",
    "legacy balance label",
)

# The usage credit balance, spelled out for the "expected ..." error messages.
_CREDIT_EXPECTATION = (
    'the "Usage credits" balance - the text of '
    '<span id="extra-usage-balance">$4.42</span>, or on the pre-2026-10 layout '
    'an amount right before a "Current balance" label -'
)


def _anchor_inventory(html: str) -> str:
    """Return a one-line inventory of the page anchors found and missing."""
    found = [name for name, pattern in _PAGE_ANCHORS.items() if pattern.search(html)]
    missing = [name for name in _PAGE_ANCHORS if name not in found]
    return (
        f"anchors found: {', '.join(found) or 'none'}; "
        f"missing: {', '.join(missing) or 'none'}"
    )


def _layout_changed(message: str, html: str) -> LayoutChangedError:
    """Return a LayoutChangedError for *message* carrying the anchor inventory."""
    return LayoutChangedError(message, _anchor_inventory(html))


def _credits_block_present(html: str) -> bool:
    """Return True when the page carries any usage-credits block trace.

    No trace at all means the account simply has no usage-credits block (e.g.
    a free plan), which is not an error. A trace means the block is there, so
    its balance has to be readable.
    """
    return any(
        _PAGE_ANCHORS[name].search(html) is not None for name in _CREDIT_BLOCK_ANCHORS
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
    credit_balance: float | None = None
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
            "credit_balance": self.credit_balance,
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
        raise _layout_changed(
            "the subscription plan could not be read: expected the plan badge "
            '(<span class="capitalize">pro</span>) on ollama.com/settings',
            html,
        )
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
        # Neither meter carries its label. Guessing the order from the document
        # order of the percentages would silently swap session and weekly
        # numbers (and their reset times), so refuse instead of guessing.
        raise _layout_changed(
            "neither the 'Session usage' nor the 'Weekly usage' meter is on "
            "ollama.com/settings, so the two percentages cannot be told apart",
            html,
        )

    # Extract percentage and time after each section marker
    def extract_after(pos: int, label: str) -> tuple[float, str]:
        # Find the next "% used" after this position using pos parameter (no slicing)
        pct_match = _PERCENT_RE.search(html, pos)
        if not pct_match:
            raise _layout_changed(
                f"expected the {label} usage percentage ('<value>% used' right "
                f"after the '{label.capitalize()} usage' label), which is not there",
                html,
            )
        # Find the next data-time after this position using pos parameter
        time_match = _TIME_RE.search(html, pos)
        if not time_match:
            raise _layout_changed(
                f"expected the {label} reset time (a data-time attribute right "
                f"after the '{label.capitalize()} usage' meter), which is not there",
                html,
            )
        return float(pct_match.group(1)), time_match.group(1)

    if session_pos == -1:
        raise _layout_changed(
            "expected the 'Session usage' section (its label and meter) on "
            "ollama.com/settings, which is not there",
            html,
        )
    if weekly_pos == -1:
        raise _layout_changed(
            "expected the 'Weekly usage' section (its label and meter) on "
            "ollama.com/settings, which is not there",
            html,
        )

    session_pct, session_time = extract_after(session_pos, "session")
    weekly_pct, weekly_time = extract_after(weekly_pos, "weekly")

    return session_pct, weekly_pct, session_time, weekly_time


def _require_segment_payload(html: str, anchor: str, name: str) -> None:
    """Raise LayoutChangedError when a request segment lost its count.

    The counters may legitimately be absent - no requests in the period means
    no segment. A segment that is on the page yet carries no ``data-requests``
    attribute, however, means the markup changed, and reporting 0 for it would
    be a silent lie.
    """
    if anchor.lower() in html.lower():
        raise _layout_changed(
            f"the {name} request segment is on the page, but no "
            f"{_REQUESTS_ATTRIBUTE} attribute could be read from it",
            html,
        )


def _extract_web_search_requests(html: str) -> int | None:
    """Extract the number of web search requests reported on the page.

    Web search is rendered as a segment inside the usage meters with a
    ``data-requests`` attribute. Returns the total (summed over all meters), or
    None when the account made no such requests in the period.
    """
    counts = _WEB_SEARCH_SEGMENT_RE.findall(html)
    if not counts:
        _require_segment_payload(html, _WEB_SEARCH_ANCHOR, "web search")
        return None
    return sum(int(c) for c in counts)


def _extract_web_fetch_requests(html: str) -> int | None:
    """Extract the number of web fetch requests reported on the page.

    Web fetch is rendered as a segment inside the usage meters with a
    ``data-requests`` attribute (same layout as web search). Returns the total
    (summed over all meters), or None when the account made no such requests in
    the period.
    """
    counts = _WEB_FETCH_SEGMENT_RE.findall(html)
    if not counts:
        _require_segment_payload(html, _WEB_FETCH_ANCHOR, "web fetch")
        return None
    return sum(int(c) for c in counts)


def _extract_credit_balance(html: str, plan: str) -> float | None:
    """Extract the usage credit / current balance shown on the page.

    The balance is the text of the ``extra-usage-balance`` element of the
    "Usage credits" section; pages using the older layout render the amount
    directly before a "Current balance" label instead.

    Returns None only for a free plan whose page carries no trace of a usage
    credits block at all. Anything else raises LayoutChangedError: a redesign
    of the site must not be reported as a zero balance.
    """
    match = _CREDIT_BALANCE_ID_RE.search(html)
    if match is None:
        match = _CREDIT_BALANCE_LABEL_RE.search(html)
    if match is None:
        if _credits_block_present(html):
            raise _layout_changed(
                f"{_CREDIT_EXPECTATION} could not be found on ollama.com/settings",
                html,
            )
        if plan != "free":
            raise _layout_changed(
                "the page carries no trace of a \"Usage credits\" block, which "
                f"a {plan.upper()} plan normally has - either "
                "ollama.com/settings changed its layout or this account really "
                "has no usage credit",
                html,
            )
        return None
    raw = re.sub(r"<[^>]*>", "", match.group(1))  # drop nested markup
    raw = re.sub(r"[^\d.,]", "", raw)  # drop currency symbol/space
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")  # 1,234.56 — comma is a thousands separator
    elif "," in raw:
        raw = raw.replace(",", ".")  # 4,51 — comma is a decimal separator
    try:
        return float(raw)
    except ValueError:
        shown = " ".join(match.group(1).split()) or "nothing"
        raise _layout_changed(
            f"{_CREDIT_EXPECTATION} could not be read: the element contains "
            f"{shown!r} instead of an amount",
            html,
        ) from None


def _extract_models(html: str) -> list[dict[str, int]] | None:
    """Extract the per-model request counts from the "Models used this week" list.

    Returns a list of {"name": ..., "requests": ...} dicts, or None when the
    list is not present or empty (a fresh period without requests). When the
    list shows request counts but none of its rows can be read, a
    LayoutChangedError is raised.
    """
    pos = html.lower().find(_MODELS_LIST_MARKER)
    if pos == -1:
        anchor = _PAGE_ANCHORS["models list"].search(html)
        if anchor is None:
            return None
        pos = anchor.start()
    # Only look within the models list section (up to the next script tag).
    end = html.find("<script", pos)
    section = html[pos:end] if end != -1 else html[pos:]
    matches = _MODEL_ITEM_RE.findall(section)
    if not matches:
        if re.search(r"\d+\s+requests", section, re.IGNORECASE):
            raise _layout_changed(
                "the 'Models used this week' list carries request counts, but "
                "none of its rows could be read (expected "
                '<span title="name">name</span> ... <span>N requests</span>)',
                html,
            )
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
    credit_balance = _extract_credit_balance(html, plan)
    models = _extract_models(html)
    logger.debug("Parsing HTML...")
    logger.debug(
        "Parsed: plan=%s session=%.1f%% weekly=%.1f%% "
        "web_search_requests=%s web_fetch_requests=%s credit_balance=%s models=%s",
        plan, session_pct, weekly_pct, web_search_requests, web_fetch_requests,
        credit_balance, "None" if models is None else len(models),
    )
    return UsageData(
        plan=plan,
        session=PeriodUsage(used_pct=session_pct, resets_at=session_time),
        weekly=PeriodUsage(used_pct=weekly_pct, resets_at=weekly_time),
        web_search_requests=web_search_requests,
        web_fetch_requests=web_fetch_requests,
        credit_balance=credit_balance,
        models=models,
    ).to_dict()


# --- Public API ---

def get_usage(cookie: str) -> dict:
    """Fetch and return Ollama Cloud usage for the given session cookie."""
    html = _fetch_html(cookie)
    return parse_html(html)
