"""Nexus — éditeur de code « maison » de Mathi (type Cursor), encore à venir.

Ce module est le CLIENT côté ARIA, prêt à se lier à Nexus dès qu'il tournera.
Deux canaux, auto-détectés (l'API a la priorité) :

  1) API LOCALE (recommandé) — Nexus expose un petit serveur HTTP local.
     Contrat attendu côté Nexus (à implémenter quand tu codes Nexus) :
        GET  {base}/health          -> 200  {"status":"ok","app":"nexus"}
        POST {base}/prompt   body:  {"prompt": str, "context": str|null}
                             ret :  {"ok": true, "result": str}
        POST {base}/open     body:  {"path": str}            -> {"ok": true}
        POST {base}/project  body:  {"path": str}            -> {"ok": true}
     Base par défaut : http://127.0.0.1:7878  (réglable via config `nexus_api_url`).

  2) EXÉCUTABLE — lancement direct de Nexus.exe (config `nexus_path`), le
     fichier/projet passé en argument de ligne de commande.

Tant que Nexus n'est ni lancé ni configuré, chaque action répond proprement
au lieu de planter. Aucune dépendance supplémentaire (juste requests).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import requests
import yaml

import app_paths

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

try:
    with app_paths.config_path().open("r", encoding="utf-8") as _f:
        _config = yaml.safe_load(_f) or {}
except Exception:
    _config = {}

API_URL: str = str(_config.get("nexus_api_url", "http://127.0.0.1:7878")).rstrip("/")
_NEXUS_PATH_RAW: str | None = _config.get("nexus_path")
HEALTH_TIMEOUT = 1.5
ACTION_TIMEOUT = 5
PROMPT_TIMEOUT = 120

APP_NAME = "Nexus"


def _exe_path() -> Path | None:
    if not _NEXUS_PATH_RAW:
        return None
    raw = str(_NEXUS_PATH_RAW).replace("USERNAME", os.environ.get("USERNAME", ""))
    return Path(raw)


def _api_online() -> bool:
    try:
        r = requests.get(f"{API_URL}/health", timeout=HEALTH_TIMEOUT)
        return r.ok
    except requests.RequestException:
        return False


def is_available() -> bool:
    """True si Nexus est joignable (API en ligne) ou installé (exe présent)."""
    if _api_online():
        return True
    exe = _exe_path()
    return bool(exe and exe.exists())


def status() -> str:
    if _api_online():
        return f"{APP_NAME} : API connectée ({API_URL})."
    exe = _exe_path()
    if exe and exe.exists():
        return f"{APP_NAME} : installé ({exe}), API hors ligne."
    return f"{APP_NAME} : pas encore disponible."


def _launch_exe(arg: str | None = None) -> str | None:
    exe = _exe_path()
    if not (exe and exe.exists()):
        return None
    args = [str(exe)] + ([arg] if arg else [])
    try:
        subprocess.Popen(args, creationflags=CREATE_NO_WINDOW)
        return f"{APP_NAME} lancé" + (f" : {arg}" if arg else ".")
    except Exception as exc:
        logger.warning("Lancement %s échoué: %s", APP_NAME, exc)
        return None


def _unavailable() -> str:
    return (
        f"{APP_NAME} n'est pas encore branché. Quand il sera prêt : renseigne "
        f"`nexus_path` (l'exe) ou démarre son API locale ({API_URL}) — "
        "ARIA s'y connectera automatiquement."
    )


def open_nexus(file_path: str | None = None) -> str:
    if _api_online() and file_path:
        try:
            requests.post(f"{API_URL}/open", json={"path": file_path}, timeout=ACTION_TIMEOUT)
            return f"Ouvert dans {APP_NAME} : {file_path}"
        except requests.RequestException:
            pass
    launched = _launch_exe(file_path)
    if launched:
        return launched
    return _unavailable()


def open_file(file_path: str) -> str:
    return open_nexus(file_path)


def open_project(project_path: str) -> str:
    if _api_online():
        try:
            requests.post(f"{API_URL}/project", json={"path": project_path}, timeout=ACTION_TIMEOUT)
            return f"Projet ouvert dans {APP_NAME} : {project_path}"
        except requests.RequestException:
            pass
    launched = _launch_exe(project_path)
    return launched or _unavailable()


def send_prompt(prompt: str, context: str | None = None) -> str:
    """Envoie une demande de code à Nexus (canal principal du lien)."""
    if _api_online():
        try:
            r = requests.post(
                f"{API_URL}/prompt",
                json={"prompt": prompt, "context": context},
                timeout=PROMPT_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            return data.get("result") or f"Demande envoyée à {APP_NAME}."
        except requests.RequestException as exc:
            logger.warning("%s /prompt injoignable: %s", APP_NAME, exc)
            return f"{APP_NAME} injoignable : {exc}"
    # API absente : au moins ouvrir l'app si elle est installée.
    if _launch_exe():
        return (
            f"{APP_NAME} n'expose pas encore son API — je l'ai ouvert. "
            f"Demande à coller : {prompt}"
        )
    return _unavailable()


def handle(text: str) -> str:
    """Routeur simple pour les commandes « … nexus … »."""
    import re

    t = text.lower()
    file_m = re.search(r"([\w./\\-]+\.(?:py|ts|tsx|js|jsx|json|ya?ml|md|css|html|rs|go|java|cpp|c))", text, re.I)
    if file_m and any(k in t for k in ("ouvre", "open", "édite", "edite", "montre")):
        return open_file(file_m.group(1))
    if "projet" in t:
        name = re.sub(r".*(?:projet|project)\s+", "", text, flags=re.I).strip()
        return open_project(name or "")
    if any(k in t for k in ("ouvre", "lance", "démarre", "demarre", "open")) and "nexus" in t and not file_m:
        return open_nexus()
    # Par défaut : demande de code.
    payload = re.sub(
        r"^.*?(?:demande|envoie|dis|code|génère|genere|crée|cree|corrige|écris|ecris)\s+"
        r"(?:(?:à|a)\s+nexus\s+(?:de\s+)?)?",
        "",
        text,
        flags=re.I,
    ).strip()
    payload = re.sub(r"\b(?:dans|sur|via|avec)\s+nexus\b", "", payload, flags=re.I).strip()
    return send_prompt(payload or text)
