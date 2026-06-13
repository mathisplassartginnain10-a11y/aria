import copy
import json
import logging

from actions import apps, system
import app_paths

logger = logging.getLogger(__name__)

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

_active_preset: str | None = None


def _normalize_key(key: str) -> str:
    return _ALIASES.get(key.lower().strip(), key.lower().strip())


def _load_custom_presets() -> dict:
    try:
        state_path = app_paths.data_dir() / "ui_state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            custom = state.get("presets", {})
            if isinstance(custom, dict):
                return custom
    except Exception:
        logger.debug("Chargement presets personnalisés impossible", exc_info=True)
    return {}


def _resolve_preset(key: str) -> tuple[dict | None, str]:
    name = _normalize_key(key)
    base = PRESETS.get(name)
    if not base:
        return None, name
    preset = copy.deepcopy(base)
    custom = _load_custom_presets().get(name, {})
    if isinstance(custom, dict) and custom:
        preset.update(custom)
    return preset, name


def _as_app_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def list_presets() -> list[str]:
    return list(PRESETS.keys())


def get_active_preset() -> str | None:
    return _active_preset


def get_merged_presets() -> dict[str, dict]:
    merged: dict[str, dict] = {}
    custom = _load_custom_presets()
    for key, base in PRESETS.items():
        item = copy.deepcopy(base)
        if isinstance(custom.get(key), dict):
            item.update(custom[key])
        merged[key] = item
    return merged


def create_preset(name: str, config: dict) -> str:
    key = _normalize_key(name)
    try:
        state_path = app_paths.data_dir() / "ui_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state: dict = {}
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
        presets = state.get("presets", {})
        if not isinstance(presets, dict):
            presets = {}
        presets[key] = config
        state["presets"] = presets
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        return f"Preset {key} enregistré."
    except Exception:
        logger.exception("Erreur création preset")
        return f"Erreur lors de l'enregistrement du preset {key}."


def activate(key: str) -> str:
    global _active_preset

    preset, name = _resolve_preset(key)
    if not preset:
        return f"Preset {key} introuvable"

    _active_preset = name

    for app in _as_app_list(preset.get("apps_open")):
        try:
            apps.launch(app)
        except Exception:
            logger.debug("Impossible d'ouvrir %s", app, exc_info=True)

    for app in _as_app_list(preset.get("apps_close")):
        try:
            apps.close(app)
        except Exception:
            logger.debug("Impossible de fermer %s", app, exc_info=True)

    if "volume" in preset and preset["volume"] is not None and preset["volume"] != "":
        try:
            system.set_volume(preset["volume"])
        except Exception:
            logger.debug("Réglage volume impossible", exc_info=True)

    if "brightness" in preset and preset["brightness"] is not None and preset["brightness"] != "":
        try:
            system.set_brightness(preset["brightness"])
        except Exception:
            logger.debug("Réglage luminosité impossible", exc_info=True)

    return preset.get("message", f"Mode {name} activé")


def deactivate() -> str:
    global _active_preset
    _active_preset = None
    return "Mode désactivé."
