import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import requests
import yaml

import memory
import memory_engine
import sounds
import tts
import ui
import app_paths
from actions import (
    apps,
    aviation,
    aviation_expert,
    browser,
    calendar_action,
    google_calendar,
    clipboard,
    cursor_control,
    nexus_control,
    files,
    git,
    math_expert,
    news,
    presets,
    system,
    timer,
    translator,
    weather,
    web_search,
)
from actions.web_search import search_news, search_web, summarize_with_ollama

logger = logging.getLogger(__name__)

_CONFIG_PATH = app_paths.config_path()
with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

MODELS: dict[str, str] = {
    "fast": "llama3.1:8b-instruct-q8_0",
    "medium": "llama3.1:8b-instruct-q8_0",
    "heavy": "qwen3:14b",
    "intent": "llama3.2:1b",
    "vision": "minicpm-v",
}

_cfg_models = (_config.get("models") or {}) if isinstance(_config, dict) else {}
for _role, _name in _cfg_models.items():
    if _role in MODELS and _name:
        MODELS[_role] = str(_name)

KNOWN_INTENTS = [
    'lancer_app', 'fermer_app', 'volume', 'meteo', 'heure_date', 'minuteur',
    'search_web', 'search_news', 'aviation_metar', 'aviation_taf',
    'math_calculate', 'question_libre', 'browser_open_site',
    'browser_search_in_site', 'preset',
]

MODEL: str = _config.get("model", MODELS["heavy"])
MODEL_FAST: str = _config.get("model_fast", MODELS["fast"])
MODEL_HEAVY: str = _config.get("model_heavy", MODELS["heavy"])
# Legacy UI/API — le rôle « code » est assuré par Nexus (fallback : MODEL_HEAVY).
MODEL_CODE: str = _config.get("model_code", MODELS["heavy"])
VISION_MODEL: str = _config.get("vision_model", "minicpm-v")
INTENT_MODEL: str = _config.get("intent_model", MODELS["intent"])
# Modèle de CONVERSATION : rapide par défaut (latence faible pour parler en direct).
# Mets "qwen3:14b" dans config (chat_model) si tu préfères la qualité à la vitesse.
CHAT_MODEL: str = _config.get("chat_model", MODEL_FAST)
# Garde le modèle chargé en VRAM entre deux requêtes -> pas de cold start.
OLLAMA_KEEP_ALIVE: str = str(_config.get("ollama_keep_alive", "30m"))
# Modèle de RÉFLEXION : activé seulement pour les questions complexes (raisonnement profond).
REASONING_MODEL: str = _config.get("reasoning_model", MODEL_HEAVY)


def _load_ui_state() -> dict:
    path = app_paths.data_dir() / "ui_state.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_forced_model() -> str | None:
    active = _config.get("active_model")
    if active and active != "auto":
        return str(active)
    active = _load_ui_state().get("active_model")
    if active and active != "auto":
        return str(active)
    return None


def _load_auto_routing() -> bool:
    ui_state = _load_ui_state()
    if "auto_routing" in ui_state:
        return bool(ui_state["auto_routing"])
    return bool(_config.get("auto_routing", True))


# Modèle FORCÉ par l'utilisateur via le sélecteur (comme Claude). None = mode « Auto »
# (micro-routeur + chat rapide + escalade réflexion automatique selon la question).
FORCED_MODEL: str | None = _load_forced_model()
AUTO_ROUTING: bool = _load_auto_routing()


def _atomic_write(path, text: str) -> None:
    """Écrit via un fichier temporaire puis os.replace (atomique).

    Empêche tout fichier tronqué/partiel si l'écriture est interrompue, et évite
    qu'un autre process lise un fichier à 0 octet pendant l'écriture.
    """
    import os
    import tempfile

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _patch_config(updates: dict) -> None:
    path = app_paths.config_path()
    try:
        with path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except OSError:
        cfg = None
    # Garde anti-corruption : ne JAMAIS réécrire config.yaml à partir d'une lecture
    # vide (fichier momentanément tronqué par une écriture concurrente). Mieux vaut
    # rater une synchro de réglage que d'écraser toute la config.
    if not isinstance(cfg, dict) or not cfg:
        logger.warning("Patch config ignoré : lecture vide/illisible de config.yaml")
        return
    cfg.update(updates)
    _atomic_write(path, yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))


def _patch_ui_state(updates: dict) -> None:
    path = app_paths.data_dir() / "ui_state.json"
    data = _load_ui_state()
    data.update(updates)
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))


def _warmup_model_async(model: str) -> None:
    try:
        import ollama_manager

        ollama_manager.warmup_model(model)
    except Exception as exc:
        logger.warning("Warmup modèle %s échoué: %s", model, exc)


def set_active_model(model_name: str) -> None:
    """Applique le choix du sélecteur en-tête et persiste (config + ui_state)."""
    global FORCED_MODEL
    normalized = (model_name or "auto").strip()
    FORCED_MODEL = None if normalized == "auto" else normalized
    _patch_config({"active_model": normalized})
    _patch_ui_state({"active_model": normalized})
    logger.info("Modèle actif: %s", normalized)
    target = FORCED_MODEL or CHAT_MODEL
    threading.Thread(target=_warmup_model_async, args=(target,), daemon=True).start()


def apply_model_settings(
    *,
    model_fast: str | None = None,
    model_heavy: str | None = None,
    model_code: str | None = None,
    auto_routing: bool | None = None,
    persist: bool = True,
) -> None:
    """Applique les réglages « Modèles » du panneau settings en live.

    persist=False : applique seulement aux variables en mémoire, SANS réécrire
    config.yaml / ui_state.json (utilisé à l'import — les valeurs viennent déjà
    de ui_state, pas besoin de les réécrire, ce qui évitait les écritures
    concurrentes qui pouvaient tronquer config.yaml)."""
    global MODEL_FAST, MODEL_HEAVY, MODEL_CODE, CHAT_MODEL, REASONING_MODEL, AUTO_ROUTING

    patches: dict = {}
    ui_patches: dict = {}

    if model_fast:
        MODEL_FAST = model_fast
        CHAT_MODEL = model_fast
        patches["model_fast"] = model_fast
        patches["chat_model"] = model_fast
        ui_patches["model_fast"] = model_fast

    if model_heavy:
        MODEL_HEAVY = model_heavy
        REASONING_MODEL = model_heavy
        patches["model_heavy"] = model_heavy
        patches["reasoning_model"] = model_heavy
        ui_patches["model_heavy"] = model_heavy

    if model_code:
        MODEL_CODE = model_code
        patches["model_code"] = model_code
        ui_patches["model_code"] = model_code

    if auto_routing is not None:
        AUTO_ROUTING = bool(auto_routing)
        patches["auto_routing"] = AUTO_ROUTING
        ui_patches["auto_routing"] = AUTO_ROUTING

    if persist and patches:
        _patch_config(patches)
    if persist and ui_patches:
        _patch_ui_state(ui_patches)

    if not FORCED_MODEL and model_fast:
        threading.Thread(target=_warmup_model_async, args=(CHAT_MODEL,), daemon=True).start()


# Au démarrage : synchroniser les réglages « Modèles » sauvegardés dans ui_state.json.
_startup_ui = _load_ui_state()
if _startup_ui:
    apply_model_settings(
        model_fast=_startup_ui.get("model_fast") or None,
        model_heavy=_startup_ui.get("model_heavy") or None,
        model_code=_startup_ui.get("model_code") or None,
        auto_routing=_startup_ui.get("auto_routing") if "auto_routing" in _startup_ui else None,
        persist=False,
    )

HEAVY_KEYWORDS = (
    "calcule",
    "démontre",
    "demontre",
    "résous",
    "resous",
    "intégrale",
    "integrale",
    "dérivée",
    "derivee",
    "équation",
    "equation",
    "probabilité",
    "probabilite",
    "explique en détail",
    "analyse approfondie",
    "architecture",
    "étape par étape",
    "etape par etape",
    "raisonne",
    "compare en détail",
    "code complet",
    "optimise",
    "refactor",
    "rédige",
    "redige",
    "metar",
    "taf",
    "plan de vol",
)

ACTIONS_1B = frozenset({
    "lancer_app",
    "fermer_app",
    "volume",
    "heure_date",
    "minuteur",
    "preset",
    "browser_open_site",
    "browser_youtube_search",
    "browser_search_in_site",
    "meteo",
})
HEAVY_REQUIRED = frozenset({
    "math_derive",
    "math_integrate",
    "math_solve_equation",
    "math_matrix",
    "math_limit",
    "math_proba",
    "aviation_theory",
    "aviation_gonogo",
    "cursor_generate_code",
    "agent_task",
})
SENTENCE_END_RE = re.compile(r"[.!?…]+\s*$")
_stop_stream = threading.Event()
_REASONING_RE = re.compile(
    r"\b(explique|expliques?|pourquoi|analyse[rz]?|compare[rz]?|d[ée]montre[rz]?|raisonne|"
    r"r[ée]fl[ée]chi[ts]?|[ée]tape par [ée]tape|r[ée]sou[ds]|r[ée]soudre|calcule[rz]?|prouve|"
    r"strat[ée]gie|optimise[rz]?|con[çc]ois|architecture|nuances?|implications?|cons[ée]quences?|"
    r"avantages? et inconv[ée]nients?|en d[ée]tail|approfondi[ts]?)\b",
    re.I,
)
# Déclencheurs « info fraîche » -> passe par la recherche web (Ollama + DuckDuckGo).
_CURRENT_INFO_RE = re.compile(
    r"\b(aujourd'?hui|actuel(?:le|lement)?|en ce moment|r[ée]cent[e]?s?|derni[èe]re?s?|"
    r"cette ann[ée]e|202[5-9]|prix de|cours de|score|qui est (?:le|la|l'|actuellement)|"
    r"qui sont|combien co[ûu]te|quoi de neuf|nouveaut[ée]s?)\b",
    re.I,
)
MAX_HISTORY: int = _config["max_history"]
BASE_SYSTEM_PROMPT: str = """Tu es ARIA, l'assistant personnel de Mathi, lycéen en Première à Couëron.
Tu le connais intimement : ses projets (ARIA l'assistant vocal, IMPERO, PPL DR400 à LFRS),
son style de communication direct et ses fautes de frappe caractéristiques.
Tu réponds toujours en tutoiement, directement, sans préambule.
Tu maîtrises : Python, pywebview, Ollama, aviation PPL, maths Première, gaming PC.
Jamais de "Bien sûr !", "Absolument !" ou politesse excessive."""
SYSTEM_PROMPT = BASE_SYSTEM_PROMPT

ACTIONS_SYSTEM_PROMPT = """Tu es ARIA, un assistant vocal Windows en français.

Pour les commandes système, réponds UNIQUEMENT avec ce format strict (pas de texte avant ou après) :

OPEN_APP:<nom>          → ouvrir une application (ex: OPEN_APP:chrome)
CLOSE_APP:<nom>         → fermer une application
SEARCH_WEB:<query>      → recherche Google
OPEN_SITE:<url>         → ouvrir un site web
VOLUME:<0-100>          → régler le volume
SCREENSHOT:             → prendre une capture d'écran
PRESET:<nom>            → activer un preset (vol/etude/gaming/detente/nuit)
METEO:<ville>           → météo d'une ville
TIMER:<secondes>        → démarrer un minuteur
CHAT:<réponse>          → pour tout le reste, répondre normalement

Exemples :
"lance google chrome" → OPEN_APP:chrome
"ouvre youtube" → OPEN_SITE:youtube.com
"volume à 50" → VOLUME:50
"quel temps fait-il à Nantes" → METEO:Nantes
"bonjour comment tu vas" → CHAT:Je vais très bien merci !
"explique moi les intégrales" → CHAT:<explication normale>
"""

ACTION_PREFIXES = (
    "OPEN_APP:",
    "CLOSE_APP:",
    "SEARCH_WEB:",
    "OPEN_SITE:",
    "VOLUME:",
    "SCREENSHOT:",
    "PRESET:",
    "METEO:",
    "TIMER:",
    "CHAT:",
)

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL}/api/generate"
HISTORY_PATH = app_paths.data_dir() / "history.json"

INTENTS = [
    # Maths v3
    "math_calculate", "math_derive", "math_integrate", "math_solve_equation",
    "math_suite", "math_proba", "math_matrix", "math_limit", "math_general",
    # Aviation v3
    "aviation_metar", "aviation_taf", "aviation_notam", "aviation_theory",
    "aviation_checklist", "aviation_nav", "aviation_wind", "aviation_fuel",
    "aviation_gonogo", "aviation_radio",
    # Search v3
    "search_geopolitics", "search_aviation_news", "search_web", "search_news",
    # Cursor v3
    "cursor_open", "cursor_generate_code", "cursor_open_file", "cursor_open_project",
    # Browser v4
    "browser_open_site", "browser_open_url", "ouvrir_site", "browser_search_google", "browser_youtube_search",
    "browser_youtube_control", "browser_spotify", "browser_new_tab", "browser_close_tab",
    "browser_close", "browser_scroll", "browser_read_page", "browser_screenshot",
    "browser_type", "browser_type_send", "browser_type_claude", "cursor_prompt",
    "browser_search_in_site", "browser_search_page",
    # Google Drive
    "drive_create_doc", "drive_write_doc", "drive_search", "drive_open",
    "drive_list", "drive_create_folder", "drive_share",
    # Existants v2
    "lancer_app", "fermer_app", "volume", "luminosite", "veille", "reboot", "shutdown",
    "actu", "meteo", "minuteur", "alarme", "recherche_web", "git", "calcul",
    "traduction", "preset", "clipboard_copy", "clipboard_paste", "ouvrir_fichier",
    "rappel", "question_libre", "blague", "heure_date", "historique", "memoire",
]

SEARCH_INTENTS = frozenset({
    "search_news", "search_geopolitics", "search_aviation_news",
})

DRIVE_INTENTS = frozenset({
    "drive_create_doc", "drive_write_doc", "drive_search", "drive_open",
    "drive_list", "drive_create_folder", "drive_share",
})

