import logging
from pathlib import Path

import pygame
import yaml
import app_paths

logger = logging.getLogger(__name__)

_CONFIG_PATH = app_paths.config_path()
with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

SOUNDS_ENABLED: bool = _config.get("sounds_enabled", True)
SOUNDS_DIR = app_paths.sounds_dir()

_pygame_ready = False


def _ensure_mixer() -> None:
    global _pygame_ready
    if not _pygame_ready:
        pygame.mixer.init()
        _pygame_ready = True


def play(name: str) -> None:
    if not SOUNDS_ENABLED:
        return
    path = SOUNDS_DIR / f"{name}.wav"
    if not path.exists():
        logger.warning("Sound file not found: %s", path)
        return
    try:
        _ensure_mixer()
        sound = pygame.mixer.Sound(str(path))
        sound.play()
    except Exception:
        logger.exception("Failed to play sound: %s", name)