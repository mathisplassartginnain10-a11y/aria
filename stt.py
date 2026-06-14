import logging
import queue
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import yaml

import sounds
import ui
import app_paths

if TYPE_CHECKING:
    from faster_whisper import WhisperModel


class _LazyModule:
    """Import paresseux — évite blocage audio/Whisper au démarrage."""

    def __init__(self, import_fn):
        self._import_fn = import_fn
        self._mod = None

    def __getattr__(self, name: str):
        if self._mod is None:
            self._mod = self._import_fn()
        return getattr(self._mod, name)


def _import_sounddevice():
    import sounddevice as sd_mod

    return sd_mod


def _import_scipy_signal():
    import scipy.signal as signal_mod

    return signal_mod


sd = _LazyModule(_import_sounddevice)
scipy_signal = _LazyModule(_import_scipy_signal)

logger = logging.getLogger(__name__)

_CONFIG_PATH = app_paths.config_path()
with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

SAMPLE_RATE: int = _config.get("sample_rate", 16000)
BLOCK_SIZE: int = int(_config.get("chunk_size", 2048))
SILENCE_THRESHOLD: float = float(_config.get("silence_threshold", 500))
SILENCE_DURATION: float = float(_config.get("silence_duration", 2.0))
WHISPER_MODEL: str = _config["whisper_model"]
# beam=1 (greedy) = transcription nettement plus rapide (idéal pour parler en direct).
# Monter à 5 si tu veux un peu plus de précision au prix de la latence.
WHISPER_BEAM: int = int(_config.get("whisper_beam", 1))
ACTUAL_RATE: int = SAMPLE_RATE
ACTUAL_BLOCKSIZE: int = BLOCK_SIZE

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
# Vrai pendant qu'ARIA réfléchit/parle : on suspend la capture (anti-écho).
_responding = threading.Event()
# Mode de conversation : "auto" => ARIA répond toute seule après chaque phrase.
VOICE_AUTO_SEND: bool = str(_config.get("voice_mode", "auto")).lower() in ("auto", "conversation", "live")

_whisper_model: Any | None = None
_whisper_lock = threading.Lock()


def _load_whisper_model():
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
                from faster_whisper import WhisperModel

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


def get_audio_level() -> float:
    with _rms_lock:
        return _current_rms


def _chunk_rms(flat: np.ndarray) -> float:
    return float(np.sqrt(np.mean(flat ** 2)) * 32768)


def _hostapi_name(device_info: dict) -> str:
    try:
        return sd.query_hostapis(device_info["hostapi"])["name"].lower()
    except Exception:
        return ""


def _find_input_device() -> int | None:
    """Sélectionne un vrai micro physique (évite Voicemeeter/Steam/virtual).

    Peut être forcé via config `mic_device` (index numérique ou bout de nom)."""
    forced = _config.get("mic_device")
    if forced not in (None, "", "auto", "default"):
        try:
            devices = sd.query_devices()
            if isinstance(forced, int) or str(forced).strip().isdigit():
                idx = int(forced)
                if 0 <= idx < len(devices) and devices[idx].get("max_input_channels", 0) > 0:
                    logger.info("Micro forcé (config): [%d] %s", idx, devices[idx]["name"])
                    return idx
            else:
                needle = str(forced).lower()
                for i, device in enumerate(devices):
                    if device.get("max_input_channels", 0) > 0 and needle in device.get("name", "").lower():
                        logger.info("Micro forcé (config '%s'): [%d] %s", forced, i, device["name"])
                        return i
            logger.warning("mic_device='%s' introuvable — retour à la sélection auto", forced)
        except Exception as exc:
            logger.warning("mic_device invalide (%s) — sélection auto", exc)

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


def _get_device_native_rate(device_index: int | None) -> int:
    try:
        if device_index is not None:
            info = sd.query_devices(device_index)
        else:
            info = sd.query_devices(kind="input")
        native = int(info.get("default_samplerate", 48000))
        logger.info("Device: %s, native rate: %d Hz", info.get("name", "?"), native)
        return native
    except Exception as exc:
        logger.warning("Impossible de lire le sample rate natif: %s", exc)
        return 48000


def _open_mic_stream(
    device_index: int | None,
) -> tuple[Any, int, int]:
    """Ouvre le stream micro avec le meilleur sample rate disponible."""
    global ACTUAL_RATE, ACTUAL_BLOCKSIZE

    native_rate = _get_device_native_rate(device_index)
    rates_to_try = list(dict.fromkeys([native_rate, 48000, 44100, 16000, 22050, 8000]))
    blocksizes = list(dict.fromkeys([BLOCK_SIZE, 2048, 1024, 4096]))

    last_error: Exception | None = None
    for rate in rates_to_try:
        for blocksize in blocksizes:
            stream: Any | None = None
            try:
                stream = sd.InputStream(
                    samplerate=rate,
                    channels=1,
                    dtype="float32",
                    blocksize=blocksize,
                    device=device_index,
                    latency="high",
                )
                stream.start()
                ACTUAL_RATE = rate
                ACTUAL_BLOCKSIZE = blocksize
                logger.info("Micro ouvert: %d Hz, blocksize=%d, device=%s", rate, blocksize, device_index)
                return stream, rate, blocksize
            except Exception as exc:
                last_error = exc
                logger.debug("Rate %d blocksize %d: %s", rate, blocksize, exc)
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass

    raise RuntimeError(f"Impossible d'ouvrir le microphone avec aucun sample rate: {last_error}")


