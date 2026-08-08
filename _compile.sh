#!/bin/bash
# Compile ollama-usage to a single-file executable with Nuitka.
#
# Nuitka is used instead of PyInstaller because it produces native-compiled,
# faster-starting, harder-to-decompile binaries.
#
# On Python 3.14 Nuitka's MinGW64 backend is not supported, so we use the
# --zig flag (Nuitka downloads the Zig compiler automatically on first build;
# no MSVC or manual MinGW install needed).
#
# Usage: Run from the project root directory
#   ./_compile.sh
#
# Requires: python with nuitka installed (pip install nuitka).
# First run downloads the Zig toolchain and may take a few minutes.

set -e

# Configuration
PACKAGE="ollama_usage"
ENTRY_POINT="ollama_usage/cli.py"
OUTPUT_NAME="ollama-usage.exe"
OUTPUT_DIR="dist"
ICON="icon.ico"

# Optional version metadata for the Windows .exe (embedded in the file's
# Properties -> Details tab). Windows version fields are 16-bit (max 65535),
# so each component is clamped and a trailing run of digits longer than 8
# chars (e.g. a timestamp like 20280807093000) is collapsed.
VERSION=$(python -c "
import re
from ollama_usage import __version__ as v
parts = [p for p in re.split(r'[^0-9]+', str(v)) if p]
parts = [str(max(0, min(65535, int(p[:5])))) for p in parts]
while len(parts) < 4:
    parts.append('0')
print('.'.join(parts[:4]))
" 2>/dev/null || echo "0.0.0.0")

echo "=== Compiling ollama-usage with Nuitka ==="

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build/ dist/ "$PACKAGE.build" "$PACKAGE.dist" "$ENTRY_POINT.build" "$ENTRY_POINT.dist" *.spec 2>/dev/null || true

# Build with Nuitka (single-file mode).
#   --onefile                       bundle everything into one .exe
#   --enable-plugin=tk-inter        include the tkinter GUI toolkit
#   --windows-icon-from-ico         embed icon.ico as the .exe resource icon
#   --include-data-files            bundle icon.ico into the onefile so the
#                                   GUI window can load it at runtime
#   --include-package               force-include these packages (cryptography
#                                   is used indirectly and pywin32 for cookies)
#   --output-dir / --output-filename  place the final .exe in dist/ollama-usage.exe
#   --assume-yes-for-downloads      let Nuitka fetch its winlibs GCC / deps silently
echo "Building with Nuitka (version $(python -m nuitka --version 2>/dev/null | head -1))..."

# IMPORTANT: unset CC/CXX so Nuitka's --zig logic takes over. If CC is set in
# the environment (e.g. CC=GCC from a shell profile), Nuitka skips its zig
# detection and falls back to gcc -> MinGW64, which FATALs on Python 3.13+.
unset CC CXX

python -m nuitka \
    --onefile \
    --zig \
    --enable-plugin=tk-inter \
    --windows-icon-from-ico="${ICON}" \
    --include-data-files="${ICON}=${ICON}" \
    --product-name="ollama-usage" \
    --product-version="${VERSION}" \
    --file-version="${VERSION}" \
    --file-description="Ollama Cloud quota usage checker" \
    --output-dir="${OUTPUT_DIR}" \
    --output-filename="${OUTPUT_NAME}" \
    --include-package=cryptography \
    --include-package="${PACKAGE}" \
    --assume-yes-for-downloads \
    "${ENTRY_POINT}"

# Nuitka emits the final onefile .exe inside the output dir.
FINAL="${OUTPUT_DIR}/${OUTPUT_NAME}"

# Check result
if [ -f "${FINAL}" ]; then
    SIZE=$(ls -lh "${FINAL}" | awk '{print $5}')
    echo ""
    echo "=== Build successful ==="
    echo "Output: ${FINAL}"
    echo "Size: ${SIZE}"
    echo ""
    echo "Testing binary..."
    "${FINAL}" --version
    # copy the *.exe to c:\Users\fmann\scoop\apps\python\current\Scripts\ overwrite the file if it already exist
    echo "Copying ${FINAL} to /c/Users/fmann/scoop/apps/python/current/Scripts/"
    cp "${FINAL}" /c/Users/fmann/scoop/apps/python/current/Scripts/
else
    echo "ERROR: Build failed - no output found at ${FINAL}"
    exit 1
fi
