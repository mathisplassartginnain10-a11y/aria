"""
Intégration Nexus — assistant de code local (type Cursor).
Module préparé, pas encore fonctionnel — Nexus n'est pas encore déployé.
"""

import logging

import requests
import yaml

import app_paths

logger = logging.getLogger(__name__)


def _get_config() -> dict:
    try:
        with app_paths.config_path().open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return cfg.get("nexus", {})
    except Exception:
        return {}


def is_enabled() -> bool:
    return _get_config().get("enabled", False)


def is_available() -> bool:
    """Vérifie si Nexus répond à son endpoint."""
    cfg = _get_config()
    if not cfg.get("enabled"):
        return False
    try:
        endpoint = str(cfg.get("endpoint", "")).rstrip("/")
        resp = requests.get(f"{endpoint}/ping", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def send_prompt(prompt: str) -> str:
    """Envoie un prompt à Nexus. Retourne un message d'erreur si non disponible."""
    cfg = _get_config()
    if not cfg.get("enabled"):
        return "Nexus n'est pas activé. Configure-le dans config.yaml."
    if not is_available():
        return "Nexus n'est pas accessible. Vérifie qu'il tourne sur " + cfg.get("endpoint", "")

    try:
        endpoint = str(cfg.get("endpoint", "")).rstrip("/")
        headers = {}
        if cfg.get("api_key"):
            headers["Authorization"] = f"Bearer {cfg['api_key']}"
        resp = requests.post(
            f"{endpoint}/prompt",
            json={"prompt": prompt},
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("response", "Réponse vide de Nexus")
    except Exception as exc:
        logger.error("Erreur Nexus: %s", exc)
        return f"Erreur de communication avec Nexus: {exc}"
