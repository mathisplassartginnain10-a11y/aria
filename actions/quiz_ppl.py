"""Quiz PPL interactif (master-doc §4.1)."""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path

import app_paths

logger = logging.getLogger(__name__)

_session: dict | None = None


def _load_questions() -> list[dict]:
    for path in (
        app_paths.data_dir() / "ppl_questions.json",
        app_paths.app_dir() / "data" / "ppl_questions.json",
    ):
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return [
        {
            "category": "Meteorology",
            "question": "Qu'est-ce qu'un METAR ?",
            "choices": ["Rapport météo aéroport", "Plan de vol", "NOTAM", "TAF"],
            "answer": 0,
        },
        {
            "category": "Regulations",
            "question": "Quelle est la visibilité minimale VFR en classe G de jour ?",
            "choices": ["1500 m", "5000 m", "8000 m", "Illimitée"],
            "answer": 0,
        },
    ]


def start_quiz(category: str | None = None) -> str:
    global _session
    questions = _load_questions()
    if category:
        cat = category.lower()
        questions = [q for q in questions if cat in q.get("category", "").lower()]
    if not questions:
        return "Aucune question disponible pour ce quiz."
    random.shuffle(questions)
    _session = {"questions": questions, "index": 0, "score": 0, "total": len(questions)}
    return _format_question()


def _format_question() -> str:
    if not _session:
        return "Aucun quiz en cours."
    q = _session["questions"][_session["index"]]
    choices = q.get("choices", [])
    letters = "ABCD"
    opts = " ".join(f"{letters[i]}: {c}" for i, c in enumerate(choices[:4]))
    return (
        f"Question {_session['index'] + 1}/{_session['total']} ({q.get('category', '')}). "
        f"{q['question']} — {opts}. Réponds A, B, C ou D."
    )


def answer(letter: str) -> str:
    global _session
    if not _session:
        return "Aucun quiz en cours. Dis 'lance un quiz PPL'."
    idx_map = {"a": 0, "b": 1, "c": 2, "d": 3}
    choice = idx_map.get(letter.strip().lower()[:1])
    if choice is None:
        return "Réponds A, B, C ou D."
    q = _session["questions"][_session["index"]]
    correct = int(q.get("answer", 0))
    if choice == correct:
        _session["score"] += 1
        feedback = "Correct !"
    else:
        feedback = f"Faux. La bonne réponse était {chr(65 + correct)}."
    _session["index"] += 1
    if _session["index"] >= _session["total"]:
        score = _session["score"]
        total = _session["total"]
        stop_quiz()
        return f"{feedback} Quiz terminé : {score}/{total} bonnes réponses."
    return f"{feedback} {_format_question()}"


def stop_quiz() -> None:
    global _session
    _session = None


def is_active() -> bool:
    return _session is not None
