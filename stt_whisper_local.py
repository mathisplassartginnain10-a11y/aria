"""
Backend STT openai/whisper — utilise la copie locale voix ia/whisper-main.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import numpy as np

import app_paths

logger = logging.getLogger(__name__)

_whisper_module: Any | None = None
_import_error: Exception | None = None


def _cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def is_available() -> bool:
    """True si voix ia/whisper-main est présent et importable."""
    return voix_ia_whisper_dir() is not None and _ensure_whisper_module() is not None


def voix_ia_whisper_dir() -> str | None:
    root = app_paths.voix_ia_whisper_dir()
    return str(root) if root else None


def _ensure_whisper_module():
    global _whisper_module, _import_error
    if _whisper_module is not None:
        return _whisper_module

    root = app_paths.voix_ia_whisper_dir()
    if not root:
        _import_error = FileNotFoundError(
            "Dossier voix ia/whisper-main introuvable à la racine du projet."
        )
        return None

    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    try:
        import whisper  # type: ignore[import-untyped]

        _whisper_module = whisper
        logger.info("Whisper local chargé depuis %s", root_str)
        return _whisper_module
    except Exception as exc:
        _import_error = exc
        logger.error("Import whisper local échoué: %s", exc)
        return None


def load_model(
    model_name: str,
    download_root: str | None = None,
    *,
    device: str | None = None,
) -> tuple[Any, str]:
    """
    Charge un modèle openai/whisper depuis voix ia/.
    Retourne (model, device).
    """
    whisper = _ensure_whisper_module()
    if whisper is None:
        raise RuntimeError(
            f"Whisper local indisponible: {_import_error or 'voix ia/ absent'}"
        )

    device = device or ("cuda" if _cuda_available() else "cpu")

    cache = download_root or str(app_paths.whisper_models_dir())
    logger.info(
        "Chargement Whisper local '%s' sur %s (cache=%s)",
        model_name,
        device,
        cache,
    )
    model = whisper.load_model(model_name, device=device, download_root=cache)
    return model, device


def transcribe_audio(
    model: Any,
    audio_16k: np.ndarray,
    *,
    language: str = "fr",
    beam_size: int = 5,
    temperature: float = 0.0,
    **_ignored: Any,
) -> str:
    """Transcrit un numpy float32 mono 16 kHz."""
    whisper = _ensure_whisper_module()
    if whisper is None:
        raise RuntimeError("Module whisper local indisponible")

    audio = np.asarray(audio_16k, dtype=np.float32).flatten()
    if audio.size == 0:
        return ""

    fp16 = False
    try:
        import torch

        fp16 = bool(getattr(model, "device", None) and str(model.device).startswith("cuda"))
    except Exception:
        fp16 = False

    result = whisper.transcribe(
        model,
        audio,
        language=language or None,
        fp16=fp16,
        beam_size=beam_size,
        temperature=temperature,
        condition_on_previous_text=False,
        verbose=False,
    )
    return str(result.get("text", "") or "").strip()


def transcribe_file(
    model: Any,
    path: str,
    *,
    language: str = "fr",
    beam_size: int = 5,
    temperature: float = 0.0,
) -> str:
    whisper = _ensure_whisper_module()
    if whisper is None:
        raise RuntimeError("Module whisper local indisponible")

    fp16 = False
    try:
        fp16 = bool(getattr(model, "device", None) and str(model.device).startswith("cuda"))
    except Exception:
        fp16 = False

    result = whisper.transcribe(
        model,
        path,
        language=language or None,
        fp16=fp16,
        beam_size=beam_size,
        temperature=temperature,
        verbose=False,
    )
    return str(result.get("text", "") or "").strip()
