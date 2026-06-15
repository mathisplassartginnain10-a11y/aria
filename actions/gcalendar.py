"""Intégration Google Calendar (master-doc §3.5)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, time as dtime

from googleapiclient.discovery import build

from actions.google_auth import get_credentials, is_configured

logger = logging.getLogger(__name__)


def _service():
    creds = get_credentials()
    if not creds:
        raise RuntimeError("Google Calendar non configuré")
    return build("calendar", "v3", credentials=creds)


def get_today_events() -> list[dict]:
    if not is_configured():
        return []
    try:
        service = _service()
        now = datetime.utcnow()
        start = datetime.combine(now.date(), dtime.min).isoformat() + "Z"
        end = datetime.combine(now.date(), dtime.max).isoformat() + "Z"
        events_result = service.events().list(
            calendarId="primary",
            timeMin=start,
            timeMax=end,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = []
        for e in events_result.get("items", []):
            start_raw = e["start"].get("dateTime", e["start"].get("date"))
            if "T" in start_raw:
                dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                time_str = dt.strftime("%H:%M")
            else:
                time_str = "Toute la journée"
            events.append({"time": time_str, "title": e.get("summary", "Sans titre")})
        return events
    except Exception as exc:
        logger.error("Erreur Google Calendar: %s", exc)
        return []


def get_upcoming_events(days: int = 7) -> list[dict]:
    if not is_configured():
        return []
    try:
        service = _service()
        now = datetime.utcnow().isoformat() + "Z"
        future = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"
        events_result = service.events().list(
            calendarId="primary",
            timeMin=now,
            timeMax=future,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = []
        for e in events_result.get("items", []):
            start_raw = e["start"].get("dateTime", e["start"].get("date"))
            events.append({"start": start_raw, "title": e.get("summary", "Sans titre")})
        return events
    except Exception as exc:
        logger.error("Erreur Google Calendar: %s", exc)
        return []


def create_event(title: str, start_dt: datetime, duration_minutes: int = 60, description: str = "") -> str:
    if not is_configured():
        return "Google Calendar non configuré. Lance setup_google.py."
    try:
        service = _service()
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Paris"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "Europe/Paris"},
        }
        service.events().insert(calendarId="primary", body=event).execute()
        return f"Événement '{title}' créé pour le {start_dt.strftime('%d/%m à %H:%M')}."
    except Exception as exc:
        logger.error("Erreur création événement: %s", exc)
        return f"Erreur lors de la création : {exc}"
