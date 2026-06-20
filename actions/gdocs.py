"""
gdocs.py — Création et édition de Google Docs via l'API officielle.
Nécessite setup_google.py pour l'authentification OAuth2 (une seule fois).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_active_doc: dict | None = None


def _get_docs_service():
    """Retourne le service Google Docs authentifié."""
    from actions.google_auth import get_credentials
    from googleapiclient.discovery import build

    creds = get_credentials()
    if not creds:
        raise RuntimeError("Google non configuré. Lance : python setup_google.py")
    return build("docs", "v1", credentials=creds)


def _get_drive_service():
    from actions.google_auth import get_credentials
    from googleapiclient.discovery import build

    creds = get_credentials()
    if not creds:
        raise RuntimeError("Google non configuré.")
    return build("drive", "v3", credentials=creds)


def is_configured() -> bool:
    """Vérifie si Google est configuré."""
    try:
        from actions.google_auth import is_configured as _is_configured

        return _is_configured()
    except Exception:
        return False


def get_active_doc() -> dict | None:
    """Retourne le doc actif de la session."""
    return _active_doc


def set_active_doc(doc_id: str, title: str, url: str) -> None:
    """Définit le doc actif."""
    global _active_doc
    _active_doc = {"id": doc_id, "title": title, "url": url}
    logger.info("Doc actif: %s (%s)", title, doc_id)


def clear_active_doc() -> None:
    global _active_doc
    _active_doc = None


def create_doc(title: str, initial_content: str = "") -> dict:
    """
    Crée un nouveau Google Doc.

    Returns:
        {'id': str, 'title': str, 'url': str}
    """
    if not is_configured():
        raise RuntimeError("Google non configuré. Lance : python setup_google.py")

    docs_service = _get_docs_service()

    doc = docs_service.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]
    url = f"https://docs.google.com/document/d/{doc_id}/edit"

    if initial_content:
        append_to_doc(doc_id, initial_content)

    logger.info("Doc créé: '%s' → %s", title, url)
    return {"id": doc_id, "title": title, "url": url}


def append_to_doc(doc_id: str, content: str) -> bool:
    """Ajoute du contenu à la FIN d'un Google Doc existant."""
    if not is_configured():
        raise RuntimeError("Google non configuré.")

    docs_service = _get_docs_service()

    doc = docs_service.documents().get(documentId=doc_id).execute()
    end_index = doc["body"]["content"][-1]["endIndex"] - 1

    requests_body = [
        {
            "insertText": {
                "location": {"index": end_index},
                "text": f"\n{content}",
            }
        }
    ]

    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests_body},
    ).execute()

    logger.info("Contenu ajouté au doc %s (%d chars)", doc_id, len(content))
    return True


def write_section_to_doc(
    doc_id: str,
    title: str,
    content: str,
    heading_level: int = 1,
) -> bool:
    """Ajoute une section avec titre formaté dans un Google Doc."""
    if not is_configured():
        raise RuntimeError("Google non configuré.")

    docs_service = _get_docs_service()

    doc = docs_service.documents().get(documentId=doc_id).execute()
    end_index = doc["body"]["content"][-1]["endIndex"] - 1

    heading_style = {
        1: "HEADING_1",
        2: "HEADING_2",
        3: "HEADING_3",
    }.get(heading_level, "HEADING_2")

    full_text = f"\n{title}\n{content}\n"

    requests_body = [
        {
            "insertText": {
                "location": {"index": end_index},
                "text": full_text,
            }
        },
        {
            "updateParagraphStyle": {
                "range": {
                    "startIndex": end_index + 1,
                    "endIndex": end_index + 1 + len(title),
                },
                "paragraphStyle": {"namedStyleType": heading_style},
                "fields": "namedStyleType",
            }
        },
    ]

    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests_body},
    ).execute()

    return True


def get_doc_info(doc_id: str) -> dict:
    """Retourne les infos d'un doc (titre, url)."""
    try:
        docs_service = _get_docs_service()
        doc = docs_service.documents().get(documentId=doc_id).execute()
        return {
            "id": doc_id,
            "title": doc.get("title", ""),
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        }
    except Exception as exc:
        logger.error("Erreur get_doc_info: %s", exc)
        return {}


def open_doc_in_browser(doc_id: str) -> None:
    """Ouvre le doc dans Chrome."""
    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for path in chrome_paths:
        if os.path.exists(path):
            subprocess.Popen([path, url], creationflags=CREATE_NO_WINDOW)
            return
    os.startfile(url)
