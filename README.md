# ollama_usage

## Settings files

The GUI and widget keep separate settings files in `~/.config/ollama_usage/`.
The directory is created automatically on first start; dotted settings files
from earlier releases (`~/.ollama-usage-gui.cfg`, `~/.ollama-usage-widget.cfg`
directly in the home directory) are moved there automatically on first start
after the upgrade:

- GUI: `~/.config/ollama_usage/gui.cfg`
  - `darkmode`: whether dark mode is enabled (`true` or `false`)
  - `autorefresh`: refresh interval in seconds
- Widget: `~/.config/ollama_usage/widget.cfg`
  - `x`: horizontal screen position
  - `y`: vertical screen position
  - `size`: `compact` or `full`

- Cookie (self-sustained mode): `~/.config/ollama_usage/cookie` — the stored
  `__Secure-session` cookie (written by `--save-cookie`, mode 0600; removed
  by `--forget-cookie`)

These paths are derived from the current user's home directory; no username
or profile path is hardcoded. Both files use INI-style CFG syntax. Existing
settings are preserved independently between GUI and widget.

Example GUI CFG:

```ini
[gui]
darkmode = false
autorefresh = 120
```

Example widget CFG:

```ini
[widget]
x = 100
y = 50
size = compact
```

Reset both settings files with:

```bash
ollama_usage --reset-settings
```

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

## Testing

### Setup
Create a virtual environment and install the package with development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

The `dev` extra installs the full test/lint/build toolchain: `pytest`, `pytest-cov`,
`ruff`, `bandit`, `mypy`, and `nuitka`.

### Run the test suite

```bash
# All tests
pytest

# Same command CI runs (with coverage report)
pytest tests/ --cov=ollama_usage --cov-report=term-missing
```

### Lint & type-check

```bash
# Ruff linter (same as CI)
ruff check ollama_usage/

# Bandit security scan (same skip list as CI)
bandit -r ollama_usage/ --skip B404,B603,B607,B310,B110

# Static type checking
mypy ollama_usage/
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

# Store the cookie once — after this the program runs without any browser
# installed. While a browser is used, the stored copy stays fresh
# automatically; re-run --save-cookie only if NO browser is available and
# the cookie expires (the program tells you when that happens).
ollama-usage --save-cookie YOUR_SESSION_COOKIE
ollama-usage

# Remove the stored cookie again
ollama-usage --forget-cookie

# Autorefresh is ON by default (120s, shows next-refresh timestamp footer)
ollama-usage
# Custom refresh interval
ollama-usage --autorefresh 60
ollama-usage --autorefresh 1200
# Disable autorefresh (single fetch)
ollama-usage --autorefresh-off

# Single-line compact output
ollama-usage --minidisplay

# Compact output with autorefresh (appends a cyan countdown)
ollama-usage --minidisplay
ollama-usage --minidisplay --autorefresh 60

# Alert mode — exit code 1 if usage exceeds 80%
ollama-usage --alert 80

# Quiet mode — no output, only exit code (useful in scripts/cron)
ollama-usage --quiet --alert 80

# One-shot — notify if usage exceeds 80% (default threshold)
ollama-usage --notify

# One-shot — notify if usage exceeds 75%
ollama-usage --notify --notify-threshold 75

# Notify when threshold is crossed, no spam between ticks (autorefresh on by default)
ollama-usage --notify

# Custom threshold and refresh interval
ollama-usage --notify --autorefresh 60 --notify-threshold 75

# Debug mode
ollama-usage --debug
ollama-usage --debug --browser firefox

# GUI window (OK + Refresh buttons)
ollama-usage --gui

# Desktop widget (always-on-top, auto-refreshing)
ollama-usage --widget
ollama-usage --widget --theme light
ollama-usage --widget --size compact
ollama-usage --widget --opacity 0.8
ollama-usage --widget --position bottom-right
ollama-usage --widget --theme minimal --size compact --position top-right

# Version
ollama-usage --version

# Help
ollama-usage --help
```

### Example output
```
Plan     :  PRO
Session  :   2.6 % used - reset at 2026-08-05T20:00:00Z (in  2h 42m)
Weekly   :   1.9 % used - reset at 2026-08-10T00:00:00Z (in  4d 6h 42m)
WebSearch:      2 requests
WebFetch :      0 requests
Model calls this week:
                2 glm-5.2
                2 web search
              382 deepseek-v4-flash:0731
               60 deepseek-v4-flash
```

### Minidisplay output
```
olu (PRO) s:   2.6 % (02:46) | w:   1.9 % (1d 06:46) ws: 2 wr: 0
```

`--minidisplay` prints one compact line: the plan name in parentheses after `olu`, then session percentage and remaining time, weekly percentage and remaining time, and the web search (`ws`) and web fetch (`wr`) request counts. Remaining time is `[dd] hh:mm` (days omitted when zero). By default a grey `(mm:ss)` countdown is appended and refreshed in place at the end of the line (disable with `--autorefresh-off`).

`--minidisplay-horizontal` shows the same information, but each item on its own line:

