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
  _streamingContent: '',
  _lastOptimisticUserText: null,
  _clockInterval: null,
  _pendingTheme: null,
  _pendingWallpaper: null,
  _currentStatus: 'idle',
  _editingAgentId: null,
  _agentRules: [],
  _agentRepos: [],
  _selectedColor: '#6C8EFF',
  _activeAgentId: 'default',
  _activeAgentIcon: '🤖',
  _activeAgentName: 'ARIA',
  _generating: false,
  _currentRequestId: null,
};

/** Logo ARIA — data URL injectée par main.js (window.__ARIA_ICON__) */
function ariaIconSrc() {
  return window.__ARIA_ICON__
    || window.ARIA_ASSETS?.iconUrl
    || window.ARIA_ICON_URL
    || '';
}

function applyAriaLogo() {
  const src = ariaIconSrc();
  if (!src) {
    setTimeout(applyAriaLogo, 100);
    return;
  }
  document.querySelectorAll('[data-aria-logo]').forEach((img) => {
    img.src = src;
  });
}

function ariaAvatarHtml(size = 28) {
  const radius = size >= 64 ? 16 : 8;
  return `<img src="${ariaIconSrc()}" data-aria-logo alt="ARIA"
    style="width:${size}px;height:${size}px;border-radius:${radius}px;object-fit:cover;flex-shrink:0">`;
}

const AGENT_COLORS = [
  '#6C8EFF', '#4ADE80', '#F59E0B', '#F87171',
  '#A78BFA', '#34D399', '#FB923C', '#60A5FA',
  '#E879F9', '#2DD4BF', '#FBBF24', '#94A3B8',
];

const AGENT_EMOJIS = [
  '🤖', '🛠️', '📚', '🎯', '🚀', '💡', '🔬', '🎨',
  '🏆', '⚡', '🔥', '❄️', '🌊', '🎸', '🎧', '📷',
  '✈️', '🚁', '🏎️', '⚽', '🎮', '🎲', '♟️', '🃏',
  '👨‍💻', '👩‍💻', '🧑‍🔬', '🧑‍🎨', '👨‍✈️', '🦁', '🐉', '🦊',
  '🧙', '🌟', '🎭', '📝', '🔮', '🌍', '🧠', '🎪',
];

