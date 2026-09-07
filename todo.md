# todo.md — Widget background problem ("3 wrong background areas" in problem_20260906_030857.png)

Command under test:

> **Status 2026-09-06 (later): Phase 2 implemented as well.**
>`--background-transparent` now launches a per-pixel transparent PySide6
> widget (`ollama_usage/widget_qt.py`) when PySide6 is importable; the Tk
> translucent pill remains the fallback (with the "needs PySide6" warning).
> The default opacity rule was simplified per user decision: **0.80 whenever
> `--background-transparent` is given**, 0.92 otherwise. `_build` bundles
> PySide6 automatically (`CONFIGURATION_BUNDLE_QT6=no` to skip).
>
> **Status 2026-09-06: Phase 1 implemented** (widget.py `_setup_window`:
>`-type`+fallback alpha, cli.py warning + `--opacity` default `None`,
>`__main__.py` for source daemon runs; tests in test_widget.py /
>test_cli.py; help/README/man/tldr/CHANGELOG updated; binary rebuilt via
>`./_build`). During implementation a second X11 bug was found and fixed:
>Tk silently ignores `-alpha` on X11 unless the X11-only `-type` attribute
>is set first — without this, `--opacity` never had any effect on Linux.

    ollama_usage --widget --autorefresh --background-transparent --browser firefox --daemon

Environment: Fedora 44, KDE Plasma **Wayland** (widget runs under XWayland), Tk 9.0 (system
python3) and bundled Tk in the Nuitka binary — both lack X11 `-transparentcolor`.

## Diagnosis (verified live on this machine, 2026-09-06)

The screenshot shows **one widget plus an unrelated window below it** — not one program
with three areas.

| Screenshot area | What it really is |
|---|---|
| Top dark strip with the `s:/w:/ws/wr` text and the `A` indicator | The widget. Exactly **560x30 px** (`_W_COMPACT`). It is dark because `--background-transparent` silently falls back to the theme background on Linux (see "Root cause" below). |
| White strip below it | **Not the widget.** The window directly underneath the widget position (Konsole title/tab bar, flat `#EFF0F1`). It was present in screen captures taken while *no* widget was running, and extends far beyond the widget's x/y bounds. |
| "Transparent area with light-gray rounded outline" below that | **Not the widget.** Top of that same underlying window (translucent body + KDE rounded corners/outline showing the wallpaper through). |

Evidence gathered:

- X window tree of one widget instance: exactly 3 stacked/nested 560x30 X windows
  (Tk wrapper → toplevel → canvas), all at the same coordinates → one visual band.
  `WM_NORMAL_HINTS` pins min/max size 560x30.
- Controlled run of the full `OllamaWidget` class at an empty screen position: exactly
  one 30px band appears; after destroy the screen is pixel-identical to the "before"
  capture (no leftover windows, no stacked bands).
- Launching the daemon command twice: both instances restore the same saved position and
  overlap — no vertical stacking ever occurs.
