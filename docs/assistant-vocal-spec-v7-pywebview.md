# Assistant Vocal — Spec v7 : Migration UI vers pywebview + HTML/CSS/JS

## Pourquoi cette migration

tkinter est limité pour les interfaces modernes. pywebview affiche une vraie fenêtre Windows native avec un moteur Chromium intégré — toutes les animations CSS, WebGL, canvas JS fonctionnent nativement. L'interface devient un fichier HTML/CSS/JS pur, beaucoup plus facile à styler et déboguer.

---

## Ce qui change

- `ui.py` → supprimé, remplacé par `ui_webview.py` + `ui/index.html`
- `pywebview` remplace tkinter comme moteur de fenêtre
- Python communique avec le JS via une API exposée (`window.pywebview.api`)
- JS communique avec Python via `window.pywebview.api.method()`
- Tout le reste du projet (main.py, stt.py, llm.py, tts.py, actions/) reste intact
- Renommer `ui_webview.py` en `ui.py` à la fin pour compatibilité

---

## Nouveaux fichiers

```
assistant-vocal/
├── ui.py                    # Remplace l'ancien ui.py — pywebview wrapper
├── ui/
│   ├── index.html           # Interface complète HTML/CSS/JS
│   ├── style.css            # Styles sci-fi (importé dans index.html)
│   └── app.js               # Logique JS (importé dans index.html)
└── assets/
    └── aria.ico             # Icône (déjà présente)
```

---

## Installation

```bash
pip install pywebview
```

pywebview utilise EdgeWebView2 sur Windows (déjà installé sur Windows 11) — pas besoin d'installer Chrome.

---

## ui.py — pywebview wrapper

```python
"""ARIA UI v7 — pywebview wrapper."""

from __future__ import annotations
import json
import logging
import threading
import time
from pathlib import Path
import webview
import app_paths

logger = logging.getLogger(__name__)

_window: webview.Window | None = None
_api: AriaAPI | None = None
_on_deactivate_cb = None
_on_quit_cb = None
_instance: UI | None = None

HTML_PATH = Path(__file__).parent / "ui" / "index.html"


class AriaAPI:
    """API exposée à JavaScript via window.pywebview.api"""

    def __init__(self) -> None:
        self._on_deactivate = None
        self._on_quit = None

    # Appelé par JS quand l'utilisateur clique ✕
    def quit_aria(self) -> None:
        logger.info("Quit demandé par UI")
        if self._on_quit:
            self._on_quit()

    # Appelé par JS quand l'utilisateur clique le toggle on/off
    def toggle_activation(self) -> None:
        if self._on_deactivate:
            self._on_deactivate()

    # Appelé par JS pour sauvegarder les settings
    def save_settings(self, settings_json: str) -> None:
        try:
            settings = json.loads(settings_json)
            state_path = app_paths.data_dir() / "ui_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            with state_path.open("w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
        except Exception:
            logger.exception("Erreur sauvegarde settings")

    # Appelé par JS pour charger les settings
    def load_settings(self) -> str:
        try:
            state_path = app_paths.data_dir() / "ui_state.json"
            if state_path.exists():
                with state_path.open("r", encoding="utf-8") as f:
                    return f.read()
        except Exception:
            pass
        return "{}"

    # Appelé par JS pour activer un preset
    def activate_preset(self, preset_key: str) -> str:
        try:
            from actions import presets
            return presets.activate(preset_key)
        except Exception as e:
            return f"Erreur preset : {e}"

    # Appelé par JS pour effacer l'historique
    def clear_history(self) -> None:
        try:
            import llm
            llm.clear_history()
        except Exception:
            pass

    # Appelé par JS pour ouvrir un fichier dans notepad
    def open_file(self, path: str) -> None:
        import subprocess
        subprocess.Popen(["notepad.exe", path], creationflags=subprocess.CREATE_NO_WINDOW)


class UI:
    def __init__(self, on_deactivate=None, on_quit=None) -> None:
        global _api, _on_deactivate_cb, _on_quit_cb
        _on_deactivate_cb = on_deactivate
        _on_quit_cb = on_quit

        _api = AriaAPI()
        _api._on_deactivate = on_deactivate
        _api._on_quit = on_quit

    def run(self) -> None:
        global _window
        _window = webview.create_window(
            title="ARIA",
            url=str(HTML_PATH.resolve()),
            js_api=_api,
            width=1920,
            height=1080,
            x=0,
            y=0,
            resizable=True,
            fullscreen=False,
            minimized=False,
            on_top=False,           # PAS always on top — fenêtre normale
            frameless=False,        # Garde la barre de titre Windows native
            easy_drag=False,
            background_color="#04040F",
            transparent=False,
        )
        webview.start(
            _on_webview_ready,
            args=(_window,),
            debug=False,
            private_mode=False,
            storage_path=str(app_paths.data_dir() / "webview_cache"),
        )

    # --- Méthodes thread-safe appelées depuis Python → JS ---

    def _js(self, code: str) -> None:
        """Exécute du JS dans la fenêtre de façon thread-safe."""
        if _window:
            try:
                _window.evaluate_js(code)
            except Exception:
                pass

    def show(self) -> None:
        self._js("if(window.aria) aria.show()")

    def hide(self) -> None:
        self._js("if(window.aria) aria.hide()")

    def show_user_text(self, text: str) -> None:
        escaped = text.replace("\\", "\\\\").replace("`", "\\`").replace("'", "\\'")
        self._js(f"if(window.aria) aria.addUserBubble(`{escaped}`)")

    def append_assistant_text(self, token: str) -> None:
        escaped = token.replace("\\", "\\\\").replace("`", "\\`").replace("'", "\\'")
        self._js(f"if(window.aria) aria.appendToken(`{escaped}`)")

    def finalize_assistant_message(self) -> None:
        self._js("if(window.aria) aria.finalizeMessage()")

    def set_status(self, state: str) -> None:
        self._js(f"if(window.aria) aria.setStatus('{state}')")

    def update_waveform(self, rms: float) -> None:
        self._js(f"if(window.aria) aria.updateWaveform({rms:.1f})")

    def show_toast(self, message: str, duration: int = 3000, toast_type: str = "info") -> None:
        escaped = message.replace("'", "\\'")
        self._js(f"if(window.aria) aria.showToast('{escaped}', '{toast_type}', {duration})")

    def show_error(self, text: str) -> None:
        escaped = text.replace("'", "\\'")
        self._js(f"if(window.aria) aria.showError('{escaped}')")

    def show_notification(self, text: str, duration: int = 3) -> None:
        self.show_toast(text, duration * 1000)

    def minimize(self) -> None:
        if _window:
            _window.minimize()


def _on_webview_ready(window: webview.Window) -> None:
    """Appelé quand la fenêtre est prête."""
    logger.info("UI pywebview prête")
    # Maximise la fenêtre au démarrage
    window.maximize()


# --- API module-level (compatibilité avec le reste du projet) ---

def init(on_deactivate=None, on_quit=None) -> UI:
    global _instance
    _instance = UI(on_deactivate=on_deactivate, on_quit=on_quit)
    return _instance

def run() -> None:
    if _instance:
        _instance.run()

def show() -> None:
    if _instance:
        _instance.show()

def hide() -> None:
    if _instance:
        _instance.hide()

def show_user_text(text: str) -> None:
    if _instance:
        _instance.show_user_text(text)

def append_assistant_text(token: str) -> None:
    if _instance:
        _instance.append_assistant_text(token)

def finalize_assistant_message() -> None:
    if _instance:
        _instance.finalize_assistant_message()

def set_status(state: str) -> None:
    if _instance:
        _instance.set_status(state)

def update_waveform(rms: float) -> None:
    if _instance:
        _instance.update_waveform(rms)

def update_info_widget(weather: str = "", time_str: str = "") -> None:
    if _instance and weather:
        escaped = weather.replace("'", "\\'")
        if _instance:
            _instance._js(f"if(window.aria) aria.updateWeather('{escaped}')")

def show_notification(text: str, duration: int = 3) -> None:
    if _instance:
        _instance.show_notification(text, duration)

def show_toast(message: str, duration: int = 3000, toast_type: str = "info") -> None:
    if _instance:
        _instance.show_toast(message, duration, toast_type)

def show_error(text: str) -> None:
    if _instance:
        _instance.show_error(text)
```

