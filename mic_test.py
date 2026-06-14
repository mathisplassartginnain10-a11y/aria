"""Test micro autonome pour ARIA.

Usage :  python mic_test.py [secondes]
Affiche les périphériques, ouvre le micro choisi par ARIA, montre le niveau RMS
en direct pendant que tu parles, puis transcrit avec Whisper et propose un seuil.
"""
import sys
import platform as _p
_p._wmi = None  # évite le gel de platform.system() sur certains Windows

import numpy as np
import stt

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main() -> None:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
    sd = stt.sd

    print("=== Périphériques d'entrée ===")
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_input_channels", 0) > 0:
            host = sd.query_hostapis(d["hostapi"])["name"]
            print(f"  [{i:2}] {d['name'][:48]:48} {d['max_input_channels']}ch {int(d.get('default_samplerate',0))}Hz [{host}]")

    dev = stt._find_input_device()
    name = sd.query_devices(dev)["name"] if dev is not None else "défaut système"
    print(f"\n>>> ARIA utilisera : [{dev}] {name}")

    print("Chargement de Whisper (peut prendre quelques secondes)…")
    stt._load_whisper_model()

    stream, rate, block = stt._open_mic_stream(dev)
    print(f"Micro ouvert : {rate} Hz, bloc {block}\n")
    print(f">>>>> PARLE MAINTENANT pendant {seconds:.0f}s — dis une phrase claire <<<<<\n")

    frames, rms_list = [], []
    for _ in range(int(rate / block * seconds)):
        data, _ = stream.read(block)
        flat = data.flatten()
        rms = stt._chunk_rms(flat)
        rms_list.append(rms)
        frames.append(flat.copy())
        bar = "#" * min(50, int(rms / 25))
        print(f"\rRMS {rms:6.0f} |{bar:<50}|", end="", flush=True)
    print()
    stream.stop()
    stream.close()

    audio = np.concatenate(frames).astype(np.float32)
    quiet = float(np.percentile(rms_list, 20))   # moments les plus calmes
    noise = float(np.percentile(rms_list, 60))   # bruit de fond typique (= calibration ARIA)
    speech = float(np.percentile(rms_list, 90))  # niveau quand tu parles
    peak = float(np.max(rms_list))
    threshold = min(max(noise * 1.6, 200.0), 4000.0)

    print(f"\nNiveaux ->  calme~{quiet:.0f}   bruit~{noise:.0f}   parole(p90)~{speech:.0f}   pic~{peak:.0f}")
    print(f"Seuil calcule par ARIA (bruit x marge) : {threshold:.0f}")
    if speech > threshold * 1.15:
        print("[OK] La parole se detache bien du bruit -> la detection devrait marcher.")
    elif speech > threshold:
        print("[~]  Parole juste au-dessus du seuil -> baisse silence_margin (ex: 1.35).")
    else:
        print("[X]  Parole SOUS le seuil -> parle plus fort/plus pres, ou baisse silence_margin (1.3).")
    print("     Reglages : config.yaml -> silence_margin (defaut 1.6), silence_floor.")

    print("\n=== TRANSCRIPTION WHISPER ===")
    text = stt._transcribe_audio(audio, rate)
    print(text if text else "(vide -- Whisper n'a rien compris : parle plus fort/plus pres)")


if __name__ == "__main__":
    main()
