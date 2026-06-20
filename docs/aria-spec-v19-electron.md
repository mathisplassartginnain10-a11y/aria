# ARIA — Spec v19 : Migration complète vers Electron

## Pourquoi Electron ?

| Critère | pywebview actuel | Electron |
|---|---|---|
| Rendu UI | EdgeChromium via WinForms | Chromium natif complet |
| CSS avancé | Partiel (backdrop-filter instable) | 100% supporté |
| Animations | Lentes, parfois saccadées | Fluides (GPU-accelerated) |
| DevTools | Difficile d'accès | F12 natif, React DevTools |
| Packaging | PyInstaller (complexe) | electron-builder (simple) |
| Communication Python↔JS | pywebview.api (lent, sync) | IPC bidirectionnel (rapide, async) |
| Mise à jour | Manuelle | electron-updater automatique |
| Accès système | Via Python uniquement | Via Python + Node.js natif |
| Multi-fenêtres | Limité | Natif |

---

## Architecture cible

```
aria/
├── electron/                    # Application Electron (frontend + shell)
│   ├── main.js                  # Process principal Electron
│   ├── preload.js               # Bridge sécurisé Electron↔Renderer
│   ├── package.json
│   ├── electron-builder.yml     # Config packaging
│   └── renderer/                # L'UI (anciennement ui/index.html)
│       ├── index.html
│       ├── app.js               # Logique JS principale (anciennement inline)
│       └── styles.css           # CSS séparé
│
├── python/                      # Backend Python (inchangé fonctionnellement)
│   ├── main.py                  # Point d'entrée Python — ARIA backend
│   ├── llm.py
│   ├── stt.py
│   ├── tts.py
│   ├── memory_engine.py
│   ├── ollama_manager.py
│   ├── ui_bridge.py             # NOUVEAU — remplace ui.py, communication via IPC
│   ├── app_paths.py
│   ├── config.yaml
│   └── actions/
│       └── ...
│
└── data/                        # Données persistantes (inchangé)
    ├── memory.json
    ├── conversations/
    └── wallpapers/
```

---

## Communication Electron ↔ Python

### Principe

```
Renderer (HTML/JS)
    ↕ contextBridge (preload.js)
Main Process (Electron/Node.js)
    ↕ WebSocket / stdin-stdout
Python Backend (ARIA)
```

On utilise **WebSocket** pour la communication bidirectionnelle :
- Electron démarre le process Python au lancement
- Python ouvre un serveur WebSocket sur `ws://127.0.0.1:9999`
- Electron s'y connecte
- Toutes les communications passent par ce WebSocket (JSON)

### Format des messages

```json
// Renderer → Python (via WebSocket)
{
  "id": "req_001",          // ID unique pour matcher la réponse
  "action": "ask",          // Nom de la fonction Python à appeler
  "args": ["lance chrome"], // Arguments
  "kwargs": {}
}

// Python → Renderer (réponse)
{
  "id": "req_001",          // Même ID que la requête
  "type": "response",
  "data": "Chrome lancé",
  "error": null
}

// Python → Renderer (event unilatéral, sans requête)
{
  "id": null,
  "type": "event",
  "event": "stt_result",   // Nom de l'événement
  "data": "Lance Google Chrome"
}

// Python → Renderer (streaming token par token)
{
  "id": "req_001",
  "type": "stream_token",
  "data": "Bonne"           // Un token à la fois
}

// Python → Renderer (fin de stream)
{
  "id": "req_001",
  "type": "stream_end",
  "data": ""
}
```

---

## FICHIER 1 — python/ui_bridge.py (remplace ui.py)

```python
"""
ui_bridge.py — Serveur WebSocket qui remplace pywebview.
Gère toute la communication entre Python et Electron via WebSocket.
"""
import asyncio
import json
import logging
import threading
import websockets
from typing import Any, Callable

logger = logging.getLogger(__name__)

WS_HOST = "127.0.0.1"
WS_PORT = 9999

# Callbacks enregistrés par les autres modules
_event_handlers: dict[str, list[Callable]] = {}
# Référence à toutes les connexions WebSocket actives
_connections: set = set()
# Boucle asyncio du serveur WS
_loop: asyncio.AbstractEventLoop | None = None


# ── API exposée au renderer (anciennement méthodes de la classe UI) ──────────

EXPOSED_FUNCTIONS: dict[str, Callable] = {}


def expose(func: Callable) -> Callable:
    """Décorateur pour exposer une fonction au renderer JS."""
    EXPOSED_FUNCTIONS[func.__name__] = func
    return func


# ── Emission d'événements vers le renderer ───────────────────────────────────

def emit(event_name: str, data: Any = None) -> None:
    """Envoie un événement unilatéral à tous les renderers connectés."""
    if not _connections:
        return
    msg = json.dumps({"id": None, "type": "event", "event": event_name, "data": data})
    asyncio.run_coroutine_threadsafe(_broadcast(msg), _loop)


async def _broadcast(message: str) -> None:
    for ws in list(_connections):
        try:
            await ws.send(message)
        except Exception:
            _connections.discard(ws)


def emit_stream_token(request_id: str, token: str) -> None:
    """Envoie un token de streaming LLM."""
    msg = json.dumps({"id": request_id, "type": "stream_token", "data": token})
    asyncio.run_coroutine_threadsafe(_broadcast(msg), _loop)


def emit_stream_end(request_id: str) -> None:
    """Signale la fin du streaming."""
    msg = json.dumps({"id": request_id, "type": "stream_end", "data": ""})
    asyncio.run_coroutine_threadsafe(_broadcast(msg), _loop)


# ── Fonctions helper (anciennement méthodes UI) ───────────────────────────────

def set_status(status: str) -> None:
    """Met à jour le statut d'ARIA dans l'UI (idle/listening/thinking/speaking)."""
    emit("status_change", status)


def show_user_text(text: str) -> None:
    """Affiche le texte de l'utilisateur dans le chat."""
    emit("user_message", text)


def append_assistant_text(text: str) -> None:
    """Ajoute du texte à la bulle ARIA en cours."""
    emit("assistant_token", text)


def finalize_assistant_message() -> None:
    """Finalise la bulle ARIA en cours."""
    emit("assistant_done", None)


def show_toast(message: str, toast_type: str = "info") -> None:
    """Affiche une notification toast."""
    emit("toast", {"message": message, "type": toast_type})


def update_waveform(rms: float) -> None:
    """Met à jour l'animation du micro."""
    emit("waveform", rms)


def show_partial_transcription(text: str) -> None:
    """Affiche la transcription partielle (temps réel)."""
    emit("stt_partial", text)


def show_final_transcription(text: str) -> None:
    """Affiche la transcription finale."""
    emit("stt_result", text)


# ── Fonctions exposées au renderer ────────────────────────────────────────────

@expose
def get_available_models() -> dict:
    import ollama_manager
    from llm import MODELS
    try:
        running = ollama_manager.is_running()
        local = ollama_manager.list_local_models() if running else []
    except Exception as e:
        running = False
        local = []
    return {
        "ollama_running": running,
        "local_models": local,
        "configured": dict(MODELS),
    }


@expose
def set_model(role: str, model_name: str) -> dict:
    import yaml, app_paths
    from llm import MODELS
    try:
        cfg_path = app_paths.config_path()
        with cfg_path.open('r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        cfg.setdefault('models', {})[role] = model_name
        with cfg_path.open('w', encoding='utf-8') as f:
            yaml.safe_dump(cfg, f, allow_unicode=True)
        MODELS[role] = model_name
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def ask(text: str, conv_mode: str = 'ecrit', request_id: str = None) -> str:
    """Traite un message utilisateur. Stream les tokens via WebSocket."""
    import llm, memory_engine as _me

    show_user_text(text)
    set_status('thinking')
    _me.add_to_conversation('user', text)

    def on_token(token: str):
        if request_id:
            emit_stream_token(request_id, token)
        else:
            append_assistant_text(token)

    result = llm.ask(text, conv_mode=conv_mode, on_token=on_token)

    if request_id:
        emit_stream_end(request_id)
    else:
        finalize_assistant_message()

    _me.add_to_conversation('assistant', result)
    set_status('idle')
    return result


@expose
def start_mic() -> dict:
    import stt
    if not stt.is_listening():
        stt.start_listening()
    return {"success": True}


@expose
def stop_mic() -> dict:
    import stt
    stt.stop_listening()
    return {"success": True}


@expose
def get_conversations() -> list:
    import memory_engine as _me
    return _me.get_all_conversations()


@expose
def new_conversation() -> dict:
    import memory_engine as _me
    conv_id = _me.create_conversation()
    return {"id": conv_id}


@expose
def load_conversation(conv_id: str) -> dict:
    import memory_engine as _me
    messages = _me.get_conversation_messages(conv_id)
    _me.switch_conversation(conv_id)
    return {"id": conv_id, "messages": messages}


@expose
def delete_conversation(conv_id: str) -> dict:
    import memory_engine as _me
    success = _me.delete_conversation(conv_id)
    return {"success": success}


@expose
def delete_all_conversations() -> dict:
    import memory_engine as _me
    count = _me.delete_all_conversations()
    return {"success": True, "count": count}


@expose
def set_conversation_mode(conv_id: str, mode: str) -> dict:
    import memory_engine as _me
    _me.set_conversation_mode(conv_id, mode)
    return {"success": True}


@expose
def save_wallpaper(base64_data: str, filename: str) -> dict:
    import base64, time, app_paths
    from pathlib import Path
    try:
        wp_dir = app_paths.data_dir() / "wallpapers"
        wp_dir.mkdir(parents=True, exist_ok=True)
        if ',' in base64_data:
            base64_data = base64_data.split(',', 1)[1]
        ext = Path(filename).suffix.lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
            ext = '.jpg'
        safe_name = f"wallpaper_{int(time.time())}{ext}"
        (wp_dir / safe_name).write_bytes(base64.b64decode(base64_data))
        return {"success": True, "filename": safe_name}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def get_wallpapers() -> list:
    import app_paths
    wp_dir = app_paths.data_dir() / "wallpapers"
    if not wp_dir.exists():
        return []
    return [
        {"filename": f.name}
        for f in sorted(wp_dir.iterdir())
        if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.gif')
    ]


@expose
def delete_wallpaper(filename: str) -> dict:
    import app_paths
    from pathlib import Path
    try:
        target = app_paths.data_dir() / "wallpapers" / Path(filename).name
        if target.exists():
            target.unlink()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def get_settings() -> dict:
    import yaml, app_paths
    try:
        with app_paths.config_path().open('r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except:
        return {}


@expose
def save_settings(settings: dict) -> dict:
    import yaml, app_paths
    try:
        with app_paths.config_path().open('w', encoding='utf-8') as f:
            yaml.safe_dump(settings, f, allow_unicode=True)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def speak_text(text: str) -> dict:
    import tts
    tts.speak(text, force=True)
    return {"success": True}


@expose
def get_installed_apps() -> list:
    """Scanne les apps installées (registre + menu démarrer + Steam)."""
    import os, winreg, subprocess
    apps = set()

    # Registre Windows
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, path in keys:
        try:
            key = winreg.OpenKey(hive, path)
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                    try:
                        name, _ = winreg.QueryValueEx(sub, "DisplayName")
                        if name and 1 < len(name) < 60:
                            apps.add(name.strip())
                    except FileNotFoundError:
                        pass
                except Exception:
                    pass
        except Exception:
            pass

    # Menu Démarrer
    for d in [
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
    ]:
        for root, _, files in os.walk(d):
            for f in files:
                if f.endswith('.lnk') and 1 < len(f) < 63:
                    apps.add(f[:-4].strip())

    return sorted(apps, key=str.lower)


# ── Serveur WebSocket ─────────────────────────────────────────────────────────

async def _handle_connection(websocket) -> None:
    """Gère une connexion WebSocket entrante."""
    _connections.add(websocket)
    logger.info("Electron connecté (total: %d)", len(_connections))
    try:
        async for message in websocket:
            await _handle_message(websocket, message)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        _connections.discard(websocket)
        logger.info("Electron déconnecté (total: %d)", len(_connections))


async def _handle_message(websocket, raw: str) -> None:
    """Traite un message entrant du renderer."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Message JSON invalide: %s", raw[:100])
        return

    request_id = msg.get("id")
    action = msg.get("action")
    args = msg.get("args", [])
    kwargs = msg.get("kwargs", {})

    logger.debug("IPC reçu: %s(%s)", action, args[:1] if args else "")

    if action not in EXPOSED_FUNCTIONS:
        await websocket.send(json.dumps({
            "id": request_id,
            "type": "response",
            "data": None,
            "error": f"Action inconnue: {action}"
        }))
        return

    func = EXPOSED_FUNCTIONS[action]

    # Passer le request_id aux fonctions qui font du streaming
    if action == 'ask' and request_id:
        kwargs['request_id'] = request_id

    try:
        # Exécuter dans un thread séparé pour ne pas bloquer la boucle asyncio
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: func(*args, **kwargs)
        )
        await websocket.send(json.dumps({
            "id": request_id,
            "type": "response",
            "data": result,
            "error": None,
        }))
    except Exception as e:
        logger.error("Erreur action %s: %s", action, e, exc_info=True)
        await websocket.send(json.dumps({
            "id": request_id,
            "type": "response",
            "data": None,
            "error": str(e),
        }))


async def _run_server() -> None:
    global _loop
    _loop = asyncio.get_event_loop()
    async with websockets.serve(_handle_connection, WS_HOST, WS_PORT):
        logger.info("Serveur WebSocket ARIA démarré sur ws://%s:%d", WS_HOST, WS_PORT)
        await asyncio.Future()  # Tourne indéfiniment


def start() -> None:
    """Démarre le serveur WebSocket dans un thread daemon."""
    def _run():
        asyncio.run(_run_server())

    t = threading.Thread(target=_run, daemon=True, name="ARIA-WebSocket")
    t.start()
    logger.info("Thread WebSocket démarré")
```
## FICHIER 2 — electron/main.js

