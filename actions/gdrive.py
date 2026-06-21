"""
gdrive.py — Google Drive : upload, recherche, fichiers récents.
"""

from __future__ import annotations

import logging
from pathlib import Path

from actions.google_auth import build_service, is_authenticated, is_configured

logger = logging.getLogger(__name__)


def _svc():
    return build_service("drive", "v3")


def _escape_query(value: str) -> str:
    return value.replace("'", "\\'")


def search_files(query: str, max_results: int = 10) -> list[dict]:
    """Recherche des fichiers dans Google Drive."""
    if not is_configured() or not is_authenticated():
        return []
    try:
        safe = _escape_query(query.strip())
        results = (
            _svc()
            .files()
            .list(
                q=f"name contains '{safe}' and trashed=false",
                pageSize=max_results,
                fields="files(id, name, mimeType, webViewLink, modifiedTime)",
            )
            .execute()
        )
        files = results.get("files", [])
        logger.info("Drive search '%s': %d fichiers", query, len(files))
        return files
    except Exception as exc:
        logger.error("Drive search: %s", exc)
        return []


def upload_file(local_path: str, folder_id: str | None = None) -> dict:
    """Upload un fichier local vers Google Drive."""
    from googleapiclient.http import MediaFileUpload

    path = Path(local_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Fichier non trouvé: {local_path}")

    file_metadata: dict = {"name": path.name}
    if folder_id:
        file_metadata["parents"] = [folder_id]

    media = MediaFileUpload(str(path), resumable=True)
    created = (
        _svc()
        .files()
        .create(body=file_metadata, media_body=media, fields="id,name,webViewLink")
        .execute()
    )
    logger.info("Drive upload: %s → %s", path.name, created.get("webViewLink"))
    return created


def list_recent_files(max_results: int = 10) -> list[dict]:
    """Liste les fichiers récemment modifiés."""
    if not is_configured() or not is_authenticated():
        return []
    try:
        results = (
            _svc()
            .files()
            .list(
                orderBy="modifiedTime desc",
                pageSize=max_results,
                fields="files(id, name, mimeType, webViewLink, modifiedTime)",
                q="trashed=false",
            )
            .execute()
        )
        return results.get("files", [])
    except Exception as exc:
        logger.error("Drive list_recent: %s", exc)
        return []


def list_recent(max_results: int = 10) -> list[dict]:
    """Alias compat llm.py legacy."""
    return list_recent_files(max_results)


def format_files_for_aria(files: list[dict], *, header: str) -> str:
    if not files:
        return header
    lines = [header]
    for f in files:
        name = f.get("name", "?")
        link = f.get("webViewLink", "")
        mime = (f.get("mimeType") or "").split(".")[-1] or "fichier"
        if link:
            lines.append(f"• [{name}]({link}) ({mime})")
        else:
            lines.append(f"• {name} ({mime})")
    return "\n".join(lines)


def download_file(file_id: str, dest_path: str) -> str:
    """Télécharge un fichier Drive vers le PC."""
    import io

    from googleapiclient.http import MediaIoBaseDownload

    request = _svc().files().get_media(fileId=file_id)
    path = Path(dest_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    logger.info("Fichier téléchargé: %s → %s", file_id, path)
    return str(path)


def delete_file(file_id: str) -> bool:
    """Supprime un fichier Drive."""
    _svc().files().delete(fileId=file_id).execute()
    logger.info("Fichier Drive supprimé: %s", file_id)
    return True


def move_file(file_id: str, new_folder_id: str) -> bool:
    """Déplace un fichier vers un dossier Drive."""
    file = _svc().files().get(fileId=file_id, fields="parents").execute()
    previous_parents = ",".join(file.get("parents", []))
    _svc().files().update(
        fileId=file_id,
        addParents=new_folder_id,
        removeParents=previous_parents,
        fields="id, parents",
    ).execute()
    return True


def create_folder(name: str, parent_id: str | None = None) -> dict:
    """Crée un dossier dans Google Drive."""
    metadata: dict = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]
    folder = (
        _svc()
        .files()
        .create(body=metadata, fields="id, name, webViewLink")
        .execute()
    )
    logger.info("Dossier créé: %s", folder.get("webViewLink"))
    return folder


def find_file_by_name(name: str, max_results: int = 10) -> dict | None:
    """Trouve le premier fichier correspondant au nom."""
    files = search_files(name, max_results=max_results)
    needle = name.strip().lower()
    for f in files:
        if needle in f.get("name", "").lower():
            return f
    return files[0] if files else None
