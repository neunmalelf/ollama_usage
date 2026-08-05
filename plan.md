# Plan: Add Web Search usage statistics to `ollama-usage`

## Background / Research

- The tool scrapes `https://ollama.com/settings` (HTML) using the `__Secure-session` cookie (`scraper.py`).
- It currently parses two quota sections — **Session usage** and **Weekly usage** — via a section-label-aware regex approach (`_extract_usage` in `scraper.py:100`): it finds the section marker text (e.g. `"weekly usage"`), then the next `"XX% used"` and next `data-time="..."` after that position.
- The settings page also exposes **web search** usage. Investigation of the live HTML shows web search is **not** a `% used + reset time` quota. It is rendered as a request-count segment inside the usage meters:
  `<button ... data-usage-segment data-model="web search" data-requests="2" />`
  (and listed under "Models used this week"). There is no separate percentage or reset time for web search.

## Changes

### 1. `scraper.py`
- Add `_WEB_SEARCH_SEGMENT_RE` to match `data-model="web search" ... data-requests="(\d+)"`.
- Add `_extract_web_search_requests(html)` returning the **sum** of all web search request counts, or `None` when no segment is present.
- Extend the `UsageData` dataclass and `to_dict()` with a `web_search_requests` field (`int | None`).

New JSON shape:
```json
{
  "plan": "pro",
  "session":   {"used_pct": 2.6, "resets_at": "..."},
  "weekly":    {"used_pct": 1.9, "resets_at": "..."},
  "web_search_requests": 2   // or null when no web search usage present
}
```

### 2. `cli.py`
- `display()`: add a `WebSearch: N requests` line, skipped when `web_search_requests` is `None`.
- `_check_alert()` and `--alert` unchanged (alerting remains percentage-based on session/weekly).

### 3. `widget.py`
- Add a "Web search: N requests" line to the compact and full views when `web_search_requests` is not `None`. No gauge/percentage — it is a request count.

### 4. `notify.py`
- Unchanged. Notifications remain percentage-based on session/weekly (web search is a count, not a quota).

### 5. Tests
- `tests/test_scraper.py`: add `web_search_requests` param to `make_html`/`make_html_reversed` (renders the data-usage-segment button); assert parsing, `None` when absent, summation of multiple segments, and that existing tests still pass unchanged.
- `tests/test_cli.py`: update `make_data()` with `web_search_requests`; add display cases (present + absent). No alert changes.
- `tests/test_notify.py`: unchanged (reverted).

### 6. Docs
- Update `README.md`: example text output, JSON example, Python usage, roadmap.
- Update `CHANGELOG.md` with the new feature entry.

## Verification
- Run `pytest` (testpaths `tests`) — full suite must pass.
- Manual: `ollama-usage --json` and `ollama-usage` against a real cookie to confirm web search parsing.

## Notes
- No new dependencies.
- Web search is optional/backward-compatible: accounts without web search usage return `null` and skip the line/widget row.
- The real page format differs from an earlier assumption (a `% used + reset time` section). Corrected to parse the `data-requests` segment.