```javascript
/**
 * main.js — Process principal Electron
 * Lance le backend Python, gère la fenêtre, le tray icon.
 */

const { app, BrowserWindow, Tray, Menu, ipcMain, shell } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const WebSocket = require('ws');
const fs = require('fs');

// ── Configuration ─────────────────────────────────────────────────────────────

const WS_PORT = 9999;
const PYTHON_BACKEND = path.join(__dirname, '..', 'python', 'main.py');
const PYTHON_EXE = process.platform === 'win32'
  ? path.join(__dirname, '..', 'python', '.venv', 'Scripts', 'python.exe')
  : path.join(__dirname, '..', 'python', '.venv', 'bin', 'python3');

// ── État global ───────────────────────────────────────────────────────────────

let mainWindow = null;
let tray = null;
let pythonProcess = null;
let wsClient = null;
let wsReady = false;
let pendingMessages = [];

// ── Lancement du backend Python ───────────────────────────────────────────────

function startPythonBackend() {
  console.log('[Electron] Lancement backend Python:', PYTHON_BACKEND);

  const env = {
    ...process.env,
    PYTHONUTF8: '1',
    ARIA_WS_PORT: String(WS_PORT),
    ARIA_ELECTRON_MODE: '1',
  };

  pythonProcess = spawn(PYTHON_EXE, [PYTHON_BACKEND], {
    env,
    stdio: ['pipe', 'pipe', 'pipe'],
    cwd: path.join(__dirname, '..', 'python'),
  });

  pythonProcess.stdout.on('data', (data) => {
    const lines = data.toString().split('\n');
    lines.forEach(line => {
      if (line.trim()) console.log('[Python]', line);
    });
  });

  pythonProcess.stderr.on('data', (data) => {
    const lines = data.toString().split('\n');
    lines.forEach(line => {
      if (line.trim()) console.error('[Python ERR]', line);
    });
  });

  pythonProcess.on('exit', (code) => {
    console.log(`[Python] Processus terminé (code: ${code})`);
    pythonProcess = null;
    wsClient = null;
    wsReady = false;
  });

  // Tenter la connexion WebSocket après 2s (laisser Python démarrer)
  setTimeout(connectWebSocket, 2000);
}

// ── Connexion WebSocket vers Python ──────────────────────────────────────────

function connectWebSocket(retries = 15) {
  console.log(`[Electron] Connexion WebSocket ws://127.0.0.1:${WS_PORT}...`);

  const ws = new WebSocket(`ws://127.0.0.1:${WS_PORT}`);

  ws.on('open', () => {
    console.log('[Electron] WebSocket connecté');
    wsClient = ws;
    wsReady = true;

    // Envoyer les messages en attente
    pendingMessages.forEach(msg => ws.send(msg));
    pendingMessages = [];

    // Notifier le renderer que le backend est prêt
    if (mainWindow) {
      mainWindow.webContents.send('backend-ready');
    }
  });

  ws.on('message', (data) => {
    try {
      const msg = JSON.parse(data.toString());
      // Relayer le message au renderer
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('ws-message', msg);
      }
    } catch (e) {
      console.error('[Electron] Erreur parse WS:', e);
    }
  });

  ws.on('close', () => {
    console.log('[Electron] WebSocket déconnecté');
    wsClient = null;
    wsReady = false;
  });

  ws.on('error', (err) => {
    console.log(`[Electron] WebSocket erreur (retries restants: ${retries}):`, err.message);
    ws.terminate();

    if (retries > 0) {
      setTimeout(() => connectWebSocket(retries - 1), 1000);
    } else {
      console.error('[Electron] Impossible de se connecter au backend Python');
      if (mainWindow) {
        mainWindow.webContents.send('backend-error', 'Impossible de démarrer le backend Python');
      }
    }
  });
}

// ── IPC Main → Renderer messages depuis le process principal ──────────────────

// Le renderer envoie une action Python via IPC
ipcMain.handle('python-call', async (event, { id, action, args, kwargs }) => {
  const msg = JSON.stringify({ id, action, args: args || [], kwargs: kwargs || {} });

  if (wsReady && wsClient) {
    wsClient.send(msg);
    return { queued: false };
  } else {
    // Mettre en file d'attente
    pendingMessages.push(msg);
    return { queued: true };
  }
});

// Le renderer demande d'ouvrir un lien externe dans le navigateur
ipcMain.on('open-external', (event, url) => {
  shell.openExternal(url);
});

// Quitter proprement
ipcMain.on('quit-app', () => {
  app.quit();
});

// ── Création de la fenêtre principale ─────────────────────────────────────────

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    backgroundColor: '#0C0C0F',
    titleBarStyle: 'hiddenInset',  // Barre de titre intégrée (macOS-like)
    frame: false,                   // Pas de barre de titre Windows
    transparent: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      webSecurity: true,
    },
    icon: path.join(__dirname, 'assets', 'icon.png'),
    show: false,  // Ne pas afficher avant que l'UI soit prête
  });

  // Charger l'UI
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  // Afficher quand prêt (évite le flash blanc)
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    // Ouvrir DevTools en développement
    if (process.env.ARIA_DEV) {
      mainWindow.webContents.openDevTools();
    }
  });

  // Masquer au lieu de fermer (tray icon)
  mainWindow.on('close', (event) => {
    if (!app.isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ── Tray Icon ─────────────────────────────────────────────────────────────────

function createTray() {
  const iconPath = path.join(__dirname, 'assets', 'tray-icon.png');
  tray = new Tray(iconPath);

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'ARIA',
      enabled: false,
      icon: path.join(__dirname, 'assets', 'icon-small.png'),
    },
    { type: 'separator' },
    {
      label: 'Ouvrir',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      },
    },
    {
      label: 'Microphone',
      submenu: [
        { label: 'Activer', click: () => sendToPython('start_mic', []) },
        { label: 'Désactiver', click: () => sendToPython('stop_mic', []) },
      ],
    },
    { type: 'separator' },
    {
      label: 'Quitter ARIA',
      click: () => {
        app.isQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);
  tray.setToolTip('ARIA — Assistant Personnel');

  tray.on('click', () => {
    if (mainWindow) {
      mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show();
    }
  });
}

// ── Helper : envoyer une action Python sans attendre de réponse ───────────────

function sendToPython(action, args = [], kwargs = {}) {
  const msg = JSON.stringify({
    id: `sys_${Date.now()}`,
    action,
    args,
    kwargs,
  });
  if (wsReady && wsClient) {
    wsClient.send(msg);
  } else {
    pendingMessages.push(msg);
  }
}

// ── Cycle de vie de l'application ─────────────────────────────────────────────

app.whenReady().then(() => {
  createWindow();
  createTray();
  startPythonBackend();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    } else if (mainWindow) {
      mainWindow.show();
    }
  });
});

app.on('before-quit', () => {
  app.isQuitting = true;

  // Arrêter proprement le backend Python
  if (pythonProcess) {
    try {
      // Envoyer une commande d'arrêt propre
      sendToPython('shutdown', []);
      setTimeout(() => {
        if (pythonProcess) {
          pythonProcess.kill('SIGTERM');
        }
      }, 3000);
    } catch (e) {
      pythonProcess.kill();
    }
  }
});

app.on('window-all-closed', () => {
  // Sur Windows/Linux, quitter quand toutes les fenêtres sont fermées
  // Sauf si on veut rester dans le tray
  // app.quit(); // Décommenter pour quitter au lieu de rester dans le tray
});
```

---

## FICHIER 3 — electron/preload.js

```javascript
/**
 * preload.js — Bridge sécurisé entre le renderer et le process principal.
 * Expose uniquement les APIs nécessaires via contextBridge.
 */

const { contextBridge, ipcRenderer } = require('electron');

// Compteur pour générer des IDs de requête uniques
let reqCounter = 0;

// Map des callbacks en attente de réponse
const pendingRequests = new Map();
const streamCallbacks = new Map();

// Écouter les messages du process principal (relayés depuis Python)
ipcRenderer.on('ws-message', (event, msg) => {
  const { id, type, data, event: eventName, error } = msg;

  if (type === 'response' && id && pendingRequests.has(id)) {
    const { resolve, reject } = pendingRequests.get(id);
    pendingRequests.delete(id);
    if (error) {
      reject(new Error(error));
    } else {
      resolve(data);
    }

  } else if (type === 'stream_token' && id && streamCallbacks.has(id)) {
    const { onToken } = streamCallbacks.get(id);
    onToken(data);

  } else if (type === 'stream_end' && id && streamCallbacks.has(id)) {
    const { onEnd } = streamCallbacks.get(id);
    streamCallbacks.delete(id);
    onEnd();

  } else if (type === 'event' && eventName) {
    // Déclencher un CustomEvent dans le renderer
    window.dispatchEvent(new CustomEvent(`aria:${eventName}`, { detail: data }));
  }
});

