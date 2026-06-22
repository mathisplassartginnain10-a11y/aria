import copy
import json
import logging
import re

import yaml

from actions import apps, system
import app_paths

logger = logging.getLogger(__name__)

# Modes par défaut (libellé + icône + valeurs de repli). La config.yaml et l'éditeur
# UI viennent par-dessus — voir get_merged_presets().
PRESETS: dict[str, dict] = {
    "vol": {
        "label": "Vol",
        "icon": "✈",
        "apps_open": ["msfs"],
        "apps_close": ["discord", "spotify"],
        "volume": 50,
        "message": "Mode vol activé. MSFS en cours de lancement.",
    },
    "etude": {
        "label": "Étude",
        "icon": "📚",
        "apps_open": ["cursor"],
        "apps_close": ["discord", "steam", "spotify"],
        "volume": 30,
        "message": "Mode étude activé. Concentration maximale.",
    },
    "gaming": {
        "label": "Gaming",
        "icon": "🎮",
        "apps_open": ["steam", "discord"],
        "apps_close": [],
        "volume": 80,
        "message": "Mode gaming activé.",
    },
    "detente": {
        "label": "Détente",
        "icon": "🎵",
        "apps_open": ["spotify", "discord"],
        "apps_close": [],
        "volume": 60,
        "message": "Mode détente activé.",
    },
    "nuit": {
        "label": "Nuit",
        "icon": "🌙",
        "apps_close": ["discord", "steam", "spotify", "chrome"],
        "volume": 15,
        "brightness": 20,
        "message": "Mode nuit activé. Bonne nuit.",
    },
}

_ALIASES = {
    "étude": "etude",
    "etude": "etude",
    "vol": "vol",
    "gaming": "gaming",
    "détente": "detente",
    "detente": "detente",
    "nuit": "nuit",
}

def _normalize_key(key: str) -> str:
    return _ALIASES.get(key.lower().strip(), key.lower().strip())


# ---------------------------------------------------------------------------
# Sources de modes : DÉFAUTS (PRESETS) < config.yaml < customs UI (ui_state.json)
# ---------------------------------------------------------------------------

def _state_path():
    return app_paths.data_dir() / "ui_state.json"


def _load_ui_state() -> dict:
    try:
        path = _state_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        logger.debug("Lecture ui_state.json impossible", exc_info=True)
    return {}


def _patch_ui_state(updates: dict) -> None:
    """Met à jour quelques clés de ui_state.json sans écraser le reste (ex: presets)."""
    try:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _load_ui_state()
        data.update(updates)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.exception("Écriture ui_state.json impossible")


def _load_custom_presets() -> dict:
    custom = _load_ui_state().get("presets", {})
    return custom if isinstance(custom, dict) else {}


def _load_config_presets() -> dict:
    """Lit la section `presets:` de config.yaml (jusqu'ici ignorée)."""
    try:
        with app_paths.config_path().open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        presets = cfg.get("presets", {})
        if isinstance(presets, dict):
            return {_normalize_key(k): v for k, v in presets.items() if isinstance(v, dict)}
    except Exception:
        logger.debug("Lecture presets config.yaml impossible", exc_info=True)
    return {}


def _as_app_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def get_preset_display(key: str) -> tuple[str, str]:
    """Retourne (icon, name) d'un preset depuis la config fusionnée."""
    preset = get_merged_presets().get(_normalize_key(key), {})
    icon = preset.get("icon", "⚙️")
    name = preset.get("name") or preset.get("label", key.capitalize())
    return icon, name


def get_merged_presets() -> dict[str, dict]:
    """Fusionne défauts + config.yaml + customs UI. Tous tes modes, une seule source."""
    config = _load_config_presets()
    custom = _load_custom_presets()
    keys = list(PRESETS.keys())
    for k in list(config.keys()) + list(custom.keys()):
        if k not in keys:
            keys.append(k)

    merged: dict[str, dict] = {}
    for key in keys:
        item = copy.deepcopy(PRESETS.get(key, {}))
        if isinstance(config.get(key), dict):
            item.update(config[key])
        if isinstance(custom.get(key), dict):
            item.update(custom[key])
        display_name = item.get("name") or item.get("label") or PRESETS.get(key, {}).get("label", key.capitalize())
        item["name"] = display_name
        item["label"] = display_name
        item.setdefault("icon", PRESETS.get(key, {}).get("icon", "⚙️"))
        merged[key] = item
    return merged


