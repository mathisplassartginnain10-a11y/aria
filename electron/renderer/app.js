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

function requireAria() {
  if (!window.ARIA) {
    throw new Error('window.ARIA non disponible — preload.js pas encore chargé ?');
  }
  return window.ARIA;
}

const api = {
  call: (action, ...args) => requireAria().call(action, ...args),
  stream: (action, args, callbacks) => requireAria().stream(action, args, callbacks),
  on: (event, cb) => {
    if (window.ARIA) return window.ARIA.on(event, cb);
    const handler = (e) => cb(e.detail);
    window.addEventListener(`aria:${event}`, handler);
    return () => window.removeEventListener(`aria:${event}`, handler);
  },
};

// ── Initialisation ────────────────────────────────────────────────────────────

async function init() {
  console.log('[ARIA] Initialisation...');
  console.log('[ARIA] Attente backend...');
  await waitForBackend();
  console.log('[ARIA] Backend prêt');

  await loadSettings();
  applyTheme(state.settings.theme || 'slate');
  setGlassIntensity(state.settings.glass_intensity || 60);
  restoreWallpaper();

  await refreshConversationList();

  const lastConvId = state.settings.last_conversation_id;
  if (lastConvId) {
    await loadConversation(lastConvId);
  } else {
    await newConversation();
  }

  setupEventListeners();
  console.log('[ARIA] Prêt');
}

