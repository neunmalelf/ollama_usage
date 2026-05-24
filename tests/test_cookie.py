"""Tests for ollama_usage.cookie."""

from __future__ import annotations

import pathlib
from unittest.mock import patch, mock_open

from ollama_usage.cookie import _chromium_key, get_cookie_env
from ollama_usage.exceptions import BrowserNotFoundError

def test_get_cookie_env() -> None:
    with patch.dict("os.environ", {"OLLAMA_BROWSER_COOKIE": "my-env-cookie"}):
        assert get_cookie_env() == "my-env-cookie"

    with patch.dict("os.environ", {}, clear=True):
        assert get_cookie_env() is None

@patch("ollama_usage.cookie._SYSTEM", "Windows")
@patch("pathlib.Path.exists", return_value=True)
@patch("builtins.open", new_callable=mock_open, read_data='{"os_crypt": {"encrypted_key": "aaaaaYWJjZGU="}}')
@patch("win32crypt.CryptUnprotectData", return_value=(None, b"decrypted_key"))
def test_chromium_key_caching(mock_crypt, mock_file_open, mock_exists) -> None:
    # Clear cache before test to ensure clean state
    _chromium_key.cache_clear()
    
    path = pathlib.Path("some_local_state")
    
    # First call - should decrypt and read
    key1 = _chromium_key(path, "Chrome")
    assert key1 == b"decrypted_key"
    assert mock_crypt.call_count == 1
    assert mock_file_open.call_count == 1
    
    # Second call with same parameters - should return cached value and not call open or win32crypt
    key2 = _chromium_key(path, "Chrome")
    assert key2 == b"decrypted_key"
    assert mock_crypt.call_count == 1
    assert mock_file_open.call_count == 1

@patch("ollama_usage.cookie._SYSTEM", "Darwin")
@patch("pathlib.Path.exists", return_value=True)
@patch("builtins.open", new_callable=mock_open, read_data='{"os_crypt": {"encrypted_key": "aaaaaYWJjZGU="}}')
@patch("subprocess.run")
def test_chromium_key_darwin_keychain_mapping(mock_run, mock_file_open, mock_exists) -> None:
    # Clear cache before test to ensure clean state
    _chromium_key.cache_clear()
    
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "my_password\n"
    
    path = pathlib.Path("some_local_state_darwin")
    
    # Let's test Edge service map
    _chromium_key(path, "Edge")
    
    # Check that subprocess.run was called with correct arguments for Edge
    mock_run.assert_called_with(
        ["security", "find-generic-password", "-a", "Microsoft Edge",
         "-s", "Microsoft Edge Safe Storage", "-w"],
        capture_output=True, text=True,
    )