```
olu (PRO)
s:   2.6 % (02:46)
w:   1.9 % (1d 06:46)
ws:  2
wr:  0
```

It refreshes in place by default, redrawing the block with the countdown on the `wr:` line (two spaces after the count).

The `WebSearch:` line reports the number of web search requests during the current session/week (shown as a request count in the settings meters). The `WebFetch :` line reports the number of web fetch requests the same way. The `Models used this week:` section lists per-model request counts. All only appear when there is data — otherwise they are omitted. Model labels are shown in white; the request numbers are shown in cyan.

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
  "web_fetch_requests": 0,
  "models": [
    {"name": "glm-5.2", "requests": 2},
    {"name": "web search", "requests": 2},
    {"name": "deepseek-v4-flash:0731", "requests": 382},
    {"name": "deepseek-v4-flash", "requests": 60}
  ]
}
```

`web_search_requests` and `web_fetch_requests` are the total numbers of web search / web fetch requests on the page. `models` is a list of `{name, requests}` objects (per-model counts from the "Models used this week" list). All are `null` when absent.

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

Each level notifies **once per threshold crossing** — no spam during autorefresh.  
If usage drops back below the threshold, the notification will fire again if it rises once more.
```bash
# One-shot — notify if usage exceeds 80%
ollama-usage --notify

# Custom threshold
ollama-usage --notify --notify-threshold 75

# Continuous monitoring with notifications (autorefresh on by default)
ollama-usage --notify 
ollama-usage --notify --autorefresh 60 --notify-threshold 75
```

---

## Voice announcements (usage reset)

`--voice-info-when-session-usage-was-reset` and `--voice-info-when-weekly-usage-was-reset`
speak a message aloud when the session or weekly quota rolls over to a new period
while the CLI is running (autorefresh mode). The first fetch only establishes the
baseline, so a reset that happened before the program started is not announced.

```bash
# Default texts
ollama-usage --autorefresh 60 --voice-info-when-session-usage-was-reset \
             --voice-info-when-weekly-usage-was-reset

# Custom texts
ollama-usage --autorefresh 60 \
             --voice-info-when-session-usage-was-reset "session quota refreshed" \
             --voice-info-when-weekly-usage-was-reset "weekly quota refreshed"
```

### How it works

The announcement is spoken by the best speech backend found on the system
(checked in this order): **Kokoro** neural TTS (if `kokoro-onnx` is installed and
the model files are present), **Microsoft Edge-TTS** (if `edge-tts` is installed),
macOS `say`, Windows PowerShell SAPI, Python `pyttsx3`, then the Linux CLI tools
`spd-say`, `espeak-ng`, `espeak`, `festival`. Speech runs in a background thread,
so the refresh loop is never blocked.

### Installing the components

- **Linux (Fedora/RHEL):** `sudo dnf install espeak-ng` (or `speech-dispatcher` for
  `spd-say`). Debian/Ubuntu: `sudo apt install espeak-ng`.
- **macOS:** nothing to install — the built-in `say` command is used.
- **Windows:** nothing to install — the built-in PowerShell SAPI voices are used.
- **Optional high-quality neural voices:**
  - `pip install edge-tts` — Microsoft neural voices (needs internet at speak time).
  - `pip install kokoro-onnx` + download the model:
    `python -c "from ollama_usage.voice import kokoro_ensure_models; kokoro_ensure_models()"`
    (fully local, CPU-only, ~300 MB in `~/.cache/kokoro`).

### Hardware requirements

None beyond a normal desktop/laptop: any machine with **speakers or headphones**
and a working audio output works. The synthesis is pure software — no GPU, no
special sound card, no microphone. Edge-TTS additionally needs an internet
connection; Kokoro and the system engines work fully offline.

### Building

The voice feature is part of the normal build — no extra build-time components.
The speech engines are runtime system tools, not bundled into the binary; build
with the usual `./_build` and install the engine of your choice on the target
machine.

---

## GUI window

`--gui` opens a simple, cross-platform window (Windows, Linux, macOS) that shows the same quota information as the CLI. It uses **tkinter** (Python stdlib), so no extra dependency is required.

- The window title shows the app name and version: `ollama-usage (<version>)`.
- An **OK** button closes the app.
- A **Refresh** button re-fetches the data and redraws the window.
- A **darkmode** checkbox toggles dark mode (Alt+d).
- An **autorefresh (s)** field sets the refresh interval in seconds (default 120).
  The value is saved and restored on the next launch.

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

## Desktop widget

`--widget` opens a small, **always-on-top** desktop widget that shows your quota as live gauges and auto-refreshes. It uses **tkinter** (Python stdlib), so no extra dependency is required.

> `--background-transparent` renders a **per-pixel transparent** widget (only the
> text and bars float over the wallpaper). This is impossible with Tk outside
> Windows, so on Linux/macOS it needs **PySide6** — install it with
> `pip install ollama-usage[widget]` (or `pip install PySide6`). Without PySide6
> the widget falls back to a translucent Tk window and prints a warning.

- **Frameless** and draggable — click and drag anywhere to move it.
- **Right-click** opens a context menu: refresh now, toggle size, or close.
- **Auto-refreshes** every 30 seconds.
- Remembers its last position between runs (unless `--position` is given).
- A status indicator in the top-right corner shows the autorefresh state: **A** by default, **M** when run with `--autorefresh-off`. It is **green** when the data is fresh and **red** when an error occurred (e.g. auth failure).

### Options

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--theme` | `dark`, `light`, `minimal` | *(widget: `dark`; GUI: saved darkmode)* | Color scheme for the widget and the GUI (`--theme dark` forces GUI dark mode, `light`/`minimal` force light) |
| `--size` | `full`, `compact` | `full` | `full` shows bars + countdown; `compact` shows text only |
| `--opacity` | `0.1` – `1.0` | `0.92` | Window opacity (`0.80` with `--background-transparent`) |
| `--position` | `top-left`, `top-right`, `bottom-left`, `bottom-right` | *(last saved)* | Screen corner to place the widget |
| `--background-transparent` | – | off | Fully transparent background — the text/bars float over the wallpaper. Native on Windows; needs **PySide6** on Linux/macOS (otherwise falls back to a translucent window) |

