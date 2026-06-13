import logging
import queue
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import yaml
from faster_whisper import WhisperModel

import sounds
import ui
import app_paths

logger = logging.getLogger(__name__)

_CONFIG_PATH = app_paths.config_path()
with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

SAMPLE_RATE: int = _config.get("sample_rate", 16000)
BLOCK_SIZE: int = int(_config.get("chunk_size", 2048))
SILENCE_THRESHOLD: float = float(_config.get("silence_threshold", 500))
SILENCE_DURATION: float = float(_config.get("silence_duration", 2.0))
WHISPER_MODEL: str = _config["whisper_model"]
MIN_AUDIO_FRAMES: int = int(SAMPLE_RATE / BLOCK_SIZE * 1.0)

SKIP_DEVICE_KEYWORDS = (
    "voicemeeter",
    "vb-audio",
    "steam",
    "virtual",
    "mapper",
    "mirroring",
    "nahimic",
    "mixage",
    "stereo input",
    "point ",
    "réseau de microphones",
)
PREFER_DEVICE_KEYWORDS = (
    "microphone array",
    "realtek",
    "intel",
    "mic input",
    "microphone (",
)

_stop_event = threading.Event()
_is_recording = False
_current_rms = 0.0
_rms_lock = threading.Lock()
_transcript_queue: queue.Queue[str] = queue.Queue()

_whisper_model: WhisperModel | None = None
_whisper_lock = threading.Lock()


def _load_whisper_model() -> WhisperModel:
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is not None:
            return _whisper_model

        preferred = _config.get("whisper_device")
        attempts: list[tuple[str, str]] = []
        if preferred == "cpu":
            attempts = [("cpu", "int8")]
        elif preferred == "cuda":
            attempts = [("cuda", "float16"), ("cpu", "int8")]
        else:
            attempts = [("cuda", "float16"), ("cpu", "int8")]

        last_error: Exception | None = None
        for device, compute_type in attempts:
            try:
                logger.info("Chargement Whisper '%s' sur %s (%s)…", WHISPER_MODEL, device, compute_type)
                start = time.monotonic()
                _whisper_model = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute_type)
                logger.info("Whisper chargé sur %s en %.1fs", device, time.monotonic() - start)
                return _whisper_model
            except Exception as exc:
                last_error = exc
                logger.warning("Whisper %s/%s indisponible: %s", device, compute_type, exc)
                _whisper_model = None

        raise RuntimeError(f"Impossible de charger Whisper: {last_error}")


_load_start = time.monotonic()
try:
    _load_whisper_model()
    logger.info("Whisper prêt en %.1fs", time.monotonic() - _load_start)
except Exception as exc:
    logger.error("Whisper non chargé au démarrage: %s", exc)


def get_audio_level() -> float:
    with _rms_lock:
        return _current_rms


def _chunk_rms(audio_chunk: np.ndarray) -> float:
    return float(np.sqrt(np.mean(audio_chunk ** 2)) * 32768)


def _is_speech(audio_chunk: np.ndarray, threshold: float) -> bool:
    return _chunk_rms(audio_chunk) > threshold


def _hostapi_name(device_info: dict) -> str:
    try:
        return sd.query_hostapis(device_info["hostapi"])["name"].lower()
    except Exception:
        return ""


def _find_input_device() -> int | None:
    """Sélectionne un vrai micro physique (évite Voicemeeter/Steam/virtual)."""
    candidates: list[tuple[int, int, str]] = []

    for i, device in enumerate(sd.query_devices()):
        if device.get("max_input_channels", 0) <= 0:
            continue

        name = device.get("name", "")
        name_lower = name.lower()
        if any(keyword in name_lower for keyword in SKIP_DEVICE_KEYWORDS):
            continue

        priority = 10
        hostapi = _hostapi_name(device)
        if "wasapi" in hostapi:
            priority = 0
        elif "wdm" in hostapi:
            priority = 2
        else:
            priority = 5

        if any(keyword in name_lower for keyword in PREFER_DEVICE_KEYWORDS):
            priority -= 20

        candidates.append((priority, i, name))

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]))
        chosen = candidates[0]
        logger.info("Micro sélectionné: [%d] %s", chosen[1], chosen[2])
        return chosen[1]

    default_in = sd.default.device[0]
    if isinstance(default_in, int) and default_in >= 0:
        logger.info("Micro par défaut: [%d] %s", default_in, sd.query_devices(default_in)["name"])
        return default_in

    return None


