---
name: tecdoc_create
description: Generate a complete technical manual (Markdown + single-file HTML) for the current project, scanning all Python source files except those under tests/. Mermaid is bundled inline so the HTML works offline. Validates both outputs for syntax / logical errors (Mermaid reserved-keyword check, HTML tag balance, code-fence balance, etc.) and reports results. Use whenever the user asks for project documentation, a code reference, an architecture manual, or wants to regenerate `tec_manual.md` / `tec_manual.html`.
---

# tecdoc_create — Auto-Generate Technical Manuals

Generates two documentation artifacts from your project's Python source (always written into the `docs/` subfolder):

| Output | Description |
|---|---|
| `docs/tec_manual.md` | Markdown manual with Mermaid architecture diagrams, TOC, class hierarchy, call graph, etc. |
| `docs/tec_manual.html` | **Single-file, fully self-contained** styled HTML — Mermaid is bundled inline so the file works offline. |

## When to use this skill

- User asks for "a manual for this project", "document my code", "reference docs", etc.
- A new project needs an entry-point technical overview
- After a large refactor, regenerate the manual
- User wants both Markdown (for wikis / GitHub) and HTML (for local browsing)

## How it works

1. **Scans** the project root (defaults to `cwd`) for `*.py` files
2. **Excludes** any path under these directories:
   - `tests/`, `__pycache__/`, `.git/`, `.pytest_cache/`, `0_bak/`
   - `docs/`, `_internal/`, `htmlcov/`, `.venv/`, `node_modules/`
   - `bak/`, `_bak/`, `.idea/`, `.vscode/`
3. **Excludes** any file whose name starts with `test_`, `_test`, or `conftest`
4. **Parses** each file with Python's `ast` module
5. **Extracts**: classes, methods, properties, decorators, signatures, docstrings, constants, imports
6. **Generates** Markdown with embedded Mermaid diagrams
7. **Bundles Mermaid inline** in the HTML — downloads once, caches under
   `_tecdoc_assets/mermaid.min.js`, and minifies the embedded copy so the
   HTML is ~30% smaller than the raw library
8. **Generates** styled HTML by converting the Markdown to safe HTML
9. **Validates** both outputs:
   - Markdown: code-fence balance, Mermaid reserved-keyword check
   - HTML: tag balance for `<html>`, `<head>`, `<body>`, `<pre>`, `<ul>`, `<ol>`, `<table>`, `<blockquote>`, `<div>`; Mermaid reserved-keyword check
   - Optional: Mermaid CLI (`mmdc`) runtime validation if installed

## How to invoke

### As a tool (executable)

```bash
bash _tecdoc_create.sh                                 # scan cwd → docs/tec_manual.*
bash _tecdoc_create.sh . dd                            # scan cwd, prefix=dd → docs/dd_manual.*
bash _tecdoc_create.sh . tec --no-bundle               # use Mermaid CDN, smaller HTML
bash _tecdoc_create.sh . tec --no-minify               # embed but skip minification
bash _tecdoc_create.sh . tec --output-dir build       # write to build/ instead of docs/
bash _tecdoc_create.sh . tec --output-dir /tmp/x       # absolute path also supported
bash _tecdoc_create.sh /path/to/proj api               # scan other dir, prefix=api
bash _tecdoc_create.sh --help                          # show all options
```

Or directly via Python:

```bash
python _tecdoc_create.py [project_root] [output_prefix] \
    [--no-bundle] [--no-minify] [--output-dir DIR]
```

### Flags

| Flag | Effect | Default |
|---|---|---|
| `--no-bundle` | Reference Mermaid from CDN instead of embedding inline | embed (offline-capable) |
| `--no-minify` | Skip JS minification when embedding (larger HTML, easier to debug) | minify on |
| `--output-dir DIR` | Directory to write the manuals into. Relative paths resolved against `project_root`; absolute paths used as-is. | `docs` |

### As a skill (via the `skill` tool in Codebuff)

The skill description above is loaded by the `skill` tool. When invoked, follow the workflow below.

## Workflow when this skill is loaded

1. **Read project source files** using the `read_files` tool — but **do NOT read anything under `tests/`** (or other excluded dirs).
2. **If asked to also generate the manuals** (not just explain):
   - Spawn a `basher` agent to run `bash _tecdoc_create.sh` and capture the output.
   - Verify the output files exist and pass validation.
3. **If asked to explain the project**, summarize the sections that `tecdoc_create` would produce:
   - Project overview
   - Source file list
   - Class hierarchy
   - Module-level functions
   - Module constants
   - Architecture diagram (Mermaid)

## Output sections produced

`tec_manual.md` (and the corresponding `tec_manual.html`) contains:

1. Project Overview
2. Source Files (table with docstrings)
3. Architecture Diagram (Mermaid `graph TD`)
4. Module Imports
5. Module Constants
6. Classes (with methods, properties, class vars, docstrings)
7. Functions (module-level)
8. Class Hierarchy (Mermaid `classDiagram`)
9. Call Graph (Mermaid `graph LR`)
10. Statistics table

## Validation criteria

A successful run prints `✅ ALL CHECKS PASSED`. Common failure modes:

| Issue | Cause | Fix |
|---|---|---|
| Mermaid block: reserved keyword `style`/`class`/`end` used as node id | Node name conflicts with Mermaid directive keyword | Rename the node to something like `styleN` or `myStyle` |
| Unbalanced `<pre>` / `</pre>` tags | Markdown converted incorrectly | The bug is in the converter; report and patch |
| Unclosed code fence (odd number of ``` ) | A code block was opened but not closed in source | Check the Mermaid block generation |

## Files

| File | Purpose |
|---|---|
| `_tecdoc_create.py` | Main tool — AST-based parser + Markdown/HTML generator + validator |
| `_tecdoc_create.sh` | Bash wrapper (following `_do.sh` / `_commit.sh` convention) — forwards all flags |
| `SKILL.md` | This file |
| `docs/tec_manual.md` | Generated Markdown manual |
| `docs/tec_manual.html` | Generated self-contained HTML manual (Mermaid bundled) |
| `_tecdoc_assets/mermaid.min.js` | Cached Mermaid library (gitignored) |

## Example output

```
tecdoc_create: scanning B:\work\1_ddmicro\dd_core
  Output prefix: tec
  Bundle Mermaid inline: True (with minification)
  Excluded dirs: ['0_bak', '_internal', 'docs', 'htmlcov', ...]

Found 2 source file(s):
  • _tecdoc_create.py
  • dd.py

  Downloading Mermaid from https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js …
  Cached Mermaid (3,339,532 bytes) at _tecdoc_assets/mermaid.min.js

✓ Created docs/tec_manual.md (54,493 chars, 1,719 lines)
✓ Created docs/tec_manual.html (2,317,402 chars, 3,201 lines)

# With --output-dir build:
✓ Created build/tec_manual.md (...)
✓ Created build/tec_manual.html (...)

============================================================
VALIDATION
============================================================
  Markdown: OK
  HTML: OK
============================================================
MERMAID SYNTAX CHECK (via mmdc CLI if available)
============================================================
  (Mermaid CLI 'mmdc' not installed — skipped runtime validation)
============================================================
✅ ALL CHECKS PASSED
============================================================
```