```bash
# Default widget (dark, full, top-right)
ollama-usage --widget

# Light theme, compact, bottom-right
ollama-usage --widget --theme light --size compact --position bottom-right

# Semi-transparent minimal widget
ollama-usage --widget --theme minimal --opacity 0.8

# Fully transparent background (PySide6 on Linux/macOS; native on Windows)
ollama-usage --widget --background-transparent
```

### Python usage
```python
from ollama_usage.widget import launch_widget
from ollama_usage.cookie import get_cookie_auto

launch_widget(
    cookie=get_cookie_auto,
    interval=60,
    theme="light",
    size="compact",
    opacity=0.9,
    position="bottom-right",
)
```

> On minimal Linux installs, tkinter may need to be installed separately:
> `sudo apt install python3-tk`

### Daemon mode (run in background)

Add `--daemon` (alias `--damon` for typo-compatibility) to run widget/GUI or autorefresh in background — terminal is not blocked and can be closed:

```bash
# Widget in background
ollama_usage --widget --daemon
ollama_usage --widget --autorefresh --browser firefox --daemon
# Alias --damon also works
ollama_usage --widget --damon

# GUI in background
ollama_usage --gui --daemon

# Any long-running CLI also supports it
ollama_usage --minidisplay --daemon
```

The daemon detaches via `fork`/`setsid` and redirects stdio to `/dev/null` so closing the terminal does not kill it (keeps `DISPLAY`/`XAUTHORITY` for widget).

Stop it with `killall`:

```bash
killall ollama_usage          # stops the running instances; the extracted
                              # onefile payload (process name ollama_usage.bi)
                              # shuts down a moment later
# or more precise, catches every process whose command line matches:
pkill -f ollama_usage
```

> On Windows `os.fork` is unavailable — `--daemon` is a no-op there.

---

## Keyboard shortcuts

- **Ctrl+C** — stop the CLI. Works in every output mode (plain, minidisplay,
  autorefresh and alert loops); prints `Stopped.` and exits.
- **Ctrl+Q** — close the GUI window and the desktop widget.

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
print(usage["web_fetch_requests"])          # None or an int like 3
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
- [x] Autorefresh mode (on by default, `--autorefresh-off` to disable)
- [x] Colored output
- [x] `--alert` and `--quiet` for scripting
- [x] Desktop notifications with `--notify`
- [x] Environment variable support (`OLLAMA_BROWSER_COOKIE`)
- [x] Web search usage statistics
- [x] GUI window with `--gui`
- [x] Desktop widget with `--widget`
- [ ] Safari support
- [ ] Migrate to official `/api/me` when available ([#12532](https://github.com/ollama/ollama/issues/12532))

---

## Building a standalone executable

You can compile `ollama-usage` into a single standalone binary (`.exe` on Windows) with **Nuitka** (native-compiled, faster-starting, harder-to-decompile than PyInstaller).

```bash
# From the project root
./_build
```

The script:
- Compiles to a single-file `dist/ollama-usage.exe` (Windows) or `dist/ollama-usage` (Linux/macOS) in onefile mode.
- Embeds `icon.ico` as the executable icon **and** bundles it so the GUI window and widget show it at runtime.
- Includes the tkinter GUI toolkit (`--enable-plugin=tk-inter`).
- Copies the finished binary to `~/sbin` (Linux/macOS) or `/b/winsbin` (Windows) — no sudo needed.

Options:

| Option | Effect |
|--------|--------|
| `--no-install` | Build only — skip copying the binary to the bin directory |
| `--release` | Build, tag with the version, and publish a GitHub release via `gh` |

```bash
./_build --no-install     # just produce dist/
./_build --release        # build + tag + GitHub release
```

Requirements:
- Python with `nuitka` installed: `pip install "ollama-usage[dev]"` (or `pip install nuitka`)
- On Python 3.13+, Nuitka needs the **Zig** compiler (installed via scoop or downloaded automatically on first build — the script handles this with `--zig`).

> The build takes a few minutes on first run (it compiles all modules to C).

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
