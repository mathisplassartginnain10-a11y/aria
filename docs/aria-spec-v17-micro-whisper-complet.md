# ARIA — Spec v17 : Résolution complète des problèmes micro + alternatives Whisper

## Contexte

Le micro détecte la parole (RMS au-dessus du seuil) mais la transcription retourne vide
ou échoue silencieusement. Ce document couvre :
1. Diagnostic systématique du pipeline STT
2. Corrections de stt.py (faster-whisper, déjà en place)
3. Alternatives si faster-whisper ne suffit pas
4. Réglages Windows côté système
5. Guide de fallback complet

---

## Partie 1 — Diagnostic systématique

### 1.1 Arbre de décision : où ça coince ?

```
Micro détecté → RMS > seuil ?
  │
  OUI → Buffer audio constitué ?
  │       │
  │       OUI → _resample_to_16k() réussit ?
  │       │       │
  │       │       OUI → transcribe() appelé ?
  │       │       │       │
  │       │       │       OUI → segments non vides ?
  │       │       │       │       │
  │       │       │       │       OUI → texte dans l'UI ? → ✅ OK
  │       │       │       │       │
  │       │       │       │       NON → Problème VAD / no_speech_prob trop élevé
  │       │       │       │             → FIX 3 (VAD moins agressif)
  │       │       │       │
  │       │       │       NON → Exception dans transcribe()
  │       │       │             → FIX 4 (compute_type / modèle)
  │       │       │
  │       │       NON → Erreur resampling (scipy)
  │       │             → FIX 2 (resampling robuste)
  │       │
  │       NON → MIN_SPEECH trop élevé ou SILENCE_LIMIT trop court
  │             → FIX 1 (seuils timing)
  │
  NON → Problème de seuil (THRESHOLD trop élevé)
        ou device micro mauvais
        → FIX 0 (calibration + device)
```

### 1.2 Logs de diagnostic à ajouter en premier

Avant toute correction, ajoute ces logs dans stt.py pour identifier précisément où ça
coince :

```python
# Après constitution du buffer (silence détecté) :
logger.info("=== STT DIAGNOSTIC ===")
logger.info("Frames capturées: %d, durée: %.2fs", len(buffer), len(buffer)*blocksize/actual_rate)
logger.info("Audio brut: min=%.4f max=%.4f rms=%.4f", float(np.min(audio_np)), float(np.max(audio_np)), float(np.sqrt(np.mean(audio_np**2))))

# Après resampling :
logger.info("Audio 16k: shape=%s, dtype=%s, min=%.4f max=%.4f", audio_16k.shape, audio_16k.dtype, float(np.min(audio_16k)), float(np.max(audio_16k)))

# Après transcription :
logger.info("Whisper résultat: lang=%s (prob=%.2f), nb_segments=%d, texte='%s'",
    info.language, info.language_probability,
    sum(1 for _ in segments), text)
```

---

## Partie 2 — Corrections stt.py (faster-whisper)

### FIX 0 — Calibration du device et seuils

