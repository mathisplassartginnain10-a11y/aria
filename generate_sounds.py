"""Génère les fichiers WAV par défaut si absents."""

import logging
from pathlib import Path

import numpy as np
from scipy.io import wavfile
import app_paths

logger = logging.getLogger(__name__)

SOUNDS_DIR = app_paths.app_dir() / "sounds"
SAMPLE_RATE = 22050


def _tone(freq: float, duration: float, volume: float = 0.3) -> np.ndarray:
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    wave = np.sin(2 * np.pi * freq * t) * volume
    fade = int(SAMPLE_RATE * 0.02)
    wave[:fade] *= np.linspace(0, 1, fade)
    wave[-fade:] *= np.linspace(1, 0, fade)
    return (wave * 32767).astype(np.int16)


def _save(name: str, data: np.ndarray) -> None:
    path = SOUNDS_DIR / f"{name}.wav"
    if path.exists():
        return
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(path), SAMPLE_RATE, data)
    logger.info("Generated sound: %s", path.name)


def ensure_sounds() -> None:
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    _save("activate", _tone(880, 0.15))
    _save("deactivate", _tone(440, 0.2))
    _save("listening", _tone(660, 0.08))
    _save("thinking", np.concatenate([_tone(520, 0.1), _tone(620, 0.1)]))
    _save("error", np.concatenate([_tone(200, 0.15), _tone(150, 0.2)]))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_sounds()
    print("Sons générés dans", SOUNDS_DIR)