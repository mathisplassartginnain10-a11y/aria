"""Checklist interactive vocale (master-doc §3.4)."""

from __future__ import annotations

import logging

import yaml

import app_paths

logger = logging.getLogger(__name__)

_active_checklist: dict | None = None
_current_section = 0
_current_item = 0


def load_checklist(name: str) -> dict:
    path = app_paths.data_dir() / "checklists" / f"{name}.yaml"
    if not path.exists():
        path = app_paths.app_dir() / "data" / "checklists" / f"{name}.yaml"
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _sync_ui() -> None:
    progress = get_progress()
    try:
        import ui

        if progress:
            ui.update_checklist_ui(progress["section"], progress["item"], progress["total"])
        else:
            ui.hide_checklist_ui()
    except Exception:
        pass


def start_checklist(name: str) -> str:
    global _active_checklist, _current_section, _current_item
    _active_checklist = load_checklist(name)
    _current_section = 0
    _current_item = 0
    _sync_ui()
    return _format_current_item(intro=True)


def _format_current_item(intro: bool = False) -> str:
    if not _active_checklist:
        return "Aucune checklist en cours."
    sections = _active_checklist["items"]
    if _current_section >= len(sections):
        return "Checklist terminée. Tous les points ont été vérifiés."
    section = sections[_current_section]
    points = section["points"]
    if _current_item >= len(points):
        return "Section terminée."
    point = points[_current_item]
    progress = f"({_current_item + 1}/{len(points)})"
    prefix = f"Checklist '{_active_checklist['nom']}' démarrée. " if intro else ""
    section_intro = f"Section : {section['section']}. " if _current_item == 0 else ""
    return f"{prefix}{section_intro}{progress} {point}. Dis 'vérifié' quand c'est fait."


def confirm_current_item() -> str:
    global _current_section, _current_item
    if not _active_checklist:
        return "Aucune checklist en cours. Dis 'démarre la checklist DR400' pour commencer."
    sections = _active_checklist["items"]
    _current_item += 1
    if _current_item >= len(sections[_current_section]["points"]):
        _current_section += 1
        _current_item = 0
        if _current_section >= len(sections):
            result = "Checklist terminée. Tous les points sont vérifiés. Bon vol !"
            stop_checklist()
            return result
    _sync_ui()
    return _format_current_item()


def repeat_current_item() -> str:
    return _format_current_item()


def go_back() -> str:
    global _current_section, _current_item
    if not _active_checklist:
        return "Aucune checklist en cours."
    if _current_item > 0:
        _current_item -= 1
    elif _current_section > 0:
        _current_section -= 1
        _current_item = len(_active_checklist["items"][_current_section]["points"]) - 1
    _sync_ui()
    return "Retour à l'item précédent. " + _format_current_item()


def stop_checklist() -> None:
    global _active_checklist, _current_section, _current_item
    _active_checklist = None
    _current_section = 0
    _current_item = 0
    _sync_ui()


def is_active() -> bool:
    return _active_checklist is not None


def get_progress() -> dict | None:
    if not _active_checklist:
        return None
    section = _active_checklist["items"][_current_section]
    return {
        "section": section["section"],
        "item": _current_item + 1,
        "total": len(section["points"]),
    }
