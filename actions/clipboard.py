import logging

import pyperclip

import tts
import app_paths

logger = logging.getLogger(__name__)


def copy_text(text: str) -> str:
    try:
        pyperclip.copy(text)
        return "Texte copié dans le presse-papier."
    except Exception:
        logger.exception("Copy failed")
        return "Impossible de copier dans le presse-papier."


def get_text() -> str:
    try:
        return pyperclip.paste()
    except Exception:
        logger.exception("Paste read failed")
        return ""


def read_clipboard() -> str:
    text = get_text()
    if not text.strip():
        return "Le presse-papier est vide."
    tts.speak(text)
    return f"Contenu du presse-papier : {text[:200]}"


def paste_as_voice() -> str:
    text = get_text()
    if not text.strip():
        return "Le presse-papier est vide."
    tts.speak(text)
    return "Lecture du presse-papier en cours."