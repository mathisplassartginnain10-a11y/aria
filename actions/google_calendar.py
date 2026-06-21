"""Google Agenda — créer / lister / déplacer / supprimer des créneaux.

Deux modes :
  1. API Google Calendar (OAuth) — lecture + écriture complètes.
     Activé dès qu'un fichier `data/google_credentials.json` (client OAuth
     « Desktop ») est présent. Le 1er appel ouvre une page de consentement,
     puis le jeton est sauvé dans `data/google_token.json`.
  2. Fallback navigateur — si l'API n'est pas configurée, on ouvre Google
     Agenda avec une page d'événement pré-remplie (l'utilisateur clique
     sur « Enregistrer »). Marche immédiatement, sans configuration.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from urllib.parse import quote_plus

import app_paths

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDENTIALS_PATH = app_paths.data_dir() / "google_credentials.json"
TOKEN_PATH = app_paths.data_dir() / "google_token.json"
TZ_NAME = "Europe/Paris"

_FR_DAYS = {0: "lundi", 1: "mardi", 2: "mercredi", 3: "jeudi", 4: "vendredi", 5: "samedi", 6: "dimanche"}
_FR_MONTHS = {
    1: "janvier", 2: "février", 3: "mars", 4: "avril", 5: "mai", 6: "juin",
    7: "juillet", 8: "août", 9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre",
}

_service = None


# --------------------------------------------------------------------------- #
#  Config / auth
# --------------------------------------------------------------------------- #
def is_configured() -> bool:
    """True si des identifiants OAuth sont présents (API utilisable)."""
    try:
        from actions.google_auth import is_configured as _auth_configured

        return _auth_configured()
    except Exception:
        return CREDENTIALS_PATH.exists()


def _get_service():
    """Construit (et met en cache) le service Calendar, ou None si non configuré."""
    global _service
    if _service is not None:
        return _service
    try:
        from actions.google_auth import build_service, is_authenticated, is_configured

        if not is_configured() or not is_authenticated():
            return None
        _service = build_service("calendar", "v3", cache_discovery=False)
        logger.info("Google Calendar API prête")
        return _service
    except Exception:
        logger.exception("Auth Google Calendar échouée")
        return None


def _local_tz():
    return dt.datetime.now().astimezone().tzinfo


def _aware(d: dt.datetime) -> dt.datetime:
    return d if d.tzinfo else d.replace(tzinfo=_local_tz())


# --------------------------------------------------------------------------- #
#  Analyse langage naturel : date/heure + titre
# --------------------------------------------------------------------------- #
_DOW = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
    "vendredi": 4, "samedi": 5, "dimanche": 6,
}


def _extract_time(text: str) -> tuple[int, int, bool]:
    """(heure, minute, heure_explicite) — défaut 9h00 si rien trouvé."""
    m = re.search(r"\b(\d{1,2})\s*h(?:\s*(\d{2}))?\b", text, re.I)
    if m:
        return int(m.group(1)), int(m.group(2) or 0), True
    m = re.search(r"\b(\d{1,2})\s*:\s*(\d{2})\b", text)
    if m:
        return int(m.group(1)), int(m.group(2)), True
    t = text.lower()
    if "minuit" in t:
        return 0, 0, True
    if "midi" in t:
        return 12, 0, True
    if "ce soir" in t or "cette nuit" in t:
        return 19, 0, True
    if "après-midi" in t or "apres-midi" in t:
        return 14, 0, True
    if "matin" in t:
        return 9, 0, True
    return 9, 0, False


def _explicit_day(text: str) -> bool:
    t = text.lower()
    if any(k in t for k in ("demain", "aujourd'hui", "aujourdhui", "ce soir", "ce midi",
                            "semaine", "lundi", "mardi", "mercredi", "jeudi", "vendredi",
                            "samedi", "dimanche")):
        return True
    return re.search(r"\b\d{1,2}[/\.]\d{1,2}", t) is not None


def _extract_day(text: str) -> dt.date | None:
    """Jour visé (sans l'heure). None si aucune date détectable."""
    t = text.lower()
    now = dt.datetime.now(tz=_local_tz())
    base = now.date()

    if "après-demain" in t or "apres-demain" in t:
        return base + dt.timedelta(days=2)
    if "demain" in t:
        return base + dt.timedelta(days=1)
    if any(k in t for k in ("aujourd'hui", "aujourdhui", "ce soir", "ce midi", "cette nuit")):
        return base
    for name, idx in _DOW.items():
        if name in t:
            return base + dt.timedelta(days=(idx - base.weekday()) % 7)
    m = re.search(r"\b(\d{1,2})[/\.](\d{1,2})(?:[/\.](\d{2,4}))?", t)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3) or now.year)
        if year < 100:
            year += 2000
        try:
            return dt.date(year, month, day)
        except ValueError:
            pass
    # dateparser pour « le 12 juin », « dans 3 jours », « lundi prochain »…
    try:
        from dateparser.search import search_dates

        found = search_dates(
            text,
            languages=["fr"],
            settings={
                "PREFER_DATES_FROM": "future",
                "DATE_ORDER": "DMY",
                "RELATIVE_BASE": now.replace(tzinfo=None),
            },
        )
        if found:
            return found[-1][1].date()
    except Exception:
        pass
    return None


