"""Google Drive / Docs API (master-doc §2.2)."""

from __future__ import annotations

import logging

from googleapiclient.discovery import build

from actions.google_auth import get_credentials, is_configured


def get_service():
    creds = get_credentials()
    if not creds:
        raise RuntimeError("Google Drive non configuré")
    return build("drive", "v3", credentials=creds)


def _docs_service():
    creds = get_credentials()
    if not creds:
        raise RuntimeError("Google Docs non configuré")
    return build("docs", "v1", credentials=creds)


def search_files(query: str, max_results: int = 10) -> list[dict]:
    if not is_configured():
        return []
    try:
        service = get_service()
        results = service.files().list(
            q=f"name contains '{query.replace(chr(39), '')}'",
            pageSize=max_results,
            fields="files(id, name, mimeType, modifiedTime)",
        ).execute()
        return results.get("files", [])
    except Exception as exc:
        logger.error("Drive search error: %s", exc)
        return []


def list_recent(max_results: int = 10) -> list[dict]:
    if not is_configured():
        return []
    try:
        service = get_service()
        results = service.files().list(
            pageSize=max_results,
            orderBy="modifiedTime desc",
            fields="files(id, name, mimeType, modifiedTime)",
        ).execute()
        return results.get("files", [])
    except Exception as exc:
        logger.error("Drive list error: %s", exc)
        return []


def create_doc(title: str, content: str) -> str:
    if not is_configured():
        return "Google Drive non configuré. Lance python setup_google.py."
    try:
        docs = _docs_service()
        doc = docs.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]
        if content:
            docs.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
            ).execute()
        return f"Document '{title}' créé : https://docs.google.com/document/d/{doc_id}"
    except Exception as exc:
        logger.error("Drive create_doc error: %s", exc)
        return f"Erreur : {exc}"


def append_to_doc(doc_id: str, content: str) -> str:
    if not is_configured():
        return "Google Drive non configuré."
    try:
        docs = _docs_service()
        doc = docs.documents().get(documentId=doc_id).execute()
        end_index = doc["body"]["content"][-1]["endIndex"] - 1
        docs.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{"insertText": {"location": {"index": end_index}, "text": content}}]},
        ).execute()
        return f"Texte ajouté au document {doc_id}."
    except Exception as exc:
        logger.error("Drive append error: %s", exc)
        return f"Erreur : {exc}"
