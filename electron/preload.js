/**
 * preload.js — Bridge sécurisé entre le renderer et le process principal.
 * Expose uniquement les APIs nécessaires via contextBridge.
 */

const { contextBridge, ipcRenderer } = require('electron');
const path = require('path');
const { pathToFileURL } = require('url');

const assetsDir = path.join(__dirname, 'assets');
const iconPath = path.join(assetsDir, 'icon.png');
const iconUrl = pathToFileURL(iconPath).href;
const assetsDirUrl = pathToFileURL(assetsDir).href;

contextBridge.exposeInMainWorld('ARIA_ASSETS', {
  iconUrl,
  assetsDir: assetsDirUrl,
});

contextBridge.exposeInMainWorld('ARIA_ICON_URL', iconUrl);

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

  pickGgufFile: () => ipcRenderer.invoke('pick-gguf-file'),

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
