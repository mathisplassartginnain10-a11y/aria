"""Gestion du processus Ollama et warmup des modèles."""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from pathlib import Path

import requests

import app_paths

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_API_TAGS = f"{OLLAMA_BASE_URL}/api/tags"
OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL}/api/generate"

REQUIRED_MODELS = [
    "llama3.1:8b-instruct-q8_0",
    "qwen3:14b",
    "qwen2.5-coder:14b",
]

_process: subprocess.Popen | None = None
_ollama_path: Path | None = None

# Chemins fallback Windows courants pour ollama.exe
_OLLAMA_FALLBACK_PATHS = (
    Path.home() / "AppData/Local/Programs/Ollama/ollama.exe",
    Path(r"C:\Program Files\Ollama\ollama.exe"),
)


def configure(ollama_path: str | Path) -> None:
    global _ollama_path
    _ollama_path = Path(ollama_path)


def _resolve_ollama_exe() -> Path | None:
    if _ollama_path and _ollama_path.exists():
        return _ollama_path
    for candidate in _OLLAMA_FALLBACK_PATHS:
        if candidate.exists():
            return candidate
    return None


def is_running() -> bool:
    """Vérifie si Ollama répond."""
    try:
        response = requests.get(OLLAMA_API_TAGS, timeout=3)
        return response.status_code == 200
    except requests.RequestException:
        return False


def list_local_models() -> list[str]:
    """Retourne la liste des modèles installés localement."""
    try:
        response = requests.get(OLLAMA_API_TAGS, timeout=5)
        response.raise_for_status()
        return [m.get("name", "") for m in response.json().get("models", []) if m.get("name")]
    except requests.RequestException as exc:
        logger.error("Erreur liste modèles: %s", exc)
        return []


def get_loaded_models() -> list[str]:
    """Alias historique — même chose que list_local_models()."""
    return list_local_models()


def _normalize_model_name(name: str) -> str:
    return name.removesuffix(":latest") if name else ""


def model_exists(name: str) -> bool:
    """Vérifie qu'un modèle est disponible localement."""
    if not name:
        return False
    target = _normalize_model_name(name)
    models = list_local_models()
    for installed in models:
        norm = _normalize_model_name(installed)
        if norm == target or target in norm or norm in target:
            return True
    return False


def _model_available(model_name: str, loaded: list[str] | None = None) -> bool:
    return model_exists(model_name) if loaded is None else any(
        _normalize_model_name(model_name) == _normalize_model_name(n) for n in loaded
    )


def _launch_ollama_serve(exe: Path | str | None = None) -> bool:
    """Tente de lancer `ollama serve`. Retourne True si le process a démarré."""
    commands: list[list[str]] = []
    if exe:
        commands.append([str(exe), "serve"])
    commands.append(["ollama", "serve"])

    for cmd in commands:
        try:
            subprocess.Popen(
                cmd,
                creationflags=CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.debug("Échec lancement %s: %s", cmd, exc)
    return False


def start_ollama() -> bool:
    """Lance ollama.exe s'il ne tourne pas. Retourne True si OK."""
    if is_running():
        logger.info("Ollama already running")
        return True

    logger.info("Lancement de ollama serve...")
    exe = _resolve_ollama_exe()
    if not _launch_ollama_serve(exe):
        logger.error("Impossible de lancer ollama.exe")
        return False

    for i in range(30):
        time.sleep(0.5)
        if is_running():
            logger.info("Ollama démarré (%.1fs)", (i + 1) * 0.5)
            return True

    logger.error("Ollama n'a pas démarré dans les 15s")
    return False


def start() -> None:
    """Compat historique — démarre Ollama sans valeur de retour."""
    global _process

    if is_running():
        logger.info("Ollama already running")
        return

    exe = _resolve_ollama_exe()
    if exe is None:
        logger.error("Ollama path not configured — call configure() first")
        if not start_ollama():
            return
        return

    try:
        _process = subprocess.Popen(
            [str(exe), "serve"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
        )
        logger.info("Ollama started via %s", exe)
    except Exception:
        start_ollama()


def wait_until_ready(timeout: float = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_running():
            return True
        time.sleep(0.5)
    logger.error("Ollama not ready after %.0f seconds", timeout)
    return False


def pull_model(model_name: str) -> bool:
    if _model_available(model_name):
        logger.info("Model %s already available", model_name)
        return True
    exe = _resolve_ollama_exe()
    if exe is None:
        logger.error("Ollama path not configured")
        return False
    try:
        result = subprocess.run(
            [str(exe), "pull", model_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
            timeout=600,
        )
        if result.returncode == 0:
            logger.info("Model %s pulled successfully", model_name)
            return True
        logger.error("Failed to pull model %s: %s", model_name, result.stderr.decode(errors="replace"))
        return False
    except subprocess.TimeoutExpired:
        logger.error("Timeout pulling model %s", model_name)
        return False


def pull_missing_models() -> None:
    loaded = list_local_models()
    for model_name in REQUIRED_MODELS:
        if not _model_available(model_name, loaded):
            logger.info("Pulling required model: %s", model_name)
            pull_model(model_name)
            loaded = list_local_models()


def warmup_model(model_name: str) -> None:
    """Charge un modèle en VRAM. Utilise keep_alive avec un prompt minimal valide."""
    if not model_exists(model_name):
        logger.warning("Modèle '%s' absent — warmup ignoré", model_name)
        return
    try:
        logger.info("Chargement modèle %s en VRAM...", model_name)
        resp = requests.post(
            OLLAMA_GENERATE_URL,
            json={
                "model": model_name,
                "prompt": "Hi",
                "stream": False,
                "keep_alive": "10m",
                "options": {"num_predict": 1},
            },
            timeout=60,
        )
        if resp.status_code == 200:
            logger.info("Modèle %s chargé en VRAM", model_name)
        else:
            logger.warning(
                "Warmup %s: HTTP %d — %s",
                model_name,
                resp.status_code,
                resp.text[:100],
            )
    except requests.RequestException as exc:
        logger.error("Warmup %s échoué: %s", model_name, exc)


def stop() -> None:
    """Arrête le processus lancé par ce module (si connu)."""
    global _process
    if _process is None:
        return
    try:
        _process.terminate()
        _process.wait(timeout=5)
        logger.info("Ollama stopped")
    except subprocess.TimeoutExpired:
        _process.kill()
        _process.wait(timeout=5)
    except Exception:
        logger.exception("Error while stopping Ollama")
    finally:
        _process = None


def stop_ollama() -> None:
    """Tue tous les processus ollama.exe / ollama."""
    stop()
    try:
        import psutil

        for proc in psutil.process_iter(["name", "pid"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name in ("ollama.exe", "ollama"):
                    proc.terminate()
                    logger.info("ollama tué (PID %s)", proc.info.get("pid"))
            except Exception:
                pass
    except ImportError:
        logger.warning("psutil absent — stop_ollama partiel")