const SoundFX = {
  volume: 0.18,
  _ctx: null,
  _buffers: {},
  _fileMap: {
    start: 'activate.wav',
    listening: 'listening.wav',
    done: 'response.wav',
    error: 'error.wav',
  },

  _getCtx() {
    return this._ctx || (this._ctx = new (window.AudioContext || window.webkitAudioContext)());
  },

  async _loadBuffer(name) {
    if (this._buffers[name]) return this._buffers[name];
    try {
      const res = await fetch(`sounds/${name}`);
      if (!res.ok) return null;
      const buf = await this._getCtx().decodeAudioData(await res.arrayBuffer());
      this._buffers[name] = buf;
      return buf;
    } catch (_) {
      return null;
    }
  },

  async play(kind) {
    if (state.settings?.sounds_enabled === false) return;
    const file = this._fileMap[kind];
    if (file) {
      const buffer = await this._loadBuffer(file);
      if (buffer) {
        try {
          const ctx = this._getCtx();
          const src = ctx.createBufferSource();
          const gain = ctx.createGain();
          src.buffer = buffer;
          gain.gain.value = this.volume;
          src.connect(gain);
          gain.connect(ctx.destination);
          src.start();
          return;
        } catch (_) {}
      }
    }
    this._playSynth(kind);
  },

  _playSynth(kind) {
    try {
      const ctx = this._getCtx();
      const now = ctx.currentTime;
      const notes = {
        start: [{ f: 523, t: 0, d: 0.08 }, { f: 659, t: 0.07, d: 0.12 }],
        listening: [{ f: 440, t: 0, d: 0.06 }, { f: 554, t: 0.05, d: 0.08 }],
        done: [{ f: 784, t: 0, d: 0.07 }, { f: 988, t: 0.06, d: 0.14 }],
      }[kind] || [{ f: 520, t: 0, d: 0.12 }];

      notes.forEach(({ f, t, d }) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = f;
        gain.gain.setValueAtTime(0, now + t);
        gain.gain.linearRampToValueAtTime(this.volume, now + t + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.001, now + t + d);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now + t);
        osc.stop(now + t + d + 0.02);
      });
    } catch (_) {}
  },
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
  if (state.settings.privacy_mode) setPrivacyMode(state.settings.privacy_mode);
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
  await checkMicPermission();
  await loadActiveAgent();
  await loadAgentDropdown();
  await updateAgentsBadge();
  refreshNexusBadge();
  startVramPolling();
  setStatus('idle');
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
  // Boutons micro (sans onclick HTML — évite double toggle)
  const micBtn = document.getElementById('mic-btn');
  if (micBtn && !micBtn._ariaMicBound) {
    micBtn._ariaMicBound = true;
    micBtn.addEventListener('click', (e) => {
      e.preventDefault();
      toggleMic();
    });
  } else if (!micBtn) {
    console.warn('[ARIA] Bouton #mic-btn introuvable dans le DOM');
  }

  const micHdrBtn = document.getElementById('mic-visual-btn');
  if (micHdrBtn && !micHdrBtn._ariaMicBound) {
    micHdrBtn._ariaMicBound = true;
    micHdrBtn.addEventListener('click', (e) => {
      e.preventDefault();
      toggleMic();
    });
  }

  if (!document.body._ariaMicKeyBound) {
    document.body._ariaMicKeyBound = true;
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.shiftKey && (e.key === 'A' || e.key === 'a')) {
        e.preventDefault();
        toggleMic();
      }
    });
  }

  api.on('mic_state', (active) => {
    console.log('[ARIA] mic_state:', active);
    setMicState(!!active);
  });

  api.on('mic_active', (active) => {
    console.log('[ARIA] mic_active:', active);
    setMicState(!!active);
  });

  // Résultat STT (transcription vocale)
  api.on('stt_result', (text) => {
    console.log('[ARIA] STT résultat:', text);
    const input = document.getElementById('text-input');
    if (!input) return;
    state._injectingSTT = true;
    input.value = text;
    input.style.color = '';
    input.dispatchEvent(new Event('input'));
    state._injectingSTT = false;
    input.focus();
    if (state.conversationMode === 'vocal') {
      startVocalCountdown(text);
    }
    // En mode écrit, voice_mode=auto envoie déjà côté Python (llm.ask)
  });

  api.on('show_transcription', (text) => {
    const input = document.getElementById('text-input');
    if (input) {
      input.value = text;
      input.style.color = '';
      input.dispatchEvent(new Event('input'));
    }
  });

  api.on('waveform_data', (data) => {
    if (data && typeof data.rms === 'number') {
      updateWaveform(data.rms);
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
  api.on('status_change', (status) => {
    setStatus(status);
    if (status === 'idle') {
      state._generating = false;
      hideStopButton();
    }
  });

  api.on('thinking_start', (payload) => {
    const data = payload && typeof payload === 'object' ? payload : {};
    showThinkingBubble(data.model || '', data.action || 'Réflexion...');
    setStatus('thinking');
  });
  api.on('thinking_action', (action) => updateThinkingAction(action));
  api.on('response_model', (modelName) => setThinkingModel(modelName));
  api.on('thinking_hide', () => {
    hideThinkingBubble();
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
    if (state._lastOptimisticUserText === text) {
      state._lastOptimisticUserText = null;
      return;
    }
    addUserBubble(text);
  });

  // Token LLM streaming
  api.on('assistant_token', (token) => {
    if (!state._generating) return;
    appendStreamToken(token);
    setStatus('speaking');
  });

  // Fin du message ARIA
  api.on('assistant_done', (modelName) => {
    console.log('[ARIA] assistant_done reçu');
    state._generating = false;
    hideStopButton();
    hideThinkingBubble();
    finalizeAssistantMessage(modelName || state._pendingModel || '');
    setStatus('idle');
    const input = document.getElementById('text-input');
    if (input) {
      input.disabled = false;
      input.focus();
    }
    SoundFX.play('done');
  });

  api.on('tts_finished', () => {
    if (state.micActive) setStatus('listening');
    else setStatus('idle');
  });

  api.on('gdoc_link', ({ title, url }) => showGdocLinkCard(title, url));
  api.on('active_gdoc', (doc) => {
    updateActiveDocWidget(doc);
    loadDaySummary();
  });
  api.on('active_doc_changed', (doc) => updateActiveDocWidget(doc));

  api.on('search_results', (html) => showSearchResultsCard(html));

  api.on('focus_indicator', (active) => updateFocusIndicator(active));

  api.on('error', (text) => {
    showToast(text || 'Erreur', 'error');
    setStatus('idle');
  });

  api.on('profile_changed', (prof) => applyProfileChanged(prof));
  api.on('nexus_mode_changed', (data) => {
    refreshNexusBadge();
    if (data?.enabled) showToast('⚡ Mode Nexus activé', 'info');
  });
  api.on('model_install_start', (data) => {
    const logEl = document.getElementById('model-install-log');
    if (logEl) {
      logEl.classList.remove('hidden');
      logEl.textContent += `\n▶ ${data?.name || data?.model_id}…\n`;
    }
  });
  api.on('model_install_progress', (data) => {
    const logEl = document.getElementById('model-install-log');
    if (logEl && data?.line) {
      logEl.textContent += data.line + '\n';
      logEl.scrollTop = logEl.scrollHeight;
    }
  });
  api.on('model_install_done', (data) => {
    const logEl = document.getElementById('model-install-log');
    if (logEl) logEl.textContent += data?.success ? '\n✅ Terminé\n' : `\n❌ ${data?.error || 'Échec'}\n`;
    loadModelCatalog();
    loadModelSettings();
    showToast(data?.success ? 'Modèle installé' : (data?.error || 'Installation échouée'), data?.success ? 'success' : 'error');
  });
  api.on('request_app_quit', () => {
    setTimeout(() => window.ARIA?.quit?.(), 500);
  });

  document.getElementById('messages')?.addEventListener('click', (e) => {
    const link = e.target.closest('a.md-link');
    if (link?.dataset?.url) {
      e.preventDefault();
      window.ARIA?.openExternal?.(link.dataset.url);
    }
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

  const list = document.getElementById('conv-list-full');
  if (!list) return;

  if (!conversations || conversations.length === 0) {
    list.innerHTML = `
      <div style="text-align:center;padding:40px 20px;color:rgba(255,255,255,0.3);font-size:13px">
        Aucune conversation.
      </div>`;
    const listLegacy = document.getElementById('conversations-list');
    if (listLegacy) listLegacy.innerHTML = '<div class="empty-conv-list">Aucune conversation</div>';
    return;
  }

  list.innerHTML = conversations.map(conv => {
    const isActive = conv.id === state.currentConvId;
    const title = esc(conv.title || 'Nouvelle conversation');
    const titleJs = JSON.stringify(conv.title || 'Nouvelle conversation');
    const date = conv.updated_at
      ? new Date(conv.updated_at).toLocaleDateString('fr-FR')
      : '';
    return `
      <div class="conv-item ${isActive ? 'active' : ''}"
           id="conv-item-${conv.id}"
           onmouseenter="this.querySelector('.conv-del')?.style && (this.querySelector('.conv-del').style.opacity='1')"
           onmouseleave="this.querySelector('.conv-del')?.style && (this.querySelector('.conv-del').style.opacity='0')">
        <div class="conv-content" onclick="app.loadConversation('${conv.id}')">
          <div class="conv-title">${title}</div>
          <div class="conv-date">${date}</div>
        </div>
        <button class="conv-del conv-delete"
          onclick="event.stopPropagation();app.deleteConversation('${conv.id}',${titleJs})"
          style="opacity:0;flex-shrink:0;background:rgba(239,68,68,0.12);
                 border:none;border-radius:6px;width:26px;height:26px;
                 color:#F87171;cursor:pointer;font-size:11px;
                 transition:opacity 0.15s,background 0.15s">✕</button>
      </div>`;
  }).join('');

  const listLegacy = document.getElementById('conversations-list');
  if (listLegacy) listLegacy.innerHTML = list.innerHTML;
}

function loadFullConversationList() {
  refreshConversationList();
}

async function newConversation() {
  try {
    const result = await api.call('new_conversation');
    state.currentConvId = result.id;
    await saveSetting('last_conversation_id', result.id);
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
    await saveSetting('last_conversation_id', result.id);

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
      document.getElementById(`conv-item-${convId}`)?.remove();
      showToast('Conversation supprimée', 'success');

      if (convId === state.currentConvId) {
        state.currentConvId = null;
        const messages = document.getElementById('messages');
        if (messages) messages.innerHTML = '';
        showHomeIdle();
      }

      await refreshConversationList();

      const remaining = document.querySelectorAll('#conv-list-full .conv-item');
      if (remaining.length === 0) {
        const list = document.getElementById('conv-list-full');
        if (list) {
          list.innerHTML = `
            <div style="text-align:center;padding:40px 20px;color:rgba(255,255,255,0.3);font-size:13px">
              Aucune conversation.
            </div>`;
        }
      }
    } else {
      showToast('Erreur lors de la suppression', 'error');
    }
  } catch (e) {
    showToast('Erreur: ' + e.message, 'error');
  }
}

async function deleteAllConversations() {
  const items = document.querySelectorAll('#conv-list-full .conv-item');
  const count = items.length;

  if (count === 0) {
    showToast('Aucune conversation à supprimer', 'info');
    return;
  }

  if (!confirm(`Supprimer les ${count} conversation(s) ?\nCette action est irréversible.`)) return;

  try {
    const result = await api.call('delete_all_conversations');

    if (result.success) {
      showToast(`${result.count} conversation(s) supprimée(s)`, 'success');

      const list = document.getElementById('conv-list-full');
      if (list) {
        list.innerHTML = `
          <div style="text-align:center;padding:40px 20px;color:rgba(255,255,255,0.3);font-size:13px">
            Aucune conversation.<br>
            <button onclick="app.newConversation()" style="margin-top:12px;padding:8px 16px;
              background:rgba(108,142,255,0.12);border:1px solid rgba(108,142,255,0.25);
              border-radius:8px;color:#6C8EFF;font-family:inherit;font-size:12px;cursor:pointer">
              + Nouvelle conversation
            </button>
          </div>`;
      }

      const badge = document.getElementById('conv-badge');
      if (badge) badge.textContent = '';

      state.currentConvId = null;
      const messages = document.getElementById('messages');
      if (messages) messages.innerHTML = '';
      showHomeIdle();
    } else {
      showToast('Erreur suppression', 'error');
    }
  } catch (e) {
    showToast('Erreur: ' + e.message, 'error');
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

function addAriaBubble(text, scroll = true, modelName = '') {
  const messages = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'bubble-wrap-outer';
  div.innerHTML = `
    ${modelName ? `<div class="model-badge">via ${esc(modelName)}</div>` : ''}
    <div class="bubble-wrap aria-wrap">
      <div class="bubble-avatar">
        ${ariaAvatarHtml(28)}
      </div>
      <div class="bubble bubble-aria">
        <div class="bubble-text">${renderMarkdown(text)}</div>
      </div>
    </div>`;
  messages.appendChild(div);
  if (scroll) scrollToBottom();
}

function appendStreamToken(token) {
  if (!token) return;
  hideThinkingBubble();
  if (!state._streamingMessage) {
    const messages = document.getElementById('messages');
    if (!messages) return;
    const outer = document.createElement('div');
    outer.className = 'bubble-wrap-outer aria-wrap';
    const div = document.createElement('div');
    div.className = 'bubble-wrap aria-wrap';
    div.innerHTML = `
      <div class="bubble-avatar">
        ${ariaAvatarHtml(28)}
      </div>
      <div class="bubble bubble-aria">
        <div class="bubble-text streaming-text"></div>
      </div>`;
    outer.appendChild(div);
    messages.appendChild(outer);
    state._streamingOuter = outer;
    state._streamingMessage = div.querySelector('.streaming-text');
    state._streamingContent = '';
  }

  state._streamingContent += token;
  state._streamingMessage.innerHTML =
    renderMarkdown(state._streamingContent) +
    '<span class="cursor-blink" style="display:inline-block;width:2px;height:14px;background:var(--accent);margin-left:2px;animation:blink 1s step-end infinite;vertical-align:middle">▋</span>';
  scrollToBottom();
}

function finalizeAssistantMessage(modelName = '') {
  const label = modelName || state._pendingModel || '';
  if (state._streamingMessage) {
    const cursor = state._streamingMessage.querySelector('.cursor-blink');
    if (cursor) cursor.remove();
    if (state._streamingContent) {
      state._streamingMessage.innerHTML = renderMarkdown(state._streamingContent);
    }
    if (label && state._streamingOuter) {
      const badge = document.createElement('div');
      badge.className = 'model-badge';
      badge.textContent = `via ${label}`;
      state._streamingOuter.insertBefore(badge, state._streamingOuter.firstChild);
    }
    state._streamingMessage = null;
    state._streamingOuter = null;
  }
  state._streamingContent = '';
  state._pendingModel = '';
}

function showThinkingBubble(modelName = '', action = '') {
  hideThinkingBubble();
  showHomeConversation();
  const messages = document.getElementById('messages');
  if (!messages) return;

  state._pendingModel = modelName || '';
  state._thinkingLog = action ? [action] : [];

  const div = document.createElement('div');
  div.id = 'thinking-bubble';
  div.className = 'bubble-wrap aria-wrap thinking-wrap';
  div.innerHTML = `
    <div class="bubble-avatar">
      ${ariaAvatarHtml(28)}
    </div>
    <div class="thinking-content">
      ${modelName ? `<div class="model-label">${esc(modelName)}</div>` : ''}
      <div class="action-log" id="thinking-action">${esc(action || 'Réflexion...')}</div>
      <ul class="thinking-log" id="thinking-log"></ul>
      <div class="thinking-dots"><span></span><span></span><span></span></div>
    </div>`;
  messages.appendChild(div);
  renderThinkingLog();
  scrollToBottom();
}

function setThinkingModel(modelName = '') {
  if (!modelName) return;
  state._pendingModel = modelName;
  const bubble = document.getElementById('thinking-bubble');
  if (!bubble) return;
  let label = bubble.querySelector('.model-label');
  if (!label) {
    label = document.createElement('div');
    label.className = 'model-label';
    bubble.querySelector('.thinking-content')?.prepend(label);
  }
  label.textContent = modelName;
}

function updateThinkingAction(action) {
  if (!action) return;
  const el = document.getElementById('thinking-action');
  if (el) {
    el.textContent = action;
    el.classList.add('action-flash');
    setTimeout(() => el.classList.remove('action-flash'), 400);
  }
  if (!state._thinkingLog) state._thinkingLog = [];
  const last = state._thinkingLog[state._thinkingLog.length - 1];
  if (action !== last) {
    state._thinkingLog.push(action);
    renderThinkingLog();
  }
  const subtitle = document.getElementById('sidebar-subtitle');
  if (subtitle) {
    const model = state._pendingModel;
    subtitle.textContent = model ? `${action} · ${model}` : action;
  }
  setStatus('thinking');
  scrollToBottom();
}

function renderThinkingLog() {
  const log = document.getElementById('thinking-log');
  if (!log || !state._thinkingLog?.length) return;
  log.innerHTML = state._thinkingLog.map((item, i) => {
    const isLast = i === state._thinkingLog.length - 1;
    return `<li class="thinking-log-item${isLast ? ' active' : ''}">${esc(item)}</li>`;
  }).join('');
}

function hideThinkingBubble() {
  document.getElementById('thinking-bubble')?.remove();
  state._thinkingLog = [];
}

function showSearchResultsCard(sourcesHtml) {
  showHomeConversation();
  const messages = document.getElementById('messages');
  if (!messages || !sourcesHtml) return;
  const wrap = document.createElement('div');
  wrap.className = 'search-results-card';
  wrap.innerHTML = sourcesHtml;
  messages.appendChild(wrap);
  scrollToBottom();
}

function showGdocLinkCard(title, url) {
  showHomeConversation();
  const messages = document.getElementById('messages');
  if (!messages) return;
  const card = document.createElement('a');
  card.className = 'gdoc-link-card';
  card.href = url || '#';
  card.target = '_blank';
  card.rel = 'noopener noreferrer';
  card.onclick = (e) => {
    if (url && window.ARIA?.openExternal) {
      e.preventDefault();
      window.ARIA.openExternal(url);
    }
  };
  card.innerHTML = `
    <span class="gdoc-link-icon">📄</span>
    <div>
      <div class="gdoc-link-text">${esc(title || 'Google Doc')}</div>
      <div class="gdoc-link-sub">${esc(url || '')}</div>
    </div>`;
  messages.appendChild(card);
  scrollToBottom();
}

function updateFocusIndicator(active) {
  const el = document.getElementById('focus-indicator');
  if (!el) return;
  if (active) {
    el.style.display = 'block';
    el.style.transform = 'translateX(0)';
  } else {
    el.style.transform = 'translateX(120%)';
    setTimeout(() => {
      el.style.display = 'none';
      el.style.transform = '';
    }, 500);
  }
}

function fileIcon(name) {
  const ext = name.split('.').pop().toLowerCase();
  const icons = {
    pdf: '📄', py: '🐍', js: '⚡', html: '🌐', css: '🎨',
    json: '📋', md: '📝', csv: '📊', txt: '📃', yaml: '⚙️',
  };
  return icons[ext] || '📁';
}

function showFileBubble(file, type) {
  showHomeConversation();
  const messages = document.getElementById('messages');
  if (!messages) return;
  const wrap = document.createElement('div');
  wrap.className = 'bubble-wrap user-wrap';
  if (type === 'image') {
    const url = URL.createObjectURL(file);
    wrap.innerHTML = `
      <div class="bubble bubble-user">
        <img src="${url}" style="max-width:100%;max-height:300px;border-radius:8px;display:block;margin-bottom:8px" alt="">
        <div class="bubble-text" style="font-size:12px;color:var(--text3)">${esc(file.name)}</div>
      </div>`;
  } else if (type === 'video') {
    const url = URL.createObjectURL(file);
    wrap.innerHTML = `
      <div class="bubble bubble-user">
        <video src="${url}" controls style="max-width:100%;max-height:200px;border-radius:8px;display:block;margin-bottom:8px"></video>
        <div class="bubble-text" style="font-size:12px;color:var(--text3)">${esc(file.name)}</div>
      </div>`;
  } else {
    wrap.innerHTML = `
      <div class="bubble bubble-user">
        <div style="display:flex;align-items:center;gap:10px;padding:4px 0">
          <span style="font-size:24px">${fileIcon(file.name)}</span>
          <div>
            <div style="font-size:13px;font-weight:500">${esc(file.name)}</div>
            <div style="font-size:11px;color:var(--text3)">${(file.size / 1024).toFixed(1)} KB</div>
          </div>
        </div>
      </div>`;
  }
  messages.appendChild(wrap);
  scrollToBottom();
}

function askFilePrompt() {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:5000;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px)';
    overlay.innerHTML = `
      <div style="background:var(--surface);border:1px solid var(--border2);border-radius:12px;padding:24px;width:480px;max-width:90vw">
        <div style="font-size:14px;font-weight:500;margin-bottom:6px;color:var(--text)">Que voulez-vous savoir ?</div>
        <div style="font-size:12px;color:var(--text3);margin-bottom:16px">Entrez votre question pour ces fichiers</div>
        <textarea id="file-prompt-input" placeholder="Ex: Corrige ce devoir, Explique ce graphique..."
          style="width:100%;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px;color:var(--text);font-family:inherit;font-size:14px;resize:none;height:80px;outline:none"></textarea>
        <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:12px">
          <button id="file-prompt-cancel" type="button" style="background:transparent;border:1px solid var(--border);color:var(--text2);padding:8px 16px;border-radius:8px;cursor:pointer;font-family:inherit">Annuler</button>
          <button id="file-prompt-send" type="button" style="background:var(--accent);border:none;color:white;padding:8px 20px;border-radius:8px;cursor:pointer;font-family:inherit;font-weight:500">Envoyer ➤</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    const input = overlay.querySelector('#file-prompt-input');
    const confirm = () => {
      const val = input.value.trim();
      if (!val) { input.style.borderColor = 'var(--error, #F87171)'; return; }
      overlay.remove();
      resolve(val);
    };
    const cancel = () => { overlay.remove(); resolve(null); };

    overlay.querySelector('#file-prompt-send').onclick = confirm;
    overlay.querySelector('#file-prompt-cancel').onclick = cancel;
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); confirm(); }
      if (e.key === 'Escape') cancel();
    });
    setTimeout(() => input.focus(), 100);
  });
}

async function handleFiles(files) {
  const fileArray = Array.from(files || []);
  if (!fileArray.length) return;

  const inputEl = document.getElementById('text-input');
  let userPrompt = inputEl?.value.trim() || '';
  const hasImages = fileArray.some(f => f.type.startsWith('image/'));

  if (!userPrompt && !hasImages) {
    userPrompt = await askFilePrompt();
    if (!userPrompt) {
      const fi = document.getElementById('file-input');
      if (fi) fi.value = '';
      return;
    }
  } else if (!userPrompt && hasImages) {
    userPrompt = 'Analyse ces images et dis-moi ce que tu observes';
  }

  fileArray.forEach(file => {
    const type = file.type.startsWith('image/') ? 'image'
      : file.type.startsWith('video/') ? 'video' : 'file';
    showFileBubble(file, type);
  });

  addUserBubble(userPrompt);
  if (inputEl) {
    inputEl.value = '';
    adjustTextarea(inputEl);
  }

  const filesData = await Promise.all(fileArray.map(async file => {
    const dataUrl = await fileToBase64(file);
    const b64 = dataUrl.includes(',') ? dataUrl.split(',')[1] : dataUrl;
    return { b64, name: file.name, type: file.type };
  }));

  try {
    await api.call('send_files_with_prompt', JSON.stringify(filesData), userPrompt);
  } catch (e) {
    showToast('Erreur envoi fichiers', 'error');
  }

  const fi = document.getElementById('file-input');
  if (fi) fi.value = '';
}

// ── Envoi de messages ─────────────────────────────────────────────────────────

function showStopButton() {
  let btn = document.getElementById('stop-btn');
  if (!btn) {
    btn = document.createElement('button');
    btn.id = 'stop-btn';
    btn.type = 'button';
    btn.innerHTML = '⏹ Arrêter';
    btn.onclick = () => stopGeneration();
    document.body.appendChild(btn);
  } else if (btn.parentElement !== document.body) {
    document.body.appendChild(btn);
  }
  btn.style.display = 'flex';
  btn.style.animation = 'fadeInUp 0.2s ease';
}

function hideStopButton() {
  const btn = document.getElementById('stop-btn');
  if (btn) btn.style.display = 'none';
}

async function stopGeneration() {
  console.log('[ARIA] stopGeneration() appelé, generating=', state._generating);
  if (!state._generating) return;

  state._generating = false;

  try {
    await api.call('stop_generation');
    console.log('[ARIA] stop_generation envoyé au backend');
  } catch (e) {
    console.error('[ARIA] Erreur stop_generation:', e);
  }

  hideStopButton();
  hideThinkingBubble();
  finalizeAssistantMessage();
  setStatus('idle');

  const input = document.getElementById('text-input');
  if (input) {
    input.disabled = false;
    input.focus();
  }

  showToast('Génération arrêtée', 'info');
}

async function sendMessage() {
  const input = document.getElementById('text-input');
  const text = input?.value?.trim();
  if (!text) return;
  if (state._generating) {
    showToast('Génération en cours...', 'info');
    return;
  }

  input.value = '';
  input.style.height = 'auto';
  input.dispatchEvent(new Event('input'));

  cancelVocalCountdown();
  showHomeConversation();

  state._lastOptimisticUserText = text;
  addUserBubble(text);

  state._generating = true;
  state._streamingContent = '';
  state._streamingMessage = null;
  state._streamingOuter = null;
  setStatus('thinking');
  input.disabled = true;
  showStopButton();

  console.log('[ARIA] Envoi message, generating=true');

  try {
    await api.call('ask', text, state.conversationMode || 'ecrit');
  } catch (e) {
    if (!e.message?.includes('stopped') && !e.message?.includes('abort')) {
      console.error('[ARIA] Erreur ask:', e);
      showToast('Erreur: ' + e.message, 'error');
    }
    finalizeAssistantMessage();
  } finally {
    state._generating = false;
    hideStopButton();
    setStatus('idle');
    input.disabled = false;
    input.focus();
    console.log('[ARIA] Message terminé, generating=false');
  }
}

function handleInputKeydown(e) {
  if (e.key === 'Escape' && state._generating) {
    e.preventDefault();
    stopGeneration();
    return;
  }
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    const input = document.getElementById('text-input');
    if (state._generating) {
      showToast('Appuie sur Échap pour arrêter', 'info');
      return;
    }
    if (input && !input.disabled) {
      sendMessage();
    }
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

let _micToggling = false;

async function toggleMic() {
  if (_micToggling) return;
  _micToggling = true;
  console.log('[ARIA] toggleMic() appelé, actif=', state.micActive);
  try {
    const result = await api.call('toggle_mic');
    console.log('[ARIA] toggle_mic résultat:', result);
    if (result && result.success === false && result.error) {
      showToast('Erreur micro: ' + result.error, 'error');
    }
  } catch (e) {
    console.error('[ARIA] Erreur toggleMic:', e);
    showToast('Erreur microphone', 'error');
  } finally {
    _micToggling = false;
  }
}

function setMicState(active) {
  const isActive = !!active;
  state.micActive = isActive;
  state.micPaused = !isActive;

  const micBtn = document.getElementById('mic-btn');
  const micHdrBtn = document.getElementById('mic-visual-btn');

  if (micBtn) {
    micBtn.classList.remove('mic-idle', 'mic-listening', 'mic-speaking-detected');
    micBtn.classList.add(isActive ? 'mic-listening' : 'mic-idle');
    micBtn.title = isActive ? 'Arrêter le micro (Ctrl+Shift+A)' : 'Parler (Ctrl+Shift+A)';
    if (!isActive) {
      micBtn.style.transform = '';
    }
  }

  if (micHdrBtn) {
    micHdrBtn.classList.toggle('active', isActive);
  }

  if (isActive) {
    setStatus('listening');
    showToast('🎤 Micro actif — parle maintenant', 'info');
  } else if (state._currentStatus === 'listening' || state._currentStatus === 'transcribing') {
    setStatus('idle');
    showToast('🔇 Micro arrêté', 'info');
  }
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
    } else {
      btn.classList.remove('mic-speaking-detected');
    }
  }

  const scale = isSpeaking ? 1 + Math.min(smooth * 3, 0.25) : 1;
  btn.style.transform = `scale(${scale.toFixed(3)})`;

  if (state._currentStatus === 'speaking') {
    const core = document.querySelector('#home-orbe .orbe-core');
    if (core) {
      const orbeScale = 1 + Math.min(smooth * 4, 0.35);
      core.style.transform = `scale(${orbeScale.toFixed(3)})`;
    }
  }

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
  const prev = state._currentStatus;
  state._currentStatus = s;
  if (s === 'listening' && prev !== 'listening' && prev !== 'transcribing') {
    SoundFX.play('listening');
  }
  const subtitle = document.getElementById('sidebar-subtitle');
  const homeOrbe = document.getElementById('home-orbe');
  const sidebarWrap = document.getElementById('sidebar-orbe-wrap')
    || document.getElementById('sidebar-logo-wrap');

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
    idle: 'orbe-idle',
    listening: 'orbe-listening',
    transcribing: 'orbe-listening',
    thinking: 'orbe-thinking',
    speaking: 'orbe-speaking',
  };
  const cls = map[s] || 'orbe-idle';
  const orbeClasses = ['orbe-idle', 'orbe-listening', 'orbe-thinking', 'orbe-speaking'];

  [homeOrbe, sidebarWrap].forEach(el => {
    if (!el) return;
    el.classList.remove(...orbeClasses);
    el.classList.add(cls);
  });

  if (s !== 'speaking') {
    document.querySelector('#home-orbe .orbe-core')?.style.removeProperty('transform');
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
  if (!state.settings) state.settings = {};
  state.settings[key] = value;
  try {
    await api.call('save_settings', state.settings);
    if (['user_firstname', 'hello_text', 'sub_text'].includes(key)) updateClock();
  } catch (e) {
    console.error('Erreur saveSetting:', key, e);
    showToast('Erreur sauvegarde paramètre', 'error');
  }
}

function toggleSettings() {
  navigate(state.currentPage === 'settings' ? 'home' : 'settings');
}

function toggleAccordion(id) {
  const body = document.querySelector(`#acc-${id} .acc-body`);
  const chevron = document.querySelector(`#acc-${id} .acc-chevron`);
  if (!body) {
    console.error(`Accordéon #acc-${id} .acc-body introuvable`);
    return;
  }
  const isHidden = body.classList.contains('hidden');
  body.classList.toggle('hidden', !isHidden);
  if (chevron) chevron.textContent = isHidden ? '▾' : '▸';

  const accordion = document.getElementById(`acc-${id}`);
  if (accordion) accordion.classList.toggle('open', isHidden);

  if (isHidden) {
    if (id === 'modeles') { loadModelSettings(); loadModelCatalog(); }
    if (id === 'profils') loadProfilesSettings();
    if (id === 'systeme') { refreshVramWidget(); refreshUpdatePanel(); refreshNexusBadge(); }
    if (id === 'apikeys') loadApiKeys();
  }
}

function switchModelTab(tab) {
  document.querySelectorAll('.model-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
  document.getElementById('model-tab-active')?.classList.toggle('hidden', tab !== 'active');
  document.getElementById('model-tab-catalog')?.classList.toggle('hidden', tab !== 'catalog');
  if (tab === 'catalog') loadModelCatalog();
  else loadModelSettings();
}

async function loadModelSettings() {
  const container = document.getElementById('model-settings');
  if (!container) return;
  container.innerHTML = '<div class="loading-text">Chargement...</div>';

  try {
    const [catalog, modelsData] = await Promise.all([
      api.call('get_model_catalog'),
      api.call('get_available_models').catch(() => null),
    ]);
    const configured = modelsData?.configured || {};
    const installed = (catalog || []).filter(m => m.installed);
    if (!installed.length) {
      container.innerHTML = '<div class="info-text">Aucun modèle installé.<br>Ouvrez l\'onglet Catalogue pour en installer.</div>';
      return;
    }

    const roles = [
      { key: 'intent', label: '⚡ Classification (intent)' },
      { key: 'fast', label: '💬 Réponses rapides (fast)' },
      { key: 'heavy', label: '🧠 Analyse approfondie (heavy)' },
      { key: 'vision', label: '👁️ Vision' },
    ];

    container.innerHTML = roles.map(r => `
      <div class="model-row">
        <label>${r.label}</label>
        <select onchange="app.setModelForRole('${r.key}', this.value)">
          ${installed.map(m => `
            <option value="${m.id}" ${m.id === configured[r.key] || m.ollama_name === configured[r.key] ? 'selected' : ''}>${m.icon || ''} ${m.name}</option>
          `).join('')}
        </select>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = `<div class="error-text">Erreur: ${e.message}</div>`;
  }
}

async function loadModelCatalog() {
  const container = document.getElementById('model-catalog');
  if (!container) return;
  container.innerHTML = '<div class="loading-text">Chargement...</div>';
  try {
    const catalog = await api.call('get_model_catalog') || [];
    if (!catalog.length) {
      container.innerHTML = '<div class="info-text">Catalogue vide</div>';
      return;
    }
    container.innerHTML = catalog.map(m => `
      <div class="model-card" data-id="${m.id}">
        <div class="model-card-head">
          <span class="model-card-icon">${m.icon || '🤖'}</span>
          <div>
            <div class="model-card-name">${m.name}</div>
            <div class="model-card-desc">${m.description || ''}</div>
          </div>
        </div>
        <div class="model-card-meta">
          <span>${m.size_gb || '?'} Go</span>
          <span>${m.use_case || ''}</span>
          ${m.installed ? '<span class="badge-installed">Installé</span>' : ''}
          ${m.is_active ? '<span class="badge-active">Actif</span>' : ''}
        </div>
        <button type="button" class="settings-btn-outline model-card-btn"
          onclick="app.${m.installed ? 'uninstallModel' : 'installModel'}('${m.id}')">
          ${m.installed ? 'Retirer' : `Installer (${m.size_gb || '?'} Go)`}
        </button>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = `<div class="error-text">Erreur: ${e.message}</div>`;
  }
}

async function installModel(modelId) {
  const logEl = document.getElementById('model-install-log');
  if (logEl) {
    logEl.classList.remove('hidden');
    logEl.textContent = `Installation de ${modelId}…\n`;
  }
  try {
    const result = await api.call('install_model', modelId);
    if (!result?.success) showToast(result?.error || 'Erreur installation', 'error');
    else showToast('Installation démarrée', 'info');
  } catch (e) {
    showToast('Erreur: ' + e.message, 'error');
  }
}

async function uninstallModel(modelId) {
  if (!confirm(`Retirer le modèle ${modelId} ?`)) return;
  try {
    const result = await api.call('uninstall_model', modelId);
    if (result?.success) {
      showToast('Modèle retiré', 'success');
      loadModelCatalog();
      loadModelSettings();
    } else showToast(result?.error || 'Erreur', 'error');
  } catch (e) {
    showToast('Erreur: ' + e.message, 'error');
  }
}

async function setModelForRole(role, modelId) {
  try {
    const result = await api.call('set_model_for_role', role, modelId);
    if (!result?.success) showToast(result?.error || 'Erreur', 'error');
    else {
      showToast(`Modèle ${role} mis à jour`, 'success');
      loadModelCatalog();
    }
  } catch (e) {
    showToast('Erreur set_model_for_role', 'error');
  }
}

async function loadProfilesSettings() {
  const container = document.getElementById('profiles-list');
  if (!container) return;
  container.innerHTML = '<div class="loading-text">Chargement...</div>';
  try {
    const data = await api.call('get_profiles');
    const current = data?.current_user;
    const profiles = data?.profiles || {};
    const keys = Object.keys(profiles);
    if (!keys.length) {
      container.innerHTML = '<div class="info-text">Aucun profil</div>';
      return;
    }
    container.innerHTML = keys.map(key => {
      const p = profiles[key];
      const active = key === current;
      return `
        <div class="profile-row ${active ? 'active' : ''}">
          <div>
            <strong>${p.name || key}</strong>
            ${active ? '<span class="badge-active">Actif</span>' : ''}
          </div>
          <div style="display:flex;gap:6px">
            ${active ? '' : `<button type="button" class="settings-btn-outline" onclick="app.activateProfile('${key}')">Activer</button>`}
            ${active || keys.length <= 1 ? '' : `<button type="button" class="settings-btn-outline" onclick="app.deleteProfile('${key}')">Supprimer</button>`}
          </div>
        </div>`;
    }).join('');
  } catch (e) {
    container.innerHTML = `<div class="error-text">Erreur: ${e.message}</div>`;
  }
}

async function activateProfile(key) {
  try {
    const result = await api.call('switch_profile', key);
    if (!result?.success) showToast(result?.error || 'Erreur', 'error');
  } catch (e) {
    showToast('Erreur profil', 'error');
  }
}

async function createProfile() {
  const input = document.getElementById('new-profile-name');
  const name = input?.value?.trim();
  if (!name) return showToast('Entrez un nom', 'error');
  try {
    const result = await api.call('create_profile', name);
    if (result?.success) {
      if (input) input.value = '';
      showToast('Profil créé', 'success');
      loadProfilesSettings();
    } else showToast(result?.error || 'Erreur', 'error');
  } catch (e) {
    showToast('Erreur: ' + e.message, 'error');
  }
}

async function deleteProfile(key) {
  if (!confirm(`Supprimer le profil ${key} ?`)) return;
  try {
    const result = await api.call('delete_profile', key);
    if (result?.success) {
      showToast('Profil supprimé', 'success');
      loadProfilesSettings();
    } else showToast(result?.error || 'Erreur', 'error');
  } catch (e) {
    showToast('Erreur', 'error');
  }
}

function applyProfileChanged(prof) {
  if (!prof) return;
  const hello = document.getElementById('home-hello-text');
  const sub = document.getElementById('home-sub-text');
  const firstname = prof.firstname || prof.name || '';
  if (hello) hello.textContent = prof.hello_text || (firstname ? `Bonjour ${firstname}.` : 'Bonjour.');
  if (sub) sub.textContent = prof.sub_text || 'Comment puis-je vous aider aujourd\'hui ?';
  if (prof.theme) applyTheme(prof.theme);
  if (prof.wallpaper) applyWallpaperImmediate(prof.wallpaper);
  showToast(`Profil ${firstname || prof._key || ''} chargé`, 'success');
  loadProfilesSettings();
  loadModelSettings();
}

async function toggleNexusMode(enabled) {
  try {
    await api.call('set_nexus_mode', !!enabled);
    refreshNexusBadge();
  } catch (e) {
    showToast('Erreur Nexus: ' + e.message, 'error');
  }
}

function refreshNexusBadge() {
  api.call('get_nexus_mode').then(data => {
    const badge = document.getElementById('nexus-badge');
    const chk = document.getElementById('set-nexus-mode');
    const on = !!data?.enabled;
    badge?.classList.toggle('hidden', !on);
    if (chk) chk.checked = on;
  }).catch(() => {});
}

async function refreshVramWidget() {
  try {
    const v = await api.call('get_vram_usage');
    const text = document.getElementById('vram-text');
    const fill = document.getElementById('vram-bar-fill');
    if (!text || !fill) return;
    const used = v?.used_mb || 0;
    const total = v?.total_mb || 0;
    text.textContent = total ? `${used} Mo utilisés / ${total} Mo` : 'VRAM — nvidia-smi indisponible';
    const pct = v?.used_pct || 0;
    fill.style.width = `${Math.min(100, pct)}%`;
    fill.className = 'vram-bar-fill' + (pct > 80 ? ' vram-high' : pct > 50 ? ' vram-mid' : ' vram-low');
  } catch (_) {}
}

async function refreshUpdatePanel() {
  try {
    const ver = await api.call('get_app_version');
    const label = document.getElementById('app-version-label');
    if (label) label.textContent = ver ? `v${ver}` : '';
  } catch (_) {}
}

async function checkForUpdates() {
  const statusEl = document.getElementById('update-status');
  const btn = document.getElementById('btn-apply-update');
  if (statusEl) statusEl.textContent = 'Vérification…';
  try {
    const data = await api.call('check_for_updates');
    if (data?.error) {
      if (statusEl) statusEl.textContent = '⚠️ ' + data.error;
      btn?.classList.add('hidden');
      return;
    }
    if (data?.available) {
      if (statusEl) statusEl.textContent = `🔄 ${data.commits_behind} commit(s) disponible(s)\n${data.latest_message || ''}`;
      btn?.classList.remove('hidden');
    } else {
      if (statusEl) statusEl.textContent = '✅ À jour';
      btn?.classList.add('hidden');
    }
  } catch (e) {
    if (statusEl) statusEl.textContent = 'Erreur: ' + e.message;
  }
}

async function applyUpdate() {
  if (!confirm('ARIA va se fermer pour appliquer la mise à jour. Continuer ?')) return;
  try {
    const result = await api.call('apply_update');
    if (result?.success) showToast('Mise à jour lancée — fermeture dans 3s…', 'info');
    else showToast(result?.error || 'Erreur', 'error');
  } catch (e) {
    showToast('Erreur: ' + e.message, 'error');
  }
}

let _vramInterval = null;
function startVramPolling() {
  if (_vramInterval) return;
  refreshVramWidget();
  _vramInterval = setInterval(refreshVramWidget, 10000);
}

async function setModel(role, modelName) {
  AnimationController.play(SettingsAnimations.animModelChange, { role, modelName });
  try {
    const result = await api.call('set_model', role, modelName);
    if (!result.success) showToast('Erreur: ' + result.error, 'error');
  } catch (e) {
    showToast('Erreur set_model', 'error');
  }
}

// ── Thèmes et wallpapers ──────────────────────────────────────────────────────

function setTheme(theme) {
  state._pendingTheme = theme;
  document.documentElement.setAttribute('data-theme', theme);
  document.querySelectorAll('.theme-pill').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.theme === theme);
  });
}

function applyTheme(theme) {
  state._pendingTheme = theme;
  document.documentElement.setAttribute('data-theme', theme);
  document.querySelectorAll('.theme-pill').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.theme === theme);
  });
}

