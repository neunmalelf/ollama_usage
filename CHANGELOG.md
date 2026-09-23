# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Naming: the program is spelled `ollama_usage` everywhere now (was
  `ollama-usage`) — `--version` prints `ollama_usage <version>`, the pip
  distribution name and console script are `ollama_usage` (PyPI treats `_`
  and `-` as equivalent, so existing installs keep resolving), `--help`
  always shows `ollama_usage` as the program name, and the man page (`.TH
  OLLAMA_USAGE`), tldr page (`tldr/ollama_usage.md`, installed as
  `ollama_usage.page.md`) and `_build` product metadata follow. The legacy
  dotted settings files (`~/.ollama-usage-gui.cfg`,
  `~/.ollama-usage-widget.cfg`) keep their names — they are the migration
  source for older releases.

## [3.0.20260923113912] - 2026-09-23

### Added

- `--dataonly`: the usage credit balance is appended as an eighth
  semicolon-separated field (`...;ws;wr;credit_balance`, two decimals,
  `0.00` when the page has no credit section).
- `--credit-alert AMOUNT`: colors the widget credit balance (the `c: $`
  value at the end of the compact line) red when it drops below AMOUNT
  (default: 1.0; a negative value disables the recolor).
- Usage credit balance: the "Usage credit / Current balance" value on
  ollama.com/settings is parsed and exposed as `credit_balance` (float or
  null) in the usage dict/JSON. The compact CLI views now show it before
  the web-search count as `cr: <balance> ` — two decimals, `0.00` when the
  page has no credit section — in `--minidisplay` and
  `--minidisplay-horizontal`.
- `--dataonly`: prints one machine-readable line for scripts and agents —
  `subscription;percent_session;seconds_to_session_reset;percent_weekly;seconds_to_weekly_reset;ws;wr`
  (single fetch, no colors/countdown; e.g.
  `PRO;48.4;11880;49.3;172800;34;0`) so wrappers can track the remaining
  token contingent and the reset times.

### Changed

- The widget compact line shows the usage credit balance after the web fetch
  count as `| c: $ <balance>` (two decimals, `0.00` when the page has no
  credit section, red below `--credit-alert`) instead of `cr: <balance>`
  before the search count — `olu (PRO) s: 42.0 % (02:46) | w: 77.0 %
  (1d 06:46) ws: 2 wr: 0 | c: $ 4.51`. The CLI compact views are unchanged.
- The `--widget` help text spells out the status letter: `A` (autorefresh by
  default), `M` (manual refresh with `--autorefresh-off`).

### Fixed

- The Qt compact widget painted its line against the old fixed 560 px width
  while the window auto-fits its content, so the `A`/`M` status letter was
  anchored beyond the visible window edge and disappeared (most visible with
  `--background-transparent`). The paint box now matches the actual window
  size.
- The compact widget window hugged its content again: it had a fixed 560 px
  width, so with `--background-transparent` a wide dead zone (often >100 px)
  appeared between the values and the status letter. The width now auto-fits
  the line — padding + line + a two-space gap + indicator + padding (Tk and
  Qt, min 220 px; loading/error states keep the roomy fallback width).
