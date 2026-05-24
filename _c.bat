@echo off
REM Compile ollama-usage to a single-file executable
REM Uses PyInstaller (Nuitka has issues with Python 3.14 + MinGW64 on Windows)

setlocal enabledelayedexpansion

set PACKAGE=ollama_usage
set ENTRY_POINT=ollama_usage/cli.py
set OUTPUT_NAME=ollama-usage.exe
set DIST_DIR=dist

echo === Compiling ollama-usage ===

REM Clean previous builds
echo Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist *.spec del /q *.spec

REM Build with PyInstaller
echo Building with PyInstaller...
python -m PyInstaller ^
    --onefile ^
    --name "ollama-usage" ^
    --console ^
    --hidden-import="%PACKAGE%" ^
    --hidden-import="%PACKAGE%.cli" ^
    --hidden-import="%PACKAGE%.scraper" ^
    --hidden-import="%PACKAGE%.cookie" ^
    --hidden-import="%PACKAGE%.exceptions" ^
    --hidden-import="%PACKAGE%.notify" ^
    --collect-all colorama ^
    --collect-all cryptography ^
    "%ENTRY_POINT%"

REM Check result
if exist "%DIST_DIR%\%OUTPUT_NAME%" (
    echo.
    echo === Build successful ===
    echo Output: %DIST_DIR%\%OUTPUT_NAME%
    for %%A in ("%DIST_DIR%\%OUTPUT_NAME%") do echo Size: %%~zA bytes
    echo.
    echo Testing binary...
    "%DIST_DIR%\%OUTPUT_NAME%" --version
) else (
    echo ERROR: Build failed - no output found
    exit /b 1
)