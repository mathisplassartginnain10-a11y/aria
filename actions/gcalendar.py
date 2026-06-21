"""
gcalendar.py — Google Calendar : créer, lire, formater des événements.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, time as dtime

from actions.google_auth import build_service, is_authenticated, is_configured

logger = logging.getLogger(__name__)

TZ_NAME = "Europe/Paris"


def _svc():
    return build_service("calendar", "v3")


def list_upcoming(max_results: int = 10) -> list[dict]:
    """Retourne les prochains événements bruts (API Google)."""
    if not is_configured() or not is_authenticated():
        return []
    try:
        now = datetime.utcnow().isoformat() + "Z"
        result = (
            _svc()
            .events()
            .list(
                calendarId="primary",
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = result.get("items", [])
        logger.info("Calendar: %d événements à venir", len(events))
        return events
    except Exception as exc:
        logger.error("Calendar list_upcoming: %s", exc)
        return []


def get_upcoming_events(max_results: int = 10) -> list[dict]:
    """Alias spec sprint E."""
    return list_upcoming(max_results)


def get_today_events() -> list[dict]:
    """Événements du jour (format simplifié pour l'UI legacy)."""
    if not is_configured() or not is_authenticated():
        return []
    try:
        service = _svc()
        now = datetime.utcnow()
        start = datetime.combine(now.date(), dtime.min).isoformat() + "Z"
        end = datetime.combine(now.date(), dtime.max).isoformat() + "Z"
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=start,
                timeMax=end,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
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
        logger.error("Erreur Google Calendar today: %s", exc)
        return []


def get_upcoming_events_days(days: int = 7) -> list[dict]:
    """Événements sur N jours (format simplifié legacy)."""
    if not is_configured() or not is_authenticated():
        return []
    try:
        service = _svc()
        now = datetime.utcnow().isoformat() + "Z"
        future = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now,
                timeMax=future,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = []
        for e in events_result.get("items", []):
            start_raw = e["start"].get("dateTime", e["start"].get("date"))
            events.append({"start": start_raw, "title": e.get("summary", "Sans titre")})
        return events
    except Exception as exc:
        logger.error("Erreur Google Calendar upcoming: %s", exc)
        return []


def create_event_api(
    title: str,
    start: datetime,
    end: datetime | None = None,
    description: str = "",
    location: str = "",
) -> dict:
    """Crée un événement et retourne l'objet API."""
    if end is None:
        end = start + timedelta(hours=1)
    event_body = {
        "summary": title,
        "description": description,
        "location": location,
        "start": {"dateTime": start.isoformat(), "timeZone": TZ_NAME},
        "end": {"dateTime": end.isoformat(), "timeZone": TZ_NAME},
    }
    created = _svc().events().insert(calendarId="primary", body=event_body).execute()
    logger.info("Événement créé: %s", created.get("htmlLink"))
    return created


def create_event(title: str, start_dt: datetime, duration_minutes: int = 60, description: str = "") -> str:
    """Crée un événement — retour texte pour compat UI."""
    if not is_configured():
        return "Google Calendar non configuré. Lance setup_google.py."
    if not is_authenticated():
        return "Google non authentifié. Lance setup_google.py."
    try:
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        created = create_event_api(title, start_dt, end_dt, description=description)
        link = created.get("htmlLink", "")
        msg = f"Événement « {title} » créé pour le {start_dt.strftime('%d/%m à %H:%M')}."
        if link:
            msg += f" {link}"
        return msg
    except Exception as exc:
        logger.error("Erreur création événement: %s", exc)
        return f"Erreur lors de la création : {exc}"


def create_event_from_fields(
    title: str,
    date_iso: str,
    time_str: str = "",
    location: str = "",
) -> str:
    """Crée un événement depuis des champs extraits (JSON LLM)."""
    if not title:
        return "Impossible d'extraire le titre de l'événement."
    try:
        from datetime import date as date_cls

        if date_iso:
            day = date_cls.fromisoformat(date_iso[:10])
        else:
            day = date_cls.today()
        hour, minute = 9, 0
        if time_str:
            tm = re.search(r"(\d{1,2})[:hH](\d{2})?", time_str)
            if tm:
                hour = int(tm.group(1))
                minute = int(tm.group(2) or 0)
        start = datetime(day.year, day.month, day.day, hour, minute)
        created = create_event_api(title, start, location=location or "")
        link = created.get("htmlLink", "")
        msg = f"C'est calé : « {title} » le {start.strftime('%d/%m/%Y à %H:%M')}."
        if location:
            msg += f" Lieu : {location}."
        if link:
            msg += f" {link}"
        return msg
    except Exception as exc:
        logger.error("create_event_from_fields: %s", exc)
        return f"Erreur création événement : {exc}"


def parse_event_json(raw: str) -> dict:
    """Parse le JSON d'extraction événement depuis le LLM."""
    raw = raw.strip()
    m = re.search(r"\{[^{}]+\}", raw, re.S)
    if m:
        raw = m.group(0)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {
        "title": "",
        "date": "",
        "time": "",
        "location": "",
    }


def format_events_for_aria(events: list[dict]) -> str:
    """Formate les événements pour une réponse naturelle d'ARIA."""
    if not events:
        return "Aucun événement à venir dans ton calendrier."
    lines = ["Voici tes prochains événements :"]
    for ev in events:
        start = ev.get("start", {})
        if isinstance(start, dict):
            start = start.get("dateTime", start.get("date", ""))
        try:
            dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            date_str = dt.strftime("%d/%m à %H:%M")
        except Exception:
            date_str = str(start)
        lines.append(f"• **{ev.get('summary', 'Sans titre')}** — {date_str}")
        if ev.get("location"):
            lines.append(f"  📍 {ev['location']}")
    return "\n".join(lines)


def get_events_today() -> list[dict]:
    """Retourne les événements d'aujourd'hui (objets API bruts)."""
    if not is_configured() or not is_authenticated():
        return []
    try:
        from datetime import date

        today = date.today()
        start = f"{today}T00:00:00Z"
        end = f"{today}T23:59:59Z"
        result = (
            _svc()
            .events()
            .list(
                calendarId="primary",
                timeMin=start,
                timeMax=end,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return result.get("items", [])
    except Exception as exc:
        logger.error("Calendar get_events_today: %s", exc)
        return []


def delete_event(event_id: str, calendar_id: str = "primary") -> bool:
    """Supprime un événement du calendrier."""
    _svc().events().delete(calendarId=calendar_id, eventId=event_id).execute()
    logger.info("Événement supprimé: %s", event_id)
    return True


def update_event(
    event_id: str,
    title: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    description: str | None = None,
) -> dict:
    """Modifie un événement existant."""
    event = _svc().events().get(calendarId="primary", eventId=event_id).execute()
    if title:
        event["summary"] = title
    if description:
        event["description"] = description
    if start:
        event["start"] = {"dateTime": start.isoformat(), "timeZone": TZ_NAME}
    if end:
        event["end"] = {"dateTime": end.isoformat(), "timeZone": TZ_NAME}
    return (
        _svc()
        .events()
        .update(calendarId="primary", eventId=event_id, body=event)
        .execute()
    )


def find_event_by_title(title: str, *, today_only: bool = False) -> dict | None:
    """Cherche un événement par titre."""
    events = get_events_today() if today_only else get_upcoming_events(20)
    needle = title.strip().lower()
    for ev in events:
        if needle in (ev.get("summary") or "").lower():
            return ev
    return None
