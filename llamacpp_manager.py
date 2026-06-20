"""
llamacpp_manager.py — Gestion des serveurs llama.cpp locaux.

Architecture : un serveur llama-server.exe par modèle actif.
Chaque serveur écoute sur un port différent.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

LLAMA_SERVER_EXE = os.environ.get("LLAMA_SERVER_PATH", r"C:\llama.cpp\llama-server.exe")

OLLAMA_URL = "http://localhost:11434"

OLLAMA_BLOBS_DIR = Path(os.environ.get("USERPROFILE", "C:/Users/mathi")) / ".ollama/models/blobs"
OLLAMA_MANIFESTS_DIR = Path(os.environ.get("USERPROFILE", "C:/Users/mathi")) / ".ollama/models/manifests"
CUSTOM_MODELS_DIR: Path | None = None

DEFAULT_PARAMS = {
    "ctx_size": 4096,
    "n_gpu_layers": 99,  # tout sur GPU — RTX 5080 16GB VRAM
    "threads": 8,
    "batch_size": 512,
}

_servers: dict[str, dict] = {}
_port_counter = 8080
_lock = threading.Lock()


def _resolve_server_exe(configured: str | None = None) -> str:
    """Cherche llama-server.exe (config, env, PATH, emplacements courants)."""
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    env_path = os.environ.get("LLAMA_SERVER_PATH")
    if env_path:
        candidates.append(Path(env_path))
    app_dir = Path(__file__).resolve().parent
    candidates.extend([
        app_dir / "llama-server.exe",
        app_dir / "bin" / "llama-server.exe",
        app_dir / "llama.cpp" / "llama-server.exe",
        app_dir / "tools" / "llama-server.exe",
        Path(r"C:\llama.cpp\llama-server.exe"),
        Path(r"C:\llama.cpp\build\bin\Release\llama-server.exe"),
        Path(r"C:\llama.cpp\build\bin\llama-server.exe"),
    ])
    which = shutil.which("llama-server") or shutil.which("llama-server.exe")
    if which:
        candidates.append(Path(which))
    for path in candidates:
        try:
            if path.is_file():
                return str(path.resolve())
        except OSError:
            continue
    return str(candidates[0]) if candidates else LLAMA_SERVER_EXE


def configure(cfg: dict | None = None) -> None:
    """Applique la section llamacpp de config.yaml."""
    global LLAMA_SERVER_EXE, OLLAMA_BLOBS_DIR, OLLAMA_MANIFESTS_DIR
    global CUSTOM_MODELS_DIR, DEFAULT_PARAMS, _port_counter

    if not cfg:
        return

    llamacpp = cfg.get("llamacpp") or {}
    configured_path = llamacpp.get("server_path") if llamacpp.get("server_path") else None
    LLAMA_SERVER_EXE = _resolve_server_exe(str(configured_path) if configured_path else None)
    if Path(LLAMA_SERVER_EXE).exists():
        logger.info("llama-server: %s", LLAMA_SERVER_EXE)
    else:
        logger.warning(
            "llama-server introuvable (%s) — modèles locaux indisponibles, IA cloud OK",
            LLAMA_SERVER_EXE,
        )
    if llamacpp.get("blobs_dir"):
        OLLAMA_BLOBS_DIR = Path(str(llamacpp["blobs_dir"]))
    if llamacpp.get("manifests_dir"):
        OLLAMA_MANIFESTS_DIR = Path(str(llamacpp["manifests_dir"]))
    if llamacpp.get("models_dir"):
        CUSTOM_MODELS_DIR = Path(str(llamacpp["models_dir"]))

    for key in ("ctx_size", "n_gpu_layers", "threads", "batch_size"):
        if key in llamacpp:
            DEFAULT_PARAMS[key] = llamacpp[key]
    if llamacpp.get("base_port") is not None:
        _port_counter = int(llamacpp["base_port"])


def _blob_from_manifest(manifest_path: Path) -> Path | None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for layer in manifest.get("layers", []):
            if layer.get("mediaType") == "application/vnd.ollama.image.model":
                digest = layer["digest"].replace("sha256:", "sha256-")
                blob_path = OLLAMA_BLOBS_DIR / digest
                if blob_path.exists():
                    return blob_path
    except Exception as exc:
        logger.debug("Erreur lecture manifeste %s: %s", manifest_path, exc)
    return None


def _find_in_custom_dir(model_name: str) -> Path | None:
    if not CUSTOM_MODELS_DIR or not CUSTOM_MODELS_DIR.exists():
        return None

    base = model_name.split(":", 1)[0].lower()
    needles = {
        base,
        base.replace(".", ""),
        model_name.lower(),
        model_name.replace(":", "-").lower(),
    }

    for path in CUSTOM_MODELS_DIR.rglob("*"):
        if not path.is_file():
            continue
        name_lower = path.name.lower()
        if path.suffix.lower() == ".gguf":
            if any(n in name_lower for n in needles if n):
                return path
        elif not path.suffix and path.stat().st_size > 50_000_000:
            if any(n in name_lower for n in needles if n):
                return path
    return None


def _find_model_blob(model_name: str) -> Path | None:
    """
    Trouve le fichier GGUF d'un modèle depuis les blobs Ollama ou models_dir.
    model_name: ex 'llama3.2:1b', 'qwen3:14b'
    """
    parts = model_name.split(":", 1)
    base = parts[0]
    tag = parts[1] if len(parts) > 1 else "latest"

    manifests_base = OLLAMA_MANIFESTS_DIR / "registry.ollama.ai" / "library"
    candidates = [
        manifests_base / base / tag,
        manifests_base / base / "latest",
    ]

    for manifest_path in candidates:
        if manifest_path.is_file():
            blob = _blob_from_manifest(manifest_path)
            if blob:
                logger.info(
                    "Modèle '%s' → %s (%.1f Go)",
                    model_name,
                    blob.name,
                    blob.stat().st_size / 1e9,
                )
                return blob

    custom = _find_in_custom_dir(model_name)
    if custom:
        logger.info("Modèle '%s' → custom %s", model_name, custom)
        return custom

    logger.warning("Modèle '%s' non trouvé dans les blobs Ollama", model_name)
    return None


def list_available_models() -> list[str]:
    """Liste tous les modèles disponibles (manifestes Ollama + models_dir)."""
    models: list[str] = []
    seen: set[str] = set()
    manifests_base = OLLAMA_MANIFESTS_DIR / "registry.ollama.ai" / "library"

    if manifests_base.exists():
        for model_dir in manifests_base.iterdir():
            if not model_dir.is_dir():
                continue
            for tag_file in model_dir.iterdir():
                if not tag_file.is_file():
                    continue
                model_name = f"{model_dir.name}:{tag_file.name}"
                if _blob_from_manifest(tag_file):
                    if model_name not in seen:
                        seen.add(model_name)
                        models.append(model_name)

    if CUSTOM_MODELS_DIR and CUSTOM_MODELS_DIR.exists():
        for path in CUSTOM_MODELS_DIR.rglob("*.gguf"):
            name = path.stem.replace("-", ":").replace("_", ":")
            if name not in seen:
                seen.add(name)
                models.append(name)

    return sorted(models)


def model_exists(model_name: str) -> bool:
    return _find_model_blob(model_name) is not None


def _next_port() -> int:
    global _port_counter
    with _lock:
        port = _port_counter
        _port_counter += 1
        return port


def start_model_server(model_name: str, params: dict | None = None) -> dict | None:
    """
    Démarre un serveur llama-server.exe pour un modèle donné.
    Retourne {process, port, url, model_path, model_name} ou None si échec.
    """
    if model_name in _servers:
        info = _servers[model_name]
        if info["process"].poll() is None:
            logger.info("Serveur '%s' déjà actif sur port %d", model_name, info["port"])
            return info
        logger.warning("Serveur '%s' mort — redémarrage", model_name)
        del _servers[model_name]

    model_path = _find_model_blob(model_name)
    if not model_path:
        logger.error("Impossible de trouver le modèle '%s'", model_name)
        return None

    if not Path(LLAMA_SERVER_EXE).exists():
        logger.warning(
            "llama-server.exe non trouvé: %s — https://github.com/ggerganov/llama.cpp/releases",
            LLAMA_SERVER_EXE,
        )
        return None

    port = _next_port()
    p = {**DEFAULT_PARAMS, **(params or {})}

    cmd = [
        LLAMA_SERVER_EXE,
        "--model",
        str(model_path),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--ctx-size",
        str(p.get("ctx_size", DEFAULT_PARAMS["ctx_size"])),
        "--n-gpu-layers",
        str(p.get("n_gpu_layers", DEFAULT_PARAMS["n_gpu_layers"])),
        "--threads",
        str(p.get("threads", DEFAULT_PARAMS["threads"])),
        "--batch-size",
        str(p.get("batch_size", DEFAULT_PARAMS["batch_size"])),
        "--no-mmap",
        "--log-disable",
    ]

    logger.info(
        "Démarrage llama-server: modèle=%s, port=%d, n_gpu_layers=%d",
        model_name, port, p.get("n_gpu_layers", DEFAULT_PARAMS["n_gpu_layers"]),
    )
    logger.debug("Commande: %s", " ".join(cmd))

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )

        url = f"http://127.0.0.1:{port}"
        for _ in range(60):
            time.sleep(0.5)
            if process.poll() is not None:
                logger.error("llama-server a planté immédiatement (modèle=%s)", model_name)
                return None
            try:
                resp = requests.get(f"{url}/health", timeout=1)
                if resp.status_code == 200:
                    logger.info("Serveur '%s' prêt sur port %d", model_name, port)
                    break
            except Exception:
                pass
        else:
            logger.error("Timeout démarrage serveur '%s'", model_name)
            process.kill()
            return None

        info = {
            "process": process,
            "port": port,
            "url": url,
            "model_path": str(model_path),
            "model_name": model_name,
        }
        _servers[model_name] = info
        return info

    except Exception as exc:
        logger.error("Erreur démarrage serveur '%s': %s", model_name, exc)
        return None


def get_server_url(model_name: str) -> str | None:
    """Retourne l'URL d'un serveur actif, None si pas démarré."""
    info = _servers.get(model_name)
    if info and info["process"].poll() is None:
        return info["url"]
    return None


def is_ollama_available() -> bool:
    """True si l'API Ollama répond sur localhost:11434."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def get_fallback_url(model_name: str) -> str | None:
    """Retourne l'URL Ollama si disponible, None sinon."""
    if is_ollama_available():
        return OLLAMA_URL
    return None


def is_running(model_name: str | None = None) -> bool:
    """True si au moins un serveur (ou le modèle donné) est actif."""
    if model_name:
        return get_server_url(model_name) is not None
    return any(info["process"].poll() is None for info in _servers.values())


def stop_all_servers() -> None:
    """Arrête tous les serveurs llama.cpp."""
    for model_name, info in list(_servers.items()):
        try:
            info["process"].terminate()
            info["process"].wait(timeout=3)
            logger.info("Serveur '%s' arrêté", model_name)
        except Exception:
            try:
                info["process"].kill()
            except Exception:
                pass
    _servers.clear()


def stop_server(model_name: str) -> None:
    """Arrête un serveur spécifique."""
    info = _servers.pop(model_name, None)
    if info:
        try:
            info["process"].terminate()
        except Exception:
            pass
        logger.info("Serveur '%s' arrêté", model_name)
