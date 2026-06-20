# 05 — Python Backend

## Stack

```
Python 3.13 (.venv)
├── ui_bridge.py         — serveur WebSocket asyncio (port dynamique 9999+)
├── main.py              — point d'entrée, démarre tous les services
├── llm.py               — routage LLM (llama.cpp + Ollama fallback + APIs)
├── stt.py               — STT (faster-whisper + PyAudio)
├── tts.py               — TTS (edge-tts + pygame)
├── memory_engine.py     — mémoire persistante (JSON)
├── llamacpp_manager.py  — gestion llama-server.exe
├── app_paths.py         — chemins absolus (compatible PyInstaller)
├── config.yaml          — configuration principale
└── actions/
    ├── apps.py          — lancer/fermer applications
    ├── browser.py       — Chrome, YouTube, recherche web
    ├── weather.py       — météo (OpenWeatherMap + wttr.in fallback)
    ├── web_research.py  — recherche multi-sources (DDG + Wikipedia + YouTube)
    ├── gdocs.py         — Google Docs (créer, écrire)
    ├── agents.py        — agents IA personnalisables
    ├── api_keys.py      — gestion clés API externes
    └── presets.py       — modes (vol, étude, gaming, nuit...)
```

## Démarrage (main.py)

```python
# Ordre de démarrage
1. ui_bridge.start()              # WebSocket serveur
2. _start_static_file_server()    # HTTP pour wallpapers (port 9998)
3. memory_engine.load_memory()    # Charger la mémoire
4. ollama/llamacpp check          # Vérifier le moteur LLM
5. threading.Thread(stt._load_whisper_model)  # Whisper en background
6. keyboard hooks (F24, Ctrl+Shift+A)
```

## WebSocket (ui_bridge.py)

Port : dynamique (9999, 10000, 10001...)
Protocole : JSON bidirectionnel
Fonctions exposées via `@expose` decorator

### Fonctions exposées principales
```python
@expose def ask(text, conv_mode, request_id)       → str (stream)
@expose def start_mic() / stop_mic()               → dict
@expose def get_conversations()                    → list
@expose def new_conversation()                     → dict
@expose def load_conversation(conv_id)             → dict
@expose def delete_conversation(conv_id)           → dict
@expose def get_available_models()                 → dict
@expose def set_model(role, model_name)            → dict
@expose def save_wallpaper(b64, filename)          → dict
@expose def get_wallpapers()                       → list
@expose def get_weather_widget()                   → dict
@expose def get_memory_stats()                     → dict
@expose def get_presets()                          → list
@expose def get_settings() / save_settings(dict)  → dict
@expose def get_api_keys_status()                  → dict
@expose def save_api_key(provider, key, model)     → dict
@expose def test_api_key(provider)                 → dict
@expose def get_agents()                           → list
@expose def create_agent(data_json)                → dict
@expose def update_agent(agent_id, data_json)      → dict
@expose def delete_agent(agent_id)                 → dict
@expose def set_active_agent(agent_id)             → dict
@expose def shutdown()                             → None
```

## LLM Routing (llm.py)

```
Texte utilisateur
    ↓
Fast intent (regex, 0ms)
    ↓ si action système
Execute directement (lancer app, météo, etc.)
    ↓ sinon
detect_intent() via llama3.2:1b (1B, ultra-rapide)
    ↓
_select_provider() → local ou API externe ?
    ↓
generate() → llama.cpp OU Ollama fallback OU API externe
    ↓
Streaming tokens → ui_bridge.emit_stream_token()
```

### Modèles
```yaml
models:
  intent: "llama3.2:1b"              # classification rapide
  fast:   "llama3.1:8b-instruct-q8_0" # conversation
  heavy:  "qwen3:14b"                 # analyse, maths
  vision: "minicpm-v:latest"          # images
```

## STT Pipeline (stt.py)

```
PyAudio (device Intel Smart Sound, index auto)
    ↓
RMS threshold (calibration 2s au démarrage)
    ↓
Buffer audio (float32, 44100Hz)
    ↓
Détection silence (1.5s)
    ↓
Resampling 44100 → 16000 Hz (scipy.signal.resample_poly)
    ↓
faster-whisper (small, fr, int8, CPU)
    ↓
_clean_transcription() (filtre hallucinations)
    ↓
ui_bridge.show_final_transcription(text)
```

## Config.yaml structure

```yaml
llamacpp:
  server_path: "C:\\llama.cpp\\llama-server.exe"
  n_gpu_layers: 99
  ctx_size: 4096
  threads: 8
  base_port: 8080

models:
  intent: "llama3.2:1b"
  fast: "llama3.1:8b-instruct-q8_0"
  heavy: "qwen3:14b"
  vision: "minicpm-v:latest"

stt:
  backend: "faster_whisper"
  model: "small"
  language: "fr"
  device_index: null

weather:
  city: "Couëron"
  api_key: ""  # optionnel, wttr.in utilisé si vide

api_keys:
  openai:    { key: "", enabled: false, default_model: "gpt-4o-mini" }
  anthropic: { key: "", enabled: false, default_model: "claude-sonnet-4-6" }
  mistral:   { key: "", enabled: false, default_model: "mistral-small-latest" }
  groq:      { key: "", enabled: false, default_model: "llama-3.1-8b-instant" }
  gemini:    { key: "", enabled: false, default_model: "gemini-2.0-flash" }

presets:
  vol:     { name: "Vol",     icon: "✈️", volume: 80 }
  etude:   { name: "Étude",   icon: "📚", volume: 30 }
  gaming:  { name: "Gaming",  icon: "🎮", volume: 70 }
  detente: { name: "Détente", icon: "🎵", volume: 50 }
  nuit:    { name: "Nuit",    icon: "🌙", volume: 20 }

agents:
  default:
    id: "default"
    name: "ARIA"
    icon: "🤖"
    color: "#6C8EFF"
    model: "llama3.1:8b-instruct-q8_0"
    system_prompt: ""
    rules: []
    git_repos: []

user_firstname: "Mathis"
hello_text: ""
sub_text: ""
kill_ollama_on_exit: true
```
