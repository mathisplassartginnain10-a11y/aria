import json
import logging

import requests
import yaml
import app_paths

logger = logging.getLogger(__name__)

_CONFIG_PATH = app_paths.config_path()
with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

MODEL = _config.get("model", "qwen3:14b")
OLLAMA_CHAT = "http://localhost:11434/api/chat"

LANG_NAMES = {
    "fr": "français",
    "en": "anglais",
    "de": "allemand",
    "es": "espagnol",
    "it": "italien",
    "anglais": "anglais",
    "allemand": "allemand",
    "espagnol": "espagnol",
    "italien": "italien",
    "français": "français",
}


def detect_language(text: str) -> str:
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": f"Detect the language of this text. Reply with only the ISO 639-1 code (fr, en, de, es, it):\n{text}",
            }
        ],
        "stream": False,
    }
    try:
        response = requests.post(OLLAMA_CHAT, json=payload, timeout=30)
        response.raise_for_status()
        code = response.json()["message"]["content"].strip().lower()[:2]
        return code
    except Exception:
        return "fr"


def translate(text: str, target_lang: str) -> str:
    lang = LANG_NAMES.get(target_lang.lower(), target_lang)
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Traduis ce texte en {lang}. Réponds uniquement avec la traduction, sans explication :\n{text}"
                ),
            }
        ],
        "stream": False,
    }
    try:
        response = requests.post(OLLAMA_CHAT, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()["message"]["content"].strip()
    except requests.RequestException:
        logger.exception("Translation failed")
        return "Traduction indisponible, Ollama n'est pas accessible."