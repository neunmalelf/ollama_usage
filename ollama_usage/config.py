"""Per-user configuration directory and legacy settings migration.

All settings files live in ``~/.config/ollama_usage/`` (created on the
first program start). Dotted settings files from earlier releases
(``~/.ollama-usage-gui.cfg``, ``~/.ollama-usage-widget.cfg``) are moved
there once, on the first start after the upgrade.
"""

from __future__ import annotations

import logging
import pathlib
import shutil

logger = logging.getLogger(__name__)

#: Per-user configuration directory (created on first program start).
CONFIG_DIR = pathlib.Path.home() / ".config" / "ollama_usage"

#: Settings file names inside CONFIG_DIR.
GUI_CFG = CONFIG_DIR / "gui.cfg"
WIDGET_CFG = CONFIG_DIR / "widget.cfg"

#: Dotted settings files from earlier releases, directly in ``$HOME``.
LEGACY_FILES: tuple[tuple[pathlib.Path, pathlib.Path], ...] = (
    (pathlib.Path.home() / ".ollama-usage-gui.cfg", GUI_CFG),
    (pathlib.Path.home() / ".ollama-usage-widget.cfg", WIDGET_CFG),
)


def ensure_config_dir() -> None:
    """Create ``CONFIG_DIR`` when missing (idempotent, best-effort)."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Could not create %s: %s", CONFIG_DIR, exc)


def migrate_legacy_configs() -> None:
    """Move dotted settings files from ``$HOME`` into ``CONFIG_DIR``."""
    ensure_config_dir()
    for legacy, current in LEGACY_FILES:
        if not legacy.is_file():
            continue
        if current.exists():
            logger.debug("Legacy %s ignored; %s exists", legacy, current)
            continue
        try:
            shutil.move(str(legacy), str(current))
            logger.debug("Migrated %s -> %s", legacy, current)
        except OSError as exc:
            logger.warning("Could not migrate %s: %s", legacy, exc)