---

## ui/index.html

Single-file HTML avec CSS et JS inline. Design sci-fi complet.

### Structure HTML

```html
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ARIA</title>
  <style>
    /* === RESET & BASE === */
    * { margin: 0; padding: 0; box-sizing: border-box; }
    
    :root {
      --bg: #04040F;
      --surface: #080818;
      --accent: #00D4FF;
      --accent2: #7B2FFF;
      --success: #00FF88;
      --alert: #FF3366;
      --warning: #FFB800;
      --text: #E8F4FF;
      --text2: #6688AA;
      --user-bubble: #0D1A2E;
      --assist-bubble: #0A0A20;
      --glow: #00D4FF;
    }

    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Courier New', monospace;
      height: 100vh;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      user-select: none;
    }

    /* === HEADER === */
    #header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 20px;
      background: var(--surface);
      border-bottom: 1px solid var(--accent);
      box-shadow: 0 0 20px rgba(0, 212, 255, 0.15);
      flex-shrink: 0;
    }

    #header-left { display: flex; align-items: center; gap: 14px; }

    #title {
      font-size: 22px;
      font-weight: bold;
      letter-spacing: 6px;
      background: linear-gradient(90deg, var(--accent), var(--accent2));
      background-size: 200%;
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      animation: gradientShift 4s linear infinite;
    }

    @keyframes gradientShift {
      0% { background-position: 0% }
      100% { background-position: 200% }
    }

    #version { font-size: 11px; color: var(--text2); }

    #status-indicator {
      width: 14px; height: 14px;
      border-radius: 50%;
      background: var(--text2);
      box-shadow: 0 0 0 rgba(0,212,255,0);
      transition: background 0.3s, box-shadow 0.3s;
    }

    #status-indicator.listening {
      background: var(--accent);
      animation: pulseGlow 0.6s ease-in-out infinite;
    }
    #status-indicator.transcribing {
      background: var(--warning);
      animation: pulseGlow 0.4s ease-in-out infinite;
    }
    #status-indicator.thinking {
      background: var(--accent2);
      animation: pulseGlow 0.8s ease-in-out infinite;
    }
    #status-indicator.speaking {
      background: var(--success);
      animation: pulseGlow 0.5s ease-in-out infinite;
    }

    @keyframes pulseGlow {
      0%, 100% { box-shadow: 0 0 4px 2px currentColor; }
      50% { box-shadow: 0 0 12px 6px currentColor; }
    }

    #header-btns { display: flex; gap: 8px; }
    .hbtn {
      background: transparent;
      border: 1px solid var(--accent);
      color: var(--text);
      font-family: 'Courier New', monospace;
      font-size: 13px;
      padding: 4px 10px;
      cursor: pointer;
      border-radius: 4px;
      transition: all 0.15s;
    }
    .hbtn:hover { background: rgba(0,212,255,0.12); box-shadow: 0 0 8px var(--accent); }

    /* === INFO BAR === */
    #info-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 6px 20px;
      background: rgba(8,8,24,0.8);
      border-bottom: 1px solid rgba(0,212,255,0.2);
      font-size: 11px;
      color: var(--text2);
      flex-shrink: 0;
    }

    /* === MAIN LAYOUT === */
    #main {
      display: flex;
      flex: 1;
      overflow: hidden;
      gap: 0;
    }

    /* === VISUALIZER PANEL === */
    #vis-panel {
      width: 380px;
      flex-shrink: 0;
      display: flex;
      flex-direction: column;
      border-right: 1px solid rgba(0,212,255,0.2);
      background: var(--surface);
    }

    #vis-canvas {
      width: 100%;
      height: 280px;
      display: block;
    }

    #wave-canvas {
      width: 100%;
      height: 80px;
      display: block;
      border-top: 1px solid rgba(0,212,255,0.15);
    }

    /* === STATS === */
    #stats {
      padding: 12px 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      border-top: 1px solid rgba(0,212,255,0.15);
    }

    .stat-row {
      display: flex;
      justify-content: space-between;
      font-size: 10px;
      color: var(--text2);
    }

    .stat-val { color: var(--accent); }

    /* === PRESETS === */
    #presets {
      padding: 12px;
      border-top: 1px solid rgba(0,212,255,0.15);
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 6px;
    }

    .preset-btn {
      background: rgba(0,212,255,0.05);
      border: 1px solid rgba(0,212,255,0.2);
      color: var(--text);
      font-family: 'Courier New', monospace;
      font-size: 10px;
      padding: 6px 4px;
      cursor: pointer;
      border-radius: 6px;
      text-align: center;
      transition: all 0.15s;
    }

    .preset-btn:hover { background: rgba(0,212,255,0.15); border-color: var(--accent); }
    .preset-btn.active { background: rgba(0,212,255,0.2); border-color: var(--accent); color: var(--accent); }

    /* === CHAT PANEL === */
    #chat-panel {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    #chat-messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      scrollbar-width: thin;
      scrollbar-color: var(--accent) transparent;
    }

    #chat-messages::-webkit-scrollbar { width: 4px; }
    #chat-messages::-webkit-scrollbar-track { background: transparent; }
    #chat-messages::-webkit-scrollbar-thumb { background: var(--accent); border-radius: 2px; }

    .bubble {
      max-width: 75%;
      padding: 12px 16px;
      border-radius: 8px;
      font-size: 13px;
      line-height: 1.6;
      animation: bubbleIn 0.25s ease-out;
      position: relative;
    }

    @keyframes bubbleIn {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .bubble.user {
      align-self: flex-end;
      background: var(--user-bubble);
      border-left: 3px solid var(--accent);
      color: var(--text);
    }

    .bubble.assistant {
      align-self: flex-start;
      background: var(--assist-bubble);
      border-left: 3px solid var(--accent2);
      color: #B8D4FF;
    }

    .bubble-header {
      font-size: 10px;
      color: var(--text2);
      margin-bottom: 6px;
      display: flex;
      justify-content: space-between;
    }

    .bubble-text { white-space: pre-wrap; word-break: break-word; }

    .cursor {
      display: inline-block;
      width: 2px;
      height: 14px;
      background: var(--accent2);
      margin-left: 2px;
      vertical-align: middle;
      animation: blink 0.8s step-end infinite;
    }

    @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

    /* === STATUS BAR === */
    #status-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 20px;
      background: var(--surface);
      border-top: 1px solid var(--accent);
      flex-shrink: 0;
    }

    #status-text {
      font-size: 12px;
      color: var(--text2);
      display: flex;
      align-items: center;
      gap: 8px;
    }

    #status-bar-btns { display: flex; gap: 8px; align-items: center; }

    /* === SETTINGS PANEL === */
    #settings-panel {
      position: fixed;
      top: 0; right: -380px;
      width: 380px;
      height: 100vh;
      background: var(--surface);
      border-left: 1px solid var(--accent);
      z-index: 1000;
      transition: right 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      overflow-y: auto;
      padding: 20px;
      box-shadow: -10px 0 40px rgba(0,212,255,0.1);
    }

    #settings-panel.open { right: 0; }

    .settings-section {
      margin-bottom: 24px;
    }

    .settings-title {
      font-size: 12px;
      color: var(--accent);
      letter-spacing: 2px;
      text-transform: uppercase;
      margin-bottom: 12px;
      border-bottom: 1px solid rgba(0,212,255,0.2);
      padding-bottom: 6px;
    }

    .setting-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 10px;
      font-size: 12px;
      color: var(--text2);
    }

    .setting-row input[type=range] {
      width: 140px;
      accent-color: var(--accent);
    }

    .setting-row select {
      background: var(--bg);
      color: var(--text);
      border: 1px solid var(--accent);
      padding: 3px 6px;
      font-family: 'Courier New', monospace;
      font-size: 11px;
      border-radius: 4px;
    }

    .setting-row input[type=checkbox] { accent-color: var(--accent); }

    .theme-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-bottom: 12px;
    }

    .theme-swatch {
      height: 32px;
      border-radius: 6px;
      border: 2px solid transparent;
      cursor: pointer;
      transition: all 0.15s;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 9px;
      font-family: 'Courier New', monospace;
    }

    .theme-swatch:hover, .theme-swatch.active { border-color: white; }

    .settings-btn {
      width: 100%;
      background: rgba(0,212,255,0.08);
      border: 1px solid var(--accent);
      color: var(--text);
      padding: 8px;
      cursor: pointer;
      border-radius: 4px;
      font-family: 'Courier New', monospace;
      font-size: 11px;
      margin-bottom: 6px;
      transition: all 0.15s;
    }

    .settings-btn:hover { background: rgba(0,212,255,0.2); }

    /* === TOASTS === */
    #toast-container {
      position: fixed;
      bottom: 60px;
      left: 20px;
      display: flex;
      flex-direction: column-reverse;
      gap: 8px;
      z-index: 2000;
      pointer-events: none;
    }

    .toast {
      padding: 10px 16px;
      background: var(--surface);
      border-radius: 6px;
      font-size: 12px;
      color: var(--text);
      animation: toastIn 0.3s ease-out;
      pointer-events: all;
      max-width: 320px;
    }

    .toast.info { border-left: 3px solid var(--accent); }
    .toast.success { border-left: 3px solid var(--success); }
    .toast.warning { border-left: 3px solid var(--warning); }
    .toast.error { border-left: 3px solid var(--alert); }

    @keyframes toastIn {
      from { opacity: 0; transform: translateX(-20px); }
      to { opacity: 1; transform: translateX(0); }
    }

    /* === GLITCH === */
    .glitch {
      animation: glitchAnim 0.15s steps(2) forwards;
    }

    @keyframes glitchAnim {
      0% { transform: translateX(0); filter: hue-rotate(0deg); }
      25% { transform: translateX(-4px); filter: hue-rotate(90deg); }
      50% { transform: translateX(4px); filter: hue-rotate(-90deg); }
      75% { transform: translateX(-2px); filter: hue-rotate(45deg); }
      100% { transform: translateX(0); filter: hue-rotate(0deg); }
    }

    /* === SCAN LINES === */
    body::after {
      content: '';
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: repeating-linear-gradient(
        0deg,
        transparent,
        transparent 2px,
        rgba(0, 212, 255, 0.015) 2px,
        rgba(0, 212, 255, 0.015) 4px
      );
      pointer-events: none;
      z-index: 9999;
    }

    /* === THEMES === */
    body.theme-matrix {
      --accent: #00FF41; --accent2: #00AA22; --glow: #00FF41;
      --bg: #000800; --surface: #001200;
      --text: #CCFFCC; --text2: #448844;
      --user-bubble: #001A00; --assist-bubble: #000F00;
    }

    body.theme-aurora {
      --accent: #7B2FFF; --accent2: #00D4FF; --glow: #00D4FF;
      --bg: #060612; --surface: #0A0A22;
      --text: #E8F4FF; --text2: #8899BB;
      --user-bubble: #12082A; --assist-bubble: #0A1020;
    }

    body.theme-blood {
      --accent: #FF0040; --accent2: #AA0028; --glow: #FF0040;
      --bg: #0A0004; --surface: #140008;
      --text: #FFE8EE; --text2: #AA6677;
      --user-bubble: #1A000A; --assist-bubble: #120006;
    }

    body.theme-gold {
      --accent: #FFD700; --accent2: #B8860B; --glow: #FFD700;
      --bg: #0A0800; --surface: #141004;
      --text: #FFF8E8; --text2: #AA9955;
      --user-bubble: #1A1400; --assist-bubble: #100C00;
    }
  </style>
</head>
<body class="theme-hologram">

<!-- HEADER -->
<div id="header">
  <div id="header-left">
    <div id="status-indicator"></div>
    <div id="title">A·R·I·A</div>
    <div id="version">v2.0</div>
  </div>
  <div id="header-btns">
    <button class="hbtn" onclick="aria.toggleSettings()">≡</button>
    <button class="hbtn" onclick="aria.togglePresets()">◉ PRESETS</button>
    <button class="hbtn" onclick="aria.toggleCompact()">⊡</button>
    <button class="hbtn" onclick="window.pywebview.api.quit_aria()">✕</button>
  </div>
</div>

<!-- INFO BAR -->
<div id="info-bar">
  <span id="weather-display">— Couëron</span>
  <span id="clock-display">--:--:--</span>
</div>

<!-- MAIN -->
<div id="main">

  <!-- VISUALIZER PANEL -->
  <div id="vis-panel">
    <canvas id="vis-canvas"></canvas>
    <canvas id="wave-canvas"></canvas>
    <div id="stats">
      <div class="stat-row"><span>STATUT</span><span class="stat-val" id="stat-status">STANDBY</span></div>
      <div class="stat-row"><span>VOLUME MIC</span><span class="stat-val" id="stat-mic">0%</span></div>
      <div class="stat-row"><span>MODÈLE</span><span class="stat-val">qwen3:14b</span></div>
      <div class="stat-row"><span>THÈME</span><span class="stat-val" id="stat-theme">HOLOGRAM</span></div>
    </div>
    <div id="presets">
      <button class="preset-btn" onclick="aria.activatePreset('vol')">✈ VOL</button>
      <button class="preset-btn" onclick="aria.activatePreset('etude')">📚 ÉTUDE</button>
      <button class="preset-btn" onclick="aria.activatePreset('gaming')">🎮 GAMING</button>
      <button class="preset-btn" onclick="aria.activatePreset('detente')">🎵 DÉTENTE</button>
      <button class="preset-btn" onclick="aria.activatePreset('nuit')">🌙 NUIT</button>
      <button class="preset-btn" onclick="aria.activatePreset('custom')">⚡ CUSTOM</button>
    </div>
  </div>

  <!-- CHAT PANEL -->
  <div id="chat-panel">
    <div id="chat-messages"></div>
  </div>

</div>

<!-- STATUS BAR -->
<div id="status-bar">
  <div id="status-text">
    <span id="status-dot" style="width:10px;height:10px;border-radius:50%;background:var(--text2);display:inline-block"></span>
    <span id="status-label">◉ STANDBY...</span>
  </div>
  <div id="status-bar-btns">
    <button class="hbtn" onclick="aria.toggleSettings()">⚙ SETTINGS</button>
    <button class="hbtn" onclick="aria.cycleTheme()">THEME</button>
  </div>
</div>

<!-- SETTINGS PANEL -->
<div id="settings-panel">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
    <span style="color:var(--accent);font-size:14px;letter-spacing:3px">SETTINGS</span>
    <button class="hbtn" onclick="aria.toggleSettings()">✕</button>
  </div>

  <div class="settings-section">
    <div class="settings-title">Thème</div>
    <div class="theme-grid">
      <div class="theme-swatch active" style="background:linear-gradient(135deg,#00D4FF,#7B2FFF)" onclick="aria.setTheme('hologram')">HOLO</div>
      <div class="theme-swatch" style="background:linear-gradient(135deg,#00FF41,#004410)" onclick="aria.setTheme('matrix')">MATRIX</div>
      <div class="theme-swatch" style="background:linear-gradient(135deg,#7B2FFF,#00D4FF)" onclick="aria.setTheme('aurora')">AURORA</div>
      <div class="theme-swatch" style="background:linear-gradient(135deg,#FF0040,#400010)" onclick="aria.setTheme('blood')">BLOOD</div>
      <div class="theme-swatch" style="background:linear-gradient(135deg,#FFD700,#442200)" onclick="aria.setTheme('gold')">GOLD</div>
      <div class="theme-swatch" style="background:linear-gradient(135deg,#888,#222)" onclick="aria.setTheme('custom')">CUSTOM</div>
    </div>
    <div class="setting-row">
      <span>Opacité</span>
      <input type="range" id="opacity-slider" min="70" max="100" value="95" oninput="aria.setOpacity(this.value)">
    </div>
    <div class="setting-row">
      <span>Scan lines</span>
      <input type="checkbox" id="scanlines-toggle" checked onchange="aria.toggleScanlines(this.checked)">
    </div>
    <div class="setting-row">
      <span>Particules</span>
      <input type="checkbox" id="particles-toggle" checked onchange="aria.toggleParticles(this.checked)">
    </div>
    <div class="setting-row">
      <span>Glitch</span>
      <input type="checkbox" id="glitch-toggle" checked onchange="aria.toggleGlitch(this.checked)">
    </div>
  </div>

  <div class="settings-section">
    <div class="settings-title">Audio</div>
    <div class="setting-row">
      <span>Voix TTS</span>
      <select id="voice-select" onchange="aria.setVoice(this.value)">
        <option value="fr-FR-DeniseNeural">Denise (FR)</option>
        <option value="fr-FR-HenriNeural">Henri (FR)</option>
        <option value="fr-FR-EloiseNeural">Eloise (FR)</option>
      </select>
    </div>
    <div class="setting-row">
      <span>Volume TTS</span>
      <input type="range" id="vol-slider" min="0" max="100" value="90" oninput="aria.setVolume(this.value)">
    </div>
    <div class="setting-row">
      <span>Vitesse TTS</span>
      <input type="range" id="rate-slider" min="-50" max="50" value="5" oninput="aria.setRate(this.value)">
    </div>
  </div>

  <div class="settings-section">
    <div class="settings-title">Assistant</div>
    <button class="settings-btn" onclick="window.pywebview.api.clear_history()">Effacer historique</button>
    <button class="settings-btn" onclick="window.pywebview.api.open_file('data/memory.json')">Voir mémoire</button>
    <button class="settings-btn" onclick="window.pywebview.api.open_file('config.yaml')">Modifier config</button>
  </div>
</div>

<!-- TOASTS -->
<div id="toast-container"></div>

<script>
// === ARIA JS ENGINE ===
const aria = {
  status: 'idle',
  theme: 'hologram',
  compact: false,
  settingsOpen: false,
  rms: 0,
  displayRms: 0,
  orbRadius: 45,
  particles: [],
  scanlines: true,
  particlesOn: true,
  glitchOn: true,
  currentAssistBubble: null,
  currentAssistText: null,
  streamingCursor: null,

  // Canvas refs
  visCtx: null,
  waveCtx: null,
  visW: 0, visH: 0,
  waveW: 0, waveH: 0,
  waveHistory: new Float32Array(200),
  radarAngles: [0, 0, 0],
  rings: [],
  phase: 0,
  glitchNext: Date.now() + 15000 + Math.random() * 30000,

  init() {
    const visCv = document.getElementById('vis-canvas');
    const waveCv = document.getElementById('wave-canvas');
    this.visCtx = visCv.getContext('2d');
    this.waveCtx = waveCv.getContext('2d');

    const resize = () => {
      visCv.width = visCv.offsetWidth;
      visCv.height = visCv.offsetHeight;
      waveCv.width = waveCv.offsetWidth;
      waveCv.height = waveCv.offsetHeight;
      this.visW = visCv.width; this.visH = visCv.height;
      this.waveW = waveCv.width; this.waveH = waveCv.height;
    };
    resize();
    window.addEventListener('resize', resize);

    this.initParticles(60);
    this.loadSettings();
    this.startClock();
    this.startGlitch();
    requestAnimationFrame(() => this.renderLoop());
  },

  initParticles(n) {
    this.particles = Array.from({length: n}, () => ({
      x: Math.random() * this.visW,
      y: Math.random() * this.visH,
      vx: (Math.random() - 0.5) * 0.5,
      vy: (Math.random() - 0.5) * 0.5,
      size: 1 + Math.random() * 2,
      alpha: 0.4 + Math.random() * 0.4,
    }));
  },

  getCSSVar(name) {
    return getComputedStyle(document.body).getPropertyValue(name).trim();
  },

  hexToRgb(hex) {
    const r = parseInt(hex.slice(1,3),16);
    const g = parseInt(hex.slice(3,5),16);
    const b = parseInt(hex.slice(5,7),16);
    return [r,g,b];
  },

  renderLoop() {
    this.phase += 0.01;
    this.radarAngles[0] = (this.radarAngles[0] + 0.3) % 360;
    this.radarAngles[1] = (this.radarAngles[1] + 0.5) % 360;
    this.radarAngles[2] = (this.radarAngles[2] + 0.8) % 360;

    const level = Math.min(1, this.rms / 1000);
    this.displayRms += (level - this.displayRms) * 0.12;
    this.orbRadius += (45 + this.displayRms * 45 - this.orbRadius) * 0.12;

    this.renderVis();
    this.renderWave();
    requestAnimationFrame(() => this.renderLoop());
  },

  renderVis() {
    const ctx = this.visCtx;
    const W = this.visW, H = this.visH;
    const cx = W / 2, cy = H / 2 - 10;
    const accent = this.getCSSVar('--accent');
    const accent2 = this.getCSSVar('--accent2');
    const success = this.getCSSVar('--success');
    const bg = this.getCSSVar('--bg');

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);

    // Rings
    this.rings = this.rings.filter(r => r.alpha > 0.01 && r.radius < 120);
    if (this.status === 'speaking' && Math.random() < 0.1) {
      this.rings.push({radius: 10, alpha: 0.9, speed: 2 + this.displayRms * 2});
    }
    this.rings.forEach(r => {
      ctx.beginPath();
      ctx.arc(cx, cy, r.radius, 0, Math.PI * 2);
      ctx.strokeStyle = success + Math.floor(r.alpha * 255).toString(16).padStart(2,'0');
      ctx.lineWidth = 1.5;
      ctx.stroke();
      r.radius += r.speed;
      r.alpha -= 0.025;
    });

    // Radar circles
    [55, 83, 111].forEach((radius, idx) => {
      const angle = this.radarAngles[idx] * Math.PI / 180;
      ctx.beginPath();
      ctx.arc(cx, cy, radius, angle, angle + Math.PI * 5/3);
      ctx.strokeStyle = accent + '50';
      ctx.lineWidth = 1;
      ctx.stroke();
    });

    // Glow layers
    const glowColors = ['40', '25', '12'];
    [this.orbRadius + 30, this.orbRadius + 18, this.orbRadius + 6].forEach((r, i) => {
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
      grad.addColorStop(0, accent + glowColors[i]);
      grad.addColorStop(1, 'transparent');
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = grad;
      ctx.fill();
    });

    // Orb
    const orbColor = this.displayRms > 0.5 ? '#AAEEFF' : accent;
    ctx.beginPath();
    ctx.arc(cx, cy, this.orbRadius, 0, Math.PI * 2);
    ctx.fillStyle = orbColor;
    ctx.fill();

    // Rotating ring
    const rr = this.orbRadius + 8;
    const startA = this.radarAngles[0] * Math.PI / 180;
    ctx.beginPath();
    ctx.arc(cx, cy, rr, startA, startA + Math.PI * 4/3);
    ctx.strokeStyle = accent;
    ctx.lineWidth = 2;
    ctx.stroke();

    // Particles
    if (this.particlesOn) {
      this.particles.forEach(p => {
        if (this.displayRms > 0.35) {
          const dx = p.x - cx, dy = p.y - cy;
          const dist = Math.max(1, Math.hypot(dx, dy));
          p.vx += (dx/dist) * 0.15 * this.displayRms;
          p.vy += (dy/dist) * 0.15 * this.displayRms;
        } else {
          p.vx *= 0.98; p.vy *= 0.98;
        }
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0 || p.x > W) p.vx *= -1;
        if (p.y < 0 || p.y > H) p.vy *= -1;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = accent + Math.floor(p.alpha * 255).toString(16).padStart(2,'0');
        ctx.fill();
      });
    }

    // Matrix rain
    if (this.theme === 'matrix') {
      if (!this.matrixDrops) {
        this.matrixDrops = Array.from({length: 20}, () => ({
          x: Math.random() * W, y: Math.random() * -H,
          ch: String.fromCharCode(0x30A0 + Math.floor(Math.random() * 96)),
        }));
      }
      ctx.font = '11px Courier New';
      this.matrixDrops.forEach(d => {
        ctx.fillStyle = accent + 'AA';
        ctx.fillText(d.ch, d.x, d.y);
        d.y += 2.5;
        if (d.y > H) { d.y = -10; d.x = Math.random() * W; }
      });
    }

    // Status text
    const labels = {idle:'STANDBY',listening:'LISTENING',transcribing:'PROCESSING',thinking:'PROCESSING',speaking:'SPEAKING'};
    const label = labels[this.status] || 'STANDBY';
    ctx.font = '11px Courier New';
    ctx.fillStyle = this.getCSSVar('--text2');
    ctx.textAlign = 'center';
    ctx.fillText(label.split('').join(' '), cx, cy + this.orbRadius + 20);
    ctx.textAlign = 'left';

    document.getElementById('stat-status').textContent = label;
    document.getElementById('stat-mic').textContent = Math.round(this.displayRms * 100) + '%';
  },

  renderWave() {
    const ctx = this.waveCtx;
    const W = this.waveW, H = this.waveH;
    const accent = this.getCSSVar('--accent');
    const accent2 = this.getCSSVar('--accent2');
    const bg = this.getCSSVar('--surface');

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);

    const mid = H / 2;
    const level = this.displayRms;

    if (this.status === 'speaking') {
      // Equalizer bars
      const bars = 48;
      const bw = W / bars;
      for (let i = 0; i < bars; i++) {
        const val = Math.abs(Math.sin(Date.now() * 0.006 + i * 0.5)) * (0.4 + level * 0.6);
        const bh = val * (H / 2 - 4);
        const t = i / bars;
        ctx.fillStyle = level > 0.5 ? '#AAEEFF' : (t < 0.5 ? accent : accent2);
        ctx.fillRect(i * bw + 1, mid - bh, bw - 2, bh * 2);
      }
    } else {
      // Oscilloscope
      const lineColor = level > 0.5 ? '#AAEEFF' : level > 0.2 ? accent : accent + '66';
      ctx.beginPath();
      ctx.moveTo(0, mid);
      for (let i = 0; i < W; i++) {
        const idx = Math.floor(i / W * this.waveHistory.length);
        const val = this.waveHistory[idx] || 0;
        const amp = Math.min(H / 2 - 4, (val / 1000) * (H / 2 - 4));
        ctx.lineTo(i, mid - amp);
      }
      ctx.strokeStyle = lineColor;
      ctx.lineWidth = level > 0.5 ? 2 : 1;
      ctx.stroke();

      // Mirror
      ctx.beginPath();
      ctx.moveTo(0, mid);
      for (let i = 0; i < W; i++) {
        const idx = Math.floor(i / W * this.waveHistory.length);
        const val = this.waveHistory[idx] || 0;
        const amp = Math.min(H / 2 - 4, (val / 1000) * (H / 2 - 4));
        ctx.lineTo(i, mid + amp);
      }
      ctx.strokeStyle = lineColor + '80';
      ctx.lineWidth = 1;
      ctx.stroke();

      // Idle animation
      if (level < 0.05) {
        ctx.beginPath();
        for (let i = 0; i < W; i++) {
          const y = mid + Math.sin(this.phase * 2 + i * 0.05) * 2;
          i === 0 ? ctx.moveTo(i, y) : ctx.lineTo(i, y);
        }
        ctx.strokeStyle = accent + '33';
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    }
  },

  // === API appelée depuis Python ===

  show() { document.body.style.display = 'flex'; },
  hide() { document.body.style.display = 'none'; },

  setStatus(state) {
    this.status = state;
    const ind = document.getElementById('status-indicator');
    ind.className = '';
    if (state !== 'idle') ind.classList.add(state);

    const dot = document.getElementById('status-dot');
    const colors = {idle:'var(--text2)',listening:'var(--accent)',transcribing:'var(--warning)',thinking:'var(--accent2)',speaking:'var(--success)'};
    dot.style.background = colors[state] || 'var(--text2)';

    const labels = {idle:'STANDBY',listening:'ÉCOUTE ACTIVE',transcribing:'TRANSCRIPTION...',thinking:'RÉFLEXION...',speaking:'ARIA PARLE'};
    const dots = ['...','.. ','.. ','...'][Math.floor(Date.now()/500)%4] || '...';
    document.getElementById('status-label').textContent = '◉ ' + (labels[state] || 'STANDBY') + dots;
  },

  updateWaveform(rms) {
    this.rms = rms;
    this.waveHistory = new Float32Array([...this.waveHistory.slice(1), rms]);
  },

  addUserBubble(text) {
    this.currentAssistBubble = null;
    this.currentAssistText = null;
    const msgs = document.getElementById('chat-messages');
    const ts = new Date().toLocaleTimeString('fr-FR', {hour:'2-digit',minute:'2-digit'});
    const div = document.createElement('div');
    div.className = 'bubble user';
    div.innerHTML = `<div class="bubble-header"><span>◈ Toi</span><span>${ts}</span></div><div class="bubble-text">${this.escHtml(text)}</div>`;
    msgs.appendChild(div);
    this.scrollBottom();
  },

  appendToken(token) {
    if (!this.currentAssistBubble) {
      const msgs = document.getElementById('chat-messages');
      const ts = new Date().toLocaleTimeString('fr-FR', {hour:'2-digit',minute:'2-digit'});
      const div = document.createElement('div');
      div.className = 'bubble assistant';
      div.innerHTML = `<div class="bubble-header"><span>◈ ARIA</span><span>${ts}</span></div><div class="bubble-text"></div>`;
      msgs.appendChild(div);
      this.currentAssistBubble = div;
      this.currentAssistText = div.querySelector('.bubble-text');
      const cursor = document.createElement('span');
      cursor.className = 'cursor';
      this.currentAssistText.appendChild(cursor);
      this.streamingCursor = cursor;
    }
    if (this.streamingCursor) {
      this.streamingCursor.insertAdjacentText('beforebegin', token);
    }
    this.scrollBottom();
  },

  finalizeMessage() {
    if (this.streamingCursor) { this.streamingCursor.remove(); this.streamingCursor = null; }
    this.currentAssistBubble = null;
    this.currentAssistText = null;
  },

  showToast(msg, type='info', duration=3000) {
    const c = document.getElementById('toast-container');
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    t.textContent = msg;
    c.appendChild(t);
    if (c.children.length > 3) c.removeChild(c.children[0]);
    setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity 0.3s'; setTimeout(() => t.remove(), 300); }, duration);
  },

  showError(text) { this.showToast(text, 'error', 5000); },

  updateWeather(text) { document.getElementById('weather-display').textContent = text; },

  toggleSettings() {
    this.settingsOpen = !this.settingsOpen;
    document.getElementById('settings-panel').classList.toggle('open', this.settingsOpen);
  },

  togglePresets() {
    // Presets are always visible in the left panel
    this.showToast('Utilisez les boutons de preset à gauche', 'info');
  },

  toggleCompact() {
    this.compact = !this.compact;
    document.getElementById('vis-panel').style.display = this.compact ? 'none' : 'flex';
  },

  activatePreset(key) {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.activate_preset(key).then(msg => this.showToast(msg, 'success'));
    }
    document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
  },

  setTheme(name) {
    document.body.className = `theme-${name}`;
    this.theme = name;
    document.querySelectorAll('.theme-swatch').forEach(s => s.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById('stat-theme').textContent = name.toUpperCase();
    this.matrixDrops = null;
    this.saveSettings();
  },

  cycleTheme() {
    const themes = ['hologram','matrix','aurora','blood','gold'];
    const idx = themes.indexOf(this.theme);
    this.setTheme(themes[(idx + 1) % themes.length]);
    this.showToast('Thème : ' + this.theme.toUpperCase(), 'info');
  },

  setOpacity(val) {
    // pywebview gère l'opacité via Python si besoin
  },

  toggleScanlines(on) {
    this.scanlines = on;
    document.body.style.setProperty('--scanlines', on ? '1' : '0');
  },

  toggleParticles(on) { this.particlesOn = on; },

  toggleGlitch(on) { this.glitchOn = on; },

  setVoice(voice) {
    // Envoyer à Python si API dispo
  },

  setVolume(val) {},
  setRate(val) {},

  scrollBottom() {
    const msgs = document.getElementById('chat-messages');
    msgs.scrollTo({top: msgs.scrollHeight, behavior: 'smooth'});
  },

  escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  },

  startClock() {
    const tick = () => {
      document.getElementById('clock-display').textContent =
        new Date().toLocaleTimeString('fr-FR');
      setTimeout(tick, 1000);
    };
    tick();
  },

  startGlitch() {
    setInterval(() => {
      if (!this.glitchOn) return;
      if (Date.now() >= this.glitchNext) {
        document.getElementById('title').classList.add('glitch');
        setTimeout(() => document.getElementById('title').classList.remove('glitch'), 150);
        this.glitchNext = Date.now() + 15000 + Math.random() * 30000;
      }
    }, 1000);
  },

  saveSettings() {
    const s = { theme: this.theme, scanlines: this.scanlines, particlesOn: this.particlesOn, glitchOn: this.glitchOn };
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.save_settings(JSON.stringify(s));
    }
  },

  loadSettings() {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.load_settings().then(s => {
        try {
          const data = JSON.parse(s);
          if (data.theme) this.setTheme(data.theme);
        } catch(e) {}
      });
    }
  },
};

// Init quand pywebview est prêt
window.addEventListener('pywebviewready', () => aria.init());
// Fallback si pas pywebview (dev browser)
if (!window.pywebview) { window.addEventListener('load', () => aria.init()); }
</script>
</body>
</html>
```

