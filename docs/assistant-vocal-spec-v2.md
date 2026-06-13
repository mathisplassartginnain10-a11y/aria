# Assistant Vocal Local — Spécifications Ultra-Complètes v2.0

## Vision générale

Assistant vocal 100% local sur Windows 11, déclenché par la touche Copilot remappée F24. Zéro cloud sauf edge-tts et les APIs d'information (météo, actus). Interface graphique flottante réactive. Mémoire persistante. Contrôle total du système. Conçu pour un lycéen en Première avec des spécialités Maths/Allemand, passionné d'aviation, de gaming et de développement.

---

## Structure du projet

```
assistant-vocal/
├── main.py                    # Point d'entrée, toggle F24
├── stt.py                     # Enregistrement micro + Whisper
├── llm.py                     # Ollama streaming + intent detection
├── tts.py                     # edge-tts + pygame
├── ollama_manager.py          # Gestion process Ollama
├── ui.py                      # Interface graphique tkinter avancée
├── memory.py                  # Mémoire persistante JSON
├── config.yaml                # Configuration utilisateur
├── requirements.txt
├── actions/
│   ├── __init__.py
│   ├── apps.py                # Lancer/fermer applications
│   ├── system.py              # Volume, luminosité, veille, reboot
│   ├── clipboard.py           # Presse-papier vocal
│   ├── files.py               # Ouvrir fichiers/dossiers
│   ├── weather.py             # Météo OpenWeatherMap
│   ├── news.py                # Actualités NewsAPI
│   ├── aviation.py            # METAR, TAF, NOTAMs
│   ├── timer.py               # Minuteurs et alarmes
│   ├── search.py              # Recherche web Brave Search
│   ├── git.py                 # Commandes Git vocales
│   ├── math_helper.py         # Calculs et conversions
│   ├── translator.py          # Traduction via Ollama
│   ├── presets.py             # Modes (étude, vol, gaming, etc.)
│   └── calendar_action.py     # Agenda et rappels
├── data/
│   ├── memory.json            # Mémoire persistante
│   ├── history.json           # Historique conversations
│   ├── timers.json            # Minuteurs persistants
│   └── presets.json           # Configuration des modes
└── sounds/
    ├── activate.wav           # Son d'activation
    ├── deactivate.wav         # Son de désactivation
    ├── listening.wav          # Bip de début d'écoute
    ├── thinking.wav           # Son pendant la réflexion
    └── error.wav              # Son d'erreur
```

---

## config.yaml

