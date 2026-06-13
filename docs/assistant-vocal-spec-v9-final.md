# Assistant Vocal — Spec v9 : Tout fonctionnel — Micro + Texte + Apps + UI

## Objectif
Tout doit fonctionner de bout en bout :
1. Micro actif en permanence dès l'activation
2. Input texte en plus du vocal
3. Lancement d'applications fiable
4. UI redesign plein écran magnifique
5. Réponses vocales fluides

---

## PRIORITÉ 1 — Correction micro (stt.py)

```python
# Remplacer tout _record_loop() par cette version robuste :

import sounddevice as sd
import numpy as np
import tempfile
import wave
import time

def _record_loop():
    logger = logging.getLogger(__name__)
    stream = None
    retry = 0
    max_retry = 10
    
    # Attendre qu'Ollama soit prêt avant de démarrer
    time.sleep(1.5)
    
    # Ouvrir le stream avec retry
    while retry < max_retry and not _stop_event.is_set():
        try:
            stream = sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype='float32',
                blocksize=1024,
                device=None,
                latency='high',
                extra_settings=None,
            )
            stream.start()
            logger.info("Microphone ouvert avec succès")
            break
        except Exception as e:
            retry += 1
            logger.warning(f"Tentative micro {retry}/{max_retry}: {e}")
            time.sleep(2)
    
    if stream is None or not stream.active:
        logger.error("Impossible d'ouvrir le microphone après %d tentatives", max_retry)
        ui.show_toast("Microphone indisponible", toast_type="error")
        return
    
    buffer = []
    silence_frames = 0
    speaking = False
    SILENCE_LIMIT = int(16000 / 1024 * float(_config.get('silence_duration', 1.5)))
    THRESHOLD = float(_config.get('silence_threshold', 500))
    
    try:
        while not _stop_event.is_set():
            try:
                data, overflowed = stream.read(1024)
            except Exception as e:
                logger.warning("Erreur lecture micro: %s", e)
                time.sleep(0.1)
                continue
            
            rms = float(np.sqrt(np.mean(data ** 2)) * 32768)
            ui.update_waveform(rms)
            
            if rms > THRESHOLD:
                speaking = True
                silence_frames = 0
                buffer.append(data.copy())
            elif speaking:
                silence_frames += 1
                buffer.append(data.copy())
                if silence_frames >= SILENCE_LIMIT:
                    # Silence détecté — transcrire
                    audio = np.concatenate(buffer, axis=0)
                    buffer = []
                    speaking = False
                    silence_frames = 0
                    
                    # Sauvegarder WAV temp
                    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                    with wave.open(tmp.name, 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(16000)
                        wf.writeframes((audio * 32768).astype(np.int16).tobytes())
                    
                    ui.set_status('transcribing')
                    try:
                        segments, _ = _whisper_model.transcribe(tmp.name, language='fr')
                        text = ' '.join(s.text for s in segments).strip()
                        if text:
                            logger.info("Transcrit: %s", text)
                            ui.show_user_text(text)
                            ui.set_status('thinking')
                            import llm
                            llm.ask(text)
                    except Exception as e:
                        logger.error("Erreur Whisper: %s", e)
                    finally:
                        import os
                        try: os.unlink(tmp.name)
                        except: pass
                    
                    ui.set_status('listening')
    finally:
        try: stream.stop(); stream.close()
        except: pass
```

---

## PRIORITÉ 2 — Input texte dans l'UI (ui/index.html)

Ajouter une zone de saisie texte en bas de la zone conversation :

```html
<!-- Zone input texte — juste au-dessus de la status bar -->
<div id="text-input-zone">
  <input 
    type="text" 
    id="text-input" 
    placeholder="Ou écrivez votre message..." 
    autocomplete="off"
  />
  <button id="send-btn" onclick="aria.sendText()">➤</button>
</div>
```

