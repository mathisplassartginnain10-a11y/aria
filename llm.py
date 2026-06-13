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
    clipboard,
    cursor_control,
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
    'fast':   'llama3.1:8b-instruct-q8_0',
    'medium': 'llama3.1:8b-instruct-q8_0',
    'heavy':  'qwen3:14b',
    'code':   'qwen2.5-coder:14b',
}

MODEL: str = _config.get("model", MODELS["heavy"])
MODEL_FAST: str = _config.get("model_fast", MODELS["fast"])
MODEL_HEAVY: str = _config.get("model_heavy", MODELS["heavy"])
MODEL_CODE: str = _config.get("model_code", MODELS["code"])
VISION_MODEL: str = _config.get("vision_model", "minicpm-v")
INTENT_MODEL: str = MODEL_FAST
MAX_HISTORY: int = _config["max_history"]
BASE_SYSTEM_PROMPT: str = """Tu es ARIA, l'assistant personnel de Mathi, lycéen en Première à Couëron.
Tu le connais intimement : ses projets (ARIA l'assistant vocal, IMPERO, PPL DR400 à LFRS),
son style de communication direct et ses fautes de frappe caractéristiques.
Tu réponds toujours en tutoiement, directement, sans préambule.
Tu maîtrises : Python, pywebview, Ollama, aviation PPL, maths Première, gaming PC.
Jamais de "Bien sûr !", "Absolument !" ou politesse excessive."""
SYSTEM_PROMPT = BASE_SYSTEM_PROMPT
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
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
    "browser_open_url", "browser_search_google", "browser_youtube_search",
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
    "search_web", "search_news", "search_geopolitics", "cherche", "recherche", "recherche_web",
})

DRIVE_INTENTS = frozenset({
    "drive_create_doc", "drive_write_doc", "drive_search", "drive_open",
    "drive_list", "drive_create_folder", "drive_share",
})

FAST_REGEX: dict[str, str] = {
    r"\b(lance|ouvre|démarre|demarre|start)\b.+": "lancer_app",
    r"\b(ferme|quitte|stop|arrête|arrete)\b.+": "fermer_app",
    r"\b(volume|son)\b.+(up|down|monte|baisse|\d+)": "volume",
    r"\b(météo|meteo|température|temperature|temps)\b": "meteo",
    r"\b(heure|date|aujourd'hui|aujourdhui)\b": "heure_date",
    r"\b(minuteur|timer|dans \d+ min)\b": "minuteur",
}

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

_history: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]


