"""Pipeline STT ARIA — faster-whisper (spec v17)."""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from math import gcd
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import yaml

import app_paths
import sounds
import ui

if TYPE_CHECKING:
    from faster_whisper import WhisperModel


class _LazyModule:
    def __init__(self, import_fn):
        self._import_fn = import_fn
        self._mod = None

    def __getattr__(self, name: str):
        if self._mod is None:
            self._mod = self._import_fn()
        return getattr(self._mod, name)


def _import_scipy_signal():
    import scipy.signal as signal_mod
    return signal_mod


scipy_signal = _LazyModule(_import_scipy_signal)

_pa_instance: Any | None = None
_active_device_index: int | None = None


def _get_pa() -> Any:
    global _pa_instance
    if _pa_instance is None:
        import pyaudio
        _pa_instance = pyaudio.PyAudio()
    return _pa_instance


def _cleanup_pyaudio() -> None:
    """Appelé uniquement à la fermeture complète d'ARIA — pas au stop du micro."""
    global _pa_instance
    if _pa_instance is not None:
        try:
            _pa_instance.terminate()
        except Exception:
            pass
        _pa_instance = None


def _read_pa_stream(stream: Any, blocksize: int) -> np.ndarray:
    raw = stream.read(blocksize, exception_on_overflow=False)
    return np.frombuffer(raw, dtype=np.float32).copy()


def _close_pa_stream(stream: Any | None) -> None:
    if stream is None:
        return
    try:
        stream.stop_stream()
        stream.close()
    except Exception:
        pass

logger = logging.getLogger(__name__)

_CONFIG_PATH = app_paths.config_path()
with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f) or {}

_STT_CFG = _config.get("stt") or {}
STT_DEBUG: bool = bool(_config.get("stt_debug", False))
WHISPER_MODEL: str = str(_STT_CFG.get("model") or _config.get("whisper_model", "small"))
STT_LANGUAGE: str = str(_STT_CFG.get("language") or _config.get("language", "fr"))
STT_BACKEND: str = str(_STT_CFG.get("backend", "faster_whisper"))
_stt_device_raw = _STT_CFG.get("device_index")
STT_DEVICE_INDEX: int | None = (
    int(_stt_device_raw) if _stt_device_raw is not None else None
)
WHISPER_MODEL_DIR = _config.get("whisper_model_dir")
BLOCK_SIZE: int = int(_config.get("chunk_size", 2048))
SILENCE_DURATION: float = float(_config.get("silence_duration", 2.0))

MIN_SPEECH_SEC = 0.4
SILENCE_LIMIT_SEC = 1.5
MAX_BUFFER_SEC = 30.0
MIN_ABSOLUTE_THRESHOLD = 0.02
SPEECH_CONFIRM_FRAMES = 3
MIN_BUFFER_DURATION_SEC = 0.6
MIN_BUFFER_RMS = 0.01

ACTUAL_RATE: int = int(_config.get("sample_rate", 16000))
ACTUAL_BLOCKSIZE: int = BLOCK_SIZE

PREFERRED_DEVICE_KEYWORDS = (
    "intel® smart sound",
    "microphone array",
    "realtek hd audio mic",
    "bt le microphone",
    "realtek",
)
EXCLUDED_KEYWORDS = (
    "voicemeeter",
    "vb-audio",
    "steam streaming",
    "mappeur",
    "pilote de capture",
    "mixage stéréo",
    "réseau de microphones",
    "point",
    "haut-parleur",
    "output",
    "sortie",
)

HALLUCINATIONS = (
    "merci d'avoir regardé",
    "merci de votre attention",
    "sous-titres",
    "abonnez-vous",
    "♪",
    "[musique]",
    "(musique)",
    "transcrit par",
    "sous-titrage",
    "au revoir",
    "bonne journée",
    "à bientôt",
)

_stop_event = threading.Event()
_is_recording = False
_current_rms = 0.0
_rms_lock = threading.Lock()
_record_thread: threading.Thread | None = None
_record_lock = threading.Lock()
_transcript_queue: queue.Queue[str] = queue.Queue()
_responding = threading.Event()
VOICE_AUTO_SEND: bool = str(_config.get("voice_mode", "auto")).lower() in (
    "auto", "conversation", "live",
)

_whisper_model: Any | None = None
_whisper_lock = threading.Lock()
_realtime_model: Any | None = None


def _config_threshold_float() -> float:
    raw = _STT_CFG.get("silence_threshold", _config.get("silence_threshold", 0.02))
    val = float(raw)
    if val > 1.0:
        return val / 32768.0
    return val


def get_audio_level() -> float:
    with _rms_lock:
        return _current_rms