```python
def _open_mic_stream():
    """Ouvre le stream micro avec le meilleur sample rate disponible."""
    import sounddevice as sd

    # Lister tous les devices disponibles et choisir le meilleur
    devices = sd.query_devices()
    logger.info("Devices audio disponibles:")
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0:
            logger.info("  [%d] %s (native: %.0fHz, ch: %d)",
                i, d['name'], d['default_samplerate'], d['max_input_channels'])

    # Tenter le device par défaut d'abord
    try:
        default_device = sd.query_devices(kind='input')
        native_rate = int(default_device['default_samplerate'])
        device_index = None
        logger.info("Device par défaut: %s @ %dHz", default_device['name'], native_rate)
    except Exception:
        native_rate = 48000
        device_index = None

    rates_to_try = list(dict.fromkeys([native_rate, 48000, 44100, 16000, 22050]))

    for rate in rates_to_try:
        for blocksize in [2048, 1024, 4096, 512]:
            try:
                stream = sd.InputStream(
                    samplerate=rate,
                    channels=1,
                    dtype='float32',
                    blocksize=blocksize,
                    device=device_index,
                    latency='high',
                )
                stream.start()
                # Test : lire un bloc pour vérifier que le stream est vraiment fonctionnel
                test_data, _ = stream.read(blocksize)
                logger.info("✅ Micro ouvert: %dHz, blocksize=%d, device=%s",
                    rate, blocksize, default_device.get('name', 'default'))
                return stream, rate, blocksize
            except Exception as e:
                logger.debug("Rate %dHz blocksize %d: %s", rate, blocksize, e)
                try:
                    stream.close()
                except:
                    pass
                continue

    raise RuntimeError("Impossible d'ouvrir le microphone avec aucun sample rate/blocksize")


def _calibrate_threshold(stream, blocksize: int, actual_rate: int) -> float:
    """Calibration adaptative du bruit ambiant sur 2 secondes."""
    logger.info("Calibration bruit ambiant (2s)...")
    cal_frames = int(actual_rate / blocksize * 2)
    cal_rms = []

    for _ in range(cal_frames):
        try:
            data, _ = stream.read(blocksize)
            rms = float(np.sqrt(np.mean(data.flatten() ** 2)))
            cal_rms.append(rms)
        except:
            pass

    if not cal_rms:
        return 0.02  # seuil par défaut si calibration échoue

    ambient = float(np.mean(cal_rms))
    ambient_max = float(np.max(cal_rms))

    # Seuil = max(config, ambiant*2.5) — moins agressif que *3.5 précédent
    config_threshold = float(_config.get('silence_threshold', 0.02))
    threshold = max(config_threshold, ambient * 2.5)

    logger.info("Calibration: ambiant_moy=%.4f, ambiant_max=%.4f, seuil=%.4f",
        ambient, ambient_max, threshold)

    if ambient < 0.0001:
        logger.warning("⚠️ Micro silencieux — vérifier Windows > Son > Micro")
        logger.warning("⚠️ Vérifier que le micro n'est pas muté dans le gestionnaire de sons")

    if ambient > 0.1:
        logger.warning("⚠️ Bruit ambiant très élevé (%.4f) — risque de fausses détections", ambient)

    return threshold
```

### FIX 1 — Seuils de timing (MIN_SPEECH et SILENCE_LIMIT)

```python
# Après ouverture du stream et calibration :

# MIN_SPEECH réduit à 0.4s (était 0.8s) — capture les phrases très courtes ("oui", "ok")
MIN_SPEECH_FRAMES = int(actual_rate / blocksize * 0.4)

# SILENCE_LIMIT : 1.5s de silence avant de considérer la phrase terminée
# (était 2.0s — trop long, on perd de la fluidité)
SILENCE_LIMIT_FRAMES = int(actual_rate / blocksize * 1.5)

# MAX_BUFFER_SECONDS : limite de sécurité — évite un buffer infini si silence non détecté
MAX_BUFFER_FRAMES = int(actual_rate / blocksize * 30)  # max 30s

logger.info("Timing: MIN_SPEECH=%.1fs, SILENCE=%.1fs, MAX=30s",
    MIN_SPEECH_FRAMES * blocksize / actual_rate,
    SILENCE_LIMIT_FRAMES * blocksize / actual_rate)
```

### FIX 2 — Resampling robuste avec fallback

