/**
 * main.js — Process principal Electron
 * Lance le backend Python, gère la fenêtre, le tray icon.
 */

const { app, BrowserWindow, Tray, Menu, ipcMain, shell, screen, dialog, nativeImage } = require('electron');
const path = require('path');
const os = require('os');
const { spawn } = require('child_process');
const WebSocket = require('ws');
const fs = require('fs');

// ── Configuration ─────────────────────────────────────────────────────────────

const DEFAULT_WS_PORT = 9999;
const PORT_FILE = path.join(os.tmpdir(), 'aria_ws_port.json');
const PYTHON_BACKEND = path.join(__dirname, '..', 'python', 'main.py');
const PYTHON_EXE = process.platform === 'win32'
  ? path.join(__dirname, '..', '.venv', 'Scripts', 'python.exe')
  : path.join(__dirname, '..', '.venv', 'bin', 'python3');

const APP_ICON_PNG = path.join(__dirname, 'assets', 'icon.png');
const APP_ICON_ICO = path.join(__dirname, 'assets', 'icon.ico');
const TRAY_ICON_PNG = path.join(__dirname, 'assets', 'tray-icon.png');

let ICON_BASE64 = '';
try {
  const iconBuffer = fs.readFileSync(APP_ICON_PNG);
  ICON_BASE64 = `data:image/png;base64,${iconBuffer.toString('base64')}`;
} catch (e) {
  console.error('Erreur lecture icon.png:', e.message);
}

function resolveAppIcon() {
  if (process.platform === 'win32' && fs.existsSync(APP_ICON_ICO)) {
    return APP_ICON_ICO;
  }
  return APP_ICON_PNG;
}

function resolveTrayIcon() {
  if (fs.existsSync(TRAY_ICON_PNG)) {
    return TRAY_ICON_PNG;
  }
  if (fs.existsSync(APP_ICON_PNG)) {
    return APP_ICON_PNG;
  }
  return APP_ICON_ICO;
}

function injectAriaIcon(webContents) {
  if (!ICON_BASE64) return Promise.resolve();
  return webContents.executeJavaScript(`
    window.__ARIA_ICON__ = ${JSON.stringify(ICON_BASE64)};
    document.querySelectorAll('[data-aria-logo]').forEach(img => {
      img.src = window.__ARIA_ICON__;
    });
  `);
}

// ── État global ───────────────────────────────────────────────────────────────

let mainWindow = null;
let splashWindow = null;
let tray = null;
let trayMenu = null;
let micTrayActive = false;
let pythonProcess = null;
let wsClient = null;
let wsReady = false;
let pendingMessages = [];
let activeWsPort = DEFAULT_WS_PORT;

function getWsPort(retries = 20) {
  return new Promise((resolve) => {
    const tryRead = (attempt) => {
      try {
        if (fs.existsSync(PORT_FILE)) {
          const data = JSON.parse(fs.readFileSync(PORT_FILE, 'utf8'));
          if (data.port) {
            console.log(`[Electron] Port WebSocket: ${data.port}`);
            resolve(data.port);
            return;
          }
        }
      } catch (e) {
        // Fichier pas encore prêt
      }

      if (attempt < retries) {
        setTimeout(() => tryRead(attempt + 1), 500);
      } else {
        console.error('[Electron] Port file not found — fallback 9999');
        resolve(DEFAULT_WS_PORT);
      }
    };
    tryRead(0);
  });
}

// ── Lancement du backend Python ───────────────────────────────────────────────

