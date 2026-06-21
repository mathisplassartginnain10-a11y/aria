"""Coller du texte dans la fenêtre active via presse-papier."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


def type_to_active_window(text: str, *, max_chars: int = 4000) -> str:
    """Copie le texte dans le presse-papier puis envoie Ctrl+V."""
    if not text or not str(text).strip():
        return "Aucun texte à écrire."

    payload = str(text).strip()
    if len(payload) > max_chars:
        return f"Texte trop long ({len(payload)} caractères). Maximum : {max_chars}."

    try:
        import pyautogui
        import pyperclip
    except ImportError as exc:
        logger.error("type_anywhere deps missing: %s", exc)
        return "pyautogui ou pyperclip manquant pour écrire dans l'application active."

    try:
        pyperclip.copy(payload)
        time.sleep(0.12)
        pyautogui.hotkey("ctrl", "v")
        preview = payload[:80] + ("…" if len(payload) > 80 else "")
        return f"Texte collé dans l'application active : « {preview} »"
    except Exception as exc:
        logger.exception("type_to_active_window failed")
        return f"Impossible d'écrire dans l'application active : {exc}"