def _resample_to_16k(audio: np.ndarray, original_rate: int) -> np.ndarray:
    """Rééchantillonne l'audio à 16000 Hz pour Whisper."""
    if original_rate == 16000:
        return audio.astype(np.float32)
    target_samples = int(len(audio) * 16000 / original_rate)
    if target_samples < 1:
        return audio.astype(np.float32)
    resampled = scipy_signal.resample(audio, target_samples)
    return resampled.astype(np.float32)


def _transcribe_audio(audio_np: np.ndarray, actual_rate: int) -> str:
    global _whisper_model

    if isinstance(audio_np, list):
        audio_np = np.concatenate(audio_np, axis=0)
    audio_np = audio_np.flatten().astype(np.float32)

    peak = float(np.max(np.abs(audio_np)))
    if peak > 0:
        audio_np = audio_np / peak * 0.95

    audio_16k = _resample_to_16k(audio_np, actual_rate)
    logger.info("Transcription de %.1fs audio…", len(audio_np) / actual_rate)

    for attempt in range(2):
        try:
            model = _load_whisper_model()
            segments, info = model.transcribe(
                audio_16k,
                language="fr",
                beam_size=WHISPER_BEAM,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            text = " ".join(segment.text for segment in segments).strip()
            lang_prob = getattr(info, "language_probability", 1.0) or 1.0
            logger.info(
                "Transcription: '%s' (lang=%s, prob=%.2f)",
                text,
                getattr(info, "language", "?"),
                lang_prob,
            )

            if not text:
                return ""

            if lang_prob < 0.4:
                segments2, _ = model.transcribe(
                    audio_16k,
                    beam_size=WHISPER_BEAM,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 500},
                )
                text2 = " ".join(segment.text for segment in segments2).strip()
                if text2:
                    text = text2

            return text
        except Exception as exc:
            err = str(exc).lower()
            if attempt == 0 and ("cublas" in err or "cuda" in err or "cudnn" in err):
                logger.warning("Transcription CUDA échouée, bascule CPU: %s", exc)
                with _whisper_lock:
                    from faster_whisper import WhisperModel

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
                beam_size=WHISPER_BEAM,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            return " ".join(segment.text for segment in segments).strip()
        except Exception as exc:
            err = str(exc).lower()
            if attempt == 0 and ("cublas" in err or "cuda" in err or "cudnn" in err):
                logger.warning("Transcription fichier CUDA échouée, bascule CPU: %s", exc)
                with _whisper_lock:
                    from faster_whisper import WhisperModel

                    _whisper_model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
                continue
            logger.error("Erreur Whisper (fichier): %s", exc)
            return ""

    return ""


def _enqueue_transcript(text: str) -> None:
    _transcript_queue.put(text)
    logger.info("Transcription mise en queue: '%s'", text)


def _dispatch_to_assistant(text: str) -> None:
    """Conversation auto : ARIA répond directement à la transcription.

    La capture est suspendue (_responding) le temps de la réponse + TTS pour que
    le micro ne réentende pas la voix d'ARIA (anti-écho / anti-boucle)."""
    _responding.set()

    def _run() -> None:
        try:
            import llm
            llm.ask(text, show_user=True)
        except Exception as exc:
            logger.error("Conversation auto échouée: %s", exc)
        finally:
            time.sleep(float(_config.get("voice_resume_delay", 0.6)))
            _responding.clear()
            if not _stop_event.is_set():
                ui.set_status("listening")

    threading.Thread(target=_run, daemon=True, name="aria-respond").start()