```python
def _resample_to_16k(audio: np.ndarray, original_rate: int) -> np.ndarray:
    """Rééchantillonne vers 16000 Hz avec fallback si scipy échoue."""
    if original_rate == 16000:
        return audio.astype(np.float32)

    try:
        # Méthode principale : scipy.signal.resample_poly (filtrage polyphase, meilleure qualité)
        import scipy.signal
        from math import gcd
        g = gcd(16000, original_rate)
        up = 16000 // g
        down = original_rate // g
        resampled = scipy.signal.resample_poly(audio, up, down)
        logger.debug("Resample polyphase %dHz → 16kHz: %d → %d samples",
            original_rate, len(audio), len(resampled))
        return resampled.astype(np.float32)

    except Exception as e:
        logger.warning("scipy.signal.resample_poly échoué (%s), fallback resample FFT", e)
        try:
            import scipy.signal
            target_samples = int(len(audio) * 16000 / original_rate)
            resampled = scipy.signal.resample(audio, target_samples)
            return resampled.astype(np.float32)
        except Exception as e2:
            logger.warning("scipy.signal.resample échoué (%s), fallback numpy", e2)
            # Fallback numpy simple (qualité moindre mais robuste)
            indices = np.round(
                np.arange(0, len(audio), original_rate / 16000)
            ).astype(int)
            indices = indices[indices < len(audio)]
            return audio[indices].astype(np.float32)


def _normalize_audio(audio: np.ndarray) -> np.ndarray:
    """Normalise en float32 entre -1.0 et 1.0."""
    audio = audio.astype(np.float32)
    max_val = np.max(np.abs(audio))
    if max_val > 1e-8:
        audio = audio / max_val * 0.95
    return audio


def _check_audio_quality(audio: np.ndarray, rate: int = 16000) -> tuple[bool, str]:
    """
    Vérifie la qualité du signal avant transcription.
    Retourne (ok: bool, raison: str)
    """
    duration = len(audio) / rate
    rms = float(np.sqrt(np.mean(audio ** 2)))
    max_amp = float(np.max(np.abs(audio)))

    if duration < 0.3:
        return False, f"Trop court ({duration:.2f}s < 0.3s)"
    if rms < 0.0005:
        return False, f"Trop silencieux (RMS={rms:.5f})"
    if max_amp > 0.999:
        return False, f"Signal saturé (max={max_amp:.3f}) — micro trop fort"

    return True, f"OK (durée={duration:.2f}s, RMS={rms:.4f})"
```

### FIX 3 — Transcription Whisper robuste avec retry

```python
def _transcribe(audio_16k: np.ndarray) -> str:
    """
    Transcription Whisper avec :
    - Language forcé en français
    - VAD paramétré finement
    - Retry sans VAD si résultat vide
    - Retry avec température > 0 si toujours vide
    """
    global _whisper_model

    # Vérification qualité avant transcription
    ok, reason = _check_audio_quality(audio_16k)
    if not ok:
        logger.warning("Audio rejeté: %s", reason)
        return ""

    logger.debug("Transcription: durée=%.2fs", len(audio_16k) / 16000)

    # Tentative 1 : configuration optimale
    try:
        segments, info = _whisper_model.transcribe(
            audio_16k,
            language='fr',                    # TOUJOURS forcer le français
            beam_size=5,
            best_of=5,
            temperature=0.0,                   # déterministe
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 300,
                "speech_pad_ms": 400,           # plus de contexte = meilleure transcription
                "threshold": 0.25,              # seuil VAD permissif
                "min_speech_duration_ms": 200,  # accepte les phrases très courtes
            },
            condition_on_previous_text=False,
            no_speech_threshold=0.6,            # tolérant — ne rejette que si vraiment pas de voix
            compression_ratio_threshold=2.4,
            word_timestamps=False,
        )
        text = ' '.join(s.text for s in segments).strip()
        logger.info("Whisper [T1]: lang=%s (%.2f), no_speech=%.2f, texte='%s'",
            info.language, info.language_probability,
            getattr(info, 'no_speech_prob', -1), text)

        if text:
            return _clean_transcription(text)

    except Exception as e:
        logger.error("Erreur transcription T1: %s", e)

    # Tentative 2 : sans VAD (si VAD a filtré trop agressivement)
    logger.warning("T1 vide — retry sans VAD")
    try:
        segments, info = _whisper_model.transcribe(
            audio_16k,
            language='fr',
            beam_size=5,
            temperature=0.0,
            vad_filter=False,
            condition_on_previous_text=False,
            no_speech_threshold=0.8,
        )
        text = ' '.join(s.text for s in segments).strip()
        logger.info("Whisper [T2 sans VAD]: texte='%s'", text)

        if text:
            return _clean_transcription(text)

    except Exception as e:
        logger.error("Erreur transcription T2: %s", e)

    # Tentative 3 : avec température (plus créatif — utile si signal dégradé)
    logger.warning("T2 vide — retry avec température 0.2")
    try:
        segments, info = _whisper_model.transcribe(
            audio_16k,
            language='fr',
            beam_size=3,
            temperature=0.2,
            vad_filter=False,
            condition_on_previous_text=False,
            no_speech_threshold=0.9,
        )
        text = ' '.join(s.text for s in segments).strip()
        logger.info("Whisper [T3 temp=0.2]: texte='%s'", text)

        if text:
            return _clean_transcription(text)

    except Exception as e:
        logger.error("Erreur transcription T3: %s", e)

    logger.warning("Transcription échouée après 3 tentatives")
    return ""


def _clean_transcription(text: str) -> str:
    """Nettoie les artefacts courants de Whisper."""
    import re

    # Supprime les hallucinations courantes de Whisper
    hallucinations = [
        "Merci d'avoir regardé",
        "Merci de votre attention",
        "Sous-titres réalisés par",
        "Sous-titrage",
        "♪",
        "Abonnez-vous",
        "[Musique]",
        "[musique]",
        "(Musique)",
    ]
    for h in hallucinations:
        text = text.replace(h, '').strip()

    # Supprime les répétitions (signe d'hallucination)
    words = text.split()
    if len(words) > 4:
        half = len(words) // 2
        if words[:half] == words[half:half*2]:
            text = ' '.join(words[:half])

    return text.strip()
```

