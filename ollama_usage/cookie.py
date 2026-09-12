"""Read the Ollama __Secure-session cookie from installed browsers."""

from __future__ import annotations

import configparser
import contextlib
import json
import logging
import os
import pathlib
import platform
import shutil
import sqlite3
import tempfile
from base64 import b64decode
from functools import lru_cache
from typing import Callable, Generator

from ollama_usage.exceptions import (
    BrowserNotFoundError,
    OllamaUsageError,
    UnsupportedOSError,
)

logger = logging.getLogger(__name__)

_SYSTEM = platform.system()
_COOKIE_NAME = "__Secure-session"
_COOKIE_HOST = "ollama.com"


# --- SQLite helpers ---

@contextlib.contextmanager
def _copy_db(path: pathlib.Path) -> Generator[str, None, None]:
    """Copy a locked SQLite DB to a temp file, yield the path, then delete it.

    On Windows the browser may hold the source file open with an exclusive
    lock. ``shutil.copy2`` then fails with ``PermissionError`` (WinError 32),
    so we open the source with all share flags (read/write/delete) before
    copying.
    """
    if not path.exists():
        raise BrowserNotFoundError(f"Cookie database not found: {path}")
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    try:
        _copy_file_shared(str(path), tmp.name)
    except OSError as e:
        pathlib.Path(tmp.name).unlink(missing_ok=True)
        raise BrowserNotFoundError(f"Could not copy cookie database (it may be locked by a running browser): {e}") from e
    try:
        yield tmp.name
    finally:
        pathlib.Path(tmp.name).unlink(missing_ok=True)
        logger.debug("Temp DB deleted: %s", tmp.name)


