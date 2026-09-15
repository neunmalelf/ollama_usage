# ollama_usage — Technical Documentation

Timestamped incident/fix records. Format: `YYYY-MM-DDThh:mm:ssZ` (UTC, trailing `Z`
per project convention `YYYYMMDDhhmmssZ`).

---

## 2026-09-15T10:32:43Z — Daemon crash after system Qt upgrade (PySide6 private-ABI mismatch)

**Fixed — daemon runs again.** Root cause was NOT the daemon logic; the daemon
child crashed instantly and its stderr goes to `/dev/null`, so it looked like
"not starting".

### Root cause chain (evidence)

1. Binary in `~/sbin` was built Sep 13 22:24 against PySide6 **6.11.1**/Qt 6.11.1.
2. dnf transaction #85 (Sep 14 17:58) upgraded the system:
   `python3-pyside6 6.11.1-4 → 6.11.2-1`, `qt6-qtbase → 6.11.2-2`.
3. The Nuitka onefile bundle ships the PySide6 extension modules but **not Qt's
   shared libraries** (Fedora RPMs put them in `/lib64`, not under
   `PySide6/Qt/lib`; `LD_DEBUG` shows the loader misses every in-bundle
   candidate and falls back to system Qt).
4. Qt's *private* ABI changed between 6.11.1 → 6.11.2: bundled `QtCore.so`
   demands `_ZN14QObjectPrivateC2E16QtPrivate_6_11_1` (`Qt_6.11_PRIVATE_API`)
   which 6.11.2 no longer exports → `ImportError` → process died. Source
   version (`./_run`) kept working because it uses the upgraded system PySide6.

### Fixes

- `ollama_usage/widget.py`: new `pyside6_import_error()` — probes the *real*
  C-extension load (cached), not just `find_spec`. `launch_widget()` now falls
  back to the translucent Tk widget when the Qt import fails instead of
  crashing; warning is logged.
- `ollama_usage/cli.py`: `_warn_transparent_fallback()` distinguishes
  "PySide6 not found" vs "found but failed to load … rebuild with `./_build`"
  — printed from the parent before daemonizing, so it's visible in the
  terminal.
- Rebuilt + redeployed `~/sbin/ollama_usage` via `./_build` (now matches
  Qt 6.11.2); CHANGELOG `[Unreleased]` → `Fixed`.

### Verification

- 393/393 tests pass, incl. 6 new regression tests (`TestPySide6Probe`,
  broken-Qt fallback, broken/missing warning wording).
- Exact failing command
  `ollama_usage --widget --autorefresh --background-transparent --browser firefox --daemon`:
  daemon survives (pids 401685/401693), window mapped at 2365,9 (560×30),
  process maps show `libQt6Widgets.so.6.11.2` → **Qt transparent backend
  active**, no import error. `killall ollama_usage` stops it.

### Known tradeoff

⚠️ The binary still links system Qt, so the **next** Qt upgrade will trip this
again — but now the widget degrades to the Tk fallback with an explicit
"rebuild with `./_build`" notice instead of dying silently. Truly
self-contained Qt vendoring would need a pip-venv PySide6 build (RPM layout
can't bundle Qt libs).