function applyWallpaperImmediate(type, url = null) {
  const layer = document.getElementById('wallpaper-image');
  if (!layer) return;

  layer.className = '';
  layer.style.backgroundImage = '';
  layer.style.background = '';

  if (type === 'custom' && url) {
    layer.style.backgroundImage = `url("${url}")`;
    layer.style.backgroundSize = 'cover';
    layer.style.backgroundPosition = 'center';
  } else if (type) {
    layer.classList.add(`wp-${type}`);
  }

  document.querySelectorAll('.wp-thumb').forEach(t => t.classList.remove('active'));
  if (type !== 'custom') {
    document.querySelector(`.wp-thumb.wp-${type}`)?.classList.add('active');
  }
}

window.__applyWallpaperImmediate = applyWallpaperImmediate;

function setWallpaper(type, url = null, opts = {}) {
  const { skipAnim = true, skipSave = true } = opts;
  state._pendingWallpaper = { type, url };
  applyWallpaperImmediate(type, url);

  if (!skipAnim && typeof SettingsAnimations !== 'undefined') {
    AnimationController.play(SettingsAnimations.animWallpaperChange, {
      type,
      url,
      label: SettingsAnimations.wallpaperLabels[type] || type,
    });
  }

  if (!skipSave) {
    saveSetting('wallpaper_type', type);
    if (url) saveSetting('wallpaper_filename', url.split('/').pop()?.split('?')[0] || '');
  }
}