FAST_REGEX: dict[str, str] = {
    r"\b(lance|démarre|demarre|start)\b.+": "lancer_app",
    r"\b(ouvre|ouvre-moi)\b.+": "lancer_app",
    r"\b(ferme|quitte|stop|arrête|arrete)\b.+": "fermer_app",
    r"\b(volume|son)\b.+(up|down|monte|baisse|\d+)": "volume",
    r"\b(météo|meteo|température|temperature|temps)\b": "meteo",
    r"\b(quelle heure|quelle date|l'heure|heure qu'il|quel jour)\b": "heure_date",
    r"\b(minuteur|timer|dans \d+ min)\b": "minuteur",
}

FAST_BROWSER_REGEX: list[tuple[str, str]] = [
    (r"(?:ouvre|va sur|navigue vers)\s+(?:le site\s+)?(?:https?://|www\.)\S+", "browser_open_url"),
    (r"(?:ouvre|va sur)\s+(?:youtube|google|github|reddit|wikipedia|netflix|tiktok)\b", "browser_open_site"),
    (r"cherche .+ sur (?:youtube|google|github|reddit|amazon|wikipedia)", "browser_search_in_site"),
    (r"recherche .+ dans (?:le navigateur|chrome|edge)", "search_web"),
    (r"va sur ", "browser_open_site"),
]

INTENT_CATEGORY_MAP: dict[str, str] = {
    "lancer_app": "lancer_app",
    "fermer_app": "fermer_app",
    "volume": "volume",
    "meteo": "meteo",
    "actu": "actu",
    "aviation": "aviation_metar",
    "maths": "math_calculate",
    "code": "cursor_generate_code",
    "recherche": "search_web",
    "question": "question_libre",
    "heure_date": "heure_date",
    "minuteur": "minuteur",
}

# === ROUTING INTELLIGENCE ===

# Actions that NEVER need the LLM — pure function calls
PURE_ACTIONS = frozenset({
    "lancer_app", "fermer_app", "volume", "luminosite", "veille",
    "reboot", "shutdown", "lock", "screenshot", "clipboard_copy",
    "clipboard_paste", "minuteur", "alarme", "preset",
    "browser_open_site", "browser_open_url", "ouvrir_site",
    "browser_youtube_search", "browser_search_in_site", "browser_youtube_control",
    "browser_search_google", "cursor_open", "cursor_open_file", "git",
    "nexus_prompt", "daily_brief", "export_pdf", "focus_mode_on", "focus_mode_off",
    "calendar_today", "calendar_upcoming", "calendar_create", "revision_plan",
    "german_mode_on", "german_mode_off", "run_macro", "smarthome", "social_discord",
})

# Actions that use an external API then summarize with LLM
API_THEN_LLM = frozenset({
    "meteo",
    "aviation_metar",
    "aviation_taf",
    "search_web",
    "search_news",
    "search_geopolitics",
    "search_aviation_news",
    "actu",
    "drive_search",
    "drive_list",
})

# Actions that use API/system only — no LLM
API_ONLY = frozenset({
    "heure_date",
    "browser_open_url",
    "browser_open_site",
    "ouvrir_site",
    "lancer_app",
    "fermer_app",
    "volume",
    "luminosite",
})

# Actions that need full LLM conversation (skip specialized dispatch)
LLM_REQUIRED = frozenset({
    "question_libre", "math_general", "math_calculate", "math_derive",
    "math_integrate", "math_solve_equation", "math_suite", "math_proba",
    "math_matrix", "math_limit",
    "aviation_theory", "aviation_nav", "aviation_gonogo",
    "traduction", "cursor_generate_code", "blague",
})

_history: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
_last_clear_time: float = 0.0

_BROWSER_LAUNCH_SKIP = re.compile(
    r"\b(va sur|visite|youtube|google\b|facebook|instagram|twitter|reddit|github|"
    r"wikipedia|netflix|tiktok|\.com\b|\.fr\b|https?://)",
    re.I,
)

BROWSER_NAMES = r"(?:microsoft\s+edge|google\s+chrome|opera\s+gx|chrome|edge|firefox|opera|brave|vivaldi|navigateur|le navigateur)"
# Verbes d'ouverture, avec variantes « -moi »/« moi » accolées ou séparées.
_OPEN_VERB = r"(?:ouvre-moi|ouvre moi|ouvre|lance-moi|lance moi|lance|d[ée]marre|mets|va sur|navigue vers)"
SITE_OPEN_PATTERN = re.compile(
    rf"{_OPEN_VERB}\s+(.+?)\s+(?:sur|dans|avec)\s+({BROWSER_NAMES})\b",
    re.IGNORECASE,
)
_BROWSER_APP_NAMES = frozenset({
    "chrome", "google chrome", "edge", "microsoft edge",
    "firefox", "opera", "opera gx", "brave", "vivaldi",
    "le navigateur", "navigateur",
})
_SEARCH_BROWSER_NAMES = frozenset({
    "chrome", "edge", "firefox", "opera", "brave", "vivaldi",
    "le navigateur", "navigateur",
})