// Écouter la disponibilité du backend
ipcRenderer.on('backend-ready', () => {
  window.dispatchEvent(new CustomEvent('aria:backend-ready'));
});

ipcRenderer.on('backend-error', (event, message) => {
  window.dispatchEvent(new CustomEvent('aria:backend-error', { detail: message }));
});

// ── API exposée au renderer ────────────────────────────────────────────────────

contextBridge.exposeInMainWorld('ARIA', {
  /**
   * Appelle une fonction Python et retourne une Promise.
   */
  call: (action, ...args) => {
    const id = `req_${++reqCounter}_${Date.now()}`;
    return new Promise((resolve, reject) => {
      pendingRequests.set(id, { resolve, reject });
      ipcRenderer.invoke('python-call', { id, action, args, kwargs: {} })
        .catch(reject);

      // Timeout de 60s
      setTimeout(() => {
        if (pendingRequests.has(id)) {
          pendingRequests.delete(id);
          reject(new Error(`Timeout pour l'action: ${action}`));
        }
      }, 60000);
    });
  },

  /**
   * Appelle une fonction Python en streaming (tokens LLM).
   * onToken(token) : appelé pour chaque token
   * onEnd() : appelé à la fin
   */
  stream: (action, args, { onToken, onEnd }) => {
    const id = `req_${++reqCounter}_${Date.now()}`;
    streamCallbacks.set(id, { onToken, onEnd });
    ipcRenderer.invoke('python-call', { id, action, args, kwargs: {} })
      .catch(onEnd);
    return id;
  },

  /**
   * Écoute un événement Python (unilatéral).
   */
  on: (eventName, callback) => {
    const handler = (e) => callback(e.detail);
    window.addEventListener(`aria:${eventName}`, handler);
    return () => window.removeEventListener(`aria:${eventName}`, handler);
  },

  /**
   * Ouvre un lien dans le navigateur système.
   */
  openExternal: (url) => {
    ipcRenderer.send('open-external', url);
  },

  /**
   * Contrôles de la fenêtre.
   */
  window: {
    minimize: () => ipcRenderer.send('window-minimize'),
    maximize: () => ipcRenderer.send('window-maximize'),
    close: () => ipcRenderer.send('window-close'),
    quit: () => ipcRenderer.send('quit-app'),
  },
});
```

---

## FICHIER 4 — electron/package.json

```json
{
  "name": "aria-assistant",
  "version": "1.0.0",
  "description": "ARIA — Assistant Personnel IA Local",
  "main": "main.js",
  "scripts": {
    "start": "electron .",
    "dev": "ARIA_DEV=1 electron .",
    "build": "electron-builder",
    "build:win": "electron-builder --win",
    "pack": "electron-builder --dir"
  },
  "dependencies": {
    "ws": "^8.16.0"
  },
  "devDependencies": {
    "electron": "^31.0.0",
    "electron-builder": "^24.13.0"
  },
  "build": {
    "appId": "com.aria.assistant",
    "productName": "ARIA",
    "directories": {
      "output": "../dist"
    },
    "win": {
      "target": ["nsis", "portable"],
      "icon": "assets/icon.ico"
    },
    "nsis": {
      "oneClick": false,
      "allowToChangeInstallationDirectory": true,
      "installerLanguages": ["French"],
      "language": "1036"
    },
    "extraResources": [
      {
        "from": "../python",
        "to": "python",
        "filter": [
          "**/*",
          "!**/__pycache__/**",
          "!**/.venv/**",
          "!**/node_modules/**"
        ]
      },
      {
        "from": "../data",
        "to": "data",
        "filter": ["checklists/**", "*.yaml"]
      }
    ]
  }
}
```
## FICHIER 5 — electron/renderer/index.html

```html
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy"
    content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
             img-src 'self' data: blob: http://127.0.0.1:*;
             connect-src ws://127.0.0.1:*;">
  <title>ARIA</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>

<!-- Barre de titre custom (sans frame natif) -->
<div id="title-bar">
  <div id="title-bar-drag"></div>
  <div id="window-controls">
    <button onclick="ARIA.window.minimize()" title="Réduire">─</button>
    <button onclick="ARIA.window.maximize()" title="Agrandir">□</button>
    <button onclick="ARIA.window.close()" class="close-btn" title="Fermer">✕</button>
  </div>
</div>

<!-- Fond d'écran -->
<div id="wallpaper-layer">
  <div id="wallpaper-image"></div>
  <div id="wallpaper-overlay"></div>
</div>

<!-- Indicateur focus mode -->
<div id="focus-indicator">🎯 Mode focus</div>

<!-- Layout principal -->
<div id="app-layout">

  <!-- Sidebar -->
  <aside id="sidebar">
    <!-- Logo + statut -->
    <div id="sidebar-header">
      <div id="aria-logo" class="logo-idle">
        <svg viewBox="0 0 64 64" width="44" height="44">
          <defs>
            <linearGradient id="logoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#6C8EFF"/>
              <stop offset="100%" stop-color="#A78BFA"/>
            </linearGradient>
            <linearGradient id="scanGrad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="rgba(108,142,255,0)"/>
              <stop offset="50%" stop-color="rgba(108,142,255,0.9)"/>
              <stop offset="100%" stop-color="rgba(108,142,255,0)"/>
            </linearGradient>
          </defs>
          <g class="logo-ticks">
            <line x1="32" y1="2" x2="32" y2="6" class="tick" style="--i:0"/>
            <line x1="32" y1="58" x2="32" y2="62" class="tick" style="--i:1"/>
            <line x1="2" y1="32" x2="6" y2="32" class="tick" style="--i:2"/>
            <line x1="58" y1="32" x2="62" y2="32" class="tick" style="--i:3"/>
            <line x1="11" y1="11" x2="14" y2="14" class="tick" style="--i:4"/>
            <line x1="53" y1="11" x2="50" y2="14" class="tick" style="--i:5"/>
            <line x1="11" y1="53" x2="14" y2="50" class="tick" style="--i:6"/>
            <line x1="53" y1="53" x2="50" y2="50" class="tick" style="--i:7"/>
          </g>
          <circle class="logo-scan" cx="32" cy="32" r="29" fill="none" stroke="url(#scanGrad)" stroke-width="2" stroke-dasharray="15 200" stroke-linecap="round"/>
          <circle class="logo-arc logo-arc-1" cx="32" cy="32" r="29" fill="none" stroke="url(#logoGrad)" stroke-width="1.5" stroke-dasharray="100 82" stroke-linecap="round"/>
          <circle class="logo-arc logo-arc-2" cx="32" cy="32" r="23" fill="none" stroke="rgba(108,142,255,0.5)" stroke-width="1.5" stroke-dasharray="70 75" stroke-linecap="round"/>
          <circle class="logo-arc logo-arc-3" cx="32" cy="32" r="17" fill="none" stroke="rgba(167,139,250,0.4)" stroke-width="1" stroke-dasharray="50 56" stroke-linecap="round"/>
          <circle class="logo-core" cx="32" cy="32" r="9" fill="url(#logoGrad)"/>
          <path class="logo-mark" d="M32 26 L37 38 L34 38 L32.5 34 L31.5 34 L30 38 L27 38 Z" fill="rgba(12,12,15,0.9)"/>
        </svg>
      </div>
      <div>
        <div id="assistant-name">ARIA</div>
        <div id="status-text">En veille</div>
      </div>
    </div>

    <!-- Nouvelle conversation -->
    <button id="new-conv-btn" onclick="app.newConversation()">
      + Nouvelle conversation
    </button>

    <!-- Liste des conversations -->
    <div id="conversations-list"></div>

    <!-- Bouton tout supprimer -->
    <button id="delete-all-btn" onclick="app.deleteAllConversations()">
      🗑️ Tout supprimer
    </button>
  </aside>

  <!-- Zone principale -->
  <main id="main-area">

    <!-- Header -->
    <header id="header">
      <div id="header-left">
        <span id="conv-title">Nouvelle conversation</span>
      </div>
      <div id="header-right">
        <button id="export-btn" onclick="app.exportConversation()" title="Exporter PDF">📄</button>
        <button id="settings-btn" onclick="app.toggleSettings()" title="Paramètres">⚙️</button>
      </div>
    </header>

    <!-- Zone de messages -->
    <div id="messages-container">
      <div id="messages"></div>
    </div>

    <!-- Zone de saisie -->
    <div id="input-area">
      <div id="input-zone">
        <!-- Bouton micro -->
        <div id="mic-orb-container">
          <div class="mic-ring" id="mic-ring-1"></div>
          <div class="mic-ring" id="mic-ring-2"></div>
          <div class="mic-ring" id="mic-ring-3"></div>
          <button id="mic-btn" onclick="app.toggleMic()" class="mic-idle" title="Micro (activer/désactiver)">
            🎤
          </button>
        </div>

        <!-- Champ texte -->
        <textarea
          id="text-input"
          placeholder="Message..."
          rows="1"
          onkeydown="app.handleInputKeydown(event)"
          oninput="app.adjustTextarea(this)"
        ></textarea>

        <!-- Bouton fichier -->
        <label id="file-btn" title="Joindre des fichiers">
          📎
          <input
            type="file"
            id="file-input"
            multiple
            accept="image/*,video/*,.pdf,.txt,.py,.js,.html,.css,.json,.yaml,.md,.csv"
            style="display:none"
            onchange="app.handleFiles(this.files)"
          >
        </label>

        <!-- Bouton envoyer -->
        <button id="send-btn" onclick="app.sendMessage()" title="Envoyer">➤</button>
      </div>
    </div>

  </main>

  <!-- Panneau paramètres -->
  <aside id="settings-panel" class="hidden">
    <div id="settings-header">
      <span>Paramètres</span>
      <button onclick="app.toggleSettings()">✕</button>
    </div>

    <div id="settings-content">

      <!-- Apparence -->
      <div class="settings-accordion open" id="acc-apparence">
        <div class="acc-header" onclick="app.toggleAccordion('apparence')">
          🎨 Apparence <span class="acc-chevron">▾</span>
        </div>
        <div class="acc-body">
          <div class="setting-row">
            <label>Thème</label>
            <div class="theme-pills">
              <button onclick="app.setTheme('slate')" class="theme-pill active" data-theme="slate">Slate</button>
              <button onclick="app.setTheme('warm')" class="theme-pill" data-theme="warm">Warm</button>
              <button onclick="app.setTheme('forest')" class="theme-pill" data-theme="forest">Forest</button>
              <button onclick="app.setTheme('rose')" class="theme-pill" data-theme="rose">Rose</button>
            </div>
          </div>
          <div class="setting-row">
            <label>Transparence</label>
            <input type="range" id="set-glass" min="0" max="100" value="60"
              oninput="app.setGlassIntensity(this.value)">
          </div>
          <!-- Wallpapers -->
          <div class="setting-label">Fond d'écran</div>
          <div class="wallpaper-presets">
            <div class="wp-thumb wp-aurora" onclick="app.setWallpaper('aurora')" title="Aurora"></div>
            <div class="wp-thumb wp-sunset" onclick="app.setWallpaper('sunset')" title="Sunset"></div>
            <div class="wp-thumb wp-midnight" onclick="app.setWallpaper('midnight')" title="Midnight"></div>
            <div class="wp-thumb wp-forest" onclick="app.setWallpaper('forest')" title="Forest"></div>
            <div class="wp-thumb wp-mesh" onclick="app.setWallpaper('mesh')" title="Mesh"></div>
            <div class="wp-thumb wp-mono" onclick="app.setWallpaper('mono')" title="Mono"></div>
          </div>
          <div id="wallpaper-custom-grid"></div>
          <label class="settings-btn-outline">
            📷 Importer une image
            <input type="file" accept="image/*" style="display:none"
              onchange="app.uploadWallpaper(this.files[0]);this.value=''">
          </label>
        </div>
      </div>

      <!-- Voix -->
      <div class="settings-accordion" id="acc-voix">
        <div class="acc-header" onclick="app.toggleAccordion('voix')">
          🎙️ Voix <span class="acc-chevron">▸</span>
        </div>
        <div class="acc-body hidden">
          <div class="setting-row">
            <label>TTS activé</label>
            <input type="checkbox" id="set-tts" onchange="app.saveSetting('tts_enabled', this.checked)">
          </div>
          <div class="setting-row">
            <label>Vitesse</label>
            <input type="range" id="set-tts-rate" min="-50" max="50" value="0"
              oninput="app.saveSetting('tts_rate', parseInt(this.value))">
          </div>
        </div>
      </div>

      <!-- Modèles IA -->
      <div class="settings-accordion" id="acc-modeles">
        <div class="acc-header" onclick="app.toggleAccordion('modeles')">
          🤖 Modèles IA <span class="acc-chevron">▸</span>
        </div>
        <div class="acc-body hidden">
          <div id="model-settings">
            <div class="loading-text">Cliquer pour charger...</div>
          </div>
          <button class="settings-btn-outline" onclick="app.loadModelSettings()" style="margin-top:8px">
            🔄 Rafraîchir
          </button>
        </div>
      </div>

      <!-- Micro -->
      <div class="settings-accordion" id="acc-micro">
        <div class="acc-header" onclick="app.toggleAccordion('micro')">
          🎤 Micro <span class="acc-chevron">▸</span>
        </div>
        <div class="acc-body hidden">
          <div class="setting-row">
            <label>Device index</label>
            <input type="number" id="set-device-index" placeholder="auto"
              onchange="app.saveSetting('stt.device_index', parseInt(this.value) || null)">
          </div>
          <div class="setting-row">
            <label>Modèle Whisper</label>
            <select id="set-whisper-model" onchange="app.saveSetting('stt.model', this.value)">
              <option value="tiny">Tiny (rapide)</option>
              <option value="base">Base</option>
              <option value="small" selected>Small ★</option>
              <option value="medium">Medium (précis)</option>
            </select>
          </div>
          <button class="settings-btn-outline" onclick="app.runMicDiagnostic()">
            🔍 Diagnostiquer le micro
          </button>
        </div>
      </div>

      <!-- Système -->
      <div class="settings-accordion" id="acc-systeme">
        <div class="acc-header" onclick="app.toggleAccordion('systeme')">
          ⚙️ Système <span class="acc-chevron">▸</span>
        </div>
        <div class="acc-body hidden">
          <div class="setting-row">
            <label>Brief quotidien</label>
            <input type="checkbox" id="set-daily-brief"
              onchange="app.saveSetting('daily_brief_enabled', this.checked)">
          </div>
          <div class="setting-row">
            <label>Tuer Ollama à la fermeture</label>
            <input type="checkbox" id="set-kill-ollama" checked
              onchange="app.saveSetting('kill_ollama_on_exit', this.checked)">
          </div>
          <div class="nexus-status">
            <span>Nexus (code)</span>
            <span id="nexus-badge">Non configuré</span>
          </div>
        </div>
      </div>

    </div>
  </aside>

