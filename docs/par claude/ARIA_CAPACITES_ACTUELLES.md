# ARIA — Capacités actuelles complètes
*Document de référence — État au 21 juin 2026*

---

## Architecture technique

```
Electron 31 (UI) ↔ WebSocket ↔ Python 3.13 (Backend)
                                    ├── llama.cpp (LLM local)
                                    ├── faster-whisper (STT)
                                    ├── edge-tts (TTS)
                                    └── mémoire JSON persistante
```

**Matériel cible** : MSI laptop, RTX 5080 16GB VRAM, Intel Core Ultra 9 275HX, 32GB DDR5

---

## 1. INTERFACE UTILISATEUR

### Layout 3 colonnes
- Sidebar gauche (230px) : navigation, logo ARIA animé, agent actif
- Zone centrale : orbe ARIA holographique, chat, input zone
- Widgets droite (265px) : résumé du jour, mémoire, raccourcis

### Orbe ARIA
- 5 anneaux animés concentriques (bleu + violet)
- 2 scan lines rotatifs (conic-gradient)
- Crosshair lumineux
- 4 états visuels : idle / listening / thinking / speaking
- Logo ARIA réel dans le noyau

### Liquid Glass
- `backdrop-filter: blur(55px) saturate(185%)`
- Bords arrondis `border-radius: 38px`
- Reflet lumineux en haut
- Fond bleu nuit `#04080F` avec radial gradients

### Pages disponibles
- Accueil (orbe + chat)
- Conversations (liste complète)
- Mémoire
- Agents IA
- Routines
- Paramètres

### Personnalisation UI
- 5 thèmes : Slate, Warm, Forest, Rose, Mono
- Slider de transparence Liquid Glass
- 6 fonds d'écran presets (Aurora, Sunset, Midnight, Forest, Mesh, Mono)
- Import de wallpaper personnalisé (image locale)
- Salutation personnalisable (prénom, texte, sous-texte)

### Animations paramètres
- 11 animations de validation (thème, glass, wallpaper, TTS, modèle, etc.)
- `AnimationController` — toutes passables avec Échap ou clic

---

## 2. CONVERSATION & LLM

### Modes de conversation
- Mode écrit (texte)
- Mode vocal (STT → LLM → TTS)
- Sélection par conversation

### Streaming
- Tokens LLM affichés en temps réel lettre par lettre
- Curseur clignotant pendant la génération
- **Bouton "⏹ Arrêter la génération"** apparu pendant le streaming

### Multi-messages
- Plusieurs échanges dans une même conversation
- Historique conservé et envoyé au LLM (10 derniers messages)
- Input réactivé après chaque réponse

### Gestion des conversations
- Créer / charger / supprimer une conversation
- Supprimer toutes les conversations
- Rester sur la page sans redirection après suppression
- Titres automatiques

---

## 3. MODÈLES IA

