r"""
Test standalone de la transcription Whisper en français.
Lance avec : .\.venv\Scripts\python.exe scripts\test_whisper_fr.py

Ce script :
1. Charge le modèle faster-whisper (même config qu'ARIA)
2. Enregistre 5 secondes depuis le micro
3. Transcrit et affiche le résultat brut
4. Vérifie que la langue détectée est bien le français
"""

from __future__ import annotations

import io
import sys
from math import gcd
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pyaudio
import scipy.signal
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

BLOCKSIZE = 2048
RECORD_SEC = 5
RATES = [44100, 48000, 16000, 22050]
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

cfg_path = Path(__file__).parent.parent / "config.yaml"
try:
    with cfg_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
except OSError:
    config = {}

stt_cfg = config.get("stt", {})
MODEL_SIZE = stt_cfg.get("model", "small")
DEVICE_IDX = stt_cfg.get("device_index", None)
LANGUAGE = stt_cfg.get("language", "fr")


def _rms(buf: bytes | np.ndarray) -> float:
    data = np.frombuffer(buf, dtype=np.float32) if isinstance(buf, (bytes, bytearray)) else buf
    if data.size == 0:
        return 0.0
    sq = np.nan_to_num(data.astype(np.float64) ** 2, nan=0.0, posinf=0.0, neginf=0.0)
    mean_sq = float(np.mean(sq))
    if not np.isfinite(mean_sq):
        return 0.0
    return float(np.sqrt(mean_sq))


def _rms_valid(rms: float) -> bool:
    """Rejette les buffers corrompus (float32 hors plage [-1, 1])."""
    return np.isfinite(rms) and rms <= 1.0


def _pick_best_device(pa: pyaudio.PyAudio) -> int | None:
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
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def _open_mic_stream(pa: pyaudio.PyAudio) -> tuple[pyaudio.Stream, int, int, str]:
    if DEVICE_IDX is not None:
        device_candidates: list[int | None] = [int(DEVICE_IDX)]
    else:
        best = _pick_best_device(pa)
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

    last_error: Exception | None = None
    for dev_idx in device_candidates:
        device_name = "défaut"
        try:
            if dev_idx is not None:
                device_name = str(pa.get_device_info_by_index(dev_idx).get("name", "défaut"))
        except Exception:
            pass

        for rate in RATES:
            stream = None
            try:
                stream = pa.open(
                    format=pyaudio.paFloat32,
                    channels=1,
                    rate=rate,
                    input=True,
                    frames_per_buffer=BLOCKSIZE,
                    input_device_index=dev_idx,
                )
                raw = stream.read(BLOCKSIZE, exception_on_overflow=False)
                rms = _rms(raw)
                if not _rms_valid(rms):
                    print(
                        f"   Device [{dev_idx}] '{device_name[:40]}' @ {rate}Hz "
                        f"— signal invalide (RMS={rms:.6f})"
                    )
                    stream.stop_stream()
                    stream.close()
                    continue
                print(
                    f"✅ Device [{dev_idx}] '{device_name[:50]}' @ {rate}Hz — RMS test={rms:.4f}"
                )
                return stream, rate, dev_idx if dev_idx is not None else -1, device_name
            except Exception as e:
                last_error = e
                print(f"   Device [{dev_idx}] @ {rate}Hz : {e}")
                if stream is not None:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass

    raise RuntimeError(f"Impossible d'ouvrir un device micro valide: {last_error}")


print("=" * 55)
print("   TEST WHISPER FRANÇAIS — ARIA")
print("=" * 55)
print(f"Modèle    : {MODEL_SIZE}")
print(f"Langue    : {LANGUAGE}")
print(f"Device    : {DEVICE_IDX if DEVICE_IDX is not None else 'auto'}")
print()

print("Chargement du modèle Whisper...")
try:
    from faster_whisper import WhisperModel
    import torch

    configs = [
        ("cuda", "float16"),
        ("cuda", "int8"),
        ("cpu", "int8"),
    ]
    model = None
    for device, compute in configs:
        if device == "cuda" and not torch.cuda.is_available():
            continue
        try:
            model = WhisperModel(MODEL_SIZE, device=device, compute_type=compute)
            print(f"✅ Modèle chargé : {MODEL_SIZE} | {device} | {compute}")
            break
        except Exception as e:
            print(f"   {device}/{compute} : {e}")

    if model is None:
        print("❌ Impossible de charger le modèle Whisper")
        sys.exit(1)

except ImportError:
    print("❌ faster-whisper non installé")
    print("   Lance : pip install faster-whisper")
    sys.exit(1)

print()
print("Ouverture du micro...")
pa = pyaudio.PyAudio()

print("Devices disponibles :")
default_idx = pa.get_default_input_device_info()["index"]
for i in range(pa.get_device_count()):
    info = pa.get_device_info_by_index(i)
    if info["maxInputChannels"] > 0:
        marker = " ← DÉFAUT" if i == default_idx else ""
        marker += " ← FORCÉ" if i == DEVICE_IDX else ""
        skip = any(k in info["name"].lower() for k in EXCLUDED_KEYWORDS)
        if not skip:
            print(f"  [{i}] {info['name'][:55]}{marker}")