</div>

<!-- Modal sélection mode -->
<div id="mode-select-overlay" class="hidden">
  <div id="mode-select-card">
    <div id="mode-select-logo"><!-- Logo SVG mini --></div>
    <div id="mode-select-title">Comment veux-tu échanger ?</div>
    <div id="mode-select-buttons">
      <button onclick="app.selectConversationMode('ecrit')">
        <span>💬</span>
        <span>Écrit</span>
      </button>
      <button onclick="app.selectConversationMode('vocal')">
        <span>🎙️</span>
        <span>Vocal</span>
      </button>
    </div>
  </div>
</div>

<!-- Toast container -->
<div id="toast-container"></div>

<script src="app.js"></script>
</body>
</html>
```
## FICHIER 6 — electron/renderer/app.js

```javascript
/**
 * app.js — Logique de l'application ARIA (renderer process)
 * Remplace tout le JS inline de l'ancien index.html
 */

// ── État global de l'application ──────────────────────────────────────────────

const state = {
  currentConvId: null,
  conversationMode: 'ecrit',
  micActive: false,
  micPaused: false,
  ttsEnabled: false,
  backendReady: false,
  settings: {},
  _vocalCountdownTimer: null,
  _originalTranscription: '',
  _staticPort: 9998,  // Port du serveur de fichiers statiques Python
  _streamingMessage: null,  // Élément DOM de la bulle ARIA en cours de streaming
};

// ── API Python ────────────────────────────────────────────────────────────────

const api = {
  call: (action, ...args) => window.ARIA.call(action, ...args),
  stream: (action, args, callbacks) => window.ARIA.stream(action, args, callbacks),
  on: (event, cb) => window.ARIA.on(event, cb),
};

// ── Initialisation ────────────────────────────────────────────────────────────

async function init() {
  console.log('[ARIA] Initialisation...');

  // Attendre que le backend soit prêt
  await waitForBackend();

  // Charger les paramètres
  await loadSettings();

  // Restaurer le thème et le wallpaper
  applyTheme(state.settings.theme || 'slate');
  setGlassIntensity(state.settings.glass_intensity || 60);
  restoreWallpaper();

  // Charger les conversations
  await refreshConversationList();

  // Démarrer une nouvelle conversation ou charger la dernière
  const lastConvId = state.settings.last_conversation_id;
  if (lastConvId) {
    await loadConversation(lastConvId);
  } else {
    await newConversation();
  }

  // Brancher les événements Python
  setupEventListeners();

  console.log('[ARIA] Prêt');
}

function waitForBackend() {
  return new Promise((resolve) => {
    if (state.backendReady) return resolve();
    window.ARIA.on('backend-ready', () => {
      state.backendReady = true;
      resolve();
    });
  });
}

function setupEventListeners() {
  // Résultat STT (transcription vocale)
  api.on('stt_result', (text) => {
    const input = document.getElementById('text-input');
    if (!input) return;
    state._injectingSTT = true;
    input.value = text;
    input.dispatchEvent(new Event('input'));
    state._injectingSTT = false;
    input.focus();
    if (state.conversationMode === 'vocal') {
      startVocalCountdown(text);
    }
  });

  // Transcription partielle (temps réel)
  api.on('stt_partial', (text) => {
    const input = document.getElementById('text-input');
    if (input) {
      input.value = text;
      input.style.color = 'var(--text3)';
    }
  });

  // Statut ARIA
  api.on('status_change', (status) => setStatus(status));

  // Waveform micro
  api.on('waveform', (rms) => updateWaveform(rms));

  // Toast
  api.on('toast', ({ message, type }) => showToast(message, type));

  // Message utilisateur depuis le backend
  api.on('user_message', (text) => addUserBubble(text));

  // Token LLM streaming
  api.on('assistant_token', (token) => appendStreamToken(token));

  // Fin du message ARIA
  api.on('assistant_done', () => finalizeAssistantMessage());
}

// ── Conversations ─────────────────────────────────────────────────────────────

async function refreshConversationList() {
  try {
    const conversations = await api.call('get_conversations');
    renderConversationList(conversations || []);
  } catch(e) {
    console.error('Erreur chargement conversations:', e);
  }
}

function renderConversationList(conversations) {
  const list = document.getElementById('conversations-list');
  if (!list) return;

  if (!conversations.length) {
    list.innerHTML = '<div class="empty-conv-list">Aucune conversation</div>';
    return;
  }

  list.innerHTML = conversations.map(conv => {
    const isActive = conv.id === state.currentConvId;
    const title = esc(conv.title || 'Nouvelle conversation');
    const date = conv.updated_at
      ? new Date(conv.updated_at).toLocaleDateString('fr-FR')
      : '';

    return `
      <div class="conv-item ${isActive ? 'active' : ''}" id="conv-${conv.id}"
           onmouseenter="this.querySelector('.conv-delete').style.opacity='1'"
           onmouseleave="this.querySelector('.conv-delete').style.opacity='0'">
        <div class="conv-content" onclick="loadConversation('${conv.id}')">
          <div class="conv-title">${title}</div>
          <div class="conv-date">${date}</div>
        </div>
        <button class="conv-delete"
          onclick="event.stopPropagation();deleteConversation('${conv.id}','${title}')">
          ✕
        </button>
      </div>`;
  }).join('');
}

async function newConversation() {
  try {
    const result = await api.call('new_conversation');
    state.currentConvId = result.id;
    document.getElementById('messages').innerHTML = '';
    document.getElementById('conv-title').textContent = 'Nouvelle conversation';
    await refreshConversationList();
    showModeSelector();
  } catch(e) {
    showToast('Erreur création conversation', 'error');
  }
}

async function loadConversation(convId) {
  try {
    const result = await api.call('load_conversation', convId);
    state.currentConvId = result.id;

    // Afficher les messages
    const messagesEl = document.getElementById('messages');
    messagesEl.innerHTML = '';
    (result.messages || []).forEach(msg => {
      if (msg.role === 'user') addUserBubble(msg.content, false);
      else addAriaBubble(msg.content, false);
    });

    // Restaurer le mode
    const mode = await api.call('get_conversation_mode', convId);
    if (mode) {
      applyConversationMode(mode);
    } else {
      showModeSelector();
    }

    await refreshConversationList();
    scrollToBottom();
  } catch(e) {
    showToast('Erreur chargement conversation', 'error');
  }
}

async function deleteConversation(convId, title) {
  if (!confirm(`Supprimer "${title}" ?\nCette action est irréversible.`)) return;
  try {
    const result = await api.call('delete_conversation', convId);
    if (result.success) {
      document.getElementById(`conv-${convId}`)?.remove();
      showToast('Conversation supprimée', 'success');
      if (convId === state.currentConvId) {
        await newConversation();
      }
    }
  } catch(e) {
    showToast('Erreur suppression', 'error');
  }
}

async function deleteAllConversations() {
  const count = document.querySelectorAll('.conv-item').length;
  if (!count) { showToast('Aucune conversation', 'info'); return; }
  if (!confirm(`Supprimer les ${count} conversation(s) ?`)) return;
  try {
    const result = await api.call('delete_all_conversations');
    if (result.success) {
      showToast(`${result.count} supprimée(s)`, 'success');
      await newConversation();
    }
  } catch(e) {
    showToast('Erreur', 'error');
  }
}