def _safe_js(script: str) -> None:
    """Appelle du JS côté UI uniquement si la fenêtre est encore vivante."""
    try:
        import ui as _ui

        if _ui._instance is None:
            return
        window = getattr(_ui, "_window", None)
        if window is None:
            window = getattr(_ui._instance, "_window", None)
        if window is None:
            return
        _ui._instance._js(script)
    except Exception as exc:
        logger.debug("JS call ignoré (fenêtre fermée ou thread mort): %s", exc)


def _present_transcription(text: str) -> None:
    """Affiche la transcription dans l'input — countdown vocal géré par aria.onSTTResult()."""
    _safe_js(f"if(window.aria) aria.onSTTResult({json.dumps(text)});")


def _show_partial_transcription(text: str) -> None:
    _safe_js(f"if(window.aria) aria.showPartialTranscription({json.dumps(text)})")


def _show_final_transcription(text: str) -> None:
    _present_transcription(text)


def _float_rms(flat: np.ndarray) -> float:
    return float(np.sqrt(np.mean(flat.astype(np.float64) ** 2)))


def _chunk_rms(flat: np.ndarray) -> float:
    return _float_rms(flat) * 32768.0


def _pick_best_device_pa() -> int | None:
    """Choisit le meilleur device micro physique via PyAudio."""
    pa = _get_pa()
    candidates: list[tuple[int, int, str]] = []
    for i in range(pa.get_device_count()):
        try:
            info = pa.get_device_info_by_index(i)
        except Exception:
            continue
        if info.get("maxInputChannels", 0) < 1:
            continue
        name = str(info.get("name", "")).lower()
        if any(excl in name for excl in EXCLUDED_KEYWORDS):
            continue
        priority = 99
        for j, kw in enumerate(PREFERRED_DEVICE_KEYWORDS):
            if kw in name:
                priority = j
                break
        candidates.append((priority, i, str(info.get("name", ""))))
        logger.debug("Device PA [%d] %s (priority=%d)", i, info["name"], priority)

    if not candidates:
        return None

    candidates.sort()
    best = candidates[0]
    logger.info("Device PyAudio sélectionné: [%d] %s", best[1], best[2])
    return best[1]


def _list_input_devices() -> None:
    logger.info("Devices audio disponibles:")
    try:
        pa = _get_pa()
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                logger.info(
                    "  [%d] %s (native: %.0fHz, ch: %d)",
                    i,
                    info["name"],
                    info.get("defaultSampleRate", 0),
                    info["maxInputChannels"],
                )
    except Exception as exc:
        logger.warning("Impossible de lister les devices: %s", exc)


def _find_input_device() -> int | None:
    """Retourne un index forcé par config, ou None pour auto-sélection dans _open_mic_stream."""
    pa = _get_pa()

    if STT_DEVICE_INDEX is not None:
        try:
            info = pa.get_device_info_by_index(STT_DEVICE_INDEX)
            if info.get("maxInputChannels", 0) > 0:
                logger.info(
                    "Micro forcé (stt.device_index): [%d] %s",
                    STT_DEVICE_INDEX,
                    info["name"],
                )
                return STT_DEVICE_INDEX
            logger.warning("stt.device_index=%s invalide — auto-sélection", STT_DEVICE_INDEX)
        except Exception as exc:
            logger.warning("stt.device_index illisible (%s) — auto-sélection", exc)

    forced = _config.get("mic_device")
    if forced not in (None, "", "auto", "default"):
        try:
            if isinstance(forced, int) or str(forced).strip().isdigit():
                idx = int(forced)
                info = pa.get_device_info_by_index(idx)
                if info.get("maxInputChannels", 0) > 0:
                    logger.info("Micro forcé (mic_device): [%d] %s", idx, info["name"])
                    return idx
            else:
                needle = str(forced).lower()
                for i in range(pa.get_device_count()):
                    info = pa.get_device_info_by_index(i)
                    if info.get("maxInputChannels", 0) > 0 and needle in str(info.get("name", "")).lower():
                        logger.info("Micro forcé (mic_device '%s'): [%d] %s", forced, i, info["name"])
                        return i
            logger.warning("mic_device='%s' introuvable — auto-sélection", forced)
        except Exception as exc:
            logger.warning("mic_device invalide (%s) — auto-sélection", exc)

    return None


