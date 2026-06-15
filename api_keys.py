"""Registre centralisé des clés API (spec v15 / master-doc)."""

from __future__ import annotations

import logging
from typing import Any

import yaml

import app_paths

logger = logging.getLogger(__name__)

_KEY_MAP = {
    "openweather": "openweather_api_key",
    "newsapi": "newsapi_key",
    "avwx": "avwx_api_key",
}


def _load_config() -> dict[str, Any]:
    try:
        with app_paths.config_path().open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        logger.exception("Erreur lecture config pour api_keys")
        return {}


def get_key(name: str) -> str:
    cfg = _load_config()
    field = _KEY_MAP.get(name, name)
    return str(cfg.get(field, "") or "").strip()


def check_status(name: str) -> dict[str, str]:
    key = get_key(name)
    if not key:
        return {"status": "missing", "message": f"Clé {name} non configurée dans config.yaml"}
    return {"status": "ok", "message": f"Clé {name} présente"}
