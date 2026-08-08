# ollama_usage

> Programmatic access to your [Ollama Cloud](https://ollama.com) usage quota — until an official API exists.

![CI](https://github.com/neunmalelf/ollama_usage/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.9+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Ollama does not yet expose a `/api/me` endpoint for quota data ([issue #12532](https://github.com/ollama/ollama/issues/12532)).  
This library fills that gap by reading your session cookie and scraping `ollama.com/settings`.

> ⚠️ This is a workaround. Once Ollama ships an official API, this library will migrate to it.

---

## Installation
```bash
pip install git+https://github.com/neunmalelf/ollama_usage
```

### With desktop notifications support
```bash
pip install "ollama-usage[notify] @ git+https://github.com/neunmalelf/ollama_usage"
```
---

## CLI Usage
```bash
# Auto-detect browser and display usage
ollama-usage

# Output as JSON
ollama-usage --json

# Force a specific browser
ollama-usage --browser firefox
ollama-usage --browser chrome

# Pass cookie manually
ollama-usage --cookie YOUR_SESSION_COOKIE

# Pass cookie via environment variable
export OLLAMA_BROWSER_COOKIE=YOUR_SESSION_COOKIE
ollama-usage

# One-line usage
OLLAMA_BROWSER_COOKIE=YOUR_SESSION_COOKIE ollama-usage --json

# Watch mode (refresh every 30s)
ollama-usage --watch
ollama-usage --watch --json
ollama-usage --watch --interval 60

# Alert mode — exit code 1 if usage exceeds 80%
ollama-usage --alert 80

# Quiet mode — no output, only exit code (useful in scripts/cron)
ollama-usage --quiet --alert 80

# One-shot — notify if usage exceeds 80% (default threshold)
ollama-usage --notify

# One-shot — notify if usage exceeds 75%
ollama-usage --notify --notify-threshold 75

# Watch mode — notify when threshold is crossed, no spam between ticks
ollama-usage --notify --watch

# Watch mode — custom threshold and refresh interval
ollama-usage --notify --watch --notify-threshold 75 --interval 60

# Debug mode
ollama-usage --debug
ollama-usage --debug --browser firefox

# GUI window (OK + Refresh buttons)
ollama-usage --gui

# Version
ollama-usage --version

# Help
ollama-usage --help
```

### Example output
```
Plan     :  pro
Session  :   2.6% used - reset at 2026-08-05T20:00:00Z (in  2h 42m)
Weekly   :   1.9% used - reset at 2026-08-10T00:00:00Z (in  4d 6h 42m)
WebSearch:      2 requests
Model calls this week:
                2 glm-5.2
                2 web search
              382 deepseek-v4-flash:0731
               60 deepseek-v4-flash
```

The `WebSearch:` line reports the number of web search requests during the current session/week (shown as a request count in the settings meters). The `Models used this week:` section lists per-model request counts. Both only appear when there is data — otherwise they are omitted. Model labels are shown in white; the request numbers are shown in cyan.

Terminal colors (ANSI, self-contained — no external dependency):
- Plan name — **orange**
- Session and weekly percentages — **green** (<50%), **yellow** (50–80%), **red** (>80%)
- WebSearch count and model request numbers — **cyan**
- "Model calls this week:" header — **grey**
- Reset countdown — the **days** number in **yellow**, the **hours** number in **cyan**, the **minutes** number in **magenta**, and the `d` / `h` / `m` unit labels in **white** (for both Session and Weekly)

```json
{
  "plan": "pro",
  "session": {
    "used_pct": 2.6,
    "resets_at": "2026-08-05T20:00:00Z"
  },
  "weekly": {
    "used_pct": 1.9,
    "resets_at": "2026-08-10T00:00:00Z"
  },
  "web_search_requests": 2,
  "models": [
    {"name": "glm-5.2", "requests": 2},
    {"name": "web search", "requests": 2},
    {"name": "deepseek-v4-flash:0731", "requests": 382},
    {"name": "deepseek-v4-flash", "requests": 60}
  ]
}
```

`web_search_requests` is the total number of web search requests on the page. `models` is a list of `{name, requests}` objects (per-model counts from the "Models used this week" list). Both are `null` when absent.

---

## Alert & scripting

`--alert PCT` exits with code 1 if session, weekly **or** web search usage exceeds `PCT%`.  
Combine with `--quiet` to suppress all output and use only the exit code.

```bash
# Cron: send a notification if weekly usage exceeds 90%
ollama-usage --quiet --alert 90 || notify-send "Ollama quota warning"

# Bash script
if ! ollama-usage --quiet --alert 75; then
  echo "Quota running low!"
fi
```

---

## Desktop notifications

`--notify` sends a native desktop notification when session, weekly **or** web search usage crosses a threshold.  
Requires the `notify` extra: `pip install "ollama-usage[notify] @ git+https://github.com/neunmalelf/ollama_usage"`

Two levels are fired automatically:
- ⚠️ **Warning** — at the configured threshold (default: 80%)
- 🔴 **Critical** — 15% above the threshold (capped at 100%)

Each level notifies **once per threshold crossing** — no spam during `--watch`.  
If usage drops back below the threshold, the notification will fire again if it rises once more.
```bash
# One-shot — notify if usage exceeds 80%
ollama-usage --notify

# Custom threshold
ollama-usage --notify --notify-threshold 75

# Continuous monitoring with notifications
ollama-usage --notify --watch
ollama-usage --notify --watch --notify-threshold 75 --interval 60
```

---

## GUI window

`--gui` opens a simple, cross-platform window (Windows, Linux, macOS) that shows the same quota information as the CLI. It uses **tkinter** (Python stdlib), so no extra dependency is required.

- The window title shows the app name and version: `ollama-usage (<version>)`.
- An **OK** button closes the app.
- A **Refresh** button re-fetches the data and redraws the window.

```bash
# Open the GUI window
ollama-usage --gui

# With a manual cookie
ollama-usage --gui --cookie YOUR_SESSION_COOKIE
```

> On minimal Linux installs, tkinter may need to be installed separately:
> `sudo apt install python3-tk`

### Python usage
```python
from ollama_usage.gui import launch_gui
from ollama_usage.cookie import get_cookie_auto

launch_gui(cookie=get_cookie_auto)
```

---

## Python Usage
```python
from ollama_usage import get_usage
from ollama_usage.cookie import get_cookie_auto

cookie = get_cookie_auto()
usage = get_usage(cookie)

print(usage["plan"])                        # "free"
print(usage["session"]["used_pct"])         # 0.0
print(usage["weekly"]["resets_at"])         # "2026-04-06T00:00:00Z"
print(usage["web_search_requests"])         # None or an int like 2
print(usage["models"])                      # None or [{"name": ..., "requests": ...}, ...]
```

### Error handling
```python
from ollama_usage import get_usage
from ollama_usage.exceptions import AuthError, NetworkError, ParseError

try:
    usage = get_usage(cookie)
except AuthError:
    print("Cookie expired — please refresh it.")
except NetworkError:
    print("Could not reach ollama.com.")
except ParseError:
    print("Unexpected page structure — open an issue.")
```

---

## Finding your cookie manually

If auto-detection fails, grab your cookie manually:

**Chrome / Edge / Brave**
1. Go to `https://ollama.com/settings`
2. Open DevTools → Application → Cookies → `ollama.com`
3. Copy the value of `__Secure-session`

**Firefox**
1. Go to `https://ollama.com/settings`
2. Open DevTools → Storage → Cookies → `https://ollama.com`
3. Copy the value of `__Secure-session`

Then pass it with `--cookie` or directly in Python.

---

## Supported browsers

| Browser | Windows | Linux | macOS |
|---------|---------|-------|-------|
| Chrome  | ✅ | ✅ | ✅ |
| Firefox | ✅ | ✅ | ✅ |
| Edge    | ✅ | ✅ | ✅ |
| Brave   | ✅ | ✅ | ✅ |
| Opera   | ✅ | ✅ | ✅ |
| Safari  | ❌ | ❌ | 🚧 |

---

## Security note

Depending on your operating system and browser, you may see a security prompt asking for permission to access your browser cookies or local browser data.

This is expected — the library reads your local browser cookie database to authenticate.

Allow access to continue.

---

## Roadmap

- [x] CLI with `--json`, `--browser`, `--cookie`
- [x] Python library API
- [x] Auto browser detection
- [x] `--watch` mode
- [x] Colored output
- [x] `--alert` and `--quiet` for scripting
- [x] Desktop notifications with `--notify`
- [x] Environment variable support (`OLLAMA_BROWSER_COOKIE`)
- [x] Web search usage statistics
- [x] GUI window with `--gui`
- [ ] Safari support
- [ ] Migrate to official `/api/me` when available ([#12532](https://github.com/ollama/ollama/issues/12532))

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT — see [LICENSE](LICENSE).

---

## Disclaimer

This project is not affiliated with Ollama.  
It relies on scraping and may break if Ollama changes their HTML structure.  
If it breaks, please [open an issue](https://github.com/neunmalelf/ollama_usage/issues).