function startPythonBackend() {
  console.log('[Electron] Lancement backend Python:', PYTHON_BACKEND);

  const env = {
    ...process.env,
    PYTHONUTF8: '1',
    ARIA_ELECTRON_MODE: '1',
  };

  pythonProcess = spawn(PYTHON_EXE, [PYTHON_BACKEND], {
    env,
    stdio: ['pipe', 'pipe', 'pipe'],
    cwd: path.join(__dirname, '..'),
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
}

// ── Connexion WebSocket vers Python ──────────────────────────────────────────

function connectWebSocket(retries = 15, port = DEFAULT_WS_PORT) {
  console.log(`[Electron] Connexion WebSocket ws://127.0.0.1:${port}...`);

  const ws = new WebSocket(`ws://127.0.0.1:${port}`);

  ws.on('open', () => {
    console.log('[Electron] WebSocket connecté');
    wsClient = ws;
    wsReady = true;

    // Envoyer les messages en attente
    pendingMessages.forEach(msg => ws.send(msg));
    pendingMessages = [];

    // Notifier le process principal et le renderer que le backend est prêt
    ipcMain.emit('backend-ready-main');
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('backend-ready');
    }
  });

  ws.on('message', (data) => {
    try {
      const msg = JSON.parse(data.toString());
      if (msg.type === 'event' && msg.event === 'mic_state') {
        micTrayActive = !!msg.data;
        rebuildTrayMenu();
      }
      // Relayer le message au renderer (fenêtre principale + splash)
      const targets = [mainWindow, splashWindow].filter(
        (w) => w && !w.isDestroyed()
      );
      for (const win of targets) {
        win.webContents.send('ws-message', msg);
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
      setTimeout(() => connectWebSocket(retries - 1, port), 1000);
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
// Contrôles de fenêtre
ipcMain.on('window-minimize', () => { if (mainWindow) mainWindow.minimize(); });
ipcMain.on('window-maximize', () => {
  if (mainWindow) {
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else mainWindow.maximize();
  }
});
ipcMain.on('window-close', () => { if (mainWindow) mainWindow.close(); });

ipcMain.handle('pick-gguf-file', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Importer un modèle GGUF',
    properties: ['openFile'],
    filters: [{ name: 'Modèles GGUF', extensions: ['gguf'] }],
  });
  if (result.canceled || !result.filePaths?.length) return null;
  return result.filePaths[0];
});


// ── Splash screen au démarrage ────────────────────────────────────────────────

function createSplashWindow() {
  splashWindow = new BrowserWindow({
    width: 480,
    height: 700,
    frame: false,
    transparent: false,
    resizable: false,
    center: true,
    alwaysOnTop: true,
    backgroundColor: '#04080F',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.js'),
    },
  });
  splashWindow.loadFile(path.join(__dirname, 'renderer', 'splash.html'));
  splashWindow.webContents.on('did-finish-load', () => {
    injectAriaIcon(splashWindow.webContents).catch(() => {});
  });
  splashWindow.once('ready-to-show', () => splashWindow.show());
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.executeJavaScript(`
      document.getElementById('splash').classList.add('fadeout');
      setTimeout(()=>{document.getElementById('finish-overlay').classList.add('active')},800);
    `);
    setTimeout(() => {
      if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
      splashWindow = null;
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.maximize();
        mainWindow.show();
        mainWindow.focus();
      }
    }, 1400);
  } else if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.maximize();
    mainWindow.show();
    mainWindow.focus();
  }
}

// ── Création de la fenêtre principale ─────────────────────────────────────────

function createWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;
  const iconPath = resolveAppIcon();

  mainWindow = new BrowserWindow({
    width: width,
    height: height,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: '#04080F',
    titleBarStyle: 'hidden',
    frame: false,
    transparent: false,
    maximized: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      webSecurity: true,
    },
    icon: iconPath,
    show: false,
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  mainWindow.webContents.on('did-finish-load', () => {
    injectAriaIcon(mainWindow.webContents).catch(() => {});
  });

  mainWindow.once('ready-to-show', () => {
    if (process.env.ARIA_DEV) {
      mainWindow.webContents.openDevTools();
    }
  });

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

function rebuildTrayMenu() {
  if (!tray) return;

  trayMenu = Menu.buildFromTemplate([
    {
      label: 'ARIA',
      enabled: false,
    },
    { type: 'separator' },
    {
      label: 'Ouvrir',
      click: () => showMainWindow(),
    },
    {
      label: micTrayActive ? 'Micro : ON' : 'Micro : OFF',
      type: 'checkbox',
      checked: micTrayActive,
      click: () => sendToPython('toggle_activation', []),
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

  tray.setContextMenu(trayMenu);
}

function showMainWindow() {
  if (!mainWindow) return;
  mainWindow.show();
  mainWindow.maximize();
  mainWindow.focus();
}

function createTray() {
  const iconPath = resolveTrayIcon();
  let trayIcon = nativeImage.createFromPath(iconPath);
  if (trayIcon.isEmpty()) {
    console.warn('[Electron] Tray icon missing or invalid:', iconPath);
    trayIcon = nativeImage.createFromPath(APP_ICON_PNG);
  }
  if (trayIcon.isEmpty()) {
    trayIcon = nativeImage.createEmpty();
  }
  tray = new Tray(trayIcon);

  rebuildTrayMenu();
  tray.setToolTip('ARIA — Assistant Personnel');

  tray.on('click', () => {
    if (!mainWindow) return;
    if (mainWindow.isVisible()) {
      mainWindow.hide();
    } else {
      showMainWindow();
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
  if (process.platform === 'win32') {
    app.setAppUserModelId('com.aria.assistant');
  }
  try { fs.unlinkSync(PORT_FILE); } catch (e) {}
  createSplashWindow();
  createWindow();
  createTray();
  startPythonBackend();

  let backendReady = false;
  let minTimeReached = false;

  const tryCloseSplash = () => {
    if (backendReady && minTimeReached) closeSplash();
  };

  setTimeout(() => {
    minTimeReached = true;
    tryCloseSplash();
  }, 5200);

  setTimeout(async () => {
    activeWsPort = await getWsPort();
    connectWebSocket(15, activeWsPort);
    ipcMain.once('backend-ready-main', () => {
      backendReady = true;
      tryCloseSplash();
    });
  }, 1000);

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
