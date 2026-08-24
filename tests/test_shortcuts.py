"""Tests for ollama_usage.shortcuts (shared keyboard shortcuts)."""

from __future__ import annotations

from unittest.mock import MagicMock

from ollama_usage import shortcuts


def test_bind_quit_binds_every_quit_key() -> None:
    target = MagicMock()
    callback = lambda _e: None  # noqa: E731

    shortcuts.bind_quit(target, callback)

    bound = {c.args[0] for c in target.bind.call_args_list}
    assert bound == set(shortcuts.QUIT_KEYS)


def test_quit_keys_are_defined_once() -> None:
    assert "<Control-q>" in shortcuts.QUIT_KEYS
    assert "<Control-Q>" in shortcuts.QUIT_KEYS
