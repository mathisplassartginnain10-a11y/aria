"""
gdocs.py — Création et édition de Google Docs via l'API officielle.
Nécessite setup_google.py pour l'authentification OAuth2 (une seule fois).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_active_doc: dict | None = None


def _get_docs_service():
    from actions.google_auth import build_service

    return build_service("docs", "v1")


def _get_drive_service():
    from actions.google_auth import build_service

    return build_service("drive", "v3")


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
    try:
        import ui_bridge as ui

        ui.notify_active_gdoc(_active_doc)
    except Exception:
        pass


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


def write_markdown_to_doc(doc_id: str, markdown: str) -> bool:
    """Écrit du markdown avec titres ## en sections H2 formatées."""
    if not markdown.strip():
        return False
    parts = re.split(r"^##\s+(.+)$", markdown.strip(), flags=re.MULTILINE)
    if len(parts) <= 1:
        return append_to_doc(doc_id, markdown.strip())
    intro = parts[0].strip()
    if intro:
        append_to_doc(doc_id, intro + "\n\n")
    idx = 1
    while idx < len(parts) - 1:
        section_title = parts[idx].strip()
        section_body = parts[idx + 1].strip()
        if section_title:
            write_section_to_doc(doc_id, section_title, section_body, heading_level=2)
        idx += 2
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


def clear_doc(doc_id: str) -> bool:
    """Vide complètement un Google Doc."""
    docs_service = _get_docs_service()
    doc = docs_service.documents().get(documentId=doc_id).execute()
    end_index = doc["body"]["content"][-1]["endIndex"]
    if end_index <= 2:
        return True
    requests_body = [
        {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}}
    ]
    docs_service.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests_body}
    ).execute()
    logger.info("Doc vidé: %s", doc_id)
    return True


def delete_doc(doc_id: str) -> bool:
    """Supprime un Google Doc via Drive."""
    drive_service = _get_drive_service()
    drive_service.files().delete(fileId=doc_id).execute()
    logger.info("Doc supprimé: %s", doc_id)
    return True


def list_docs(max_results: int = 10) -> list[dict]:
    """Liste les Google Docs récents."""
    drive_service = _get_drive_service()
    results = (
        drive_service.files()
        .list(
            q="mimeType='application/vnd.google-apps.document' and trashed=false",
            pageSize=max_results,
            orderBy="modifiedTime desc",
            fields="files(id, name, webViewLink, modifiedTime)",
        )
        .execute()
    )
    return results.get("files", [])


def rename_doc(doc_id: str, new_title: str) -> bool:
    """Renomme un Google Doc."""
    drive_service = _get_drive_service()
    drive_service.files().update(fileId=doc_id, body={"name": new_title}).execute()
    logger.info("Doc renommé: %s → %s", doc_id, new_title)
    return True


def find_doc_by_name(name: str, max_results: int = 20) -> dict | None:
    """Trouve un doc par titre (partiel, insensible à la casse)."""
    needle = name.strip().lower()
    if not needle:
        return None
    for doc in list_docs(max_results):
        if needle in doc.get("name", "").lower():
            return doc
    return None


def resolve_doc(name_or_id: str) -> dict | None:
    """Résout un doc par ID, doc actif ou titre."""
    active = get_active_doc()
    if active and (
        name_or_id.strip().lower() in active.get("title", "").lower()
        or name_or_id.strip() == active.get("id", "")
    ):
        return active
    if len(name_or_id) > 20 and " " not in name_or_id.strip():
        info = get_doc_info(name_or_id.strip())
        return info if info else None
    found = find_doc_by_name(name_or_id)
    if found:
        return {
            "id": found["id"],
            "title": found.get("name", name_or_id),
            "url": found.get("webViewLink", f"https://docs.google.com/document/d/{found['id']}/edit"),
        }
    return None