### FIX 4 — Chargement du modèle Whisper optimal pour RTX 5080

```python
def _load_whisper_model():
    """
    Charge faster-whisper avec les paramètres optimaux pour le hardware.
    RTX 5080 16GB VRAM → float16 sur CUDA.
    """
    from faster_whisper import WhisperModel
    import torch

    # Choix du modèle selon config (défaut: "small" — bon compromis vitesse/qualité)
    model_size = _config.get('whisper_model', 'small')

    # Hiérarchie de tentatives : CUDA float16 → CUDA int8 → CPU int8
    configs_to_try = [
        ('cuda', 'float16'),   # optimal RTX 5080
        ('cuda', 'int8_float16'),  # alternative CUDA légère
        ('cuda', 'int8'),      # CUDA avec quantisation int8
        ('cpu',  'int8'),      # fallback CPU
    ]

    for device, compute_type in configs_to_try:
        if device == 'cuda' and not torch.cuda.is_available():
            continue
        try:
            model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
                num_workers=1,
                download_root=_config.get('whisper_model_dir', None),
            )
            # Test rapide pour vérifier que le modèle est fonctionnel
            import numpy as np
            test_audio = np.zeros(16000, dtype=np.float32)  # 1s de silence
            list(model.transcribe(test_audio, language='fr')[0])
            logger.info("✅ Whisper chargé: modèle=%s, device=%s, compute=%s",
                model_size, device, compute_type)
            return model
        except Exception as e:
            logger.warning("Config %s/%s échouée: %s", device, compute_type, e)
            continue

    raise RuntimeError("Impossible de charger le modèle Whisper avec aucune configuration")
```

---

## Partie 3 — Alternatives si faster-whisper ne suffit pas

### Alternative A — openai/whisper (repo officiel PyTorch)

Le zip `whisper-main.zip` contient ce repo. À utiliser si faster-whisper pose des
problèmes persistants (incompatibilité CUDA, modèle corrompu, etc.).

```bash
# Installation depuis le zip téléchargé
cd "chemin\vers\whisper-main"
pip install -e .
# OU depuis PyPI directement
pip install openai-whisper
```

```python
# stt_openai_whisper.py — alternative à stt.py utilisant le package officiel

import whisper
import numpy as np
import torch

def _load_openai_whisper():
    """Charge le modèle Whisper officiel OpenAI."""
    model_size = _config.get('whisper_model', 'small')
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = whisper.load_model(model_size, device=device)
    logger.info("OpenAI Whisper chargé: modèle=%s, device=%s", model_size, device)
    return model

def _transcribe_openai(audio_16k: np.ndarray) -> str:
    """Transcription via le package openai/whisper officiel."""
    # openai/whisper attend un float32 normalisé entre -1 et 1 à 16kHz
    result = _openai_model.transcribe(
        audio_16k,
        language='fr',
        task='transcribe',
        fp16=torch.cuda.is_available(),  # fp16 sur GPU, fp32 sur CPU
        temperature=0.0,
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
        logprob_threshold=-1.0,
        compression_ratio_threshold=2.4,
    )
    text = result.get('text', '').strip()
    logger.info("OpenAI Whisper: texte='%s'", text)
    return text
```

**Différences pratiques faster-whisper vs openai/whisper :**