- `--widget --background-transparent` no longer dies when PySide6 is present
  but its C extension fails to load (e.g. a compiled binary built against an
  older Qt than the system one after a distribution update - the failure was
  invisible in `--daemon` mode because the child's stderr is /dev/null). The
  widget now probes the real Qt load, falls back to the translucent Tk
  widget, and the CLI pre-flight prints a "failed to load ... rebuild with
  ./_build" notice naming the import error.

## [3.0.20260912071632Z] - 2026-09-12

### Added

- Self-sustained mode: `--save-cookie COOKIE` stores the session cookie in
  `~/.config/ollama_usage/cookie` (mode 0600), so the program runs without
  any installed browser; `--forget-cookie` removes it. Cookie lookup order:
  `--cookie` → `OLLAMA_BROWSER_COOKIE` → stored cookie → browser
  auto-detect. A browser-provided cookie is synced to the stored copy
  automatically, so no manual action is normally required; auth failures
  hint at updating the stored cookie when it expires.

## [2.0.20260911213613Z] - 2026-09-11

### Added

- Voice announcements: `--voice-info-when-session-usage-was-reset [TEXT]` and
  `--voice-info-when-weekly-usage-was-reset [TEXT]` speak a message when the
  session/weekly quota rolls over while the CLI runs (auto-refresh mode).
  New `ollama_usage/voice.py` mirrors the ddpico speech design: Kokoro neural
  TTS, Microsoft Edge-TTS, macOS `say`, Windows PowerShell SAPI, pyttsx3,
  `spd-say`, `espeak-ng`, `espeak`, `festival` — best available wins, speech
  runs in a background thread. No special hardware needed (any speakers or
  headphones); README documents install steps per platform.
- Widget: `--background-transparent` now renders a **per-pixel transparent**
  widget (only text and bars visible over the wallpaper) via a new PySide6
  backend (`ollama_usage/widget_qt.py`) on Linux/macOS — plain Tk cannot do
  per-pixel transparency outside Windows. Install with
  `pip install ollama_usage[widget]`. Without PySide6 the widget falls back
  to the translucent Tk window and prints a warning (also in `--daemon`
  mode, via the parent process, since the child's stderr is /dev/null).
  `_build` bundles PySide6 automatically when it is importable in the build
  Python (`CONFIGURATION_BUNDLE_QT6=no` to skip). The Qt backend shares the
  Tk widget's themes, layouts, state file and interactions (drag, context
  menu, size toggle, A/M indicator, cookie refresh).

### Changed

- Widget: the default opacity is now **0.80 whenever `--background-transparent`
  is given** (0.92 otherwise); an explicit `--opacity` always wins.

- CLI: single-shot ``--minidisplay`` and ``--minidisplay-horizontal``
  (``--autorefresh-off``) no longer clear the terminal before printing;
  the in-place auto-refresh redraw is unchanged.
- Config: all settings now live in ``~/.config/ollama_usage/``
  (``gui.cfg``, ``widget.cfg``). The directory is created on first program
  start and dotted legacy files (``~/.ollama-usage-*.cfg``) are migrated
  there automatically. ``--reset-settings`` removes the new files.

- GUI: the window auto-sizes to its content — the fixed 640x300 default
  clipped the text (longest line 852px; content needs ~1010x334). It is not
  resizable and has no scrollbar (the content always fits); the obsolete
  ``geometry`` setting was removed. The text height follows the content line
  count, clamped to the screen.
- CLI/widget/GUI: a single space is printed between a percentage value and
  the ``%`` sign everywhere (full display, minidisplay, widget compact and
  bars, GUI).

### Fixed
- GUI: unit tests wrote mock values into the real
  ``~/.ollama-usage-gui.cfg``; a corrupted ``geometry`` value then crashed
  startup ("bad geometry specifier") so no window appeared. Tests no longer
  touch the real state file, and with the ``geometry`` setting removed (see
  above) the crash class is gone entirely.
- GUI: ``--theme dark`` (and ``--theme light``/``minimal``) now sets the
  GUI darkmode; previously the flag only affected the widget and the GUI
  always restored its saved setting. Without ``--theme`` the GUI keeps
  restoring its saved darkmode value.
- GUI: on a light background the yellow color (the "days" part of the
  countdown, and 50-80% percentages) is darkened to readable amber
  (``#a05a00``) instead of bright yellow on white.
- Widget (Qt backend): the right-click context menu never opened in the
  Nuitka-compiled binary — shiboken's signal machinery inspects slots with
  CPython `PyFunction_*` APIs, which raise `SystemError` (funcobject.c:432)
  on Nuitka-compiled methods once extra packages are bundled
  (`--include-package`). All signal slots (menu actions, fetch timer,
  `QTimer.singleShot` reschedule, Ctrl+Q shortcut) are now wrapped in a
  callable-instance `_Callback`, which shiboken treats as a generic
  callable. This also fixes the widget freezing after the first fetch (the
  timer reschedule silently failed in the binary).
- Widget (Qt backend): the A/M status indicator (and the right-aligned
  percentages in the full view) were rendered at the left edge — the
  right-aligned text rect was anchored at x instead of ending at x + w; the
  indicator is back at the right edge with the reserved padding before it.
- Widget: `--background-transparent` no longer falls back silently to the
  opaque theme background on Linux/macOS (Tk's `-transparentcolor` is a
  Windows-only attribute); the Tk fallback is now a translucent window with
  the 1px theme border kept and a visible warning.
- Widget: fixed `--opacity` silently not applying on X11 — Tk ignores
  `-alpha` unless the X11-only window `-type` attribute is set first;
  the widget now sets it (wrapped in `try/except TclError` for
  Windows/macOS) so window opacity works as documented on Linux.
- CLI: `python -m ollama_usage --daemon` (source runs) now works; the
  package gained an `ollama_usage/__main__.py` entry point.
- Help text, README, man and tldr pages document the transparency behavior.

- Initial public release under the MIT license.
- CLI with `--json`, `--browser`, `--cookie`, `--watch`, `--alert`,
  `--quiet`, `--notify`, `--minidisplay` and `--debug` flags.
- Python library API via `ollama_usage.get_usage`.
- Auto browser cookie detection and manual cookie support.
- Web search and web fetch usage statistics and per-model request counts.
- Widget shows the canonical subscription name ("Pro") and keeps the
  autorefresh "Stopped." message visible after exiting.
- Colored ANSI output.
- Single-line `--minidisplay` output with optional autorefresh countdown.
- Desktop notifications via the `[notify]` extra.
