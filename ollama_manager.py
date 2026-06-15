import logging
import subprocess
import sys
import time
from pathlib import Path

import requests
import app_paths

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

OLLAMA_API_TAGS = "http://localhost:11434/api/tags"
OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"

REQUIRED_MODELS = [
    "llama3.1:8b-instruct-q8_0",
    "qwen3:14b",
    "qwen2.5-coder:14b",
]

_process: subprocess.Popen | None = None
_ollama_path: Path | None = None


def configure(ollama_path: str | Path) -> None:
    global _ollama_path
    _ollama_path = Path(ollama_path)


def _is_ollama_reachable() -> bool:
    # 3s : quand Ollama charge un modèle il peut tarder à répondre à /api/tags ;
    # un timeout trop court (1s) le déclarait « absent » à tort.
    try:
        response = requests.get(OLLAMA_API_TAGS, timeout=3)
        return response.status_code == 200
    except requests.RequestException:
        return False


def is_running() -> bool:
    return _is_ollama_reachable()


def get_loaded_models() -> list[str]:
    try:
        response = requests.get(OLLAMA_API_TAGS, timeout=10)
        response.raise_for_status()
        models = response.json().get("models", [])
        return [m.get("name", "") for m in models if m.get("name")]
    except requests.RequestException:
        logger.exception("Failed to get loaded models")
        return []


def _normalize_model_name(name: str) -> str:
    return name.removesuffix(":latest")


def _model_available(model_name: str, loaded: list[str] | None = None) -> bool:
    if loaded is None:
        loaded = get_loaded_models()
    target = _normalize_model_name(model_name)
    return any(_normalize_model_name(n) == target for n in loaded)


def pull_model(model_name: str) -> bool:
    if _model_available(model_name):
        logger.info("Model %s already available", model_name)
        return True
    if _ollama_path is None or not _ollama_path.exists():
        logger.error("Ollama path not configured")
        return False
    try:
        result = subprocess.run(
            [str(_ollama_path), "pull", model_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
            timeout=600,
        )
        if result.returncode == 0:
            logger.info("Model %s pulled successfully", model_name)
            return True
        logger.error("Failed to pull model %s: %s", model_name, result.stderr.decode())
        return False
    except subprocess.TimeoutExpired:
        logger.error("Timeout pulling model %s", model_name)
        return False


def pull_missing_models() -> None:
    """Télécharge tous les modèles requis absents du cache Ollama."""
    loaded = get_loaded_models()
    for model_name in REQUIRED_MODELS:
        if not _model_available(model_name, loaded):
            logger.info("Pulling required model: %s", model_name)
            pull_model(model_name)
            loaded = get_loaded_models()


def start() -> None:
    global _process

    if _is_ollama_reachable():
        logger.info("Ollama already running")
        return

    if _ollama_path is None:
        logger.error("Ollama path not configured — call configure() first")
        return

    if not _ollama_path.exists():
        logger.error("Ollama executable not found at %s", _ollama_path)
        return

    _process = subprocess.Popen(
        [str(_ollama_path), "serve"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=CREATE_NO_WINDOW,
    )
    logger.info("Ollama started")


def stop() -> None:
    global _process

    if _process is None:
        return

    try:
        _process.terminate()
        _process.wait(timeout=5)
        logger.info("Ollama stopped")
    except subprocess.TimeoutExpired:
        logger.warning("Ollama did not terminate in time, killing process")
        _process.kill()
        _process.wait(timeout=5)
        logger.info("Ollama stopped")
    except Exception:
        logger.exception("Error while stopping Ollama")
        try:
            _process.kill()
            _process.wait(timeout=5)
            logger.info("Ollama stopped")
        except Exception:
            logger.exception("Failed to kill Ollama process")
    finally:
        _process = None


def wait_until_ready(timeout: float = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_ollama_reachable():
            return True
        time.sleep(0.5)
    logger.error("Ollama not ready after %.0f seconds", timeout)
    return False


def warmup_model(model: str) -> None:
    """Envoie une requête vide pour charger le modèle en VRAM."""
    try:
        logger.info("Chargement modèle %s en VRAM...", model)
        requests.post(
            OLLAMA_GENERATE_URL,
            json={"model": model, "prompt": " ", "keep_alive": "1h"},
            timeout=120,
        )
        logger.info("Modèle %s chargé en VRAM", model)
    except requests.RequestException as exc:
        logger.warning("Warmup échoué pour %s: %s", model, exc)