// ── Messages ──────────────────────────────────────────────────────────────────

function addUserBubble(text, scroll = true) {
  const messages = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'bubble-wrap user-wrap';
  div.innerHTML = `
    <div class="bubble bubble-user">
      <div class="bubble-text">${esc(text)}</div>
    </div>`;
  messages.appendChild(div);
  if (scroll) scrollToBottom();
}

function addAriaBubble(text, scroll = true) {
  const messages = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'bubble-wrap aria-wrap';
  div.innerHTML = `
    <div class="bubble-avatar">
      <svg viewBox="0 0 24 24" width="20" height="20">
        <circle cx="12" cy="12" r="5" fill="url(#logoGrad)"/>
        <circle cx="12" cy="12" r="9" fill="none" stroke="rgba(108,142,255,0.4)" stroke-width="1"/>
      </svg>
    </div>
    <div class="bubble bubble-aria">
      <div class="bubble-text">${renderMarkdown(text)}</div>
    </div>`;
  messages.appendChild(div);
  if (scroll) scrollToBottom();
}

function appendStreamToken(token) {
  if (!state._streamingMessage) {
    // Créer une nouvelle bulle ARIA
    const messages = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = 'bubble-wrap aria-wrap';
    div.innerHTML = `
      <div class="bubble-avatar">
        <svg viewBox="0 0 24 24" width="20" height="20">
          <circle cx="12" cy="12" r="5" fill="url(#logoGrad)"/>
          <circle cx="12" cy="12" r="9" fill="none" stroke="rgba(108,142,255,0.4)" stroke-width="1"/>
        </svg>
      </div>
      <div class="bubble bubble-aria">
        <div class="bubble-text streaming-text"></div>
      </div>`;
    messages.appendChild(div);
    state._streamingMessage = div.querySelector('.streaming-text');
    state._streamingContent = '';
  }

  state._streamingContent += token;
  state._streamingMessage.innerHTML = renderMarkdown(state._streamingContent) + '<span class="cursor-blink">▋</span>';
  scrollToBottom();
}

function finalizeAssistantMessage() {
  if (state._streamingMessage) {
    state._streamingMessage.innerHTML = renderMarkdown(state._streamingContent);
    state._streamingMessage = null;
    state._streamingContent = '';
  }
}

// ── Envoi de messages ─────────────────────────────────────────────────────────

async function sendMessage() {
  const input = document.getElementById('text-input');
  const text = input.value.trim();
  if (!text) return;

  input.value = '';
  input.style.height = 'auto';

  cancelVocalCountdown();
  setStatus('thinking');

  try {
    await api.call('ask', text, state.conversationMode);
  } catch(e) {
    showToast('Erreur: ' + e.message, 'error');
    finalizeAssistantMessage();
    setStatus('idle');
  }
}

function handleInputKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function adjustTextarea(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

// ── Mode vocal ────────────────────────────────────────────────────────────────

function showModeSelector() {
  document.getElementById('mode-select-overlay')?.classList.remove('hidden');
}

async function selectConversationMode(mode) {
  document.getElementById('mode-select-overlay')?.classList.add('hidden');
  await api.call('set_conversation_mode', state.currentConvId, mode);
  applyConversationMode(mode);
}

function applyConversationMode(mode) {
  state.conversationMode = mode;
  if (mode === 'vocal') {
    state.ttsEnabled = true;
    document.getElementById('mic-btn')?.classList.add('mic-emphasized');
    addAriaBubble('Mode vocal activé. Appuie sur 🎤 pour parler.');
  } else {
    state.ttsEnabled = false;
    document.getElementById('mic-btn')?.classList.remove('mic-emphasized');
    document.getElementById('text-input')?.focus();
  }
}

function startVocalCountdown(text) {
  cancelVocalCountdown();
  state._originalTranscription = text;

  const input = document.getElementById('text-input');
  input.style.outline = '2px solid rgba(108,142,255,0.7)';

  const cleanup = () => {
    state._vocalCountdownTimer = null;
    if (input) input.style.outline = '';
    input.removeEventListener('keydown', onKeyDown);
    input.removeEventListener('input', onInput);
  };

  const onKeyDown = (e) => {
    if (e.key === 'Escape') {
      clearTimeout(state._vocalCountdownTimer);
      cleanup();
      input.value = '';
    } else if (e.key !== 'Enter') {
      clearTimeout(state._vocalCountdownTimer);
      cleanup();
    }
  };

  const onInput = () => {
    if (state._injectingSTT) return;
    if (input.value !== state._originalTranscription) {
      clearTimeout(state._vocalCountdownTimer);
      cleanup();
    }
  };

  input.addEventListener('keydown', onKeyDown);
  input.addEventListener('input', onInput);

  state._vocalCountdownTimer = setTimeout(() => {
    cleanup();
    if (input.value.trim() === state._originalTranscription.trim()) {
      sendMessage();
    }
  }, 1500);
}

function cancelVocalCountdown() {
  if (state._vocalCountdownTimer) {
    clearTimeout(state._vocalCountdownTimer);
    state._vocalCountdownTimer = null;
  }
  const input = document.getElementById('text-input');
  if (input) input.style.outline = '';
}

// ── Micro ─────────────────────────────────────────────────────────────────────

async function toggleMic() {
  if (state.micActive) {
    state.micActive = false;
    state.micPaused = true;
    await api.call('stop_mic');
    setMicState('idle');
  } else {
    state.micActive = true;
    state.micPaused = false;
    await api.call('start_mic');
    setMicState('listening');
  }
}

function setMicState(s) {
  const btn = document.getElementById('mic-btn');
  if (!btn) return;
  btn.classList.remove('mic-idle', 'mic-listening', 'mic-speaking-detected');
  const icons = { idle: '🎤', listening: '🎤', transcribing: '⏳' };
  btn.textContent = icons[s] || '🎤';
  btn.classList.add(`mic-${s}`);
}

function updateWaveform(rms) {
  const btn = document.getElementById('mic-btn');
  if (!btn || !state.micActive) return;

  state._rmsHistory = state._rmsHistory || [];
  state._rmsHistory.push(rms);
  if (state._rmsHistory.length > 8) state._rmsHistory.shift();
  const smooth = state._rmsHistory.reduce((a, b) => a + b, 0) / state._rmsHistory.length;

  const isSpeaking = smooth > 0.02;
  if (isSpeaking !== state._wasSpeaking) {
    state._wasSpeaking = isSpeaking;
    if (isSpeaking) {
      btn.classList.add('mic-speaking-detected');
      btn.textContent = '🎙️';
    } else {
      btn.classList.remove('mic-speaking-detected');
      btn.textContent = '🎤';
    }
  }

  const scale = isSpeaking ? 1 + Math.min(smooth * 3, 0.25) : 1;
  btn.style.transform = `scale(${scale.toFixed(3)})`;

  // Anneaux
  const now = Date.now();
  if (isSpeaking && smooth > 0.04 && (!state._lastRingTime || now - state._lastRingTime > 400)) {
    state._lastRingTime = now;
    triggerMicRings();
  }
}

function triggerMicRings() {
  document.querySelectorAll('.mic-ring').forEach((ring, i) => {
    ring.classList.remove('ring-active');
    setTimeout(() => {
      ring.classList.add('ring-active');
      setTimeout(() => ring.classList.remove('ring-active'), 700);
    }, i * 80);
  });
}

// ── Statut ────────────────────────────────────────────────────────────────────

function setStatus(s) {
  const statusText = document.getElementById('status-text');
  const logo = document.getElementById('aria-logo');

  const labels = {
    idle: 'En veille', listening: 'Écoute...', transcribing: 'Transcription...',
    thinking: 'Réfléchit...', speaking: 'Parle...',
  };
  if (statusText) statusText.textContent = labels[s] || s;

  if (logo) {
    logo.classList.remove('logo-idle', 'logo-listening', 'logo-thinking', 'logo-speaking');
    const map = {
      idle: 'logo-idle', listening: 'logo-listening', transcribing: 'logo-listening',
      thinking: 'logo-thinking', speaking: 'logo-speaking',
    };
    logo.classList.add(map[s] || 'logo-idle');
  }
}

// ── Paramètres ────────────────────────────────────────────────────────────────

async function loadSettings() {
  try {
    state.settings = await api.call('get_settings') || {};
  } catch(e) {
    state.settings = {};
  }
}

async function saveSetting(key, value) {
  state.settings[key] = value;
  try {
    await api.call('save_settings', state.settings);
  } catch(e) {
    console.error('Erreur sauvegarde setting:', e);
  }
}

function toggleSettings() {
  const panel = document.getElementById('settings-panel');
  panel?.classList.toggle('hidden');
}

function toggleAccordion(id) {
  const body = document.querySelector(`#acc-${id} .acc-body`);
  const chevron = document.querySelector(`#acc-${id} .acc-chevron`);
  const isHidden = body?.classList.contains('hidden');
  body?.classList.toggle('hidden', !isHidden);
  if (chevron) chevron.textContent = isHidden ? '▾' : '▸';

  if (id === 'modeles' && isHidden) {
    loadModelSettings();
  }
}

async function loadModelSettings() {
  const container = document.getElementById('model-settings');
  if (!container) return;
  container.innerHTML = '<div class="loading-text">Chargement...</div>';

  try {
    const data = await api.call('get_available_models');
    if (!data.ollama_running) {
      container.innerHTML = '<div class="error-text">⚠️ Ollama non disponible</div>';
      return;
    }
    if (!data.local_models?.length) {
      container.innerHTML = '<div class="info-text">Aucun modèle installé.<br><code>ollama pull llama3.2:1b</code></div>';
      return;
    }

    const roles = [
      { key: 'intent', label: '⚡ Classification (1B)' },
      { key: 'fast',   label: '💬 Réponses rapides' },
      { key: 'heavy',  label: '🧠 Analyse approfondie' },
      { key: 'vision', label: '👁️ Vision' },
    ];

    container.innerHTML = roles.map(r => `
      <div class="model-row">
        <label>${r.label}</label>
        <select onchange="setModel('${r.key}', this.value)">
          ${data.local_models.map(m => `
            <option value="${m}" ${m === data.configured[r.key] ? 'selected' : ''}>${m}</option>
          `).join('')}
        </select>
      </div>
    `).join('');
  } catch(e) {
    container.innerHTML = `<div class="error-text">Erreur: ${e.message}</div>`;
  }
}

async function setModel(role, modelName) {
  try {
    const result = await api.call('set_model', role, modelName);
    if (result.success) showToast(`${role} → ${modelName}`, 'success');
    else showToast('Erreur: ' + result.error, 'error');
  } catch(e) {
    showToast('Erreur set_model', 'error');
  }
}

// ── Thèmes et wallpapers ──────────────────────────────────────────────────────

function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  document.querySelectorAll('.theme-pill').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.theme === theme);
  });
  saveSetting('theme', theme);
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  document.querySelector(`.theme-pill[data-theme="${theme}"]`)?.classList.add('active');
}

function setGlassIntensity(value) {
  const blur = 4 + (value / 100) * 36;
  const alpha = 0.18 - (value / 100) * 0.16;
  document.documentElement.style.setProperty('--glass-blur', `${blur}px`);
  document.documentElement.style.setProperty('--glass-alpha', alpha);
}

