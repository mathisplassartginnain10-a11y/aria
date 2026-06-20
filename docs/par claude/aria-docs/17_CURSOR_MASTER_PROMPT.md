# 17 — Cursor Master Prompt

## Instructions pour Cursor

Tu construis ARIA — un assistant IA personnel local qui tourne sur Electron + Python.

**Règles absolues :**
1. Consulte TOUJOURS les fichiers dans `/docs/` avant de modifier quoi que ce soit
2. Le design visuel est défini dans `01_UI_BIBLE.md` et `02_DESIGN_SYSTEM.md` — ne t'en écarte JAMAIS
3. L'orbe ARIA est défini pixel-perfect dans `03_ANIMATION_SYSTEM.md` — reproduis-le exactement
4. L'architecture Electron est dans `04_ELECTRON_ARCHITECTURE.md`
5. Le backend Python est dans `05_PYTHON_BACKEND.md`

**Stack :**
- Frontend: Electron 31 + HTML/CSS/JS vanilla (PAS de React/Vue)
- Backend: Python 3.13 + asyncio WebSocket (websockets lib)
- LLM: llama.cpp (llama-server.exe) avec fallback Ollama
- STT: faster-whisper + PyAudio
- TTS: edge-tts + pygame

**Chemins du projet :**
```
c:\Users\mathi\OneDrive\Documents\assistant-ia\assistant-vocal\
├── electron/
│   ├── main.js
│   ├── preload.js
│   ├── package.json
│   ├── assets/ (icon.png, icon.ico, tray-icon.png)
│   └── renderer/
│       ├── index.html
│       ├── app.js
│       └── styles.css
└── python/
    ├── main.py
    ├── ui_bridge.py
    ├── llm.py
    ├── stt.py
    ├── tts.py
    ├── memory_engine.py
    ├── llamacpp_manager.py
    ├── app_paths.py
    ├── config.yaml
    └── actions/
```

**Pour chaque sprint, procéder dans cet ordre :**
1. Lire les docs concernés
2. Modifier uniquement les fichiers listés dans la spec
3. Ne pas casser les features existantes
4. Tester mentalement le rendu avant de valider

## Sprint plan

### Sprint 1 — UI Layout 3 colonnes (index.html + styles.css)
Implémenter le layout exact du mockup (voir 01_UI_BIBLE.md)

### Sprint 2 — Orbe ARIA animé (app.js + styles.css)
Implémenter l'orbe avec tous ses états (voir 03_ANIMATION_SYSTEM.md)

### Sprint 3 — Navigation multi-pages (app.js)
navigate() + pages Home/Conversations/Mémoire/Agents/Paramètres

### Sprint 4 — Widgets temps réel (ui_bridge.py + app.js)
Météo wttr.in, mémoire stats, raccourcis depuis presets

### Sprint 5 — Chat conversation (app.js + ui_bridge.py)
Messages, streaming tokens, shrink de l'orbe au démarrage

### Sprint 6 — Paramètres complets (app.js + styles.css)
Tous les accordéons avec animations de validation

### Sprint 7 — Micro & STT (stt.py + app.js)
Pipeline complet, bouton micro animé, countdown vocal

### Sprint 8 — LLM + llama.cpp (llm.py + llamacpp_manager.py)
Routage, streaming, fallback Ollama, fast intent

### Sprint 9 — Agents IA (actions/agents.py + app.js)
Modal éditeur, git context, sélecteur rapide dans header

### Sprint 10 — Clés API (actions/api_keys.py + app.js)
5 providers, test, sauvegarde obfusquée

### Sprint 11 — Recherche web (actions/web_research.py + llm.py)
DDG + Wikipedia + YouTube, synthèse LLM, écriture Google Docs

### Sprint 12 — Animations paramètres (app.js)
11 animations de validation (AnimationController)

### Sprint 13 — Présets personnalisables (actions/presets.py + app.js)
Nom, icône, volume, apps

### Sprint 14 — Lancement Windows (launch_aria.bat + scripts/)
Raccourci menu Démarrer, icône ARIA

### Sprint 15 — Polish & Performance
Micro-animations, sons, 60fps check, encodage UTF-8
