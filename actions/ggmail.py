"""
ggmail.py — Gmail : lire et envoyer des emails.
"""

from __future__ import annotations

import base64
import logging
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from actions.google_auth import build_service, is_authenticated, is_configured

logger = logging.getLogger(__name__)


def _svc():
    return build_service("gmail", "v1")


def get_unread_emails(max_results: int = 5) -> list[dict]:
    """Retourne les emails non lus récents."""
    if not is_configured() or not is_authenticated():
        return []
    try:
        results = (
            _svc()
            .users()
            .messages()
            .list(userId="me", q="is:unread", maxResults=max_results)
            .execute()
        )
        messages = []
        for msg_ref in results.get("messages", []):
            msg = (
                _svc()
                .users()
                .messages()
                .get(
                    userId="me",
                    id=msg_ref["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )
            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            messages.append(
                {
                    "id": msg["id"],
                    "from": headers.get("From", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", ""),
                }
            )
        logger.info("Gmail: %d emails non lus", len(messages))
        return messages
    except Exception as exc:
        logger.error("Gmail get_unread: %s", exc)
        return []


def parse_email_draft(raw: str) -> tuple[str, str]:
    """Extrait objet et corps depuis la réponse LLM (OBJET:/CORPS:)."""
    subject = ""
    body = ""
    obj_m = re.search(r"OBJET\s*:\s*(.+?)(?:\n|$)", raw, re.I | re.S)
    corps_m = re.search(r"CORPS\s*:\s*(.+)$", raw, re.I | re.S)
    if obj_m:
        subject = obj_m.group(1).strip()
    if corps_m:
        body = corps_m.group(1).strip()
    if not subject and not body:
        lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
        if lines:
            subject = lines[0]
            body = "\n".join(lines[1:]) if len(lines) > 1 else lines[0]
    return subject, body


def format_draft_preview(to: str, subject: str, body: str) -> str:
    """Affiche un brouillon email dans le chat."""
    return (
        f"**Brouillon email pour {to}**\n\n"
        f"**Objet :** {subject}\n\n"
        f"{body}\n\n"
        "— Réponds **« oui envoie »** ou **« confirme »** pour envoyer, "
        "ou **« non »** pour annuler."
    )


def send_email(to: str, subject: str, body: str, html: bool = False) -> bool:
    """Envoie un email depuis le compte Gmail authentifié."""
    if not is_configured() or not is_authenticated():
        raise RuntimeError("Google non configuré ou non authentifié.")

    if html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "html"))
    else:
        msg = MIMEText(body)
    msg["to"] = to.strip()
    msg["subject"] = subject.strip()
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    _svc().users().messages().send(userId="me", body={"raw": raw}).execute()
    logger.info("Email envoyé à %s: %s", to, subject)
    return True


def format_emails_for_aria(emails: list[dict]) -> str:
    if not emails:
        return "Aucun email non lu."
    lines = [f"Tu as {len(emails)} email(s) non lu(s) :"]
    for e in emails:
        lines.append(f"• **{e.get('subject', '(sans objet)')}** de {e.get('from', '?')}")
        snippet = (e.get("snippet") or "").strip()
        if snippet:
            preview = snippet[:100] + ("…" if len(snippet) > 100 else "")
            lines.append(f"  _{preview}_")
    return "\n".join(lines)
