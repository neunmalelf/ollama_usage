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


def test_bind_keys_binds_every_given_key() -> None:
    target = MagicMock()
    callback = lambda _e: None  # noqa: E731

    shortcuts.bind_keys(target, ("<Alt-r>", "<Alt-d>"), callback)

    bound = {c.args[0] for c in target.bind.call_args_list}
    assert bound == {"<Alt-r>", "<Alt-d>"}
    for call in target.bind.call_args_list:
        assert call.args[1] is callback


def test_refresh_keys_are_defined_once() -> None:
    assert shortcuts.REFRESH_KEYS == ("<Alt-r>", "<Alt-Key-r>")


def test_close_keys_are_defined_once() -> None:
    assert shortcuts.CLOSE_KEYS == ("<Alt-o>", "<Alt-Key-o>", "<Return>", "<Escape>")


def test_dark_keys_are_defined_once() -> None:
    assert shortcuts.DARK_KEYS == ("<Alt-d>", "<Alt-Key-d>")


def test_bind_quit_reuses_bind_keys() -> None:
    target = MagicMock()
    callback = lambda _e: None  # noqa: E731

    shortcuts.bind_quit(target, callback)

    bound = [c.args[0] for c in target.bind.call_args_list]
    assert bound == list(shortcuts.QUIT_KEYS)
