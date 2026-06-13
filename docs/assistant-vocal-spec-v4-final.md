# Assistant Vocal — Spec v4 : Boot automatique + UI fonctionnelle + Chrome

> Ce fichier corrige et complète les specs v2 et v3. Priorité absolue : F24 doit ouvrir l'interface immédiatement. Le script doit démarrer seul au boot Windows.

---

## Problèmes à corriger en priorité

### 1. F24 ne fait rien — cause probable
Le hook `keyboard.add_hotkey` nécessite des droits admin sur Windows 11 pour intercepter les touches globalement. Sans ça, la touche est ignorée silencieusement.

**Fix obligatoire dans main.py :**
```python
import ctypes
import sys

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if not is_admin():
    # Relance le script en admin automatiquement
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, " ".join(sys.argv), None, 1
    )
    sys.exit()
```
Ce bloc doit être la toute première chose dans `main.py`, avant tout import des modules du projet.

### 2. tkinter dans un thread — cause de crash silencieux
tkinter DOIT tourner dans le thread principal sur Windows. Tout le reste (STT, LLM, TTS) tourne dans des threads daemon. La structure correcte :

```python
# main.py — structure correcte
if __name__ == "__main__":
    check_admin()           # relance en admin si besoin
    load_config()           # charge config.yaml
    init_logging()          # logging rotatif
    ui = UI()               # crée la fenêtre tkinter (pas encore visible)
    setup_keyboard_hook()   # hook F24 dans un thread séparé
    ui.run()                # mainloop() tkinter dans le thread principal — BLOQUANT
```

Le hook clavier tourne dans un thread daemon via `threading.Thread(target=keyboard.wait, daemon=True)`.

---

## Démarrage automatique au boot

### Fichier : setup_autostart.py
Script à exécuter UNE SEULE FOIS pour configurer le démarrage auto.

```python
import subprocess
import sys
import os
from pathlib import Path

def setup_autostart():
    python_exe = sys.executable.replace("python.exe", "pythonw.exe")
    script_path = Path(__file__).parent / "main.py"
    working_dir = Path(__file__).parent
    
    # Crée une tâche planifiée Windows
    task_xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
  </Settings>
  <Actions>
    <Exec>
      <Command>{python_exe}</Command>
      <Arguments>"{script_path}"</Arguments>
      <WorkingDirectory>{working_dir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""
    
    xml_path = working_dir / "autostart_task.xml"
    xml_path.write_text(task_xml, encoding='utf-16')
    
    result = subprocess.run(
        ["schtasks", "/create", "/tn", "AssistantVocal", 
         "/xml", str(xml_path), "/f"],
        capture_output=True, text=True
    )
    
    if result.returncode == 0:
        print("✅ Démarrage automatique configuré.")
        print("   Le script se lancera automatiquement à la prochaine connexion.")
    else:
        print(f"❌ Erreur : {result.stderr}")
    
    xml_path.unlink()

if __name__ == "__main__":
    setup_autostart()
```

**Utilisation :** lancer `python setup_autostart.py` UNE SEULE FOIS en admin. Après ça, le script démarre tout seul à chaque connexion Windows.

### Fichier : start.bat
Raccourci pour lancer manuellement pendant le développement :
```bat
@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
pythonw main.py
```

---

## ui.py — Refonte complète interface

### Design "ARIA" — thème midnight glassmorphism
- Fond `#080810` avec légère transparence
- Accents `#4A9EFF` (bleu électrique)
- Texte principal `#E8E8F0`
- Texte secondaire `#8888A8`
- Police `Consolas` pour tout
- Fenêtre sans bordure, coins arrondis simulés via canvas
- Positionnée en bas à droite, 30px des bords de l'écran
- Taille : 480×680px
- Toujours au premier plan