| Critère | faster-whisper | openai/whisper |
|---|---|---|
| Vitesse | 2-4x plus rapide | Référence |
| VRAM | Moins (CTranslate2) | Plus |
| API | `WhisperModel.transcribe()` iterator | `model.transcribe()` dict |
| VAD intégré | ✅ Oui | ❌ Non (manuel) |
| Streaming | ✅ Oui (segments) | ❌ Non |
| Modèles dispo | Mêmes + large-v3-turbo | Mêmes |
| Précision français | Identique | Identique |

**Recommandation** : rester sur faster-whisper. Utiliser openai/whisper uniquement si
faster-whisper a des problèmes irréductibles de compatibilité CUDA.

### Alternative B — Whisper.cpp (via ctransformers ou subprocess)

Plus rapide encore, tourne directement sur CPU ou GPU via GGML/GGUF.

```bash
pip install pywhispercpp
# OU cloner et compiler :
# git clone https://github.com/ggerganov/whisper.cpp
```

```python
# Si pywhispercpp installé :
from pywhispercpp.model import Model

_whisper_cpp_model = Model('small', n_threads=4)

def _transcribe_cpp(audio_16k: np.ndarray) -> str:
    segments = _whisper_cpp_model.transcribe(audio_16k, language='fr')
    return ' '.join(s.text for s in segments).strip()
```

Utile si VRAM saturée par Ollama + vision + Whisper simultanément.

### Alternative C — SpeechRecognition + Google Speech (fallback cloud)

Uniquement comme dernier recours si tout le reste échoue — nécessite internet.

```python
import speech_recognition as sr

def _transcribe_google_fallback(audio_np: np.ndarray, rate: int) -> str:
    """Fallback cloud Google Speech — uniquement si Whisper local indisponible."""
    import io, wave
    r = sr.Recognizer()

    # Convertir numpy array en WAV bytes
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(rate)
        audio_int16 = (audio_np * 32767).astype(np.int16)
        wf.writeframes(audio_int16.tobytes())
    buffer.seek(0)

    with sr.AudioFile(buffer) as source:
        audio = r.record(source)
    try:
        return r.recognize_google(audio, language='fr-FR')
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as e:
        logger.error("Google Speech API erreur: %s", e)
        return ""
```

### Alternative D — Système de routing STT configurable

Permettre de choisir le backend STT dans config.yaml :

```yaml
stt:
  backend: "faster_whisper"  # options: faster_whisper | openai_whisper | whisper_cpp | google
  model: "small"             # tiny | base | small | medium | large-v3
  language: "fr"
  device: "auto"             # auto | cuda | cpu
```

```python
# stt.py — routing selon config

def _get_transcriber():
    backend = _config.get('stt', {}).get('backend', 'faster_whisper')
    if backend == 'faster_whisper':
        return _transcribe  # fonction actuelle
    elif backend == 'openai_whisper':
        return _transcribe_openai
    elif backend == 'whisper_cpp':
        return _transcribe_cpp
    elif backend == 'google':
        return _transcribe_google_fallback
    else:
        logger.warning("Backend STT inconnu '%s', fallback faster_whisper", backend)
        return _transcribe

TRANSCRIBE_FN = _get_transcriber()
```

---

## Partie 4 — Réglages Windows qui causent des problèmes micro

### 4.1 Problèmes Windows courants

| Problème | Symptôme dans les logs | Solution |
|---|---|---|
| Micro muté | `ambient < 0.0001`, RMS=0 | Paramètres son → Enregistrement → Désourdiner |
| Volume micro trop faible | RMS très bas mais non nul, transcription vide | Paramètres son → Niveaux micro → Monter à 80+ |
| Amélioration du son activée | Transcriptions chaotiques, mots coupés | Paramètres son → Avancé → Décocher toutes les améliorations |
| Format audio incompatible | PaErrorCode -9997 | Paramètres son → Format → 16 bits, 44100 Hz ou 48000 Hz |
| Plusieurs applis qui capturent | PortAudio ne peut pas ouvrir le stream | Fermer Discord, Teams, OBS pendant ARIA |
| Device index incorrect | Mauvais micro sélectionné | Log des devices au démarrage → vérifier le bon index |

### 4.2 Script de diagnostic Windows (à lancer depuis Python)

