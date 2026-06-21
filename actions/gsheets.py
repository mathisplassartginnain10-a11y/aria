"""
gsheets.py — Google Sheets : créer, lire et écrire des feuilles de calcul.
"""

from __future__ import annotations

import logging
import re

from actions.google_auth import build_service, is_authenticated, is_configured

logger = logging.getLogger(__name__)

_active_spreadsheet: dict | None = None


def _svc():
    return build_service("sheets", "v4")


def create_spreadsheet(title: str) -> dict:
    """Crée une nouvelle feuille de calcul."""
    result = (
        _svc()
        .spreadsheets()
        .create(body={"properties": {"title": title}})
        .execute()
    )
    logger.info("Sheet créé: %s", result.get("spreadsheetUrl"))
    info = {
        "id": result["spreadsheetId"],
        "title": title,
        "url": result.get("spreadsheetUrl", ""),
    }
    set_active_spreadsheet(info["id"], info["title"], info["url"])
    return info


def read_range(spreadsheet_id: str, range_: str = "Sheet1!A1:Z100") -> list[list]:
    """Lit une plage de données."""
    try:
        result = (
            _svc()
            .spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=range_)
            .execute()
        )
        return result.get("values", [])
    except Exception as exc:
        logger.error("Sheets read: %s", exc)
        return []


def append_rows(spreadsheet_id: str, values: list[list], range_: str = "Sheet1") -> bool:
    """Ajoute des lignes à la fin d'une feuille."""
    _svc().spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=range_,
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()
    logger.info("Sheets append: %d lignes", len(values))
    return True


def write_range(spreadsheet_id: str, range_: str, values: list[list]) -> bool:
    """Écrit des données dans une plage spécifique."""
    _svc().spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_,
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()
    return True


def set_active_spreadsheet(sheet_id: str, title: str, url: str) -> None:
    global _active_spreadsheet
    _active_spreadsheet = {"id": sheet_id, "title": title, "url": url}


def get_active_spreadsheet() -> dict | None:
    return _active_spreadsheet


def find_spreadsheet_by_title(title: str) -> dict | None:
    """Recherche un spreadsheet par titre via Drive API."""
    from actions.gdrive import search_files

    query = title.strip()
    for f in search_files(query, max_results=15):
        mime = f.get("mimeType", "")
        if "spreadsheet" in mime and query.lower() in f.get("name", "").lower():
            return {
                "id": f["id"],
                "title": f.get("name", title),
                "url": f.get("webViewLink", ""),
            }
    return None


def resolve_spreadsheet_id(text: str) -> str | None:
    """Extrait un ID ou résout un titre depuis le texte utilisateur."""
    m = re.search(r"spreadsheets/d/([a-zA-Z0-9-_]+)", text)
    if m:
        return m.group(1)
    m = re.search(r"\b([a-zA-Z0-9-_]{20,})\b", text)
    if m:
        return m.group(1)
    active = get_active_spreadsheet()
    if active:
        return active["id"]
    title = re.sub(
        r"^(?:lis|lire|ouvre|affiche)\s+(?:le\s+)?(?:tableau|sheet|feuille)\s+",
        "",
        text,
        flags=re.I,
    ).strip(" :'\"")
    if title:
        found = find_spreadsheet_by_title(title)
        if found:
            return found["id"]
    return None


def format_sheet_data_for_aria(values: list[list], *, title: str = "Tableau") -> str:
    if not values:
        return f"Le tableau « {title} » est vide."
    lines = [f"Contenu de « {title} » ({len(values)} lignes) :"]
    for row in values[:20]:
        lines.append(" | ".join(str(c) for c in row))
    if len(values) > 20:
        lines.append(f"… ({len(values) - 20} lignes supplémentaires)")
    return "\n".join(lines)


def extract_sheet_title(text: str) -> str:
    m = re.search(
        r"(?:crée|créer|cree|nouveau)\s+(?:un\s+)?(?:tableau|sheet|feuille)\s+(?:google\s*)?"
        r"(?:sheets?\s+)?(?:intitulé|intitule|nommé|nomme|appelé|appele)?\s*['\"]?(.+?)['\"]?\s*$",
        text,
        re.I,
    )
    if m:
        return m.group(1).strip(" '\"")
    cleaned = re.sub(
        r"^(?:crée|créer|cree)\s+(?:un\s+)?(?:google\s*)?(?:sheet|sheets|tableau)\s+",
        "",
        text,
        flags=re.I,
    ).strip(" :'\"")
    return cleaned or "Tableau ARIA"


def _drive_svc():
    return build_service("drive", "v3")


def create_spreadsheet_with_data(title: str, rows: list[list]) -> dict:
    """Crée un sheet, écrit les données et formate l'en-tête."""
    info = create_spreadsheet(title)
    if rows:
        write_range(info["id"], "Sheet1!A1", rows)
        try:
            format_spreadsheet_header(info["id"])
        except Exception as exc:
            logger.warning("Header format skipped: %s", exc)
    return info


def delete_spreadsheet(spreadsheet_id: str) -> bool:
    """Supprime une feuille de calcul via Drive."""
    _drive_svc().files().delete(fileId=spreadsheet_id).execute()
    logger.info("Sheet supprimé: %s", spreadsheet_id)
    return True


def list_spreadsheets(max_results: int = 10) -> list[dict]:
    """Liste les Google Sheets récents."""
    results = (
        _drive_svc()
        .files()
        .list(
            q="mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
            pageSize=max_results,
            orderBy="modifiedTime desc",
            fields="files(id, name, webViewLink, modifiedTime)",
        )
        .execute()
    )
    return results.get("files", [])


def add_sheet_tab(spreadsheet_id: str, tab_name: str) -> bool:
    """Ajoute un onglet dans une feuille de calcul."""
    _svc().spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]},
    ).execute()
    return True


def delete_sheet_tab(spreadsheet_id: str, sheet_id: int) -> bool:
    """Supprime un onglet dans une feuille de calcul."""
    _svc().spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"deleteSheet": {"sheetId": sheet_id}}]},
    ).execute()
    return True


def format_spreadsheet_header(spreadsheet_id: str, range_: str = "Sheet1!A1:Z1") -> bool:
    """Met la première ligne en gras avec fond coloré."""
    del range_
    _svc().spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": 0,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 0.26, "green": 0.35, "blue": 1.0},
                                "textFormat": {
                                    "bold": True,
                                    "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                                },
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat)",
                    }
                }
            ]
        },
    ).execute()
    return True


def parse_sheet_write_data(data: str) -> list[list]:
    """Parse une ligne vocal en valeurs de cellules."""
    raw = data.strip()
    if "|" in raw:
        return [[c.strip() for c in raw.split("|")]]
    if ";" in raw:
        return [[c.strip() for c in raw.split(";")]]
    if "," in raw:
        return [[c.strip() for c in raw.split(",")]]
    return [[raw]]