def list_presets() -> list[str]:
    return list(get_merged_presets().keys())


def match_in_text(text: str) -> str | None:
    """Retrouve un mode mentionné dans une phrase (gère les accents, plus long d'abord)."""
    t = text.lower()
    candidates: dict[str, str] = {k: k for k in get_merged_presets()}
    candidates.update(_ALIASES)
    for k, preset in get_merged_presets().items():
        for field in ("name", "label"):
            val = str(preset.get(field) or "").strip().lower()
            if len(val) >= 3:
                candidates[val] = k
    for token in sorted(candidates, key=len, reverse=True):
        if len(token) >= 3 and re.search(rf"\b{re.escape(token)}\b", t):
            return _normalize_key(candidates[token])
    return None


def get_active_preset() -> str | None:
    return _load_ui_state().get("active_preset")


def _opened_by_mode() -> list[str]:
    opened = _load_ui_state().get("active_preset_opened", [])
    return [str(a) for a in opened] if isinstance(opened, list) else []


def create_preset(name: str, config: dict) -> str:
    key = _normalize_key(name)
    try:
        custom = _load_custom_presets()
        custom[key] = config
        _patch_ui_state({"presets": custom})
        return f"Preset {key} enregistré."
    except Exception:
        logger.exception("Erreur création preset")
        return f"Erreur lors de l'enregistrement du preset {key}."


def activate(key: str) -> str:
    name = _normalize_key(key)
    icon, display_name = get_preset_display(name)
    merged = get_merged_presets()
    preset = merged.get(name)
    if not preset:
        dispo = ", ".join(merged.keys())
        return f"Mode « {key} » introuvable. Disponibles : {dispo}."

    new_open = _as_app_list(preset.get("apps_open"))
    new_open_lower = {a.lower() for a in new_open}

    # Fermetures : apps_close explicites + apps ouvertes par le mode précédent
    # qui ne font pas partie du nouveau mode (transition propre).
    to_close = _as_app_list(preset.get("apps_close"))
    for app in _opened_by_mode():
        if app.lower() not in new_open_lower and app not in to_close:
            to_close.append(app)
    for app in to_close:
        try:
            entry = apps.find_app(app)
            target = entry["name"] if entry else app
            apps.close(target)
        except Exception:
            logger.debug("Fermeture %s impossible", app, exc_info=True)

    # Ouvertures (avec retour sur ce qui a réellement démarré).
    opened_ok: list[str] = []
    failed: list[str] = []
    for app in new_open:
        try:
            entry = apps.find_app(app)
            if not entry:
                failed.append(app)
                continue
            res = apps.launch(entry["name"])
        except Exception:
            res = "erreur"
            logger.debug("Lancement %s impossible", app, exc_info=True)
        label = entry["name"] if entry else app
        (opened_ok if "lancé" in res.lower() else failed).append(label)

    if preset.get("volume") not in (None, ""):
        try:
            system.set_volume(preset["volume"])
        except Exception:
            logger.debug("Réglage volume impossible", exc_info=True)

    if preset.get("brightness") not in (None, ""):
        try:
            system.set_brightness(preset["brightness"])
        except Exception:
            logger.debug("Réglage luminosité impossible", exc_info=True)

    _patch_ui_state({"active_preset": name, "active_preset_opened": opened_ok})

    message = preset.get("message") or f"Mode {icon} {display_name} activé."
    details: list[str] = []
    if opened_ok:
        details.append("ouvert : " + ", ".join(opened_ok))
    if failed:
        details.append("introuvable : " + ", ".join(failed))
    return message + (" (" + " ; ".join(details) + ")" if details else "")


def deactivate() -> str:
    name = get_active_preset()
    closed: list[str] = []
    for app in _opened_by_mode():
        try:
            if "fermé" in apps.close(app).lower():
                closed.append(app)
        except Exception:
            logger.debug("Fermeture %s impossible", app, exc_info=True)

    _patch_ui_state({"active_preset": None, "active_preset_opened": []})

    if name:
        base = f"Mode {name} désactivé."
    else:
        base = "Aucun mode actif."
    return base + (" Fermé : " + ", ".join(closed) + "." if closed else "")