```yaml
# Général
hotkey: f24
model: qwen3:14b
ollama_path: "C:/Users/mathi/AppData/Local/Programs/Ollama/ollama.exe"
language: fr

# STT
whisper_model: small
silence_threshold: 500
silence_duration: 1.5
sample_rate: 16000
chunk_size: 1024

# TTS
tts_voice: fr-FR-DeniseNeural
tts_rate: "+5%"
tts_volume: "+0%"
sounds_enabled: true

# LLM
max_history: 20
system_prompt: |
  Tu es ARIA (Assistant Résidant Intelligent et Autonome), un assistant vocal local
  en français. Tu es concis, naturel, et adapté à une lecture à voix haute.
  Tu connais ton utilisateur : lycéen en Première (Maths/Allemand), passionné
  d'aviation (PPL, Robin DR400, LFRS Nantes), gaming (MSFS 2024, No Man's Sky,
  Age of Empires 4), et développement (Python, React Native, Three.js).
  Réponds toujours en français sauf si on te demande autre chose.
  Sois direct et précis. Pas de listes à puces dans tes réponses vocales.

# UI
ui_width: 500
ui_height: 700
ui_position: bottom_right  # bottom_right, bottom_left, top_right, top_left, center
ui_opacity: 0.95
ui_theme: dark  # dark, darker, midnight
ui_font: Consolas
ui_font_size: 11
always_on_top: true
show_waveform: true

# Localisation
city: Couëron
lat: 47.2167
lon: -1.7333
timezone: Europe/Paris

# APIs (à remplir)
openweather_api_key: ""
newsapi_key: ""
brave_search_key: ""
avwx_api_key: ""  # Pour METAR/TAF aviation

# Applications (chemins personnalisés)
apps:
  msfs: "C:/Program Files/WindowsApps/Microsoft.FlightSimulator_*/FlightSimulator.exe"
  spotify: "C:/Users/mathi/AppData/Roaming/Spotify/Spotify.exe"
  chrome: "C:/Program Files/Google/Chrome/Application/chrome.exe"
  firefox: "C:/Program Files/Mozilla Firefox/firefox.exe"
  vscode: "C:/Users/mathi/AppData/Local/Programs/Microsoft VS Code/Code.exe"
  cursor: "C:/Users/mathi/AppData/Local/Programs/cursor/Cursor.exe"
  discord: "C:/Users/mathi/AppData/Local/Discord/app-*/Discord.exe"
  steam: "C:/Program Files (x86)/Steam/Steam.exe"
  obs: "C:/Program Files/obs-studio/bin/64bit/obs64.exe"
  notepad: "notepad.exe"
  explorer: "explorer.exe"
  calculator: "calc.exe"
  taskmgr: "taskmgr.exe"

# Aviation
default_icao: LFRS  # Nantes Atlantique
home_icao: LFRS
callsign: N123AZ

# Modes/Presets
presets:
  etude:
    apps_open: [vscode, cursor]
    apps_close: [discord, steam, spotify]
    volume: 30
    message: "Mode étude activé. Discord et Steam fermés."
  vol:
    apps_open: [msfs]
    apps_close: [discord]
    volume: 50
    message: "Mode vol activé. MSFS en cours de lancement."
  gaming:
    apps_open: [steam, discord]
    volume: 70
    message: "Mode gaming activé."
  detente:
    apps_open: [spotify, discord]
    volume: 60
    message: "Mode détente activé."
  nuit:
    apps_close: [discord, steam, spotify, chrome]
    volume: 15
    brightness: 30
    message: "Mode nuit activé. Bonne nuit."

# Démarrage
morning_briefing: true
morning_briefing_time: "08:00"
briefing_includes: [weather, news, calendar]
```

---

## main.py

- Charge `config.yaml` avec PyYAML
- Initialise le logger global (`logging.basicConfig` niveau INFO, fichier `assistant-vocal.log`)
- Initialise `memory.py` au démarrage (charge `data/memory.json`)
- Vérifie les droits admin et affiche un warning si absent
- `actif = False` + `threading.Lock()` thread-safe
- `keyboard.add_hotkey('f24', on_press)` dans le thread principal
- `on_press()` :
  - Si `actif == False` :
    - `sounds.play('activate')`
    - `ollama_manager.start()` dans un thread
    - `ui.show()` immédiatement
    - `stt.start_listening()` dans un thread daemon
    - Lance le brief matinal si heure correspondante et `morning_briefing: true`
  - Si `actif == True` :
    - `sounds.play('deactivate')`
    - `stt.stop_listening()`
    - `tts.stop()`
    - `ollama_manager.stop()`
    - `ui.hide()`
    - `memory.save()` — sauvegarde mémoire
- Gère `SIGINT` et `SIGTERM` proprement (cleanup complet avant de quitter)
- `keyboard.wait()` en fin de script

---

## ollama_manager.py

- `start()` : vérifie si déjà actif via `GET /api/tags`, sinon lance `ollama serve` avec `CREATE_NO_WINDOW`
- `stop()` : `terminate()` → `wait(5)` → `kill()` si nécessaire
- `wait_until_ready(timeout=30)` : polling toutes les 0.5s
- `is_running()` : retourne True/False
- `get_loaded_models()` : `GET /api/tags` → retourne liste des modèles disponibles
- `pull_model(model_name)` : lance `ollama pull` en subprocess si modèle absent

---

## stt.py

- Charge `WhisperModel` une seule fois à l'import (device="cuda", compute_type="float16")
- Affiche dans les logs le temps de chargement du modèle
- `_stop_event = threading.Event()`
- `_is_recording = False`
- `start_listening()` :
  1. `ollama_manager.wait_until_ready()`
  2. Reset `_stop_event`
  3. `ui.set_status('listening')`
  4. Lance `_record_loop()` en thread daemon