def _open_mic_stream(device_index: int | None) -> tuple[Any, int, int, str]:
    """Ouvre un stream PyAudio avec le meilleur device disponible."""
    global ACTUAL_RATE, ACTUAL_BLOCKSIZE, _active_device_index

    import pyaudio

    _list_input_devices()
    pa = _get_pa()

    forced = device_index
    if forced is None:
        forced = _config.get("stt", {}).get("device_index")
        if forced is not None:
            forced = int(forced)

    if forced is not None:
        device_candidates: list[int | None] = [int(forced)]
    else:
        best = _pick_best_device_pa()
        all_inputs = [
            i
            for i in range(pa.get_device_count())
            if pa.get_device_info_by_index(i).get("maxInputChannels", 0) > 0
            and not any(
                excl in pa.get_device_info_by_index(i).get("name", "").lower()
                for excl in EXCLUDED_KEYWORDS
            )
        ]
        device_candidates = ([best] if best is not None else []) + [
            i for i in all_inputs if i != best
        ] + [None]

    rates = [44100, 48000, 16000, 22050]
    blocksize = 2048
    last_error: Exception | None = None

    for dev_idx in device_candidates:
        device_name = "défaut"
        try:
            if dev_idx is not None:
                device_name = str(pa.get_device_info_by_index(dev_idx).get("name", "défaut"))
        except Exception:
            pass

        for rate in rates:
            stream: Any | None = None
            try:
                stream = pa.open(
                    format=pyaudio.paFloat32,
                    channels=1,
                    rate=rate,
                    input=True,
                    frames_per_buffer=blocksize,
                    input_device_index=dev_idx,
                )
                audio = _read_pa_stream(stream, blocksize)
                rms = _float_rms(audio)

                if rms < 0.00001:
                    logger.warning(
                        "Device PA [%s] '%s' silencieux (RMS=%.6f) — essai suivant",
                        dev_idx,
                        device_name,
                        rms,
                    )
                    _close_pa_stream(stream)
                    continue

                ACTUAL_RATE = rate
                ACTUAL_BLOCKSIZE = blocksize
                _active_device_index = dev_idx
                logger.info(
                    "✅ PyAudio ouvert: device=[%s] '%s', rate=%dHz, RMS=%.4f",
                    dev_idx,
                    device_name,
                    rate,
                    rms,
                )
                return stream, rate, blocksize, device_name
            except Exception as exc:
                last_error = exc
                logger.debug("PA device=%s rate=%d: %s", dev_idx, rate, exc)
                _close_pa_stream(stream)

    raise RuntimeError(
        f"PyAudio: impossible d'ouvrir un device micro avec signal valide: {last_error}"
    )


def _calibrate_threshold(stream: Any, blocksize: int, actual_rate: int) -> float:
    """Calibration adaptative 2s — seuil float normalisé."""
    logger.info("Calibration bruit ambiant (2s)...")
    cal_frames = max(1, int(actual_rate / blocksize * 2))
    cal_rms: list[float] = []

    for _ in range(cal_frames):
        if _stop_event.is_set():
            break
        try:
            flat = _read_pa_stream(stream, blocksize)
            cal_rms.append(_float_rms(flat))
        except Exception:
            pass

    if not cal_rms:
        logger.warning("Calibration échouée — seuil par défaut 0.015")
        return 0.015

    ambient = float(np.mean(cal_rms))
    stt_cfg = _config.get("stt") or {}
    raw_threshold = stt_cfg.get("silence_threshold", _config.get("silence_threshold", 0.015))
    config_threshold = float(raw_threshold)
    if config_threshold > 1.0:
        config_threshold = config_threshold / 32768.0
    threshold = max(config_threshold, ambient * 2.5, 0.01)

    logger.info("Seuil calibré: %.4f (ambiant=%.4f × 2.5)", threshold, ambient)

    if ambient < 0.0001:
        logger.warning("⚠️ Micro silencieux — vérifier Windows > Son > Micro")
        ui.show_toast("Micro silencieux — vérifie le volume d'entrée Windows", toast_type="warning")

    if ambient > 0.1:
        logger.warning("⚠️ Bruit ambiant très élevé (%.4f) — risque de fausses détections", ambient)

    return threshold


def _resample_to_16k(audio: np.ndarray, original_rate: int) -> np.ndarray:
    if original_rate == 16000:
        return audio.astype(np.float32)

    audio = audio.astype(np.float32).flatten()
    try:
        signal = scipy_signal
        g = gcd(16000, original_rate)
        up = 16000 // g
        down = original_rate // g
        resampled = signal.resample_poly(audio, up, down)
        logger.debug(
            "Resample polyphase %dHz → 16kHz: %d → %d samples",
            original_rate, len(audio), len(resampled),
        )
        return resampled.astype(np.float32)
    except Exception as exc:
        logger.warning("resample_poly échoué (%s), fallback resample FFT", exc)
        try:
            signal = scipy_signal
            target_samples = int(len(audio) * 16000 / original_rate)
            if target_samples < 1:
                return audio
            resampled = signal.resample(audio, target_samples)
            logger.debug("Resample FFT %d → %d samples", len(audio), len(resampled))
            return resampled.astype(np.float32)
        except Exception as exc2:
            logger.warning("resample FFT échoué (%s), fallback numpy", exc2)
            indices = np.round(np.arange(0, len(audio), original_rate / 16000)).astype(int)
            indices = indices[indices < len(audio)]
            return audio[indices].astype(np.float32)


