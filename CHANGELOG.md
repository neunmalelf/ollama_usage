# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
  `pip install ollama-usage[widget]`. Without PySide6 the widget falls back
  to the translucent Tk window and prints a warning (also in `--daemon`
  mode, via the parent process, since the child's stderr is /dev/null).
  `_build` bundles PySide6 automatically when it is importable in the build
  Python (`CONFIGURATION_BUNDLE_QT6=no` to skip). The Qt backend shares the
  Tk widget's themes, layouts, state file and interactions (drag, context
  menu, size toggle, A/M indicator, cookie refresh).

### Changed

- Widget: the default opacity is now **0.80 whenever `--background-transparent`
  is given** (0.92 otherwise); an explicit `--opacity` always wins.

### Fixed
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