async function restoreWallpaper() {
  const type = state.settings.wallpaper_type;
  if (!type) return;

  if (type === 'custom' && state.settings.wallpaper_filename) {
    const url = `http://127.0.0.1:${state._staticPort}/wallpapers/${state.settings.wallpaper_filename}`;
    state._pendingWallpaper = { type: 'custom', url };
    applyWallpaperImmediate('custom', url);
  } else {
    state._pendingWallpaper = { type, url: null };
    applyWallpaperImmediate(type);
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
      const url = `http://127.0.0.1:${state._staticPort}/wallpapers/${result.filename}`;
      setWallpaper('custom', url);
      await loadCustomWallpapers();
      AnimationController.play(SettingsAnimations.animWallpaperImport, {
        filename: result.filename,
        url,
      });
      saveSetting('wallpaper_type', 'custom');
      saveSetting('wallpaper_filename', result.filename);
    } else {
      showToast('Erreur: ' + result.error, 'error');
    }
  } catch (e) {
    showToast('Erreur import', 'error');
  }
}

function setGlassIntensity(value) {
  const blur = 4 + (value / 100) * 36;
  const alpha = 0.18 - (value / 100) * 0.16;
  document.documentElement.style.setProperty('--glass-blur', `${blur}px`);
  document.documentElement.style.setProperty('--glass-alpha', alpha);
}

