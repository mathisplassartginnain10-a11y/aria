import asyncio
import concurrent.futures
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path

import yaml
import app_paths

logger = logging.getLogger(__name__)

_CONFIG_PATH = app_paths.config_path()
with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

TTS_VOICE: str = _config["tts_voice"]
TTS_RATE: str = _config["tts_rate"]
SOUNDS_DIR = app_paths.sounds_dir()

_lock = threading.Lock()
_stop_event = threading.Event()
_duck_lock = threading.Lock()
_saved_sessions: list[tuple] = []

# Global TTS enabled flag — disabled by default
TTS_ENABLED = False

_mixer_ready = False
_mixer_lock = threading.Lock()


def _ensure_mixer() -> None:
    """Initialise pygame.mixer à la demande (évite blocage au import)."""
    global _mixer_ready
    if _mixer_ready:
        return
    with _mixer_lock:
        if _mixer_ready:
            return
        import pygame

        pygame.mixer.init()
        _mixer_ready = True


def _pygame():
    import pygame

    return pygame


def mute_other_apps() -> None:
    global _saved_sessions
    with _duck_lock:
        if _saved_sessions:
            return
        try:
            from pycaw.pycaw import AudioUtilities

            own_pid = os.getpid()
            saved: list[tuple] = []

            for session in AudioUtilities.GetAllSessions():
                try:
                    if session.ProcessId == own_pid:
                        continue
                    if session.State != 1:
                        continue
                    volume = session.SimpleAudioVolume
                    if volume is None:
                        continue
                    was_mute = bool(volume.GetMute())
                    master_vol = float(volume.GetMasterVolume())
                    volume.SetMute(1, None)
                    saved.append((volume, was_mute, master_vol))
                except Exception:
                    continue

            _saved_sessions = saved
        except Exception:
            _saved_sessions = []


def restore_other_apps() -> None:
    global _saved_sessions
    with _duck_lock:
        if not _saved_sessions:
            return
        try:
            for volume, was_mute, master_vol in _saved_sessions:
                try:
                    volume.SetMasterVolume(master_vol, None)
                    volume.SetMute(1 if was_mute else 0, None)
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            _saved_sessions = []


def _clean_text(text: str) -> str:
    text = re.sub(r"[*_#`~\[\]()]", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^\w\s\u00C0-\u024F.,!?;:'\"-]", "", text, flags=re.UNICODE)
    return " ".join(text.split()).strip()


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


async def _generate_audio(text: str, output_path: Path, voice: str, rate: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(output_path))


def _run_async(coro) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            future.result()
    else:
        asyncio.run(coro)


def _play_music() -> None:
    _ensure_mixer()
    mute_other_apps()
    try:
        pg = _pygame()
        pg.mixer.music.play()
        while pg.mixer.music.get_busy() and not _stop_event.is_set():
            time.sleep(0.05)
    finally:
        restore_other_apps()


def set_voice(voice_name: str) -> None:
    global TTS_VOICE
    TTS_VOICE = voice_name
    logger.info("TTS voice set to %s", voice_name)


def set_rate(rate: str) -> None:
    global TTS_RATE
    TTS_RATE = rate
    logger.info("TTS rate set to %s", rate)


def set_enabled(enabled: bool) -> None:
    global TTS_ENABLED
    TTS_ENABLED = enabled
    logger.info("TTS %s", "activé" if enabled else "désactivé")


def stop() -> None:
    _stop_event.set()
    if not _mixer_ready:
        restore_other_apps()
        return
    try:
        pg = _pygame()
        pg.mixer.music.stop()
    except Exception:
        pass
    restore_other_apps()


def speak_sound(sound_name: str) -> None:
    path = SOUNDS_DIR / f"{sound_name}.wav"
    if not path.exists():
        logger.warning("Sound not found: %s", path)
        return
    with _lock:
        try:
            _ensure_mixer()
            pg = _pygame()
            pg.mixer.music.load(str(path))
            pg.mixer.music.play()
            while pg.mixer.music.get_busy() and not _stop_event.is_set():
                time.sleep(0.05)
        except Exception:
            logger.exception("Failed to play sound %s", sound_name)


def speak(text: str) -> None:
    if not TTS_ENABLED:
        logger.debug("TTS désactivé, skip: %s", text[:50])
        return

    if not text or not text.strip():
        return

    cleaned = _clean_text(text)
    if not cleaned:
        return

    sentences = _split_sentences(cleaned)
    _stop_event.clear()

    with _lock:
        for sentence in sentences:
            if _stop_event.is_set():
                break
            tmp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                    tmp_path = Path(tmp_file.name)

                _run_async(_generate_audio(sentence, tmp_path, TTS_VOICE, TTS_RATE))

                _ensure_mixer()
                pg = _pygame()
                pg.mixer.music.load(str(tmp_path))
                _play_music()
            except Exception:
                logger.exception("TTS playback failed for: %s", sentence)
                restore_other_apps()
            finally:
                if tmp_path is not None and tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        logger.warning("Could not delete temp audio: %s", tmp_path)