def parse_when(text: str) -> tuple[dt.datetime | None, dt.datetime | None]:
    """Extrait (début, fin). Heure et jour analysés séparément (robuste)."""
    hour, minute, has_time = _extract_time(text)
    day = _extract_day(text)
    if day is None and not has_time:
        return None, None

    now = dt.datetime.now(tz=_local_tz())
    if day is None:
        day = now.date()
    start = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=_local_tz())
    # Heure seule déjà passée → on bascule au lendemain.
    if not _explicit_day(text) and start <= now:
        start += dt.timedelta(days=1)

    end = None
    m_range = re.search(
        r"(?:de\s+)?\d{1,2}\s*h(?:\s*\d{2})?\s*(?:à|a|jusqu'?(?:à|a))\s*(\d{1,2})\s*h(?:\s*(\d{2}))?",
        text, re.I,
    )
    if m_range:
        end = start.replace(hour=int(m_range.group(1)), minute=int(m_range.group(2) or 0))
    else:
        m_dur = re.search(
            r"(?:pendant|pour|dur[ée]e?(?:\s+de)?)\s+(\d{1,3})\s*(h|heures?|min|minutes?)",
            text, re.I,
        )
        if m_dur:
            n = int(m_dur.group(1))
            mins = n * 60 if m_dur.group(2).lower().startswith("h") else n
            end = start + dt.timedelta(minutes=mins)
    if end is None or end <= start:
        end = start + dt.timedelta(hours=1)
    return start, end


_VERB_PREFIX = re.compile(
    r"^\s*(?:cale(?:r|-moi)?|ajoute|cr[ée]e|cree|planifie|r[ée]serve|reserve|bloque|"
    r"mets?|programme|note|pr[ée]vois|d[ée]place|deplace|d[ée]cale|decale|change|modifie|"
    r"reporte|repousse|annule|supprime|enl[èe]ve)\b[\s:,-]*",
    re.I,
)
_FILLER = re.compile(
    r"\b(un|une|le|la|les|mon|ma|mes|du|de la|d'|à|a|au|pour|dans|rendez-vous|rdv|"
    r"cr[ée]neau|creneau|r[ée]union|reunion|[ée]v[èé]nement|evenement|event|s[ée]ance|seance|"
    r"cours|rappel)\b",
    re.I,
)
_TEMPORAL = re.compile(
    r"\b(aujourd'?hui|demain|apr[èe]s-?demain|ce soir|ce midi|cette nuit|"
    r"lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|prochain[e]?|"
    r"\d{1,2}\s*h(?:\s*\d{2})?|\d{1,2}[/\.]\d{1,2}(?:[/\.]\d{2,4})?|"
    r"midi|minuit|de\s+\d{1,2}\s*h.*?(?:à|a)\s*\d{1,2}\s*h|pendant\s+\d+\s*\w+|"
    r"dans\s+\d+\s*\w+|semaine prochaine|la semaine|matin|apr[èe]s-midi|"
    r"janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|d[ée]cembre)\b",
    re.I,
)


def extract_title(text: str) -> str:
    """Déduit le titre du créneau en retirant le verbe, les mots vides et la date."""
    s = _VERB_PREFIX.sub("", text).strip()
    s = _TEMPORAL.sub(" ", s)
    s = _FILLER.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip(" :,.-'\"")
    return s or "Rendez-vous"


# --------------------------------------------------------------------------- #
#  Formatage
# --------------------------------------------------------------------------- #
def _fmt_dt(d: dt.datetime) -> str:
    d = _aware(d)
    return f"{_FR_DAYS[d.weekday()]} {d.day} {_FR_MONTHS[d.month]} à {d.hour}h{d.minute:02d}"


