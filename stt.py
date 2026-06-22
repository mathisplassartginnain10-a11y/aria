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
import ui_bridge as ui

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
WHISPER_MODEL_DIR = _config.get("whisper_model_dir") or str(app_paths.whisper_models_dir())
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
    "haut-parleur du pc",
    "stereo input",
)

_whisper_device: str = "cpu"

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
_stt_callbacks: dict[str, Any] = {"on_result": None, "on_status": None}
VOICE_AUTO_SEND: bool = str(_config.get("voice_mode", "auto")).lower() in (
    "auto", "conversation", "live",
)

_whisper_model: Any | None = None
_whisper_lock = threading.Lock()
_active_backend: str = ""


def _normalize_backend_name(name: str) -> str:
    return str(name or "faster_whisper").lower().replace("-", "_")


def _faster_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _effective_backend() -> str:
    """Résout le backend STT effectif (faster_whisper ou openai_whisper local)."""
    configured = _normalize_backend_name(STT_BACKEND)
    if configured == "auto":
        if _faster_whisper_available():
            return "faster_whisper"
        if app_paths.voix_ia_whisper_dir():
            return "openai_whisper"
        return "faster_whisper"
    if configured in ("voix_ia", "openai_whisper", "whisper", "whisper_local"):
        return "openai_whisper"
    return "faster_whisper"


def _load_openai_whisper_model() -> Any:
    """Charge openai/whisper depuis voix ia/whisper-main."""
    import stt_whisper_local

    if not stt_whisper_local.is_available():
        raise RuntimeError(
            "Backend openai_whisper : dossier voix ia/whisper-main introuvable "
            "ou dépendances manquantes (torch, tiktoken)."
        )
    model, device = stt_whisper_local.load_model(WHISPER_MODEL, WHISPER_MODEL_DIR)
    global _whisper_device, _active_backend
    _whisper_device = device
    _active_backend = "openai_whisper"
    logger.info(
        "✅ Whisper local chargé: modèle=%s, device=%s, path=%s",
        WHISPER_MODEL,
        device,
        stt_whisper_local.voix_ia_whisper_dir(),
    )
    return model
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


def _stt_notify_status(status: str, value: Any = None) -> None:
    """Relaie le statut STT vers l'UI et les callbacks optionnels."""
    if status == "listening":
        ui.set_status("listening")
        ui.notify_mic_state(True)
    elif status == "transcribing":
        ui.set_status("transcribing")
    elif status == "idle":
        ui.set_status("idle")
        if not is_listening():
            ui.notify_mic_state(False)
    elif status == "error":
        ui.show_toast("Erreur microphone", toast_type="error")
        ui.set_status("idle")
        ui.notify_mic_state(False)
    elif status == "waveform" and value is not None:
        ui.update_waveform(float(value))

    cb = _stt_callbacks.get("on_status")
    if cb:
        try:
            if value is not None:
                cb(status, value)
            else:
                cb(status)
        except TypeError:
            cb(status)
        except Exception as exc:
            logger.debug("on_status callback: %s", exc)


def _safe_js(script: str) -> None:
    """Compat — remplacé par ui_bridge WebSocket."""
    del script


def _present_transcription(text: str) -> None:
    """Affiche la transcription dans l'input."""
    ui.show_final_transcription(text)
    cb = _stt_callbacks.get("on_result")
    if cb:
        try:
            cb(text)
        except Exception as exc:
            logger.debug("on_result callback: %s", exc)


def _show_partial_transcription(text: str) -> None:
    ui.show_partial_transcription(text)


def _show_final_transcription(text: str) -> None:
    _present_transcription(text)


def _float_rms(flat: np.ndarray) -> float:
    return float(np.sqrt(np.mean(flat.astype(np.float64) ** 2)))


def _chunk_rms(flat: np.ndarray) -> float:
    return _float_rms(flat)


def _maybe_update_waveform(level: float) -> None:
    """Émet le niveau micro vers l'UI pendant l'écoute."""
    if _is_recording or STT_DEBUG:
        ui.update_waveform(level)
        cb = _stt_callbacks.get("on_status")
        if cb and _is_recording:
            try:
                cb("waveform", level)
            except TypeError:
                pass
            except Exception:
                pass