### Structure visuelle complète
```
┌──────────────────────────────────────────┐
│  ●  ARIA                    [−] [⚙] [×] │  ← header draggable
├──────────────────────────────────────────┤
│  ┌────────────────────────────────────┐  │
│  │  🌤 18°C  Couëron  |  14:32:05    │  │  ← info bar (météo + heure live)
│  └────────────────────────────────────┘  │
├──────────────────────────────────────────┤
│                                          │
│              [zone vide au début]        │
│                                          │
│  ┌────────────────────────────────┐      │
│  │ 🧑 Toi              14:32      │      │  ← bulle user (droite)
│  │ texte transcrit par Whisper    │      │
│  └────────────────────────────────┘      │
│                                          │
│  ┌────────────────────────────────┐      │
│  │ 🤖 ARIA             14:32      │      │  ← bulle assistant (gauche)
│  │ réponse token par token...     │      │
│  └────────────────────────────────┘      │
│                                          │
├──────────────────────────────────────────┤
│  ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░   │  ← waveform audio animée
├──────────────────────────────────────────┤
│  🔴 En écoute...                    [⚙] │  ← barre de statut
└──────────────────────────────────────────┘
```

### Indicateur d'état animé (cercle pulsant dans le header)
- `listening` → rouge `#FF4444` pulsant (animation scale 1.0→1.3→1.0, 1s)
- `transcribing` → jaune `#FFB800` pulsant rapide (0.5s)
- `thinking` → bleu `#4A9EFF` pulsant (0.8s)
- `speaking` → vert `#44FF88` pulsant (0.6s)
- `idle` → gris `#444466` statique
- Animation via `canvas.after()` loop dans tkinter

### Bulles de conversation
- Bulle utilisateur : fond `#1E1E3A`, bordure gauche `3px #4A9EFF`, texte blanc, alignée droite, padding 12px
- Bulle assistant : fond `#0A1628`, bordure gauche `3px #44FF88`, texte `#B8D4FF`, alignée gauche, padding 12px
- Chaque bulle a : icône (🧑/🤖), timestamp discret, texte
- Les tokens LLM s'ajoutent lettre par lettre dans la bulle en cours via `root.after(0, callback)`
- Auto-scroll vers le bas après chaque token

### Waveform animée
- Canvas 440×35px
- 40 barres verticales centrées
- Hauteur de chaque barre proportionnelle au RMS audio en temps réel
- Couleur : `#4A9EFF` si silence, `#44FF88` si parole détectée (RMS > threshold)
- Mise à jour 30fps via `root.after(33, update_waveform)`
- Quand micro inactif : animation idle (barres qui oscillent doucement)

### Info bar (météo + heure)
- Heure mise à jour chaque seconde via `root.after(1000, update_clock)`
- Météo mise à jour toutes les 30 min
- Format : "🌤 18°C  Couëron  |  14:32:05"
- Si pas de clé météo : affiche juste l'heure

### Panneau settings (slide depuis la droite)
- S'ouvre avec `[⚙]` dans le header
- Slider volume TTS (0-100)
- Slider vitesse TTS (-50% à +50%)
- Toggle sons d'ambiance
- Dropdown voix TTS (liste des voix FR disponibles edge-tts)
- Toggle always on top
- Bouton "Effacer historique"
- Bouton "Voir mémoire" (ouvre data/memory.json dans notepad)
- Bouton "Configurer APIs" (ouvre config.yaml dans notepad)
- Animation slide : `canvas.move()` sur 200ms

### Popup presets (grille de boutons)
- Ouvert via `[MODE]` dans le header
- Grille 2×3 : Étude / Vol / Gaming / Détente / Nuit / Personnalisé
- Bouton actif surligné en `#4A9EFF`
- Clic → `presets.activate(name)` + ferme popup

### Notifications toast
- Apparaissent en bas de la fenêtre pendant 3 secondes
- Fond semi-transparent, texte blanc
- Utilisées pour : "Ollama démarré", "Minuteur terminé", "Fichier ouvert", etc.
- Animation fade in/out via `canvas.itemconfig(... fill=...)`