function waitForBackend() {
  return new Promise((resolve) => {
    if (state.backendReady && window.ARIA) return resolve();

    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      state.backendReady = true;
      resolve();
    };

    const check = () => {
      if (window.ARIA) finish();
      else setTimeout(check, 100);
    };

    window.addEventListener('aria:backend-ready', finish, { once: true });

    setTimeout(() => {
      if (!settled) {
        console.warn('[ARIA] Timeout backend-ready — continuer sans confirmation');
        finish();
      }
    }, 10000);

    check();
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

  api.on('tts_finished', () => {
    if (state.micActive) setStatus('listening');
    else setStatus('idle');
  });
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

function hideModeSelector() {
  const overlay = document.getElementById('mode-select-overlay');
  if (!overlay) return;
  overlay.classList.add('hidden');
  overlay.style.pointerEvents = 'none';
}

function showModeSelector() {
  const overlay = document.getElementById('mode-select-overlay');
  if (!overlay) return;
  overlay.classList.remove('hidden');
  overlay.style.pointerEvents = '';
}

async function selectConversationMode(mode) {
  if (!window.ARIA) {
    console.error('window.ARIA non disponible — preload.js pas encore chargé ?');
    setTimeout(() => selectConversationMode(mode), 500);
    return;
  }

  hideModeSelector();

  try {
    if (state.currentConvId) {
      await window.ARIA.call('set_conversation_mode', state.currentConvId, mode);
    }
  } catch (e) {
    console.error('set_conversation_mode error:', e);
    showToast('Erreur enregistrement du mode', 'error');
  }

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

// ── AnimationController (overlay skippable — doit se détruire au stop) ─────────

const AnimationController = {
  _current: null,
  _skipOverlay: null,

  play(animFn, opts = {}) {
    this.stop();
    const overlay = document.createElement('div');
    overlay.style.cssText =
      'position:fixed;inset:0;z-index:7998;cursor:pointer;pointer-events:all;background:transparent;';
    overlay.id = 'anim-skip-overlay';
    document.body.appendChild(overlay);
    this._skipOverlay = overlay;

    const ctrl = { stopped: false, cleanup: null };
    this._current = ctrl;

    const stop = () => this.stop();
    overlay.addEventListener('click', stop);
    const onKey = (e) => {
      if (e.key === 'Escape') {
        stop();
        document.removeEventListener('keydown', onKey);
      }
    };
    document.addEventListener('keydown', onKey);

    ctrl.cleanup = animFn(ctrl, opts);
    return ctrl;
  },

  stop() {
    if (this._current) {
      this._current.stopped = true;
      if (typeof this._current.cleanup === 'function') {
        try { this._current.cleanup(); } catch (e) { console.warn('Animation cleanup:', e); }
      }
      this._current = null;
    }
    if (this._skipOverlay) {
      this._skipOverlay.remove();
      this._skipOverlay = null;
    }
    document.getElementById('anim-skip-overlay')?.remove();
  },
};

function cleanupBlockingOverlays() {
  AnimationController.stop();
  document.querySelectorAll('#anim-skip-overlay').forEach(el => el.remove());
}

// ── Démarrage ─────────────────────────────────────────────────────────────────

function bindTitleBarButtons() {
  document.getElementById('win-minimize')?.addEventListener('click', () => {
    window.ARIA?.window?.minimize();
  });
  document.getElementById('win-maximize')?.addEventListener('click', () => {
    window.ARIA?.window?.maximize();
  });
  document.getElementById('win-close')?.addEventListener('click', () => {
    window.ARIA?.window?.close();
  });
}

function bindMainUiButtons() {
  const actions = {
    'new-conv-btn': () => newConversation(),
    'delete-all-btn': () => deleteAllConversations(),
    'export-btn': () => window.app?.exportConversation?.(),
    'settings-btn': () => toggleSettings(),
    'settings-close-btn': () => toggleSettings(),
    'mic-btn': () => toggleMic(),
    'send-btn': () => sendMessage(),
  };
  Object.entries(actions).forEach(([id, fn]) => {
    document.getElementById(id)?.addEventListener('click', (e) => {
      e.preventDefault();
      fn();
    });
  });

  document.querySelectorAll('.acc-header').forEach(el => {
    const accId = el.closest('.settings-accordion')?.id?.replace(/^acc-/, '');
    if (!accId) return;
    el.addEventListener('click', () => toggleAccordion(accId));
  });

  document.querySelectorAll('.theme-pill[data-theme]').forEach(btn => {
    btn.addEventListener('click', () => setTheme(btn.dataset.theme));
  });

  document.querySelectorAll('.wp-thumb').forEach(el => {
    const wpClass = [...el.classList].find(c => c.startsWith('wp-') && c !== 'wp-thumb');
    if (!wpClass) return;
    el.addEventListener('click', () => setWallpaper(wpClass.replace(/^wp-/, '')));
  });

  const loadModelsBtn = document.querySelector('#acc-modeles .settings-btn-outline');
  loadModelsBtn?.addEventListener('click', () => loadModelSettings());

  const micDiagBtn = document.querySelector('#acc-micro .settings-btn-outline');
  micDiagBtn?.addEventListener('click', () => window.app?.runMicDiagnostic?.());

  const textInput = document.getElementById('text-input');
  textInput?.addEventListener('keydown', handleInputKeydown);
  textInput?.addEventListener('input', function onInput() { adjustTextarea(this); });
}

function bindModeSelectorButtons() {
  document.querySelectorAll('#mode-select-buttons button[data-mode]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const mode = btn.getAttribute('data-mode');
      console.log('Mode sélectionné:', mode);
      selectConversationMode(mode);
    });
  });
}

function exposeGlobalApp() {
  window.app = {
    newConversation,
    loadConversation,
    deleteConversation,
    deleteAllConversations,
    sendMessage,
    handleInputKeydown,
    adjustTextarea,
    toggleMic,
    selectConversationMode,
    toggleSettings,
    toggleAccordion,
    loadModelSettings,
    setModel,
    setTheme,
    setGlassIntensity,
    setWallpaper,
    uploadWallpaper,
    deleteWallpaper,
    saveSetting,
    exportConversation: () => api.call('export_current_conversation'),
    runMicDiagnostic: () => api.call('run_mic_diagnostic'),
    handleFiles: () => showToast('Pièces jointes — bientôt disponible', 'info'),
  };

  Object.assign(window, {
    loadConversation,
    deleteConversation,
    setModel,
    setWallpaper,
    deleteWallpaper,
    selectConversationMode,
  });
}

function boot() {
  cleanupBlockingOverlays();
  bindTitleBarButtons();
  bindMainUiButtons();
  bindModeSelectorButtons();
  exposeGlobalApp();
  init();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