### Moteur principal : llama.cpp
- `llama-server.exe` dans `C:\llama.cpp\`
- GPU : `--n-gpu-layers 99` (tout sur RTX 5080)
- Un serveur par modèle, ports dynamiques (8080, 8081...)
- Fallback automatique vers Ollama si llama-server absent

### Modèles configurés
| Rôle | Modèle | Usage |
|------|--------|-------|
| Intent | llama3.2:1b | Classification rapide (0ms) |
| Fast | llama3.1:8b-instruct-q8_0 | Conversation quotidienne |
| Heavy | qwen3:14b | Maths, analyse, raisonnement |
| Vision | minicpm-v:latest | Images, photos |

### APIs externes supportées
- OpenAI (gpt-4o, gpt-4o-mini)
- Anthropic (claude-sonnet-4-6, claude-haiku)
- Mistral (mistral-small, mistral-large)
- Groq (llama-3.1-8b-instant, ultra-rapide)
- Google Gemini (gemini-2.0-flash)
- Clés stockées obfusquées localement
- Test de clé en 1 clic
- Fallback automatique si llama.cpp absent

### Sélection intelligente du modèle
- Actions simples → 1B (ultra-rapide)
- Mode vocal → fast uniquement
- Analyse/maths → heavy
- Jamais le gros modèle en mode vocal

---

## 4. VOIX (STT + TTS)

### STT — Reconnaissance vocale
- **faster-whisper** modèle `small`, français, int8
- **PyAudio** comme backend (plus stable que sounddevice)
- Sélection automatique du device Intel Smart Sound
- Calibration bruit ambiant au démarrage (2s)
- Seuil RMS adaptatif (×2.5 ambiant)
- 3 tentatives de transcription (T1 VAD, T2 sans VAD, T3 temp=0.2)
- Logs bruts avant/après `_clean_transcription()`

### TTS — Synthèse vocale
- **edge-tts** (fr-FR-DeniseNeural)
- **pygame** pour la lecture audio
- Vitesse réglable (-50% à +50%)
- Activation/désactivation par session

### Contrôle micro
- **F24** (touche Copilot remappée via PowerToys)
- **Ctrl+Shift+A** (raccourci test)
- Bouton micro dans l'UI (bascule ON/OFF)
- Le micro NE démarre PAS automatiquement au lancement
- Countdown vocal 1.5s après transcription (annulable si on modifie le texte)

---

## 5. ACTIONS SYSTÈME

### Lancer des applications
- Scan registre Windows (HKLM + HKCU + WOW6432Node)
- Scan menu Démarrer (.lnk)
- 458 apps indexées
- Intent détecté par regex PUIS par LLM

### Actions disponibles
- `lancer_app` — ouvrir une application
- `fermer_app` — fermer une application
- `volume` — régler le volume système
- `meteo` — météo OpenWeatherMap + wttr.in fallback
- `heure_date` — heure et date actuelles
- `minuteur` — démarrer un timer
- `search_web` — recherche Google
- `browser_youtube_search` — recherche YouTube
- `browser_open_site` — ouvrir un site web
- `preset` — activer un mode (vol, étude, gaming, nuit...)
- `aviation_metar` / `aviation_taf` — données météo aviation

### Presets (modes)
Chaque preset est personnalisable :
- **Nom** + **Icône emoji** (sélecteur graphique)
- Volume associé
- Apps à ouvrir / fermer
- 5 presets par défaut : ✈️ Vol, 📚 Étude, 🎮 Gaming, 🎵 Détente, 🌙 Nuit

---

## 6. RECHERCHE WEB

### Sources
- **DuckDuckGo** (`ddgs`) — recherche générale
- **DuckDuckGo News** — actualités (timelimit: semaine)
- **Wikipedia API** — résumés gratuits sans clé
- **YouTube via DDG** — `site:youtube.com`

### Fonctionnement
- Recherche parallèle multi-sources (`ThreadPoolExecutor`)
- Synthèse via LLM (heavy) → réponse naturelle en français
- Format chat (synthèse courte) ou format doc (structuré pour Google Docs)

### Intents de recherche
- `recherche_web` — recherche générale
- `recherche_actualites` — news de la semaine
- `recherche_wikipedia` — encyclopédie
- `recherche_multi` — toutes sources simultanément
- `browser_youtube_search` — vidéos YouTube

---

## 7. GOOGLE DOCS

### Fonctionnalités
- Créer un nouveau Google Doc avec titre personnalisé
- Définir un Doc "actif" de session
- Ajouter du contenu à la fin d'un Doc existant
- Écrire une section avec titre formaté (H1/H2/H3)
- Ouvrir le Doc dans Chrome automatiquement

### Workflow recherche → Doc
```
"crée un doc 'Veille IA'"
  → Doc créé + ouvert dans Chrome

"cherche les actus IA et note dans le doc"
  → Recherche DDG + Wikipedia
  → Résultats écrits dans le Doc actif avec titre H2