def _normalize_audio(audio: np.ndarray) -> np.ndarray:
    audio = audio.astype(np.float32)
    max_val = float(np.max(np.abs(audio)))
    if max_val > 1e-8:
        audio = audio / max_val * 0.95
    return audio


def _prepare_whisper_input(audio_np: np.ndarray, actual_rate: int) -> np.ndarray:
    """Resample à 16 kHz puis normalisation légère uniquement si nécessaire."""
    audio_16k = _resample_to_16k(audio_np.astype(np.float32).flatten(), actual_rate)
    max_val = float(np.max(np.abs(audio_16k)))
    if max_val > 0 and max_val < 0.1:
        audio_16k = audio_16k / max_val * 0.5
        logger.debug("Signal amplifié (max_val=%.4f était trop faible)", max_val)
    elif max_val > 1.0:
        audio_16k = audio_16k / max_val * 0.95
    return audio_16k


def _check_audio_quality(audio: np.ndarray, rate: int = 16000) -> tuple[bool, str]:
    duration = len(audio) / rate
    rms = _float_rms(audio)
    max_amp = float(np.max(np.abs(audio)))

    if duration < 0.3:
        return False, f"Trop court ({duration:.2f}s < 0.3s)"
    if rms < 0.0005:
        return False, f"Trop silencieux (RMS={rms:.5f})"
    if max_amp > 0.999:
        return False, f"Signal saturé (max={max_amp:.3f}) — micro trop fort"
    return True, f"OK (durée={duration:.2f}s, RMS={rms:.4f})"


def _validate_speech_buffer(audio_np: np.ndarray, actual_rate: int) -> bool:
    """Rejette les buffers trop courts ou trop silencieux avant transcription."""
    duration = len(audio_np) / actual_rate
    if duration < MIN_BUFFER_DURATION_SEC:
        logger.debug("Buffer trop court (%.2fs) — ignoré", duration)
        return False
    buffer_rms = _float_rms(audio_np)
    if buffer_rms < MIN_BUFFER_RMS:
        logger.debug("Buffer trop silencieux (RMS=%.4f) — ignoré", buffer_rms)
        return False
    return True


def _finalize_transcription(text: str) -> str:
    """Logue la transcription Whisper validée avant envoi au LLM."""
    logger.info("═══ WHISPER TRANSCRIPTION ═══")
    logger.info("WHISPER: '%s'", text)
    logger.info("═════════════════════════════")
    return text


def _clean_transcription(text: str) -> str:
    text_lower = text.lower().strip()

    for h in HALLUCINATIONS:
        if text_lower == h:
            logger.debug("Hallucination exacte filtrée: '%s'", text)
            return ""

    if len(text.strip()) <= 1:
        logger.debug("Texte trop court (1 char) filtré: '%s'", text)
        return ""

    if not re.search(r"[a-zéèêëàâîïôùûüç]", text_lower):
        logger.debug("Texte sans lettres filtré: '%s'", text)
        return ""

    words = text.split()
    if len(words) >= 6:
        half = len(words) // 2
        if words[:half] == words[half : half * 2]:
            logger.debug("Répétition filtrée: '%s'", text)
            return ""

    return text.strip()


def _load_whisper_model():
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is not None:
            return _whisper_model

        from faster_whisper import WhisperModel

        cuda_ok = False
        try:
            import torch
            cuda_ok = bool(torch.cuda.is_available())
        except Exception:
            pass

        configs = [
            ("cuda", "float16"),
            ("cuda", "int8_float16"),
            ("cuda", "int8"),
            ("cpu", "int8"),
        ]
        last_error: Exception | None = None

        for device, compute_type in configs:
            if device == "cuda" and not cuda_ok:
                continue
            try:
                kwargs: dict = {
                    "device": device,
                    "compute_type": compute_type,
                    "num_workers": 1,
                }
                if WHISPER_MODEL_DIR:
                    kwargs["download_root"] = WHISPER_MODEL_DIR
                logger.info("Chargement Whisper '%s' sur %s (%s)…", WHISPER_MODEL, device, compute_type)
                model = WhisperModel(WHISPER_MODEL, **kwargs)
                test_audio = np.zeros(16000, dtype=np.float32)
                list(model.transcribe(test_audio, language=STT_LANGUAGE)[0])
                _whisper_model = model
                logger.info(
                    "✅ Whisper chargé: modèle=%s, device=%s, compute=%s, backend=%s",
                    WHISPER_MODEL, device, compute_type, STT_BACKEND,
                )
                return _whisper_model
            except Exception as exc:
                last_error = exc
                logger.warning("Config Whisper %s/%s échouée: %s", device, compute_type, exc)

        raise RuntimeError(f"Impossible de charger Whisper: {last_error}")


