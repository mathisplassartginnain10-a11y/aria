"""Catalogue et gestion des modèles Ollama (Sprint F)."""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import app_paths

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

MODEL_CATALOG: list[dict] = [
    {
        "id": "llama3.2:1b",
        "name": "Llama 3.2 1B",
        "description": "Ultra léger — classification d'intents",
        "size_gb": 1.3,
        "use_case": "intent",
        "icon": "⚡",
        "ollama_name": "llama3.2:1b",
    },
    {
        "id": "qwen2.5:1.5b-instruct-q8_0",
        "name": "Qwen 2.5 1.5B",
        "description": "Intent alternatif, très rapide",
        "size_gb": 1.6,
        "use_case": "intent",
        "icon": "⚡",
        "ollama_name": "qwen2.5:1.5b-instruct-q8_0",
    },
    {
        "id": "llama3.1:8b-instruct-q8_0",
        "name": "Llama 3.1 8B",
        "description": "Réponses rapides et naturelles",
        "size_gb": 8.5,
        "use_case": "fast",
        "icon": "💬",
        "ollama_name": "llama3.1:8b-instruct-q8_0",
    },
    {
        "id": "phi3:mini",
        "name": "Phi-3 Mini",
        "description": "Compact, bon en français",
        "size_gb": 2.3,
        "use_case": "fast",
        "icon": "💬",
        "ollama_name": "phi3:mini",
    },
    {
        "id": "mistral:7b",
        "name": "Mistral 7B",
        "description": "Polyvalent, bon équilibre",
        "size_gb": 4.1,
        "use_case": "fast",
        "icon": "💬",
        "ollama_name": "mistral:7b",
    },
    {
        "id": "qwen3:14b",
        "name": "Qwen3 14B",
        "description": "Analyse approfondie et raisonnement",
        "size_gb": 9.0,
        "use_case": "heavy",
        "icon": "🧠",
        "ollama_name": "qwen3:14b",
    },
    {
        "id": "deepseek-r1:8b",
        "name": "DeepSeek R1 8B",
        "description": "Raisonnement chain-of-thought",
        "size_gb": 5.0,
        "use_case": "heavy",
        "icon": "🧠",
        "ollama_name": "deepseek-r1:8b",
    },
    {
        "id": "minicpm-v:latest",
        "name": "MiniCPM-V",
        "description": "Vision — images et captures",
        "size_gb": 5.5,
        "use_case": "vision",
        "icon": "👁️",
        "ollama_name": "minicpm-v:latest",
    },
    {
        "id": "codellama:7b",
        "name": "Code Llama 7B",
        "description": "Génération et analyse de code",
        "size_gb": 3.8,
        "use_case": "heavy",
        "icon": "💻",
        "ollama_name": "codellama:7b",
    },
]

_install_lock = threading.Lock()
_install_running = False


def _ollama_exe() -> str | None:
    try:
        import yaml
        with app_paths.config_path().open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        path = str(cfg.get("ollama_path", "")).replace("USERNAME", __import__("os").environ.get("USERNAME", ""))
        if path and Path(path).is_file():
            return path
    except Exception:
        pass
    which = shutil.which("ollama")
    return which


def get_installed_models() -> list[str]:
    exe = _ollama_exe()
    if not exe:
        return []
    try:
        out = subprocess.run(
            [exe, "list"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
        names: list[str] = []
        for line in (out.stdout or "").splitlines()[1:]:
            parts = line.split()
            if parts:
                names.append(parts[0])
        return names
    except Exception as exc:
        logger.debug("ollama list failed: %s", exc)
        return []


def _is_installed(model_id: str, installed: list[str]) -> bool:
    base = model_id.split(":")[0]
    for name in installed:
        if name == model_id or name.startswith(base + ":"):
            return True
    return False


def _active_roles() -> dict[str, str]:
    try:
        from llm import MODELS
        return dict(MODELS)
    except Exception:
        return {}


def get_model_catalog() -> list[dict]:
    installed = get_installed_models()
    roles = _active_roles()
    active_values = {str(v) for v in roles.values()}
    result = []
    for entry in MODEL_CATALOG:
        mid = entry["id"]
        item = dict(entry)
        item["installed"] = _is_installed(mid, installed)
        item["is_active"] = mid in active_values or any(
            mid.split(":")[0] in v for v in active_values
        )
        item["active_roles"] = [r for r, m in roles.items() if m == mid or mid.split(":")[0] in m]
        result.append(item)
    return result


def _emit(event: str, data) -> None:
    try:
        import ui_bridge as ui
        ui.emit(event, data)
    except Exception:
        logger.debug("emit %s failed", event, exc_info=True)


def install_model(model_id: str) -> dict:
    global _install_running
    entry = next((m for m in MODEL_CATALOG if m["id"] == model_id), None)
    if not entry:
        return {"success": False, "error": f"Modèle inconnu: {model_id}"}
    exe = _ollama_exe()
    if not exe:
        return {"success": False, "error": "ollama.exe introuvable"}

    with _install_lock:
        if _install_running:
            return {"success": False, "error": "Installation déjà en cours"}
        _install_running = True

    ollama_name = entry.get("ollama_name") or model_id

    def _run() -> None:
        global _install_running
        _emit("model_install_start", {"model_id": model_id, "name": entry["name"]})
        try:
            proc = subprocess.Popen(
                [exe, "pull", ollama_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if line:
                    _emit("model_install_progress", {"model_id": model_id, "line": line})
            proc.wait()
            ok = proc.returncode == 0
            _emit("model_install_done", {
                "model_id": model_id,
                "success": ok,
                "error": None if ok else f"ollama pull exit {proc.returncode}",
            })
        except Exception as exc:
            _emit("model_install_done", {"model_id": model_id, "success": False, "error": str(exc)})
        finally:
            with _install_lock:
                _install_running = False

    threading.Thread(target=_run, daemon=True, name=f"ARIA-Pull-{model_id}").start()
    return {"success": True, "started": True}


def uninstall_model(model_id: str) -> dict:
    entry = next((m for m in MODEL_CATALOG if m["id"] == model_id), None)
    if not entry:
        return {"success": False, "error": f"Modèle inconnu: {model_id}"}
    exe = _ollama_exe()
    if not exe:
        return {"success": False, "error": "ollama.exe introuvable"}
    ollama_name = entry.get("ollama_name") or model_id
    try:
        subprocess.run(
            [exe, "rm", ollama_name],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def set_model_for_role(role: str, model_id: str) -> dict:
    if role not in ("intent", "fast", "heavy", "vision"):
        return {"success": False, "error": f"Rôle invalide: {role}"}
    try:
        import llm
        llm.set_model_role(role, model_id)
        return {"success": True, "role": role, "model": model_id}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