def _record_loop() -> None:
    global _is_recording, _current_rms

    logger.info("Démarrage _record_loop")
    stream: Any | None = None
    actual_rate = ACTUAL_RATE
    blocksize = ACTUAL_BLOCKSIZE
    device_index = _find_input_device()

    time.sleep(0.5)

    for retry in range(1, 11):
        if _stop_event.is_set():
            return
        try:
            stream, actual_rate, blocksize = _open_mic_stream(device_index)
            break
        except Exception as exc:
            logger.warning("Tentative micro %d/10: %s", retry, exc)
            time.sleep(1.5)

    if stream is None or not stream.active:
        logger.error("Impossible d'ouvrir le microphone")
        ui.show_toast("Microphone indisponible", toast_type="error")
        ui.set_status("idle")
        return

    _is_recording = True
    try:
        ui.set_status("listening")
        ui.show_toast(f"Micro actif ({actual_rate}Hz)", toast_type="info")
        logger.info("Calibration bruit ambiant…")

        cal_frames = max(1, int(actual_rate / blocksize * 2))
        cal_rms: list[float] = []
        for _ in range(cal_frames):
            if _stop_event.is_set():
                return
            try:
                data, _ = stream.read(blocksize)
            except Exception as exc:
                logger.warning("Erreur lecture micro (calibration): %s", exc)
                time.sleep(0.1)
                continue
            flat = data.flatten()
            rms = _chunk_rms(flat)
            cal_rms.append(rms)
            with _rms_lock:
                _current_rms = rms
            ui.update_waveform(rms)

        # Estimation ROBUSTE du bruit de fond : 75e percentile (englobe les pics de
        # fond) plutôt que la moyenne. Sur ce micro (Intel Smart Sound) le plancher
        # de bruit est haut (~1500-2000), donc le seuil doit se poser JUSTE au-dessus.
        ambient = float(np.percentile(cal_rms, 75)) if cal_rms else 0.0
        floor = float(_config.get("silence_floor", 200))
        ceil = float(_config.get("silence_ceiling", 4000))
        margin = float(_config.get("silence_margin", 1.6))
        threshold = min(max(ambient * margin, floor), ceil)
        logger.info(
            "Seuil vocal: %.0f (bruit p75: %.0f, marge x%.2f, plancher %.0f, plafond %.0f)",
            threshold, ambient, margin, floor, ceil,
        )

        if ambient < 1.0:
            # On ne coupe PAS le micro : l'utilisateur était peut-être simplement
            # silencieux pendant la calibration. Le seuil plancher (200) suffit à
            # déclencher sur la parole réelle.
            logger.warning("Niveau ambiant très faible (%.2f) — on continue avec le seuil plancher", ambient)
            ui.show_toast("Micro faible — vérifie le volume d'entrée Windows si ARIA ne t'entend pas", toast_type="warning")

        buffer: list[np.ndarray] = []
        silence_frames = 0
        speaking = False
        frame_count = 0
        silence_limit = int(actual_rate / blocksize * SILENCE_DURATION)
        min_speech = max(1, int(actual_rate / blocksize * 0.8))

        logger.info(
            "Boucle d'enregistrement (silence_limit=%d, min_speech=%d, rate=%d, block=%d)",
            silence_limit,
            min_speech,
            actual_rate,
            blocksize,
        )

        while not _stop_event.is_set():
            try:
                data, _overflowed = stream.read(blocksize)
            except Exception as exc:
                logger.warning("Erreur lecture micro: %s", exc)
                time.sleep(0.1)
                continue

            # Anti-écho : tant qu'ARIA réfléchit/parle, on vide le flux sans l'analyser.
            if _responding.is_set():
                buffer = []
                speaking = False
                silence_frames = 0
                with _rms_lock:
                    _current_rms = 0.0
                if frame_count % 3 == 0:
                    ui.update_waveform(0.0)
                frame_count += 1
                continue

            flat = data.flatten()
            rms = _chunk_rms(flat)
            with _rms_lock:
                _current_rms = rms

            if frame_count % 3 == 0:
                ui.update_waveform(rms)
            frame_count += 1

            if rms > threshold:
                if not speaking:
                    logger.debug("Parole détectée (RMS=%.0f)", rms)
                speaking = True
                silence_frames = 0
                buffer.append(flat.copy())
            elif speaking:
                silence_frames += 1
                buffer.append(flat.copy())

                if silence_frames >= silence_limit:
                    if len(buffer) >= min_speech:
                        audio_np = np.concatenate(buffer).astype(np.float32)
                        ui.set_status("transcribing")
                        text = ""
                        try:
                            text = _transcribe_audio(audio_np, actual_rate)
                        except Exception as exc:
                            logger.error("Erreur transcription: %s", exc)
                        if text:
                            if VOICE_AUTO_SEND:
                                # Conversation auto : ARIA répond directement (gère
                                # le statut et l'anti-écho via _responding).
                                _dispatch_to_assistant(text)
                            else:
                                _enqueue_transcript(text)
                                ui.set_status("listening")
                        else:
                            ui.show_toast("Je n'ai rien entendu — réessaie", toast_type="warning")
                            ui.set_status("listening")

                    buffer = []
                    speaking = False
                    silence_frames = 0

    except Exception as exc:
        logger.error("Erreur _record_loop: %s", exc)
        ui.show_toast(f"Erreur micro: {exc}", toast_type="error")
    finally:
        _is_recording = False
        if stream is not None:
            try:
                stream.stop()
                stream.close()
                logger.info("Stream micro fermé")
            except Exception:
                pass
        try:
            sd.stop()
        except Exception:
            pass
        ui.set_status("idle")

    logger.info("Stopped listening")


def is_ready() -> bool:
    return _whisper_model is not None


def start_listening() -> None:
    _stop_event.clear()

    sounds.play("listening")
    logger.info("Listening for speech…")

    def _bootstrap() -> None:
        try:
            _load_whisper_model()
        except Exception as exc:
            logger.error("Whisper non chargé: %s", exc)

    threading.Thread(target=_bootstrap, daemon=True).start()

    record_thread = threading.Thread(target=_record_loop, daemon=True)
    record_thread.start()
    record_thread.join()


def stop_listening() -> None:
    _stop_event.set()
    try:
        sd.stop()
    except Exception:
        pass