```python
# scripts/diagnose_mic.py — lance avant de déboguer stt.py
"""
Script de diagnostic micro indépendant d'ARIA.
Lance-le pour identifier les problèmes Windows/device avant de toucher stt.py.
"""
import sounddevice as sd
import numpy as np
import time

print("=== Diagnostic micro ARIA ===\n")

# 1. Lister tous les devices
print("Devices audio disponibles:")
devices = sd.query_devices()
for i, d in enumerate(devices):
    if d['max_input_channels'] > 0:
        mark = "← DÉFAUT" if i == sd.default.device[0] else ""
        print(f"  [{i}] {d['name']} | native: {d['default_samplerate']:.0f}Hz | "
              f"ch: {d['max_input_channels']} {mark}")

print()

# 2. Tester le device par défaut avec différents sample rates
print("Test de capture sur le device par défaut:")
for rate in [48000, 44100, 16000]:
    try:
        with sd.InputStream(samplerate=rate, channels=1, dtype='float32', blocksize=1024) as s:
            data, _ = s.read(1024)
            rms = float(np.sqrt(np.mean(data.flatten() ** 2)))
            print(f"  {rate}Hz → ✅ OK (RMS={rms:.4f})")
    except Exception as e:
        print(f"  {rate}Hz → ❌ {e}")

print()

# 3. Enregistrer 3 secondes et mesurer le niveau
print("Enregistrement 3 secondes — parle dans le micro...")
try:
    RATE = 44100
    with sd.InputStream(samplerate=RATE, channels=1, dtype='float32', blocksize=1024) as s:
        frames = []
        for _ in range(int(RATE / 1024 * 3)):
            data, _ = s.read(1024)
            frames.append(data.flatten())
            rms = float(np.sqrt(np.mean(data.flatten() ** 2)))
            bar = '█' * int(rms * 500)
            print(f"\r  Niveau: {bar:<40} RMS={rms:.4f}", end='', flush=True)
        print()

    audio = np.concatenate(frames)
    rms_total = float(np.sqrt(np.mean(audio ** 2)))
    peak = float(np.max(np.abs(audio)))
    print(f"\nRMS total: {rms_total:.4f} | Peak: {peak:.4f}")

    if rms_total < 0.001:
        print("⚠️ PROBLÈME: Signal trop faible — micro muté ou volume trop bas")
        print("   Action: Paramètres Son → Enregistrement → Niveaux → Monter à 80+")
    elif rms_total > 0.3:
        print("⚠️ ATTENTION: Signal très fort — risque de saturation")
        print("   Action: Paramètres Son → Enregistrement → Niveaux → Baisser")
    else:
        print("✅ Niveau correct")

except Exception as e:
    print(f"❌ Impossible d'enregistrer: {e}")

print("\n=== Fin du diagnostic ===")
```

### 4.3 Activer les logs détaillés sans relancer ARIA

Ajouter dans config.yaml :
```yaml
stt_debug: true  # active les logs diagnostics détaillés dans stt.py
```

---

## Partie 5 — Boucle STT complète réécrite et robuste

Version finale de `_record_loop()` intégrant tous les fixes :