def _copy_file_shared(src: str, dst: str) -> None:
    """Copy ``src`` to ``dst``, opening ``src`` with full sharing on Windows.

    Falls back to ``shutil.copy2`` on non-Windows platforms.
    """
    if _SYSTEM != "Windows":
        shutil.copy2(src, dst)
        return

    # Open the source with FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE
    # so a running browser's exclusive lock does not block us (WinError 32).
    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80

    import ctypes
    import msvcrt
    from ctypes import wintypes

    handle = ctypes.windll.kernel32.CreateFileW(
        wintypes.LPCWSTR(src),
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError()
    src_fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    try:
        with os.fdopen(src_fd, "rb") as fsrc, open(dst, "wb") as fdst:
            shutil.copyfileobj(fsrc, fdst)
    except Exception:
        os.close(src_fd)
        raise


def _query_cookie(db_path: str, query: str, params: tuple) -> bytes | None:
    """Execute a query on a SQLite cookie database and return the first result."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# --- Firefox ---

def _firefox_profile_bases() -> list[pathlib.Path]:
    """Return all possible Firefox profile roots for the current platform."""
    home = pathlib.Path.home()
    if _SYSTEM == "Windows":
        return [home / "AppData/Roaming/Mozilla/Firefox"]
    if _SYSTEM == "Darwin":
        return [home / "Library/Application Support/Firefox"]
    if _SYSTEM == "Linux":
        return [
            home / ".mozilla/firefox",
            home / ".config/mozilla/firefox",
            home / ".var/app/org.mozilla.firefox/.mozilla/firefox",
            home / ".var/app/org.mozilla.firefox/.mozilla",
            home / ".var/app/org.mozilla.firefox/data/.mozilla/firefox",
            home / "snap/firefox/common/.mozilla/firefox",
        ]
    raise UnsupportedOSError(f"Firefox not supported on {_SYSTEM}")


def _root_has_profiles(base: pathlib.Path) -> bool:
    """Return True when a Firefox profile root contains any profile data."""
    if not base.is_dir():
        return False
    if (base / "profiles.ini").is_file():
        return True
    try:
        return any(
            entry.is_dir() and (entry / "cookies.sqlite").is_file()
            for entry in base.iterdir()
        )
    except OSError:
        return False


def _firefox_profiles_dir() -> pathlib.Path:
    """Return the first Firefox profile root that contains profiles.

    Empty roots (e.g. a leftover ``~/.mozilla/firefox`` after Firefox moved
    to ``~/.config/mozilla/firefox``) are skipped in favour of populated
    ones.
    """
    for base in _firefox_profile_bases():
        if _root_has_profiles(base):
            return base
    return _firefox_profile_bases()[0]


def _get_default_firefox_profile(base: pathlib.Path) -> pathlib.Path:
    """
    Return the path of the default Firefox profile that contains cookies.sqlite.
    Reads profiles.ini, collects all candidates (Default=1 first),
    then returns the first one that actually has cookies.sqlite.
    Falls back to glob if profiles.ini is absent or malformed.
    """
    candidates: list[pathlib.Path] = []

    ini_candidates = [base / "profiles.ini", base.parent / "profiles.ini"]
    if base.name == ".mozilla":
        ini_candidates.insert(0, base / "firefox" / "profiles.ini")
    for ini_candidate in ini_candidates:
        if not ini_candidate.exists():
            continue
        config = configparser.ConfigParser()
        config.read(str(ini_candidate), encoding="utf-8")

        defaults: list[pathlib.Path] = []
        others: list[pathlib.Path] = []

        for section in config.sections():
            rel_path = config.get(section, "Path", fallback=None)
            if not rel_path:
                continue
            is_relative = config.get(section, "IsRelative", fallback="1") == "1"
            profile = (
                (ini_candidate.parent / rel_path)
                if is_relative
                else pathlib.Path(rel_path)
            )
            if config.get(section, "Default", fallback="0") == "1":
                defaults.append(profile)
            else:
                others.append(profile)

        candidates = defaults + others
        break

    if not candidates:
        logger.debug("profiles.ini not found or empty — falling back to profile search")
        # Firefox profiles are normally named *.default-release, but older
        # installs and custom profiles may use different names.
        candidates = [
            path for path in base.iterdir()
            if path.is_dir() and (path / "cookies.sqlite").exists()
        ] if base.is_dir() else []

    if not candidates:
        raise BrowserNotFoundError(f"No Firefox profile found under {base}")

    for profile in candidates:
        db = profile / "cookies.sqlite"
        if db.exists():
            logger.debug("Firefox profile: %s", profile)
            return profile

    raise BrowserNotFoundError(f"No Firefox profile with cookies.sqlite found under {base}")


def firefox_profile_diagnostics() -> list[tuple[pathlib.Path, list[pathlib.Path]]]:
    """Return every Firefox root and profile discovered without reading cookies."""
    result: list[tuple[pathlib.Path, list[pathlib.Path]]] = []
    for base in _firefox_profile_bases():
        profiles: list[pathlib.Path] = []
        if base.is_dir():
            try:
                profiles = sorted(
                    path for path in base.iterdir()
                    if path.is_dir() and (path / "cookies.sqlite").is_file()
                )
            except OSError:
                pass
        result.append((base, profiles))
    return result


def get_cookie_firefox() -> str | None:
    """Read __Secure-session from any discoverable Firefox profile."""
    bases = _firefox_profile_bases()
    found_profile = False
    for base in bases:
        if not base.is_dir():
            continue
        try:
            profile = _get_default_firefox_profile(base)
        except BrowserNotFoundError:
            continue
        found_profile = True
        with _copy_db(profile / "cookies.sqlite") as db:
            value = _query_cookie(
                db,
                "SELECT value FROM moz_cookies "
                "WHERE (host=? OR host=?) AND name=? "
                "ORDER BY CASE WHEN host=? THEN 0 ELSE 1 END",
                (_COOKIE_HOST, "." + _COOKIE_HOST, _COOKIE_NAME, _COOKIE_HOST),
            )
        if isinstance(value, str) and value:
            logger.debug("Firefox cookie found in %s", profile)
            return value
    if found_profile:
        return None
    raise BrowserNotFoundError(
        "No Firefox profile found in configured Firefox profile locations"
    )


# --- Chromium-based browsers ---

@lru_cache(maxsize=8)
def _chromium_key(local_state: pathlib.Path, browser_name: str = "Chrome") -> bytes:
    """Decrypt the AES key from Chrome's Local State file."""
    if not local_state.exists():
        raise BrowserNotFoundError(f"Local State not found: {local_state}")
    with open(local_state, encoding="utf-8") as f:
        data = json.load(f)
    try:
        encrypted_key = b64decode(data["os_crypt"]["encrypted_key"])[5:]
    except (KeyError, TypeError, ValueError) as e:
        raise BrowserNotFoundError(
            f"Local State for {browser_name} is missing or has no encrypted_key "
            f"(is {browser_name} installed and has been run at least once?): {e}"
        ) from e

    if _SYSTEM == "Windows":
        import win32crypt
        return win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
    elif _SYSTEM == "Darwin":
        import hashlib
        import subprocess
        service_map = {
            "Chrome": ("Chrome", "Chrome Safe Storage"),
            "Brave": ("Brave", "Brave Safe Storage"),
            "Edge": ("Microsoft Edge", "Microsoft Edge Safe Storage"),
            "Opera": ("Opera", "Opera Safe Storage"),
        }
        account, service = service_map.get(browser_name, ("Chrome", "Chrome Safe Storage"))
        result = subprocess.run(
            ["security", "find-generic-password", "-a", account,
             "-s", service, "-w"],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise BrowserNotFoundError(
                f"Could not retrieve {browser_name} Safe Storage key from Keychain "
                f"(exit {result.returncode}): {result.stderr.strip()}"
            )
        password = result.stdout.strip().encode()
        return hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, 16)
    else:
        import hashlib
        return hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, 16)


