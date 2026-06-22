"""
google_workspace.py — Orchestrateur Google Workspace + recherche web.
Tous les flux : recherche → synthèse LLM fast → écriture Google.
Règle : MODELS['fast'] uniquement, max 300 tokens par appel LLM.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

FAST_MAX_TOKENS = 300


def _fast_llm(prompt: str, *, max_tokens: int = 300, temperature: float = 0.3) -> str:
    import llm

    return llm.generate(
        prompt,
        model=llm.MODELS["fast"],
        max_tokens=min(max_tokens, FAST_MAX_TOKENS),
        temperature=temperature,
        stream=False,
    )


def _parse_json_response(response: str, fallback: dict) -> dict:
    try:
        clean = re.sub(r"```json|```", "", response or "").strip()
        return json.loads(clean)
    except Exception:
        return fallback


def _research_text(topic: str) -> str:
    from actions.web_research import format_results_for_llm, multi_search

    results = multi_search(
        topic,
        sources=["web", "wikipedia", "news"],
        max_per_source=4,
    )
    return format_results_for_llm(results, topic)[:2500]


# ── GOOGLE DOCS ─────────────────────────────────────────────────────────────


def research_and_write_doc(topic: str, doc_title: str | None = None) -> dict:
    """Recherche web + écriture structurée dans un Google Doc."""
    from actions.gdocs import create_doc, set_active_doc, write_section_to_doc

    title = doc_title or f"Recherche — {topic[:60]}"
    raw_results = _research_text(topic)

    structure_prompt = f"""Tu es ARIA. Structure ces résultats de recherche sur "{topic}" pour un Google Doc.
Format EXACT (JSON uniquement, pas de markdown) :
{{
  "sections": [
    {{"title": "Introduction", "content": "..."}},
    {{"title": "Points clés", "content": "..."}},
    {{"title": "Détails", "content": "..."}},
    {{"title": "Sources", "content": "..."}}
  ]
}}
Résultats: {raw_results[:2000]}"""

    response = _fast_llm(structure_prompt, max_tokens=300, temperature=0.3)
    data = _parse_json_response(response, {})
    sections = data.get("sections") or [{"title": topic, "content": raw_results[:1500]}]

    doc = create_doc(title)
    doc_id = doc["id"]
    doc_url = doc.get("url", "")

    for section in sections:
        write_section_to_doc(
            doc_id,
            title=str(section.get("title", "")),
            content=str(section.get("content", "")),
            heading_level=2,
        )

    set_active_doc(doc_id, title, doc_url)
    return {"doc_url": doc_url, "doc_title": title, "sections": len(sections)}


def write_text_to_active_doc(text: str) -> str:
    """Écrit du texte dans le doc actif de session."""
    from actions.gdocs import append_to_doc, create_doc, get_active_doc, set_active_doc

    active = get_active_doc()
    if not active:
        doc = create_doc("Notes ARIA")
        set_active_doc(doc["id"], doc["title"], doc.get("url", ""))
        active = get_active_doc()
    append_to_doc(active["id"], text)
    return f"Écrit dans « {active['title']} » ✓"


def append_research_to_active_doc(topic: str, fallback_text: str = "") -> str:
    """Recherche un sujet et ajoute la synthèse au doc actif."""
    from actions.gdocs import get_active_doc, write_markdown_to_doc
    from actions.web_research import build_doc_structure_prompt

    active = get_active_doc()
    if not active:
        return "Aucun doc actif. Lance d'abord une veille ou crée un doc."

    raw = _research_text(topic or fallback_text)
    if not raw:
        content = fallback_text
    else:
        structured = _fast_llm(
            build_doc_structure_prompt(topic or "notes", raw),
            max_tokens=300,
            temperature=0.25,
        )
        content = structured if not structured.startswith("Erreur") else raw[:1500]

    stamp = datetime.now().strftime("%d/%m %H:%M")
    write_markdown_to_doc(
        active["id"],
        f"## Notes — {stamp}\n{content}",
    )
    return f"Ajouté au doc « {active['title']} » ✓ — {active['url']}"


# ── GOOGLE SHEETS ────────────────────────────────────────────────────────────


def research_and_write_sheet(topic: str, sheet_title: str | None = None) -> dict:
    """Recherche + Google Sheet structuré."""
    from actions.gsheets import append_rows, create_spreadsheet, format_spreadsheet_header

    title = sheet_title or f"Tableau — {topic[:60]}"
    raw_results = _research_text(topic)

    table_prompt = f"""Transforme ces données sur "{topic}" en tableau structuré.
