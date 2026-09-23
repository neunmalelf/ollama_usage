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
3. `function_usage` (help function) — Built-in CLI help function / `argparse` descriptions and help registry. (if the program(s) has(have) and -h or --help functionality)
4. `docs/` (MkDocs documentation) — Markdown sources under `docs/` and `mkdocs.yml` rendered via `./_docs`. (if the ./docs folder exist)
5. `ChangeLog.md` — Project version and change changelog.
6. `NEWS` -- newest changes, keep the last 2 changes
7. `man/` — Linux/Unix man page (e.g., `man/_downloads_cleaner.1`).
8. `tldr/` — Simplified command-line usage examples page (e.g., `tldr/_downloads_cleaner.md`).

---

## Workflow

After any change to the project:

### 1. Determine Current Version
```bash
VERSION=$(timestamp)
```

### 2. Inspect & Update Documentation Assets

1 **`README.md`**:
   - Check if new CLI arguments, flags, or configuration variables were added.
   - Update command examples, output samples, and usage instructions.
   - Update version string to match `$VERSION`.

2. **`README_tecdocu.md` (if it exists)**:
   - Check if functions, classes, or architecture workflows changed.
   - Update Mermaid diagrams, data structures, and edge lists if necessary.

3. **`function_usage` (CLI Help Function) (if the program(s) has(have) -h or --help functionality)**:
   - Ensure the `usage()` or `function_usage()' / `--help` display in code reflects all current CLI flags (`-h`, `--help`, `-d`, `--dryrun`, `--keep-logfile`, etc.).
   - Verify that option descriptions, default values, and example invocations are accurate.

4. **`docs/` (MkDocs Documentation) (if this folder exists)**:
   - Check documentation files under `docs/` (`index.md`, `cli.md`, `api.md`, `rules.md`, `fuzzing.md`, etc.).
   - Update `mkdocs.yml` navigation if new pages or modules were created.
   - Verify build with:
     ```bash
     ./_docs
     ```
5. **`ChangeLog.md`**:
   - if history.md exist integrate it into ChangeLog.md then remove the file
   - Append or update the entry for the current change with `$VERSION` and a concise summary.

6. **'NEWS**:   
   - keep the newest two changes from the ChangeLog.md in the file: NEWS
   
7. **`man/` File** (if the folder ./man exists):
   - Inspect the man page under `man/` (e.g., `man/<program_name>.1`).
   - Update the date, version header, and any modified command options or descriptions.

8. **`tldr/` File** (if the folder ./tldr exist):
   - Inspect the tldr page under `tldr/` (e.g., `tldr/<program_name>.page.md`).
   - Ensure quick reference commands and descriptions accurately reflect typical usage patterns.


### 3. Verify Line Endings

Ensure all edited documentation files retain Unix (LF, `\n`) line endings:
```bash
git ls-files --eol | awk '$2 == "w/crlf"'
```

### 4. Git Commit

Stage the updated documentation and commit using the required message format:
```bash
git add README.md README_tecdocu.md docs/ mkdocs.yml history.md man/ tldr/
git commit -m "<version> - documentation updated"
```
Example:
```bash
git commit -m "20260906133143 - documentation updated"
```

---

## Rules

1. **Never leave documentation stale**: If a flag or function changes in code, the documentation must match before the task is marked complete.
2. **Synchronized version numbers**: Update the version number across all modified documentation files simultaneously.
3. **Commit message format**: The documentation commit must strictly follow `<version> - documentation updated`.