---

## Mise à jour requirements.txt

```
pywebview
```

---

## Mise à jour build.spec

Ajouter dans `datas` :
```python
('ui', 'ui'),
```

Ajouter dans `hiddenimports` :
```python
'webview',
'webview.platforms.winforms',
```

---

## Mise à jour main.py

Changer l'import `ui` — tout le reste est compatible, l'API est identique.

Dans `main()`, supprimer :
```python
ui.show()
ui.set_status("idle")
```

Ces appels doivent se faire APRÈS que pywebview soit prêt. Utiliser :
```python
# ui.run() bloque jusqu'à fermeture de la fenêtre
# show() et set_status() sont appelés dans _on_webview_ready via JS
```

---

## Prompt Cursor

> Replace ui.py and create ui/index.html as specified in this v7 spec. The old tkinter-based ui.py must be completely replaced with the pywebview wrapper. Create ui/index.html as a single file with all CSS and JS inline. The HTML file must contain the complete sci-fi interface with: animated orb visualizer on canvas, oscilloscope waveform, chat bubbles, preset buttons, settings panel, toast notifications, 6 themes, glitch effects. All Python→JS communication via window.evaluate_js(). All JS→Python communication via window.pywebview.api. Add pywebview to requirements.txt. Update build.spec to include the ui/ folder in datas. Only create/modify: ui.py, ui/index.html, requirements.txt, build.spec. Do not touch main.py or any other file.