def _decrypt_chromium_value(encrypted: bytes, key: bytes) -> str:
    """Decrypt a Chromium AES-GCM encrypted cookie value."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce, ciphertext = encrypted[3:15], encrypted[15:]
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode()


def _read_chromium_cookie(db_path: pathlib.Path, key: bytes) -> str | None:
    """Read and decrypt __Secure-session from a Chromium cookies DB."""
    with _copy_db(db_path) as tmp:
        encrypted = _query_cookie(
            tmp,
            "SELECT encrypted_value FROM cookies WHERE host_key=? AND name=?",
            (_COOKIE_HOST, _COOKIE_NAME),
        )
    if not encrypted:
        return None
    return _decrypt_chromium_value(encrypted, key)


def _chromium_cookie(base: pathlib.Path, cookies_rel: pathlib.Path, browser_name: str = "Chrome") -> str | None:
    """Generic helper for all Chromium-based browsers."""
    key = _chromium_key(base / "Local State", browser_name)
    return _read_chromium_cookie(base / cookies_rel, key)


# --- Per-browser public API ---

def _chromium_base(win: str, linux: str, mac: str, linux_snap: str | None = None, linux_flatpak: str | None = None) -> pathlib.Path:
    if _SYSTEM == "Windows":
        return pathlib.Path.home() / win
    if _SYSTEM == "Darwin":
        return pathlib.Path.home() / mac
    if _SYSTEM == "Linux":
        # Ordre de priorité : installation classique, puis Snap, puis Flatpak
        candidates = [pathlib.Path.home() / linux]
        if linux_snap:
            candidates.append(pathlib.Path.home() / linux_snap)
        if linux_flatpak:
            candidates.append(pathlib.Path.home() / linux_flatpak)
        for path in candidates:
            if path.exists():
                logger.debug("Chromium base dir: %s", path)
                return path
        return candidates[0]  # laisse l'erreur se produire normalement
    raise UnsupportedOSError(f"Unsupported OS: {_SYSTEM}")


_CHROMIUM_COOKIES_PATH = pathlib.Path("Default/Network/Cookies")


def get_cookie_chrome() -> str | None:
    base = _chromium_base(
        win="AppData/Local/Google/Chrome/User Data",
        linux=".config/google-chrome",
        mac="Library/Application Support/Google/Chrome",
        linux_snap="snap/chromium/common/chromium/Default",
        linux_flatpak=".var/app/com.google.Chrome/config/google-chrome",
    )
    return _chromium_cookie(base, _CHROMIUM_COOKIES_PATH, "Chrome")


def get_cookie_edge() -> str | None:
    base = _chromium_base(
        win="AppData/Local/Microsoft/Edge/User Data",
        linux=".config/microsoft-edge",
        mac="Library/Application Support/Microsoft Edge",
        linux_flatpak=".var/app/com.microsoft.Edge/config/microsoft-edge",
    )
    return _chromium_cookie(base, _CHROMIUM_COOKIES_PATH, "Edge")


def get_cookie_brave() -> str | None:
    base = _chromium_base(
        win="AppData/Local/BraveSoftware/Brave-Browser/User Data",
        linux=".config/BraveSoftware/Brave-Browser",
        mac="Library/Application Support/BraveSoftware/Brave-Browser",
        linux_flatpak=".var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser",
    )
    return _chromium_cookie(base, _CHROMIUM_COOKIES_PATH, "Brave")


def get_cookie_opera() -> str | None:
    base = _chromium_base(
        win="AppData/Roaming/Opera Software/Opera Stable",
        linux=".config/opera",
        mac="Library/Application Support/com.operasoftware.Opera",
    )
    return _chromium_cookie(base, pathlib.Path("Cookies"), "Opera")


# --- Auto-detection ---

_BROWSERS: list[Callable[[], str | None]] = [
    get_cookie_chrome,
    get_cookie_firefox,
    get_cookie_edge,
    get_cookie_brave,
    get_cookie_opera,
]

def get_cookie_auto() -> str:
    """Try each browser in order and return the first valid cookie found."""
    for browser in _BROWSERS:
        logger.debug("Trying %s...", browser.__name__)
        try:
            cookie = browser()
            if cookie:
                logger.debug("Cookie found via %s", browser.__name__)
                return cookie
        except OllamaUsageError as e:
            logger.debug("%s failed: %s", browser.__name__, e)
            continue
        except Exception as e:  # catch KeyError, JSON errors, etc. and treat as browser not usable
            logger.debug("%s failed with unexpected error: %s", browser.__name__, e)
            continue
    raise OllamaUsageError(
        "No Ollama session cookie found in any supported browser. "
        "Pass it manually with --cookie, or store one once with "
        "--save-cookie to run without any installed browser."
    )


# --- Environment Variable ---


def get_cookie_env() -> str | None:
    """Read cookie from OLLAMA_BROWSER_COOKIE environment variable."""
    import os

    return os.environ.get("OLLAMA_BROWSER_COOKIE")