try:
    stream, sample_rate, active_dev, device_name = _open_mic_stream(pa)
except RuntimeError as e:
    print(f"❌ {e}")
    pa.terminate()
    sys.exit(1)

print()
print("Calibration bruit ambiant (1s)...")
cal = []
for _ in range(int(sample_rate / BLOCKSIZE * 1)):
    raw = stream.read(BLOCKSIZE, exception_on_overflow=False)
    cal.append(_rms(raw))
ambient = float(np.mean(cal))
if not np.isfinite(ambient):
    ambient = 0.0
threshold = max(ambient * 2.5, 0.015)
print(f"   Ambiant={ambient:.4f}, Seuil={threshold:.4f}")

print()
print(f"Enregistrement {RECORD_SEC}s — PARLE MAINTENANT...")
print("   (dis une phrase en français, ex: 'Lance Google Chrome')")
print()

frames = []
total_frames = int(sample_rate / BLOCKSIZE * RECORD_SEC)

for i in range(total_frames):
    raw = stream.read(BLOCKSIZE, exception_on_overflow=False)
    data = np.frombuffer(raw, dtype=np.float32)
    frames.append(data.copy())
    rms = _rms(data)
    if not np.isfinite(rms):
        rms = 0.0
    bar_len = int(rms / threshold * 20) if threshold > 0 else 0
    bar = "█" * min(bar_len, 40)
    seuil_mark = "|" if bar_len < 40 else "!"
    remaining = RECORD_SEC - (i * BLOCKSIZE / sample_rate)
    print(f"\r  [{bar:<40}] {seuil_mark} RMS={rms:.3f} ({remaining:.1f}s)", end="", flush=True)

print()
stream.stop_stream()
stream.close()
pa.terminate()

audio_np = np.concatenate(frames).astype(np.float32)
duration = len(audio_np) / sample_rate
rms_total = _rms(audio_np)
print(f"\nAudio capturé : {duration:.2f}s | RMS={rms_total:.4f} | samples={len(audio_np)}")

g = gcd(16000, sample_rate)
audio_16k = scipy.signal.resample_poly(audio_np, 16000 // g, sample_rate // g).astype(np.float32)
print(f"Resamplé     : {len(audio_16k)/16000:.2f}s @ 16kHz | samples={len(audio_16k)}")

print()
print("Transcription Whisper...")
print("-" * 55)

last_info = None

print("[T1] VAD activé, language='fr', temperature=0.0")
try:
    segs, info = model.transcribe(
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
    text_t1 = " ".join(s.text for s in segs).strip()
    last_info = info
    print(f"   Langue détectée : {info.language} (prob={info.language_probability:.2f})")
    print(f"   Texte brut      : {repr(text_t1)}")
except Exception as e:
    text_t1 = ""
    print(f"   ERREUR T1: {e}")

print("[T2] VAD désactivé, language='fr', temperature=0.0")
try:
    segs, info = model.transcribe(
        audio_16k,
        language="fr",
        beam_size=5,
        temperature=0.0,
        vad_filter=False,
        condition_on_previous_text=False,
        no_speech_threshold=0.8,
    )
    text_t2 = " ".join(s.text for s in segs).strip()
    last_info = info
    print(f"   Langue détectée : {info.language} (prob={info.language_probability:.2f})")
    print(f"   Texte brut      : {repr(text_t2)}")
except Exception as e:
    text_t2 = ""
    print(f"   ERREUR T2: {e}")

print("[T3] VAD désactivé, langue AUTO, temperature=0.0")
try:
    segs, info = model.transcribe(
        audio_16k,
        beam_size=5,
        temperature=0.0,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    text_t3 = " ".join(s.text for s in segs).strip()
    last_info = info
    print(f"   Langue détectée : {info.language} (prob={info.language_probability:.2f})")
    print(f"   Texte brut      : {repr(text_t3)}")
except Exception as e:
    text_t3 = ""
    print(f"   ERREUR T3: {e}")

print()
print("=" * 55)
print("   RÉSULTAT FINAL")
print("=" * 55)

best = text_t1 or text_t2 or text_t3
if best:
    print(f"✅ Transcription : '{best}'")
    detected_lang = getattr(last_info, "language", None) if last_info else None
    if detected_lang == "fr":
        print("✅ Langue        : français détecté correctement")
    else:
        print(f"⚠️  Langue        : {detected_lang} détecté — forcer language='fr' dans config")
else:
    print("❌ Aucune transcription — vérifier :")
    print("   1. RMS pendant l'enregistrement > seuil (barre doit dépasser |)")
    print("   2. Micro non muté dans Windows > Paramètres > Son > Entrées")
    print("   3. Essayer device_index différent dans config.yaml")
    if rms_total < 0.01:
        print(f"\n⚠️  RMS trop faible ({rms_total:.4f}) — micro muté ou trop bas")

print()
print("Commande pour forcer un device spécifique :")
print("  Modifier config.yaml → stt.device_index: <numéro>")
print()