```

### Intents Google Docs
- `gdoc_create` — créer un doc
- `gdoc_write_search` — écrire résultats recherche dans le doc
- `gdoc_open` — ouvrir le doc actif dans Chrome
- `gdoc_status` — afficher le doc actif

---

## 8. AGENTS IA PERSONNALISABLES

### Caractéristiques d'un agent
- **Nom** personnalisé
- **Icône** emoji (sélecteur 40 emojis)
- **Couleur** (12 pastilles)
- **Modèle local** choisi parmi ceux installés
- **System prompt** personnalisé
- **Règles** supplémentaires (liste de contraintes)
- **Repos Git** associés (contexte code auto-injecté)

### Contexte Git
- Lit les fichiers récemment modifiés (dernière semaine)
- Injecte le dernier commit dans le system prompt
- Supporte plusieurs repos simultanément

### Interface
- Modal éditeur 3 colonnes (Identité / Comportement / Git)
- Sélecteur rapide dans le header du chat
- Dropdown agent dans la zone d'input
- Badge compteur d'agents dans les paramètres

### Agent par défaut
- **ARIA** (id: default, modèle: llama3.1:8b-instruct-q8_0)
- Ne peut pas être supprimé

---

## 9. MÉMOIRE

### Stockage
- JSON persistant (`data/memory.json`)
- Auto-save toutes les 60s
- 8 sessions, 40 conversations, 147 messages (état actuel)

### Structure
- Sessions (regroupement temporel)
- Conversations (fil de discussion)
- Messages (user + assistant)
- Mode de chaque conversation (écrit/vocal)

### Fonctions disponibles
- Charger / sauvegarder / switcher de conversation
- Supprimer une conversation (sans redirection)
- Supprimer toutes les conversations
- Stats : conversations, messages, sessions
- Donut chart dans le widget mémoire

---

## 10. PARAMÈTRES

### Sections accordéon
1. **🎨 Apparence** — thème, transparence, wallpaper
2. **👋 Salutation** — prénom, texte bienvenue, sous-texte
3. **🎙️ Voix** — TTS on/off, vitesse
4. **🤖 Modèles IA** — dropdown par rôle (intent/fast/heavy/vision)
5. **🔑 Clés API** — 5 providers, test, sauvegarde
6. **🎤 Micro** — device index, modèle Whisper
7. **⚙️ Système** — kill Ollama à la fermeture, etc.

### Sauvegarde
- `config.yaml` — settings techniques
- Clés API obfusquées (base64)
- Chargement automatique au démarrage

---

## 11. WIDGETS TEMPS RÉEL

### Résumé du jour
- Météo via **wttr.in** (gratuit, sans clé) ou OpenWeatherMap
- Batterie PC
- Horloge temps réel (mise à jour chaque seconde)
- Tâches / rappels (placeholder)

### Widget Mémoire
- Donut chart canvas (gradient bleu→violet)
- Stats conversations / messages / sessions
- Bouton "Explorer la mémoire"

### Widget Raccourcis
- Grille 2×2 de raccourcis rapides
- Chargés depuis les presets configurés
- Clic → envoie le prompt directement à ARIA

---

## 12. LANCEMENT & DÉPLOIEMENT

### Démarrage
```bat
launch_aria.bat
→ Tue les instances précédentes
→ Lance Python en arrière-plan (fenêtre cachée)
→ Attend le port WebSocket
→ Lance Electron (plein écran)
```

### Raccourci Windows
- Installé dans le menu Démarrer via `scripts/install_shortcut.ps1`
- Taper "ARIA" dans la recherche Windows → lance tout automatiquement
- Icône = nouveau logo fourni (512px, .ico multi-tailles)
- **Aucune mise à jour du raccourci nécessaire** après modifications du code

### Arrêt propre
- Fermeture Electron → signal Python → arrêt STT/TTS → save mémoire → kill Ollama (optionnel)

### Tray icon
- ARIA reste dans le system tray quand minimisé
- Clic → réouvre en plein écran maximisé
- Menu : Ouvrir / Micro ON-OFF / Quitter

---

## 13. ARCHITECTURE FICHIERS

```
assistant-vocal/
├── electron/
│   ├── main.js              ← Fenêtre, tray, WebSocket client
│   ├── preload.js           ← window.ARIA API (call, stream, on)
│   ├── package.json
│   ├── assets/
│   │   ├── icon.png         ← Logo ARIA (512px)
│   │   ├── icon.ico         ← Multi-tailles Windows
│   │   └── tray-icon.png    ← 22px system tray
│   └── renderer/
│       ├── index.html       ← Structure 3 colonnes
│       ├── app.js           ← Toute la logique JS
│       └── styles.css       ← Design system complet
│
├── python/
│   ├── main.py              ← Point d'entrée, démarre tout
│   ├── ui_bridge.py         ← WebSocket serveur + fonctions @expose
│   ├── llm.py               ← Routing LLM (llama.cpp + Ollama + APIs)
│   ├── stt.py               ← STT (faster-whisper + PyAudio)
│   ├── tts.py               ← TTS (edge-tts + pygame)
│   ├── memory_engine.py     ← Mémoire persistante JSON
│   ├── llamacpp_manager.py  ← Gestion llama-server.exe
│   ├── app_paths.py         ← Chemins absolus
│   ├── config.yaml          ← Configuration principale
│   └── actions/
│       ├── apps.py          ← Lancer/fermer applications
│       ├── browser.py       ← Chrome, YouTube, sites
│       ├── weather.py       ← Météo
│       ├── web_research.py  ← DDG + Wikipedia + YouTube
│       ├── gdocs.py         ← Google Docs
│       ├── agents.py        ← Agents IA personnalisables
│       ├── api_keys.py      ← Clés API providers
│       └── presets.py       ← Modes (vol, gaming, etc.)
│
├── data/
│   ├── memory.json          ← Mémoire persistante
│   ├── conversations/       ← Fichiers par conversation
│   └── wallpapers/          ← Images fond d'écran importées
│
├── docs/                    ← Architecture Bible
│   ├── 00_PRODUCT_VISION.md
│   ├── 01_UI_BIBLE.md
│   ├── 02_DESIGN_SYSTEM.md
│   ├── 03_ANIMATION_SYSTEM.md
│   ├── 04_ELECTRON_ARCHITECTURE.md
│   ├── 05_PYTHON_BACKEND.md
│   └── 17_CURSOR_MASTER_PROMPT.md
│
├── scripts/
│   ├── install_shortcut.ps1
│   ├── find_models.ps1
│   └── test_whisper_fr.py
│
└── launch_aria.bat          ← Lanceur Windows
```

---

## CE QUI N'EST PAS ENCORE FAIT

| Fonctionnalité | Statut | Sprint |
|----------------|--------|--------|
| Ouvrir TOUTES les apps (UWP, Store) | ⏳ Partiel | A |
| Écrire partout via presse-papier | ❌ | B |
| Résumés vraiment structurés | ⏳ Partiel | C |
| Liaison téléphone via Tailscale | ❌ | D |
| Google Calendar, Drive, Gmail, Sheets | ❌ | E |
| Installer modèles depuis l'UI | ❌ | F |
| Multi-utilisateurs | ❌ | G |
| Mises à jour en 1 clic | ❌ | H |
| Nexus mode VRAM économique | ❌ | I |
| Wake word "Hey ARIA" | ❌ | — |
| Sons d'interface | ❌ | — |