Format EXACT — JSON uniquement :
{{
  "headers": ["Colonne1", "Colonne2", "Colonne3"],
  "rows": [
    ["val1", "val2", "val3"]
  ]
}}
Maximum 15 lignes. Données: {raw_results[:1500]}"""

    response = _fast_llm(table_prompt, max_tokens=300, temperature=0.2)
    data = _parse_json_response(response, {})
    headers = data.get("headers") or [topic]
    rows = data.get("rows") or []
    if not rows and raw_results:
        rows = [[line] for line in raw_results.split("\n")[:10] if line.strip()]

    sheet = create_spreadsheet(title)
    sheet_id = sheet["id"]
    sheet_url = sheet.get("url", "")

    append_rows(sheet_id, [headers] + rows)
    format_spreadsheet_header(sheet_id)

    return {"sheet_url": sheet_url, "sheet_title": title, "rows": len(rows)}


def write_data_to_sheet(sheet_id: str, data: list, start_range: str = "A1") -> str:
    from actions.gsheets import write_range

    write_range(sheet_id, start_range, data)
    return "Données écrites dans le tableau ✓"


# ── GOOGLE FORMS ─────────────────────────────────────────────────────────────


def _build_form_question(q: dict, index: int) -> dict | None:
    qtype = str(q.get("type", "TEXT")).upper()
    base = {
        "title": q.get("title", f"Question {index + 1}"),
        "questionItem": {},
    }

    if qtype in ("TEXT", "PARAGRAPH"):
        base["questionItem"]["question"] = {
            "required": bool(q.get("required", False)),
            "textQuestion": {"paragraph": qtype == "PARAGRAPH"},
        }
    elif qtype in ("MULTIPLE_CHOICE", "CHECKBOX"):
        base["questionItem"]["question"] = {
            "required": bool(q.get("required", False)),
            "choiceQuestion": {
                "type": "RADIO" if qtype == "MULTIPLE_CHOICE" else "CHECKBOX",
                "options": [{"value": opt} for opt in q.get("options", ["Oui", "Non"])],
            },
        }
    elif qtype == "SCALE":
        base["questionItem"]["question"] = {
            "required": bool(q.get("required", False)),
            "scaleQuestion": {
                "low": 1,
                "high": 5,
                "lowLabel": "Pas du tout",
                "highLabel": "Totalement",
            },
        }
    elif qtype == "DATE":
        base["questionItem"]["question"] = {
            "required": bool(q.get("required", False)),
            "dateQuestion": {},
        }
    else:
        return None
    return base


def create_form_from_topic(topic: str, form_title: str | None = None) -> dict:
    """Crée un Google Form avec questions générées par le LLM fast."""
    from actions.google_auth import build_service

    title = form_title or f"Formulaire — {topic[:60]}"

    form_prompt = f"""Génère un formulaire Google Forms sur "{topic}".
