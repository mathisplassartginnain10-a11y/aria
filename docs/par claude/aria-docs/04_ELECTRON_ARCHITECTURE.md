# 04 — Electron Architecture

## Stack technique

```
Electron 31+
├── Main Process (Node.js)
│   ├── main.js              — fenêtre, tray, lifecycle
│   ├── preload.js           — contextBridge → window.ARIA
│   └── ipc-handlers.js      — routes IPC main↔renderer
│
├── Renderer Process (HTML/CSS/JS vanilla)
│   ├── index.html           — structure 3 colonnes
│   ├── app.js               — logique principale
│   └── styles.css           — design system complet
│
└── Python Backend (subprocess)
    └── Communique via WebSocket ws://127.0.0.1:PORT
```

## Communication Electron ↔ Python

```
Renderer → preload.js → ipcMain → WebSocket → Python
Python → WebSocket → ipcMain → renderer (ws-message event)
```

### Format messages WebSocket
```json
// Renderer → Python
{ "id": "req_001", "action": "ask", "args": ["lance chrome"], "kwargs": {} }

// Python → Renderer (réponse)
{ "id": "req_001", "type": "response", "data": "Chrome lancé", "error": null }

// Python → Renderer (stream token)
{ "id": "req_001", "type": "stream_token", "data": "Bon" }

// Python → Renderer (event unilatéral)
{ "id": null, "type": "event", "event": "stt_result", "data": "Lance Chrome" }
```

### window.ARIA API (preload.js)
```javascript
window.ARIA = {
  call: (action, ...args) => Promise,       // appel Python, retourne Promise
  stream: (action, args, {onToken, onEnd}), // streaming LLM token par token
  on: (event, callback) => unsubscribe,     // écoute event Python unilatéral
  openExternal: (url) => void,
  window: { minimize, maximize, close, quit },
};
```

## Fenêtre principale

```javascript
// main.js
mainWindow = new BrowserWindow({
  width: primaryDisplay.workAreaSize.width,
  height: primaryDisplay.workAreaSize.height,
  backgroundColor: '#060B1A',
  titleBarStyle: 'hidden',
  frame: false,
  show: false,
  webPreferences: {
    preload: path.join(__dirname, 'preload.js'),
    contextIsolation: true,
    nodeIntegration: false,
    sandbox: false,
  },
  icon: path.join(__dirname, 'assets', 'icon.png'),
});

mainWindow.once('ready-to-show', () => {
  mainWindow.maximize();
  mainWindow.show();
});
```

## Port WebSocket dynamique

Python écrit le port dans `%TEMP%/aria_ws_port.json`.
Electron le lit au démarrage et s'y connecte.

```javascript
// main.js
const PORT_FILE = path.join(os.tmpdir(), 'aria_ws_port.json');

async function getWsPort(retries = 20) {
  for (let i = 0; i < retries; i++) {
    if (fs.existsSync(PORT_FILE)) {
      const { port } = JSON.parse(fs.readFileSync(PORT_FILE, 'utf8'));
      if (port) return port;
    }
    await new Promise(r => setTimeout(r, 500));
  }
  return 9999; // fallback
}
```

## Démarrage

```javascript
// main.js — ordre de démarrage
app.whenReady().then(() => {
  fs.unlinkSync(PORT_FILE);  // nettoyer port précédent
  createWindow();
  createTray();
  startPythonBackend();
  setTimeout(async () => {
    const port = await getWsPort();
    connectWebSocket(15, port);
  }, 1000);
});
```

## Tray icon

Actions disponibles :
- Ouvrir (show + maximize + focus)
- Micro ON/OFF
- Quitter ARIA (kill Python + Electron)

## Lancement via recherche Windows

```bat
@echo off
title ARIA
cd /d "c:\Users\mathi\OneDrive\Documents\assistant-ia\assistant-vocal"
taskkill /f /im python.exe >nul 2>&1
taskkill /f /im electron.exe >nul 2>&1
timeout /t 1 >nul
del "%TEMP%\aria_ws_port.json" >nul 2>&1
start /min "" cmd /c ".\.venv\Scripts\python.exe python\main.py > "%TEMP%\aria_python.log" 2>&1"
:WAIT
timeout /t 1 >nul
if not exist "%TEMP%\aria_ws_port.json" goto WAIT
timeout /t 1 >nul
cd electron && start "" node_modules\.bin\electron.cmd .
```

Raccourci installé dans le menu Démarrer via `scripts/install_shortcut.ps1`.