function setWallpaper(type, url = null) {
  const layer = document.getElementById('wallpaper-image');
  if (!layer) return;

  layer.className = '';
  layer.style.backgroundImage = '';
  layer.style.background = '';

  if (type === 'custom' && url) {
    layer.style.backgroundImage = `url("${url}")`;
    layer.style.backgroundSize = 'cover';
    layer.style.backgroundPosition = 'center';
  } else {
    layer.classList.add(`wp-${type}`);
  }

  document.querySelectorAll('.wp-thumb').forEach(t => t.classList.remove('active'));
  document.querySelector(`.wp-thumb.wp-${type}`)?.classList.add('active');

  saveSetting('wallpaper_type', type);
  if (url) saveSetting('wallpaper_filename', url.split('/').pop());
}

async function restoreWallpaper() {
  const type = state.settings.wallpaper_type;
  if (!type) return;

  if (type === 'custom' && state.settings.wallpaper_filename) {
    const url = `http://127.0.0.1:${state._staticPort}/wallpapers/${state.settings.wallpaper_filename}`;
    setWallpaper('custom', url);
  } else if (type) {
    setWallpaper(type);
  }
}

async function uploadWallpaper(file) {
  if (!file?.type.startsWith('image/')) {
    showToast('Fichier non supporté', 'error');
    return;
  }
  showToast('Import en cours...', 'info');
  try {
    const b64 = await fileToBase64(file);
    const result = await api.call('save_wallpaper', b64, file.name);
    if (result.success) {
      showToast('Image importée ✓', 'success');
      const url = `http://127.0.0.1:${state._staticPort}/wallpapers/${result.filename}`;
      setWallpaper('custom', url);
      await loadCustomWallpapers();
    } else {
      showToast('Erreur: ' + result.error, 'error');
    }
  } catch(e) {
    showToast('Erreur import', 'error');
  }
}

async function loadCustomWallpapers() {
  const grid = document.getElementById('wallpaper-custom-grid');
  if (!grid) return;
  try {
    const files = await api.call('get_wallpapers');
    grid.innerHTML = files.map(f => `
      <div class="wp-custom-item">
        <img src="http://127.0.0.1:${state._staticPort}/wallpapers/${f.filename}"
             onclick="setWallpaper('custom','http://127.0.0.1:${state._staticPort}/wallpapers/${f.filename}')">
        <button onclick="deleteWallpaper('${f.filename}')">✕</button>
      </div>
    `).join('');
  } catch(e) {}
}

async function deleteWallpaper(filename) {
  try {
    await api.call('delete_wallpaper', filename);
    showToast('Fond supprimé', 'success');
    await loadCustomWallpapers();
  } catch(e) {}
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ── Utilitaires ───────────────────────────────────────────────────────────────

function esc(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderMarkdown(text) {
  // Markdown minimal : gras, italique, code, sauts de ligne
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>');
}

function scrollToBottom() {
  const container = document.getElementById('messages-container');
  if (container) container.scrollTop = container.scrollHeight;
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = e => resolve(e.target.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// ── Démarrage ─────────────────────────────────────────────────────────────────

// Exposer les fonctions dans le scope global pour les onclick HTML
Object.assign(window, {
  app: {
    newConversation, loadConversation, deleteConversation, deleteAllConversations,
    sendMessage, handleInputKeydown, adjustTextarea,
    toggleMic, selectConversationMode,
    toggleSettings, toggleAccordion, loadModelSettings, setModel,
    setTheme, setGlassIntensity, setWallpaper, uploadWallpaper, deleteWallpaper,
    saveSetting, exportConversation: () => api.call('export_current_conversation'),
    runMicDiagnostic: () => api.call('run_mic_diagnostic'),
  },
  // Fonctions appelées depuis le HTML généré dynamiquement
  loadConversation, deleteConversation, setModel, setWallpaper, deleteWallpaper,
});

// Démarrer quand le DOM est prêt
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
```
## FICHIER 7 — electron/renderer/styles.css (extrait des règles clés)

```css
/* ── Variables CSS (thèmes) ────────────────────────────────────────────────── */
:root {
  --glass-blur: 24px;
  --glass-alpha: 0.06;
}

[data-theme="slate"] {
  --bg: #0C0C0F;
  --surface: #17171E;
  --card: #1E1E28;
  --border: rgba(255,255,255,0.07);
  --text: #F1F1F3;
  --text2: #A8A8B3;
  --text3: #55555F;
  --accent: #6C8EFF;
  --accent-bg: rgba(108,142,255,0.1);
  --error: #F87171;
  --success: #4ADE80;
}

[data-theme="warm"] {
  --bg: #0F0D0C;
  --surface: #1A1714;
  --accent: #F59E0B;
  --accent-bg: rgba(245,158,11,0.1);
}

[data-theme="forest"] {
  --bg: #0A0F0C;
  --surface: #131A14;
  --accent: #34D399;
  --accent-bg: rgba(52,211,153,0.1);
}

[data-theme="rose"] {
  --bg: #0F0C0E;
  --surface: #1A1318;
  --accent: #F472B6;
  --accent-bg: rgba(244,114,182,0.1);
}

/* ── Reset & base ──────────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  height: 100vh;
  overflow: hidden;
  user-select: none;
}

/* ── Barre de titre ────────────────────────────────────────────────────────── */
#title-bar {
  height: 32px;
  -webkit-app-region: drag;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  position: fixed;
  top: 0; left: 0; right: 0;
  z-index: 1000;
  background: rgba(12,12,15,0.3);
}

#title-bar-drag { flex: 1; height: 100%; }

#window-controls {
  -webkit-app-region: no-drag;
  display: flex;
  gap: 2px;
  padding-right: 4px;
}

#window-controls button {
  width: 36px; height: 32px;
  background: transparent;
  border: none;
  color: var(--text3);
  cursor: pointer;
  font-size: 12px;
  transition: background 0.15s, color 0.15s;
}

#window-controls button:hover { background: rgba(255,255,255,0.08); color: var(--text); }
#window-controls .close-btn:hover { background: rgba(239,68,68,0.8); color: white; }

/* ── Fond d'écran ──────────────────────────────────────────────────────────── */
#wallpaper-layer { position: fixed; inset: 0; z-index: -1; }

#wallpaper-image {
  position: absolute; inset: 0;
  background-size: cover;
  background-position: center;
}

#wallpaper-overlay {
  position: absolute; inset: 0;
  background: rgba(0,0,0,0.2);
}

/* Presets gradient */
.wp-aurora   { background: linear-gradient(135deg, #1a1a2e, #16213e, #0f3460, #533483); }
.wp-sunset   { background: linear-gradient(135deg, #2d1b2e, #5e2750, #a8456b, #e8845a); }
.wp-midnight { background: linear-gradient(135deg, #050510, #0a0a20, #14143a); }
.wp-forest   { background: linear-gradient(135deg, #0b1e14, #163d2c, #1f5c3d); }
.wp-mesh     {
  background:
    radial-gradient(at 20% 30%, rgba(108,142,255,0.25) 0, transparent 50%),
    radial-gradient(at 80% 20%, rgba(167,139,250,0.2) 0, transparent 50%),
    radial-gradient(at 50% 80%, rgba(74,222,128,0.15) 0, transparent 50%),
    #0C0C0F;
}
.wp-mono { background: #0C0C0F; }

/* ── Layout principal ──────────────────────────────────────────────────────── */
#app-layout {
  display: flex;
  height: 100vh;
  padding-top: 32px;  /* Title bar */
}

/* ── Sidebar ───────────────────────────────────────────────────────────────── */
#sidebar {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: rgba(18,18,26,var(--glass-alpha));
  backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  box-shadow: 2px 0 20px rgba(0,0,0,0.1);
  overflow: hidden;
}

#sidebar-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 16px 12px;
}

#assistant-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: 1px;
}

#status-text {
  font-size: 11px;
  color: var(--text3);
  margin-top: 2px;
}

#new-conv-btn {
  margin: 8px 12px;
  padding: 10px 14px;
  background: rgba(108,142,255,0.1);
  border: 1px solid rgba(108,142,255,0.2);
  border-radius: 10px;
  color: var(--accent);
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}

#new-conv-btn:hover { background: rgba(108,142,255,0.18); }

#conversations-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px;
}

#conversations-list::-webkit-scrollbar { width: 4px; }
#conversations-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }

.conv-item {
  display: flex;
  align-items: center;
  border-radius: 10px;
  padding: 0;
  margin-bottom: 2px;
  transition: background 0.15s;
  cursor: pointer;
}

.conv-item:hover { background: rgba(255,255,255,0.05); }
.conv-item.active { background: rgba(108,142,255,0.12); }

.conv-content {
  flex: 1;
  min-width: 0;
  padding: 10px 10px 10px 12px;
  overflow: hidden;
}

.conv-title {
  font-size: 13px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-date { font-size: 10px; color: var(--text3); margin-top: 2px; }

.conv-delete {
  opacity: 0;
  flex-shrink: 0;
  width: 28px; height: 28px;
  margin-right: 6px;
  background: rgba(239,68,68,0.12);
  border: none;
  border-radius: 6px;
  color: var(--error);
  cursor: pointer;
  font-size: 11px;
  transition: opacity 0.15s, background 0.15s;
}

.conv-delete:hover { background: rgba(239,68,68,0.25); }

#delete-all-btn {
  margin: 8px 12px 12px;
  padding: 8px;
  background: rgba(239,68,68,0.07);
  border: 1px solid rgba(239,68,68,0.15);
  border-radius: 8px;
  color: var(--error);
  font-size: 11px;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.15s;
}

#delete-all-btn:hover { background: rgba(239,68,68,0.15); }

/* ── Zone principale ───────────────────────────────────────────────────────── */
#main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

/* ── Header ────────────────────────────────────────────────────────────────── */
#header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: transparent;
}

#conv-title { font-size: 14px; color: var(--text2); }

#header-right { display: flex; gap: 8px; }

#header-right button {
  width: 36px; height: 36px;
  background: rgba(255,255,255,0.06);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text2);
  cursor: pointer;
  font-size: 16px;
  transition: background 0.15s;
}

#header-right button:hover { background: rgba(255,255,255,0.1); }

/* ── Messages ──────────────────────────────────────────────────────────────── */
#messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

#messages-container::-webkit-scrollbar { width: 4px; }
#messages-container::-webkit-scrollbar-thumb {
  background: rgba(255,255,255,0.08);
  border-radius: 2px;
}

#messages { display: flex; flex-direction: column; gap: 16px; }

.bubble-wrap { display: flex; gap: 10px; align-items: flex-end; }
.user-wrap { flex-direction: row-reverse; }

.bubble {
  max-width: 75%;
  padding: 12px 16px;
  font-size: 14px;
  line-height: 1.6;
  animation: bubbleIn 0.3s cubic-bezier(0.34,1.4,0.64,1);
}