CSS :
```css
#text-input-zone {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 20px;
  background: rgba(8,8,24,0.9);
  border-top: 1px solid rgba(0,212,255,0.2);
  flex-shrink: 0;
}

#text-input {
  flex: 1;
  background: rgba(0,212,255,0.05);
  border: 1px solid rgba(0,212,255,0.3);
  border-radius: 24px;
  padding: 10px 20px;
  color: #E8F4FF;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}

#text-input:focus {
  border-color: #00D4FF;
  box-shadow: 0 0 12px rgba(0,212,255,0.2);
}

#send-btn {
  width: 44px; height: 44px;
  border-radius: 50%;
  background: rgba(0,212,255,0.1);
  border: 1px solid #00D4FF;
  color: #00D4FF;
  font-size: 18px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex; align-items: center; justify-content: center;
}

#send-btn:hover {
  background: rgba(0,212,255,0.25);
  box-shadow: 0 0 12px rgba(0,212,255,0.4);
}
```

JS dans aria object :
```javascript
sendText() {
  const input = document.getElementById('text-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  this.addUserBubble(text);
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.send_text(text);
  }
},
```

Ajouter `send_text` dans AriaAPI (ui.py) :
```python
def send_text(self, text: str) -> None:
    import llm
    import threading
    import ui
    ui.set_status('thinking')
    threading.Thread(target=llm.ask, args=(text,), daemon=True).start()
```

Aussi : appuyer sur Entrée dans le champ texte doit envoyer :
```javascript
document.getElementById('text-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') aria.sendText();
});
```

---

## PRIORITÉ 3 — Lancement d'applications (actions/apps.py)

Réécrire complètement `launch(app_name)` pour être fiable :

