/**
 * app.js — Logique de l'application ARIA (renderer process)
 * Remplace tout le JS inline de l'ancien index.html
 */

// ── État global de l'application ──────────────────────────────────────────────

const state = {
  currentConvId: null,
  currentPage: 'home',
  conversationMode: 'ecrit',
  micActive: false,
  micPaused: false,
  ttsEnabled: false,
  backendReady: false,
  settings: {},
  _vocalCountdownTimer: null,
  _originalTranscription: '',
  _staticPort: 9998,
  _streamingMessage: null,
  _clockInterval: null,
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
  await waitForBackend();
  console.log('[ARIA] Backend prêt');

  try {
    const port = await api.call('get_static_port');
    if (port) state._staticPort = port;
  } catch (_) {}

  await loadSettings();
  applyTheme(state.settings.theme || 'slate');
  setGlassIntensity(state.settings.glass_intensity ?? 60);
  await restoreWallpaper();
  applySettingsForm();

  await refreshConversationList();
  await initWidgets();

  const lastConvId = state.settings.last_conversation_id;
  if (lastConvId) {
    await loadConversation(lastConvId);
  } else {
    await newConversation();
  }

  setupEventListeners();
  initLogoParticles();
  navigate('home');
  updateClock();
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

  api.on('thinking_start', () => setStatus('thinking'));
  api.on('thinking_action', (action) => {
    const subtitle = document.getElementById('sidebar-subtitle');
    if (subtitle && action) subtitle.textContent = action;
    setStatus('thinking');
  });
  api.on('thinking_hide', () => {
    if (state.micActive) setStatus('listening');
    else setStatus('idle');
  });

  // Waveform micro
  api.on('waveform', (rms) => updateWaveform(rms));

  // Toast
  api.on('toast', ({ message, type }) => showToast(message, type));

  // Message utilisateur depuis le backend
  api.on('user_message', (text) => {
    showHomeConversation();
    addUserBubble(text);
  });

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
  const badge = document.getElementById('conv-badge');
  if (badge) badge.textContent = conversations.length ? String(conversations.length) : '';

  const html = !conversations.length
    ? '<div class="empty-conv-list">Aucune conversation</div>'
    : conversations.map(conv => {
        const isActive = conv.id === state.currentConvId;
        const title = esc(conv.title || 'Nouvelle conversation');
        const date = conv.updated_at
          ? new Date(conv.updated_at).toLocaleDateString('fr-FR')
          : '';

        return `
          <div class="conv-item ${isActive ? 'active' : ''}" id="conv-${conv.id}"
               onmouseenter="this.querySelector('.conv-delete')?.style && (this.querySelector('.conv-delete').style.opacity='1')"
               onmouseleave="this.querySelector('.conv-delete')?.style && (this.querySelector('.conv-delete').style.opacity='0')">
            <div class="conv-content" onclick="loadConversation('${conv.id}')">
              <div class="conv-title">${title}</div>
              <div class="conv-date">${date}</div>
            </div>
            <button class="conv-delete"
              onclick="event.stopPropagation();deleteConversation('${conv.id}','${title.replace(/'/g, "\\'")}')">
              ✕
            </button>
          </div>`;
      }).join('');

  const listFull = document.getElementById('conv-list-full');
  if (listFull) listFull.innerHTML = html;

  const listLegacy = document.getElementById('conversations-list');
  if (listLegacy) listLegacy.innerHTML = html;
}

function loadFullConversationList() {
  refreshConversationList();
}

async function newConversation() {
  try {
    const result = await api.call('new_conversation');
    state.currentConvId = result.id;
    showHomeIdle();
    await refreshConversationList();
    navigate('home');
    showModeSelector();
  } catch (e) {
    showToast('Erreur création conversation', 'error');
  }
}