def _clean_site(site: str) -> str:
    """Retire les amorces « le site / la page » d'un nom de site capturé.

    On ne touche PAS aux articles seuls (« le monde » reste « le monde »,
    sinon on casserait l'alias lemonde.fr)."""
    cleaned = re.sub(
        r"^(?:le |la |l'|mon )?(?:site|page)(?: web)?\s+",
        "",
        site.strip(),
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or site.strip()
# Fichier de code/config — même liste d'extensions que cursor_open_file
_CODE_FILE_RE = re.compile(
    r"([\w./\\-]+\.(?:py|ts|tsx|js|jsx|json|ya?ml|md))\b",
    re.IGNORECASE,
)


def _is_browser_app_name(name: str) -> bool:
    return name.strip().lower() in _BROWSER_APP_NAMES


def _fast_intent(text: str) -> tuple[str, dict] | None:
    """Détecte l'intent + params via regex — latence 0ms."""
    text_lower = text.lower().strip()

    # PRIORITY 1: « ouvre [site] sur/dans/avec [navigateur] » → site, pas le navigateur
    m = SITE_OPEN_PATTERN.search(text_lower)
    if m:
        site, browser_name = _clean_site(m.group(1)), m.group(2).strip()
        return "browser_open_site", {"site": site, "browser": browser_name}

    # PRIORITY 2: « cherche [query] sur [site] »
    m = re.search(r"(?:cherche|recherche|trouve)\s+(.+?)\s+sur\s+(.+)", text_lower)
    if m:
        query, site = m.group(1).strip(), m.group(2).strip()
        if site in _SEARCH_BROWSER_NAMES:
            return "search_web", {"query": query}
        return "browser_search_in_site", {"site": site, "query": query}

    # PRIORITY 2.5: « ferme l'onglet » → onglet navigateur, pas une app nommée "onglet"
    if re.search(r"\bferme\b.*\b(onglet|tab)\b", text_lower):
        return "browser_close_tab", {}

    # PRIORITY 2.7: Nexus (éditeur de code local) — avant lancer_app/navigateur
    if re.search(
        r"(?:demande|envoie)\s+(?:à|a)\s+nexus|envoie\s+ça\s+à\s+nexus|"
        r"nexus\s+(?:fais|fait)\s+",
        text_lower,
    ):
        return "nexus_prompt", {"query": text, "text": text}
    if "nexus" in text_lower:
        if re.search(r"\b(demande|envoie|dis|code|écris|ecris|génère|genere|corrige)\b", text_lower):
            return "nexus_prompt", {"query": text, "text": text}
        if re.search(r"\b(ouvre|lance|démarre|demarre|open|va sur)\b", text_lower):
            file_m = _CODE_FILE_RE.search(text_lower)
            return ("nexus_open", {"path": file_m.group(1)}) if file_m else ("nexus_open", {})

    # PRIORITY 2.8: modes / presets (« mode étude », « active le mode gaming »,
    # « désactive le mode »…). Indispensable pour le mobile qui ne s'appuie que
    # sur le fast-path regex depuis l'optimisation vitesse.
    if re.search(r"\b(?:mode|preset)\b", text_lower):
        if any(
            w in text_lower
            for w in ("désactive", "desactive", "quitte le mode", "sors du mode", "arrête le mode", "arrete le mode")
        ):
            return "preset", {}
        preset_name = presets.match_in_text(text)
        if preset_name:
            return "preset", {"preset": preset_name}

    # PRIORITY 3: « ouvre [cible] » sans navigateur explicite
    m = re.search(r"(?:ouvre-moi|ouvre moi|ouvre|va sur|navigue vers)\s+(.+)", text_lower)
    if m:
        target = m.group(1).strip()
        if _is_browser_app_name(target):
            return "lancer_app", {"app": target}
        # Cible Nexus (éditeur de code maison) → ouvrir dans Nexus, pas le navigateur
        if "nexus" in target:
            file_m = _CODE_FILE_RE.search(text_lower)
            if file_m:
                return "nexus_open", {"path": file_m.group(1)}
            return "nexus_open", {}
        # Cible Cursor ou fichier de code → ouvrir dans Cursor, pas dans le navigateur
        if "cursor" in target or _CODE_FILE_RE.search(target):
            file_m = _CODE_FILE_RE.search(text_lower)
            if file_m:
                return "cursor_open_file", {"path": file_m.group(1)}
            if "projet" in target:
                return "cursor_open_project", {"name": text}
            return "cursor_open", {}
        # « ouvre <app installée> » → lancer l'app (Spotify, Discord, OBS…),
        # y compris « ouvre discord et spotify ». Sinon → site web.
        # resolve_known est RAPIDE (pas de scan disque) pour rester en fast-path.
        if apps.resolve_known(target):
            return "lancer_app", {"app": target}
        return "browser_open_site", {"site": _clean_site(target)}

    for pattern, intent in FAST_BROWSER_REGEX:
        if re.search(pattern, text_lower):
            return intent, {}

    if _BROWSER_LAUNCH_SKIP.search(text_lower) and re.search(
        r"\b(lance|ouvre|démarre|demarre|start|mets)\b", text_lower
    ):
        return None

    for pattern, intent in FAST_REGEX.items():
        if re.search(pattern, text_lower):
            return intent, _fast_intent_params(intent, text)
    return None


def _fast_intent_params(intent: str, text: str) -> dict:
    if intent in ("lancer_app", "fermer_app"):
        return {"app": _extract_app_name(text)}
    if intent == "volume":
        return {"level": text}
    if intent == "meteo":
        return {"city": text}
    if intent == "minuteur":
        return {"text": text}
    return {}


def _build_dynamic_system_prompt() -> str:
    personalized_ctx = memory_engine.get_engine().build_personalized_system_prompt()
    dynamic_system = BASE_SYSTEM_PROMPT + "\n\n" + personalized_ctx
    style_hint = memory_engine.get_engine().get_style_hint()
    if style_hint:
        dynamic_system += "\n\nSTYLE: " + style_hint
    try:
        import focus

        if focus.is_focus_active():
            dynamic_system += "\n\nMode focus actif : sois bref et direct, évite les digressions."
    except Exception:
        pass
    try:
        import german_mode

        if german_mode.is_german_mode_active():
            dynamic_system += (
                "\n\nMode allemand immersif actif : réponds en allemand. "
                "Si l'utilisateur écrit en allemand, corrige discrètement ses erreurs "
                "en donnant la version correcte suivie d'une brève explication en français entre parenthèses."
            )
    except Exception:
        pass
    if _get_conversation_mode() == "vocal":
        dynamic_system += (
            "\n\nTu es en mode vocal. Réponds en 1-3 phrases maximum, de façon "
            "naturelle et conversationnelle. Pas de listes, pas de markdown, pas de tirets."
        )
    return dynamic_system


def _get_conversation_mode() -> str:
    try:
        conv_id = memory_engine.get_current_conversation_id()
        return memory_engine.get_conversation_mode(conv_id) or "ecrit"
    except Exception:
        return "ecrit"


def resolve_model(text: str = "", intent: str = "") -> str:
    """Point unique de sélection — respecte le sélecteur en-tête en priorité."""
    if FORCED_MODEL:
        return FORCED_MODEL
    if not AUTO_ROUTING:
        return MODEL_FAST if _get_conversation_mode() == "vocal" else CHAT_MODEL
    return _select_model(text, intent)


def _select_model(text: str, intent: str = "") -> str:
    """Sélection automatique — actions simples → 1B, vocal → fast uniquement, heavy si mots-clés."""
    if intent in ACTIONS_1B:
        return MODELS["intent"]

    conv_mode = _get_conversation_mode()
    if conv_mode == "vocal":
        return MODELS["fast"]

    text_lower = text.lower()
    if any(kw in text_lower for kw in HEAVY_KEYWORDS):
        return MODELS["heavy"]
    if intent in HEAVY_REQUIRED:
        return MODELS["heavy"]
    return MODELS["fast"]


def _ollama_available() -> bool:
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        return response.status_code == 200
    except requests.RequestException:
        return False


def _ensure_ollama() -> None:
    if _ollama_available():
        return
    logger.warning("Ollama non disponible — tentative de démarrage")
    import ollama_manager

    if not ollama_manager.start_ollama():
        raise RuntimeError("Impossible de démarrer Ollama")


def _resolve_model_with_fallback(model: str) -> str:
    import ollama_manager

    local = ollama_manager.list_local_models()
    if not local:
        return model
    return _match_local_model(model, local)


def _match_local_model(model: str, local_models: list[str]) -> str:
    """Correspondance exacte, partielle (préfixe), puis premier modèle local."""
    if not local_models:
        return model

    for name in local_models:
        if name == model:
            return name

    base = model.split(":")[0] if model else ""
    if base:
        for name in local_models:
            if base in name:
                return name

    fallback = local_models[0]
    if fallback != model:
        logger.warning("Modèle '%s' absent — fallback sur '%s'", model, fallback)
    return fallback


def set_model_role(role: str, model_name: str) -> None:
    """Change le modèle pour un rôle (intent/fast/heavy/vision) — config + live."""
    global MODEL_FAST, MODEL_HEAVY, CHAT_MODEL, REASONING_MODEL, INTENT_MODEL, VISION_MODEL

    if role not in MODELS:
        raise ValueError(f"Rôle inconnu: {role}")

    MODELS[role] = model_name
    patches: dict = {"models": dict(_config.get("models") or {})}
    patches["models"][role] = model_name

    if role == "fast":
        MODEL_FAST = model_name
        CHAT_MODEL = model_name
        patches["model_fast"] = model_name
        patches["chat_model"] = model_name
    elif role == "heavy":
        MODEL_HEAVY = model_name
        REASONING_MODEL = model_name
        patches["model_heavy"] = model_name
        patches["reasoning_model"] = model_name
    elif role == "intent":
        INTENT_MODEL = model_name
        patches["intent_model"] = model_name
    elif role == "vision":
        VISION_MODEL = model_name
        patches["vision_model"] = model_name

    _patch_config(patches)
    logger.info("Modèle %s → %s", role, model_name)
    threading.Thread(target=_warmup_model_async, args=(model_name,), daemon=True).start()


def generate(
    prompt: str,
    model: str | None = None,
    system: str | None = None,
    stream: bool = True,
    max_tokens: int = 400,
    temperature: float = 0.7,
    on_token=None,
) -> str:
    """Appel principal à Ollama /api/generate avec streaming optionnel."""
    _ensure_ollama()

    import ollama_manager

    if model is None:
        model = MODELS["fast"]

    local_models = ollama_manager.list_local_models()
    if not local_models:
        return "Erreur : aucun modèle installé dans Ollama. Lance 'ollama pull llama3.2:1b'."

    chosen = _match_local_model(model, local_models)
    logger.info("Modèle utilisé: %s", chosen)

    payload: dict = {
        "model": chosen,
        "prompt": prompt,
        "stream": stream,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    if system:
        payload["system"] = system

    logger.warning(
        "═══ Ollama POST %s → model=%s stream=%s tokens=%d ═══",
        OLLAMA_GENERATE_URL,
        chosen,
        stream,
        max_tokens,
    )
    logger.debug("Prompt: %s", prompt[:200])

    try:
        if stream and on_token:
            parts: list[str] = []
            with requests.post(
                OLLAMA_GENERATE_URL,
                json=payload,
                stream=True,
                timeout=120,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = data.get("response", "")
                    if token:
                        parts.append(token)
                        on_token(token)
                    if data.get("done"):
                        break
            result = "".join(parts)
        else:
            resp = requests.post(
                OLLAMA_GENERATE_URL,
                json={**payload, "stream": False},
                timeout=120,
            )
            resp.raise_for_status()
            result = resp.json().get("response", "").strip()

        logger.warning("═══ Ollama response: %d chars (model=%s) ═══", len(result), chosen)
        return result

    except requests.exceptions.HTTPError as exc:
        response = exc.response
        if response is not None and response.status_code == 500:
            error_body = response.text
            logger.error("Ollama 500: %s", error_body)
            try:
                err_msg = response.json().get("error", str(exc))
            except Exception:
                err_msg = error_body or str(exc)
            return f"Erreur Ollama: {err_msg}"
        logger.error("Erreur Ollama HTTP: %s", exc, exc_info=True)
        return f"Erreur : {exc}"
    except requests.exceptions.ConnectionError:
        logger.error("Connexion Ollama refusée")
        return "Erreur : impossible de contacter Ollama. Vérifie qu'il tourne."
    except requests.exceptions.Timeout:
        logger.error("Timeout Ollama (model=%s)", chosen)
        return "Erreur : Ollama a mis trop de temps à répondre."
    except Exception as exc:
        logger.error("Erreur Ollama: %s", exc, exc_info=True)
        return f"Erreur : {exc}"


def _get_options(intent: str, conv_mode: str) -> dict:
    options = {"temperature": 0.7, "top_p": 0.9}
    if conv_mode == "vocal":
        options["num_predict"] = 120
    elif intent in HEAVY_REQUIRED:
        options["num_predict"] = 800
    else:
        options["num_predict"] = 400
    return options


def _process_memory_learning(user_text: str, response: str) -> None:
    engine = memory_engine.get_engine()
    quality = engine.analyze_conversation_quality(user_text, response)
    engine.record_fine_tune_example(user_text, response, quality)
    window = engine.current_conversation.get("messages", [])[-6:]
    engine.detect_implicit_preferences(window)
    engine.detect_command_sequences()
    old_score = engine.profile.get("satisfaction_score", 0.5)
    engine.profile["satisfaction_score"] = old_score * 0.95 + quality * 0.05
    memory_engine.save_json(memory_engine.PROFILE_PATH, engine.profile)
    memory_engine.save_json(memory_engine.PATTERNS_PATH, engine.patterns)


def _refresh_system_prompt() -> None:
    global _history
    prompt = _build_dynamic_system_prompt()
    if _history and _history[0].get("role") == "system":
        _history[0]["content"] = prompt
    else:
        _history.insert(0, {"role": "system", "content": prompt})


def _trim_history() -> None:
    global _history
    if len(_history) <= MAX_HISTORY:
        return
    system_messages = [m for m in _history if m.get("role") == "system"]
    non_system = [m for m in _history if m.get("role") != "system"]
    excess = len(_history) - MAX_HISTORY
    if excess > 0:
        non_system = non_system[excess:]
    _history = system_messages + non_system


def _save_history() -> None:
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY_PATH.open("w", encoding="utf-8") as f:
            json.dump(_history, f, ensure_ascii=False, indent=2)
    except OSError:
        logger.exception("Failed to save history")


def _ollama_request(
    messages: list,
    stream: bool = False,
    retries: int = 3,
    model: str | None = None,
    num_predict: int | None = None,
    intent: str = "",
    conv_mode: str | None = None,
) -> requests.Response | None:
    try:
        _ensure_ollama()
    except RuntimeError:
        logger.error("Ollama indisponible pour la requête chat")
        return None

    if conv_mode is None:
        conv_mode = _get_conversation_mode()
    options = _get_options(intent, conv_mode)
    if num_predict is not None:
        options["num_predict"] = num_predict
    chosen = _resolve_model_with_fallback(model or MODEL)
    payload = {
        "model": chosen,
        "messages": messages,
        "stream": stream,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": options,
    }
    for attempt in range(retries):
        try:
            response = requests.post(
                OLLAMA_CHAT_URL,
                json=payload,
                stream=stream,
                timeout=120,
            )
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as exc:
            resp = exc.response
            if resp is not None and resp.status_code == 500:
                try:
                    err_msg = resp.json().get("error", resp.text)
                except Exception:
                    err_msg = resp.text or str(exc)
                logger.error("Ollama chat 500 (model=%s): %s", chosen, err_msg)
                return None
            logger.warning("Ollama HTTP error (attempt %d/%d): %s", attempt + 1, retries, exc)
            time.sleep(1)
        except requests.RequestException as exc:
            logger.warning("Ollama request failed (attempt %d/%d): %s", attempt + 1, retries, exc)
            time.sleep(1)
    return None


def _detect_intent(text: str) -> dict:
    """Détection d'intent ultra-rapide via llama3.2:1b (~50-100ms)."""
    try:
        _ensure_ollama()
    except RuntimeError:
        return {"intent": "question_libre", "params": {}, "confidence": 0.0}

    model = _resolve_model_with_fallback(MODELS["intent"])
    prompt = f"""Classifie cette commande en UN mot parmi cette liste :
{'|'.join(KNOWN_INTENTS)}
Commande : "{text}"
Réponds uniquement avec la catégorie, rien d'autre :"""

    try:
        raw = generate(prompt, model=model, stream=False, max_tokens=10, temperature=0.1)
        if raw.startswith("Erreur"):
            raise RuntimeError(raw)
        raw = raw.strip().lower()
        for intent in KNOWN_INTENTS:
            if intent in raw:
                logger.info("Intent détecté: %s (modèle=%s)", intent, model)
                return {"intent": intent, "params": {}, "confidence": 0.85}
    except Exception as exc:
        logger.error("Erreur intent detection: %s", exc)

    return {"intent": "question_libre", "params": {}, "confidence": 0.5}


def _extract_in_site_search(text: str) -> tuple[str, str] | None:
    """Extrait (query, site) depuis « cherche X sur Y »."""
    match = re.search(
        r"(?:cherche|trouve|recherche)\s+(.+?)\s+(?:sur|dans)\s+(.+?)(?:\.|$)",
        text.strip(),
        re.I,
    )
    if not match:
        return None
    query, site = match.group(1).strip(), match.group(2).strip()
    if re.search(r"internet|google\b|la page|cette page|page ouverte|mon drive|google drive", site, re.I):
        return None
    return query, site


def _extract_page_search_query(text: str) -> str | None:
    """Extrait la query depuis « cherche X dans la page »."""
    match = re.search(
        r"(?:cherche|trouve|recherche)\s+(.+?)\s+(?:dans|sur)\s+"
        r"(?:la page(?: ouverte)?|cette page|la page actuelle)",
        text.strip(),
        re.I,
    )
    return match.group(1).strip() if match else None


def _extract_doc_content(text: str) -> str:
    """Extrait ce qu'ARIA doit écrire depuis « écris X dans un google doc »."""
    m = re.search(
        r"(?:[ée]cris|ecris|note|r[ée]dige|redige|tape|met[s]?|ajoute)\s+(.+?)\s+"
        r"(?:dans|sur)\s+(?:un\s+|le\s+|mon\s+|ce\s+)?(?:nouveau\s+)?"
        r"(?:google\s+)?(?:doc|document|drive)",
        text,
        re.I,
    )
    if m:
        return m.group(1).strip(" :,'\"")
    # Repli : on retire juste le verbe d'amorce.
    cleaned = re.sub(
        r"^(?:[ée]cris|ecris|note|r[ée]dige|redige|tape|met[s]?|ajoute)\s+",
        "",
        text.strip(),
        flags=re.I,
    )
    return cleaned.strip(" :,'\"") or text


def _handle_drive_intent(intent: str, params: dict, original_text: str) -> str:
    """Route les intents Drive. Écriture/création de doc -> automatisation navigateur
    (on écrit réellement dedans). Recherche/liste -> MCP avec repli navigateur."""
    if intent in ("drive_write_doc", "drive_create_doc"):
        content = _extract_doc_content(original_text)
        return browser.write_in_google_doc(content)

    mcp_prompt = f"""Use the Google Drive MCP tools to: {original_text}

Available operations:
- search_files: search for files
- create_file: create a new document
- read_file_content: read file content
- list_recent_files: list recent files

Execute the appropriate operation and return the result in French."""

    try:
        response = requests.post(
            OLLAMA_CHAT_URL,
            json={
                "model": MODEL_HEAVY,
                "messages": [{"role": "user", "content": mcp_prompt}],
                "stream": False,
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": "google_drive",
                        "description": "Interact with Google Drive",
                        "parameters": {},
                    },
                }],
            },
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
        content = result.get("message", {}).get("content", "")
        if content.strip():
            return content
        return "Opération Drive effectuée"
    except Exception:
        logger.exception("Drive MCP routing failed, using browser fallback")
        if intent == "drive_search":
            query = params.get("query", original_text)
            q_match = re.search(
                r"cherche\s+(.+?)\s+(?:dans|sur)\s+(?:mon\s+)?(?:google\s+)?drive",
                original_text,
                re.I,
            )
            if q_match:
                query = q_match.group(1).strip()
            return browser.open_url(f"https://drive.google.com/drive/search?q={quote_plus(query)}")
        if intent in ("drive_create_doc", "drive_write_doc"):
            return browser.open_url("https://docs.google.com/document/create")
        if intent == "drive_create_folder":
            return browser.open_url("https://drive.google.com/drive/u/0/my-drive")
        return browser.open_url("https://drive.google.com")


def _rule_based_intent(text: str) -> dict:
    t = text.lower()
    rules = [
        # === Google Agenda (priorité haute ; move/delete/add AVANT list) ===
        (
            r"(?:d[ée]place|deplace|d[ée]cale|decale|reporte|repousse|change|modifie)\b.*?"
            r"(?:rendez-?vous|rdv|cr[ée]neau|r[ée]union|s[ée]ance|cours|[ée]v[èé]nement|"
            r"\d{1,2}\s*h|demain|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)",
            "calendar_move",
            {"text": text},
        ),
        (
            r"(?:annule|supprime|enl[èe]ve|retire)\b.*?"
            r"(?:rendez-?vous|rdv|cr[ée]neau|r[ée]union|s[ée]ance|cours|[ée]v[èé]nement)",
            "calendar_delete",
            {"text": text},
        ),
        (
            r"(?:cale|caler|planifie|programme|r[ée]serve|reserve|bloque|ajoute|"
            r"cr[ée]e|cree|note|pr[ée]vois)\b.*?"
            r"(?:rendez-?vous|rdv|cr[ée]neau|r[ée]union|s[ée]ance|cours|[ée]v[èé]nement|"
            r"\d{1,2}\s*h|demain|apr[èe]s-demain|lundi|mardi|mercredi|jeudi|vendredi|"
            r"samedi|dimanche|midi|ce soir|semaine prochaine)",
            "calendar_add",
            {"text": text},
        ),
        (
            r"(?:mon|ma|mes)\s+(?:agenda|planning|rendez-?vous|rdv|cr[ée]neaux?|"
            r"[ée]v[èé]nements?)\b|qu'?est-ce que j'?ai\s+(?:de\s+)?(?:pr[ée]vu|"
            r"aujourd'?hui|demain|cette semaine|au programme)|"
            r"(?:rendez-?vous|rdv)\s+(?:de\s+)?(?:la\s+)?(?:journ[ée]e|semaine|aujourd'?hui|demain)",
            "calendar_list",
            {},
        ),
        # Recherche in-page et in-site (avant recherche web générique)
        (
            r"(?:cherche|trouve|recherche).*(?:dans la page|sur la page|cette page|"
            r"page ouverte|page actuelle)",
            "browser_search_page",
            {"query": text},
        ),
        (
            r"(?:cherche|trouve|recherche)\s+.+\s+(?:sur|dans)\s+"
            r"(?!la page|cette page|internet|google\b|mon drive|google drive)",
            "browser_search_in_site",
            {"text": text},
        ),
        # Google Drive
        (
            r"(?:ouvre|accède|accede|va sur).*(?:mes fichiers|mon drive|google drive)",
            "drive_open",
            {},
        ),
        (
            r"liste.*(?:fichiers|r[ée]cents).*(?:drive|google drive)",
            "drive_list",
            {},
        ),
        (
            r"(?:cr[ée]e|cree|cr[ée]er|creer).*(?:dossier|folder).*(?:drive|google drive)",
            "drive_create_folder",
            {"name": text},
        ),
        (
            r"(?:cr[ée]e|cree|cr[ée]er|creer).*(?:document|google doc).*(?:drive|google drive)|"
            r"(?:cr[ée]e|cree)\s+(?:un\s+)?google doc(?:ument)?\s+(?:sur|intitul[ée])",
            "drive_create_doc",
            {"title": text},
        ),
        (
            r"(?:[ée]cris|ecris).*(?:dans|sur).*(?:document|nouveau document|google doc|drive)",
            "drive_write_doc",
            {"content": text},
        ),
        (
            r"cherche\s+.+\s+(?:dans|sur)\s+(?:mon\s+)?(?:google\s+)?drive",
            "drive_search",
            {"query": text},
        ),
        (
            r"partage.*(?:drive|fichier|document)",
            "drive_share",
            {"text": text},
        ),
        # Browser v4 (before generic open/launch)
        (r"youtube.*(cherche|joue|lance|mets)|ouvre youtube", "browser_youtube_search", {"query": text}),
        (r"pause la vid[ée]o|coupe le son|plein [ée]cran|vid[ée]o suivante|volume youtube", "browser_youtube_control", {"action": text}),
        (r"spotify", "browser_spotify", {"action": text}),
        (r"recherche.*google|google.*recherche", "browser_search_google", {"query": text}),
        (r"lis.*(cette page|la page|le site)", "browser_read_page", {}),
        (r"capture.*(navigateur|page|écran)", "browser_screenshot", {}),
        (r"d[ée]file|scroll|descend.*page|monte.*page", "browser_scroll", {"direction": text}),
        (r"ferme.*navigateur|ferme chrome", "browser_close", {}),
        (r"ferme.*onglet", "browser_close_tab", {}),
        (r"nouvel onglet", "browser_new_tab", {"url": text}),
        (r"va sur ", "browser_open_site", {"site": text}),
        (r"ouvre https?://", "browser_open_url", {"url": text}),
        # Saisie universelle navigateur / Claude / Cursor
        (r"demande\s+(?:à|a)\s+claude", "browser_type_claude", {"text": text}),
        (r"envoie.*cursor|demande\s+(?:à|a)\s+cursor", "cursor_prompt", {"text": text}),
        (r"tape .+ sur (?:la |cette )?page", "browser_type", {"text": text}),
        (r"[ée]cris .+ dans le navigateur", "browser_type", {"text": text}),
        (r"^envoie .+ sur (?:la |cette )?page", "browser_type_send", {"text": text}),
        (r"^envoie(?!.*(?:cursor|claude|sur la page|sur cette page))", "browser_type_send", {"text": text}),
        # Nexus (éditeur de code maison) — avant Cursor
        (r"(?:ouvre|lance|d[ée]marre)\s+nexus", "nexus_open", {}),
        (r"(?:demande|envoie|dis)\s+(?:à|a)\s+nexus|\b(?:dans|sur|via)\s+nexus\b|\bcode\b.*\bnexus\b", "nexus_prompt", {"text": text}),
        # Cursor v3
        (r"ouvre cursor$|ouvre cursor\s*$|lance cursor", "cursor_open", {}),
        (r"projet.*cursor|cursor.*projet", "cursor_open_project", {"name": text}),
        (r"ouvre.*\.(py|ts|tsx|js)|fichier.*cursor", "cursor_open_file", {"path": text}),
        (r"génère|genere|crée|cree|dans cursor|corrige.*cursor", "cursor_generate_code", {"request": text}),
        # Search v3 — news before generic web search
        (r"cherche.*nouvelles|cherche.*actualit|recherche.*nouvelles|nouvelles sur|derni[èe]res? nouvelles|derni[èe]res? actu", "search_news", {"query": text}),
        (r"cherche.*intelligence artificielle|recherche.*intelligence artificielle", "search_news", {"query": "intelligence artificielle"}),
        (r"géopolitique|geopolitique", "search_geopolitics", {}),
        (r"actu.*aviation|aviation.*actu|nouvelles.*aviation", "search_aviation_news", {}),
        (r"actu.*ia|ia.*actu", "search_news", {"topic": "ia"}),
        (r"briefing.*actu", "search_news", {}),
        # Maths v3
        (r"d[ée]riv[ée]e", "math_derive", {"text": text}),
        (r"int[èe]gre|int[ée]grale", "math_integrate", {"text": text}),
        (r"r[ée]sous|equation", "math_solve_equation", {"text": text}),
        (r"suite arithm|suite g[ée]om", "math_suite", {"text": text}),
        (r"binomiale|binom|probabilit", "math_proba", {"text": text}),
        (r"matrice|d[ée]terminant", "math_matrix", {"text": text}),
        (r"limite de|limite quand", "math_limit", {"text": text}),
        (r"factorise|d[ée]veloppe", "math_general", {"text": text}),
        (r"combien font|calcule", "math_calculate", {"text": text}),
        # Aviation v3
        (r"d[ée]code.*metar|metar.*d[ée]code", "aviation_metar", {"raw": text}),
        (r"checklist", "aviation_checklist", {"phase": text}),
        (r"vent de travers|composante.*vent", "aviation_wind", {"text": text}),
        (r"triangle des vitesses|cap à tenir", "aviation_nav", {"text": text}),
        (r"planifie.*vol|carburant|fuel", "aviation_fuel", {"text": text}),
        (r"go.?no.?go|gonogo", "aviation_gonogo", {"text": text}),
        (r"phon[ée]tique|radio|phras[ée]ologie", "aviation_radio", {"text": text}),
        (r"d[ée]crochage|ppl|a[ée]rodynamique|vx|vy|vs\b|dr400|th[ée]orie.*vol", "aviation_theory", {"text": text}),
        # Existants v2
        (r"lance(?:-moi)?|ouvre(?:-moi)?|d[ée]marre|mets?\s+.+\s+en route", "lancer_app", {"app": text}),
        (r"ferme|quitte|arr[êe]te", "fermer_app", {"app": text}),
        (r"volume|son", "volume", {"level": text}),
        (r"luminosité|luminosite|brightness", "luminosite", {"level": text}),
        (r"veille|suspend", "veille", {}),
        (r"redémarre|reboot", "reboot", {}),
        (r"éteins|shutdown|extinction", "shutdown", {}),
        (r"\bactus?\b|actualit[ée]s?|\bnews\b", "actu", {}),
        (r"météo|meteo|température", "meteo", {"city": text}),
        (r"\bmetar\b", "aviation_metar", {"icao": _extract_icao(text)}),
        (r"\btaf\b", "aviation_taf", {"icao": _extract_icao(text)}),
        (r"\bnotam\b", "aviation_notam", {"icao": _extract_icao(text)}),
        (r"minuteur|timer", "minuteur", {"text": text}),
        (r"alarme", "alarme", {"text": text}),
        (r"cherche|recherche|google|sur internet", "search_web", {"query": text}),
        (r"git|commit|push|pull", "git", {"text": text}),
        (r"convertis|traduis", "traduction", {"text": text}),
        (r"mode ", "preset", {"name": text}),
        (r"presse.papier|clipboard", "clipboard_paste", {}),
        (r"rappel|agenda|[ée]v[ée]nement", "rappel", {"text": text}),
        (r"quelle heure|quelle date|heure", "heure_date", {}),
        (r"blague", "blague", {}),
        (r"fais-moi mon brief|brief du jour|résumé de la journée|quoi de neuf aujourd", "daily_brief", {}),
        (r"exporte.*(conversation|pdf|session)", "export_pdf", {}),
        (r"mode focus|mode concentration|ne me dérange pas", "focus_mode_on", {"text": text}),
        (r"désactive.*focus|desactive.*focus|fin du mode focus", "focus_mode_off", {}),
        (r"qu'est-ce que j'ai aujourd|mon agenda|mes rendez-vous", "calendar_today", {}),
        (r"prochains rendez|semaine prochaine", "calendar_upcoming", {}),
        (r"ajoute un rendez|programme un événement|crée un événement", "calendar_create", {"text": text}),
        (r"plan de révision|planning bac|révision bac", "revision_plan", {}),
        (r"mode allemand|passons à l'allemand|parle allemand", "german_mode_on", {}),
        (r"désactive.*allemand|desactive.*allemand|retour au français", "german_mode_off", {}),
        (r"lance la macro|exécute la macro|execute la macro", "run_macro", {"text": text}),
        (r"allume|éteins|eteins|domotique|home assistant", "smarthome", {"text": text}),
        (r"discord|messages discord", "social_discord", {}),
        (r"mémoire|memoire|souviens", "memoire", {"text": text}),
    ]
    for pattern, intent, params in rules:
        if re.search(pattern, t):
            return {"intent": intent, "params": params, "confidence": 0.85}
    return {"intent": "question_libre", "params": {}, "confidence": 0.5}


def _extract_browser_text(text: str, intent: str) -> str:
    """Extrait le texte à taper depuis une commande vocale."""
    result = text.strip()
    prefixes = {
        "browser_type": (
            r"^tape\s+",
            r"^(?:écris|ecris)\s+",
        ),
        "browser_type_send": (
            r"^envoie\s+",
        ),
        "browser_type_claude": (
            r"^demande\s+(?:à|a)\s+claude(?:\s+de)?\s+",
        ),
        "cursor_prompt": (
            r"^demande\s+(?:à|a)\s+cursor(?:\s+de)?\s+",
            r"^envoie(?:-|\s)?(?:le|la|les|moi|ça|ca)?\s*(?:à|a)\s*cursor\s+",
            r"^envoie(?:-|\s)?(?:ça|ca)\s*(?:à|a)\s*cursor\s*",
        ),
    }
    for pattern in prefixes.get(intent, ()):
        match = re.match(pattern, result, re.I)
        if match:
            result = result[match.end():].strip()
            break
    for suffix in (
        r"\s+sur\s+(?:la\s+|cette\s+)?page\.?$",
        r"\s+dans\s+le\s+navigateur\.?$",
    ):
        result = re.sub(suffix, "", result, flags=re.I).strip()
    return result.strip(" :,.\"'")


def _extract_icao(text: str) -> str:
    match = re.search(r"\b([A-Z]{4})\b", text.upper())
    if match:
        return match.group(1)
    for word in text.split():
        if word.lower() in ("nantes", "lfrs"):
            return "LFRS"
    return _config.get("default_icao", "LFRS")


def _extract_app_name(text: str) -> str:
    text = re.sub(
        r"^(lance(?:-moi)?|ouvre(?:-moi)?|d[ée]marre(?:-moi)?|mets?|ferme(?:-moi)?|quitte(?:-moi)?|arr[êe]te(?:-moi)?)\s+",
        "",
        text.strip(),
        flags=re.I,
    )
    text = re.sub(r"\s+en route$", "", text, flags=re.I)
    for word in ("ferme", "quitte", "arrête", "arrete", "stop"):
        text = re.sub(rf"\b{word}\b", "", text, flags=re.I)
    return text.strip()


def _extract_search_query(text: str) -> str:
    return web_search.extract_query(text)


def _execute_ddg_search(intent: str, params: dict, original_text: str) -> str:
    query = _extract_search_query(params.get("query", original_text))
    if intent == "search_geopolitics" and (not query or query == original_text.strip()):
        query = "géopolitique mondiale"
    text_lower = original_text.lower()
    is_news = (
        intent in ("search_news", "search_geopolitics")
        or any(
            kw in text_lower
            for kw in ("actu", "news", "nouvelles", "actualité", "actualites", "géopolitique", "geopolitique", "briefing")
        )
    )
    if is_news:
        results = search_news(query)
        if not results:
            results = search_web(query)
    else:
        results = search_web(query)
        if not results:
            results = search_news(query)
    summary = summarize_with_ollama(results, context=query)
    _speak_response(summary)
    return summary


def _should_speak_tts() -> bool:
    """Parle si TTS global activé ou conversation en mode vocal."""
    if _config.get("tts_enabled", False):
        return True
    try:
        conv_id = memory_engine.get_current_conversation_id()
        return memory_engine.get_conversation_mode(conv_id) == "vocal"
    except Exception:
        return False


def _speak_response(summary: str) -> None:
    _present_action_result(summary)


def _speak_already_displayed(text: str) -> None:
    """TTS sans ré-afficher le texte (réponse déjà dans le chat)."""
    if not text or not text.strip():
        return
    try:
        import focus

        if focus.is_focus_active():
            return
    except Exception:
        pass
    if not _should_speak_tts():
        return
    ui.set_status("speaking")
    tts.speak(text, force=True)
    ui.set_status("idle")


def _present_action_result(result: str) -> None:
    """Affiche le résultat d'une action dans le chat puis le lit via TTS."""
    if not result or not result.strip():
        ui.set_status("idle")
        return
    ui.append_assistant_text(result)
    ui.finalize_assistant_message()
    try:
        import focus

        if focus.is_focus_active():
            ui.set_status("idle")
            return
    except Exception:
        pass
    if not _should_speak_tts():
        ui.set_status("idle")
        return
    ui.set_status("speaking")
    tts.speak(result, force=True)
    ui.set_status("idle")


def _finish_streamed_response(full_response: str, *, already_spoken: bool = False) -> None:
    """Lit via TTS une réponse déjà streamée et affichée token par token."""
    if not full_response or not full_response.strip():
        ui.set_status("idle")
        return
    if already_spoken:
        ui.set_status("idle")
        tts.notify_speech_finished()
        return
    try:
        import focus

        if focus.is_focus_active():
            ui.set_status("idle")
            return
    except Exception:
        pass
    if not _should_speak_tts():
        ui.set_status("idle")
        return
    ui.set_status("speaking")
    tts.speak(full_response, force=True)
    ui.set_status("idle")


def _extract_site_for_browser(params: dict, original_text: str) -> str:
    site = params.get("site") or params.get("url") or params.get("query") or original_text
    if site == original_text:
        extracted = browser._extract_site_name(original_text)
        if extracted:
            site = extracted
        else:
            match = re.search(
                r"(?:ouvre|va sur|lance|ouvre le navigateur sur)\s+(.+)",
                original_text,
                re.I,
            )
            if match:
                site = match.group(1).strip()
    site = re.sub(r"^(va sur|ouvre(?:-moi)?|visite|lance)\s*", "", site, flags=re.I).strip()
    site = re.sub(r"\s+en route$", "", site, flags=re.I).strip()
    return site


def _needs_reasoning(text: str) -> bool:
    """Vrai si la question mérite le modèle de raisonnement (plus lent mais profond)."""
    if _REASONING_RE.search(text):
        return True
    return len(text.split()) > 45


def _is_current_info_query(text: str) -> bool:
    """Vrai si la question porte sur une info récente/actuelle -> recherche web."""
    return bool(_CURRENT_INFO_RE.search(text))


def _resolve_intent_for_routing(text: str) -> tuple[str, dict, float]:
    """Résout l'intent : regex rapide puis détection complète."""
    fast = _fast_intent(text)
    if fast:
        intent, params = fast
        logger.info("Fast intent (regex): %s", intent)
        return intent, params, 0.95

    try:
        detected = _detect_intent(text)
        intent = detected.get("intent", "question_libre")
        params = detected.get("params", {})
        confidence = float(detected.get("confidence", 0.5))
        logger.info("Detected intent: %s (confidence=%.2f)", intent, confidence)
        if confidence < 0.6:
            intent = "question_libre"
    except Exception as exc:
        logger.warning("Intent detection failed: %s", exc)
        intent = "question_libre"
        confidence = 0.0

    # Question ouverte portant sur une info récente -> recherche web (infos fraîches).
    if intent == "question_libre" and _is_current_info_query(text):
        logger.info("Question ouverte -> recherche web (info actuelle)")
        return "search_web", {"query": text}, 0.9

    return intent, params, confidence


def _is_news_query(text: str) -> bool:
    t = text.lower()
    return any(
        kw in t
        for kw in ("actu", "news", "nouvelles", "actualité", "actualites", "géopolitique", "geopolitique", "briefing")
    )


def _fetch_api_data(intent: str, params: dict, text: str) -> str | None:
    """Récupère les données API brutes. Retourne None en cas d'échec."""
    try:
        if intent == "meteo":
            city = params.get("city")
            if isinstance(city, str):
                for c in ("nantes", "couëron", "coueron", "paris"):
                    if c in city.lower():
                        city = c.capitalize()
                        break
                else:
                    city = re.sub(
                        r".*(météo|meteo|température|temperature|temps)\s*(?:à|a|de|pour)?\s*",
                        "",
                        city,
                        flags=re.I,
                    ).strip() or None
            if not city:
                for c in ("nantes", "couëron", "coueron", "paris"):
                    if c in text.lower():
                        city = c.capitalize()
                        break
            data = weather.get_current(city or _config.get("city", "Coueron"))
            if "error" not in data:
                return (
                    f"Données météo pour {data.get('city', city)}: "
                    f"température {data.get('temp')}°C, ressenti {data.get('feels_like')}°C, "
                    f"{data.get('description')}, humidité {data.get('humidity')}%, "
                    f"vent {data.get('wind')} km/h"
                )
            return None

        if intent == "aviation_metar":
            metar_match = re.search(r"METAR\s+[A-Z]{4}\s+.*", text.upper())
            if metar_match:
                return f"METAR brut: {metar_match.group(0)}"
            icao = params.get("icao") or _extract_icao(text)
            data = aviation.get_metar(icao)
            if isinstance(data, dict) and "error" not in data:
                return f"METAR brut pour {icao}: {data.get('raw', data)}"
            return None

        if intent == "aviation_taf":
            icao = params.get("icao") or _extract_icao(text)
            data = aviation.get_taf(icao)
            if isinstance(data, dict) and "error" not in data:
                raw = data.get("raw") or data.get("taf") or str(data)
                return f"TAF brut pour {icao}: {raw}"
            return None

        if intent == "actu":
            category = "technology" if "tech" in text.lower() else None
            articles = news.get_top_headlines(category)
            if articles:
                items = [
                    f"- {a.get('title', '')}: {a.get('description', '')[:200]}"
                    for a in articles[:5]
                ]
                return "Actualités:\n" + "\n".join(items)
            return None

        if intent == "search_aviation_news":
            summary = web_search.search_aviation_news()
            return summary if summary and "Pas d'" not in summary else None

        if intent in ("search_web", "search_news", "search_geopolitics"):
            query = _extract_search_query(params.get("query", text))
            if intent == "search_geopolitics" and (not query or query == text.strip()):
                query = "géopolitique mondiale"
            is_news = intent in ("search_news", "search_geopolitics") or _is_news_query(text)
            results = search_news(query) if is_news else search_web(query)
            if not results:
                results = search_web(query) if is_news else search_news(query)
            if results:
                items = [
                    f"- {r.get('title', '')}: {r.get('body', r.get('snippet', ''))[:200]}"
                    for r in results[:5]
                ]
                return "Résultats de recherche:\n" + "\n".join(items)
            return None

        if intent == "drive_search":
            query = params.get("query", text)
            q_match = re.search(
                r"cherche\s+(.+?)\s+(?:dans|sur)\s+(?:mon\s+)?(?:google\s+)?drive",
                text,
                re.I,
            )
            if q_match:
                query = q_match.group(1).strip()
            return f"Recherche Drive: {query}"

        if intent == "drive_list":
            return "Liste des fichiers récents Google Drive demandée"

    except Exception as exc:
        logger.error("API fetch error for %s: %s", intent, exc)
        return None

    return None


def _build_format_prompt(intent: str, api_data: str, original_text: str) -> str:
    prompts = {
        "meteo": f"Formate ces données météo en une phrase naturelle en français pour lecture vocale: {api_data}",
        "aviation_metar": f"Décode ce METAR en français naturel pour un pilote PPL, inclus les conditions VFR/IMC: {api_data}",
        "aviation_taf": f"Décode ce TAF en français naturel pour un pilote PPL: {api_data}",
        "search_web": f"Résume ces résultats en 2-3 phrases naturelles en français. Question: '{original_text}'. Résultats: {api_data}",
        "search_news": f"Résume ces actualités en 3-4 phrases en français. Question: '{original_text}'. Actualités: {api_data}",
        "search_geopolitics": f"Analyse ces infos géopolitiques en 3-4 phrases factuelles en français: {api_data}",
        "search_aviation_news": f"Résume ces actualités aviation en français pour un passionné PPL: {api_data}",
        "actu": f"Résume ces actualités en 3-4 phrases naturelles en français: {api_data}",
        "drive_search": f"Indique en français comment effectuer cette recherche Google Drive: {api_data}",
        "drive_list": f"Explique en français comment lister les fichiers Drive: {api_data}",
    }
    return prompts.get(intent, f"Résume en français naturel pour lecture vocale: {api_data}")


def _llm_format(prompt: str) -> str:
    result = generate(prompt, model=MODEL_FAST, stream=False, max_tokens=200, temperature=0.3)
    if result.startswith("Erreur"):
        logger.error("LLM format error: %s", result)
        return prompt
    return result.strip() or prompt


def _build_chat_prompt_from_history() -> tuple[str, str | None]:
    """Construit prompt + system pour /api/generate à partir de _history."""
    system_content: str | None = None
    turns: list[str] = []
    for msg in _history:
        role = msg.get("role")
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        if role == "system":
            system_content = content
        elif role == "user":
            turns.append(f"Utilisateur: {content}")
        elif role == "assistant":
            turns.append(f"ARIA: {content}")
    prompt = "\n".join(turns)
    if prompt and not prompt.rstrip().endswith("ARIA:"):
        prompt = f"{prompt}\nARIA:"
    elif not prompt:
        prompt = "ARIA:"
    return prompt, system_content


def _conversation_via_generate(
    model: str,
    max_tokens: int,
    stream_to_ui: bool,
    temperature: float = 0.7,
) -> tuple[str, bool]:
    """Conversation libre via generate() (/api/generate) avec streaming UI optionnel."""
    prompt, system = _build_chat_prompt_from_history()
    conv_mode = _get_conversation_mode()
    if conv_mode == "vocal" and system:
        system = system + "\nMode vocal: réponds en 1-3 phrases max, pas de markdown ni de listes."

    spoke_streaming = False
    sentence_buffer = ""

    if stream_to_ui:
        ui.set_status("thinking")

    if stream_to_ui:
        tts_queue: list[str | None] = []

        def _speak_worker() -> None:
            nonlocal spoke_streaming
            while True:
                if tts_queue:
                    sentence = tts_queue.pop(0)
                    if sentence is None:
                        break
                    if len(sentence.strip()) > 2 and _should_speak_tts():
                        ui.set_status("speaking")
                        tts.speak(sentence, force=True, notify_finished=False)
                        spoke_streaming = True
                else:
                    time.sleep(0.02)

        tts_thread: threading.Thread | None = None
        if _should_speak_tts():
            tts_thread = threading.Thread(target=_speak_worker, daemon=True, name="LLM-TTS")
            tts_thread.start()

        def on_token(token: str) -> None:
            nonlocal sentence_buffer
            ui.append_assistant_text(token)
            sentence_buffer += token
            if SENTENCE_END_RE.search(sentence_buffer.rstrip()):
                sentence = sentence_buffer.strip()
                if sentence and tts_thread is not None:
                    tts_queue.append(sentence)
                sentence_buffer = ""

        result = generate(
            prompt,
            model=model,
            system=system,
            stream=True,
            max_tokens=max_tokens,
            temperature=temperature,
            on_token=on_token,
        )

        remainder = sentence_buffer.strip()
        if remainder and tts_thread is not None:
            tts_queue.append(remainder)
        if tts_thread is not None:
            tts_queue.append(None)
            tts_thread.join(timeout=30)

        ui.finalize_assistant_message()
    else:
        result = generate(
            prompt,
            model=model,
            system=system,
            stream=False,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    if result.startswith("Erreur"):
        return "", False
    return result.strip(), spoke_streaming


def _execute_action(intent: str, params: dict, text: str) -> str | None:
    try:
        if intent == "lancer_app":
            app = params.get("app", "")
            if not app:
                match = re.search(r"(?:lance|ouvre|démarre|demarre|start)\s+(.+)", text, re.I)
                app = match.group(1).strip() if match else text
            clean = _extract_app_name(app)
            app_names = [a.strip() for a in re.split(r"\bet\b|,|&", clean) if a.strip()]
            if len(app_names) > 1:
                for name in app_names:
                    memory_engine.record_app_launch(name)
                return apps.launch_multiple(app_names)
            memory_engine.record_app_launch(clean or app)
            result = apps.launch(clean or app)
            if "introuvable" in result.lower():
                return browser.open_site(browser._extract_site_name(text) or clean)
            return result

        if intent == "fermer_app":
            return apps.close(_extract_app_name(params.get("app", text)))

        if intent == "volume":
            level = params.get("level", text)
            nums = re.findall(r"\d+", str(level))
            return system.set_volume(int(nums[0]) if nums else level)

        if intent == "luminosite":
            level = params.get("level", text)
            nums = re.findall(r"\d+", str(level))
            return system.set_brightness(int(nums[0]) if nums else level)

        if intent == "veille":
            return system.sleep()
        if intent == "reboot":
            return system.reboot()
        if intent == "shutdown":
            delay_match = re.search(r"(\d+)", text)
            delay = int(delay_match.group(1)) * 60 if delay_match else 0
            return system.shutdown(delay)
        if intent == "lock":
            return system.lock()
        if intent == "screenshot":
            return system.screenshot()

        if intent == "heure_date":
            now = datetime.now()
            return f"Il est {now.strftime('%H:%M')}, le {now.strftime('%d/%m/%Y')}"

        if intent in ("browser_open_site", "browser_open_url", "ouvrir_site"):
            site = params.get("site") or _extract_site_for_browser(params, text)
            browser_param = params.get("browser")
            if not site:
                return "Quel site veux-tu ouvrir ?"
            if site.startswith("http"):
                return browser.open_url(site, browser=browser_param)
            return browser.open_site(site, browser=browser_param)

        if intent == "browser_youtube_search":
            match = re.search(r"(?:cherche|lance|mets|youtube)\s+(.+?)(?:\s+sur youtube)?$", text, re.I)
            query = match.group(1).strip() if match else params.get("query", text)
            return browser.search_youtube(query)

        if intent == "browser_search_google":
            return browser.search_google(params.get("query", text))

        if intent == "browser_search_in_site":
            site = params.get("site")
            query = params.get("query")
            if site and query:
                return browser.search_within_site(site, query)
            parsed = _extract_in_site_search(text)
            if parsed:
                return browser.search_within_site(parsed[1], parsed[0])
            return browser.search_google(text)

        if intent == "browser_youtube_control":
            return browser.youtube_control(params.get("action", text))

        if intent == "cursor_open":
            return cursor_control.open_cursor()

        if intent == "cursor_open_file":
            file_match = re.search(r"([\w./\\-]+\.(py|ts|tsx|js|jsx|json|yaml|md))", text, re.I)
            if file_match:
                return cursor_control.open_file_in_cursor(file_match.group(1))
            return cursor_control.handle(text)

        if intent == "git":
            t = text.lower()
            if "statut" in t or "status" in t:
                return git.status()
            if "commit" in t:
                return git.commit(re.sub(r".*message\s*", "", text, flags=re.I).strip() or "commit vocal")
            if "push" in t or "pousse" in t:
                return git.push()
            if "pull" in t:
                return git.pull()
            return git.status()

        if intent in ("minuteur", "alarme"):
            return timer.parse_and_set(text)

        if intent == "preset":
            t = text.lower()
            if any(w in t for w in ("désactive", "desactive", "quitte le mode", "sors du mode", "arrête le mode", "arrete le mode")):
                return presets.deactivate()
            preset = presets.match_in_text(text)
            if not preset:
                raw = params.get("preset") or params.get("name", "")
                if raw and presets._normalize_key(raw) in presets.get_merged_presets():
                    preset = presets._normalize_key(raw)
            if preset:
                return presets.activate(preset)
            return "Quel mode ? (" + "/".join(presets.list_presets()) + ")"

        if intent == "clipboard_copy":
            return clipboard.copy_text(text)
        if intent == "clipboard_paste":
            clip = clipboard.get_text()
            return clip if clip.strip() else "Le presse-papier est vide."

        if intent == "nexus_prompt":
            from actions import nexus

            if not nexus.is_enabled():
                return (
                    "Nexus n'est pas encore configuré. "
                    "Tu peux l'activer dans config.yaml une fois Nexus lancé."
                )
            query = params.get("query") or params.get("text") or text
            payload = re.sub(
                r"^.*?(?:demande|envoie|dis)\s+(?:à|a)\s+nexus\s+(?:de\s+)?",
                "",
                query,
                flags=re.I,
            ).strip()
            payload = re.sub(r"\b(?:dans|sur|via)\s+nexus\b", "", payload, flags=re.I).strip()
            nexus_m = re.search(r"^nexus\s+(?:fais|fait)\s+(.+)", payload, re.I)
            if nexus_m:
                payload = nexus_m.group(1).strip()
            return nexus.send_prompt(payload or query)

    except Exception as exc:
        logger.error("Action error for %s: %s", intent, exc)
        return f"Erreur: {exc}"

    return None


def _route_with_intelligence(
    intent: str,
    params: dict,
    text: str,
    *,
    stream_to_ui: bool = True,
) -> str:
    if intent in PURE_ACTIONS or intent in API_ONLY:
        result = _execute_action(intent, params, text)
        if not result:
            result = _dispatch_action(intent, params, text)
        if result and stream_to_ui:
            _speak_response(result)
        if result:
            logger.warning("═══ LLM→UI: '%s' ═══", str(result)[:200])
        return result or ""

    if intent in API_THEN_LLM:
        api_data = _fetch_api_data(intent, params, text)
        if api_data:
            formatted = _llm_format(_build_format_prompt(intent, api_data, text))
            if stream_to_ui:
                _speak_response(formatted)
            logger.warning("═══ LLM→UI: '%s' ═══", str(formatted)[:200])
            return formatted
        logger.warning("API failed for %s, falling back to LLM", intent)

    if intent != "question_libre":
        try:
            result = _dispatch_action(intent, params, text)
        except Exception:
            logger.exception("Dispatch failed for intent %s", intent)
            result = ""
        if result:
            if stream_to_ui and intent != "blague":
                _speak_response(result)
            elif stream_to_ui and intent == "blague":
                _present_action_result(result)
            logger.warning("═══ LLM→UI: '%s' ═══", str(result)[:200])
            return result

    response, spoke = _conversation(text, stream_to_ui=stream_to_ui, intent=intent)
    if stream_to_ui and response:
        _finish_streamed_response(response, already_spoken=spoke)
    if response:
        logger.warning("═══ LLM→UI: '%s' ═══", str(response)[:200])
    return response


def _dispatch_action(intent: str, params: dict, original_text: str) -> str:
    if intent == "lancer_app":
        app_param = params.get("app", original_text)
        clean = _extract_app_name(app_param)
        app_names = [a.strip() for a in re.split(r"\bet\b|,|&", clean) if a.strip()]

        if len(app_names) > 1:
            for name in app_names:
                memory_engine.record_app_launch(name)
            result = apps.launch_multiple(app_names)
        else:
            app_name = clean or app_param
            memory_engine.record_app_launch(app_name)
            result = apps.launch(app_name)
            if "introuvable" in result.lower():
                site = browser._extract_site_name(original_text) or app_name
                result = browser.open_site(site)

        ui.show_toast(result, toast_type="success")
        return result
    if intent == "fermer_app":
        app_name = _extract_app_name(params.get("app", original_text))
        result = apps.close(app_name)
        ui.show_toast(result, toast_type="success" if "fermé" in result.lower() else "info")
        return result
    if intent == "volume":
        level = params.get("level", original_text)
        nums = re.findall(r"\d+", level)
        return system.set_volume(int(nums[0]) if nums else level)
    if intent == "luminosite":
        level = params.get("level", original_text)
        nums = re.findall(r"\d+", level)
        return system.set_brightness(int(nums[0]) if nums else level)
    if intent == "veille":
        return system.sleep()
    if intent == "reboot":
        return system.reboot()
    if intent == "shutdown":
        delay_match = re.search(r"(\d+)", original_text)
        delay = int(delay_match.group(1)) * 60 if delay_match else 0
        return system.shutdown(delay)
    if intent == "actu":
        if "tech" in original_text.lower():
            articles = news.get_top_headlines("technology")
        else:
            articles = news.get_top_headlines()
        return news.format_briefing(articles)
    if intent == "meteo":
        city = None
        for c in ("nantes", "couëron", "coueron", "paris"):
            if c in original_text.lower():
                city = c.capitalize()
                break
        data = weather.get_current(city)
        return weather.format_for_speech(data)
    if intent == "aviation_metar":
        metar_match = re.search(r"METAR\s+[A-Z]{4}\s+.*", original_text.upper())
        if metar_match:
            return aviation_expert.decode_metar_expert(metar_match.group(0))
        icao = params.get("icao") or _extract_icao(original_text)
        data = aviation.get_metar(icao)
        if "error" in data:
            return data["error"]
        return aviation_expert.decode_metar_expert(data.get("raw", ""))
    if intent == "aviation_taf":
        icao = params.get("icao") or _extract_icao(original_text)
        data = aviation.get_taf(icao)
        return aviation.format_taf_speech(data)
    if intent == "aviation_notam":
        icao = params.get("icao") or _extract_icao(original_text)
        notams = aviation.get_notams(icao)
        return ". ".join(notams[:3])
    if intent == "aviation_theory":
        return aviation_expert.answer_theory(original_text)
    if intent == "aviation_checklist":
        phase = re.sub(r".*checklist\s*", "", original_text, flags=re.I)
        return aviation_expert.checklist(phase or "avant décollage")
    if intent == "aviation_wind":
        return aviation_expert.handle(original_text)
    if intent == "aviation_nav":
        return aviation_expert.handle(original_text)
    if intent == "aviation_fuel":
        return aviation_expert.handle(original_text)
    if intent == "aviation_gonogo":
        return aviation_expert.handle(original_text)
    if intent == "aviation_radio":
        return aviation_expert.handle(original_text)
    if intent in (
        "math_calculate", "math_derive", "math_integrate", "math_solve_equation",
        "math_suite", "math_proba", "math_matrix", "math_limit", "math_general",
    ):
        return math_expert.handle(original_text)
    if intent in SEARCH_INTENTS:
        return _execute_ddg_search(intent, params, original_text)
    if intent == "search_web":
        query = params.get("query", original_text)
        browser.search_google(query)
        return "Recherche lancée dans Chrome"
    if intent == "search_aviation_news":
        return web_search.search_aviation_news()
    if intent == "nexus_open":
        path = params.get("path")
        return nexus_control.open_nexus(path) if path else nexus_control.open_nexus()
    if intent == "nexus_prompt":
        from actions import nexus

        if not nexus.is_enabled():
            return (
                "Nexus n'est pas encore configuré. "
                "Tu peux l'activer dans config.yaml une fois Nexus lancé."
            )
        query = params.get("query") or params.get("text") or original_text
        payload = re.sub(
            r"^.*?(?:demande|envoie|dis)\s+(?:à|a)\s+nexus\s+(?:de\s+)?",
            "",
            query,
            flags=re.I,
        ).strip()
        payload = re.sub(r"\b(?:dans|sur|via)\s+nexus\b", "", payload, flags=re.I).strip()
        nexus_m = re.search(r"^nexus\s+(?:fais|fait)\s+(.+)", payload, re.I)
        if nexus_m:
            payload = nexus_m.group(1).strip()
        return nexus.send_prompt(payload or query)
    if intent == "cursor_open":
        return cursor_control.open_cursor()
    if intent == "cursor_open_project":
        name = params.get("name", original_text)
        for kw in ("ouvre le projet", "ouvre", "projet", "dans cursor", "cursor"):
            name = re.sub(rf"\b{kw}\b", "", name, flags=re.I).strip()
        return cursor_control.open_project(name)
    if intent == "cursor_open_file":
        file_match = re.search(r"([\w./\\-]+\.(py|ts|tsx|js|jsx|json|yaml|md))", original_text, re.I)
        if file_match:
            return cursor_control.open_file_in_cursor(file_match.group(1))
        return cursor_control.handle(original_text)
    if intent == "cursor_generate_code":
        from actions import nexus

        request = params.get("request", original_text)
        if nexus.is_enabled() and nexus.is_available():
            return nexus.send_prompt(request)
        response, _ = _conversation(request, stream_to_ui=False)
        return response
    if intent == "cursor_prompt":
        payload = _extract_browser_text(original_text, "cursor_prompt")
        return browser.type_in_cursor_composer(payload or original_text)
    if intent == "browser_type":
        payload = _extract_browser_text(original_text, "browser_type")
        if re.search(r"[ée]cris .+ dans le navigateur", original_text, re.I):
            return browser.focus_and_type("", payload or original_text)
        return browser.type_on_current_page(payload or original_text)
    if intent == "browser_type_send":
        payload = _extract_browser_text(original_text, "browser_type_send")
        return browser.type_and_send(payload or original_text)
    if intent == "browser_type_claude":
        payload = _extract_browser_text(original_text, "browser_type_claude")
        return browser.type_in_claude(payload or original_text)
    if intent in ("browser_open_site", "browser_open_url", "ouvrir_site"):
        site = params.get("site") or _extract_site_for_browser(params, original_text)
        browser_param = params.get("browser")
        if not site:
            return "Quel site veux-tu ouvrir ?"
        if site.startswith("http"):
            return browser.open_url(site, browser=browser_param)
        return browser.open_site(site, browser=browser_param)
    if intent == "browser_search_google":
        query = params.get("query", original_text)
        return browser.search_google(query)
    if intent == "browser_youtube_search":
        query = params.get("query", original_text)
        result = browser.search_youtube(query)
        return result or f"YouTube : {query}"
    if intent == "browser_youtube_control":
        return browser.youtube_control(params.get("action", original_text))
    if intent == "browser_spotify":
        return browser.spotify_web_control(original_text)
    if intent == "browser_new_tab":
        url_match = re.search(r"https?://\S+", original_text)
        return browser.open_new_tab(url_match.group(0) if url_match else None)
    if intent == "browser_close_tab":
        return browser.close_tab()
    if intent == "browser_close":
        return browser.close_browser()
    if intent == "browser_scroll":
        t = original_text.lower()
        direction = "up" if "haut" in t or "monte" in t else "down"
        return browser.scroll(direction)
    if intent == "browser_read_page":
        return browser.read_page_content()
    if intent == "browser_screenshot":
        return browser.take_screenshot()
    if intent == "browser_search_in_site":
        parsed = _extract_in_site_search(original_text)
        if parsed:
            query, site = parsed
            return browser.search_within_site(site, query)
        query = params.get("query", original_text)
        site = params.get("site", "")
        if site and query:
            return browser.search_within_site(site, query)
        return browser.search_google(original_text)
    if intent == "browser_search_page":
        query = _extract_page_search_query(original_text) or params.get("query", original_text)
        query = re.sub(r"^(?:cherche|trouve|recherche)\s+", "", query, flags=re.I).strip()
        return browser.search_current_page(query)
    if intent in DRIVE_INTENTS:
        return _handle_drive_intent(intent, params, original_text)
    if intent in ("minuteur", "alarme"):
        return timer.parse_and_set(original_text)
    if intent == "git":
        t = original_text.lower()
        if "statut" in t or "status" in t:
            return git.status()
        if "commit" in t:
            msg = re.sub(r".*message\s*", "", original_text, flags=re.I).strip()
            return git.commit(msg or "commit vocal")
        if "push" in t or "pousse" in t:
            return git.push()
        if "pull" in t:
            return git.pull()
        return git.status()
    if intent == "calcul":
        return math_expert.handle(original_text)
    if intent == "traduction":
        lang_match = re.search(r"en (\w+)", original_text, re.I)
        target = lang_match.group(1) if lang_match else "anglais"
        text_to_translate = re.sub(r"traduis.*?[,:]\s*", "", original_text, flags=re.I)
        return translator.translate(text_to_translate or original_text, target)
    if intent == "preset":
        t = original_text.lower()
        if any(w in t for w in ("désactive", "desactive", "quitte le mode", "sors du mode", "arrête le mode", "arrete le mode")):
            return presets.deactivate()
        preset = presets.match_in_text(original_text)
        if preset:
            return presets.activate(preset)
        return "Quel mode veux-tu activer ? (" + "/".join(presets.list_presets()) + ")"
    if intent == "clipboard_paste":
        text = clipboard.get_text()
        if not text.strip():
            return "Le presse-papier est vide."
        return text
    if intent == "clipboard_copy":
        return clipboard.copy_text(original_text)
    if intent == "ouvrir_fichier":
        path = params.get("path", original_text)
        return files.open_path(path)
    if intent == "calendar_add":
        start, end = google_calendar.parse_when(original_text)
        title = google_calendar.extract_title(original_text)
        if start is None:
            return f"À quelle date et heure veux-tu caler « {title} » ?"
        return google_calendar.create_event(title, start, end)
    if intent == "calendar_move":
        start, end = google_calendar.parse_when(original_text)
        title = google_calendar.extract_title(original_text)
        if start is None:
            return f"Vers quelle date et heure veux-tu déplacer « {title} » ?"
        return google_calendar.move_event(title, start, end)
    if intent == "calendar_delete":
        return google_calendar.delete_event(google_calendar.extract_title(original_text))
    if intent == "calendar_list":
        if not google_calendar.is_configured():
            return calendar_action.get_today_events()
        from datetime import timedelta

        now = datetime.now()
        t = original_text.lower()
        if "demain" in t:
            day = now + timedelta(days=1)
            events = google_calendar.list_events(
                time_min=day.replace(hour=0, minute=0, second=0, microsecond=0),
                time_max=day.replace(hour=23, minute=59, second=59, microsecond=0),
            )
            return google_calendar.describe_events(events, empty="Rien de prévu demain.")
        if "semaine" in t:
            events = google_calendar.list_events(time_max=now + timedelta(days=7))
            return google_calendar.describe_events(events, empty="Rien de prévu cette semaine.")
        events = google_calendar.list_events(
            time_max=now.replace(hour=23, minute=59, second=59, microsecond=0)
        )
        return google_calendar.describe_events(events, empty="Rien de prévu aujourd'hui.")
    if intent == "rappel":
        if "aujourd'hui" in original_text.lower() or "agenda" in original_text.lower():
            return calendar_action.get_today_events()
        return calendar_action.get_upcoming()
    if intent == "heure_date":
        now = datetime.now()
        return f"Il est {now.strftime('%H:%M')}, nous sommes le {now.strftime('%A %d %B %Y')}."
    if intent == "blague":
        joke, _ = _conversation("Raconte une blague courte en une phrase.", stream_to_ui=False)
        return joke
    if intent == "memoire":
        memory.extract_from_conversation(original_text)
        return "C'est noté, je m'en souviendrai."
    if intent == "historique":
        return get_history_summary()
    if intent == "daily_brief":
        return generate_daily_brief()
    if intent == "export_pdf":
        from actions.export_pdf import export_conversation

        messages = memory_engine.get_current_conversation_messages()
        title = memory_engine.get_current_conversation_title()
        path = export_conversation(messages, title=title)
        return f"Conversation exportée : {path}"
    if intent == "focus_mode_on":
        import focus
        import re

        duration = None
        m = re.search(r"(\d+)\s*(?:heure|h|minute|min)", original_text.lower())
        if m:
            val = int(m.group(1))
            duration = val * 60 if "heure" in original_text.lower() or " h" in original_text.lower() else val
        focus.set_focus_mode(True, duration)
        try:
            ui.update_focus_indicator(True)
        except Exception:
            pass
        return "Mode focus activé." + (f" Pendant {duration} minutes." if duration else "")
    if intent == "focus_mode_off":
        import focus

        focus.set_focus_mode(False)
        try:
            ui.update_focus_indicator(False)
        except Exception:
            pass
        return "Mode focus désactivé."
    if intent == "calendar_today":
        from actions import gcalendar

        if not gcalendar.is_configured():
            return "Google Calendar non configuré. Lance setup_google.py."
        events = gcalendar.get_today_events()
        if events:
            return "Aujourd'hui tu as : " + ", ".join(f"{e['time']} : {e['title']}" for e in events) + "."
        return "Tu n'as rien de prévu aujourd'hui."
    if intent == "calendar_upcoming":
        from actions import gcalendar

        if not gcalendar.is_configured():
            return "Google Calendar non configuré."
        events = gcalendar.get_upcoming_events(7)
        if events:
            lines = [f"{e['title']} ({e['start'][:10]})" for e in events[:5]]
            return "Dans les 7 prochains jours : " + ", ".join(lines) + "."
        return "Rien de prévu dans les 7 prochains jours."
    if intent == "calendar_create":
        from actions import gcalendar

        import dateparser

        if not gcalendar.is_configured():
            return "Google Calendar non configuré."
        dt = dateparser.parse(params.get("datetime_text", original_text), languages=["fr"])
        if not dt:
            return "Je n'ai pas compris la date/heure. Précise par exemple 'demain à 14h'."
        title = params.get("title", original_text)
        return gcalendar.create_event(title, dt, int(params.get("duration", 60)))
    if intent == "revision_plan":
        from actions.revision_planner import generate_plan

        return generate_plan()
    if intent == "german_mode_on":
        import german_mode

        german_mode.set_german_mode(True)
        return "Mode allemand activé. Ich spreche jetzt Deutsch."
    if intent == "german_mode_off":
        import german_mode

        german_mode.set_german_mode(False)
        return "Mode allemand désactivé. Retour au français."
    if intent == "run_macro":
        from actions import macros

        name = original_text.lower()
        for key in macros.list_macros():
            if key in name:
                return macros.run_macro(key, lambda step: ask_return_text(step) or step)
        return "Macro introuvable. Macros disponibles : " + ", ".join(macros.list_macros())
    if intent == "smarthome":
        from actions import smarthome

        t = original_text.lower()
        if "allume" in t or "active" in t:
            entity = params.get("entity_id", "light.salon")
            return smarthome.call_service("light", "turn_on", entity)
        if "éteins" in t or "eteins" in t or "coupe" in t:
            entity = params.get("entity_id", "light.salon")
            return smarthome.call_service("light", "turn_off", entity)
        return "Dis par exemple « allume la lumière » ou configure Home Assistant dans config.yaml."
    if intent == "social_discord":
        from actions import social

        return social.read_discord_unread()
    if intent == "drive_search":
        from actions import gdrive

        if gdrive.is_configured():
            files = gdrive.search_files(params.get("query", original_text))
            if files:
                return "Fichiers trouvés : " + ", ".join(f["name"] for f in files[:5])
            return "Aucun fichier trouvé."
        return _handle_drive_intent(intent, params, original_text)
    if intent == "drive_list":
        from actions import gdrive

        if gdrive.is_configured():
            files = gdrive.list_recent()
            if files:
                return "Fichiers récents : " + ", ".join(f["name"] for f in files[:5])
            return "Aucun fichier récent."
        return _handle_drive_intent(intent, params, original_text)
    return ""


def _route_action(intent_data: dict, original_text: str) -> str:
    intent = intent_data.get("intent", "question_libre")
    params = intent_data.get("params", {})
    return _route_with_intelligence(intent, params, original_text, stream_to_ui=True)


def _stream_and_speak(response: requests.Response, stream_to_ui: bool = True) -> tuple[str, bool]:
    """Stream le LLM et parle chaque phrase dès qu'elle est complète (file TTS ordonnée)."""
    tts_queue: list[str | None] = []
    spoke_streaming = False

    def _speak_worker() -> None:
        nonlocal spoke_streaming
        while True:
            if tts_queue:
                sentence = tts_queue.pop(0)
                if sentence is None:
                    break
                if len(sentence.strip()) > 2 and _should_speak_tts():
                    ui.set_status("speaking")
                    tts.speak(sentence, force=True, notify_finished=False)
                    spoke_streaming = True
            else:
                time.sleep(0.02)

    tts_thread: threading.Thread | None = None
    if stream_to_ui and _should_speak_tts():
        tts_thread = threading.Thread(target=_speak_worker, daemon=True, name="LLM-TTS")
        tts_thread.start()

    sentence_buffer = ""
    full_response = ""

    if stream_to_ui:
        ui.set_status("thinking")

    try:
        for line in response.iter_lines():
            if not line or _stop_stream.is_set():
                break
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue

            content = chunk.get("message", {}).get("content", "")
            if content:
                full_response += content
                sentence_buffer += content
                if stream_to_ui:
                    ui.append_assistant_text(content)

                if SENTENCE_END_RE.search(sentence_buffer.rstrip()):
                    sentence = sentence_buffer.strip()
                    if sentence and tts_thread is not None:
                        tts_queue.append(sentence)
                    sentence_buffer = ""

            if chunk.get("done"):
                break

        remainder = sentence_buffer.strip()
        if remainder:
            if tts_thread is not None:
                tts_queue.append(remainder)
            elif stream_to_ui and len(remainder) > 2 and _should_speak_tts():
                ui.set_status("speaking")
                tts.speak(remainder, force=True, notify_finished=False)
                spoke_streaming = True
    finally:
        if tts_thread is not None:
            tts_queue.append(None)
            tts_thread.join(timeout=30)

    if stream_to_ui:
        ui.finalize_assistant_message()

    return full_response, spoke_streaming


def _conversation(text: str, stream_to_ui: bool = True, intent: str = "question_libre") -> tuple[str, bool]:
    global _history

    _refresh_system_prompt()
    _history.append({"role": "user", "content": text})
    _trim_history()

    conv_mode = _get_conversation_mode()
    chat_model = resolve_model(text, intent)

    logger.debug("═══ PROMPT OLLAMA ═══")
    logger.debug("%s", text[:500])
    logger.debug("════════════════════")

    # Escalade « réflexion » : trop lent en mode vocal — réservé au mode écrit.
    if FORCED_MODEL is None and AUTO_ROUTING and conv_mode != "vocal" and _needs_reasoning(text):
        logger.info("Réflexion activée -> %s", REASONING_MODEL)
        if stream_to_ui:
            ui.set_status("thinking")
        answer, _ = _conversation_via_generate(REASONING_MODEL, max_tokens=2000, stream_to_ui=False)
        if not answer:
            _history.pop()
            _present_action_result("Ollama n'est pas disponible.")
            return "", False
        if stream_to_ui:
            ui.append_assistant_text(answer)
            ui.finalize_assistant_message()
        _history.append({"role": "assistant", "content": answer})
        _trim_history()
        logger.warning("═══ LLM RÉPONSE (reasoning): %s ═══", answer[:200])
        return answer, False

    max_tokens = 150 if conv_mode == "vocal" else 500
    full_response, spoke_streaming = _conversation_via_generate(
        chat_model,
        max_tokens=max_tokens,
        stream_to_ui=stream_to_ui,
    )

    if not full_response.strip():
        _history.pop()
        if stream_to_ui:
            ui.set_status("idle")
        return "", False

    logger.warning("═══ LLM RÉPONSE: %s ═══", full_response[:200])

    _history.append({"role": "assistant", "content": full_response})
    _trim_history()
    return full_response, spoke_streaming


def _describe_image_b64(image_b64: str, prompt: str) -> str:
    """Description vision via Ollama (sans streaming UI)."""
    try:
        response = requests.post(
            OLLAMA_CHAT_URL,
            json={
                "model": VISION_MODEL,
                "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
                "stream": False,
            },
            timeout=90,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("message", {}).get("content", "").strip()
    except requests.RequestException as exc:
        logger.error("Vision error: %s", exc)
        return f"Erreur analyse image: {exc}"


def analyze_homework_image(image_b64: str, user_prompt: str = "") -> str:
    """Analyse image devoir BAC : vision puis bascule heavy si résolution nécessaire."""
    correction_mode = any(
        kw in (user_prompt or "").lower()
        for kw in ("corrige", "correction", "devoir", "exercice", "note", "évalue", "evalue")
    )
    vision_prompt = (
        "Décris précisément le contenu de cette image : énoncé, correction, graphique… "
        "Transcris le texte et formules visibles."
    )
    if correction_mode:
        vision_prompt = (
            "Analyse ce devoir scanné ou photographié. Transcris l'énoncé, identifie "
            "les erreurs de l'élève si une correction est visible, sinon propose une correction détaillée."
        )
    description = _describe_image_b64(image_b64, vision_prompt)
    if not description or description.startswith("Erreur"):
        return description or "Impossible d'analyser l'image."
    needs_solving = any(kw in description.lower() for kw in (
        "énoncé", "exercice", "calculer", "démontrer", "résoudre", "déterminer"
    ))
    if correction_mode:
        return ask_return_text(
            f"Voici un devoir analysé:\n\n{description}\n\n"
            f"{'Question: ' + user_prompt if user_prompt else 'Corrige et explique les erreurs étape par étape.'}"
        )
    if needs_solving and not user_prompt:
        return ask_return_text(f"Voici un exercice transcrit:\n\n{description}\n\nRésous-le étape par étape.")
    if user_prompt:
        return ask_return_text(f"Contexte image: {description}\n\nQuestion: {user_prompt}")
    return description


def _build_history_text(max_turns: int = 6) -> str:
    """Construit un historique textuel compact pour le prompt actions."""
    lines: list[str] = []
    for msg in _history:
        if msg.get("role") == "system":
            continue
        role = "Utilisateur" if msg.get("role") == "user" else "ARIA"
        content = str(msg.get("content", "")).strip()
        if content:
            lines.append(f"{role}: {content}")
    if max_turns > 0:
        lines = lines[-max_turns * 2 :]
    return "\n".join(lines)


def _parse_action_response(response: str) -> tuple[str, str]:
    """
    Parse la réponse du LLM au format strict.
    Retourne (action_type, action_value).
    """
    response = response.strip()
    for prefix in ACTION_PREFIXES:
        if response.startswith(prefix):
            action_type = prefix.rstrip(":")
            action_value = response[len(prefix) :].strip()
            logger.info("Action parsée: %s → '%s'", action_type, action_value)
            return action_type, action_value

    logger.warning("Format non reconnu: '%s' → fallback CHAT", response[:100])
    return "CHAT", response


def _execute_parsed_action(action_type: str, action_value: str, original_text: str) -> str:
    """Exécute l'action parsée depuis la réponse LLM."""
    logger.info("Exécution: %s(%s)", action_type, action_value)

    if action_type == "OPEN_APP":
        result = apps.launch(action_value)
    elif action_type == "CLOSE_APP":
        result = apps.close(action_value)
    elif action_type == "SEARCH_WEB":
        result = browser.search_google(action_value)
    elif action_type == "OPEN_SITE":
        if action_value.startswith("http"):
            result = browser.open_url(action_value)
        else:
            result = browser.open_site(action_value)
    elif action_type == "VOLUME":
        try:
            result = system.set_volume(int(action_value))
        except ValueError:
            result = f"Niveau de volume invalide: {action_value}"
    elif action_type == "SCREENSHOT":
        result = system.screenshot()
    elif action_type == "PRESET":
        result = presets.activate(action_value)
    elif action_type == "METEO":
        import api_keys

        status = api_keys.check_status("openweather")
        data = (
            weather.get_current(action_value)
            if status.get("status") == "ok"
            else weather.get_current_free(action_value)
        )
        if "error" not in data:
            raw = (
                f"Météo à {data.get('city', action_value)}: {data.get('temp')}°C, "
                f"{data.get('description')}, vent {data.get('wind')} km/h"
            )
            result = _llm_format(f"Formate en une phrase naturelle: {raw}")
        else:
            result = f"Impossible d'obtenir la météo pour {action_value}"
    elif action_type == "TIMER":
        try:
            result = timer.set_timer(int(action_value))
        except (ValueError, TypeError):
            result = f"Durée invalide: {action_value}"
    elif action_type == "CHAT":
        result = action_value
    else:
        result = action_value

    logger.warning("═══ LLM→UI: '%s' ═══", str(result)[:200])
    return result


def ask_with_actions(text: str) -> str:
    """
    Route les commandes simples via format strict LLM.
    Fast intent regex en premier, puis classification Ollama.
    """
    fast = _fast_intent(text)
    if fast and fast[0] != "question_libre":
        intent, params = fast
        logger.info("Fast intent: %s", intent)
        result = _execute_action(intent, params, text)
        if result:
            logger.warning("═══ LLM→UI: '%s' ═══", str(result)[:200])
            return result

    model = resolve_model(text, intent="question_libre")
    conv_mode = _get_conversation_mode()

    history_text = _build_history_text()
    full_prompt = f"{ACTIONS_SYSTEM_PROMPT}\n\n{history_text}\nUtilisateur: {text}\nARIA:"

    logger.warning("═══ ask_with_actions → generate() model=%s ═══", model)

    raw_response = generate(
        full_prompt,
        model=model,
        stream=False,
        max_tokens=150 if conv_mode == "vocal" else 400,
        temperature=0.2,
    )

    if raw_response.startswith("Erreur"):
        logger.error("Erreur LLM: %s", raw_response)
        return "Désolé, je n'ai pas pu traiter ta demande."

    logger.warning("═══ ask_with_actions réponse: %s ═══", raw_response[:200])

    action_type, action_value = _parse_action_response(raw_response)
    return _execute_parsed_action(action_type, action_value, text)


def generate_daily_brief() -> str:
    import brief

    return brief.generate_daily_brief()


def ask(text: str, *, show_user: bool = True) -> None:
    """Point d'entrée principal — route vers le bon handler selon l'intent."""
    if not text or not text.strip():
        return

    logger.warning("═══ STT→LLM: '%s' ═══", text)

    memory_engine.get_engine().update_active_hours()

    import conversation_modes

    mode_response = conversation_modes.try_handle(text)
    if mode_response is not None:
        if show_user:
            ui.show_user_text(text)
        ui.append_assistant_text(mode_response)
        ui.finalize_assistant_message()
        _speak_already_displayed(mode_response)
        ui.set_status("idle")
        return

    custom = memory.match_custom_command(text)
    if custom:
        logger.info("Custom command matched: %s -> %s", text, custom)
        if show_user:
            ui.show_user_text(text)
        ui.set_status("thinking")
        sounds.play("thinking")
        # L'action personnalisée (ex: « dodo » -> « éteins le pc ») doit être routée
        # comme un vrai prompt (intent + exécution), pas envoyée telle quelle au chat.
        c_intent, c_params, _ = _resolve_intent_for_routing(custom)
        logger.info("Custom command routing intent: %s", c_intent)
        try:
            response = _route_with_intelligence(c_intent, c_params, custom, stream_to_ui=True)
            if response:
                _history.append({"role": "user", "content": text.strip()})
                _history.append({"role": "assistant", "content": response})
                _trim_history()
                _save_history()
        except Exception as exc:
            logger.error("Custom command error: %s", exc)
            sounds.play("error")
            _speak_response(f"Désolé, une erreur s'est produite: {exc}")
        ui.set_status("idle")
        return

    if show_user:
        ui.show_user_text(text)
    ui.set_status("thinking")
    sounds.play("thinking")

    intent, params, _confidence = _resolve_intent_for_routing(text)
    logger.info("Routing intent: %s", intent)

    _refresh_system_prompt()
    memory_engine.record_message("user", text, intent=intent, model=MODEL)
    memory_engine.record_intent(intent)
    memory_engine.add_to_conversation("user", text)

    try:
        if _get_conversation_mode() == "vocal":
            logger.warning("═══ ask() → ask_with_actions() (vocal) ═══")
            response = ask_with_actions(text)
            if response:
                _speak_response(response)
                _history.append({"role": "user", "content": text.strip()})
                _history.append({"role": "assistant", "content": response})
                _trim_history()
                _save_history()
                memory.extract_from_conversation(text)
                memory_engine.record_message("assistant", response, model=MODEL)
                memory_engine.extract_preferences(text, response)
                memory_engine.add_to_conversation("assistant", response)
                memory_engine.get_engine().save_current_conversation()
                _process_memory_learning(text, response)
        else:
            logger.warning("═══ ask() → _route_with_intelligence() (écrit) ═══")
            response = _route_with_intelligence(intent, params, text, stream_to_ui=True)
            if response:
                _history.append({"role": "user", "content": text.strip()})
                _history.append({"role": "assistant", "content": response})
                _trim_history()
                _save_history()
                memory.extract_from_conversation(text)
                memory_engine.record_message("assistant", response, model=MODEL)
                memory_engine.extract_preferences(text, response)
                memory_engine.add_to_conversation("assistant", response)
                memory_engine.get_engine().save_current_conversation()
                _process_memory_learning(text, response)
    except Exception as exc:
        logger.error("Routing error: %s", exc)
        sounds.play("error")
        error_msg = f"Désolé, une erreur s'est produite: {exc}"
        ui.append_assistant_text(error_msg)
        ui.finalize_assistant_message()
        _speak_response(error_msg)

    ui.set_status("idle")


def ask_return_text(text: str) -> str:
    """Version de ask() qui retourne le texte au lieu de streamer vers l'UI."""
    if not text or not text.strip():
        return ""

    memory_engine.get_engine().update_active_hours()

    custom = memory.match_custom_command(text)
    if custom:
        response, _ = _conversation(custom, stream_to_ui=False)
        return response or custom

    intent, params, _confidence = _resolve_intent_for_routing(text)

    _refresh_system_prompt()
    memory_engine.record_message("user", text, intent=intent, model=MODEL)
    memory_engine.record_intent(intent)
    memory_engine.add_to_conversation("user", text)

    logger.debug("═══ PROMPT OLLAMA ═══")
    logger.debug("%s", text[:500])
    logger.debug("════════════════════")

    try:
        response = _route_with_intelligence(intent, params, text, stream_to_ui=False)
        if response:
            logger.info("═══ LLM RÉPONSE ═══")
            logger.info("%s", response[:300])
            logger.info("═══════════════════")
            _history.append({"role": "user", "content": text.strip()})
            _history.append({"role": "assistant", "content": response})
            _trim_history()
            _save_history()
            memory.extract_from_conversation(text)
            memory_engine.record_message("assistant", response, model=MODEL)
            memory_engine.extract_preferences(text, response)
            memory_engine.add_to_conversation("assistant", response)
            _process_memory_learning(text, response)
            return response
    except Exception:
        logger.exception("ask_return_text routing failed")

    response, _ = _conversation(text, stream_to_ui=False)
    if response:
        logger.info("═══ LLM RÉPONSE ═══")
        logger.info("%s", response[:300])
        logger.info("═══════════════════")
        _save_history()
        memory.extract_from_conversation(text)
        memory_engine.record_message("assistant", response, model=MODEL)
        memory_engine.extract_preferences(text, response)
        memory_engine.add_to_conversation("assistant", response)
        _process_memory_learning(text, response)
        return response

    return "Désolé, je n'ai pas pu répondre."


def _stream_response(response, user_text: str = "", model: str = MODEL_HEAVY) -> str:
    """Stream une réponse Ollama vers l'UI et TTS."""
    global _history

    full_response, spoke_streaming = _stream_and_speak(response, stream_to_ui=True)

    if not full_response.strip():
        ui.set_status("idle")
        return ""

    logger.info("═══ LLM RÉPONSE ═══")
    logger.info("%s", full_response[:300])
    logger.info("═══════════════════")

    _history.append({"role": "assistant", "content": full_response})
    _trim_history()
    _save_history()
    if user_text:
        memory_engine.record_message("assistant", full_response, model=model)
        memory_engine.extract_preferences(user_text, full_response)
        memory_engine.add_to_conversation("assistant", full_response)
        _process_memory_learning(user_text, full_response)
    _finish_streamed_response(full_response, already_spoken=spoke_streaming)
    return full_response


def ask_with_image(question: str, image_path: str) -> None:
    """Envoie une image à Ollama avec un modèle vision (minicpm-v / llava)."""
    import base64

    global _history

    _refresh_system_prompt()
    memory_engine.record_message("user", question, model=VISION_MODEL)
    memory_engine.add_to_conversation("user", question)
    ui.set_status("thinking")
    sounds.play("thinking")

    try:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        response = requests.post(
            OLLAMA_CHAT_URL,
            json={
                "model": VISION_MODEL,
                "messages": [{
                    "role": "user",
                    "content": question,
                    "images": [img_b64],
                }],
                "stream": True,
            },
            stream=True,
            timeout=60,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        err = str(exc)
        if "404" in err or "400" in err:
            _speak_response(
                f"Le modèle de vision n'est pas installé. Lance : ollama pull {VISION_MODEL}"
            )
        else:
            _speak_response(f"Erreur analyse image: {exc}")
        return
    except Exception as exc:
        _speak_response(f"Erreur analyse image: {exc}")
        return

    _history.append({"role": "user", "content": question})
    _trim_history()
    _stream_response(response, user_text=question, model=VISION_MODEL)


def ask_with_images_and_text(
    prompt: str,
    images_b64: list,
    text_contents: list | None = None,
) -> None:
    """Envoie plusieurs images + texte en une seule requête vision."""
    global _history

    content = prompt
    if text_contents:
        content += "\n\nFichiers joints:\n" + "\n\n".join(text_contents)

    _refresh_system_prompt()
    memory_engine.record_message("user", prompt, model=VISION_MODEL)
    memory_engine.add_to_conversation("user", prompt)
    ui.set_status("thinking")
    sounds.play("thinking")

    try:
        response = requests.post(
            OLLAMA_CHAT_URL,
            json={
                "model": VISION_MODEL,
                "messages": [{
                    "role": "user",
                    "content": content,
                    "images": images_b64,
                }],
                "stream": True,
            },
            stream=True,
            timeout=120,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        err = str(exc)
        if "404" in err or "400" in err:
            _speak_response(
                f"Le modèle de vision n'est pas installé. Lance : ollama pull {VISION_MODEL}"
            )
        else:
            _speak_response(f"Erreur analyse fichiers: {exc}")
        return
    except Exception as exc:
        _speak_response(f"Erreur analyse fichiers: {exc}")
        return

    _history.append({"role": "user", "content": prompt})
    _trim_history()
    _stream_response(response, user_text=prompt, model=VISION_MODEL)


def ask_with_file(question: str, file_path: str, filename: str) -> None:
    """Lit un fichier texte et l'envoie à Ollama pour analyse."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(8000)
        prompt = f"Fichier: {filename}\n\nContenu:\n{content}\n\nQuestion: {question}"
        ask(prompt, show_user=False)
    except Exception as e:
        _speak_response(f"Impossible de lire le fichier: {e}")


def ask_with_pdf(question: str, pdf_path: str) -> None:
    """Extrait le texte d'un PDF et l'analyse."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        pages_text = []
        for page in reader.pages[:5]:
            pages_text.append(page.extract_text() or "")
        content = "\n".join(pages_text)[:8000] or "PDF illisible"
        prompt = f"PDF analysé:\n{content}\n\nQuestion: {question}"
        ask(prompt, show_user=False)
    except Exception:
        logger.exception("PDF extraction failed")
        ask_with_file(question, pdf_path, "document.pdf")


def ask_with_video(question: str, video_path: str) -> None:
    """Extrait une frame d'une vidéo et l'analyse."""
    import tempfile

    frame_path = None
    try:
        frame_path = tempfile.mktemp(suffix=".jpg")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.run(
            ["ffmpeg", "-i", video_path, "-ss", "00:00:01", "-frames:v", "1", frame_path, "-y"],
            capture_output=True,
            timeout=15,
            creationflags=flags,
        )
        if os.path.exists(frame_path):
            ask_with_image(question, frame_path)
        else:
            _speak_response("Impossible d'extraire une image de la vidéo")
    except Exception as e:
        _speak_response(f"Erreur vidéo: {e}")
    finally:
        if frame_path and os.path.exists(frame_path):
            try:
                os.unlink(frame_path)
            except OSError:
                pass


def clear_history() -> None:
    global _history, _last_clear_time
    now = time.monotonic()
    if now - _last_clear_time < 1.0:
        return
    _last_clear_time = now
    _history = [{"role": "system", "content": _build_dynamic_system_prompt()}]
    _save_history()
    logger.info("History cleared")


def load_conversation_messages(messages: list) -> None:
    global _history
    _refresh_system_prompt()
    for m in messages:
        role = m.get("role", "user")
        text = m.get("text") or m.get("content", "")
        if role in ("user", "assistant") and text:
            _history.append({"role": role, "content": text})
    _trim_history()
    _save_history()


def get_history_summary() -> str:
    if len(_history) <= 1:
        return "Pas de conversation en cours."
    summary_prompt = "Résume brièvement notre conversation en 2-3 phrases."
    response = _ollama_request(
        _history + [{"role": "user", "content": summary_prompt}],
        stream=False,
    )
    if response is None:
        return "Impossible de résumer, Ollama indisponible."
    try:
        return response.json()["message"]["content"]
    except (KeyError, json.JSONDecodeError):
        return "Résumé indisponible."