```python
import subprocess
import os
import glob
import re
import psutil
import logging
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)

# Chemins hardcodés des apps les plus courantes
KNOWN_APPS = {
    # Jeux et simulateurs
    'msfs': [
        r"C:\Program Files\WindowsApps\Microsoft.FlightSimulator*\FlightSimulator.exe",
        r"C:\Program Files (x86)\Steam\steamapps\common\MicrosoftFlightSimulator\FlightSimulator.exe",
    ],
    'flight simulator': 'msfs',
    'simulateur de vol': 'msfs',
    'steam': r"C:\Program Files (x86)\Steam\Steam.exe",
    'valorant': r"C:\Riot Games\VALORANT\live\VALORANT.exe",
    'no man sky': r"C:\Program Files (x86)\Steam\steamapps\common\No Man's Sky\Binaries\NMS.exe",
    "no man's sky": r"C:\Program Files (x86)\Steam\steamapps\common\No Man's Sky\Binaries\NMS.exe",
    'age of empires': r"C:\Program Files\WindowsApps\Microsoft.MSPhoenix*\RelicCardinal.exe",
    'cossacks': r"C:\Program Files (x86)\Steam\steamapps\common\Cossacks 3\cossacks3.exe",
    
    # Dev
    'cursor': [
        r"C:\Users\mathi\AppData\Local\Programs\cursor\Cursor.exe",
        r"C:\Users\%USERNAME%\AppData\Local\Programs\cursor\Cursor.exe",
    ],
    'vscode': [
        r"C:\Users\mathi\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ],
    'visual studio code': 'vscode',
    
    # Browsers
    'chrome': r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    'firefox': r"C:\Program Files\Mozilla Firefox\firefox.exe",
    'edge': r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    'opera': r"C:\Users\mathi\AppData\Local\Programs\Opera GX\opera.exe",
    'opera gx': r"C:\Users\mathi\AppData\Local\Programs\Opera GX\opera.exe",
    
    # Communication
    'discord': r"C:\Users\mathi\AppData\Local\Discord\app-*\Discord.exe",
    'whatsapp': r"C:\Users\mathi\AppData\Local\WhatsApp\WhatsApp.exe",
    
    # Médias
    'spotify': r"C:\Users\mathi\AppData\Roaming\Spotify\Spotify.exe",
    'vlc': r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    'obs': r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
    
    # Outils
    'notepad': 'notepad.exe',
    'bloc-notes': 'notepad.exe',
    'calculatrice': 'calc.exe',
    'calculette': 'calc.exe',
    'explorateur': 'explorer.exe',
    'gestionnaire de tâches': 'taskmgr.exe',
    'paint': 'mspaint.exe',
    'word': r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
    'excel': r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
    'blender': r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
    'unity': r"C:\Program Files\Unity\Hub\Editor\*\Editor\Unity.exe",
    
    # Système
    'paramètres': 'ms-settings:',
    'store': 'ms-windows-store:',
    'xbox': 'xbox:',
}

def _resolve_path(path_str: str) -> str | None:
    """Résout un chemin avec wildcards et variables d'environnement."""
    if not path_str or path_str.endswith(':'):
        return path_str  # URI protocol — retourner tel quel
    
    # Remplacer %USERNAME%
    path_str = os.path.expandvars(path_str)
    
    # Glob pour wildcards
    if '*' in path_str:
        matches = sorted(glob.glob(path_str))
        if matches:
            return matches[-1]  # Prendre la version la plus récente
        return None
    
    if os.path.exists(path_str):
        return path_str
    
    return None

def _find_in_registry(app_name: str) -> str | None:
    """Cherche une app dans le registre Windows."""
    try:
        import winreg
        keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths",
        ]
        for key_path in keys:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                try:
                    subkey = winreg.OpenKey(key, f"{app_name}.exe")
                    val, _ = winreg.QueryValueEx(subkey, "")
                    if val and os.path.exists(val):
                        return val
                except FileNotFoundError:
                    pass
            except Exception:
                pass
    except Exception:
        pass
    return None

def _search_start_menu(app_name: str) -> str | None:
    """Cherche dans les raccourcis du menu Démarrer."""
    try:
        start_dirs = [
            os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
            r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
        ]
        for start_dir in start_dirs:
            for root, dirs, files in os.walk(start_dir):
                for f in files:
                    if f.lower().endswith('.lnk') and app_name.lower() in f.lower():
                        return os.path.join(root, f)
    except Exception:
        pass
    return None

def launch(app_name: str) -> str:
    """Lance une application par son nom."""
    name_lower = app_name.lower().strip()
    
    # Charger apps custom depuis config
    try:
        import app_paths
        with app_paths.config_path().open('r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        custom_apps = config.get('apps', {})
        for key, path in custom_apps.items():
            if key.lower() in name_lower or name_lower in key.lower():
                resolved = _resolve_path(str(path))
                if resolved:
                    KNOWN_APPS[key.lower()] = resolved
    except Exception:
        pass
    
    # 1. Chercher dans KNOWN_APPS
    target = None
    for key, value in KNOWN_APPS.items():
        if key in name_lower or name_lower in key:
            if isinstance(value, str) and value != key:
                # Peut être un alias
                if value in KNOWN_APPS:
                    value = KNOWN_APPS[value]
                target = value
                break
            elif isinstance(value, list):
                for v in value:
                    resolved = _resolve_path(v)
                    if resolved:
                        target = resolved
                        break
                if target:
                    break
    
    if target and isinstance(target, list):
        for v in target:
            resolved = _resolve_path(v)
            if resolved:
                target = resolved
                break
    
    if target and isinstance(target, str):
        resolved = _resolve_path(target) if '*' in target or '%' in target else target
        if resolved:
            target = resolved
    
    # 2. Chercher dans le registre
    if not target or (isinstance(target, str) and not os.path.exists(target) and not target.endswith(':')):
        reg_path = _find_in_registry(name_lower)
        if reg_path:
            target = reg_path
    
    # 3. Chercher dans le menu Démarrer
    if not target:
        lnk = _search_start_menu(name_lower)
        if lnk:
            target = lnk
    
    # 4. Essayer directement comme commande système
    if not target:
        target = name_lower
    
    # Lancer
    try:
        if isinstance(target, str) and target.endswith(':'):
            # URI protocol (ms-settings:, xbox:, etc.)
            os.startfile(target)
            logger.info("Lancé via URI: %s", target)
            return f"{app_name} ouvert"
        elif isinstance(target, str) and target.endswith('.lnk'):
            os.startfile(target)
            logger.info("Lancé via raccourci: %s", target)
            return f"{app_name} lancé"
        else:
            subprocess.Popen(
                [target],
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )
            logger.info("Lancé: %s", target)
            return f"{app_name} lancé"
    except FileNotFoundError:
        logger.error("App introuvable: %s (résolu: %s)", app_name, target)
        return f"Je n'ai pas trouvé {app_name} sur ton PC"
    except Exception as e:
        logger.error("Erreur lancement %s: %s", app_name, e)
        return f"Erreur au lancement de {app_name}: {e}"

def close(app_name: str) -> str:
    """Ferme une application par son nom."""
    name_lower = app_name.lower()
    closed = []
    
    for proc in psutil.process_iter(['name', 'pid']):
        try:
            proc_name = proc.info['name'].lower()
            if name_lower in proc_name or proc_name.replace('.exe','') in name_lower:
                proc.terminate()
                closed.append(proc.info['name'])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    if closed:
        return f"{', '.join(closed)} fermé(s)"
    return f"Aucun processus trouvé pour {app_name}"

def list_running() -> list[str]:
    """Liste les apps connues qui tournent actuellement."""
    running = []
    known_exes = set()
    for val in KNOWN_APPS.values():
        if isinstance(val, str) and val.endswith('.exe'):
            known_exes.add(Path(val).name.lower())
    
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'].lower() in known_exes:
                running.append(proc.info['name'])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    return list(set(running))

def focus(app_name: str) -> str:
    """Met une app au premier plan."""
    try:
        import pygetwindow as gw
        windows = gw.getWindowsWithTitle(app_name)
        if windows:
            windows[0].activate()
            return f"{app_name} mis au premier plan"
    except Exception as e:
        logger.error("Focus error: %s", e)
    return f"Impossible de mettre {app_name} au premier plan"
```

