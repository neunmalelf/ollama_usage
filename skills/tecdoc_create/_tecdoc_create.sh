#!/usr/bin/env bash
# _tecdoc_create.sh — Bash wrapper for the tecdoc_create tool
#
# Usage:
#   bash _tecdoc_create.sh [project_root] [output_prefix] [--no-bundle] [--no-minify]
#
# Positional args:
#   project_root    Directory to scan (default: this script's directory)
#   output_prefix   Output file prefix (default: "tec" → tec_manual.md/html)
#
# Optional flags (forwarded to the Python tool):
#   --no-bundle           Use Mermaid from CDN instead of embedding it inline
#   --no-minify           Keep embedded Mermaid source verbatim (larger HTML)
#   --output-dir DIR      Output directory (default: docs/, relative to project_root)
#   -h, --help            Show this help text
#
# Examples:
#   bash _tecdoc_create.sh                              # scan cwd → docs/tec_manual.*
#   bash _tecdoc_create.sh . dd                        # scan cwd, prefix=dd → docs/dd_manual.*
#   bash _tecdoc_create.sh . tec --no-bundle           # use CDN, smaller HTML
#   bash _tecdoc_create.sh . tec --no-minify           # embed but skip minification
#   bash _tecdoc_create.sh . tec --output-dir build     # write to build/ instead of docs/
#   bash _tecdoc_create.sh . tec --output-dir /tmp/x    # absolute path also supported
#   bash _tecdoc_create.sh /path/to/proj api            # scan other dir, prefix=api
#
# Generates (always under docs/):
#   docs/<prefix>_manual.md
#   docs/<prefix>_manual.html
# Then validates both files for syntax / logical errors.

cd "$(dirname "$0")"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Pick Python interpreter
PYTHON_BIN="${PYTHON_BIN:-python}"

if ! command -v "$PYTHON_BIN" &>/dev/null; then
    echo "Error: $PYTHON_BIN not found in PATH"
    exit 1
fi

if [[ ! -f "$SCRIPT_DIR/_tecdoc_create.py" ]]; then
    echo "Error: _tecdoc_create.py not found next to this script ($SCRIPT_DIR)"
    exit 1
fi

# Handle help locally for a quick path
for arg in "$@"; do
    if [[ "$arg" == "-h" || "$arg" == "--help" ]]; then
        sed -n '2,30p' "$0"
        exit 0
    fi
done

echo "tecdoc_create wrapper"
echo "  Project root: ${1:-$SCRIPT_DIR}"
echo "  Output prefix: ${2:-tec}"
echo "  Output dir:   docs/  (always)"
echo "  Python: $PYTHON_BIN"
echo "  Extra args: ${@:3}"
echo ""

# Forward ALL args to the Python tool so --no-bundle / --no-minify propagate
"$PYTHON_BIN" "$SCRIPT_DIR/_tecdoc_create.py" "$@"
