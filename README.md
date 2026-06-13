# ARIA — Assistant Vocal Local

Assistant vocal personnel 100% local pour Windows 11.

## Installation

1. Cloner le repo
2. Copier `config.example.yaml` en `config.yaml` et remplir les champs
3. Double-cliquer sur `install.bat`
4. Accepter l'UAC
5. Attendre la fin de l'installation
6. Appuyer sur F24 (touche Copilot remappée via PowerToys)

## Prérequis

- Windows 11
- Python 3.13+
- Ollama installé avec les modèles : llama3.1:8b-instruct-q8_0, qwen3:14b, qwen2.5-coder:14b, minicpm-v
- PowerToys pour remapper la touche Copilot → F24

## Stack

- STT : faster-whisper (CUDA)
- LLM : Ollama local
- TTS : edge-tts
- UI : pywebview + HTML/CSS/JS

## Serveur mobile

Pour contrôler ARIA depuis ton téléphone (même WiFi) :

```bash
start_mobile.bat
# ou
.venv\Scripts\python.exe aria_mobile_server.py
```

PIN et port configurables dans `config.yaml` :
```yaml
mobile_port: 5000
mobile_pin: "0000"
```

Connecte-toi à l'URL affichée avec le code PIN par défaut `0000`.

L'app mobile peut **scanner le réseau local** pour trouver automatiquement le PC (bouton sur l'écran de connexion).

Endpoints optimisés mobile :
- `POST /ask/fast` — réponses courtes (cache + modèle rapide)
- `POST /ask/stream` — streaming token par token
- `POST /transcribe` — transcription vocale (Whisper sur le PC)
- `POST /warmup` — pré-charge le modèle Ollama

## Application Android (APK)

L'app mobile Expo se trouve dans `aria-mobile/`.

```bash
# Install EAS CLI
npm install -g eas-cli

# Login to Expo
eas login

# Configure build
cd aria-mobile
npm install
eas build:configure

# Cloud (compte Expo)
cd aria-mobile && npm run build:apk
# ou : aria-mobile\build-apk.bat

# Local (Android Studio)
npx expo run:android
```

Prérequis : Node.js 18+, Android Studio pour build local.
Lance `aria_mobile_server.py` sur le PC avant de connecter l'app.