def _transcribe(audio_16k: np.ndarray) -> str:
    """Transcription Whisper — 3 tentatives (T1 VAD, T2 sans VAD, T3 température)."""
    global _whisper_model

    ok, reason = _check_audio_quality(audio_16k)
    if not ok:
        logger.warning("Audio rejeté: %s", reason)
        return ""

    _load_whisper_model()

    # T1
    try:
        segments, info = _whisper_model.transcribe(
            audio_16k,
            language="fr",
            beam_size=5,
            temperature=0.0,
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 200,
                "threshold": 0.45,
                "min_speech_duration_ms": 400,
            },
            condition_on_previous_text=False,
            no_speech_threshold=0.4,
        )
        raw_text = " ".join(s.text for s in segments).strip()

        print(f"[T1] AVANT CLEAN: {repr(raw_text)}")
        cleaned = _clean_transcription(raw_text)
        print(f"[T1] APRÈS CLEAN: {repr(cleaned)}")
        logger.warning(
            "WHISPER T1: brut='%s' clean='%s' lang=%s(%.2f)",
            raw_text,
            cleaned,
            getattr(info, "language", "?"),
            float(getattr(info, "language_probability", 0.0) or 0.0),
        )

        if cleaned:
            return cleaned
    except Exception as e:
        logger.error("T1 erreur: %s", e)

    # T2 — sans VAD
    logger.warning("T1 vide — retry T2 sans VAD")
    try:
        segments, info = _whisper_model.transcribe(
            audio_16k,
            language="fr",
            beam_size=5,
            temperature=0.0,
            vad_filter=False,
            condition_on_previous_text=False,
            no_speech_threshold=0.8,
        )
        raw_text = " ".join(s.text for s in segments).strip()

        print(f"[T2] AVANT CLEAN: {repr(raw_text)}")
        cleaned = _clean_transcription(raw_text)
        print(f"[T2] APRÈS CLEAN: {repr(cleaned)}")
        logger.warning("WHISPER T2: brut='%s' clean='%s'", raw_text, cleaned)

        if cleaned:
            return cleaned
    except Exception as e:
        logger.error("T2 erreur: %s", e)

    # T3 — température 0.2
    logger.warning("T2 vide — retry T3 temp=0.2")
    try:
        segments, info = _whisper_model.transcribe(
            audio_16k,
            language="fr",
            beam_size=3,
            temperature=0.2,
            vad_filter=False,
            condition_on_previous_text=False,
            no_speech_threshold=0.9,
        )
        raw_text = " ".join(s.text for s in segments).strip()

        print(f"[T3] AVANT CLEAN: {repr(raw_text)}")
        cleaned = _clean_transcription(raw_text)
        print(f"[T3] APRÈS CLEAN: {repr(cleaned)}")
        logger.warning("WHISPER T3: brut='%s' clean='%s'", raw_text, cleaned)

        return cleaned
    except Exception as e:
        logger.error("T3 erreur: %s", e)

    return ""


def _transcribe_audio(audio_np: np.ndarray, actual_rate: int) -> str:
    if isinstance(audio_np, list):
        audio_np = np.concatenate(audio_np, axis=0)
    audio_np = audio_np.flatten().astype(np.float32)

    if STT_DEBUG:
        logger.info(
            "=== STT DIAGNOSTIC ===\nFrames audio brut: durée=%.2fs min=%.4f max=%.4f rms=%.4f",
            len(audio_np) / actual_rate,
            float(np.min(audio_np)), float(np.max(audio_np)), _float_rms(audio_np),
        )

    audio_16k = _prepare_whisper_input(audio_np, actual_rate)
    logger.info(
        "Pipeline STT: %.1fs @ %dHz → %.1fs @ 16kHz",
        len(audio_np) / actual_rate, actual_rate, len(audio_16k) / 16000,
    )
    return _transcribe(audio_16k)


