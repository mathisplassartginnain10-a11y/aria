"""Journal de vol vocal (master-doc §4.3)."""

from __future__ import annotations

import json
import logging
from datetime import datetime

import app_paths

logger = logging.getLogger(__name__)

LOGBOOK_PATH = app_paths.data_dir() / "logbook.json"
_FIELDS = ["duration", "departure", "arrival", "flight_type", "conditions", "remarks"]
_LABELS = {
    "duration": "Quelle était la durée du vol (en minutes) ?",
    "departure": "Aérodrome de départ (ICAO) ?",
    "arrival": "Aérodrome d'arrivée (ICAO) ?",
    "flight_type": "Type de vol (local, navigation, solo…) ?",
    "conditions": "Conditions météo rencontrées ?",
    "remarks": "Remarques éventuelles ?",
}

_session: dict | None = None


def _load() -> list[dict]:
    if LOGBOOK_PATH.exists():
        return json.loads(LOGBOOK_PATH.read_text(encoding="utf-8"))
    return []


def _save(entries: list[dict]) -> None:
    LOGBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOGBOOK_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def start_session() -> str:
    global _session
    _session = {"data": {"date": datetime.now().strftime("%Y-%m-%d")}, "field_idx": 0}
    return _LABELS[_FIELDS[0]]


def is_active() -> bool:
    return _session is not None


def answer(text: str) -> str:
    global _session
    if not _session:
        return "Aucune saisie de vol en cours. Dis 'nouveau vol' pour commencer."
    field = _FIELDS[_session["field_idx"]]
    _session["data"][field] = text.strip()
    _session["field_idx"] += 1
    if _session["field_idx"] >= len(_FIELDS):
        return _finalize()
    return _LABELS[_FIELDS[_session["field_idx"]]]


def _finalize() -> str:
    global _session
    entries = _load()
    entry = dict(_session["data"])
    try:
        mins = int("".join(c for c in str(entry.get("duration", "0")) if c.isdigit()) or "0")
    except ValueError:
        mins = 0
    total_mins = sum(int(e.get("duration_minutes", 0)) for e in entries) + mins
    entry["duration_minutes"] = mins
    entry["total_hours"] = round(total_mins / 60, 1)
    entries.append(entry)
    _save(entries)
    _session = None
    return f"Vol enregistré. Total cumulé : {entry['total_hours']} h."


def stop_session() -> None:
    global _session
    _session = None