@keyframes bubbleIn {
  from { opacity: 0; transform: translateY(12px) scale(0.95); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

.bubble-user {
  background: rgba(108,142,255,0.14);
  border-radius: 18px 18px 4px 18px;
  color: var(--text);
}

.bubble-aria {
  background: rgba(255,255,255,0.04);
  border-radius: 4px 18px 18px 18px;
  color: var(--text);
}

.bubble-avatar {
  width: 28px; height: 28px;
  border-radius: 8px;
  background: rgba(108,142,255,0.1);
  border: 1px solid rgba(108,142,255,0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.cursor-blink {
  animation: blink 1s step-end infinite;
  color: var(--accent);
}

@keyframes blink {
  50% { opacity: 0; }
}

/* ── Zone de saisie ────────────────────────────────────────────────────────── */
#input-area {
  padding: 8px 16px 16px;
}

#input-zone {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  background: rgba(255,255,255,0.06);
  backdrop-filter: blur(20px) saturate(180%);
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 24px;
  padding: 8px 8px 8px 12px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

#input-zone:focus-within {
  border-color: rgba(108,142,255,0.35);
  box-shadow: 0 0 0 3px rgba(108,142,255,0.08);
}

#text-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.5;
  resize: none;
  max-height: 160px;
  overflow-y: auto;
}

#text-input::placeholder { color: var(--text3); }

/* Bouton micro */
#mic-orb-container { position: relative; width: 40px; height: 40px; flex-shrink: 0; }

.mic-ring {
  position: absolute; inset: 0;
  border-radius: 50%;
  border: 1.5px solid rgba(108,142,255,0.4);
  opacity: 0;
  pointer-events: none;
}

@keyframes ringExpand {
  0%   { transform: scale(1);   opacity: 0.6; }
  100% { transform: scale(2.5); opacity: 0; }
}

.mic-ring.ring-active { animation: ringExpand 0.6s ease-out forwards; }

#mic-btn {
  position: absolute; inset: 0;
  border-radius: 50%;
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.12);
  color: var(--text);
  font-size: 17px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s cubic-bezier(0.34,1.2,0.64,1);
  z-index: 2;
}

#mic-btn.mic-listening { background: rgba(108,142,255,0.18); border-color: rgba(108,142,255,0.4); }
#mic-btn.mic-speaking-detected { background: rgba(74,222,128,0.18); border-color: rgba(74,222,128,0.4); }
#mic-btn.mic-emphasized { animation: micPulse 2.5s ease-in-out infinite; }

@keyframes micPulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(108,142,255,0.3); }
  50%      { box-shadow: 0 0 0 8px rgba(108,142,255,0); }
}

#file-btn {
  width: 36px; height: 36px;
  border-radius: 10px;
  background: rgba(255,255,255,0.06);
  border: 1px solid var(--border);
  color: var(--text2);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 17px;
  flex-shrink: 0;
  transition: background 0.15s;
}

#file-btn:hover { background: rgba(255,255,255,0.1); }

#send-btn {
  width: 36px; height: 36px;
  border-radius: 50%;
  background: var(--accent);
  border: none;
  color: white;
  font-size: 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform 0.15s, opacity 0.15s;
}

#send-btn:hover { transform: scale(1.08); }

/* ── Panneau paramètres ─────────────────────────────────────────────────────── */
#settings-panel {
  width: 300px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: rgba(16,16,24,calc(var(--glass-alpha) + 0.08));
  backdrop-filter: blur(40px) saturate(180%);
  box-shadow: -4px 0 20px rgba(0,0,0,0.15);
  overflow: hidden;
  transition: width 0.25s ease;
}

#settings-panel.hidden { width: 0; }

#settings-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  flex-shrink: 0;
}

#settings-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.settings-accordion { margin-bottom: 6px; }

.acc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: rgba(255,255,255,0.04);
  border-radius: 10px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  color: var(--text2);
  transition: background 0.15s;
}

.acc-header:hover { background: rgba(255,255,255,0.07); }
.acc-chevron { font-size: 12px; }

.acc-body {
  padding: 10px 12px 12px;
}

.acc-body.hidden { display: none; }

.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 0;
  font-size: 12px;
  color: var(--text2);
}

.setting-label {
  font-size: 11px;
  color: var(--text3);
  margin: 8px 0 5px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.theme-pills { display: flex; gap: 5px; }

.theme-pill {
  padding: 4px 9px;
  border-radius: 20px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text3);
  font-size: 11px;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s;
}

.theme-pill.active {
  background: var(--accent-bg);
  border-color: var(--accent);
  color: var(--accent);
}

.settings-btn-outline {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text2);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  width: 100%;
  margin-top: 6px;
  transition: background 0.15s;
}

.settings-btn-outline:hover { background: rgba(255,255,255,0.06); }

/* Wallpaper grid */
.wallpaper-presets { display: grid; grid-template-columns: repeat(3,1fr); gap: 6px; margin-bottom: 8px; }
.wp-thumb { height: 50px; border-radius: 10px; cursor: pointer; border: 2px solid transparent; transition: border-color 0.15s; }
.wp-thumb:hover, .wp-thumb.active { border-color: var(--accent); }

#wallpaper-custom-grid { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }

.wp-custom-item { position: relative; width: 72px; height: 50px; border-radius: 8px; overflow: hidden; }
.wp-custom-item img { width: 100%; height: 100%; object-fit: cover; cursor: pointer; }
.wp-custom-item button {
  position: absolute; top: 2px; right: 2px;
  background: rgba(0,0,0,0.65); color: white; border: none; border-radius: 50%;
  width: 18px; height: 18px; font-size: 9px; cursor: pointer;
}

/* Model settings */
.model-row { margin-bottom: 10px; }
.model-row label { display: block; font-size: 11px; color: var(--text3); margin-bottom: 4px; }
.model-row select {
  width: 100%;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 7px 10px;
  color: var(--text);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
  outline: none;
}

/* ── Modal sélection mode ───────────────────────────────────────────────────── */
#mode-select-overlay {
  position: fixed; inset: 0; z-index: 9000;
  background: rgba(0,0,0,0.45);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
}

#mode-select-overlay.hidden { display: none; }

#mode-select-card {
  background: rgba(24,24,36,0.7);
  backdrop-filter: blur(40px) saturate(180%);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 24px;
  padding: 36px 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.4);
}

#mode-select-title { font-size: 16px; color: var(--text); text-align: center; }

#mode-select-buttons { display: flex; gap: 14px; }

#mode-select-buttons button {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 20px 28px;
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 16px;
  color: var(--text);
  font-family: inherit;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34,1.2,0.64,1);
}

#mode-select-buttons button span:first-child { font-size: 28px; }

#mode-select-buttons button:hover {
  background: rgba(108,142,255,0.15);
  border-color: rgba(108,142,255,0.4);
  transform: scale(1.04);
}

/* ── Toast ──────────────────────────────────────────────────────────────────── */
#toast-container {
  position: fixed;
  top: 50px; right: 16px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.toast {
  background: rgba(30,30,44,0.6);
  backdrop-filter: blur(30px) saturate(180%);
  border: 0.5px solid rgba(255,255,255,0.12);
  border-radius: 12px;
  padding: 10px 16px;
  font-size: 13px;
  color: var(--text);
  opacity: 0;
  transform: translateX(20px);
  transition: opacity 0.25s, transform 0.25s;
  box-shadow: 0 8px 24px rgba(0,0,0,0.25);
}

.toast.show { opacity: 1; transform: translateX(0); }
.toast-error { border-color: rgba(248,113,113,0.4); }
.toast-success { border-color: rgba(74,222,128,0.4); }

