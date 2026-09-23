# ollama_usage

> Check your Ollama Cloud quota usage (session and weekly percentages, web search / web fetch request counts, per-model statistics).
> More information: <https://github.com/neunmalelf/ollama_usage>.

- Display current usage (auto-detects the browser cookie):

`ollama_usage`

- Output as JSON:

`ollama_usage --json`

- Force a specific browser:

`ollama_usage --browser {{firefox|chrome|edge|brave|opera}}`

- Pass the session cookie manually:

`ollama_usage --cookie {{__Secure-session_cookie}}`


- Persist the session cookie so no browser is needed (self-sustained):

`ollama_usage --save-cookie {{cookie}}`

- Remove the stored session cookie:

`ollama_usage --forget-cookie`

- Print one compact line with a 60 second refresh:

`ollama_usage --minidisplay --autorefresh {{60}}`

- Print one machine-readable line for scripts and agents (subscription, percentages, seconds until reset, ws, wr, credit balance):

`ollama_usage --dataonly`

- Disable auto-refresh (single fetch):

`ollama_usage --autorefresh-off`

- Exit with code 1 if session or weekly usage exceeds 80%, without printing anything:

`ollama_usage --quiet --alert {{80}}`

- Send a desktop notification when usage crosses 75%:

`ollama_usage --notify --notify-threshold {{75}}`

- Open the desktop widget (light theme, compact, bottom-right):

`ollama_usage --widget --theme {{light}} --size {{compact}} --position {{bottom-right}}`

- Open the GUI window:

`ollama_usage --gui`
- Open the widget with a transparent background (fully transparent on Windows, translucent elsewhere):

`ollama_usage --widget --background-transparent`
- Speak when the session or weekly usage resets (auto-refresh mode):

`ollama_usage --autorefresh {{60}} --voice-info-when-session-usage-was-reset --voice-info-when-weekly-usage-was-reset`
