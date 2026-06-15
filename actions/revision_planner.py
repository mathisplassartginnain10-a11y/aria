"""Planning révision BAC (master-doc §4.4)."""

from __future__ import annotations

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_SUBJECTS = ["Maths", "Allemand", "Physique", "Philosophie", "Histoire-Géo"]


def generate_plan(days: int = 14, hours_per_day: float = 2.0) -> str:
    lines = [f"Plan de révision BAC sur {days} jours (~{hours_per_day}h/jour) :"]
    start = date.today()
    for i in range(days):
        d = start + timedelta(days=i)
        subject = _SUBJECTS[i % len(_SUBJECTS)]
        lines.append(f"- {d.strftime('%d/%m')} : {subject} ({hours_per_day}h)")
    lines.append("Dis 'ajoute au calendrier' pour synchroniser avec Google Calendar.")
    return "\n".join(lines)
