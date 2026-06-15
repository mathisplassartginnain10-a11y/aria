"""Smart home via Home Assistant (master-doc §5.1 — stub)."""

from __future__ import annotations

import logging

import requests
import yaml

import app_paths

logger = logging.getLogger(__name__)


def _config() -> dict:
    try:
        with app_paths.config_path().open("r", encoding="utf-8") as f:
            return yaml.safe_load(f).get("home_assistant", {}) or {}
    except Exception:
        return {}


def is_enabled() -> bool:
    cfg = _config()
    return bool(cfg.get("enabled") and cfg.get("url") and cfg.get("token"))


def call_service(domain: str, service: str, entity_id: str) -> str:
    cfg = _config()
    if not is_enabled():
        return "Home Assistant non configuré dans config.yaml."
    url = f"{cfg['url'].rstrip('/')}/api/services/{domain}/{service}"
    headers = {"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json"}
    try:
        r = requests.post(url, json={"entity_id": entity_id}, headers=headers, timeout=10)
        r.raise_for_status()
        return f"Service {domain}.{service} appelé sur {entity_id}."
    except Exception as exc:
        logger.error("Home Assistant error: %s", exc)
        return f"Erreur Home Assistant : {exc}"