def _event_start(ev: dict) -> dt.datetime | None:
    raw = ev.get("start", {})
    val = raw.get("dateTime") or raw.get("date")
    if not val:
        return None
    try:
        if "T" in val:
            return dt.datetime.fromisoformat(val.replace("Z", "+00:00")).astimezone(_local_tz())
        return _aware(dt.datetime.fromisoformat(val))
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
#  Actions
# --------------------------------------------------------------------------- #
def create_event(summary: str, start: dt.datetime, end: dt.datetime | None = None,
                 description: str = "", location: str = "") -> str:
    start = _aware(start)
    end = _aware(end) if end else start + dt.timedelta(hours=1)
    svc = _get_service()
    if svc is None:
        return _browser_quick_add(summary, start, end)
    try:
        body = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": start.isoformat(), "timeZone": TZ_NAME},
            "end": {"dateTime": end.isoformat(), "timeZone": TZ_NAME},
        }
        svc.events().insert(calendarId="primary", body=body).execute()
        return f"C'est calé : « {summary} » {_fmt_dt(start)}."
    except Exception:
        logger.exception("create_event API échec, fallback navigateur")
        return _browser_quick_add(summary, start, end)


def list_events(time_min: dt.datetime | None = None, time_max: dt.datetime | None = None,
                max_results: int = 10) -> list[dict]:
    svc = _get_service()
    if svc is None:
        return []
    now = dt.datetime.now(tz=_local_tz())
    time_min = _aware(time_min) if time_min else now
    try:
        params = {
            "calendarId": "primary",
            "timeMin": time_min.isoformat(),
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": max_results,
        }
        if time_max:
            params["timeMax"] = _aware(time_max).isoformat()
        return svc.events().list(**params).execute().get("items", [])
    except Exception:
        logger.exception("list_events échec")
        return []


def find_events(query: str, horizon_days: int = 60) -> list[dict]:
    """Événements à venir dont le titre contient `query`."""
    q = query.strip().lower()
    end = dt.datetime.now(tz=_local_tz()) + dt.timedelta(days=horizon_days)
    events = list_events(time_max=end, max_results=50)
    if not q:
        return events
    return [e for e in events if q in e.get("summary", "").lower()]


def describe_events(events: list[dict], empty: str = "Rien de prévu.") -> str:
    if not events:
        return empty
    parts = []
    for e in events[:8]:
        start = _event_start(e)
        when = _fmt_dt(start) if start else "?"
        parts.append(f"{e.get('summary', 'Événement')} — {when}")
    return ". ".join(parts) + "."


def move_event(query: str, new_start: dt.datetime, new_end: dt.datetime | None = None) -> str:
    svc = _get_service()
    if svc is None:
        from actions import browser
        browser.open_url("https://calendar.google.com/calendar/u/0/r")
        return ("Pour déplacer un créneau il me faut l'accès API Google Agenda "
                "(dépose tes identifiants OAuth). J'ouvre l'agenda en attendant.")
    matches = find_events(query)
    if not matches:
        return f"Aucun créneau « {query} » trouvé à venir."
    ev = matches[0]
    new_start = _aware(new_start)
    old_start = _event_start(ev)
    duration = dt.timedelta(hours=1)
    if old_start:
        old_end = _event_start({"start": ev.get("end", {})})
        if old_end:
            duration = old_end - old_start
    new_end = _aware(new_end) if new_end else new_start + duration
    try:
        svc.events().patch(
            calendarId="primary",
            eventId=ev["id"],
            body={
                "start": {"dateTime": new_start.isoformat(), "timeZone": TZ_NAME},
                "end": {"dateTime": new_end.isoformat(), "timeZone": TZ_NAME},
            },
        ).execute()
        return f"Déplacé : « {ev.get('summary', 'créneau')} » → {_fmt_dt(new_start)}."
    except Exception:
        logger.exception("move_event échec")
        return "Je n'ai pas réussi à déplacer ce créneau."


def delete_event(query: str) -> str:
    svc = _get_service()
    if svc is None:
        from actions import browser
        browser.open_url("https://calendar.google.com/calendar/u/0/r")
        return "Accès API requis pour supprimer. J'ouvre l'agenda."
    matches = find_events(query)
    if not matches:
        return f"Aucun créneau « {query} » trouvé."
    ev = matches[0]
    try:
        svc.events().delete(calendarId="primary", eventId=ev["id"]).execute()
        return f"Supprimé : « {ev.get('summary', 'créneau')} »."
    except Exception:
        logger.exception("delete_event échec")
        return "Je n'ai pas réussi à supprimer ce créneau."


def quick_add_url(summary: str, start: dt.datetime, end: dt.datetime) -> str:
    fmt = "%Y%m%dT%H%M%S"
    dates = f"{_aware(start).strftime(fmt)}/{_aware(end).strftime(fmt)}"
    return ("https://calendar.google.com/calendar/render?action=TEMPLATE"
            f"&text={quote_plus(summary)}&dates={dates}")


def _browser_quick_add(summary: str, start: dt.datetime, end: dt.datetime) -> str:
    from actions import browser
    browser.open_url(quick_add_url(summary, start, end))
    return (f"J'ouvre Google Agenda avec « {summary} » {_fmt_dt(start)} pré-rempli — "
            "clique sur « Enregistrer ». (Configure l'API pour que je le fasse tout seul.)")
