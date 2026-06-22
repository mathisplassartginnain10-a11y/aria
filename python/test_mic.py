"""
test_mic.py — Diagnostic complet du microphone.
Lance : .venv\\Scripts\\python.exe python\\test_mic.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

print("=== DIAGNOSTIC MICROPHONE ARIA ===\n")

# 1. Test PyAudio
print("1. Test PyAudio...")
try:
    import pyaudio
    import numpy as np

    p = pyaudio.PyAudio()
    device_count = p.get_device_count()
    print(f"   OK PyAudio — {device_count} devices trouvés")
    print("   Devices d'entrée disponibles:")
    for i in range(device_count):
        info = p.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0:
            print(f"   [{i}] {info['name']} ({int(info['defaultSampleRate'])}Hz)")
    p.terminate()
except Exception as e:
    print(f"   ERREUR PyAudio: {e}")

# 2. Test capture audio
print("\n2. Test capture audio (3 secondes)...")
try:
    import pyaudio
    import numpy as np

    p = pyaudio.PyAudio()
    chunk = 1024
    stream = p.open(
        format=pyaudio.paFloat32,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=chunk,
    )
    frames = []
    for _ in range(int(3.0 * 16000 / chunk)):
        data = stream.read(chunk, exception_on_overflow=False)
        frames.append(np.frombuffer(data, dtype=np.float32))
    stream.stop_stream()
    stream.close()
    p.terminate()
    all_audio = np.concatenate(frames)
    rms = float(np.sqrt(np.mean(all_audio**2)))
    print(f"   OK Capture — RMS: {rms:.4f}")
    if rms < 0.001:
        print("   ATTENTION: son très faible — vérifie le device sélectionné")
    else:
        print("   OK Son détecté")
except Exception as e:
    print(f"   ERREUR capture: {e}")

# 3. Test faster-whisper
print("\n3. Test faster-whisper...")
try:
    from faster_whisper import WhisperModel

    WhisperModel("tiny", device="cpu", compute_type="int8")
    print("   OK faster-whisper")
except Exception as e:
    print(f"   ERREUR faster-whisper: {e}")

# 4. Test module stt ARIA
print("\n4. Test module stt ARIA...")
try:
    import stt

    devices = stt.get_available_devices()
    print(f"   OK stt.py — {len(devices)} device(s) listé(s)")
    report = stt.run_diagnostic()
    print(report)
except Exception as e:
    print(f"   ERREUR stt: {e}")

print("\n=== FIN DIAGNOSTIC ===")