- The white band exists in captures with **no** widget process running at all
  (color `239,240,241` matches the user's screenshot band 2 exactly).
- KWin-side window list (`kdotool`) shows the widget as a single 386x21 (scaled) window.

## Root cause of the real bug (dark instead of transparent background)

`ollama_usage/widget.py`:

- `_TRANSPARENT_COLOR` sentinel (line ~104) + `OllamaWidget._bg_color()` (lines ~390-394)
  and `OllamaWidget._setup_window()` (lines ~396-417).

`wm_attributes("-transparentcolor", ...)` is a **Windows-only** Tk attribute. On X11 the
call raises `TclError: bad attribute "-transparentcolor": must be -alpha, -fullscreen,
-topmost, -type, or -zoomed` (verified live; also confirmed in Tk sources — X11 supports
only `-alpha/-topmost/-zoomed/-fullscreen/-type`). The `except tk.TclError` branch then
falls back to `self._theme["bg"]` (dark `#1e1e2e`) — which is exactly what the user sees.

Two aggravating factors:

1. The fallback only logs via `logger.warning` (widget.py ~410-413) — invisible without
   `--debug`.
2. In `--daemon` mode stderr/stdout of the child are `subprocess.DEVNULL`
   (cli.py ~626-633), so even with `--debug` the child's warning never reaches the user.

Plain Tk on X11 **cannot** do per-pixel (background-only) transparency at all — only
whole-window `-alpha` (needs a compositor; KWin qualifies). Background-transparent
widgets on Linux require an ARGB-capable toolkit (Qt/GTK).

## What NOT to do

- Do not chase the white/transparent bands in widget code — they are the window below.
- Do not attempt libX11/ctypes ARGB-visual hacks around Tk (fragile, unsupported).
- Do not "fake" transparency by sampling the wallpaper color (user has an animated
  wallpaper → stale background would be visible).

## Fix plan

### Phase 1 — honest, good-looking X11 fallback (small, do first)

1. `widget.py::_setup_window()` — when `-transparentcolor` is unsupported:
   - Keep `bg = theme["bg"]` (unchanged), but make the fallback *look* like a
     translucent pill: apply a stronger whole-window alpha, e.g. effective opacity
     `0.80`, instead of the default `0.92`, unless the user passed `--opacity`
     explicitly.
   - To distinguish "explicitly passed" from default: change cli.py `--opacity` default
     to `None` (resolve `0.92` / `0.80` at launch time), or compare against the default.
   - Keep the 1px canvas border in fallback mode (`highlightthickness=1`,
     `highlightbackground=theme["border"]`) — it visually separates the widget from
     windows below (directly addresses the confusion in this screenshot).
2. Make the limitation visible:
   - cli.py: before `--daemon` spawns the detached child (still attached to the
     terminal), if `args.widget and args.background_transparent` and not Windows:
     print e.g. `Warning: --background-transparent is only fully supported on Windows;
     on Linux the widget uses a translucent background instead.` to stderr.
   - Update `--background-transparent` help text (cli.py ~580-583) and README to state
     Windows-only true transparency / Linux translucent fallback.
3. Tests: unit-test `_bg_color()` + the fallback path with a stub root whose
   `wm_attributes` raises `TclError` (pattern already used in tests/test_widget.py);
   assert fallback color, alpha value, and visible-border flag.
4. Manual verification: run the daemon command, confirm the warning prints, the widget
   is a translucent pill, and (with Konsole moved away) that no extra bands exist.

### Phase 2 — real transparency on Linux via Qt (optional, the "correct" fix)

Per-pixel transparency with floating text is impossible in Tk on X11. If the user wants
the true look (only text/bars visible over the wallpaper), implement transparent mode
with PySide6 (works on Wayland natively and X11):

1. New module `ollama_usage/widget_qt.py`:
   - Frameless, always-on-top, `Qt.WA_TranslucentBackground` window.
   - Reuse the existing pure helpers from `widget.py` (`_mini_segments`,
     `_countdown_segments`, `_pct_color`, THEMES, `_load_state`/`_save_state`) — they
     already return `(text, color)` segments, so rendering maps 1:1 to
     `QPainter.drawText` / rounded-rect bars.
   - Same interactions: drag to move, right-click menu, size toggle, A/M indicator.
2. `widget.py::launch_widget()` — on Linux with `background_transparent=True`, try
   `import PySide6`; on `ImportError` fall back to the Phase-1 Tk pill with the visible
   warning.
3. Packaging: `pyproject.toml` → `[project.optional-dependencies] widget = ["PySide6"]`;
   document `pip install ollama-usage[widget]`. Note: Nuitka onefile build will grow
   considerably if PySide6 is bundled — alternatively keep Tk fallback in the binary and
   offer the Qt widget for pip installs.
4. Verification: screenshot diff under KDE Wayland — widget shows wallpaper through the
   background with fully opaque text; drag/menu/size-toggle work; state file round-trips.

## Acceptance

- `--background-transparent` on Linux: user-visible notice + consistent translucent
  (Phase 1) or truly transparent (Phase 2) widget.
- The widget window is exactly 560x30 (compact) / 240x172 (full) — no additional areas
  ever belong to it; with any window below moved away, only the widget strip remains.