```python
def _record_loop():
    """
    Boucle d'enregistrement principale — robuste, avec diagnostic complet.
    Incorpore : multi-sample-rate, resampling polyphase, transcription 3 tentatives,
    calibration adaptative, détection qualité audio, logs diagnostics.
    """
    stream = None
    actual_rate = 16000
    blocksize = 1024

    try:
        stream, actual_rate, blocksize = _open_mic_stream()

        THRESHOLD = _calibrate_threshold(stream, blocksize, actual_rate)

        MIN_SPEECH = int(actual_rate / blocksize * 0.4)    # 0.4s minimum
        SILENCE_LIMIT = int(actual_rate / blocksize * 1.5) # 1.5s de silence
        MAX_BUFFER = int(actual_rate / blocksize * 30)      # 30s maximum

        logger.info("STT prêt: rate=%dHz, seuil=%.4f, min_speech=%.1fs",
            actual_rate, THRESHOLD,
            MIN_SPEECH * blocksize / actual_rate)

        ui.set_status('listening')
        ui.show_toast("Micro actif", toast_type="info")

        buffer = []
        silence_frames = 0
        speaking = False
        frame_count = 0

        while not _stop_event.is_set():
            try:
                data, overflowed = stream.read(blocksize)
                if overflowed:
                    logger.debug("Overflow micro — blocksize peut-être trop petit")
            except Exception as e:
                logger.warning("Erreur lecture stream: %s — reconnexion dans 1s", e)
                import time; time.sleep(1)
                continue

            flat = data.flatten()
            rms = float(np.sqrt(np.mean(flat ** 2)))

            # Mise à jour waveform UI toutes les 4 frames
            if frame_count % 4 == 0:
                try:
                    ui.update_waveform(rms)
                except:
                    pass
            frame_count += 1

            if rms > THRESHOLD:
                if not speaking:
                    logger.debug("🎤 Début parole détecté (RMS=%.4f > seuil=%.4f)", rms, THRESHOLD)
                speaking = True
                silence_frames = 0
                buffer.append(flat.copy())

                if len(buffer) > MAX_BUFFER:
                    logger.warning("Buffer trop long (>30s), transcription forcée")
                    # Force la transcription même sans silence
                    silence_frames = SILENCE_LIMIT

            elif speaking:
                silence_frames += 1
                buffer.append(flat.copy())

                if silence_frames >= SILENCE_LIMIT:
                    logger.debug("🔇 Fin de parole (%.1fs de silence)",
                        silence_frames * blocksize / actual_rate)

                    if len(buffer) >= MIN_SPEECH:
                        # Pipeline de transcription
                        audio_np = np.concatenate(buffer).astype(np.float32)
                        audio_np = _normalize_audio(audio_np)
                        audio_16k = _resample_to_16k(audio_np, actual_rate)

                        ui.set_status('transcribing')

                        text = _transcribe(audio_16k)

                        if text:
                            logger.info("✅ Transcription: '%s'", text)
                            safe = (text
                                .replace('\\', '\\\\')
                                .replace('"', '\\"')
                                .replace('\n', ' ')
                                .replace("'", "\\'"))
                            try:
                                import ui as _ui
                                if _ui._instance:
                                    _ui._instance._js(
                                        f'document.getElementById("text-input").value="{safe}";'
                                        f'document.getElementById("text-input")'
                                        f'.dispatchEvent(new Event("input"));'
                                        f'document.getElementById("text-input").focus();'
                                    )
                            except Exception as e:
                                logger.error("Erreur injection texte UI: %s", e)
                        else:
                            logger.warning("❌ Transcription vide après 3 tentatives")
                            ui.show_toast("Parole non comprise — réessaie", toast_type="info")
                    else:
                        logger.debug("Buffer trop court (%d frames < min %d) — ignoré",
                            len(buffer), MIN_SPEECH)

                    # Reset
                    buffer = []
                    speaking = False
                    silence_frames = 0
                    ui.set_status('listening')

    except Exception as e:
        logger.error("Erreur fatale _record_loop: %s", e, exc_info=True)
        ui.show_toast(f"Erreur micro: {e}", toast_type="error")
    finally:
        if stream:
            try:
                stream.stop()
                stream.close()
                logger.info("Stream micro fermé proprement")
            except:
                pass
        ui.set_status('idle')
```

---

## Partie 6 — Modèles Whisper recommandés selon le contexte

| Modèle | VRAM | Vitesse | Qualité FR | Recommandé pour |
|---|---|---|---|---|
| tiny | ~150 Mo | Très rapide | Passable | Mode temps réel (fenêtres glissantes) |
| base | ~300 Mo | Rapide | Bonne | Mode temps réel amélioré |
| small | ~500 Mo | Bon | Très bonne | **Usage quotidien ARIA** ← recommandé |
| medium | ~1.5 Go | Moyen | Excellente | Discussions longues, accent fort |
| large-v3 | ~3 Go | Lent | Parfaite | Enregistrements importants, transcription de cours |
| large-v3-turbo | ~1.6 Go | Rapide | Excellente | Meilleur rapport qualité/vitesse si VRAM dispo |

Sur RTX 5080 (16GB VRAM) avec Ollama qui tourne en parallèle :
- Ollama utilise ~8-10 Go pour qwen3:14b
- Whisper small : ~500 Mo → aucun problème
- Whisper large-v3-turbo : ~1.6 Go → encore OK
- **Ne pas dépasser large-v3 (3 Go) si qwen3:14b est chargé simultanément**

