"""
google_auth.py — Authentification OAuth2 Google commune à tous les services Workspace.
"""

from __future__ import annotations

import logging
from pathlib import Path

import app_paths

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/forms",
]

TOKEN_FILE = app_paths.data_dir() / "google_token.json"


def _credential_candidates() -> list[Path]:
    root = app_paths.app_dir()
    return [
        root / "credentials.json",
        root / "python" / "credentials.json",
        app_paths.data_dir() / "google_credentials.json",
    ]


def credentials_path() -> Path | None:
    """Retourne le premier fichier credentials OAuth trouvé."""
    for path in _credential_candidates():
        if path.exists():
            return path.resolve()
    return None


# Compatibilité imports externes
CREDENTIALS_FILE = credentials_path() or _credential_candidates()[0]


def is_configured() -> bool:
    """True si un client OAuth est présent (credentials.json)."""
    return credentials_path() is not None


def is_authenticated() -> bool:
    """True si un token utilisateur valide ou rafraîchissable existe."""
    if not TOKEN_FILE.exists():
        return False
    try:
        creds = get_credentials(interactive=False)
        return creds is not None and creds.valid
    except Exception:
        return False


def get_credentials(*, interactive: bool = True):
    """Charge ou obtient les credentials OAuth2 (ouvre le navigateur si besoin)."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception as exc:
            logger.warning("Token Google illisible: %s", exc)
            creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception as exc:
            logger.warning("Refresh token Google échoué: %s", exc)
            creds = None

    if not interactive:
        return None

    creds_file = credentials_path()
    if not creds_file:
        raise FileNotFoundError(
            "credentials.json non trouvé. Place le fichier OAuth Desktop dans "
            f"{app_paths.app_dir() / 'credentials.json'} "
            "ou lance setup_google.py."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    logger.info("Authentification Google réussie → %s", TOKEN_FILE)
    return creds


def build_service(service_name: str, version: str, *, cache_discovery: bool = False):
    """Construit un client googleapiclient pour le service demandé."""
    from googleapiclient.discovery import build

    creds = get_credentials(interactive=True)
    if not creds:
        raise RuntimeError("Google non authentifié. Lance setup_google.py.")
    return build(service_name, version, credentials=creds, cache_discovery=cache_discovery)


def run_oauth_flow() -> None:
    """Force le flux OAuth interactif (setup initial)."""
    get_credentials(interactive=True)
