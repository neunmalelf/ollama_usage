# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