---

## Prompt Cursor (complet)

> Réécris stt.py pour corriger définitivement les problèmes de transcription qui
> retournent un résultat vide. Le micro détecte la parole (RMS au-dessus du seuil)
> mais Whisper ne transcrit rien.
>
> Applique TOUTES les corrections suivantes dans l'ordre :
>
> **1. `_open_mic_stream()`** : liste tous les devices input au démarrage (log INFO),
> essaie les rates dans l'ordre [native, 48000, 44100, 16000, 22050] × blocksizes
> [2048, 1024, 4096, 512], fait un `stream.read(blocksize)` de test après ouverture pour
> valider que le stream est vraiment fonctionnel, log ✅ avec device name/rate/blocksize.
>
> **2. `_calibrate_threshold(stream, blocksize, actual_rate)`** : capture 2s de bruit
> ambiant, seuil = max(config_threshold, ambient * 2.5) (réduit de 3.5 à 2.5),
> log détaillé (ambiant_moy, ambiant_max, seuil final), warn si ambiant < 0.0001
> (micro silencieux) ou > 0.1 (bruit fort).
>
> **3. Seuils timing** : `MIN_SPEECH = 0.4s` (réduit de 0.8), `SILENCE_LIMIT = 1.5s`
> (réduit de 2.0), `MAX_BUFFER = 30s` (nouveau — sécurité).
>
> **4. `_resample_to_16k(audio, original_rate)`** : utilise `scipy.signal.resample_poly`
> en principal (meilleure qualité, moins d'artefacts), fallback vers
> `scipy.signal.resample` puis numpy simple si scipy échoue. Log DEBUG avec shapes.
>
> **5. `_normalize_audio(audio)`** : normalise float32 entre -0.95 et 0.95 (évite
> saturation numérique). `_check_audio_quality(audio, rate=16000)` → (bool, str) :
> rejette si durée < 0.3s, RMS < 0.0005, ou max_amp > 0.999.
>
> **6. `_transcribe(audio_16k)`** : 3 tentatives dans l'ordre :
> - T1 : `language='fr', beam_size=5, temperature=0.0, vad_filter=True` avec
>   `vad_parameters={'min_silence_duration_ms':300, 'speech_pad_ms':400, 'threshold':0.25,
>   'min_speech_duration_ms':200}`, `no_speech_threshold=0.6`
> - T2 (si T1 vide) : mêmes params mais `vad_filter=False`
> - T3 (si T2 vide) : `temperature=0.2, vad_filter=False, no_speech_threshold=0.9`
> - Log INFO du résultat de chaque tentative (lang, probability, texte)
>
> **7. `_clean_transcription(text)`** : supprime les hallucinations courantes de Whisper
> (liste définie dans la spec), supprime les répétitions de séquences.
>
> **8. `_load_whisper_model()`** : essaie dans l'ordre cuda/float16 → cuda/int8_float16 →
> cuda/int8 → cpu/int8. Fait un test de transcription sur 1s de silence pour valider.
> Log ✅ avec modèle/device/compute_type.
>
> **9. `_record_loop()`** : intègre tous les éléments ci-dessus. Ajoute :
> - Log DEBUG au début de chaque parole détectée (RMS vs seuil)
> - Log DEBUG fin de parole (durée silence)
> - Toast "Parole non comprise — réessaie" si transcription vide après 3 tentatives
> - Reconnexion automatique si `stream.read()` lève une exception (sleep 1s + continue)
> - Reset correct du buffer même en cas d'exception dans le pipeline de transcription
>
> **10. `config.yaml`** : ajoute si absent :
> ```yaml
> stt:
>   backend: "faster_whisper"
>   model: "small"
>   language: "fr"
> ```
>
> **11. Crée `scripts/diagnose_mic.py`** : script standalone (sans dépendances ARIA)
> qui liste les devices, teste chaque sample rate, enregistre 3s avec vumètre en temps
> réel, et affiche un diagnostic lisible.
>
> Ne pas toucher aux autres fichiers. Modifie uniquement stt.py, config.yaml.
> Crée scripts/diagnose_mic.py.