async function loadConversation(convId) {
  try {
    const result = await api.call('load_conversation', convId);
    state.currentConvId = result.id;

    const messagesEl = document.getElementById('messages');
    if (messagesEl) messagesEl.innerHTML = '';
    (result.messages || []).forEach(msg => {
      if (msg.role === 'user') addUserBubble(msg.content, false);
      else addAriaBubble(msg.content, false);
    });

    const mode = await api.call('get_conversation_mode', convId);
    if (mode) {
      applyConversationMode(mode);
    } else {
      showModeSelector();
    }

    if ((result.messages || []).length) showHomeConversation();
    else showHomeIdle();

    await refreshConversationList();
    navigate('home');
    scrollToBottom();
  } catch (e) {
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
  showHomeConversation();
  const messages = document.getElementById('messages');
  if (!messages) return;
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
  navigate('home');
  showHomeConversation();
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

function initLogoParticles() {
  const container = document.getElementById('home-logo-particles');
  if (!container || container.childElementCount > 0) return;

  for (let i = 0; i < 8; i++) {
    const p = document.createElement('div');
    p.className = 'logo-particle';
    const angle = (i / 8) * Math.PI * 2;
    const radius = 25 + Math.random() * 15;
    p.style.cssText = `
      --x: ${50 + Math.cos(angle) * radius}%;
      --y: ${50 + Math.sin(angle) * radius}%;
      --dx: ${(Math.random() - 0.5) * 20}px;
      --dy: ${(Math.random() - 0.5) * 20}px;
      --dx2: ${(Math.random() - 0.5) * 30}px;
      --dy2: ${(Math.random() - 0.5) * 30}px;
      --dx3: ${(Math.random() - 0.5) * 40}px;
      --dy3: ${(Math.random() - 0.5) * 40}px;
      --dur: ${1.5 + Math.random() * 2}s;
      --delay: ${Math.random() * 2}s;
    `;
    container.appendChild(p);
  }
}

function setStatus(s) {
  const subtitle = document.getElementById('sidebar-subtitle');
  const homeLogo = document.getElementById('home-logo');
  const sidebarWrap = document.getElementById('sidebar-logo-wrap');

  const labels = {
    idle: 'En veille',
    listening: 'Écoute...',
    transcribing: 'Transcription...',
    thinking: 'Réfléchit...',
    speaking: 'Parle...',
  };
  const label = labels[s] || s;
  if (subtitle) {
    subtitle.textContent = label;
    subtitle.className = `status-${s === 'idle' ? 'idle' : 'active'}`;
  }

  const map = {
    idle: 'logo-idle',
    listening: 'logo-listening',
    transcribing: 'logo-listening',
    thinking: 'logo-thinking',
    speaking: 'logo-speaking',
  };
  const cls = map[s] || 'logo-idle';

  [homeLogo, sidebarWrap].forEach(el => {
    if (!el) return;
    el.classList.remove('logo-idle', 'logo-listening', 'logo-thinking', 'logo-speaking');
    el.classList.add(cls);
  });
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
    if (['user_firstname', 'hello_text', 'sub_text'].includes(key)) updateClock();
  } catch (e) {
    console.error('Erreur sauvegarde setting:', e);
  }
}

function toggleSettings() {
  navigate(state.currentPage === 'settings' ? 'home' : 'settings');
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

// ── Widgets temps réel ────────────────────────────────────────────────────────

async function initWidgets() {
  updateClock();
  if (state._clockInterval) clearInterval(state._clockInterval);
  state._clockInterval = setInterval(updateClock, 1000);

  await loadWeatherWidget();
  setInterval(loadWeatherWidget, 5 * 60 * 1000);

  await loadMemoryWidget();
  setInterval(loadMemoryWidget, 30 * 1000);

  loadShortcutsWidget();
  updateBattery();
}

function updateClock() {
  const now = new Date();
  const timeEl = document.getElementById('wval-time');
  const greetingEl = document.getElementById('home-greeting');
  const dateEl = document.getElementById('home-date');

  if (timeEl) {
    timeEl.textContent = now.toLocaleTimeString('fr-FR', {
      hour: '2-digit', minute: '2-digit',
    });
  }

  const firstname = state.settings?.user_firstname || 'Mathis';
  const h = now.getHours();
  const salut = h < 12 ? 'Bonjour' : h < 18 ? 'Bon après-midi' : 'Bonsoir';

  if (greetingEl) greetingEl.textContent = `${salut}, ${firstname}.`;

  if (dateEl) {
    dateEl.textContent = now.toLocaleDateString('fr-FR', {
      weekday: 'long', day: 'numeric', month: 'long',
    });
  }

  const helloEl = document.getElementById('home-hello-text');
  const subEl = document.getElementById('home-sub-text');
  if (helloEl) {
    helloEl.textContent = state.settings?.hello_text ||
      `${salut}, ${firstname}.`;
  }
  if (subEl) {
    subEl.textContent = state.settings?.sub_text || 'Comment puis-je vous aider aujourd\'hui ?';
  }

  const tasksLabel = document.getElementById('wlabel-tasks');
  if (tasksLabel && tasksLabel.textContent === 'Chargement...') {
    tasksLabel.textContent = 'Aucune tâche planifiée';
  }
}

async function updateBattery() {
  const el = document.getElementById('wval-battery');
  if (!el || !navigator.getBattery) {
    if (el) el.textContent = 'N/A';
    return;
  }
  try {
    const bat = await navigator.getBattery();
    const pct = Math.round(bat.level * 100);
    el.textContent = `${pct}%${bat.charging ? ' ⚡' : ''}`;
    bat.addEventListener('levelchange', () => {
      el.textContent = `${Math.round(bat.level * 100)}%${bat.charging ? ' ⚡' : ''}`;
    });
  } catch {
    if (el) el.textContent = 'N/A';
  }
}

async function loadWeatherWidget() {
  try {
    const data = await api.call('get_weather_widget') || {};
    const valEl = document.getElementById('wval-meteo');
    const iconEl = document.getElementById('wicon-meteo');

    if (data.error || data.temp == null) {
      if (valEl) valEl.textContent = 'N/A';
      return;
    }

    const weatherIcons = {
      ensoleillé: '☀️', clair: '☀️', soleil: '☀️',
      nuageux: '☁️', couvert: '☁️', nuage: '☁️',
      pluie: '🌧️', pluvieux: '🌧️',
      brouillard: '🌫️', brume: '🌫️',
      neige: '❄️', orage: '⛈️',
    };
    const desc = (data.description || '').toLowerCase();
    const icon = Object.entries(weatherIcons).find(([k]) => desc.includes(k))?.[1] || '🌡️';

    if (iconEl) iconEl.textContent = icon;
    if (valEl) valEl.textContent = `${Math.round(data.temp)}° ${data.city || ''}`;
  } catch {
    const el = document.getElementById('wval-meteo');
    if (el) el.textContent = 'N/A';
  }
}

async function loadMemoryWidget() {
  try {
    const data = await api.call('get_memory_stats') || {};

    document.getElementById('mem-convs')?.replaceChildren(document.createTextNode(String(data.conversations ?? 0)));
    document.getElementById('mem-msgs')?.replaceChildren(document.createTextNode(String(data.messages ?? 0)));
    document.getElementById('mem-sessions')?.replaceChildren(document.createTextNode(String(data.sessions ?? 0)));

    const pct = Math.min(100, Math.round((data.messages || 0) / 5));
    const pctEl = document.getElementById('memory-pct');
    if (pctEl) pctEl.textContent = `${pct}%`;
    drawMemoryDonut(pct);

    const statsEl = document.getElementById('memory-stats-label');
    if (statsEl) {
      statsEl.textContent = `${data.conversations ?? 0} conversations · ${data.messages ?? 0} messages`;
    }
  } catch (e) {
    console.warn('loadMemoryWidget:', e);
  }
}

function drawMemoryDonut(pct) {
  const canvas = document.getElementById('memory-donut');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const cx = 50; const cy = 50; const r = 38; const lw = 8;

  ctx.clearRect(0, 0, 100, 100);

  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.strokeStyle = 'rgba(255,255,255,0.08)';
  ctx.lineWidth = lw;
  ctx.stroke();

  const angle = (pct / 100) * Math.PI * 2 - Math.PI / 2;
  const grad = ctx.createLinearGradient(0, 0, 100, 100);
  grad.addColorStop(0, '#6C8EFF');
  grad.addColorStop(1, '#A78BFA');
  ctx.beginPath();
  ctx.arc(cx, cy, r, -Math.PI / 2, angle);
  ctx.strokeStyle = grad;
  ctx.lineWidth = lw;
  ctx.lineCap = 'round';
  ctx.stroke();
}

async function loadShortcutsWidget() {
  try {
    const presets = await api.call('get_presets') || [];
    const grid = document.getElementById('shortcuts-grid');
    if (!grid) return;

    const fixed = [
      { icon: '✉️', label: 'Rédiger un email', action: 'rédige un email', color: '#6C8EFF' },
      { icon: '🎯', label: 'Démarrer focus', action: 'active le mode focus', color: '#A78BFA' },
      { icon: '📊', label: 'Analyse système', action: 'analyse le système', color: '#4ADE80' },
    ];

    const presetShortcuts = presets.slice(0, 3).map(p => ({
      icon: p.icon || '⚡',
      label: `Mode ${p.name}`,
      action: `active le mode ${p.name}`,
      color: '#F59E0B',
    }));

    const all = [...fixed, ...presetShortcuts].slice(0, 6);

    grid.innerHTML = all.map(s => `
      <button class="shortcut-btn" onclick="app.quickAction(${JSON.stringify(s.action)})"
              style="--shortcut-color: ${s.color}">
        <span class="shortcut-icon">${s.icon}</span>
        <span class="shortcut-label">${esc(s.label)}</span>
      </button>
    `).join('');
  } catch (e) {
    console.warn('loadShortcutsWidget:', e);
  }
}

async function quickAction(text) {
  navigate('home');
  showHomeConversation();
  if (!state.currentConvId) {
    try {
      const result = await api.call('new_conversation');
      state.currentConvId = result.id;
      await refreshConversationList();
    } catch (e) {
      showToast('Erreur création conversation', 'error');
      return;
    }
  }
  hideModeSelector();
  setStatus('thinking');
  try {
    await api.call('ask', text, state.conversationMode);
  } catch (e) {
    showToast('Erreur: ' + e.message, 'error');
    setStatus('idle');
  }
}

function navigate(page) {
  document.querySelectorAll('.page').forEach(p => {
    p.classList.add('hidden');
    p.classList.remove('active');
  });
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  const pageEl = document.getElementById(`page-${page}`);
  if (pageEl) {
    pageEl.classList.remove('hidden');
    pageEl.classList.add('active');
  }

  document.querySelectorAll(`[data-page="${page}"]`).forEach(btn => btn.classList.add('active'));

  state.currentPage = page;

  if (page === 'conversations') loadFullConversationList();
  if (page === 'agents') loadAgentsPage();
  if (page === 'memory') loadMemoryPage();
  if (page === 'settings') {
    loadModelSettings();
    loadApiKeys();
    applySettingsForm();
    loadCustomWallpapers();
  }
}

function showHomeConversation() {
  document.getElementById('home-logo-container')?.classList.add('shrunk');
  document.getElementById('home-messages')?.classList.remove('hidden');
}

function showHomeIdle() {
  document.getElementById('home-logo-container')?.classList.remove('shrunk');
  document.getElementById('home-messages')?.classList.add('hidden');
  const messages = document.getElementById('messages');
  if (messages) messages.innerHTML = '';
}

function applyGreeting() {
  const firstname = document.getElementById('set-firstname')?.value?.trim();
  const hello = document.getElementById('set-hello-text')?.value?.trim();
  const sub = document.getElementById('set-sub-text')?.value?.trim();
  if (firstname) saveSetting('user_firstname', firstname);
  if (hello) saveSetting('hello_text', hello);
  if (sub) saveSetting('sub_text', sub);
  updateClock();
  showStyledSettingToast('✓ Salutation mise à jour', '#4ADE80');
}

function applySettingsForm() {
  const s = state.settings;
  const firstnameEl = document.getElementById('set-firstname');
  const helloEl = document.getElementById('set-hello-text');
  const subEl = document.getElementById('set-sub-text');
  const glassEl = document.getElementById('set-glass');

  if (firstnameEl && s.user_firstname) firstnameEl.value = s.user_firstname;
  if (helloEl && s.hello_text) helloEl.value = s.hello_text;
  if (subEl && s.sub_text) subEl.value = s.sub_text;
  if (glassEl && s.glass_intensity != null) glassEl.value = s.glass_intensity;
}

function showStyledSettingToast(message, color) {
  showToast(message, 'success');
  void color;
}

function validateSection(section) {
  showStyledSettingToast(`✓ Section ${section} appliquée`, '#4ADE80');
}

function toggleWidget(name) {
  const body = document.getElementById(`widget-${name}-body`);
  if (body) body.classList.toggle('collapsed');
}

function toggleModeMenu() {
  document.getElementById('mode-menu')?.classList.toggle('hidden');
}

function toggleAgentDropdown() {
  document.getElementById('agent-dropdown')?.classList.toggle('hidden');
}

function setPrivacyMode(enabled) {
  const badge = document.getElementById('home-mode-badge');
  if (badge) badge.classList.toggle('private', !!enabled);
  saveSetting('privacy_mode', !!enabled);
}

async function loadMemoryPage() {
  await loadMemoryWidget();
  const content = document.getElementById('memory-content');
  if (!content) return;
  try {
    const data = await api.call('get_memory_stats') || {};
    content.innerHTML = `
      <div class="memory-page-stats">
        <div class="mem-stat-card"><div class="mem-stat-val">${data.conversations ?? 0}</div><div class="mem-stat-label">Conversations</div></div>
        <div class="mem-stat-card"><div class="mem-stat-val">${data.messages ?? 0}</div><div class="mem-stat-label">Messages</div></div>
        <div class="mem-stat-card"><div class="mem-stat-val">${data.sessions ?? 0}</div><div class="mem-stat-label">Sessions</div></div>
      </div>`;
  } catch {
    content.innerHTML = '<div class="error-text">Impossible de charger la mémoire</div>';
  }
}

async function loadAgentsPage() {
  const list = document.getElementById('agents-page-list');
  if (!list) return;
  list.innerHTML = '<div class="loading-text">Chargement...</div>';
  try {
    const agents = await api.call('get_agents') || [];
    if (!agents.length) {
      list.innerHTML = '<div class="info-text">Aucun agent configuré</div>';
      return;
    }
    list.innerHTML = agents.map(a => `
      <div class="agent-card" onclick="app.openAgentEditor('${esc(a.id)}')">
        <span class="agent-card-icon">${a.icon || '🤖'}</span>
        <div>
          <div class="agent-card-name">${esc(a.name || a.id)}</div>
          <div class="agent-card-desc">${esc(a.description || '')}</div>
        </div>
      </div>
    `).join('');
  } catch (e) {
    list.innerHTML = `<div class="error-text">Erreur: ${esc(e.message)}</div>`;
  }
}

function openAgentEditor(agentId) {
  showToast(agentId ? 'Éditeur agent — bientôt disponible' : 'Création agent — bientôt disponible', 'info');
}

async function loadApiKeys() {
  const container = document.getElementById('api-keys-list');
  if (!container) return;
  container.innerHTML = '<div class="loading-text">Chargement...</div>';

  try {
    const providers = await api.call('get_api_keys_status') || {};
    container.innerHTML = Object.entries(providers).map(([id, p]) => `
      <div class="api-key-card ${p.has_key ? 'configured' : ''}" id="api-card-${esc(id)}">
        <div class="api-key-header">
          <span class="api-key-icon">${p.icon}</span>
          <div>
            <div class="api-key-name">${esc(p.name)}</div>
            <div class="api-key-status ${esc(p.status)}">
              ${p.has_key
                ? (p.status === 'ok' ? '✅ Configurée' : '⚠️ ' + esc(p.message || ''))
                : '○ Non configurée'}
            </div>
          </div>
          <div style="margin-left:auto;display:flex;gap:6px;align-items:center">
            ${p.has_key ? `
              <button type="button" class="api-test-btn" onclick="app.testApiKey('${esc(id)}')">Tester</button>
              <button type="button" class="api-delete-btn" onclick="app.deleteApiKey('${esc(id)}')">✕</button>
            ` : ''}
          </div>
        </div>
        <div class="api-key-input-row" id="api-input-${esc(id)}" style="${p.has_key ? 'display:none' : ''}">
          <input type="password" id="api-key-field-${esc(id)}" placeholder="${esc(p.name)} API Key"
            class="agent-input" autocomplete="off" spellcheck="false">
          <select id="api-model-${esc(id)}" class="agent-select" style="width:auto;flex-shrink:0">
            ${(p.models || []).map(m =>
              `<option value="${esc(m)}" ${m === p.default_model ? 'selected' : ''}>${esc(m)}</option>`
            ).join('')}
          </select>
          <button type="button" class="api-save-btn" onclick="app.saveApiKey('${esc(id)}')">Enregistrer</button>
        </div>
        ${!p.has_key ? `
          <a class="api-get-key-link" href="#" onclick="window.ARIA?.openExternal?.('${esc(p.url)}');return false;">
            Obtenir une clé API gratuite →
          </a>
        ` : `
          <div class="api-model-active">
            Modèle actif : ${esc(p.default_model)}
            <button type="button" onclick="app.showApiKeyInput('${esc(id)}')"
              style="margin-left:8px;font-size:10px;background:rgba(255,255,255,0.06);border:1px solid var(--border);
              border-radius:4px;padding:2px 6px;color:var(--text3);cursor:pointer">Modifier</button>
          </div>
        `}
      </div>
    `).join('');
  } catch {
    container.innerHTML = '<div class="error-text">Erreur chargement clés API</div>';
  }
}

async function saveApiKey(provider) {
  const key = document.getElementById(`api-key-field-${provider}`)?.value?.trim();
  const model = document.getElementById(`api-model-${provider}`)?.value;
  if (!key) { showToast('Clé vide', 'error'); return; }
  try {
    const result = await api.call('save_api_key', provider, key, model || '');
    if (result.success) {
      showToast('Clé enregistrée ✓', 'success');
      await loadApiKeys();
    } else {
      showToast('Erreur: ' + (result.error || '?'), 'error');
    }
  } catch (e) {
    showToast('Erreur enregistrement clé', 'error');
  }
}

async function deleteApiKey(provider) {
  if (!confirm(`Supprimer la clé ${provider} ?`)) return;
  try {
    await api.call('delete_api_key', provider);
    showToast('Clé supprimée', 'success');
    await loadApiKeys();
  } catch {
    showToast('Erreur suppression clé', 'error');
  }
}

async function testApiKey(provider) {
  const btn = document.querySelector(`#api-card-${provider} .api-test-btn`);
  if (btn) { btn.textContent = '⟳'; btn.disabled = true; }
  try {
    const result = await api.call('test_api_key', provider);
    if (result.success) showToast(`✅ ${provider} fonctionne !`, 'success');
    else showToast(`❌ ${provider}: ${result.error || result.response || '?'}`, 'error');
  } catch (e) {
    showToast(`❌ ${provider}: ${e.message}`, 'error');
  } finally {
    if (btn) { btn.textContent = 'Tester'; btn.disabled = false; }
  }
}

function showApiKeyInput(provider) {
  const row = document.getElementById(`api-input-${provider}`);
  if (row) row.style.display = 'flex';
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
  const container = document.getElementById('home-messages') || document.getElementById('messages-container');
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
  document.querySelectorAll('#mode-select-overlay button[data-mode]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      selectConversationMode(btn.getAttribute('data-mode'));
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
    navigate,
    quickAction,
    applyGreeting,
    applySettingsForm,
    validateSection,
    toggleWidget,
    toggleModeMenu,
    toggleAgentDropdown,
    setPrivacyMode,
    openAgentEditor,
    loadApiKeys,
    saveApiKey,
    deleteApiKey,
    testApiKey,
    showApiKeyInput,
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