---

## PRIORITÉ 4 — Détection d'intent pour les apps (llm.py)

S'assurer que les phrases suivantes déclenchent bien `lancer_app` :

Phrases déclenchantes à ajouter dans le system prompt d'intent detection :
- "lance X", "ouvre X", "démarre X", "lance-moi X", "ouvre-moi X"
- "met X", "mets X en route", "démarre X"
- Exemples : "lance MSFS", "ouvre Spotify", "démarre Discord", "lance le simulateur de vol"

Dans le routing llm.py, pour intent `lancer_app` :
```python
elif intent == 'lancer_app':
    app_name = params.get('app', '')
    from actions.apps import launch
    result = launch(app_name)
    tts.speak(result)
    ui.show_toast(result, toast_type='success')
```

---

## PRIORITÉ 5 — Refonte UI complète (ui/index.html)

Réécrire entièrement avec le nouveau layout :

### Layout vertical plein écran
```
header (48px)
visualizer (40vh) — canvas full width, orbe centré énorme
presets (50px) — pills horizontaux centrés  
conversation (flex:1) — remplit l'espace
text-input (60px) — champ texte + bouton envoyer
status-bar (64px) — bouton micro central
```

### Points critiques du design
- Fond : `radial-gradient(ellipse at center, #080820 0%, #04040F 70%)`
- Orbe radius min 100px, max 160px, lerp 0.12
- Waveform en bas du canvas visualiseur, miroir
- Particules 50, réagissent au volume
- Glitch sur le titre toutes les 20-40s
- Bouton micro : 64px, pulse quand actif
- Input texte : pill rounded, focus glow cyan
- Bulles : glassmorphism, animation slide-in
- Settings panel : slide depuis droite 360px
- 6 thèmes via CSS custom properties sur body
- Scan lines via ::after sur body

---

## PRIORITÉ 6 — Correction fermeture (ui/index.html)

Le bouton ✕ doit afficher une modale de confirmation :

```javascript
confirmQuit() {
  const modal = document.getElementById('quit-modal');
  modal.style.display = 'flex';
},
```