### Méthodes thread-safe (toutes via root.after)
```python
def show_user_text(self, text):
    self.root.after(0, lambda: self._add_bubble(text, role='user'))

def append_assistant_text(self, token):
    self.root.after(0, lambda: self._append_to_current_bubble(token))

def finalize_assistant_message(self):
    self.root.after(0, self._close_current_bubble)

def set_status(self, state):
    self.root.after(0, lambda: self._update_status(state))

def update_waveform(self, rms):
    self.root.after(0, lambda: self._draw_waveform(rms))

def show_toast(self, message, duration=3000):
    self.root.after(0, lambda: self._display_toast(message, duration))

def show(self):
    self.root.after(0, self._show_window)

def hide(self):
    self.root.after(0, self._hide_window)
```

---

## actions/browser.py — Contrôle Chrome via Playwright

### Installation
```bash
pip install playwright
playwright install chromium
```

### Fonctionnalités

- `open_url(url)` :
  - Lance Chrome si pas ouvert, ouvre un nouvel onglet
  - Navigue vers l'URL
  - Attend que la page soit chargée

- `search_google(query)` :
  - Ouvre `https://www.google.com/search?q={query}`
  - Lit le premier résultat via TTS

- `search_youtube(query)` :
  - Ouvre `https://www.youtube.com/results?search_query={query}`
  - Clique sur le premier résultat vidéo
  - Lance la lecture automatiquement

- `youtube_control(action)` :
  - `play` / `pause` : `page.keyboard.press('k')`
  - `mute` : `page.keyboard.press('m')`
  - `fullscreen` : `page.keyboard.press('f')`
  - `volume_up` : `page.keyboard.press('ArrowUp')` x N
  - `volume_down` : `page.keyboard.press('ArrowDown')` x N
  - `next` : clique sur bouton suivant
  - `rewind` : `page.keyboard.press('j')` (recule 10s)
  - `forward` : `page.keyboard.press('l')` (avance 10s)

- `spotify_web_control(action)` :
  - Ouvre `https://open.spotify.com` si pas déjà ouvert
  - `play` / `pause` : `page.keyboard.press('Space')`
  - `next` : `Ctrl+Right`
  - `previous` : `Ctrl+Left`
  - `search(query)` : navigue vers la recherche Spotify Web

- `open_new_tab(url=None)` :
  - Ouvre un nouvel onglet vide ou avec URL

- `close_tab()` :
  - Ferme l'onglet actif : `page.keyboard.press('Control+w')`

- `close_browser()` :
  - Ferme Chrome complètement

- `get_current_url()` :
  - Retourne l'URL de la page active

- `get_page_title()` :
  - Retourne le titre de la page active, lit via TTS

- `scroll(direction, amount=3)` :
  - `down` / `up` / `top` / `bottom`
  - Via `page.keyboard.press('End')` ou `page.evaluate("window.scrollBy(0, 300)")`

- `click_element(description)` :
  - Trouve un élément par texte visible ou aria-label
  - `page.get_by_text(description).click()`

- `fill_search_bar(query)` :
  - Trouve la barre de recherche de la page active
  - Tape la requête et valide

- `read_page_content()` :
  - Extrait le texte principal de la page via `page.inner_text('body')`
  - Résumé via Ollama
  - Lit le résumé via TTS

- `take_screenshot(save_path)` :
  - `page.screenshot(path=save_path)`

### Gestion du contexte navigateur
```python
# browser.py — singleton playwright
_playwright = None
_browser = None
_page = None

def get_page():
    global _playwright, _browser, _page
    if _browser is None or not _browser.is_connected():
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=False, channel="chrome")
        _page = _browser.new_page()
    return _page
```

### Commandes vocales
- "ouvre YouTube et cherche [titre]"
- "pause la vidéo"
- "coupe le son"
- "passe à la suivante"
- "ouvre un nouvel onglet"
- "ferme cet onglet"
- "va sur [site]"
- "recherche [requête] sur Google"
- "lis moi cette page"
- "fais défiler vers le bas"
- "ouvre Spotify et lance [titre/artiste]"
- "monte le volume YouTube"