- `_record_loop()` :
  - Boucle principale : enregistre chunks 16kHz via `sounddevice`
  - Calcule RMS de chaque chunk
  - Alimente la waveform UI en temps réel : `ui.update_waveform(rms)`
  - Accumule chunks dans buffer si RMS > threshold
  - Détecte fin de parole (silence > `silence_duration`)
  - Sauvegarde WAV temp dans `tempfile.gettempdir()`
  - `ui.set_status('transcribing')`
  - Transcrit avec Whisper, retourne texte + langue détectée + confidence score
  - Si texte vide ou confidence trop basse : retour écoute silencieuse
  - Si texte valide : `ui.show_user_text(texte)`, puis `llm.ask(texte)`
  - Supprime WAV temp
  - Retour en écoute
- `stop_listening()` : `_stop_event.set()`
- `get_audio_level()` : retourne le niveau RMS actuel (pour la waveform)

---

## llm.py

- `history = []` avec system prompt initial
- Intent detection intégrée : avant d'appeler Ollama pour une réponse, envoie un premier appel rapide pour classifier l'intent parmi :
  `["lancer_app", "fermer_app", "volume", "luminosite", "veille", "reboot", "shutdown", "actu", "meteo", "aviation_metar", "aviation_taf", "aviation_notam", "minuteur", "alarme", "recherche_web", "git", "calcul", "traduction", "preset", "clipboard_copy", "clipboard_paste", "ouvrir_fichier", "rappel", "question_libre", "blague", "heure_date", "historique", "memoire"]`
  Retourne JSON : `{"intent": "...", "params": {...}, "confidence": 0.95}`
- Si `confidence > 0.8` → route vers le module `actions/` correspondant sans passer par Ollama conversationnel
- Sinon → conversation libre avec Ollama en streaming
- `ask(text)` :
  1. Détecte l'intent
  2. Route vers action ou conversation
  3. Pour les actions : appelle le module, récupère la réponse textuelle, lit via TTS
  4. Pour la conversation : stream Ollama, affiche tokens en temps réel dans UI, lit via TTS
  5. Met à jour l'historique
  6. Sauvegarde dans `data/history.json`
  7. Extrait et met à jour la mémoire si nouvelles infos détectées
- `clear_history()` : reset history en gardant le system prompt
- `get_history_summary()` : demande à Ollama un résumé de la conversation en cours

---

## tts.py

- `_lock = threading.Lock()`
- `_current_process = None`
- `speak(text)` :
  1. Si text vide : return
  2. Nettoie le texte (supprime markdown, émojis, caractères spéciaux non lisibles)
  3. Découpe en phrases pour streamer phrase par phrase (latence minimale)
  4. Pour chaque phrase : génère audio edge-tts, joue avec pygame, supprime temp
  5. S'arrête proprement si `_stop_event` set entre deux phrases
- `stop()` : `pygame.mixer.music.stop()`, set `_stop_event`
- `set_voice(voice_name)` : change la voix à chaud
- `set_rate(rate)` : change la vitesse à chaud
- `speak_sound(sound_name)` : joue un fichier WAV depuis `sounds/`
- `pygame.mixer.init()` une seule fois à l'import

---

## memory.py

- Charge/sauvegarde `data/memory.json`
- Structure :
  ```json
  {
    "user": {
      "name": "mathi",
      "preferences": {},
      "facts": [],
      "last_session": ""
    },
    "context": {
      "last_app_launched": "",
      "last_search": "",
      "last_icao": "LFRS"
    },
    "reminders": [],
    "custom_commands": {}
  }
  ```
- `remember(key, value)` : stocke une info
- `recall(key)` : récupère une info
- `add_reminder(text, datetime)` : ajoute un rappel
- `get_due_reminders()` : retourne les rappels à déclencher
- `add_custom_command(trigger, action)` : crée une commande vocale personnalisée
- `get_custom_commands()` : retourne toutes les commandes custom
- `extract_from_conversation(text)` : analyse le texte pour extraire des infos mémorisables (noms, préférences, faits mentionnés)

