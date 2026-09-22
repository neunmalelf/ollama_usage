---
name: _update_documention
description: After each change, checks README.md, README_tecdocu.md (if it exists), function_usage (help function), docs, history.md, man file, and tldr file, updates their version numbers and content, and commits with '<version> - documentation updated'.
version: 1.0.20260906133143Z
load: always
---

# _update_documention

Ensures all project documentation remains synchronized, comprehensive, and up-to-date after any code, configuration, or structural change.

## Overview

Whenever a change is made to the codebase (such as adding, changing, or refactoring functions, CLI arguments, configuration options, data structures, or tests), all documentation assets must be inspected and updated accordingly before concluding the work.

Documentation assets covered:
1. `README.md` — Main project overview, installation, CLI usage, examples, and version stamp.
2. `README_tecdocu.md` — Technical documentation, architecture diagrams, call graphs, and module dependencies (if it exists).
3. `function_usage` (help function) — Built-in CLI help function / `argparse` descriptions and help registry.
4. `docs/` (MkDocs documentation) — Markdown sources under `docs/` and `mkdocs.yml` rendered via `./_docs`.
5. `history.md` — Project version and change changelog.
6. `man/` — Linux/Unix man page (e.g., `man/_downloads_cleaner.1`).
7. `tldr/` — Simplified command-line usage examples page (e.g., `tldr/_downloads_cleaner.md`).

---

## Workflow

After any change to the project:

### 1. Determine Current Version

The version micro segment is a **UTC** timestamp with a trailing `Z`
(format `MAJOR.MINOR.YYYYMMDDhhmmssZ`), independent of the local timezone:
```bash
VERSION=$(timestamp)
```

### 2. Inspect & Update Documentation Assets

1. **`README.md`**:
   - Check if new CLI arguments, flags, or configuration variables were added.
   - Update command examples, output samples, and usage instructions.
   - Update version string to match `$VERSION`.

2. **`README_tecdocu.md` (if it exists)**:
   - Check if functions, classes, or architecture workflows changed.
   - Update Mermaid diagrams, data structures, and edge lists if necessary.

3. **`function_usage` (CLI Help Function)**:
   - Ensure the `usage()` / `--help` display in code reflects all current CLI flags (`-h`, `--help`, `-d`, `--dryrun`, `--keep-logfile`, etc.).
   - Verify that option descriptions, default values, and example invocations are accurate.

4. **`docs/` (MkDocs Documentation)**:
   - Check documentation files under `docs/` (`index.md`, `cli.md`, `api.md`, `rules.md`, `fuzzing.md`, etc.).
   - Update `mkdocs.yml` navigation if new pages or modules were created.
   - Verify build with:
     ```bash
     ./_docs
     ```

5. **`history.md`**:
   - Append or update the entry for the current change with `$VERSION` and a concise summary.

6. **`man/` File**:
   - Inspect the man page under `man/` (e.g., `man/_downloads_cleaner.1`).
   - Update the date, version header, and any modified command options or descriptions.

7. **`tldr/` File**:
   - Inspect the tldr page under `tldr/` (e.g., `tldr/_downloads_cleaner.md`).
   - Ensure quick reference commands and descriptions accurately reflect typical usage patterns.

### 3. Verify Line Endings

Ensure all edited documentation files retain Unix (LF, `\n`) line endings:
```bash
git ls-files --eol | grep 'w/crlf'
```

### 4. Git Commit

Stage the updated documentation and commit using the required message format:
```bash
git add README.md README_tecdocu.md docs/ mkdocs.yml history.md man/ tldr/
git commit -m "<version> - documentation updated"
```
Example:
```bash
git commit -m "20260906133143Z - documentation updated"
```

---

## Rules

1. **Never leave documentation stale**: If a flag or function changes in code, the documentation must match before the task is marked complete.
2. **Synchronized version numbers**: Update the version number across all modified documentation files simultaneously.
3. **Commit message format**: The documentation commit must strictly follow `<version> - documentation updated`.
