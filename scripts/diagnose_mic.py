#!/usr/bin/env python3
"""
Script de diagnostic micro indépendant d'ARIA.
Lance-le pour identifier les problèmes Windows/device avant de déboguer stt.py.

Usage: python scripts/diagnose_mic.py
"""
from __future__ import annotations

import sys

try:
    import numpy as np
    import sounddevice as sd
except ImportError as exc:
    print(f"Dépendances manquantes: {exc}")
    print("Installe: pip install sounddevice numpy")
    sys.exit(1)


PREFERRED_DEVICE_KEYWORDS = [
    "intel® smart sound",
    "realtek hd audio mic",
    "microphone array",
    "bt le microphone",
    "realtek",
]
EXCLUDED_KEYWORDS = [
    "voicemeeter",
    "steam streaming",
    "mappeur de sons",
    "pilote de capture",
    "réseau de microphones",
    "mixage stéréo",
    "point",
    "vb-audio",
]


def _pick_best_device(devices) -> int | None:
    """Retourne l'index du meilleur device micro physique réel (même logique que stt.py)."""
    candidates = []
    for i, d in enumerate(devices):
        if d["max_input_channels"] < 1:
            continue
        name_lower = d["name"].lower()
        if any(excl in name_lower for excl in EXCLUDED_KEYWORDS):
            continue
        priority = 99
        for j, kw in enumerate(PREFERRED_DEVICE_KEYWORDS):
            if kw in name_lower:
                priority = j
                break
        candidates.append((priority, i, d["name"]))

    if not candidates:
        return None

    candidates.sort()
    return candidates[0][1]


def main() -> int:
    print("=== Diagnostic micro ARIA ===\n")

    print("Devices audio disponibles:")
    devices = sd.query_devices()
    default_in = sd.default.device[0]
    for i, d in enumerate(devices):
        if d.get("max_input_channels", 0) > 0:
            mark = " ← DÉFAUT" if i == default_in else ""
            print(
                f"  [{i}] {d['name']} | native: {d['default_samplerate']:.0f}Hz | "
                f"ch: {d['max_input_channels']}{mark}"
            )

    print("\nDevice recommandé pour ARIA:")
    best = _pick_best_device(devices)
    if best is not None:
        d = devices[best]
        print(f"  → [{best}] {d['name']}")
    else:
        print("  → Aucun device physique trouvé, ARIA utilisera le défaut")

    test_device = best if best is not None else default_in
    test_name = devices[test_device]["name"] if test_device is not None and test_device >= 0 else "défaut"
    print(f"\nTest de capture sur [{test_device}] {test_name}:")
    for rate in (48000, 44100, 16000, 22050):
        try:
            with sd.InputStream(
                samplerate=rate,
                channels=1,
                dtype="float32",
                blocksize=1024,
                device=test_device if test_device is not None and test_device >= 0 else None,
            ) as s:
                data, _ = s.read(1024)
                rms = float(np.sqrt(np.mean(data.flatten() ** 2)))
                print(f"  {rate}Hz → OK (RMS={rms:.4f})")
        except Exception as e:
            print(f"  {rate}Hz → ERREUR: {e}")

    print("\nEnregistrement 3 secondes — parle dans le micro...")
    try:
        rate = 44100
        blocksize = 1024
        frames: list[np.ndarray] = []
        with sd.InputStream(
            samplerate=rate,
            channels=1,
            dtype="float32",
            blocksize=blocksize,
            device=test_device if test_device is not None and test_device >= 0 else None,
        ) as s:
            n_blocks = int(rate / blocksize * 3)
            for _ in range(n_blocks):
                data, _ = s.read(blocksize)
                flat = data.flatten()
                frames.append(flat)
                rms = float(np.sqrt(np.mean(flat ** 2)))
                bar = "█" * min(40, int(rms * 500))
                print(f"\r  Niveau: {bar:<40} RMS={rms:.4f}", end="", flush=True)
            print()

        audio = np.concatenate(frames)
        rms_total = float(np.sqrt(np.mean(audio ** 2)))
        peak = float(np.max(np.abs(audio)))
        print(f"\nRMS total: {rms_total:.4f} | Peak: {peak:.4f}")

        if rms_total < 0.001:
            print("PROBLÈME: Signal trop faible — micro muté ou volume trop bas")
            print("Action: Paramètres Son → Enregistrement → Niveaux → Monter à 80+")
        elif rms_total > 0.3:
            print("ATTENTION: Signal très fort — risque de saturation")
            print("Action: Paramètres Son → Enregistrement → Niveaux → Baisser")
        else:
            print("Niveau correct")

        duration = len(audio) / rate
        print(f"Durée capturée: {duration:.2f}s — prêt pour Whisper si RMS > 0.001")

    except Exception as e:
        print(f"\nImpossible d'enregistrer: {e}")
        return 1

    print("\nTest PyAudio:")
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info["maxInputChannels"] < 1:
                continue
            name = info["name"]
            if any(excl in name.lower() for excl in ["voicemeeter", "steam", "mappeur"]):
                continue
            try:
                s = pa.open(
                    format=pyaudio.paFloat32,
                    channels=1,
                    rate=44100,
                    input=True,
                    frames_per_buffer=2048,
                    input_device_index=i,
                )
                raw = s.read(2048, exception_on_overflow=False)
                rms = float(np.sqrt(np.mean(np.frombuffer(raw, dtype=np.float32) ** 2)))
                status = f"RMS={rms:.4f}" if rms > 0.0001 else "SILENCIEUX"
                print(f"  [{i}] {name[:50]} → {status}")
                s.stop_stream()
                s.close()
            except Exception as e:
                print(f"  [{i}] {name[:50]} → ERREUR: {e}")
        pa.terminate()
    except ImportError:
        print("  PyAudio non installé — lance: pip install pyaudio")

    print("\n=== Fin du diagnostic ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