async function loadCustomWallpapers() {
  const grid = document.getElementById('wallpaper-custom-grid');
  if (!grid) return;
  try {
    const files = await api.call('get_wallpapers');
    grid.innerHTML = files.map(f => `
      <div class="wp-custom-item">
        <img src="http://127.0.0.1:${state._staticPort}/wallpapers/${f.filename}"
             onclick="app.setWallpaper('custom','http://127.0.0.1:${state._staticPort}/wallpapers/${f.filename}')">
        <button onclick="app.deleteWallpaper('${f.filename}')">✕</button>
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
  loadDaySummary();
  setInterval(loadDaySummary, 60 * 1000);
  updateBattery();
}

function updateActiveDocWidget(doc) {
  const gdocVal = document.getElementById('wval-gdoc');
  if (!gdocVal) return;
  if (doc?.title && doc?.url) {
    gdocVal.innerHTML = `<a href="#" class="widget-gdoc-link" data-url="${esc(doc.url)}">${esc(doc.title)}</a>`;
    const link = gdocVal.querySelector('.widget-gdoc-link');
    if (link) {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        api.openExternal(doc.url);
      });
    }
  } else {
    gdocVal.textContent = '—';
  }
}

async function loadDaySummary() {
  try {
    const data = await api.call('get_day_summary') || {};
    const tasksLabel = document.getElementById('wlabel-tasks');
    const tasksVal = document.getElementById('wval-tasks');
    const rappelsVal = document.getElementById('wval-rappels');

    if (tasksLabel) tasksLabel.textContent = data.tasks_label || 'Aucune tâche';
    if (tasksVal) tasksVal.textContent = data.tasks_detail || (data.tasks_count ? String(data.tasks_count) : '');
    if (rappelsVal) rappelsVal.textContent = data.rappels_label || '—';

    const gdocVal = document.getElementById('wval-gdoc');
    if (gdocVal) {
      const gdoc = data.active_gdoc;
      if (gdoc?.title && gdoc?.url) {
        updateActiveDocWidget(gdoc);
      } else {
        gdocVal.textContent = '—';
      }
    }

    try {
      const cal = await api.call('get_calendar_widget') || {};
      if (cal.success && cal.events?.length && rappelsVal) {
        const preview = cal.events.slice(0, 3).map(e => `${e.time} ${e.title}`).join(' · ');
        rappelsVal.textContent = preview;
      }
    } catch (_) {}
  } catch (_) {
    const tasksLabel = document.getElementById('wlabel-tasks');
    if (tasksLabel?.textContent === 'Chargement...') {
      tasksLabel.textContent = 'Aucune tâche planifiée';
    }
  }
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
  const cx = 55; const cy = 55; const r = 42; const lw = 8;
  const size = canvas.width || 110;

  ctx.clearRect(0, 0, size, size);

  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.strokeStyle = 'rgba(255,255,255,0.08)';
  ctx.lineWidth = lw;
  ctx.stroke();

  const angle = (pct / 100) * Math.PI * 2 - Math.PI / 2;
  const grad = ctx.createLinearGradient(0, 0, size, size);
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
  const grid = document.getElementById('shortcuts-grid');
  if (!grid) return;

  let shortcuts = [];
  try {
    const presets = await api.call('get_presets') || [];
    shortcuts = presets.slice(0, 4).map(p => ({
      icon: p.icon || '⚡',
      label: p.name || p.label || p.id,
      action: `active le mode ${p.name || p.label || p.id}`,
      color: '#6C8EFF',
    }));
  } catch (_) {}

  if (!shortcuts.length) {
    grid.innerHTML = `
      <div style="grid-column:1/-1;text-align:center;padding:12px;color:var(--text3);font-size:11px">
        Aucune routine configurée
      </div>`;
    return;
  }

  grid.innerHTML = shortcuts.map(s => `
    <button class="shortcut-btn" onclick="app.quickAction(${JSON.stringify(s.action)})"
            style="--shortcut-color: ${s.color}">
      <span class="shortcut-icon">${s.icon}</span>
      <span class="shortcut-label">${esc(s.label)}</span>
    </button>
  `).join('');
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
  state._generating = true;
  state._streamingContent = '';
  state._streamingMessage = null;
  setStatus('thinking');
  showStopButton();
  const input = document.getElementById('text-input');
  if (input) input.disabled = true;
  try {
    await api.call('ask', text, state.conversationMode || 'ecrit');
  } catch (e) {
    if (!e.message?.includes('stopped') && !e.message?.includes('abort')) {
      showToast('Erreur: ' + e.message, 'error');
    }
    finalizeAssistantMessage();
  } finally {
    state._generating = false;
    hideStopButton();
    setStatus('idle');
    if (input) {
      input.disabled = false;
      input.focus();
    }
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
  } else {
    console.error(`Page #page-${page} introuvable dans le DOM`);
  }

  document.querySelectorAll(`[data-page="${page}"]`).forEach(btn => btn.classList.add('active'));

  state.currentPage = page;

  if (page === 'settings') {
    loadSettingsPage();
    updateAgentsBadge();
  }
  if (page === 'conversations') loadFullConversationList();
  if (page === 'agents') {
    loadAgentsPage();
    updateAgentsBadge();
  }
  if (page === 'memory') loadMemoryPage();
  if (page === 'routines') {
    loadPresetsPage();
    loadAppsForAutocomplete();
  }
}

function showHomeConversation() {
  document.getElementById('home-logo-container')?.classList.add('shrunk');
  document.getElementById('home-messages')?.classList.remove('hidden');
  document.getElementById('home-glass-card')?.classList.add('has-conversation');
}

function showHomeIdle() {
  document.getElementById('home-logo-container')?.classList.remove('shrunk');
  document.getElementById('home-messages')?.classList.add('hidden');
  document.getElementById('home-glass-card')?.classList.remove('has-conversation');
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
  if (typeof window.showStyledSettingToast === 'function') {
    window.showStyledSettingToast('✓ Salutation mise à jour', '#4ADE80');
  } else {
    showToast('✓ Salutation mise à jour', 'success');
  }
}

function loadSettingsPage() {
  const s = state.settings || {};

  const fn = document.getElementById('set-firstname');
  if (fn) fn.value = s.user_firstname || '';
  const ht = document.getElementById('set-hello-text');
  if (ht) ht.value = s.hello_text || '';
  const st = document.getElementById('set-sub-text');
  if (st) st.value = s.sub_text || '';

  const tts = document.getElementById('set-tts');
  if (tts) tts.checked = s.tts_enabled !== false;

  const rate = document.getElementById('set-tts-rate');
  if (rate) {
    const rateVal = s.tts_rate;
    if (typeof rateVal === 'string') {
      const m = rateVal.match(/(-?\d+)/);
      rate.value = m ? m[1] : 0;
    } else {
      rate.value = rateVal ?? 0;
    }
  }

  const soundsEl = document.getElementById('set-sounds');
  if (soundsEl) soundsEl.checked = s.sounds_enabled !== false;

  const briefEl = document.getElementById('set-daily-brief');
  if (briefEl) briefEl.checked = s.daily_brief_enabled !== false;

  const wakeEl = document.getElementById('set-wake-word');
  if (wakeEl) wakeEl.checked = !!s.wake_word_enabled;

  const realtimeEl = document.getElementById('set-realtime-stt');
  if (realtimeEl) realtimeEl.checked = !!s.realtime_transcription;

  const focusEl = document.getElementById('set-focus');
  if (focusEl) focusEl.checked = !!s.focus_mode;

  const killOllamaEl = document.getElementById('set-kill-ollama');
  if (killOllamaEl) killOllamaEl.checked = s.kill_ollama_on_exit !== false;

  const lightVramEl = document.getElementById('set-light-vram');
  if (lightVramEl) lightVramEl.checked = !!s.light_vram_mode;

  const nexusEl = document.getElementById('set-nexus-mode');
  if (nexusEl) nexusEl.checked = !!s.nexus_mode;

  loadAppsIndexLabel();
  loadGoogleStatus();

  const di = document.getElementById('set-audio-device');
  const deviceIdx = s.stt?.device_index ?? s['stt.device_index'];
  if (di && deviceIdx != null) {
    const pyVal = `py_${deviceIdx}`;
    const opt = di.querySelector(`option[value="${pyVal}"]`);
    if (opt) di.value = pyVal;
  }

  const wm = document.getElementById('set-whisper-model');
  if (wm) wm.value = s.stt?.model || s['stt.model'] || s.whisper_model || 'small';

  const theme = s.theme || 'slate';
  document.querySelectorAll('.theme-pill').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.theme === theme);
  });
  state._pendingTheme = theme;

  const glass = document.getElementById('set-glass');
  if (glass) glass.value = s.glass_intensity ?? 60;

  if (document.getElementById('acc-modeles')?.classList.contains('open')) {
    loadModelSettings();
  }
  if (document.getElementById('acc-apikeys')?.classList.contains('open')) {
    loadApiKeys();
  }

  loadCustomWallpapers();
}

function applySettingsForm() {
  loadSettingsPage();
}

function styledSettingToast(message, color) {
  if (typeof window.showStyledSettingToast === 'function') {
    window.showStyledSettingToast(message, color);
  } else {
    showToast(message, 'success');
  }
}

async function validateSection(section) {
  const btn = document.querySelector(`#acc-${section} .settings-validate-btn`);
  if (btn) {
    btn.textContent = '⟳ Application...';
    btn.disabled = true;
  }

  try {
    switch (section) {
      case 'apparence': {
        const theme = document.querySelector('.theme-pill.active')?.dataset.theme
          || state._pendingTheme
          || state.settings.theme
          || 'slate';
        const glassVal = parseInt(document.getElementById('set-glass')?.value ?? '60', 10);
        await saveSetting('theme', theme);
        await saveSetting('glass_intensity', glassVal);
        state._pendingTheme = null;
        setTheme(theme);
        setGlassIntensity(glassVal);

        const wp = state._pendingWallpaper;
        if (wp?.type) {
          await saveSetting('wallpaper_type', wp.type);
          if (wp.url) {
            await saveSetting('wallpaper_filename', wp.url.split('/').pop()?.split('?')[0] || '');
          }
        }

        if (typeof SettingsAnimations !== 'undefined' && typeof AnimationController !== 'undefined') {
          AnimationController.play(SettingsAnimations.animThemeChange, {
            newTheme: theme,
            accentColor: SettingsAnimations.themeColors[theme]
              || getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
          });
          setTimeout(() => {
            AnimationController.play(SettingsAnimations.animGlassIntensity, { value: glassVal });
          }, 900);
          if (wp?.type) {
            setTimeout(() => {
              AnimationController.play(SettingsAnimations.animWallpaperChange, {
                type: wp.type,
                url: wp.url,
                label: SettingsAnimations.wallpaperLabels[wp.type] || wp.type,
              });
            }, 1800);
          }
        }
        showToast('Apparence appliquée ✓', 'success');
        break;
      }
      case 'greeting': {
        const fn = document.getElementById('set-firstname')?.value?.trim() || 'Mathis';
        const ht = document.getElementById('set-hello-text')?.value?.trim() || '';
        const st = document.getElementById('set-sub-text')?.value?.trim() || '';
        await saveSetting('user_firstname', fn);
        await saveSetting('hello_text', ht);
        await saveSetting('sub_text', st);
        updateClock();
        showToast('Salutation mise à jour ✓', 'success');
        break;
      }
      case 'voix': {
        const ttsEnabled = document.getElementById('set-tts')?.checked;
        const ttsRateNum = parseInt(document.getElementById('set-tts-rate')?.value || '0', 10);
        const ttsRate = `${ttsRateNum >= 0 ? '+' : ''}${ttsRateNum}%`;
        const soundsEnabled = document.getElementById('set-sounds')?.checked;
        const briefEnabled = document.getElementById('set-daily-brief')?.checked;
        const wakeEnabled = document.getElementById('set-wake-word')?.checked;
        const realtimeEnabled = document.getElementById('set-realtime-stt')?.checked;
        try { await api.call('set_tts_enabled', !!ttsEnabled); } catch (_) {}
        try { await api.call('set_tts_rate', ttsRate); } catch (_) {}
        await saveSetting('tts_enabled', !!ttsEnabled);
        await saveSetting('tts_rate', ttsRate);
        await saveSetting('sounds_enabled', !!soundsEnabled);
        try { await api.call('set_daily_brief', !!briefEnabled); } catch (_) {}
        try { await api.call('set_wake_word', !!wakeEnabled); } catch (_) {}
        try { await api.call('set_realtime_stt', !!realtimeEnabled); } catch (_) {}
        if (typeof SettingsAnimations !== 'undefined' && typeof AnimationController !== 'undefined') {
          AnimationController.play(SettingsAnimations.animTTSToggle, { enabled: !!ttsEnabled });
          setTimeout(() => {
            AnimationController.play(SettingsAnimations.animTTSRate, { rate: ttsRateNum });
          }, ttsEnabled ? 1100 : 400);
          if (document.getElementById('set-daily-brief')) {
            setTimeout(() => {
              AnimationController.play(SettingsAnimations.animDailyBriefToggle, { enabled: !!briefEnabled });
            }, 1600);
          }
        }
        showToast('Voix sauvegardée ✓', 'success');
        break;
      }
      case 'micro': {
        const deviceVal = document.getElementById('set-audio-device')?.value;
        let deviceIdx = null;
        if (deviceVal && deviceVal.startsWith('py_')) {
          deviceIdx = parseInt(deviceVal.replace('py_', ''), 10);
        }
        const whisperModel = document.getElementById('set-whisper-model')?.value;
        try { await api.call('set_stt_device_index', deviceIdx ?? ''); } catch (_) {}
        try { await api.call('set_whisper_model', whisperModel); } catch (_) {}
        await saveSetting('stt.device_index', deviceIdx);
        await saveSetting('stt.model', whisperModel);
        if (typeof SettingsAnimations !== 'undefined' && typeof AnimationController !== 'undefined') {
          AnimationController.play(SettingsAnimations.animDeviceChange, { deviceIndex: deviceIdx });
          if (whisperModel) {
            setTimeout(() => {
              AnimationController.play(SettingsAnimations.animWhisperModelChange, { modelName: whisperModel });
            }, 1200);
          }
        }
        showToast('Micro sauvegardé ✓', 'success');
        break;
      }
      case 'systeme': {
        const focusEnabled = document.getElementById('set-focus')?.checked;
        const killOllama = document.getElementById('set-kill-ollama')?.checked;
        const lightVram = document.getElementById('set-light-vram')?.checked;
        const nexusMode = document.getElementById('set-nexus-mode')?.checked;
        try { await api.call('set_focus_mode', !!focusEnabled); } catch (_) {}
        if (focusEnabled != null) await saveSetting('focus_mode', !!focusEnabled);
        if (killOllama != null) await saveSetting('kill_ollama_on_exit', !!killOllama);
        try { await api.call('set_light_vram_mode', !!lightVram); } catch (_) {}
        if (lightVram != null) await saveSetting('light_vram_mode', !!lightVram);
        try { await api.call('set_nexus_mode', !!nexusMode); } catch (_) {}
        if (nexusMode != null) await saveSetting('nexus_mode', !!nexusMode);
        if (typeof SettingsAnimations !== 'undefined' && typeof AnimationController !== 'undefined'
            && document.getElementById('set-focus')) {
          AnimationController.play(SettingsAnimations.animFocusMode, { enabled: !!focusEnabled });
        }
        showToast('Paramètres système appliqués ✓', 'success');
        break;
      }
      default:
        styledSettingToast(`✓ Section ${section} appliquée`, '#4ADE80');
    }
  } catch (e) {
    console.warn('validateSection', e);
    showToast('Erreur: ' + e.message, 'error');
  }

  setTimeout(() => {
    if (btn) {
      btn.textContent = '✓ Appliquer';
      btn.disabled = false;
    }
  }, 600);
}

async function optimizeMemory() {
  showToast('Optimisation de la mémoire...', 'info');
  try {
    const result = await api.call('optimize_memory');
    if (result?.success) {
      showToast(result.message || 'Mémoire optimisée ✓', 'success');
      await loadMemoryWidget();
      if (state.currentPage === 'memory') await loadMemoryPage();
    } else {
      showToast('Optimisation non disponible pour le moment', 'info');
    }
  } catch (_) {
    showToast('Optimisation non disponible pour le moment', 'info');
  }
}