Format JSON uniquement :
{{
  "title": "{title}",
  "description": "...",
  "questions": [
    {{"title": "Question 1 ?", "type": "TEXT", "required": true}},
    {{"title": "Question 2 ?", "type": "MULTIPLE_CHOICE",
      "required": false, "options": ["Option A", "Option B", "Option C"]}}
  ]
}}
Types: TEXT, PARAGRAPH, MULTIPLE_CHOICE, CHECKBOX, SCALE, DATE. Maximum 8 questions."""

    response = _fast_llm(form_prompt, max_tokens=300, temperature=0.4)
    form_data = _parse_json_response(
        response,
        {
            "title": title,
            "description": f"Formulaire sur {topic}",
            "questions": [{"title": "Votre réponse ?", "type": "TEXT", "required": True}],
        },
    )

    forms_svc = build_service("forms", "v1")
    form = forms_svc.forms().create(
        body={
            "info": {
                "title": form_data.get("title", title),
                "documentTitle": form_data.get("title", title),
            }
        }
    ).execute()

    form_id = form["formId"]
    form_url = form.get("responderUri", f"https://docs.google.com/forms/d/{form_id}/viewform")

    requests = []
    for i, q in enumerate(form_data.get("questions", [])):
        item = _build_form_question(q, i)
        if item:
            requests.append({"createItem": {"item": item, "location": {"index": i}}})

    if requests:
        forms_svc.forms().batchUpdate(formId=form_id, body={"requests": requests}).execute()

    if form_data.get("description"):
        forms_svc.forms().batchUpdate(
            formId=form_id,
            body={
                "requests": [{
                    "updateFormInfo": {
                        "info": {"description": form_data["description"]},
                        "updateMask": "description",
                    }
                }]
            },
        ).execute()

    logger.info("Form créé: %s — %s", title, form_url)
    return {
        "form_url": form_url,
        "form_title": form_data.get("title", title),
        "questions": len(form_data.get("questions", [])),
    }


# ── GMAIL ────────────────────────────────────────────────────────────────────


def draft_and_confirm_email(to: str, subject: str, context: str = "") -> dict:
    """Rédige un brouillon email (confirmation requise avant envoi)."""
    ctx = context or ""
    if ctx and len(ctx.split()) < 8:
        web_ctx = _research_text(ctx)[:500]
        if web_ctx:
            ctx = f"{ctx}\nContexte web: {web_ctx}"

    email_prompt = f"""Rédige un email professionnel en français.
Destinataire: {to}
Sujet: {subject}
Contexte: {ctx or 'email professionnel standard'}
Format JSON uniquement :
{{"objet": "...", "corps": "..."}}
Corps: 3-4 phrases max, professionnel, direct."""

    response = _fast_llm(email_prompt, max_tokens=200, temperature=0.4)
    email = _parse_json_response(response, {"objet": subject, "corps": response})

    return {
        "to": to,
        "subject": email.get("objet", subject),
        "body": email.get("corps", ""),
        "pending_send": True,
    }


# ── CALENDAR ─────────────────────────────────────────────────────────────────


def smart_create_calendar_event(text: str) -> dict:
    """Extrait titre/date/heure depuis le texte et crée l'événement."""
    from actions.gcalendar import create_event_from_fields, parse_event_json

    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")

    extract_prompt = f"""Extrait les informations d'événement depuis ce texte.
Format JSON uniquement :
{{"title": "...", "date": "YYYY-MM-DD", "time": "HH:MM", "duration_hours": 1, "location": "", "description": ""}}
Si la date est "demain", utilise {tomorrow}.
Si la date est "aujourd'hui", utilise {today}.
Texte: {text}"""

    response = _fast_llm(extract_prompt, max_tokens=80, temperature=0.1)
    if response.startswith("Erreur"):
        return {"success": False, "error": response}

    try:
        ev = parse_event_json(response)
        title = ev.get("title") or text.strip()[:50]
        msg = create_event_from_fields(
            title,
            str(ev.get("date") or ""),
            str(ev.get("time") or ""),
            str(ev.get("location") or ""),
        )
        url_m = re.search(r"https?://\S+", msg)
        start_label = ""
        if ev.get("date") and ev.get("time"):
            start_label = f"{ev['date']} {ev['time']}"
        return {
            "success": True,
            "title": title,
            "start": start_label,
            "url": url_m.group(0) if url_m else "",
            "message": msg,
        }
    except Exception as exc:
        logger.error("Calendar smart create: %s", exc)
        return {"success": False, "error": str(exc)}


def get_session_active_doc() -> dict | None:
    from actions.gdocs import get_active_doc

    return get_active_doc()
