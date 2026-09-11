"""Tests for ollama_usage.config (config dir + legacy migration)."""

from __future__ import annotations

import ollama_usage.config as config


def test_ensure_config_dir_creates(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    config.ensure_config_dir()
    assert (tmp_path / "cfg").is_dir()


def test_ensure_config_dir_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    config.ensure_config_dir()
    config.ensure_config_dir()
    assert (tmp_path / "cfg").is_dir()


def test_migrate_moves_legacy_files(tmp_path, monkeypatch) -> None:
    legacy = tmp_path / ".ollama-usage-gui.cfg"
    legacy.write_text("[gui]\ndarkmode = False\n", encoding="utf-8")
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setattr(config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(
        config, "LEGACY_FILES", ((legacy, cfg_dir / "gui.cfg"),)
    )
    config.migrate_legacy_configs()
    assert not legacy.exists()
    assert (cfg_dir / "gui.cfg").read_text(encoding="utf-8") == (
        "[gui]\ndarkmode = False\n"
    )


def test_migrate_never_overwrites_existing(tmp_path, monkeypatch) -> None:
    legacy = tmp_path / ".legacy.cfg"
    legacy.write_text("legacy", encoding="utf-8")
    current = tmp_path / "current.cfg"
    current.write_text("current", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "LEGACY_FILES", ((legacy, current),))
    config.migrate_legacy_configs()
    assert current.read_text(encoding="utf-8") == "current"
    # Legacy file left untouched when a current file already exists.
    assert legacy.exists()


def test_migrate_without_legacy_is_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(config, "LEGACY_FILES", ())
    config.migrate_legacy_configs()
    assert (tmp_path / "cfg").is_dir()