"""Agent multi-étapes plan → validation → exécution (master-doc §5.3)."""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_pending_plan: list[dict] | None = None


def create_plan(goal: str, llm_fn) -> str:
    """Génère un plan JSON via le LLM."""
    global _pending_plan
    prompt = (
        "Tu es un planificateur d'actions pour l'assistant ARIA. "
        f"Objectif utilisateur: {goal}\n"
        "Réponds UNIQUEMENT avec un JSON valide: "
        '{"steps":[{"action":"nom_intent","params":{},"description":"..."}]} '
        "Actions possibles: daily_brief, focus_mode_on, calendar_create, lancer_app, "
        "preset, minuteur, export_pdf, revision_plan. Max 5 étapes."
    )
    raw = llm_fn(prompt)
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0) if m else raw)
        _pending_plan = data.get("steps", [])
    except (json.JSONDecodeError, AttributeError):
        _pending_plan = None
        return "Impossible de générer un plan structuré pour cet objectif."

    if not _pending_plan:
        return "Aucune étape proposée."

    lines = [f"{i + 1}. {s.get('description', s.get('action', '?'))}" for i, s in enumerate(_pending_plan)]
    return (
        "Voici ce que je propose :\n" + "\n".join(lines)
        + "\n\nDis « confirme le plan » pour exécuter ou « annule le plan » pour abandonner."
    )


def has_pending_plan() -> bool:
    return bool(_pending_plan)


def confirm_and_execute(dispatch_fn) -> str:
    global _pending_plan
    if not _pending_plan:
        return "Aucun plan en attente."
    results = []
    for step in _pending_plan:
        action = step.get("action", "")
        params = step.get("params") or {}
        try:
            results.append(str(dispatch_fn(action, params)))
        except Exception as exc:
            results.append(f"Erreur {action}: {exc}")
    _pending_plan = None
    return "Plan exécuté. " + " | ".join(r for r in results if r)


def cancel_plan() -> str:
    global _pending_plan
    _pending_plan = None
    return "Plan annulé."
