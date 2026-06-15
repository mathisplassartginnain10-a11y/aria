"""Export conversation PDF (master-doc §3.7)."""

from __future__ import annotations

import logging
from datetime import datetime

from fpdf import FPDF

import app_paths

logger = logging.getLogger(__name__)


class ConversationPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(108, 142, 255)
        self.cell(0, 10, "ARIA — Export de conversation", ln=True, align="C")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(120, 120, 130)
        self.cell(0, 6, datetime.now().strftime("%d/%m/%Y %H:%M"), ln=True, align="C")
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def _safe(text: str) -> str:
    return str(text).encode("latin-1", "replace").decode("latin-1")


def export_conversation(messages: list[dict], title: str = "Conversation") -> str:
    pdf = ConversationPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(20, 20, 25)
    pdf.cell(0, 10, _safe(title), ln=True)
    pdf.ln(4)

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content") or msg.get("text", "")
        timestamp = msg.get("timestamp") or msg.get("time", "")
        if role == "user":
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(70, 100, 220)
            label = f"Toi ({timestamp[:16]})" if timestamp else "Toi"
        else:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(30, 130, 100)
            label = f"ARIA ({timestamp[:16]})" if timestamp else "ARIA"
        pdf.cell(0, 6, _safe(label), ln=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(30, 30, 35)
        pdf.multi_cell(0, 5.5, _safe(content))
        pdf.ln(2)

    out_dir = app_paths.data_dir() / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"aria_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    out_path = out_dir / filename
    pdf.output(str(out_path))
    logger.info("Export PDF créé: %s", out_path)
    return str(out_path)