```html
<div id="quit-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;align-items:center;justify-content:center;backdrop-filter:blur(4px)">
  <div style="background:#080818;border:1px solid #00D4FF;border-radius:12px;padding:32px;text-align:center;max-width:320px">
    <div style="color:#E8F4FF;font-size:16px;margin-bottom:8px">Fermer ARIA ?</div>
    <div style="color:#6688AA;font-size:12px;margin-bottom:24px">Ollama sera arrêté et la VRAM libérée.</div>
    <div style="display:flex;gap:12px;justify-content:center">
      <button onclick="window.pywebview.api.quit_aria()" style="background:rgba(255,51,102,0.15);border:1px solid #FF3366;color:#FF3366;padding:8px 24px;border-radius:6px;cursor:pointer;font-family:'Courier New',monospace">Oui, fermer</button>
      <button onclick="document.getElementById('quit-modal').style.display='none'" style="background:rgba(0,212,255,0.1);border:1px solid #00D4FF;color:#00D4FF;padding:8px 24px;border-radius:6px;cursor:pointer;font-family:'Courier New',monospace">Annuler</button>
    </div>
  </div>
</div>
```

---

## Prompt Cursor FINAL

> Apply all fixes from this v9 spec. This is the most important update — everything must work end to end.
>
> FILE 1 — stt.py (CRITICAL — mic must work):
> Rewrite _record_loop() completely using the robust version in this spec with:
> - sd.InputStream with latency='high', retry up to 10 times with 2s delay
> - numpy RMS calculation
> - Proper silence detection with SILENCE_LIMIT frames
> - WAV temp file creation with wave module
> - faster-whisper transcription
> - Calls to ui.update_waveform(rms), ui.set_status(), ui.show_user_text(), llm.ask()
> - 1.5s startup delay
> - Proper cleanup in finally block
>
> FILE 2 — actions/apps.py (CRITICAL — app launch must work):
> Rewrite completely using the version in this spec with:
> - KNOWN_APPS dict with all apps including MSFS, Steam, Spotify, Discord, Chrome, Cursor, VSCode, No Man's Sky, Age of Empires, Cossacks, Valorant, OBR, Blender, Unity, Office apps
> - _resolve_path() with glob wildcard support and os.path.expandvars
> - _find_in_registry() Windows registry search
> - _search_start_menu() Start Menu shortcut search
> - launch() with 4-step fallback: KNOWN_APPS → registry → start menu → direct command
> - close() using psutil
> - list_running() 
> - focus() using pygetwindow
>
> FILE 3 — ui/index.html (CRITICAL — beautiful full screen UI):
> Rewrite completely with:
> - Vertical single-column layout: header(48px) → visualizer(40vh) → presets(50px) → conversation(flex:1) → text-input(60px) → statusbar(64px)
> - Full width visualizer canvas with large orb (min 100px, max 160px radius), particles, radar circles, sound rings
> - Waveform embedded in bottom of visualizer canvas
> - Horizontal preset pills row
> - Conversation zone fills remaining space, scrollable, chat bubbles with glassmorphism
> - Text input zone: rounded pill input + send button, Enter key sends
> - Status bar with large 64px mic button that pulses when active
> - Quit confirmation modal
> - 6 themes via CSS custom properties
> - Settings panel slides from right
> - All existing API methods preserved: show, hide, setStatus, updateWaveform, addUserBubble, appendToken, finalizeMessage, showToast, showError, updateWeather
>
> FILE 4 — ui.py:
> Add send_text() method to AriaAPI:
> ```python
> def send_text(self, text: str) -> None:
>     import llm, threading, ui
>     ui.set_status('thinking')
>     threading.Thread(target=llm.ask, args=(text,), daemon=True).start()
> ```
>
> FILE 5 — llm.py:
> Make sure intent 'lancer_app' routing calls actions/apps.launch(params['app']) and speaks the result via tts.speak(). Add these trigger phrases to the intent detection prompt: "lance", "ouvre", "démarre", "ferme", "arrête".
>
> Do NOT touch: main.py, ollama_manager.py, memory.py, tts.py, briefing.py, sounds.py, config.yaml.
> Every function fully implemented. No placeholders. This file will be long — that is expected.
