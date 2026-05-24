#!/bin/bash
# Compile ollama-usage to a single-file executable
# Uses PyInstaller (Nuitka has issues with Python 3.14 + MinGW64 on Windows)
#
# Usage: Run from the project root directory
#   source _c.sh   # or
#   . _c.sh        # or run commands directly

set -e

# Configuration
PACKAGE="ollama_usage"
ENTRY_POINT="ollama_usage/cli.py"
OUTPUT_NAME="ollama-usage.exe"
DIST_DIR="dist"

echo "=== Compiling ollama-usage ==="

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build/ dist/ *.spec 2>/dev/null || true

# Build with PyInstaller
echo "Building with PyInstaller..."

# Note: On Windows, run this script in a shell where 'python' is available
# If python is not found, try: 'py -m PyInstaller' or specify full path
python -m PyInstaller \
    --onefile \
    --name "ollama-usage" \
    --console \
    --hidden-import="${PACKAGE}" \
    --hidden-import="${PACKAGE}.cli" \
    --hidden-import="${PACKAGE}.scraper" \
    --hidden-import="${PACKAGE}.cookie" \
    --hidden-import="${PACKAGE}.exceptions" \
    --hidden-import="${PACKAGE}.notify" \
    --collect-all colorama \
    --collect-all cryptography \
    "${ENTRY_POINT}"

# Check result
if [ -f "${DIST_DIR}/${OUTPUT_NAME}" ]; then
    SIZE=$(ls -lh "${DIST_DIR}/${OUTPUT_NAME}" | awk '{print $5}')
    echo ""
    echo "=== Build successful ==="
    echo "Output: ${DIST_DIR}/${OUTPUT_NAME}"
    echo "Size: ${SIZE}"
    echo ""
    echo "Testing binary..."
    "${DIST_DIR}/${OUTPUT_NAME}" --version
else
    echo "ERROR: Build failed - no output found"
    exit 1
fi