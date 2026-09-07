# ollama-usage

> Check your Ollama Cloud quota usage (session and weekly percentages, web search / web fetch request counts, per-model statistics).
> More information: <https://github.com/neunmalelf/ollama_usage>.

- Display current usage (auto-detects the browser cookie):

`ollama-usage`

- Output as JSON:

`ollama-usage --json`

- Force a specific browser:

`ollama-usage --browser {{firefox|chrome|edge|brave|opera}}`

- Pass the session cookie manually:

`ollama-usage --cookie {{__Secure-session_cookie}}`

- Print one compact line with a 60 second refresh:

`ollama-usage --minidisplay --autorefresh {{60}}`

- Disable auto-refresh (single fetch):

`ollama-usage --autorefresh-off`

- Exit with code 1 if session or weekly usage exceeds 80%, without printing anything:

`ollama-usage --quiet --alert {{80}}`

- Send a desktop notification when usage crosses 75%:

`ollama-usage --notify --notify-threshold {{75}}`

- Open the desktop widget (light theme, compact, bottom-right):

`ollama-usage --widget --theme {{light}} --size {{compact}} --position {{bottom-right}}`

- Open the GUI window:

`ollama-usage --gui`
- Open the widget with a transparent background (fully transparent on Windows, translucent elsewhere):

`ollama-usage --widget --background-transparent`
- Speak when the session or weekly usage resets (auto-refresh mode):

`ollama-usage --autorefresh {{60}} --voice-info-when-session-usage-was-reset --voice-info-when-weekly-usage-was-reset`
