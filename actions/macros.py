"""Macros vocales (master-doc §4.6)."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

import app_paths

logger = logging.getLogger(__name__)

MACROS_PATH = app_paths.data_dir() / "macros.yaml"


def _load() -> dict:
    if MACROS_PATH.exists():
        return yaml.safe_load(MACROS_PATH.read_text(encoding="utf-8")) or {}
    default = {
        "revision_bac": {
            "label": "Révision BAC",
            "steps": ["active le mode focus", "lance spotify", "ouvre cursor"],
        }
    }
    MACROS_PATH.parent.mkdir(parents=True, exist_ok=True)
    MACROS_PATH.write_text(yaml.safe_dump(default, allow_unicode=True), encoding="utf-8")
    return default


def list_macros() -> list[str]:
    return list(_load().keys())


def run_macro(name: str, execute_fn) -> str:
    macros = _load()
    macro = macros.get(name)
    if not macro:
        return f"Macro '{name}' introuvable."
    results = []
    for step in macro.get("steps", []):
        try:
            results.append(execute_fn(step))
        except Exception as exc:
            results.append(f"Erreur sur '{step}': {exc}")
    return f"Macro '{macro.get('label', name)}' exécutée. " + " | ".join(r for r in results if r)
