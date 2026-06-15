"""Intégrations réseaux sociaux — stub (master-doc §5.2)."""

from __future__ import annotations

import logging

import yaml

import app_paths

logger = logging.getLogger(__name__)


def _social_cfg() -> dict:
    try:
        with app_paths.config_path().open("r", encoding="utf-8") as f:
            return yaml.safe_load(f).get("social", {}) or {}
    except Exception:
        return {}


def read_discord_unread() -> str:
    cfg = _social_cfg()
    token = cfg.get("discord_bot_token", "")
    if not token:
        return (
            "Discord non configuré. Ajoute social.discord_bot_token dans config.yaml "
            "(bot personnel, pas le compte utilisateur)."
        )
    return "Lecture Discord non implémentée — configure un bot et un channel_id dans config.yaml."


def read_telegram_messages() -> str:
    cfg = _social_cfg()
    token = cfg.get("telegram_bot_token", "")
    if not token:
        return "Telegram non configuré. Ajoute social.telegram_bot_token dans config.yaml."
    return "Lecture Telegram non implémentée — configure telegram_chat_id dans config.yaml."