def _fast_intent(text: str) -> str | None:
    """Détecte l'intent sans appel LLM via regex — latence 0ms."""
    text_lower = text.lower()
    for pattern, intent in FAST_REGEX.items():
        if re.search(pattern, text_lower):
            return intent
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
    return dynamic_system


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
    num_predict: int = 2000,
) -> requests.Response | None:
    payload = {
        "model": model or MODEL,
        "messages": messages,
        "stream": stream,
        "options": {"num_predict": num_predict},
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
        except requests.RequestException:
            logger.warning("Ollama request failed (attempt %d/%d)", attempt + 1, retries)
            time.sleep(1)
    return None


def _detect_intent(text: str) -> dict:
    fast = _fast_intent(text)
    if fast:
        logger.info("Fast intent (regex): %s", fast)
        return {"intent": fast, "params": _fast_intent_params(fast, text), "confidence": 0.95}

    rule = _rule_based_intent(text)
    if rule.get("intent") != "question_libre" and rule.get("confidence", 0) >= 0.85:
        logger.info("Rule intent: %s", rule.get("intent"))
        return rule

    prompt = (
        f'Classify this command in ONE word from this list:\n'
        f'lancer_app|fermer_app|volume|meteo|actu|aviation|maths|code|recherche|question\n'
        f'If multiple apps are mentioned (e.g. "lance Spotify et Discord"), classify as lancer_app.\n'
        f'Command: "{text}"\n'
        f'Answer with just the category:'
    )
    response = _ollama_request(
        [{"role": "user", "content": prompt}],
        stream=False,
        model=INTENT_MODEL,
        num_predict=10,
    )
    if response is None:
        return {"intent": "question_libre", "params": {}, "confidence": 0.0}

    try:
        content = response.json()["message"]["content"].strip().lower()
        content = re.sub(r"[^a-z_]", "", content.split()[0] if content.split() else content)
        mapped = INTENT_CATEGORY_MAP.get(content)
        if mapped:
            rule_params = _rule_based_intent(text)
            params = rule_params.get("params", {}) if rule_params.get("intent") == mapped else _fast_intent_params(mapped, text)
            logger.info("LLM intent (%s): %s", INTENT_MODEL, mapped)
            return {"intent": mapped, "params": params, "confidence": 0.88}
    except (json.JSONDecodeError, KeyError, IndexError):
        logger.exception("Intent parsing failed")

    return _rule_based_intent(text)


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


def _handle_drive_intent(intent: str, params: dict, original_text: str) -> str:
    """Route les intents Drive vers le MCP Google Drive (fallback navigateur)."""
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
        (r"va sur |ouvre https?://", "browser_open_url", {"url": text}),
        # Saisie universelle navigateur / Claude / Cursor
        (r"demande\s+(?:à|a)\s+claude", "browser_type_claude", {"text": text}),
        (r"envoie.*cursor|demande\s+(?:à|a)\s+cursor", "cursor_prompt", {"text": text}),
        (r"tape .+ sur (?:la |cette )?page", "browser_type", {"text": text}),
        (r"[ée]cris .+ dans le navigateur", "browser_type", {"text": text}),
        (r"^envoie .+ sur (?:la |cette )?page", "browser_type_send", {"text": text}),
        (r"^envoie(?!.*(?:cursor|claude|sur la page|sur cette page))", "browser_type_send", {"text": text}),
        # Cursor v3
        (r"ouvre cursor$|ouvre cursor\s*$|lance cursor", "cursor_open", {}),
        (r"projet.*cursor|cursor.*projet", "cursor_open_project", {"name": text}),
        (r"ouvre.*\.(py|ts|tsx|js)|fichier.*cursor", "cursor_open_file", {"path": text}),
        (r"génère|genere|crée|cree|dans cursor|corrige.*cursor", "cursor_generate_code", {"request": text}),
        # Search v3 — news before generic web search
        (r"cherche.*nouvelles|cherche.*actualit|recherche.*nouvelles|nouvelles sur|dernières nouvelles", "search_news", {"query": text}),
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
        (r"actu|actualité|news", "actu", {}),
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
        (r"rappel|agenda|événement|aujourd'hui", "rappel", {"text": text}),
        (r"quelle heure|quelle date|heure", "heure_date", {}),
        (r"blague", "blague", {}),
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


def _speak_response(summary: str) -> None:
    _present_action_result(summary)


def _present_action_result(result: str) -> None:
    """Affiche le résultat d'une action dans le chat puis le lit via TTS."""
    if not result or not result.strip():
        ui.set_status("idle")
        return
    ui.append_assistant_text(result)
    ui.finalize_assistant_message()
    ui.set_status("speaking")
    tts.speak(result)
    ui.set_status("idle")


def _finish_streamed_response(full_response: str, *, already_spoken: bool = False) -> None:
    """Lit via TTS une réponse déjà streamée et affichée token par token."""
    if not full_response or not full_response.strip():
        ui.set_status("idle")
        return
    if already_spoken:
        ui.set_status("idle")
        return
    ui.set_status("speaking")
    tts.speak(full_response)
    ui.set_status("idle")


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
    if intent == "search_aviation_news":
        return web_search.search_aviation_news()
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
        request = params.get("request", original_text)
        result = cursor_control.voice_to_cursor(request)
        return result
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
    if intent == "browser_open_url":
        url_match = re.search(r"(https?://\S+|\b[\w-]+\.(com|fr|org|net|io)\b[\w./-]*)", original_text, re.I)
        url = url_match.group(1) if url_match else original_text
        url = re.sub(r"^(va sur|ouvre)\s*", "", url, flags=re.I).strip()
        return browser.open_url(url)
    if intent == "browser_search_google":
        query = params.get("query", original_text)
        return browser.search_google(query)
    if intent == "browser_youtube_search":
        return browser.search_youtube(original_text)
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
        if "désactive" in original_text.lower() or "desactive" in original_text.lower():
            return presets.deactivate()
        for name in presets.list_presets():
            if name in original_text.lower():
                return presets.activate(name)
        return "Quel mode veux-tu activer ? Étude, vol, gaming, détente ou nuit."
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
    return ""


def _route_action(intent_data: dict, original_text: str) -> str:
    intent = intent_data.get("intent", "question_libre")
    params = intent_data.get("params", {})
    defer_ui = intent == "blague" or intent in SEARCH_INTENTS

    try:
        result = _dispatch_action(intent, params, original_text)
    except Exception:
        logger.exception("Action routing failed for intent %s", intent)
        sounds.play("error")
        ui.show_error("Une erreur s'est produite.")
        result = "Désolé, une erreur s'est produite."

    if result and result.strip() and not defer_ui:
        _present_action_result(result)
    return result


def _conversation(text: str, stream_to_ui: bool = True) -> tuple[str, bool]:
    global _history

    _refresh_system_prompt()
    _history.append({"role": "user", "content": text})
    _trim_history()

    response = _ollama_request(_history, stream=True)
    if response is None:
        _history.pop()
        msg = "Ollama n'est pas disponible."
        _present_action_result(msg)
        return "", False

    sentence_buffer = ""
    full_response = ""
    spoke_streaming = False
    sentence_endings = (". ", "! ", "? ", ".\n", "!\n", "?\n")

    if stream_to_ui:
        ui.set_status("thinking")

    for line in response.iter_lines():
        if not line:
            continue
        chunk = json.loads(line)
        content = chunk.get("message", {}).get("content", "")
        if content:
            full_response += content
            sentence_buffer += content
            if stream_to_ui:
                ui.append_assistant_text(content)

            if stream_to_ui:
                if any(sentence_buffer.endswith(ending) for ending in sentence_endings):
                    sentence = sentence_buffer.strip()
                    if sentence and len(sentence) > 5:
                        ui.set_status("speaking")
                        threading.Thread(target=tts.speak, args=(sentence,), daemon=True).start()
                        spoke_streaming = True
                        sentence_buffer = ""

        if chunk.get("done"):
            break

    if stream_to_ui and sentence_buffer.strip():
        remainder = sentence_buffer.strip()
        if len(remainder) > 5:
            ui.set_status("speaking")
            threading.Thread(target=tts.speak, args=(remainder,), daemon=True).start()
            spoke_streaming = True

    if stream_to_ui:
        ui.finalize_assistant_message()

    if not full_response.strip():
        _history.pop()
        ui.set_status("idle")
        return "", False

    _history.append({"role": "assistant", "content": full_response})
    _trim_history()
    return full_response, spoke_streaming


def ask(text: str, *, show_user: bool = True) -> None:
    if not text or not text.strip():
        return

    memory_engine.get_engine().update_active_hours()

    custom = memory.match_custom_command(text)
    if custom:
        logger.info("Custom command matched: %s", custom)
        if show_user:
            ui.show_user_text(text)
        ui.set_status("thinking")
        response = _route_action({"intent": "question_libre", "params": {}}, custom)
        if response:
            return
        _present_action_result(custom)
        return

    if show_user:
        ui.show_user_text(text)
    ui.set_status("thinking")
    sounds.play("thinking")

    intent_data = _detect_intent(text)
    logger.info("Intent: %s (confidence=%.2f)", intent_data.get("intent"), intent_data.get("confidence", 0))

    confidence = intent_data.get("confidence", 0)
    intent = intent_data.get("intent", "question_libre")

    _refresh_system_prompt()
    memory_engine.record_message("user", text, intent=intent, model=MODEL)
    memory_engine.record_intent(intent)
    memory_engine.add_to_conversation("user", text)

    if confidence > 0.8 and intent != "question_libre":
        response = _route_action(intent_data, text)
        if response:
            _history.append({"role": "user", "content": text.strip()})
            _history.append({"role": "assistant", "content": response})
            _trim_history()
            _save_history()
            memory.extract_from_conversation(text)
            memory_engine.record_message("assistant", response, model=MODEL)
            memory_engine.extract_preferences(text, response)
            memory_engine.add_to_conversation("assistant", response)
            _process_memory_learning(text, response)
            if intent == "blague":
                _present_action_result(response)
            return

    response, spoke_streaming = _conversation(text)
    if response:
        logger.info("Assistant: %s", response[:200])
        _save_history()
        memory.extract_from_conversation(text)
        memory_engine.record_message("assistant", response, model=MODEL)
        memory_engine.extract_preferences(text, response)
        memory_engine.add_to_conversation("assistant", response)
        _process_memory_learning(text, response)
        _finish_streamed_response(response, already_spoken=spoke_streaming)
    else:
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

    intent_data = _detect_intent(text)
    confidence = intent_data.get("confidence", 0)
    intent = intent_data.get("intent", "question_libre")
    params = intent_data.get("params", {})

    _refresh_system_prompt()
    memory_engine.record_message("user", text, intent=intent, model=MODEL)
    memory_engine.record_intent(intent)
    memory_engine.add_to_conversation("user", text)

    if confidence > 0.8 and intent != "question_libre":
        try:
            response = _dispatch_action(intent, params, text)
            if response:
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
            logger.exception("ask_return_text action failed")

    response, _ = _conversation(text, stream_to_ui=False)
    if response:
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

    sentence_buffer = ""
    full_response = ""
    spoke_streaming = False
    sentence_endings = (". ", "! ", "? ", ".\n", "!\n", "?\n")
    ui.set_status("thinking")

    for line in response.iter_lines():
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        token = data.get("message", {}).get("content", "")
        if token:
            full_response += token
            sentence_buffer += token
            ui.append_assistant_text(token)

            if any(sentence_buffer.endswith(p) for p in sentence_endings):
                sentence = sentence_buffer.strip()
                if sentence and len(sentence) > 5:
                    ui.set_status("speaking")
                    threading.Thread(target=tts.speak, args=(sentence,), daemon=True).start()
                    spoke_streaming = True
                    sentence_buffer = ""

        if data.get("done"):
            break

    if sentence_buffer.strip():
        remainder = sentence_buffer.strip()
        if len(remainder) > 5:
            ui.set_status("speaking")
            threading.Thread(target=tts.speak, args=(remainder,), daemon=True).start()
            spoke_streaming = True

    ui.finalize_assistant_message()

    if not full_response.strip():
        ui.set_status("idle")
        return ""

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
    global _history
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