---

## Mise à jour llm.py — intents navigateur

Ajouter à la liste INTENTS :
```python
# Browser
"browser_open_url",        # ouvrir une URL
"browser_search_google",   # recherche Google
"browser_youtube_search",  # chercher sur YouTube
"browser_youtube_control", # play/pause/next/volume YouTube
"browser_spotify",         # contrôle Spotify Web
"browser_new_tab",         # nouvel onglet
"browser_close_tab",       # fermer onglet
"browser_close",           # fermer Chrome
"browser_scroll",          # défiler
"browser_read_page",       # lire le contenu
"browser_screenshot",      # capture d'écran navigateur
```

---

## Mise à jour requirements.txt (ajouter)

```
playwright
```

---

## Mise à jour config.yaml (ajouter)

```yaml
# Browser
browser: chrome          # chrome, msedge, firefox
browser_headless: false
browser_default_search: google
```

---

## Installation complète v4

```bash
# Dans le venv activé
pip install playwright
playwright install chromium

# Setup démarrage auto (UNE SEULE FOIS, en admin)
python setup_autostart.py
```

---

## Checklist de debug — F24 ne fait rien

Le script vérifie automatiquement ces points au démarrage et log les erreurs dans `assistant-vocal.log` :

1. ✅ Script lancé en admin (auto-relance si non)
2. ✅ PowerToys actif et remap Copilot→F24 configuré
3. ✅ `keyboard` lib installée
4. ✅ tkinter dans le thread principal
5. ✅ Hook F24 enregistré (log "Hook F24 actif" au démarrage)
6. ✅ Test hook : au démarrage, log "En attente de F24..."
7. ✅ Ollama installé et accessible
8. ✅ Modèle qwen3:14b présent (sinon pull automatique)

**Log au démarrage normal :**
```
[INFO] main - Droits admin : OK
[INFO] main - Config chargée : config.yaml
[INFO] main - Hook F24 enregistré
[INFO] main - ARIA prêt. Appuyez sur F24 pour activer.
```

---

## Prompt Cursor pour implémenter le v4

> The voice assistant project is fully implemented (v2 + v3 addons). Now apply these v4 fixes and additions:
> 
> PRIORITY 1 — Fix main.py:
> - Add admin check at the very top (auto-relaunch as admin if not already)
> - Move tkinter mainloop to main thread, keyboard hook in daemon thread
> - Add startup log "Hook F24 enregistré" and "ARIA prêt. Appuyez sur F24 pour activer."
> 
> PRIORITY 2 — Rewrite ui.py completely:
> - Full midnight glassmorphism theme (#080810 background, #4A9EFF accents)
> - Animated pulsing status indicator (listening=red, transcribing=yellow, thinking=blue, speaking=green)
> - Real-time waveform canvas (40 bars, 30fps, green when speech detected)
> - Chat bubbles with role icons and timestamps, tokens displayed in real-time
> - Live clock in info bar updated every second
> - Settings panel slide-in from right
> - Preset popup grid
> - Toast notifications
> - ALL UI updates via root.after() for thread safety
> 
> PRIORITY 3 — Create setup_autostart.py:
> - Creates Windows Task Scheduler task via schtasks
> - Runs at logon with highest privileges
> - Uses pythonw.exe to run without console window
> 
> PRIORITY 4 — Create start.bat:
> - Activates venv and launches pythonw main.py
> 
> PRIORITY 5 — Create actions/browser.py:
> - Playwright chromium singleton (get_page() function)
> - All browser control functions as specified
> - YouTube, Spotify Web, Google search, tab management
> 
> PRIORITY 6 — Update llm.py:
> - Add browser intents to INTENTS list
> - Add routing to actions/browser.py
> 
> Do not touch any other existing file except main.py, ui.py, llm.py, requirements.txt.
> Every function fully implemented. No placeholders.