function exploreMemory() {
  navigate('memory');
}

async function updateAgentsBadge() {
  try {
    const agents = await api.call('get_agents') || [];
    const count = agents.length;
    const navBadge = document.getElementById('agents-badge');
    if (navBadge) navBadge.textContent = count ? String(count) : '';
    const settingsBadge = document.getElementById('agents-settings-badge');
    if (settingsBadge) settingsBadge.textContent = count ? `${count} agent${count > 1 ? 's' : ''}` : '';
  } catch (_) {}
}

async function loadPresetsPage() {
  const container = document.getElementById('presets-page-list');
  if (!container) return;
  container.innerHTML = '<div class="loading-text">Chargement...</div>';
  try {
    const presets = await api.call('get_presets_full') || [];
    if (!presets.length) {
      container.innerHTML = '<div class="info-text">Aucune routine configurée</div>';
      return;
    }
    container.innerHTML = presets.map(p => `
      <div class="agent-card" style="margin-bottom:8px;display:flex;align-items:center;gap:10px">
        <span class="agent-card-icon">${p.icon || '⚡'}</span>
        <div style="flex:1;min-width:0">
          <div class="agent-card-name">${esc(p.name || p.label || p.id)}</div>
          <div class="agent-card-desc">${esc((p.apps_open || []).join(', ') || '—')}</div>
        </div>
        <button type="button" class="page-action-btn" style="padding:6px 10px" onclick="event.stopPropagation();app.openPresetEditor('${esc(p.id)}')">✎</button>
        <button type="button" class="page-action-btn" onclick="app.runPreset('${esc(p.id)}')">▶</button>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = `<div class="error-text">Erreur: ${esc(e.message)}</div>`;
  }
}

async function runPreset(presetId) {
  try {
    const result = await api.call('run_preset', presetId);
    if (result.success) showToast(result.message || 'Routine activée ✓', 'success');
    else showToast('Erreur: ' + (result.error || '?'), 'error');
  } catch (e) {
    showToast('Erreur lancement routine', 'error');
  }
}

function openPresetEditor(presetId) {
  openPresetEditorImpl(presetId).catch(e => console.error('openPresetEditor:', e));
}

async function openPresetEditorImpl(presetId) {
  state._editingPresetId = presetId;

  if (presetId) {
    const presets = await api.call('get_presets_full') || [];
    const preset = presets.find(p => p.id === presetId);
    if (preset) {
      const icon = preset.icon || '⚡';
      document.getElementById('preset-icon-btn').textContent = icon;
      document.getElementById('preset-icon-input').value = icon;
      document.getElementById('preset-name-input').value = preset.name || preset.label || presetId;
      document.getElementById('preset-volume').value = preset.volume ?? 50;
      setPresetAppTags('preset-apps-open-tags', preset.apps_open || []);
      setPresetAppTags('preset-apps-close-tags', preset.apps_close || []);
      document.getElementById('preset-message').value = preset.message || '';
    }
  } else {
    document.getElementById('preset-icon-btn').textContent = '⚡';
    document.getElementById('preset-icon-input').value = '⚡';
    document.getElementById('preset-name-input').value = '';
    document.getElementById('preset-volume').value = 50;
    setPresetAppTags('preset-apps-open-tags', []);
    setPresetAppTags('preset-apps-close-tags', []);
    document.getElementById('preset-message').value = '';
  }

  updatePresetPreview();
  initPresetEmojiPicker();
  await loadAppsForAutocomplete();
  const modal = document.getElementById('preset-editor-modal');
  modal?.classList.remove('hidden');
  requestAnimationFrame(() => modal?.classList.add('modal-open'));
}

function closePresetEditor() {
  const modal = document.getElementById('preset-editor-modal');
  modal?.classList.remove('modal-open');
  setTimeout(() => modal?.classList.add('hidden'), 250);
}

function updatePresetPreview() {
  const name = document.getElementById('preset-name-input')?.value || 'Nouvelle routine';
  const icon = document.getElementById('preset-icon-btn')?.textContent
    || document.getElementById('preset-icon-input')?.value
    || '⚡';
  const previewName = document.getElementById('preset-preview-name');
  const previewIcon = document.getElementById('preset-preview-icon');
  if (previewName) previewName.textContent = name;
  if (previewIcon) previewIcon.textContent = icon;
}

function initPresetEmojiPicker() {
  const picker = document.getElementById('preset-emoji-picker');
  if (!picker || picker._ready) return;
  picker._ready = true;
  picker.innerHTML = AGENT_EMOJIS.map(e =>
    `<button type="button" class="emoji-option" onclick="app.selectPresetEmoji('${e}')">${e}</button>`
  ).join('');
}

function togglePresetEmojiPicker() {
  const picker = document.getElementById('preset-emoji-picker');
  if (!picker) return;
  initPresetEmojiPicker();
  document.querySelectorAll('.emoji-picker').forEach(p => {
    if (p.id !== 'preset-emoji-picker') p.style.display = 'none';
  });
  picker.style.display = picker.style.display === 'none' ? 'grid' : 'none';
}

function selectPresetEmoji(emoji) {
  document.getElementById('preset-icon-btn').textContent = emoji;
  document.getElementById('preset-icon-input').value = emoji;
  document.getElementById('preset-emoji-picker').style.display = 'none';
  updatePresetPreview();
}

async function loadAppsForAutocomplete() {
  try {
    const apps = await api.call('get_apps_index') || [];
    const sorted = [...apps].sort((a, b) => (a.name || '').localeCompare(b.name || ''));
    const html = sorted
      .map((app) => `<option value="${esc(app.name)}" data-type="${esc(app.type || '')}"></option>`)
      .join('');

    for (const id of ['apps-datalist', 'installed-apps-list', 'agent-apps-datalist']) {
      const datalist = document.getElementById(id);
      if (datalist) datalist.innerHTML = html;
    }
    return apps;
  } catch (e) {
    console.error('Erreur chargement apps index:', e);
    return [];
  }
}

async function searchAppsLive(input) {
  if (!input) return;
  const query = input.value.trim();
  if (query.length < 2) {
    hideAppSuggestions(input);
    return;
  }

  try {
    const apps = await api.call('search_apps', query) || [];

    let dropdown = input.nextElementSibling;
    if (!dropdown || !dropdown.classList.contains('app-dropdown')) {
      dropdown = document.createElement('div');
      dropdown.className = 'app-dropdown';
      dropdown.style.cssText = `
        position:absolute; z-index:1000;
        background:rgba(16,20,50,0.95);
        border:1px solid rgba(108,142,255,0.2);
        border-radius:10px;
        max-height:200px; overflow-y:auto;
        min-width:100%; backdrop-filter:blur(20px);
        box-shadow:0 8px 32px rgba(0,0,30,0.4);
      `;
      input.parentElement.style.position = 'relative';
      input.parentElement.appendChild(dropdown);
    }

    const typeIcons = {
      registry: '🖥️',
      win32: '🖥️',
      uwp: '🏪',
      lnk: '📎',
      start_menu: '📎',
      steam_game: '🎮',
      gaming: '🎮',
      epic: '⚡',
      program_files: '📦',
      unknown: '📦',
    };

    dropdown.innerHTML = '';
    apps.forEach((app) => {
      const row = document.createElement('div');
      row.className = 'app-suggestion';
      row.style.cssText = `
        padding:8px 12px;cursor:pointer;display:flex;align-items:center;
        gap:8px;font-size:12px;color:rgba(255,255,255,0.75);
        border-bottom:1px solid rgba(255,255,255,0.04);transition:background 0.1s;
      `;
      row.addEventListener('mouseenter', () => { row.style.background = 'rgba(108,142,255,0.12)'; });
      row.addEventListener('mouseleave', () => { row.style.background = 'transparent'; });
      row.addEventListener('mousedown', (e) => {
        e.preventDefault();
        selectAppForPreset(input, app.name);
      });
      const icon = typeIcons[app.type] || '📦';
      row.innerHTML = `
        <span>${icon}</span>
        <span>${esc(app.name)}</span>
        <span style="font-size:10px;color:rgba(255,255,255,0.25);margin-left:auto">${esc(app.type || '')}</span>
      `;
      dropdown.appendChild(row);
    });

    dropdown.style.display = apps.length ? 'block' : 'none';
  } catch (e) {
    console.debug('searchAppsLive:', e);
  }
}

function hideAppSuggestions(input) {
  const dropdown = input?.parentElement?.querySelector('.app-dropdown');
  if (dropdown) dropdown.style.display = 'none';
}

function createAppTag(appName) {
  const tag = document.createElement('div');
  tag.className = 'app-tag';
  tag.dataset.appName = appName;
  tag.style.cssText = `
    display:inline-flex;align-items:center;gap:5px;
    padding:4px 10px;margin:3px;
    background:rgba(108,142,255,0.15);
    border:1px solid rgba(108,142,255,0.25);
    border-radius:20px;font-size:11px;color:rgba(255,255,255,0.8);
  `;
  const label = document.createElement('span');
  label.textContent = appName;
  const remove = document.createElement('span');
  remove.textContent = '✕';
  remove.style.cssText = 'cursor:pointer;opacity:0.5;font-size:12px;margin-left:2px';
  remove.addEventListener('click', () => tag.remove());
  tag.appendChild(label);
  tag.appendChild(remove);
  return tag;
}

function setPresetAppTags(containerId, appNames) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = '';
  (appNames || []).forEach((name) => {
    if (name) container.appendChild(createAppTag(name));
  });
}

function selectAppForPreset(input, appName) {
  const section = input?.closest('.preset-section');
  const container = section?.querySelector('.app-tags');
  if (!container || !appName) return;

  const existing = Array.from(container.querySelectorAll('.app-tag'))
    .map((tag) => tag.dataset.appName);
  if (!existing.includes(appName)) {
    container.appendChild(createAppTag(appName));
  }

  input.value = '';
  hideAppSuggestions(input);
}

function getSelectedApps(containerSelector) {
  const el = document.querySelector(containerSelector);
  return Array.from(el?.querySelectorAll('.app-tag') || [])
    .map((tag) => tag.dataset.appName)
    .filter(Boolean);
}

async function refreshInstalledAppsDatalist() {
  return loadAppsForAutocomplete();
}

async function refreshAppsIndex() {
  try {
    const result = await api.call('refresh_apps_index');
    if (result.success) {
      showToast(`${result.count} applications indexées`, 'success');
      loadAppsIndexLabel();
      refreshInstalledAppsDatalist();
    } else {
      showToast('Erreur scan applications', 'error');
    }
  } catch (e) {
    showToast('Erreur: ' + e.message, 'error');
  }
}

async function loadGoogleStatus() {
  const badge = document.getElementById('google-status-badge');
  const detail = document.getElementById('google-status-detail');
  if (!badge && !detail) return;
  try {
    const st = await api.call('get_google_status') || {};
    if (st.authenticated) {
      if (badge) badge.textContent = 'Connecté ✓';
      if (detail) detail.textContent = 'Compte Google authentifié — Calendar, Gmail, Drive, Sheets actifs.';
    } else if (st.configured) {
      if (badge) badge.textContent = 'À connecter';
      if (detail) detail.textContent = 'credentials.json détecté — clique « Connecter Google » pour autoriser ARIA.';
    } else {
      if (badge) badge.textContent = 'Non configuré';
      if (detail) detail.textContent = 'Place credentials.json à la racine du projet (OAuth Desktop Google Cloud).';
    }
  } catch (_) {
    if (badge) badge.textContent = '—';
    if (detail) detail.textContent = 'Impossible de lire le statut Google.';
  }
}

async function connectGoogle() {
  showToast('Ouverture OAuth Google…', 'info');
  try {
    const result = await api.call('run_google_setup');
    if (result.success) {
      showToast('Google connecté ✓', 'success');
      loadGoogleStatus();
    } else {
      showToast('Erreur : ' + (result.error || '?'), 'error');
    }
  } catch (e) {
    showToast('Erreur connexion Google', 'error');
  }
}

async function loadAppsIndexLabel() {
  const el = document.getElementById('apps-index-label');
  if (!el) return;
  try {
    const stats = await api.call('get_apps_index_stats') || {};
    el.textContent = stats.count
      ? `${stats.count} apps indexées`
      : 'Non scanné';
  } catch (_) {
    el.textContent = '—';
  }
}

async function pickAndRegisterLocalModel() {
  if (!window.ARIA?.pickGgufFile) {
    showToast('Import disponible uniquement dans Electron', 'error');
    return;
  }
  const filePath = await window.ARIA.pickGgufFile();
  if (!filePath) return;
  showToast('Import du modèle...', 'info');
  try {
    const result = await api.call('register_local_model', filePath);
    if (result.success) {
      showToast(`Modèle ${result.filename} importé ✓`, 'success');
      loadModelSettings();
    } else {
      showToast('Erreur: ' + (result.error || '?'), 'error');
    }
  } catch (_) {
    showToast('Erreur import modèle', 'error');
  }
}

async function registerLocalModel(file) {
  if (!file?.name?.toLowerCase().endsWith('.gguf')) {
    showToast('Sélectionne un fichier .gguf', 'error');
    return;
  }
  const filePath = file.path;
  if (!filePath) {
    showToast('Chemin fichier inaccessible — relance depuis Electron', 'error');
    return;
  }
  showToast('Import du modèle...', 'info');
  try {
    const result = await api.call('register_local_model', filePath);
    if (result.success) {
      showToast(`Modèle ${result.filename} importé ✓`, 'success');
      loadModelSettings();
    } else {
      showToast('Erreur: ' + (result.error || '?'), 'error');
    }
  } catch (e) {
    showToast('Erreur import modèle', 'error');
  }
}

async function savePreset() {
  const name = document.getElementById('preset-name-input')?.value?.trim();
  if (!name) {
    showToast('Le nom est obligatoire', 'error');
    return;
  }

  const key = name.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, '_');
  const data = {
    name,
    icon: document.getElementById('preset-icon-btn')?.textContent?.trim()
      || document.getElementById('preset-icon-input')?.value?.trim()
      || '⚡',
    volume: parseInt(document.getElementById('preset-volume')?.value || '50', 10),
    apps_open: getSelectedApps('#preset-apps-open-tags'),
    apps_close: getSelectedApps('#preset-apps-close-tags'),
    message: document.getElementById('preset-message')?.value?.trim() || `Mode ${name} activé.`,
  };

  try {
    const result = await api.call('save_preset', state._editingPresetId || key, JSON.stringify(data));
    if (result.success) {
      showToast('Routine enregistrée ✓', 'success');
      closePresetEditor();
      loadPresetsPage();
      loadShortcutsWidget();
    } else {
      showToast('Erreur: ' + (result.error || '?'), 'error');
    }
  } catch (e) {
    showToast('Erreur enregistrement routine', 'error');
  }
}

function toggleWidget(name) {
  const body = document.getElementById(`widget-${name}-body`);
  if (body) body.classList.toggle('collapsed');
}

function toggleModeMenu() {
  document.getElementById('mode-menu')?.classList.toggle('hidden');
}

function toggleAgentDropdown() {
  const dropdown = document.getElementById('agent-dropdown');
  if (!dropdown) return;
  dropdown.classList.toggle('hidden');
  if (!dropdown.classList.contains('hidden')) {
    bindAgentDropdownEvents();
  }
}

const PRIVACY_MODE_LABELS = {
  local: 'Mode Privé',
  hybrid: 'Mode Hybride',
  cloud: 'Mode Cloud',
};

function setPrivacyMode(mode) {
  const m = ['local', 'hybrid', 'cloud'].includes(mode) ? mode : 'local';
  const badge = document.getElementById('home-mode-badge');
  const labelEl = document.getElementById('home-mode-label');
  if (labelEl) labelEl.textContent = PRIVACY_MODE_LABELS[m] || PRIVACY_MODE_LABELS.local;
  if (badge) badge.classList.toggle('private', m === 'local');
  saveSetting('privacy_mode', m);
  document.getElementById('mode-menu')?.classList.add('hidden');
}

async function loadMemoryPage() {
  await loadMemoryWidget();
  const content = document.getElementById('memory-content');
  if (!content) return;
  try {
    const data = await api.call('get_memory_stats') || {};
    let engineStats = {};
    try {
      engineStats = await api.call('get_memory_engine_stats') || {};
    } catch (_) {}

    const pct = Math.min(100, Math.round((data.messages || 0) / 5));
    content.innerHTML = `
      <div class="memory-page-stats">
        <div class="mem-stat-card"><div class="mem-stat-val">${data.conversations ?? 0}</div><div class="mem-stat-label">Conversations</div></div>
        <div class="mem-stat-card"><div class="mem-stat-val">${data.messages ?? 0}</div><div class="mem-stat-label">Messages</div></div>
        <div class="mem-stat-card"><div class="mem-stat-val">${data.sessions ?? 0}</div><div class="mem-stat-label">Sessions</div></div>
      </div>
      <div class="memory-insight-card">
        <div class="memory-insight-title">Utilisation mémoire</div>
        <div class="memory-insight-row"><span>Capacité estimée</span><span>${pct}%</span></div>
        <div class="memory-insight-row"><span>Satisfaction</span><span>${engineStats.satisfaction || '—'}</span></div>
        <div class="memory-insight-row"><span>App la plus utilisée</span><span>${engineStats.top_app || '—'}</span></div>
        <div class="memory-insight-row"><span>Sujet fréquent</span><span>${engineStats.top_topic || '—'}</span></div>
      </div>
      <div style="padding:0 24px 24px">
        <button class="widget-action-btn" onclick="app.optimizeMemory()" style="width:100%">Optimiser la mémoire</button>
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
    await updateAgentsBadge();
  } catch (e) {
    list.innerHTML = `<div class="error-text">Erreur: ${esc(e.message)}</div>`;
  }
}

function openAgentEditor(agentId) {
  openAgentEditorImpl(agentId).catch(e => console.error('openAgentEditor:', e));
}

async function openAgentEditorImpl(agentId) {
  state._editingAgentId = agentId;
  state._agentRules = [];
  state._agentRepos = [];

  let modelsData = {};
  try {
    modelsData = await api.call('get_available_models') || {};
  } catch (_) {}

  const models = modelsData.local_models || [];
  const cloudModels = modelsData.cloud_models || [];

  const modelSelect = document.getElementById('agent-model-select');
  if (modelSelect) {
    let html = '';
    if (models.length) {
      html += `<optgroup label="💻 Local">${models.map(m =>
        `<option value="${esc(m)}">${esc(m)}</option>`
      ).join('')}</optgroup>`;
    }
    if (cloudModels.length) {
      html += `<optgroup label="☁️ Cloud (API)">${cloudModels.map(cm =>
        `<option value="${esc(cm.id)}">☁️ ${esc(cm.label)} (${esc(cm.provider_name)})</option>`
      ).join('')}</optgroup>`;
    }
    modelSelect.innerHTML = html || '<option value="">Aucun modèle disponible</option>';
  }

  const picker = document.getElementById('agent-emoji-picker');
  if (picker) {
    picker.innerHTML = AGENT_EMOJIS.map(e =>
      `<button type="button" class="emoji-option" onclick="app.selectAgentEmoji('${e}')">${e}</button>`
    ).join('');
  }

  const colorSwatches = document.getElementById('agent-color-swatches');
  if (colorSwatches) {
    colorSwatches.innerHTML = AGENT_COLORS.map(c => `
      <button type="button" class="color-swatch" style="background:${c}"
        onclick="app.selectAgentColor('${c}')"
        title="${c}">
      </button>
    `).join('');
  }

  if (agentId) {
    const agents = await api.call('get_agents') || [];
    const agent = agents.find(a => a.id === agentId);
    if (agent) {
      document.getElementById('agent-name-input').value = agent.name;
      document.getElementById('agent-icon-btn').textContent = agent.icon || '🤖';
      document.getElementById('agent-system-prompt').value = agent.system_prompt || '';
      if (modelSelect) modelSelect.value = agent.model || models[0] || '';
      state._agentRules = [...(agent.rules || [])];
      state._agentRepos = [...(agent.git_repos || [])];
      state._selectedColor = agent.color || '#6C8EFF';
      const deleteBtn = document.getElementById('agent-delete-btn');
      if (deleteBtn) deleteBtn.style.display = agentId === 'default' ? 'none' : 'flex';
    }
  } else {
    document.getElementById('agent-name-input').value = '';
    document.getElementById('agent-icon-btn').textContent = '🤖';
    document.getElementById('agent-system-prompt').value = '';
    state._selectedColor = '#6C8EFF';
    document.getElementById('agent-delete-btn').style.display = 'none';
    if (modelSelect && models[0]) modelSelect.value = models[0];
  }

  renderAgentRulesList();
  renderAgentReposList();
  updateAgentPreview();
  selectAgentColor(state._selectedColor);

  const modal = document.getElementById('agent-editor-modal');
  modal?.classList.remove('hidden');
  requestAnimationFrame(() => modal?.classList.add('modal-open'));
}

function closeAgentEditor() {
  const modal = document.getElementById('agent-editor-modal');
  modal?.classList.remove('modal-open');
  setTimeout(() => modal?.classList.add('hidden'), 250);
}

function updateAgentPreview() {
  const name = document.getElementById('agent-name-input')?.value || 'Nouvel agent';
  const icon = document.getElementById('agent-icon-btn')?.textContent || '🤖';
  const previewName = document.getElementById('agent-preview-name');
  const previewIcon = document.getElementById('agent-preview-icon');
  if (previewName) previewName.textContent = name;
  if (previewIcon) previewIcon.textContent = icon;
}

function selectAgentEmoji(emoji) {
  document.getElementById('agent-icon-btn').textContent = emoji;
  document.getElementById('agent-emoji-picker').style.display = 'none';
  updateAgentPreview();
}

function selectAgentColor(color) {
  state._selectedColor = color;
  document.querySelectorAll('#agent-color-swatches .color-swatch').forEach(s => {
    s.classList.toggle('active', s.getAttribute('title') === color);
  });
}

function toggleAgentEmojiPicker() {
  const picker = document.getElementById('agent-emoji-picker');
  if (!picker) return;
  document.querySelectorAll('.emoji-picker').forEach(p => {
    if (p.id !== 'agent-emoji-picker') p.style.display = 'none';
  });
  picker.style.display = picker.style.display === 'none' ? 'grid' : 'none';
}

function addAgentRule() {
  const input = document.getElementById('agent-rule-input');
  const rule = input?.value?.trim();
  if (!rule) return;
  state._agentRules.push(rule);
  input.value = '';
  renderAgentRulesList();
}

function removeAgentRule(idx) {
  state._agentRules.splice(idx, 1);
  renderAgentRulesList();
}

function renderAgentRulesList() {
  const list = document.getElementById('agent-rules-list');
  if (!list) return;
  list.innerHTML = state._agentRules.map((rule, i) => `
    <div class="agent-tag-item">
      <span>${esc(rule)}</span>
      <button type="button" onclick="app.removeAgentRule(${i})">✕</button>
    </div>
  `).join('');
}

async function addAgentRepo() {
  const input = document.getElementById('agent-repo-input');
  const path = input?.value?.trim();
  if (!path) return;

  const statusEl = document.getElementById('agent-repo-status');
  if (statusEl) {
    statusEl.textContent = 'Vérification...';
    statusEl.style.color = 'var(--text3)';
  }

  try {
    const result = await api.call('validate_git_repo', path);
    if (result.valid) {
      state._agentRepos.push(result.path);
      input.value = '';
      if (statusEl) {
        statusEl.textContent = '✅ Repo Git valide';
        statusEl.style.color = 'var(--success)';
      }
      renderAgentReposList();
      setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 2000);
    } else if (statusEl) {
      statusEl.textContent = '❌ Chemin invalide ou pas un repo Git';
      statusEl.style.color = 'var(--error)';
    }
  } catch (_) {
    if (statusEl) {
      statusEl.textContent = '❌ Erreur de validation';
      statusEl.style.color = 'var(--error)';
    }
  }
}