def transcribe_file(path: str | Path, language: str | None = None) -> str:
    """Transcrit un fichier audio — serveur mobile."""
    lang = language or STT_LANGUAGE
    for attempt in range(2):
        try:
            model = _load_whisper_model()
            segments, info = model.transcribe(
                str(path),
                language=lang,
                beam_size=5,
                temperature=0.0,
                vad_filter=True,
                vad_parameters={
                    "min_silence_duration_ms": 300,
                    "speech_pad_ms": 400,
                    "threshold": 0.25,
                    "min_speech_duration_ms": 200,
                },
                no_speech_threshold=0.6,
            )
            text = _clean_transcription(" ".join(s.text for s in segments).strip())
            if not text:
                segments2, _ = model.transcribe(str(path), language=lang, vad_filter=False, temperature=0.0)
                text = _clean_transcription(" ".join(s.text for s in segments2).strip())
            logger.info("Whisper fichier: lang=%s, texte='%s'", getattr(info, "language", "?"), text)
            return text
        except Exception as exc:
            err = str(exc).lower()
            if attempt == 0 and ("cublas" in err or "cuda" in err or "cudnn" in err):
                logger.warning("Transcription fichier CUDA échouée, bascule CPU")
                with _whisper_lock:
                    from faster_whisper import WhisperModel
                    global _whisper_model
                    _whisper_model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
                continue
            logger.error("Erreur Whisper (fichier): %s", exc)
            return ""
    return ""


def _enqueue_transcript(text: str) -> None:
    _present_transcription(text)
    _transcript_queue.put(text)
    logger.info("Transcription affichée: '%s'", text)


def _dispatch_to_assistant(text: str) -> None:
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


def _handle_transcription_result(text: str) -> None:
    if text:
        logger.info("✅ Transcription: '%s'", text)
        _present_transcription(text)
        ui.set_status("listening")
    else:
        logger.warning("❌ Transcription vide après 3 tentatives")
        ui.show_toast("Parole non comprise — réessaie", toast_type="info")
        ui.set_status("listening")


def _get_realtime_model():
    global _realtime_model
    if _realtime_model is None:
        from faster_whisper import WhisperModel
        try:
            _realtime_model = WhisperModel("tiny", device="cuda", compute_type="int8")
        except Exception:
            _realtime_model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _realtime_model


def _record_loop_realtime() -> None:
    global _is_recording, _current_rms

    logger.info("Démarrage _record_loop_realtime")
    stream = None
    device_index = _find_input_device()
    try:
        stream, actual_rate, blocksize, _ = _open_mic_stream(device_index)
    except Exception as exc:
        logger.error("Micro indisponible (realtime): %s", exc)
        ui.show_toast("Microphone indisponible", toast_type="error")
        return

    threshold = _calibrate_threshold(stream, blocksize, actual_rate)
    _is_recording = True
    ui.set_status("listening")

    window_size = int(actual_rate * 1.5)
    slide_size = int(actual_rate * 0.5)
    rolling = np.zeros(0, dtype=np.float32)
    full_buffer: list[np.ndarray] = []
    speaking = False
    silence_frames = 0
    consecutive_above = 0
    silence_limit = int(actual_rate / blocksize * 1.5)
    min_speech = max(1, int(actual_rate / blocksize * 0.4))
    max_buffer = int(actual_rate / blocksize * 30)

    try:
        rt_model = _get_realtime_model()
    except Exception as exc:
        logger.warning("Modèle realtime indisponible: %s", exc)
        ui.show_toast("Transcription temps réel indisponible", toast_type="warning")
        return

    frame_count = 0
    try:
        while not _stop_event.is_set():
            if _responding.is_set():
                continue
            try:
                flat = _read_pa_stream(stream, blocksize)
            except Exception as exc:
                logger.warning("Erreur lecture stream realtime: %s — pause 1s", exc)
                time.sleep(1)
                continue

            rms = _float_rms(flat)
            with _rms_lock:
                _current_rms = _chunk_rms(flat)
            if frame_count % 4 == 0:
                ui.update_waveform(_chunk_rms(flat))
            frame_count += 1

            if rms > threshold:
                consecutive_above += 1
                if consecutive_above >= SPEECH_CONFIRM_FRAMES:
                    if not speaking:
                        logger.debug(
                            "🎤 Parole confirmée après %d frames (RMS=%.4f > seuil=%.4f)",
                            consecutive_above, rms, threshold,
                        )
                    speaking = True
                    silence_frames = 0
                    full_buffer.append(flat.copy())
                    rolling = np.concatenate([rolling, flat])
                    if len(rolling) >= window_size:
                        audio_16k = _normalize_audio(_resample_to_16k(rolling[-window_size:], actual_rate))
                        segments, _ = rt_model.transcribe(
                            audio_16k, language=STT_LANGUAGE, beam_size=1,
                            temperature=0.0, vad_filter=False, condition_on_previous_text=False,
                        )
                        partial = _clean_transcription(" ".join(s.text for s in segments).strip())
                        if partial:
                            _show_partial_transcription(partial)
                        rolling = rolling[-slide_size:]
                    if len(full_buffer) > max_buffer:
                        silence_frames = silence_limit
            else:
                consecutive_above = 0
                if speaking:
                    silence_frames += 1
                    full_buffer.append(flat.copy())
                    if silence_frames >= silence_limit:
                        logger.debug(
                            "🔇 Fin parole (%.1fs silence)",
                            silence_frames * blocksize / actual_rate,
                        )
                        if len(full_buffer) >= min_speech:
                            try:
                                audio_np = np.concatenate(full_buffer).astype(np.float32)
                                if not _validate_speech_buffer(audio_np, actual_rate):
                                    full_buffer = []
                                    rolling = np.zeros(0, dtype=np.float32)
                                    speaking = False
                                    silence_frames = 0
                                    continue
                                ui.set_status("transcribing")
                                text = _transcribe_audio(audio_np, actual_rate)
                                _handle_transcription_result(text)
                            except Exception as exc:
                                logger.error("Erreur pipeline realtime: %s", exc)
                                ui.show_toast("Parole non comprise — réessaie", toast_type="info")
                        full_buffer = []
                        rolling = np.zeros(0, dtype=np.float32)
                        speaking = False
                        silence_frames = 0
    finally:
        _is_recording = False
        _close_pa_stream(stream)


