"""Test microphone indépendamment de tout le reste."""
import sounddevice as sd
import numpy as np
import wave
import tempfile
import time

print("=== TEST MICROPHONE ===")
print(f"sounddevice version: {sd.__version__}")
print(f"\nPériphériques audio disponibles:")
print(sd.query_devices())
print(f"\nPériphérique par défaut: {sd.default.device}")

print("\n1. Test enregistrement 3 secondes...")
try:
    audio = sd.rec(int(3 * 16000), samplerate=16000, channels=1, dtype="float32")
    sd.wait()
    rms = float(np.sqrt(np.mean(audio**2)) * 32768)
    print(f"   RMS moyen: {rms:.1f}")
    if rms > 10:
        print("   OK Micro fonctionne")
    else:
        print("   FAIL Micro silencieux (RMS trop bas)")
except Exception as e:
    print(f"   FAIL Erreur: {e}")

print("\n2. Test InputStream latency=high...")
try:
    with sd.InputStream(
        samplerate=16000,
        channels=1,
        dtype="float32",
        blocksize=1024,
        latency="high",
    ) as stream:
        data, _ = stream.read(1024)
        rms = float(np.sqrt(np.mean(data**2)) * 32768)
        print(f"   RMS: {rms:.1f} — OK Stream ouvert")
except Exception as e:
    print(f"   FAIL Erreur: {e}")

print("\n2b. Test InputStream avec device sélectionné...")
device_index = None
for d in sd.query_devices():
    if d["max_input_channels"] > 0:
        name = d.get("name", "")
        if "microsoft" not in name.lower() and "mapper" not in name.lower():
            device_index = d["index"]
            print(f"   Device choisi: [{device_index}] {name}")
            break
try:
    with sd.InputStream(
        samplerate=16000,
        channels=1,
        dtype="float32",
        blocksize=2048,
        device=device_index,
        latency="high",
    ) as stream:
        data, _ = stream.read(2048)
        rms = float(np.sqrt(np.mean(data**2)) * 32768)
        print(f"   RMS: {rms:.1f} — OK Stream device ouvert")
except Exception as e:
    print(f"   FAIL Erreur device: {e}")

print("\n3. Test Whisper sur 3 secondes de voix...")
for device, ctype in [("cuda", "float16"), ("cpu", "int8")]:
    try:
        from faster_whisper import WhisperModel

        print(f"   Essai Whisper device={device} compute_type={ctype}...")
        model = WhisperModel("small", device=device, compute_type=ctype)
        audio = sd.rec(int(3 * 16000), samplerate=16000, channels=1, dtype="float32")
        print("   Parle maintenant (3 sec)...")
        sd.wait()
        tmp = tempfile.mktemp(suffix=".wav")
        with wave.open(tmp, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes((audio * 32768).astype(np.int16).tobytes())
        segments, info = model.transcribe(tmp, language="fr")
        text = " ".join(s.text for s in segments).strip()
        print(f"   Transcription ({device}): '{text}'")
        if text:
            print(f"   OK Whisper fonctionne sur {device}")
        else:
            print(f"   WARN Transcription vide sur {device}")
        break
    except Exception as e:
        print(f"   FAIL Erreur Whisper ({device}): {e}")

print("\n=== FIN TEST ===")