function removeAgentRepo(idx) {
  state._agentRepos.splice(idx, 1);
  renderAgentReposList();
}

function renderAgentReposList() {
  const list = document.getElementById('agent-repos-list');
  if (!list) return;
  list.innerHTML = state._agentRepos.map((repo, i) => `
    <div class="agent-tag-item agent-repo-item">
      <span style="font-size:11px">📁 ${esc(repo)}</span>
      <button type="button" onclick="app.removeAgentRepo(${i})">✕</button>
    </div>
  `).join('');
}

async function saveAgent() {
  const name = document.getElementById('agent-name-input')?.value?.trim();
  if (!name) {
    showToast('Le nom est obligatoire', 'error');
    return;
  }

  const data = {
    name,
    icon: document.getElementById('agent-icon-btn')?.textContent || '🤖',
    color: state._selectedColor || '#6C8EFF',
    model: document.getElementById('agent-model-select')?.value,
    system_prompt: document.getElementById('agent-system-prompt')?.value || '',
    rules: state._agentRules,
    git_repos: state._agentRepos,
  };

  let result;
  if (state._editingAgentId) {
    result = await api.call('update_agent', state._editingAgentId, JSON.stringify(data));
  } else {
    result = await api.call('create_agent', JSON.stringify(data));
  }

  if (result.success) {
    showToast(`Agent "${data.icon} ${data.name}" sauvegardé ✓`, 'success');
    closeAgentEditor();
    await loadAgentsPage();
    await loadAgentDropdown();
  } else {
    showToast('Erreur: ' + (result.error || 'inconnue'), 'error');
  }
}