def _open_input_stream(device_index: int | None) -> sd.InputStream:
    return sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=BLOCK_SIZE,
        device=device_index,
        latency="high",
    )


def _transcribe_audio(audio_np: np.ndarray) -> str:
    global _whisper_model

    audio_np = np.concatenate(audio_np, axis=0).flatten().astype(np.float32) if isinstance(audio_np, list) else audio_np.flatten().astype(np.float32)
    peak = float(np.max(np.abs(audio_np)))
    if peak > 0:
        audio_np = audio_np / peak * 0.95

    for attempt in range(2):
        try:
            model = _load_whisper_model()
            segments, _ = model.transcribe(
                audio_np,
                language="fr",
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            return " ".join(segment.text for segment in segments).strip()
        except Exception as exc:
            err = str(exc).lower()
            if attempt == 0 and ("cublas" in err or "cuda" in err or "cudnn" in err):
                logger.warning("Transcription CUDA échouée, bascule CPU: %s", exc)
                with _whisper_lock:
                    _whisper_model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
                continue
            logger.error("Erreur Whisper: %s", exc)
            ui.show_toast("Erreur transcription Whisper", toast_type="error")
            return ""

    return ""


def transcribe_file(path: str | Path, language: str = "fr") -> str:
    """Transcrit un fichier audio (wav, m4a, mp3…) — utilisé par le serveur mobile."""
    global _whisper_model

    file_path = str(path)
    for attempt in range(2):
        try:
            model = _load_whisper_model()
            segments, _ = model.transcribe(
                file_path,
                language=language,
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            return " ".join(segment.text for segment in segments).strip()
        except Exception as exc:
            err = str(exc).lower()
            if attempt == 0 and ("cublas" in err or "cuda" in err or "cudnn" in err):
                logger.warning("Transcription fichier CUDA échouée, bascule CPU: %s", exc)
                with _whisper_lock:
                    _whisper_model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
                continue
            logger.error("Erreur Whisper (fichier): %s", exc)
            return ""

    return ""


def _enqueue_transcript(text: str) -> None:
    _transcript_queue.put(text)
    logger.info("Transcription mise en queue: '%s'", text)


def _record_loop() -> None:
    global _is_recording, _current_rms

    logger.info("Démarrage _record_loop")
    stream: sd.InputStream | None = None
    device_index = _find_input_device()

    time.sleep(0.5)

    for retry in range(1, 11):
        if _stop_event.is_set():
            return
        try:
            stream = _open_input_stream(device_index)
            stream.start()
            logger.info("Microphone ouvert (device=%s, block=%d)", device_index, BLOCK_SIZE)
            break
        except Exception as exc:
            logger.warning("Tentative micro %d/10: %s", retry, exc)
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
                stream = None
            time.sleep(1.5)

    if stream is None or not stream.active:
        logger.error("Impossible d'ouvrir le microphone")
        ui.show_toast("Microphone indisponible", toast_type="error")
        return

    _is_recording = True
    try:
        calibration_samples: list[float] = []
        ui.set_status("listening")
        logger.info("Calibration bruit ambiant (50 chunks)…")

        for _ in range(50):
            if _stop_event.is_set():
                logger.info("Stop demandé pendant calibration")
                return
            try:
                data, _ = stream.read(BLOCK_SIZE)
            except Exception as exc:
                logger.warning("Erreur lecture micro (calibration): %s", exc)
                time.sleep(0.1)
                continue
            rms = _chunk_rms(data)
            calibration_samples.append(rms)
            with _rms_lock:
                _current_rms = rms
            ui.update_waveform(rms)

        max_rms = max(calibration_samples) if calibration_samples else 0.0
        avg_rms = sum(calibration_samples) / len(calibration_samples) if calibration_samples else 0.0
        logger.info("Calibration: max=%.0f avg=%.0f", max_rms, avg_rms)

        if max_rms < 5:
            logger.error("MICRO SILENCIEUX — vérifie les paramètres Windows")
            ui.show_toast("Micro silencieux — vérifie Windows", toast_type="error")
            ui.show_toast("Paramètres → Système → Son → Micro → Volume", toast_type="warning")
            return

        threshold = max(float(SILENCE_THRESHOLD), avg_rms * 4, 200.0)
        logger.info("Seuil adaptatif: %.0f (ambiant: %.0f)", threshold, avg_rms)
        ui.show_toast(f"Micro actif — seuil {threshold:.0f}", toast_type="info")

        buffer: list[np.ndarray] = []
        silence_frames = 0
        speaking = False
        frame_count = 0
        silence_limit = int(SAMPLE_RATE / BLOCK_SIZE * SILENCE_DURATION)

        logger.info(
            "Boucle d'enregistrement (silence_limit=%d, min_frames=%d)",
            silence_limit,
            MIN_AUDIO_FRAMES,
        )

        while not _stop_event.is_set():
            try:
                data, _overflowed = stream.read(BLOCK_SIZE)
            except Exception as exc:
                logger.warning("Erreur lecture micro: %s", exc)
                time.sleep(0.1)
                continue

            rms = _chunk_rms(data)
            with _rms_lock:
                _current_rms = rms
            ui.update_waveform(rms)

            frame_count += 1
            if frame_count % 50 == 0:
                logger.info(
                    "Chunk RMS=%.0f threshold=%.0f speaking=%s buffer=%d",
                    rms,
                    threshold,
                    speaking,
                    len(buffer),
                )

            if _is_speech(data, threshold):
                if not speaking:
                    logger.info("Parole détectée (RMS=%.0f)", rms)
                speaking = True
                silence_frames = 0
                buffer.append(data.copy())
            elif speaking:
                silence_frames += 1
                buffer.append(data.copy())
                if silence_frames >= silence_limit:
                    if len(buffer) < MIN_AUDIO_FRAMES:
                        logger.debug("Buffer trop court (%d frames), ignoré", len(buffer))
                        buffer = []
                        speaking = False
                        silence_frames = 0
                        continue

                    logger.info("Fin de segment (%d frames), transcription…", len(buffer))
                    audio_chunks = buffer
                    buffer = []
                    speaking = False
                    silence_frames = 0

                    ui.set_status("transcribing")
                    try:
                        text = _transcribe_audio(np.concatenate(audio_chunks, axis=0))
                        if text:
                            logger.info("Transcription OK: '%s'", text)
                            _enqueue_transcript(text)
                        else:
                            logger.info("Transcription vide")
                            ui.show_toast("Je n'ai rien entendu — réessaie", toast_type="warning")
                    except Exception as exc:
                        logger.error("Erreur transcription: %s", exc)
                    finally:
                        ui.set_status("listening")
    finally:
        _is_recording = False
        try:
            if stream is not None:
                stream.stop()
                stream.close()
        except Exception:
            pass
        try:
            sd.stop()
        except Exception:
            pass

    logger.info("Stopped listening")


def is_ready() -> bool:
    return _whisper_model is not None


def start_listening() -> None:
    _stop_event.clear()

    sounds.play("listening")
    logger.info("Listening for speech…")

    record_thread = threading.Thread(target=_record_loop, daemon=True)
    record_thread.start()
    record_thread.join()


def stop_listening() -> None:
    _stop_event.set()
    try:
        sd.stop()
    except Exception:
        pass