---

## ui.py — Interface graphique avancée

### Design
- Fenêtre tkinter sans bordure (`overrideredirect(True)`)
- Thème midnight : fond `#080810`, accents `#4A9EFF`, texte `#E8E8F0`
- Coins arrondis via canvas
- Positionnée selon `ui_position` dans config
- Opacity configurée via `wm_attributes('-alpha', ui_opacity)`
- Toujours au premier plan si `always_on_top: true`
- Draggable via clic maintenu sur le header

### Layout
```
┌──────────────────────────────────────┐
│  ◉ ARIA          [_] [MODE] [×]      │  ← header
├──────────────────────────────────────┤
│                                      │
│  ┌──────────────────────────────┐    │
│  │  Météo: 18°C ☁ Couëron      │    │  ← widget info (optionnel)
│  └──────────────────────────────┘    │
│                                      │
│  ╔══════════════════╗                │
│  ║ Toi              ║                │  ← bulle utilisateur (droite)
│  ║ texte transcrit  ║                │
│  ╚══════════════════╝                │
│                                      │
│  ╔═══════════════════════════╗       │
│  ║ ARIA                      ║       │  ← bulle assistant (gauche)
│  ║ réponse en temps réel...  ║       │
│  ╚═══════════════════════════╝       │
│                                      │
├──────────────────────────────────────┤
│  ▁▂▃▄▅▄▃▂▁  🎤 En écoute...  [⚙]   │  ← waveform + statut + settings
└──────────────────────────────────────┘
```

### Composants UI détaillés

**Header** :
- Indicateur d'état animé (cercle pulsant) : rouge=écoute, bleu=transcription, vert=réponse, gris=inactif
- Nom de l'assistant "ARIA" en police monospace bold
- Bouton `[_]` : minimize (masque sans désactiver)
- Bouton `[MODE]` : ouvre un popup de sélection de preset
- Bouton `[×]` : désactive complètement (équivalent F24)

**Widget info** (barre compacte) :
- Météo actuelle (mise à jour toutes les 30 min)
- Heure et date
- Dernier METAR si aviation mode actif
- Cliquable pour voir plus de détails

**Zone de conversation** :
- `tkinter.Text` scrollable avec scrollbar auto
- Auto-scroll vers le bas à chaque nouveau message
- Bulles utilisateur : alignées droite, fond `#1E1E3A`, texte blanc, arrondi 12px simulé
- Bulles assistant : alignées gauche, fond `#0A2A4A`, texte `#B0D4FF`, arrondi 12px simulé
- Tokens LLM affichés en temps réel dans la bulle en cours de construction
- Bouton copier sur hover de chaque bulle
- Timestamp discret sur chaque bulle

**Waveform** :
- Canvas tkinter 500×40px
- Barres verticales animées reflétant le niveau audio en temps réel (60fps)
- Couleur : vert si parole détectée, gris sinon
- Visible uniquement si `show_waveform: true`

