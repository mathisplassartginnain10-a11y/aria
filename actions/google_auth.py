"""Authentification Google partagée Drive + Calendar + Docs."""

from __future__ import annotations

import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

import app_paths

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/calendar",
]

TOKEN_PATH = app_paths.data_dir() / "google_token.json"
CREDS_PATH = app_paths.data_dir() / "google_credentials.json"


def get_credentials() -> Credentials | None:
    if not TOKEN_PATH.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def is_configured() -> bool:
    return TOKEN_PATH.exists()


def run_oauth_flow() -> None:
    if not CREDS_PATH.exists():
        raise FileNotFoundError(
            f"Place ton fichier credentials.json dans {CREDS_PATH}"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    logger.info("Authentification Google réussie")
