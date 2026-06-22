"""Profils multi-utilisateurs (Sprint G)."""
from __future__ import annotations

import copy
import logging
import re

import yaml

import app_paths

logger = logging.getLogger(__name__)

_DEFAULT_PROFILE = {
    "name": "Mathis",
    "firstname": "Mathis",
    "hello_text": "",
    "sub_text": "",
    "theme": "slate",
    "wallpaper": "aurora",
    "tts_enabled": False,
    "tts_rate": 0,
    "system_prompt_extra": "",
    "models": {
        "intent": "llama3.2:1b",
        "fast": "llama3.1:8b-instruct-q8_0",
        "heavy": "qwen3:14b",
        "vision": "minicpm-v:latest",
    },
}


def _load_config() -> dict:
    with app_paths.config_path().open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_config(cfg: dict) -> None:
    with app_paths.config_path().open("w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _normalize_key(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", name.lower().strip().replace(" ", "_"))


def _fuzzy_match_profile(name: str, profiles: dict) -> str | None:
    query = name.lower().strip()
    if not query:
        return None
    q_key = _normalize_key(query)
    if q_key in profiles:
        return q_key
    for key, prof in profiles.items():
        if query in key or key in query:
            return key
        for field in ("name", "firstname"):
            val = str(prof.get(field, "")).lower()
            if val and (query in val or val in query):
                return key
        if q_key and (q_key in key or key.startswith(q_key[:3])):
            return key
    return None


def get_all_profiles() -> dict:
    cfg = _load_config()
    profiles = cfg.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        return {"mathis": copy.deepcopy(_DEFAULT_PROFILE)}
    return profiles


def get_current_user_key() -> str:
    cfg = _load_config()
    return str(cfg.get("current_user") or "mathis")


def get_current_profile() -> dict:
    profiles = get_all_profiles()
    key = get_current_user_key()
    prof = profiles.get(key)
    if not isinstance(prof, dict):
        prof = copy.deepcopy(_DEFAULT_PROFILE)
    prof = copy.deepcopy(prof)
    prof["_key"] = key
    return prof


def _apply_profile_to_runtime(prof: dict) -> None:
    """Applique thème, modèles et TTS du profil actif."""
    try:
        import llm
        models = prof.get("models") or {}
        for role in ("intent", "fast", "heavy", "vision"):
            if models.get(role):
                llm.set_model_role(role, str(models[role]))
        llm._refresh_system_prompt()
    except Exception:
        logger.debug("apply profile models failed", exc_info=True)
    try:
        import tts
        tts.set_enabled(bool(prof.get("tts_enabled", True)))
        rate = prof.get("tts_rate")
        if rate is not None:
            tts.set_rate(rate)
    except Exception:
        pass


def switch_profile(name: str) -> dict:
    cfg = _load_config()
    profiles = get_all_profiles()
    if not isinstance(cfg.get("profiles"), dict):
        cfg["profiles"] = profiles

    key = _fuzzy_match_profile(name, profiles)
    if not key:
        return {"success": False, "error": f"Profil « {name} » introuvable"}

    cfg["current_user"] = key
    _save_config(cfg)
    prof = copy.deepcopy(profiles[key])
    prof["_key"] = key
    _apply_profile_to_runtime(prof)

    try:
        import ui_bridge as ui
        ui.emit("profile_changed", prof)
    except Exception:
        pass

    firstname = prof.get("firstname") or prof.get("name") or key
    return {"success": True, "profile": prof, "message": f"Bonjour {firstname} ! Profil chargé."}


def create_profile(name: str) -> dict:
    cfg = _load_config()
    profiles = get_all_profiles()
    key = _normalize_key(name)
    if not key:
        return {"success": False, "error": "Nom de profil invalide"}
    if key in profiles:
        return {"success": False, "error": "Ce profil existe déjà"}

    prof = copy.deepcopy(_DEFAULT_PROFILE)
    prof["name"] = name.strip()
    prof["firstname"] = name.strip()
    profiles[key] = prof
    cfg["profiles"] = profiles
    if "current_user" not in cfg:
        cfg["current_user"] = key
    _save_config(cfg)
    return {"success": True, "key": key, "profile": prof}


def update_profile(key: str, field: str, value) -> dict:
    cfg = _load_config()
    profiles = get_all_profiles()
    if key not in profiles:
        return {"success": False, "error": "Profil introuvable"}
    profiles[key][field] = value
    cfg["profiles"] = profiles
    _save_config(cfg)
    if key == get_current_user_key():
        _apply_profile_to_runtime(profiles[key])
    return {"success": True}


def delete_profile(name: str) -> dict:
    cfg = _load_config()
    profiles = get_all_profiles()
    key = _fuzzy_match_profile(name, profiles) or _normalize_key(name)
    current = get_current_user_key()
    if key == current:
        return {"success": False, "error": "Impossible de supprimer le profil actif"}
    if key not in profiles:
        return {"success": False, "error": "Profil introuvable"}
    if len(profiles) <= 1:
        return {"success": False, "error": "Au moins un profil requis"}
    del profiles[key]
    cfg["profiles"] = profiles
    _save_config(cfg)
    return {"success": True}


def match_profile_in_text(text: str) -> str | None:
    """Extrait un nom de profil depuis une phrase vocale."""
    t = text.lower()
    patterns = (
        r"passe en mode\s+(.+)",
        r"switch sur\s+(.+)",
        r"change de profil\s+(.+)",
        r"profil\s+(.+)",
        r"mode\s+(.+)",
    )
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            name = m.group(1).strip().strip("?.!")
            for noise in ("s'il te plaît", "stp", "merci", "maintenant"):
                name = name.replace(noise, "").strip()
            return name
    return None
