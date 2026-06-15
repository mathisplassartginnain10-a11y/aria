"""Modes conversationnels prioritaires (checklist, quiz, logbook) — master-doc."""

from __future__ import annotations

import logging
import re

from actions import checklist, logbook, quiz_ppl

logger = logging.getLogger(__name__)

_CHECKLIST_START = (
    "démarre la checklist",
    "commence la checklist",
    "checklist dr400",
    "checklist pré-vol",
    "checklist pre-vol",
)
_QUIZ_START = ("lance un quiz ppl", "quiz ppl", "teste-moi sur", "lance un quiz")
_LOGBOOK_START = ("nouveau vol", "journal de vol", "enregistre un vol")
_AGENT_CONFIRM = ("confirme le plan", "exécute le plan", "execute le plan", "valide le plan")
_AGENT_CANCEL = ("annule le plan", "abandonne le plan")
_AGENT_START = ("organise mon", "planifie mon", "prépare mon", "prepare mon")


def try_handle(text: str) -> str | None:
    """Intercepte les modes spéciaux. Retourne une réponse ou None."""
    t = text.lower().strip()

    from actions import agent

    if any(p in t for p in _AGENT_CONFIRM):
        def _exec(action, p):
            import llm

            return llm._dispatch_action({"intent": action, "params": p}, "") or "ok"

        return agent.confirm_and_execute(_exec)
    if any(p in t for p in _AGENT_CANCEL):
        return agent.cancel_plan()
    if any(p in t for p in _AGENT_START):
        import llm

        return agent.create_plan(text, llm.ask_return_text)

    if checklist.is_active():
        return _handle_checklist(t)
    if quiz_ppl.is_active():
        return _handle_quiz(t)
    if logbook.is_active():
        return logbook.answer(text)

    for phrase in _CHECKLIST_START:
        if phrase in t:
            return checklist.start_checklist("dr400_pre_vol")
    for phrase in _QUIZ_START:
        if phrase in t:
            cat = None
            for c in ("météo", "meteo", "réglementation", "reglementation", "communications"):
                if c in t:
                    cat = c
                    break
            return quiz_ppl.start_quiz(cat)
    for phrase in _LOGBOOK_START:
        if phrase in t:
            return logbook.start_session()

    return None


def _handle_checklist(t: str) -> str:
    if any(w in t for w in ("vérifié", "verifie", "ok", "fait", "check", "suivant")):
        return checklist.confirm_current_item()
    if any(w in t for w in ("répète", "repete", "redis", "encore")):
        return checklist.repeat_current_item()
    if any(w in t for w in ("retour", "précédent", "precedent", "arrière", "arriere")):
        return checklist.go_back()
    if any(w in t for w in ("stop", "arrête", "arrete", "annule", "termine")):
        checklist.stop_checklist()
        return "Checklist interrompue."
    return checklist.repeat_current_item()


def _handle_quiz(t: str) -> str:
    m = re.search(r"\b([abcd])\b", t)
    if m:
        return quiz_ppl.answer(m.group(1))
    if "stop" in t or "arrête" in t or "arrete" in t:
        quiz_ppl.stop_quiz()
        return "Quiz interrompu."
    return "Réponds A, B, C ou D, ou dis stop pour quitter."
