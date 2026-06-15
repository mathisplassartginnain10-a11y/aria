"""Détection wake word en continu (master-doc §3.1)."""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_stop_event = threading.Event()
_wake_callback = None


def start(callback, model_name: str = "hey_jarvis_v0.1") -> None:
    global _wake_callback
    _wake_callback = callback
    _stop_event.clear()
    thread = threading.Thread(target=_listen_loop, args=(model_name,), daemon=True)
    thread.start()
    logger.info("Wake word detection démarrée (modèle: %s)", model_name)


def stop() -> None:
    _stop_event.set()


def _listen_loop(model_name: str) -> None:
    try:
        import numpy as np
        import sounddevice as sd
        from openwakeword.model import Model
    except ImportError as exc:
        logger.error("openwakeword/sounddevice requis pour le wake word: %s", exc)
        return

    try:
        oww_model = Model(wakeword_models=[model_name], inference_framework="onnx")
    except Exception as exc:
        logger.error("Impossible de charger le modèle wake word: %s", exc)
        return

    sample_rate = 16000
    chunk = 1280
    stream = None
    try:
        stream = sd.InputStream(samplerate=sample_rate, channels=1, dtype="int16", blocksize=chunk)
        stream.start()
    except Exception as exc:
        logger.error("Impossible d'ouvrir le micro pour wake word: %s", exc)
        return

    logger.info("En écoute du wake word...")
    cooldown = 0
    try:
        while not _stop_event.is_set():
            try:
                audio, _ = stream.read(chunk)
                audio = audio.flatten()
                if cooldown > 0:
                    cooldown -= 1
                    continue
                prediction = oww_model.predict(audio)
                for _mdl, score in prediction.items():
                    if score > 0.5:
                        logger.info("Wake word détecté (score=%.2f)", score)
                        cooldown = 20
                        if _wake_callback:
                            _wake_callback()
            except Exception as exc:
                logger.warning("Erreur boucle wake word: %s", exc)
    finally:
        if stream:
            stream.stop()
            stream.close()
