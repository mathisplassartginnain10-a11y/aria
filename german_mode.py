"""Mode allemand immersif (master-doc §4.7)."""

from __future__ import annotations

import logging

import yaml

import app_paths

logger = logging.getLogger(__name__)


def _load_config() -> dict:
    with app_paths.config_path().open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_config(cfg: dict) -> None:
    with app_paths.config_path().open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def is_german_mode_active() -> bool:
    return bool(_load_config().get("german_mode", False))


def set_german_mode(enabled: bool) -> None:
    cfg = _load_config()
    cfg["german_mode"] = enabled
    _save_config(cfg)
    logger.info("Mode allemand: %s", "activé" if enabled else "désactivé")