**Barre de statut** :
- Texte animé selon état : "En écoute...", "Transcription en cours...", "ARIA réfléchit...", "Lecture..."
- Animation de points (`...` qui s'ajoutent)
- Icône micro animée (clignote en rouge pendant l'écoute active)
- Bouton `[⚙]` : ouvre panneau de settings

**Panneau settings** (slide-in depuis la droite) :
- Slider volume TTS
- Slider vitesse TTS
- Toggle sons d'ambiance
- Bouton "Effacer l'historique"
- Bouton "Voir la mémoire"
- Dropdown choix de voix TTS
- Toggle always on top
- Bouton "Ajouter commande custom"

**Popup preset** :
- Grille de boutons : Étude / Vol / Gaming / Détente / Nuit
- Clic → active le preset correspondant
- Indicateur du preset actif

### Méthodes exposées
- `show()` / `hide()` / `minimize()`
- `show_user_text(text)` : nouvelle bulle utilisateur
- `append_assistant_text(token)` : token par token en temps réel
- `finalize_assistant_message()` : ferme la bulle en cours
- `set_status(state)` : met à jour indicateur + barre de statut
- `update_waveform(rms_value)` : met à jour l'animation waveform
- `update_info_widget(weather, time)` : met à jour le widget info
- `show_notification(text, duration=3)` : notification toast en bas
- `show_error(text)` : bulle d'erreur rouge
- Toutes les mises à jour UI via `root.after()` pour thread-safety

---

## actions/apps.py

- `launch(app_name)` : résout le nom via config `apps`, supporte les wildcards glob, lance avec `subprocess.Popen`
- `close(app_name)` : trouve le process via `psutil`, termine proprement
- `close_all_except(keep_list)` : ferme tout sauf la liste
- `list_running()` : retourne les apps actuellement ouvertes (filtrées sur les apps connues)
- `focus(app_name)` : met l'app au premier plan via `win32gui`
- Commandes vocales : "lance MSFS", "ouvre Spotify", "ferme Discord", "bascule sur Chrome"

---

## actions/system.py

- `set_volume(level)` : via `pycaw`, accepte 0-100 ou "monte", "baisse", "coupe", "rétablis"
- `get_volume()` : retourne le niveau actuel
- `set_brightness(level)` : via `screen-brightness-control`, accepte 0-100
- `get_brightness()` : retourne la valeur actuelle
- `sleep()` : `os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")`
- `shutdown(delay=0)` : `os.system(f"shutdown /s /t {delay}")`
- `reboot(delay=0)` : `os.system(f"shutdown /r /t {delay}")`
- `cancel_shutdown()` : `os.system("shutdown /a")`
- `lock()` : `ctypes.windll.user32.LockWorkStation()`
- `empty_trash()` : `winshell.recycle_bin().empty()`
- `get_battery()` : via `psutil.sensors_battery()`
- `get_cpu_temp()` : via `psutil` ou `wmi`
- `get_ram_usage()` : via `psutil`
- `get_disk_usage(path)` : via `psutil`
- `screenshot(save_path)` : via `PIL.ImageGrab`
- Commandes vocales : "volume à 50", "baisse la luminosité", "mets en veille", "éteins dans 10 minutes", "capture d'écran"

---

## actions/clipboard.py

- `copy_text(text)` : copie dans le presse-papier via `pyperclip`
- `get_text()` : lit le contenu actuel
- `read_clipboard()` : lit le contenu à voix haute via TTS
- `paste_as_voice()` : dicte le contenu du presse-papier
- Commandes vocales : "lis le presse-papier", "copie ça", "qu'est-ce que j'ai copié"

---

## actions/weather.py

- `get_current(city)` : OpenWeatherMap current weather, retourne température, ressenti, description, vent, humidité
- `get_forecast(city, days=3)` : prévisions 3 jours
- `get_hourly(city)` : prévisions horaires du jour
- `format_for_speech(data)` : formate en phrase naturelle pour TTS
- Cache local 30 min pour éviter les appels répétés
- Fallback si pas de clé API : message clair
- Commandes vocales : "météo aujourd'hui", "il va pleuvoir demain ?", "température à Nantes"

---

## actions/news.py

- `get_top_headlines(category, country='fr', n=5)` : via NewsAPI
- `get_by_topic(topic, n=3)` : recherche par sujet
- `format_briefing(articles)` : formate en lecture naturelle pour TTS (titre + une phrase de résumé)
- Catégories : general, technology, science, sports, aviation
- Cache 15 min
- `morning_briefing()` : top 5 actus générales + 2 actus tech
- Commandes vocales : "actus du jour", "actus tech", "quoi de neuf en France"

---

## actions/aviation.py

- `get_metar(icao)` : via AVWX API ou aviationweather.gov (fallback gratuit)
  - Parse et retourne : vent, visibilité, nuages, température, point de rosée, QNH, conditions
  - `decode_metar_to_speech(raw)` : traduit le METAR brut en français naturel
- `get_taf(icao)` : prévision aéronautique, décode en français
- `get_notams(icao)` : NOTAMs actifs pour un terrain
- `get_atis(icao)` : si disponible
- `get_sunrise_sunset(lat, lon)` : via `ephem` ou formule
- `compute_density_altitude(pressure, temp, elevation)` : calcul de densité altitude
- `decode_cloud_cover(oktas)` : SKC/FEW/SCT/BKN/OVC en français
- `decode_wind(wind_string)` : "vent du 270 à 15 nœuds rafales 25"
- Commandes vocales : "METAR Nantes", "TAF LFRS", "conditions de vol aujourd'hui", "densité altitude"

---

## actions/timer.py

- `set_timer(duration_seconds, label)` : crée un minuteur, persiste dans `data/timers.json`
- `set_alarm(time_str, label)` : alarme à heure fixe
- `cancel_timer(label)` : annule un minuteur par nom
- `list_timers()` : liste les minuteurs actifs
- `_timer_loop()` : thread daemon qui vérifie toutes les secondes, déclenche TTS + son quand expiration
- Parse le langage naturel : "dans 10 minutes", "dans 1h30", "à 18h00", "dans 2 heures"
- Commandes vocales : "minuteur 10 minutes", "alarme à 7h30", "annule le minuteur", "dans combien de temps"

---

## actions/search.py

- `search(query, n=3)` : via Brave Search API, retourne top 3 résultats
- `summarize_results(results)` : envoie les résultats à Ollama pour résumé vocal en 2-3 phrases
- `open_in_browser(url)` : ouvre le premier résultat dans le navigateur par défaut
- Commandes vocales : "cherche comment faire X", "qu'est-ce que Y", "recherche Z sur internet"

---

## actions/git.py

- Détecte le repo Git du dossier courant (ou dernier repo utilisé en mémoire)
- `status()` : `git status` → résumé vocal
- `add_all()` : `git add .`
- `commit(message)` : `git commit -m "message"`
- `push()` : `git push`
- `pull()` : `git pull`
- `create_branch(name)` : `git checkout -b name`
- `switch_branch(name)` : `git checkout name`
- `log(n=5)` : derniers n commits → résumé vocal
- Commandes vocales : "commit avec le message X", "pousse le code", "quel est le statut git", "crée une branche feature"

---

## actions/math_helper.py

- `calculate(expression)` : évalue une expression mathématique via `sympy` ou `eval` sécurisé
- `convert_units(value, from_unit, to_unit)` : conversions (km/h→nœuds, °C→°F, kg→lb, nm→km, etc.)
- `solve_equation(equation)` : résolution via `sympy`
- `derivative(expression, variable)` : dérivée
- `integral(expression, variable)` : intégrale
- `matrix_op(op, matrix)` : opérations matricielles basiques
- Contexte lycée Première : reconnaît "dérive f(x)=...", "résous X²+3X-4=0"
- Commandes vocales : "combien font 15% de 340", "convertis 120 nœuds en km/h", "dérive 3x²+2x"

---

## actions/translator.py

- `translate(text, target_lang)` : via Ollama (prompt de traduction), supporte FR/EN/DE/ES/IT
- `detect_language(text)` : détecte la langue du texte
- Commandes vocales : "traduis X en allemand", "comment dit-on Y en anglais", "traduis ce que je viens de dire en espagnol"

---

## actions/presets.py

- `activate(preset_name)` : lit le preset depuis config.yaml, exécute toutes les actions dans l'ordre
  - Ouvre les apps listées dans `apps_open`
  - Ferme les apps listées dans `apps_close`
  - Règle le volume
  - Règle la luminosité si spécifiée
  - Lit le message de confirmation via TTS
- `create_preset(name, config)` : crée un nouveau preset custom
- `list_presets()` : liste les presets disponibles
- `get_active_preset()` : retourne le preset actuellement actif
- Commandes vocales : "mode étude", "mode vol", "mode gaming", "mode nuit", "désactive le mode"

---

## actions/calendar_action.py

- Intégration Google Calendar (via `google-auth` + API Calendar) ou fichier `.ics` local
- `get_today_events()` : événements du jour
- `get_upcoming(days=7)` : événements de la semaine
- `add_event(title, date, time, duration)` : crée un événement
- `add_reminder(text, datetime)` : ajoute dans `data/memory.json`
- `get_due_reminders()` : vérifie et lit les rappels échus
- Commandes vocales : "qu'est-ce que j'ai aujourd'hui", "ajoute un rappel demain à 14h", "mes événements de la semaine"

---

## Brief matinal automatique

Déclenché automatiquement si `morning_briefing: true` et heure = `morning_briefing_time` (vérifié au démarrage du script).

Séquence :
1. Son d'activation
2. "Bonjour Mathi, voici ton briefing du [jour] [date]."
3. Météo du jour (température, conditions, prévision)
4. Top 3 actualités (général)
5. Rappels du jour depuis calendar_action
6. Minuteurs persistants restants
7. "Bonne journée !"

---

## Commandes vocales personnalisées

Via `memory.py`, l'utilisateur peut créer ses propres commandes :
- "apprends que quand je dis X, tu fais Y"
- Stocké dans `memory.json` → `custom_commands`
- Vérifié avant le routing d'intent normal

---

## Gestion des erreurs

Chaque module gère ses erreurs proprement :
- API injoignable → message vocal clair ("Météo indisponible, vérifie ta connexion")
- Ollama pas prêt → retry 3 fois avec délai, sinon message d'erreur
- Micro non détecté → message vocal + log
- Whisper erreur → retry sur le dernier buffer
- App introuvable → "Je n'ai pas trouvé l'application X sur ton PC"
- Son d'erreur joué dans tous les cas

---

## Logging

- Fichier `assistant-vocal.log` avec rotation (max 5MB, 3 backups)
- Format : `[TIMESTAMP] [MODULE] [LEVEL] message`
- Niveau INFO en production, DEBUG si `debug: true` dans config
- Chaque module a son propre logger `logging.getLogger(__name__)`

---

## requirements.txt

```
faster-whisper
sounddevice
scipy
keyboard
pygame
edge-tts
pyyaml
requests
psutil
pycaw
screen-brightness-control
pyperclip
sympy
Pillow
pywin32
winshell
google-auth
google-auth-oauthlib
google-api-python-client
ephem
```

---

## Installation complète

```bash
cd "c:\Users\mathi\OneDrive\Documents\assistant-ia\assistant-vocal"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
ollama pull qwen3:14b
python main.py
```

---

## Démarrage automatique au boot

1. `Win+R` → `taskschd.msc`
2. Créer une tâche → Déclencheur : À l'ouverture de session
3. Action : `pythonw.exe` + argument `main.py` + dossier de démarrage = chemin projet
4. Conditions : décocher "Démarrer uniquement sur secteur"

---

## Flux complet

```
BOOT Windows
    └─► main.py démarre (veille, ~0 CPU)
            └─► keyboard hook F24 actif

F24 appui #1
    ├─► son activate.wav
    ├─► ollama_manager.start()     → subprocess ollama serve
    ├─► ui.show()                  → fenêtre flottante
    ├─► stt.start_listening()
    │       ├─► wait_until_ready() → Ollama prêt
    │       ├─► micro actif, waveform animée
    │       ├─► détecte silence après parole
    │       ├─► Whisper → texte
    │       └─► llm.ask(texte)
    │               ├─► intent detection (appel Ollama rapide)
    │               ├─► si action → actions/*.py → réponse texte → tts.speak()
    │               └─► si question libre → stream Ollama → ui tokens → tts.speak()
    └─► (boucle continue)

F24 appui #2
    ├─► son deactivate.wav
    ├─► stt.stop_listening()
    ├─► tts.stop()
    ├─► ollama_manager.stop()      → libère VRAM
    ├─► memory.save()
    └─► ui.hide()
```

---

## Prompt Cursor pour générer ce projet

> Implement the complete voice assistant project described in this specification file. Generate ALL files fully implemented with no placeholders. Start with: config.yaml, then requirements.txt, then ollama_manager.py, then memory.py, then tts.py, then stt.py, then all files in actions/ folder, then llm.py, then ui.py, then main.py. Every function must be fully implemented. Use pathlib.Path for all paths. All subprocess calls use CREATE_NO_WINDOW. All UI updates use root.after() for thread safety. Log everything with logging.getLogger(__name__).