def _waveform_level(flat: np.ndarray) -> float:
    """Niveau normalisé 0–1 pour l'UI (orbe / bouton micro)."""
    return _float_rms(flat)


def _host_api_priority(pa: Any, dev_idx: int) -> int:
    """WASAPI/MME d'abord — WDM-KS bloque souvent avec PyAudio."""
    try:
        info = pa.get_device_info_by_index(dev_idx)
        host = pa.get_host_api_info_by_index(int(info["hostApi"]))
        name = str(host.get("name", "")).lower()
    except Exception:
        return 50
    if "wasapi" in name:
        return 0
    if name == "mme":
        return 1
    if "directsound" in name:
        return 2
    if "wdm" in name:
        return 99
    return 50


def _device_sort_key(pa: Any, dev_idx: int, name: str) -> tuple[int, int, int]:
    name_lower = name.lower()
    kw_priority = 99
    for j, kw in enumerate(PREFERRED_DEVICE_KEYWORDS):
        if kw in name_lower:
            kw_priority = j
            break
    return (_host_api_priority(pa, dev_idx), kw_priority, dev_idx)


def _pick_best_device_pa() -> int | None:
    """Choisit le meilleur device micro physique via PyAudio."""
    pa = _get_pa()
    candidates: list[tuple[tuple[int, int, int], int, str]] = []
    for i in range(pa.get_device_count()):
        try:
            info = pa.get_device_info_by_index(i)
        except Exception:
            continue
        if info.get("maxInputChannels", 0) < 1:
            continue
        name = str(info.get("name", ""))
        name_lower = name.lower()
        if any(excl in name_lower for excl in EXCLUDED_KEYWORDS):
            continue
        sort_key = _device_sort_key(pa, i, name)
        candidates.append((sort_key, i, name))
        logger.debug(
            "Device PA [%d] %s (host=%d, kw=%d)",
            i, name, sort_key[0], sort_key[1],
        )

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
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
        pa_inputs: list[tuple[tuple[int, int, int], int]] = []
        for i in range(pa.get_device_count()):
            try:
                info = pa.get_device_info_by_index(i)
            except Exception:
                continue
            if info.get("maxInputChannels", 0) < 1:
                continue
            name = str(info.get("name", ""))
            if any(excl in name.lower() for excl in EXCLUDED_KEYWORDS):
                continue
            if _host_api_priority(pa, i) >= 99:
                continue
            pa_inputs.append((_device_sort_key(pa, i, name), i))
        pa_inputs.sort(key=lambda x: x[0])
        ordered = [i for _, i in pa_inputs]
        device_candidates = ([best] if best is not None else []) + [
            i for i in ordered if i != best
        ] + [None]

    blocksize = 2048
    last_error: Exception | None = None

    for dev_idx in device_candidates:
        device_name = "défaut"
        native_rate = 44100
        try:
            if dev_idx is not None:
                dev_info = pa.get_device_info_by_index(dev_idx)
                device_name = str(dev_info.get("name", "défaut"))
                native_rate = int(float(dev_info.get("defaultSampleRate", 44100)))
        except Exception:
            pass

        rates = list(dict.fromkeys([native_rate, 48000, 44100, 16000, 22050]))

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
                probe_rms: list[float] = []
                for _ in range(4):
                    probe_rms.append(_float_rms(_read_pa_stream(stream, blocksize)))
                max_rms = max(probe_rms) if probe_rms else 0.0
                if max_rms < 0.000001:
                    logger.warning(
                        "Device PA [%s] '%s' très silencieux (max RMS=%.6f) — conservé",
                        dev_idx,
                        device_name,
                        max_rms,
                    )

                ACTUAL_RATE = rate
                ACTUAL_BLOCKSIZE = blocksize
                _active_device_index = dev_idx
                logger.info(
                    "✅ PyAudio ouvert: device=[%s] '%s', rate=%dHz, RMS=%.4f",
                    dev_idx,
                    device_name,
                    rate,
                    max_rms,
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


def _is_cuda_whisper_error(exc: Exception) -> bool:
    err = str(exc).lower()
    return any(x in err for x in ("cublas", "cuda", "cudnn", "cufft", "gpu"))


def _force_whisper_cpu() -> Any:
    """Recharge Whisper sur CPU après échec CUDA à l'inférence."""
    global _whisper_model, _whisper_device, _active_backend

    with _whisper_lock:
        _whisper_model = None
        if _active_backend == "openai_whisper":
            import stt_whisper_local

            model, device = stt_whisper_local.load_model(
                WHISPER_MODEL, WHISPER_MODEL_DIR, device="cpu"
            )
            _whisper_model = model
            _whisper_device = device
            ui.show_toast("Whisper local en mode CPU", toast_type="warning")
            return _whisper_model

        from faster_whisper import WhisperModel

        kwargs: dict = {"device": "cpu", "compute_type": "int8", "num_workers": 1}
        if WHISPER_MODEL_DIR:
            kwargs["download_root"] = WHISPER_MODEL_DIR
        logger.warning("Bascule Whisper → CPU (%s)", WHISPER_MODEL)
        _whisper_model = WhisperModel(WHISPER_MODEL, **kwargs)
        _whisper_device = "cpu"
        _active_backend = "faster_whisper"
    ui.show_toast("Whisper en mode CPU (CUDA indisponible)", toast_type="warning")
    return _whisper_model


def _load_whisper_model():
    global _whisper_model, _whisper_device, _active_backend
    with _whisper_lock:
        if _whisper_model is not None:
            return _whisper_model

        backend = _effective_backend()
        if backend == "openai_whisper":
            _whisper_model = _load_openai_whisper_model()
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
        test_audio = np.random.randn(16000).astype(np.float32) * 0.01

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
                logger.info(
                    "Chargement Whisper '%s' sur %s (%s)…",
                    WHISPER_MODEL, device, compute_type,
                )
                model = WhisperModel(WHISPER_MODEL, **kwargs)
                list(model.transcribe(test_audio, language=STT_LANGUAGE)[0])
                _whisper_model = model
                _whisper_device = device
                _active_backend = "faster_whisper"
                logger.info(
                    "✅ Whisper chargé: modèle=%s, device=%s, compute=%s, backend=%s",
                    WHISPER_MODEL, device, compute_type, _active_backend,
                )
                return _whisper_model
            except Exception as exc:
                last_error = exc
                logger.warning("Config Whisper %s/%s échouée: %s", device, compute_type, exc)
                if device == "cuda" and _is_cuda_whisper_error(exc):
                    logger.warning("CUDA Whisper indisponible — essai CPU")

        # Fallback voix ia/ openai-whisper si faster-whisper échoue
        if app_paths.voix_ia_whisper_dir():
            logger.warning(
                "faster-whisper indisponible (%s) — bascule voix ia/openai-whisper",
                last_error,
            )
            try:
                _whisper_model = _load_openai_whisper_model()
                ui.show_toast("STT : bascule sur Whisper local (voix ia)", toast_type="info")
                return _whisper_model
            except Exception as local_exc:
                last_error = local_exc

        raise RuntimeError(f"Impossible de charger Whisper: {last_error}")


def _run_whisper_pass(audio_16k: np.ndarray, **kwargs) -> tuple[str, Any]:
    if _active_backend == "openai_whisper":
        import stt_whisper_local

        text = stt_whisper_local.transcribe_audio(
            _whisper_model,
            audio_16k,
            language=str(kwargs.get("language") or STT_LANGUAGE),
            beam_size=int(kwargs.get("beam_size") or 5),
            temperature=float(kwargs.get("temperature") or 0.0),
        )
        return text, None

    segments, info = _whisper_model.transcribe(audio_16k, **kwargs)
    return " ".join(s.text for s in segments).strip(), info


def _transcribe(audio_16k: np.ndarray) -> str:
    """Transcription Whisper — 3 tentatives (T1 VAD, T2 sans VAD, T3 température)."""
    global _whisper_model

    ok, reason = _check_audio_quality(audio_16k)
    if not ok:
        logger.warning("Audio rejeté: %s", reason)
        return ""

    _load_whisper_model()

    passes = [
        ("T1", {
            "language": STT_LANGUAGE,
            "beam_size": 5,
            "temperature": 0.0,
            "vad_filter": True,
            "vad_parameters": {
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 200,
                "threshold": 0.45,
                "min_speech_duration_ms": 400,
            },
            "condition_on_previous_text": False,
            "no_speech_threshold": 0.4,
        }),
        ("T2", {
            "language": STT_LANGUAGE,
            "beam_size": 5,
            "temperature": 0.0,
            "vad_filter": False,
            "condition_on_previous_text": False,
            "no_speech_threshold": 0.8,
        }),
        ("T3", {
            "language": STT_LANGUAGE,
            "beam_size": 3,
            "temperature": 0.2,
            "vad_filter": False,
            "condition_on_previous_text": False,
            "no_speech_threshold": 0.9,
        }),
    ]

    for idx, (label, kwargs) in enumerate(passes):
        if idx > 0:
            logger.warning("%s vide — retry %s", passes[idx - 1][0], label)
        try:
            raw_text, info = _run_whisper_pass(audio_16k, **kwargs)
            cleaned = _clean_transcription(raw_text)
            logger.warning(
                "WHISPER %s (%s/%s): brut='%s' clean='%s' lang=%s(%.2f)",
                label,
                _whisper_device,
                WHISPER_MODEL,
                raw_text,
                cleaned,
                getattr(info, "language", "?"),
                float(getattr(info, "language_probability", 0.0) or 0.0),
            )
            if cleaned:
                return cleaned
        except Exception as exc:
            if _is_cuda_whisper_error(exc) and _whisper_device != "cpu":
                logger.warning("%s CUDA échouée, bascule CPU: %s", label, exc)
                _force_whisper_cpu()
                try:
                    raw_text, info = _run_whisper_pass(audio_16k, **kwargs)
                    cleaned = _clean_transcription(raw_text)
                    logger.warning(
                        "WHISPER %s CPU: brut='%s' clean='%s'",
                        label, raw_text, cleaned,
                    )
                    if cleaned:
                        return cleaned
                except Exception as exc2:
                    logger.error("%s erreur CPU: %s", label, exc2)
            else:
                logger.error("%s erreur: %s", label, exc)

    sr_text = _transcribe_speech_recognition(audio_16k)
    if sr_text:
        logger.info("Fallback SpeechRecognition: '%s'", sr_text)
        return sr_text

    return ""


def _transcribe_speech_recognition(audio_16k: np.ndarray) -> str:
    """Fallback Google SpeechRecognition (nécessite Internet)."""
    try:
        import io
        import wave

        import speech_recognition as sr
    except ImportError:
        return ""

    try:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            pcm = (np.clip(audio_16k, -1.0, 1.0) * 32767).astype(np.int16)
            wf.writeframes(pcm.tobytes())
        buf.seek(0)

        recognizer = sr.Recognizer()
        with sr.AudioFile(buf) as source:
            audio_data = recognizer.record(source)
        text = recognizer.recognize_google(audio_data, language="fr-FR")
        return _clean_transcription(text.strip())
    except Exception as exc:
        logger.debug("SpeechRecognition échoué: %s", exc)
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
            _load_whisper_model()
            if _active_backend == "openai_whisper":
                import stt_whisper_local

                text = _clean_transcription(
                    stt_whisper_local.transcribe_file(
                        _whisper_model,
                        str(path),
                        language=lang,
                    )
                )
                logger.info("Whisper local fichier: texte='%s'", text)
                return text

            segments, info = _whisper_model.transcribe(
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
                segments2, _ = _whisper_model.transcribe(
                    str(path), language=lang, vad_filter=False, temperature=0.0
                )
                text = _clean_transcription(" ".join(s.text for s in segments2).strip())
            logger.info("Whisper fichier: lang=%s, texte='%s'", getattr(info, "language", "?"), text)
            return text
        except Exception as exc:
            err = str(exc).lower()
            if attempt == 0 and _is_cuda_whisper_error(exc):
                logger.warning("Transcription fichier CUDA échouée, bascule CPU: %s", exc)
                _force_whisper_cpu()
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
        text = _finalize_transcription(text)
        logger.info("✅ Transcription Whisper: '%s'", text)
        _present_transcription(text)
        if VOICE_AUTO_SEND:
            ui.set_status("thinking")
            _dispatch_to_assistant(text)
        else:
            ui.set_status("listening")
    else:
        logger.warning("❌ Transcription vide après 3 tentatives Whisper")
        ui.show_toast("Parole non comprise — réessaie", toast_type="info")
        ui.set_status("listening")


def _get_realtime_model():
    global _realtime_model
    if _realtime_model is None:
        backend = _active_backend or _effective_backend()
        if backend == "openai_whisper":
            import stt_whisper_local

            model, _ = stt_whisper_local.load_model("tiny", WHISPER_MODEL_DIR)
            _realtime_model = model
        else:
            from faster_whisper import WhisperModel
            try:
                _realtime_model = WhisperModel("tiny", device="cuda", compute_type="int8")
            except Exception:
                _realtime_model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _realtime_model


def _realtime_partial_text(rt_model: Any, audio_16k: np.ndarray) -> str:
    """Transcription partielle temps réel — compatible faster-whisper et voix ia."""
    if _active_backend == "openai_whisper":
        import stt_whisper_local

        raw = stt_whisper_local.transcribe_audio(
            rt_model,
            audio_16k,
            language=STT_LANGUAGE,
            beam_size=1,
            temperature=0.0,
        )
        return _clean_transcription(raw)

    segments, _ = rt_model.transcribe(
        audio_16k,
        language=STT_LANGUAGE,
        beam_size=1,
        temperature=0.0,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    return _clean_transcription(" ".join(s.text for s in segments).strip())


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
        _load_whisper_model()
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
                _current_rms = _waveform_level(flat)
            if frame_count % 4 == 0:
                _maybe_update_waveform(_waveform_level(flat))
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
                        partial = _realtime_partial_text(rt_model, audio_16k)
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
                                _stt_notify_status("transcribing")
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

    logger.info("Démarrage _record_loop (spec v17) — device_index=%s", device_index)
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
        _stt_notify_status("listening")
        ui.show_toast(
            f"Micro actif · Whisper {WHISPER_MODEL} ({actual_rate}Hz)",
            toast_type="info",
        )

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
                    _maybe_update_waveform(0.0)
                frame_count += 1
                continue

            rms = _float_rms(flat)
            with _rms_lock:
                _current_rms = _waveform_level(flat)

            if frame_count % 4 == 0:
                _maybe_update_waveform(_waveform_level(flat))
            if frame_count % 20 == 0 and STT_DEBUG:
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
                                _stt_notify_status("transcribing")
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


def start_listening(
    device_index: int | None = None,
    language: str | None = None,
    on_result=None,
    on_status=None,
) -> None:
    """Démarre le pipeline STT."""
    global _record_thread, STT_DEVICE_INDEX, STT_LANGUAGE

    logger.info("=== start_listening() appelé ===")
    logger.info(
        "Backend configuré: %s, modèle chargé: %s",
        _active_backend or _effective_backend(),
        _whisper_model is not None,
    )

    if device_index is not None:
        STT_DEVICE_INDEX = int(device_index)
    if language:
        STT_LANGUAGE = str(language)
    if on_result is not None:
        _stt_callbacks["on_result"] = on_result
    if on_status is not None:
        _stt_callbacks["on_status"] = on_status

    with _record_lock:
        if _record_thread is not None and _record_thread.is_alive():
            logger.warning("Déjà en écoute — arrêt puis redémarrage")
            _stop_event.set()
            _record_thread.join(timeout=3)
            _record_thread = None
            time.sleep(0.3)

        _stop_event.clear()

        try:
            _load_whisper_model()
            logger.info(
                "Whisper prêt pour STT: %s sur %s (backend=%s)",
                WHISPER_MODEL,
                _whisper_device,
                _active_backend or _effective_backend(),
            )
        except Exception as exc:
            logger.error("AUCUN backend STT disponible: %s", exc, exc_info=True)
            ui.show_toast(f"Whisper indisponible: {exc}", toast_type="error")
            _stt_notify_status("error")
            return

        sounds.play("listening")

        _record_thread = threading.Thread(
            target=_record_loop,
            daemon=True,
            name="ARIA-STT-RecordLoop",
        )
        _record_thread.start()
        logger.info("Thread STT démarré: %s", _record_thread.name)
        _stt_notify_status("listening")


def stop_listening() -> None:
    """Arrête l'écoute sans détruire l'instance PyAudio."""
    global _record_thread

    logger.info("=== stop_listening() appelé ===")
    _stop_event.set()
    if _record_thread is not None and _record_thread.is_alive():
        _record_thread.join(timeout=5)
    _record_thread = None
    _stt_notify_status("idle")
    logger.info("STT arrêté")


def run_diagnostic() -> str:
    """Diagnostic rapide micro + Whisper pour l'UI."""
    lines = [
        "=== Diagnostic STT ARIA ===",
        f"Backend configuré: {STT_BACKEND}",
        f"Backend actif: {_active_backend or _effective_backend()}",
        f"Modèle Whisper: {WHISPER_MODEL}",
        f"Langue: {STT_LANGUAGE}",
    ]
    voix_path = app_paths.voix_ia_whisper_dir()
    if voix_path:
        lines.append(f"voix ia/: {voix_path}")
    else:
        lines.append("voix ia/: absent")
    lines.append(f"Cache modèles: {WHISPER_MODEL_DIR}")
    try:
        pa = _get_pa()
        lines.append(f"PyAudio: OK ({pa.get_device_count()} devices)")
        best = _pick_best_device_pa()
        if best is not None:
            info = pa.get_device_info_by_index(best)
            host = pa.get_host_api_info_by_index(int(info["hostApi"]))
            lines.append(f"Micro recommandé: [{best}] {info['name']}")
            lines.append(f"  Host API: {host.get('name', '?')}")
        else:
            lines.append("Micro recommandé: aucun trouvé")
    except Exception as exc:
        lines.append(f"PyAudio: ERREUR — {exc}")

    try:
        _load_whisper_model()
        lines.append(
            f"Whisper: OK (backend={_active_backend or '?'}, device={_whisper_device}, modèle={WHISPER_MODEL})"
        )
    except Exception as exc:
        lines.append(f"Whisper: ERREUR — {exc}")

    try:
        stream, rate, blocksize, name = _open_mic_stream(_find_input_device())
        rms = _float_rms(_read_pa_stream(stream, blocksize))
        lines.append(f"Capture test: OK — {name} @ {rate}Hz, RMS={rms:.4f}")
        _close_pa_stream(stream)
    except Exception as exc:
        lines.append(f"Capture test: ERREUR — {exc}")

    lines.append("Devices d'entrée:")
    for dev in get_available_devices():
        lines.append(
            f"  [{dev['index']}] {dev['name']} ({dev['sample_rate']}Hz, {dev['channels']}ch)"
        )

    report = "\n".join(lines)
    logger.info(report)
    return report


def get_available_devices() -> list[dict]:
    """Liste les périphériques d'entrée audio PyAudio."""
    devices: list[dict] = []
    try:
        pa = _get_pa()
        for i in range(pa.get_device_count()):
            try:
                info = pa.get_device_info_by_index(i)
                if int(info.get("maxInputChannels", 0)) < 1:
                    continue
                devices.append({
                    "index": i,
                    "name": str(info.get("name", "")),
                    "channels": int(info.get("maxInputChannels", 1)),
                    "sample_rate": int(info.get("defaultSampleRate", 16000)),
                })
            except Exception:
                pass
    except Exception as exc:
        logger.debug("get_available_devices: %s", exc)
    return devices


def load_whisper_model(model_name: str | None = None) -> None:
    """API publique — charge le modèle STT (appelée au boot)."""
    global WHISPER_MODEL
    if model_name:
        WHISPER_MODEL = str(model_name)
    _load_whisper_model()


def toggle() -> None:
    """Bascule écoute ON/OFF (F24 / Ctrl+Shift+A / bouton micro UI)."""
    if is_listening():
        stop_listening()
        logger.info("Pause — arrêt du microphone")
    else:
        start_listening()
        logger.info("Reprise — démarrage du microphone")
