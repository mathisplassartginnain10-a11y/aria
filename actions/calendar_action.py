import logging
from datetime import datetime, timedelta
from pathlib import Path

import memory
import app_paths

logger = logging.getLogger(__name__)

ICS_PATH = app_paths.data_dir() / "calendar.ics"


def _parse_ics_events() -> list[dict]:
    if not ICS_PATH.exists():
        return []
    events = []
    try:
        content = ICS_PATH.read_text(encoding="utf-8")
        current: dict = {}
        for line in content.splitlines():
            if line.startswith("BEGIN:VEVENT"):
                current = {}
            elif line.startswith("SUMMARY:"):
                current["title"] = line[8:]
            elif line.startswith("DTSTART"):
                date_str = line.split(":")[-1]
                try:
                    if "T" in date_str:
                        current["datetime"] = datetime.strptime(date_str[:15], "%Y%m%dT%H%M%S")
                    else:
                        current["datetime"] = datetime.strptime(date_str[:8], "%Y%m%d")
                except ValueError:
                    pass
            elif line.startswith("END:VEVENT") and current:
                events.append(current)
    except OSError:
        logger.exception("Failed to read ICS file")
    return events


def get_today_events() -> str:
    today = datetime.now().date()
    events = [e for e in _parse_ics_events() if e.get("datetime", datetime.min).date() == today]
    reminders = memory.get_due_reminders()

    parts = []
    if events:
        for e in events:
            t = e["datetime"].strftime("%H:%M") if "datetime" in e else ""
            parts.append(f"{e.get('title', 'Événement')} à {t}")
    if reminders:
        for r in reminders:
            parts.append(f"Rappel : {r.get('text', '')}")

    if not parts:
        return "Rien de prévu aujourd'hui."
    return "Aujourd'hui : " + ". ".join(parts) + "."


def get_upcoming(days: int = 7) -> str:
    now = datetime.now()
    end = now + timedelta(days=days)
    events = [
        e for e in _parse_ics_events()
        if now <= e.get("datetime", datetime.min) <= end
    ]
    if not events:
        return f"Pas d'événements dans les {days} prochains jours."
    parts = []
    for e in events:
        dt = e.get("datetime", datetime.min)
        parts.append(f"{e.get('title', 'Événement')} le {dt.strftime('%d/%m à %H:%M')}")
    return ". ".join(parts) + "."


def add_event(title: str, date: str, time_str: str = "09:00", duration: int = 60) -> str:
    ICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        dt = datetime.strptime(f"{date} {time_str}", "%d/%m/%Y %H:%M")
    except ValueError:
        return "Format de date invalide. Utilise JJ/MM/AAAA HH:MM."

    uid = f"{int(datetime.now().timestamp())}@assistant-vocal"
    end = dt + timedelta(minutes=duration)
    event = (
        f"BEGIN:VEVENT\n"
        f"UID:{uid}\n"
        f"SUMMARY:{title}\n"
        f"DTSTART:{dt.strftime('%Y%m%dT%H%M%S')}\n"
        f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}\n"
        f"END:VEVENT\n"
    )
    if not ICS_PATH.exists():
        ICS_PATH.write_text("BEGIN:VCALENDAR\nVERSION:2.0\n", encoding="utf-8")

    content = ICS_PATH.read_text(encoding="utf-8")
    if "END:VCALENDAR" in content:
        content = content.replace("END:VCALENDAR", event + "END:VCALENDAR")
    else:
        content += event + "END:VCALENDAR\n"
    ICS_PATH.write_text(content, encoding="utf-8")
    return f"Événement {title} ajouté le {dt.strftime('%d/%m à %H:%M')}."


def add_reminder(text: str, when: str) -> str:
    memory.add_reminder(text, when)
    return f"Rappel ajouté : {text}."


def get_due_reminders() -> str:
    due = memory.get_due_reminders()
    if not due:
        return ""
    return ". ".join(r.get("text", "") for r in due)