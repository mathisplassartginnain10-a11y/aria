"""Mode focus / ne pas déranger (master-doc §3.6)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import yaml

import app_paths

logger = logging.getLogger(__name__)


def _load_config() -> dict:
    with app_paths.config_path().open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_config(cfg: dict) -> None:
    with app_paths.config_path().open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def is_focus_active() -> bool:
    cfg = _load_config()
    if not cfg.get("focus_mode", False):
        return False
    until = cfg.get("focus_mode_until")
    if until:
        try:
            if datetime.fromisoformat(str(until)) < datetime.now():
                set_focus_mode(False)
                return False
        except ValueError:
            pass
    return True


def set_focus_mode(enabled: bool, duration_minutes: int | None = None) -> None:
    cfg = _load_config()
    cfg["focus_mode"] = enabled
    if enabled and duration_minutes:
        until = datetime.now() + timedelta(minutes=int(duration_minutes))
        cfg["focus_mode_until"] = until.isoformat()
    else:
        cfg["focus_mode_until"] = None
    _save_config(cfg)
    logger.info("Mode focus: %s", "activé" if enabled else "désactivé")
    try:
        import ui_bridge as ui

        ui.update_focus_indicator(enabled)
    except Exception:
        pass