def _record_loop() -> None:
    global _is_recording, _current_rms

    if _stop_event.is_set():
        logger.warning("_stop_event était set au démarrage — reset")
        _stop_event.clear()

    if _config.get("realtime_transcription", False):
        _record_loop_realtime()
        return

    logger.info("Démarrage _record_loop (spec v17)")
    stream: Any | None = None
    actual_rate = ACTUAL_RATE
    blocksize = ACTUAL_BLOCKSIZE
    device_index = _find_input_device()

    time.sleep(0.5)
    for retry in range(1, 11):
        if _stop_event.is_set():
            return
        try:
            stream, actual_rate, blocksize, device_name = _open_mic_stream(device_index)
            logger.info("Stream prêt sur %s", device_name)
            break
        except Exception as exc:
            logger.warning("Tentative micro %d/10: %s", retry, exc)
            time.sleep(1.5)

    if stream is None:
        logger.error("Impossible d'ouvrir le microphone")
        ui.show_toast("Microphone indisponible", toast_type="error")
        ui.set_status("idle")
        return

    _is_recording = True
    try:
        threshold = _calibrate_threshold(stream, blocksize, actual_rate)
        min_speech = max(1, int(actual_rate / blocksize * MIN_SPEECH_SEC))
        silence_limit = int(actual_rate / blocksize * SILENCE_LIMIT_SEC)
        max_buffer = int(actual_rate / blocksize * MAX_BUFFER_SEC)

        logger.info(
            "STT prêt: rate=%dHz, seuil=%.4f, min_speech=%.1fs, silence=%.1fs, max=%.0fs",
            actual_rate, threshold,
            min_speech * blocksize / actual_rate,
            silence_limit * blocksize / actual_rate,
            MAX_BUFFER_SEC,
        )

        ui.set_status("listening")
        ui.show_toast(f"Micro actif ({actual_rate}Hz)", toast_type="info")

        buffer: list[np.ndarray] = []
        silence_frames = 0
        speaking = False
        consecutive_above = 0
        frame_count = 0

        while not _stop_event.is_set():
            try:
                flat = _read_pa_stream(stream, blocksize)
            except Exception as exc:
                logger.warning("Erreur lecture PyAudio: %s — reconnexion dans 1s", exc)
                _close_pa_stream(stream)
                time.sleep(1)
                try:
                    stream, actual_rate, blocksize, device_name = _open_mic_stream(device_index)
                    threshold = _calibrate_threshold(stream, blocksize, actual_rate)
                    min_speech = max(1, int(actual_rate / blocksize * MIN_SPEECH_SEC))
                    silence_limit = int(actual_rate / blocksize * SILENCE_LIMIT_SEC)
                    max_buffer = int(actual_rate / blocksize * MAX_BUFFER_SEC)
                except Exception as reopen_exc:
                    logger.warning("Reconnexion micro échouée: %s", reopen_exc)
                buffer = []
                speaking = False
                silence_frames = 0
                consecutive_above = 0
                continue

            if _responding.is_set():
                buffer = []
                speaking = False
                silence_frames = 0
                consecutive_above = 0
                with _rms_lock:
                    _current_rms = 0.0
                if frame_count % 4 == 0:
                    ui.update_waveform(0.0)
                frame_count += 1
                continue

            rms = _float_rms(flat)
            with _rms_lock:
                _current_rms = _chunk_rms(flat)

            if frame_count % 4 == 0:
                ui.update_waveform(_chunk_rms(flat))
            if frame_count % 20 == 0:
                logger.debug(
                    "RMS courant=%.4f seuil=%.4f speaking=%s",
                    rms, threshold, speaking,
                )
            frame_count += 1

            if rms > threshold:
                consecutive_above += 1
                if consecutive_above >= SPEECH_CONFIRM_FRAMES:
                    if not speaking:
                        logger.debug(
                            "🎤 Parole confirmée après %d frames (RMS=%.4f > seuil=%.4f)",
                            consecutive_above, rms, threshold,
                        )
                    speaking = True
                    silence_frames = 0
                    buffer.append(flat.copy())
                    if len(buffer) > max_buffer:
                        logger.warning("Buffer trop long (>30s), transcription forcée")
                        silence_frames = silence_limit
            else:
                consecutive_above = 0
                if speaking:
                    silence_frames += 1
                    buffer.append(flat.copy())

                    if silence_frames >= silence_limit:
                        logger.debug(
                            "🔇 Fin de parole (%.1fs de silence)",
                            silence_frames * blocksize / actual_rate,
                        )
                        if len(buffer) >= min_speech:
                            try:
                                audio_np = np.concatenate(buffer).astype(np.float32)
                                if not _validate_speech_buffer(audio_np, actual_rate):
                                    buffer = []
                                    speaking = False
                                    silence_frames = 0
                                    if not _responding.is_set():
                                        ui.set_status("listening")
                                    continue
                                if STT_DEBUG:
                                    logger.info(
                                        "=== STT DIAGNOSTIC ===\nFrames: %d, durée: %.2fs",
                                        len(buffer), len(buffer) * blocksize / actual_rate,
                                    )
                                ui.set_status("transcribing")
                                text = _transcribe_audio(audio_np, actual_rate)
                                _handle_transcription_result(text)
                            except Exception as exc:
                                logger.error("Erreur pipeline transcription: %s", exc, exc_info=True)
                                ui.show_toast("Parole non comprise — réessaie", toast_type="info")
                                ui.set_status("listening")
                        else:
                            logger.debug(
                                "Buffer trop court (%d frames < min %d) — ignoré",
                                len(buffer), min_speech,
                            )

                        buffer = []
                        speaking = False
                        silence_frames = 0
                        if not _responding.is_set():
                            ui.set_status("listening")

    except Exception as exc:
        logger.error("Erreur fatale _record_loop: %s", exc, exc_info=True)
        ui.show_toast(f"Erreur micro: {exc}", toast_type="error")
    finally:
        _is_recording = False
        _close_pa_stream(stream)
        ui.set_status("idle")

    logger.info("Stopped listening")