async function deleteCurrentAgent() {
  if (!state._editingAgentId || state._editingAgentId === 'default') return;
  if (!confirm('Supprimer cet agent ? Cette action est irréversible.')) return;

  const result = await api.call('delete_agent', state._editingAgentId);
  if (result.success) {
    showToast('Agent supprimé', 'success');
    closeAgentEditor();
    await loadAgentsPage();
    await loadAgentDropdown();
  }
}

function applyActiveAgentUI(agent) {
  if (!agent) return;
  state._activeAgentId = agent.id || 'default';
  state._activeAgentIcon = agent.icon || '🤖';
  state._activeAgentName = agent.name || 'ARIA';
  const color = agent.color || '#6C8EFF';

  const chipIcon = document.getElementById('agent-chip-icon');
  const chipName = document.getElementById('agent-chip-name');
  const homeIcon = document.getElementById('home-agent-icon');
  const homeName = document.getElementById('home-agent-name');
  const inputIcon = document.getElementById('input-agent-icon');
  const inputName = document.getElementById('input-agent-name');
  const selector = document.getElementById('input-agent-selector');

  if (chipIcon) chipIcon.textContent = state._activeAgentIcon;
  if (chipName) chipName.textContent = state._activeAgentName;
  if (homeIcon) homeIcon.textContent = state._activeAgentIcon;
  if (homeName) {
    homeName.textContent = agent.id === 'default'
      ? 'ARIA'
      : (state._activeAgentName || 'ARIA');
  }
  if (inputIcon) inputIcon.textContent = state._activeAgentIcon;
  if (inputName) {
    inputName.textContent = agent.id === 'default'
      ? 'Assistant Avancé'
      : (state._activeAgentName || 'Assistant Avancé');
  }
  if (selector) selector.style.borderColor = color;
  document.documentElement.style.setProperty('--agent-color', color);
}

async function loadActiveAgent() {
  try {
    const active = await api.call('get_active_agent') || {};
    applyActiveAgentUI(active);
  } catch (e) {
    console.warn('loadActiveAgent:', e);
  }
}

async function loadAgentDropdown() {
  try {
    const agents = await api.call('get_agents') || [];
    renderAgentDropdown(agents);
  } catch (e) {
    console.warn('loadAgentDropdown:', e);
  }
}

function renderAgentDropdown(agents) {
  const dropdown = document.getElementById('agent-dropdown');
  if (!dropdown) return;
  const activeId = state._activeAgentId || 'default';

  dropdown.innerHTML = agents.map(agent => {
    const active = agent.id === activeId;
    return `
      <div class="agent-dropdown-item${active ? ' active' : ''}" data-agent-id="${esc(agent.id)}">
        <span style="font-size:18px">${agent.icon || '🤖'}</span>
        <div style="min-width:0;flex:1">
          <div style="font-size:13px;color:var(--text)">${esc(agent.name)}</div>
          <div style="font-size:10px;color:var(--text3)">${esc(agent.model || '')}</div>
        </div>
        ${active ? '<span style="color:var(--accent);font-size:12px">✓</span>' : ''}
      </div>`;
  }).join('') + `
    <div class="agent-dropdown-divider"></div>
    <div class="agent-dropdown-item" data-agent-create>
      <span style="font-size:16px">+</span>
      <div style="font-size:13px;color:var(--accent)">Créer un agent</div>
    </div>
  `;
  bindAgentDropdownEvents();
}

function bindAgentDropdownEvents() {
  const dropdown = document.getElementById('agent-dropdown');
  if (!dropdown || dropdown._pickBound) return;
  dropdown._pickBound = true;
  dropdown.addEventListener('mousedown', e => e.stopPropagation());
  dropdown.addEventListener('click', e => {
    const createBtn = e.target.closest('[data-agent-create]');
    if (createBtn) {
      e.stopPropagation();
      openAgentEditor(null);
      dropdown.classList.add('hidden');
      return;
    }
    const item = e.target.closest('.agent-dropdown-item[data-agent-id]');
    if (!item) return;
    e.stopPropagation();
    setActiveAgent(item.getAttribute('data-agent-id'));
  });
}

async function setActiveAgent(agentId) {
  const result = await api.call('set_active_agent', agentId);
  if (result.success) {
    applyActiveAgentUI(result.agent);
    document.getElementById('agent-dropdown')?.classList.add('hidden');
    await loadAgentDropdown();
    showToast(`Agent "${result.agent.icon} ${result.agent.name}" activé`, 'success');
  }
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
  if (!text) return '';

  const links: { label: string; url: string }[] = [];
  let processed = String(text).replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => {
    const id = links.length;
    links.push({ label, url });
    return `\x00LINK${id}\x00`;
  });

  let html = esc(processed);
  links.forEach((link, id) => {
    const safeUrl = link.url.replace(/"/g, '&quot;');
    html = html.replace(
      `\x00LINK${id}\x00`,
      `<a href="#" class="md-link" data-url="${safeUrl}">${esc(link.label)}</a>`
    );
  });

  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h2">$1</h3>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/^• (.+)$/gm, '<div class="md-bullet">• $1</div>');
  html = html.replace(/\n/g, '<br>');
  return html;
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
    if (!accId || el.getAttribute('onclick')) return;
    el.addEventListener('click', () => toggleAccordion(accId));
  });

  document.querySelectorAll('.theme-pill[data-theme]').forEach(btn => {
    if (btn.getAttribute('onclick')) return;
    btn.addEventListener('click', () => setTheme(btn.dataset.theme));
  });

  document.querySelectorAll('.wp-thumb').forEach(el => {
    if (el.getAttribute('onclick')) return;
    const wpClass = [...el.classList].find(c => c.startsWith('wp-') && c !== 'wp-thumb');
    if (!wpClass) return;
    el.addEventListener('click', () => setWallpaper(wpClass.replace(/^wp-/, '')));
  });

  const loadModelsBtn = document.querySelector('#acc-modeles .settings-btn-outline');
  loadModelsBtn?.addEventListener('click', () => loadModelSettings());

  const textInput = document.getElementById('text-input');
  textInput?.addEventListener('keydown', handleInputKeydown);
  textInput?.addEventListener('input', function onInput() { adjustTextarea(this); });

  if (!document.body._ariaStopKeyBound) {
    document.body._ariaStopKeyBound = true;
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && state._generating) {
        e.preventDefault();
        stopGeneration();
      }
    });
  }

  const inputZone = document.getElementById('input-zone');
  if (inputZone && !inputZone._dropBound) {
    inputZone._dropBound = true;
    inputZone.addEventListener('dragover', e => { e.preventDefault(); inputZone.classList.add('drag-over'); });
    inputZone.addEventListener('dragleave', () => inputZone.classList.remove('drag-over'));
    inputZone.addEventListener('drop', e => {
      e.preventDefault();
      inputZone.classList.remove('drag-over');
      if (e.dataTransfer?.files?.length) handleFiles(e.dataTransfer.files);
    });
  }
}

async function checkMicPermission() {
  try {
    if (!navigator.permissions?.query) return;
    const result = await navigator.permissions.query({ name: 'microphone' });
    const el = document.getElementById('mic-permission-status');
    if (el) el.style.display = result.state === 'denied' ? 'block' : 'none';
    result.onchange = () => {
      if (el) el.style.display = result.state === 'denied' ? 'block' : 'none';
    };
  } catch (_) {}
}

async function refreshAudioDevices() {
  const select = document.getElementById('set-audio-device');
  if (!select) return;

  try {
    await checkMicPermission();

    if (navigator.mediaDevices?.getUserMedia) {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((t) => t.stop());
    }

    const audioInputs = navigator.mediaDevices
      ? (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'audioinput')
      : [];

    let pyDevices = [];
    try {
      pyDevices = await api.call('get_audio_devices') || [];
      if (typeof pyDevices === 'string') pyDevices = JSON.parse(pyDevices);
    } catch (_) {}

    const saved = state.settings?.stt?.device_index ?? state.settings?.['stt.device_index'];
    select.innerHTML = '<option value="-1">Auto (recommandé)</option>';

    audioInputs.forEach((d) => {
      const opt = document.createElement('option');
      opt.value = d.deviceId;
      opt.textContent = `🌐 ${d.label || 'Microphone ' + d.deviceId.slice(0, 8)}`;
      select.appendChild(opt);
    });

    pyDevices.forEach((d) => {
      const opt = document.createElement('option');
      opt.value = `py_${d.index}`;
      opt.textContent = `🐍 [${d.index}] ${d.name}`;
      if (saved != null && String(d.index) === String(saved)) opt.selected = true;
      select.appendChild(opt);
    });

    showToast(`${audioInputs.length + pyDevices.length} devices trouvés`, 'success');
  } catch (e) {
    showToast('Erreur: ' + e.message, 'error');
  }
}

async function testMicrophone() {
  const resultEl = document.getElementById('mic-test-result');
  const deviceSelect = document.getElementById('set-audio-device');
  const deviceVal = deviceSelect?.value;

  if (resultEl) resultEl.textContent = '🎤 Test en cours (2 secondes)...';

  try {
    const deviceIndex = deviceVal?.startsWith('py_')
      ? parseInt(deviceVal.replace('py_', ''), 10)
      : null;

    const result = await api.call('test_microphone', deviceIndex);

    if (resultEl) {
      if (result?.success && result.is_active) {
        const bars = Math.round((result.avg_rms || 0) * 1000);
        resultEl.style.color = '#4ADE80';
        resultEl.textContent = `✅ ${result.message} (niveau: ${bars}/10)`;
      } else if (result?.success) {
        resultEl.style.color = '#F59E0B';
        resultEl.textContent = '⚠️ Microphone détecté mais aucun son — parle dans le micro';
      } else {
        resultEl.style.color = '#F87171';
        resultEl.textContent = `❌ Erreur: ${result?.error || 'inconnue'}`;
      }
    }
  } catch (e) {
    if (resultEl) {
      resultEl.style.color = '#F87171';
      resultEl.textContent = '❌ Erreur: ' + e.message;
    }
  }
}

async function setAudioDevice(value) {
  if (!value || value === '-1') {
    try { await api.call('set_stt_device_index', ''); } catch (_) {}
    await saveSetting('stt.device_index', null);
    showToast('Device audio : auto', 'success');
    return;
  }
  if (value.startsWith('py_')) {
    const idx = parseInt(value.replace('py_', ''), 10);
    try { await api.call('set_stt_device', idx); } catch (_) {
      await api.call('set_stt_device_index', idx);
    }
    await saveSetting('stt.device_index', idx);
    showToast(`Device PyAudio [${idx}] sélectionné`, 'success');
  } else {
    await saveSetting('stt.device_id_browser', value);
    showToast('Device navigateur mis à jour', 'success');
  }
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
    stopGeneration,
    handleInputKeydown,
    adjustTextarea,
    toggleMic,
    selectConversationMode,
    toggleSettings,
    toggleAccordion,
    loadModelSettings,
    switchModelTab,
    loadModelCatalog,
    installModel,
    uninstallModel,
    setModelForRole,
    loadProfilesSettings,
    activateProfile,
    createProfile,
    deleteProfile,
    toggleNexusMode,
    refreshVramWidget,
    checkForUpdates,
    applyUpdate,
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
    loadSettingsPage,
    validateSection,
    toggleWidget,
    toggleModeMenu,
    toggleAgentDropdown,
    setPrivacyMode,
    openAgentEditor,
    closeAgentEditor,
    saveAgent,
    deleteCurrentAgent,
    selectAgentEmoji,
    selectAgentColor,
    toggleAgentEmojiPicker,
    addAgentRule,
    removeAgentRule,
    addAgentRepo,
    removeAgentRepo,
    updateAgentPreview,
    setActiveAgent,
    loadAgentDropdown,
    loadActiveAgent,
    loadPresetsPage,
    runPreset,
    openPresetEditor,
    closePresetEditor,
    savePreset,
    updatePresetPreview,
    optimizeMemory,
    exploreMemory,
    updateAgentsBadge,
    togglePresetEmojiPicker,
    selectPresetEmoji,
    refreshAppsIndex,
    refreshInstalledAppsDatalist,
    loadAppsForAutocomplete,
    searchAppsLive,
    hideAppSuggestions,
    selectAppForPreset,
    getSelectedApps,
    setPresetAppTags,
    registerLocalModel,
    pickAndRegisterLocalModel,
    loadGoogleStatus,
    connectGoogle,
    loadApiKeys,
    saveApiKey,
    deleteApiKey,
    testApiKey,
    showApiKeyInput,
    exportConversation: () => api.call('export_current_conversation'),
    runMicDiagnostic: () => api.call('run_mic_diagnostic'),
    refreshAudioDevices,
    testMicrophone,
    setAudioDevice,
    checkMicPermission,
    handleFiles,
    askFilePrompt,
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
  applyAriaLogo();
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