/* ── Logo JARVIS animé ─────────────────────────────────────────────────────── */
#aria-logo { display: inline-flex; align-items: center; justify-content: center; filter: drop-shadow(0 0 8px rgba(108,142,255,0.3)); }
.logo-arc-1 { transform-origin: 32px 32px; animation: logoRotate 12s linear infinite; }
.logo-arc-2 { transform-origin: 32px 32px; animation: logoRotate 8s linear infinite reverse; }
.logo-arc-3 { transform-origin: 32px 32px; animation: logoRotate 5s linear infinite; }
@keyframes logoRotate { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.logo-core { animation: logoPulse 3s ease-in-out infinite; transform-origin: 32px 32px; }
@keyframes logoPulse { 0%,100% { opacity: 0.85; transform: scale(1); } 50% { opacity: 1; transform: scale(1.08); } }
.logo-scan { transform-origin: 32px 32px; animation: logoScan 6s linear infinite; }
@keyframes logoScan { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.tick { stroke: rgba(108,142,255,0.25); stroke-width: 1.5; stroke-linecap: round; animation: tickGlow 4s ease-in-out infinite; animation-delay: calc(var(--i) * 0.3s); }
@keyframes tickGlow { 0%,80%,100% { stroke: rgba(108,142,255,0.15); } 10% { stroke: rgba(108,142,255,0.8); } }

.logo-listening { filter: drop-shadow(0 0 12px rgba(0,212,255,0.45)) !important; }
.logo-thinking .logo-arc-1 { animation-duration: 2s; }
.logo-thinking .logo-arc-2 { animation-duration: 1.6s; }
.logo-thinking .logo-arc-3 { animation-duration: 1.2s; }
.logo-thinking { filter: drop-shadow(0 0 14px rgba(167,139,250,0.5)) !important; }
.logo-speaking .logo-core { fill: #4ADE80; }
.logo-speaking { filter: drop-shadow(0 0 14px rgba(74,222,128,0.45)) !important; }

/* ── Focus indicator ───────────────────────────────────────────────────────── */
#focus-indicator {
  display: none;
  position: fixed;
  top: 42px; right: 16px;
  background: rgba(167,139,250,0.15);
  border: 1px solid rgba(167,139,250,0.3);
  color: #A78BFA;
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 8px;
  z-index: 50;
}

/* ── Utilitaires ────────────────────────────────────────────────────────────── */
.hidden { display: none !important; }
.loading-text { font-size: 12px; color: var(--text3); padding: 8px 0; }
.error-text { font-size: 12px; color: var(--error); padding: 8px; background: rgba(239,68,68,0.08); border-radius: 8px; }
.info-text { font-size: 12px; color: var(--text3); }
code { background: rgba(255,255,255,0.08); padding: 2px 6px; border-radius: 4px; font-size: 11px; }
```
## FICHIER 8 — python/main.py (adapté pour Electron)

```python
"""
main.py — Point d'entrée ARIA en mode Electron.
Lance le serveur WebSocket et démarre les services.
"""
import sys
import io
import logging
import threading
import time

# Fix encodage Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import logging
logging.getLogger('comtypes').setLevel(logging.WARNING)
logging.getLogger('asyncio').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

import yaml
import app_paths

# Charger la config
try:
    with app_paths.config_path().open('r', encoding='utf-8') as f:
        _config = yaml.safe_load(f) or {}
except Exception as e:
    logger.error("Erreur chargement config: %s", e)
    _config = {}

# ── Démarrage des services ───────────────────────────────────────────────────

def main():
    logger.info("=== ARIA Backend démarrage ===")

    # 1. Démarrer le serveur WebSocket (communication avec Electron)
    import ui_bridge
    ui_bridge.start()
    logger.info("WebSocket serveur démarré")

    # Attendre qu'Electron se connecte (max 15s)
    time.sleep(1)

    # 2. Démarrer Ollama
    import ollama_manager
    if ollama_manager.start_ollama():
        models = ollama_manager.list_local_models()
        logger.info("Modèles disponibles: %s", models)

        # Warmup des modèles qui existent
        from llm import MODELS
        for role, model in [('intent', MODELS.get('intent')), ('fast', MODELS.get('fast'))]:
            if model and ollama_manager.model_exists(model):
                threading.Thread(
                    target=ollama_manager.warmup_model,
                    args=(model,),
                    daemon=True
                ).start()
            else:
                logger.warning("Modèle %s (%s) absent — warmup ignoré", role, model)
    else:
        logger.warning("Ollama non disponible au démarrage")

    # 3. Charger la mémoire
    import memory_engine as _me
    _me.load_memory()
    logger.info("Mémoire chargée: %d conversations", len(_me.get_all_conversations()))

    # 4. Charger le modèle Whisper en arrière-plan
    def _load_whisper():
        try:
            import stt
            stt._load_whisper_model()
            logger.info("Whisper prêt")
        except Exception as e:
            logger.error("Erreur chargement Whisper: %s", e)

    threading.Thread(target=_load_whisper, daemon=True).start()

    # 5. Démarrer le serveur de fichiers statiques (wallpapers)
    _start_static_file_server()

    # 6. Hook clavier F24
    try:
        import keyboard
        import stt

        def on_f24():
            stt.toggle()
            if stt.is_listening():
                ui_bridge.set_status('listening')
            else:
                ui_bridge.set_status('idle')

        keyboard.add_hotkey('f24', on_f24)
        keyboard.add_hotkey('ctrl+shift+a', on_f24)
        logger.info("Hooks clavier F24 + Ctrl+Shift+A enregistrés")
    except Exception as e:
        logger.warning("Hooks clavier non disponibles: %s", e)

    # 7. Démarrage serveur mobile (optionnel)
    try:
        import aria_mobile_server
        threading.Thread(
            target=aria_mobile_server.run,
            daemon=True
        ).start()
        logger.info("Serveur mobile démarré")
    except Exception as e:
        logger.warning("Serveur mobile non démarré: %s", e)

    # 8. Exposer la fonction shutdown
    @ui_bridge.expose
    def shutdown():
        logger.info("Arrêt demandé par Electron")
        import stt, tts
        stt.stop_listening()
        stt._cleanup_pyaudio()
        if _config.get('kill_ollama_on_exit', True):
            ollama_manager.stop_ollama()
        _me.save_all()
        sys.exit(0)

    logger.info("=== ARIA Backend prêt ===")

    # Maintenir le process vivant
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Arrêt manuel (Ctrl+C)")
        shutdown()


def _start_static_file_server():
    """Sert data/wallpapers/ sur http://127.0.0.1:9998"""
    import http.server, socketserver, socket

    port = 9998
    # Trouver un port libre
    for p in range(port, port + 20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', p))
                port = p
                break
        except OSError:
            continue

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(app_paths.data_dir()), **kwargs)
        def log_message(self, *args):
            pass

    def _run():
        with socketserver.TCPServer(('127.0.0.1', port), Handler) as httpd:
            httpd.allow_reuse_address = True
            logger.info("Serveur statique: http://127.0.0.1:%d", port)
            httpd.serve_forever()

    threading.Thread(target=_run, daemon=True).start()

    # Stocker le port pour que le renderer puisse l'utiliser
    ui_bridge.STATIC_FILE_PORT = port

    # Exposer le port au renderer
    @ui_bridge.expose
    def get_static_port():
        return port


if __name__ == '__main__':
    main()
```

---

## FICHIER 9 — Guide d'installation et migration

### Prérequis

```bash
# Node.js 20+ requis
node --version  # doit être >= 20

# npm 10+
npm --version
```

### Structure des dossiers à créer

```bash
mkdir -p electron/assets
mkdir -p electron/renderer
```

### Installation des dépendances Electron

```bash
cd electron
npm install
```

### Icônes requises

Créer ou copier dans `electron/assets/` :
- `icon.ico` (Windows, 256x256)
- `icon.png` (512x512)
- `tray-icon.png` (22x22 ou 16x16, blanc sur transparent pour Windows)
- `icon-small.png` (16x16)

### Lancement en développement

```bash
# Terminal 1 — Lancer Python
cd python
.venv\Scripts\python.exe main.py

# Terminal 2 — Lancer Electron (attend que Python soit prêt)
cd electron
npm start
```

### Build pour Windows

```bash
cd electron
npm run build:win
```

Génère `dist/ARIA Setup.exe` (installateur) et `dist/ARIA.exe` (portable).

---

## FICHIER 10 — electron-builder.yml (config de build)

```yaml
appId: com.aria.assistant
productName: ARIA
copyright: ARIA © 2026

directories:
  output: ../dist
  buildResources: assets

files:
  - "**/*"
  - "!node_modules/.cache"
  - "!**/*.map"

extraResources:
  - from: ../python
    to: python
    filter:
      - "**/*.py"
      - "**/*.yaml"
      - "**/*.json"
      - "!**/__pycache__/**"
      - "!**/.venv/**"
      - "!**/node_modules/**"
  - from: ../data/checklists
    to: data/checklists

win:
  target:
    - target: nsis
      arch: [x64]
    - target: portable
      arch: [x64]
  icon: assets/icon.ico
  requestedExecutionLevel: asInvoker

nsis:
  oneClick: false
  allowToChangeInstallationDirectory: true
  installerLanguages:
    - French
  language: 1036
  runAfterFinish: true
  createDesktopShortcut: true
  createStartMenuShortcut: true

publish:
  provider: github
  owner: mathisplassartginnain10-a11y
  repo: aria
```

---

## Migration : correspondance ancienne → nouvelle API

| Ancien (pywebview) | Nouveau (Electron) |
|---|---|
| `window.pywebview.api.xxx()` | `window.ARIA.call('xxx')` |
| `ui._instance._js('fn()')` | `ui_bridge.emit('event', data)` |
| `ui.show_toast(msg, type)` | `ui_bridge.show_toast(msg, type)` |
| `ui.set_status(s)` | `ui_bridge.set_status(s)` |
| `ui.update_waveform(rms)` | `ui_bridge.update_waveform(rms)` |
| `ui.show_final_transcription(t)` | `ui_bridge.show_final_transcription(t)` |
| `ui.append_assistant_text(t)` | `ui_bridge.append_assistant_text(t)` |
| `ui.finalize_assistant_message()` | `ui_bridge.finalize_assistant_message()` |
| `webview.create_window(...)` | `BrowserWindow(...)` dans main.js |
| `webview.start(...)` | `app.whenReady()` dans main.js |

---

## Prompt Cursor (à coller tel quel)

> Migrer ARIA de pywebview vers Electron. C'est une migration complète qui remplace le système de communication Python↔UI.
>
> **ÉTAPE 1 — Créer la structure Electron**
>
> Créer les dossiers et fichiers suivants :
> - `electron/main.js` : process principal Electron (contenu complet dans la spec)
> - `electron/preload.js` : bridge contextBridge (contenu complet dans la spec)
> - `electron/package.json` : avec dépendances `ws`, `electron`, `electron-builder`
> - `electron/renderer/index.html` : UI complète (contenu complet dans la spec)
> - `electron/renderer/app.js` : toute la logique JS (contenu complet dans la spec)
> - `electron/renderer/styles.css` : tous les styles (contenu complet dans la spec)
> - `electron/assets/` : dossier pour les icônes (créer des placeholders PNG si absents)
>
> **ÉTAPE 2 — Créer python/ui_bridge.py**
>
> Créer `python/ui_bridge.py` (contenu complet dans la spec) qui :
> - Expose les fonctions via le décorateur `@expose`
> - Lance un serveur WebSocket asyncio sur `ws://127.0.0.1:9999`
> - Gère les événements unilatéraux via `emit(event_name, data)`
> - Gère le streaming LLM token par token via `emit_stream_token(id, token)`
> - Expose toutes les fonctions nécessaires : `get_available_models`, `set_model`, `ask`, `start_mic`, `stop_mic`, `get_conversations`, `new_conversation`, `load_conversation`, `delete_conversation`, `delete_all_conversations`, `set_conversation_mode`, `save_wallpaper`, `get_wallpapers`, `delete_wallpaper`, `get_settings`, `save_settings`, `speak_text`, `get_installed_apps`, `get_static_port`
>
> **ÉTAPE 3 — Modifier python/main.py**
>
> Réécrire main.py pour :
> - Supprimer TOUTES les références à pywebview, webview, ui.py
> - Importer et démarrer `ui_bridge.start()` à la place
> - Démarrer le serveur de fichiers statiques sur port 9998 (wallpapers)
> - Exposer `get_static_port()` via `ui_bridge.expose`
> - Garder le reste (Ollama, Whisper, mémoire, hooks clavier, serveur mobile)
>
> **ÉTAPE 4 — Modifier stt.py, tts.py, llm.py**
>
> Remplacer TOUS les appels à `ui.*` ou `_safe_js(...)` par des appels à `ui_bridge.*` :
> - `ui.set_status(s)` → `ui_bridge.set_status(s)`
> - `ui.update_waveform(rms)` → `ui_bridge.update_waveform(rms)`
> - `ui.show_final_transcription(t)` → `ui_bridge.show_final_transcription(t)`
> - `ui.show_partial_transcription(t)` → `ui_bridge.show_partial_transcription(t)`
> - `ui.show_toast(msg, type)` → `ui_bridge.show_toast(msg, type)`
> - `_safe_js(...)` → supprimer (remplacé par les événements WebSocket)
> - `ui.append_assistant_text(t)` → `ui_bridge.append_assistant_text(t)`
> - `ui.finalize_assistant_message()` → `ui_bridge.finalize_assistant_message()`
>
> **ÉTAPE 5 — Supprimer ou archiver**
>
> Déplacer dans un dossier `_archive/` (ne pas supprimer pour référence) :
> - `ui.py` (remplacé par ui_bridge.py)
>
> **ÉTAPE 6 — Ajouter la dépendance WebSocket Python**
>
> ```bash
> .venv\Scripts\python.exe -m pip install websockets
> ```
> Ajouter `websockets>=12.0` à requirements.txt.
>
> **ÉTAPE 7 — Installer Electron**
>
> ```bash
> cd electron
> npm install
> ```
>
> **ÉTAPE 8 — Test**
>
> Lancer dans deux terminaux séparés :
> ```bash
> # Terminal 1
> cd python && .venv\Scripts\python.exe main.py
>
> # Terminal 2 (après que Python affiche "=== ARIA Backend prêt ===")
> cd electron && npm start
> ```
>
> Vérifier que :
> - La fenêtre Electron s'ouvre
> - Les logs Python affichent "Electron connecté"
> - Le sélecteur de mode Écrit/Vocal s'affiche
> - La liste des modèles Ollama s'affiche dans les paramètres
> - Les wallpapers peuvent être importés et s'affichent correctement
> - Le micro fonctionne (transcription visible dans le champ texte)
> - L'envoi d'un message déclenche une vraie réponse Ollama
>
> Créer : electron/main.js, electron/preload.js, electron/package.json,
> electron/renderer/index.html, electron/renderer/app.js,
> electron/renderer/styles.css, python/ui_bridge.py.
>
> Modifier : python/main.py, python/stt.py, python/tts.py, python/llm.py,
> python/requirements.txt.
>
> Archiver : python/ui.py → python/_archive/ui.py.
