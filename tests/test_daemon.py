"""Tests for --daemon / --damon (run in background, killall)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import pathlib
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# CLI parser accepts --daemon and --damon
# ---------------------------------------------------------------------------

def _parse_args(argv):
    """Helper to parse args via cli.main's parser without executing main."""
    import ollama_usage.cli as cli
    import argparse
    captured = {}
    original_parse = argparse.ArgumentParser.parse_args

    def fake_parse(self, args=None, namespace=None):
        result = original_parse(self, args, namespace)
        captured["args"] = result
        raise SystemExit(0)

    with patch.object(argparse.ArgumentParser, "parse_args", fake_parse):
        with patch.object(sys, "argv", ["ollama_usage"] + argv):
            try:
                cli.main()
            except SystemExit:
                pass
    return captured.get("args")


class TestDaemonParser:

    def test_daemon_flag(self):
        args = _parse_args(["--daemon"])
        assert args.daemon is True

    def test_damon_alias(self):
        args = _parse_args(["--damon"])
        assert args.daemon is True

    def test_daemon_with_widget(self):
        args = _parse_args(["--widget", "--daemon"])
        assert args.daemon is True
        assert args.widget is True

    def test_no_daemon_by_default(self):
        args = _parse_args([])
        assert args.daemon is False

    def test_daemon_help_contains_killall(self):
        result = subprocess.run(
            ["/home/fmann/sbin/ollama_usage", "--help"],
            capture_output=True, text=True, timeout=5,
        )
        out = result.stdout + result.stderr
        assert "--daemon" in out
        assert "killall" in out

    def test_readme_contains_daemon_and_killall(self):
        readme = pathlib.Path(__file__).resolve().parent.parent / "README.md"
        readme = readme.read_text()
        assert "--daemon" in readme
        assert "killall ollama_usage" in readme


# ---------------------------------------------------------------------------
# Daemon subprocess logic (unit, with mocks)
# ---------------------------------------------------------------------------

class TestDaemonForkLogic:

    def test_daemon_spawns_child_and_parent_exits(self):
        """Parent should spawn child via subprocess.Popen and exit 0."""
        import ollama_usage.cli as cli
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        with patch("ollama_usage.cli.subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("ollama_usage.cli.sys.exit") as mock_exit:
            with patch.object(sys, "argv", ["ollama_usage", "--daemon", "--widget"]):
                with patch("ollama_usage.cli.get_cookie_auto", return_value="cookie"), \
                     patch("ollama_usage.widget.launch_widget") as mock_widget:
                    mock_exit.side_effect = SystemExit(0)
                    try:
                        cli.main()
                    except SystemExit as e:
                        assert e.code == 0
                    # Popen should have been called to spawn child
                    mock_popen.assert_called_once()
                    # Parent should exit before reaching widget
                    mock_widget.assert_not_called()

    def test_daemon_popen_receives_correct_args(self):
        """The child process should receive all args except --daemon/--damon."""
        import ollama_usage.cli as cli
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        with patch("ollama_usage.cli.subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("ollama_usage.cli.sys.exit", side_effect=SystemExit(0)):
            with patch.object(sys, "argv", ["ollama_usage", "--widget", "--daemon", "--autorefresh", "60"]):
                try:
                    cli.main()
                except SystemExit:
                    pass
                call_args = mock_popen.call_args
                launched = call_args[0][0]  # first positional arg = command list
                assert "--daemon" not in launched
                assert "--widget" in launched
                assert "--autorefresh" in launched
                assert "60" in launched

    def test_daemon_popen_uses_devnull(self):
        """stdin/stdout/stderr should be DEVNULL for the child."""
        import ollama_usage.cli as cli
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        with patch("ollama_usage.cli.subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("ollama_usage.cli.sys.exit", side_effect=SystemExit(0)):
            with patch.object(sys, "argv", ["ollama_usage", "--daemon", "--widget"]):
                try:
                    cli.main()
                except SystemExit:
                    pass
                call_kwargs = mock_popen.call_args[1]
                assert call_kwargs["stdin"] == subprocess.DEVNULL
                assert call_kwargs["stdout"] == subprocess.DEVNULL
                assert call_kwargs["stderr"] == subprocess.DEVNULL


# ---------------------------------------------------------------------------
# Integration: daemon actually detaches and survives
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform.startswith("win"), reason="daemon only on POSIX")
class TestWrapperDaemonIntegration:

    def test_daemon_starts_detached_and_killall(self):
        """--daemon must return immediately, leave process running, killable via pkill."""
        subprocess.run(["pkill", "-f", "ollama_usage.*autorefresh"], capture_output=True, timeout=5)
        time.sleep(0.3)

        start = time.time()
        result = subprocess.run(
            ["/home/fmann/sbin/ollama_usage", "--damon", "--autorefresh", "60", "--cookie", "dummy", "--quiet"],
            capture_output=True, text=True, timeout=5
        )
        elapsed = time.time() - start
        assert elapsed < 3.0, f"daemon should not block, took {elapsed}s"
        assert "daemon started" in result.stdout + result.stderr
        assert "killall" in result.stdout + result.stderr
        time.sleep(1.0)
        ps = subprocess.run(["pgrep", "-f", "ollama_usage.*autorefresh"], capture_output=True, text=True, timeout=5)
        assert ps.stdout.strip() != "", f"daemon not found: {ps.stdout}"

        # Kill
        subprocess.run(["pkill", "-f", "ollama_usage.*autorefresh"], capture_output=True, timeout=5)
        time.sleep(0.8)
        ps2 = subprocess.run(["pgrep", "-f", "ollama_usage.*autorefresh"], capture_output=True, text=True, timeout=5)
        if ps2.stdout.strip():
            subprocess.run(["pkill", "-9", "-f", "ollama_usage.*autorefresh"], capture_output=True, timeout=5)
            time.sleep(0.5)
        # Final cleanup
        subprocess.run(["pkill", "-9", "-f", "ollama_usage.*autorefresh"], capture_output=True, timeout=5)

    def test_daemon_terminal_can_close(self):
        """Daemon should survive after parent exits (detached via start_new_session)."""
        subprocess.run(["pkill", "-f", "ollama_usage.*autorefresh"], capture_output=True, timeout=5)
        time.sleep(0.2)
        result = subprocess.run(
            ["/home/fmann/sbin/ollama_usage", "--daemon", "--autorefresh", "60", "--cookie", "dummy", "--quiet"],
            capture_output=True, text=True, timeout=5
        )
        assert "daemon started" in result.stdout + result.stderr
        time.sleep(1.0)
        ps = subprocess.run(["pgrep", "-f", "ollama_usage.*autorefresh"], capture_output=True, text=True, timeout=5)
        assert ps.stdout.strip() != "", "daemon should be running"
        # Cleanup
        subprocess.run(["pkill", "-9", "-f", "ollama_usage.*autorefresh"], capture_output=True, timeout=5)
        time.sleep(0.5)