def is_ready() -> bool:
    return _whisper_model is not None


def is_listening() -> bool:
    return _record_thread is not None and _record_thread.is_alive()


def start_listening() -> None:
    """Démarre le pipeline STT. Ignore si déjà actif."""
    global _record_thread

    with _record_lock:
        if _record_thread is not None and _record_thread.is_alive():
            logger.warning("STT déjà actif — démarrage ignoré (évite double instance)")
            return

        _stop_event.clear()

        def _bootstrap() -> None:
            try:
                _load_whisper_model()
            except Exception as exc:
                logger.error("Whisper non chargé: %s", exc)

        threading.Thread(target=_bootstrap, daemon=True, name="STT-WhisperBootstrap").start()
        sounds.play("listening")

        _record_thread = threading.Thread(
            target=_record_loop,
            daemon=True,
            name="STT-RecordLoop",
        )
        _record_thread.start()
        logger.info(
            "Listening for speech… (backend=%s, modèle=%s)",
            STT_BACKEND,
            _config.get("stt", {}).get("model", WHISPER_MODEL),
        )


def stop_listening() -> None:
    """Arrête l'écoute sans détruire l'instance PyAudio."""
    global _record_thread

    _stop_event.set()
    if _record_thread is not None and _record_thread.is_alive():
        _record_thread.join(timeout=5)
    _record_thread = None
    logger.info("STT arrêté")


def toggle() -> None:
    """Bascule écoute ON/OFF (F24 / Ctrl+Shift+A / bouton micro UI)."""
    if is_listening():
        stop_listening()
        logger.info("Pause — arrêt du microphone")
    else:
        start_listening()
        logger.info("Reprise — démarrage du microphone")
