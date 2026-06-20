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
};

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
];

const SoundFX = {
  volume: 0.18,
  _ctx: null,
  _buffers: {},
  _fileMap: {
    start: 'activate.mp3',
    listening: 'listening.mp3',
    done: 'response.mp3',
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
  await loadActiveAgent();
  await loadAgentDropdown();
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
  api.on('assistant_done', () => {
    finalizeAssistantMessage();
    SoundFX.play('done');
  });

  api.on('tts_finished', () => {
    if (state.micActive) setStatus('listening');
    else setStatus('idle');
  });

  api.on('gdoc_link', ({ title, url }) => showGdocLinkCard(title, url));

  api.on('search_results', (html) => showSearchResultsCard(html));

  api.on('focus_indicator', (active) => updateFocusIndicator(active));

  api.on('error', (text) => {
    showToast(text || 'Erreur', 'error');
    setStatus('idle');
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
    SoundFX.play('start');
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
  loadDaySummary();
  setInterval(loadDaySummary, 60 * 1000);
  updateBattery();
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

  const fixed = [
    { icon: '✉️', label: 'Rédiger un email', action: 'rédige un email professionnel', color: '#6C8EFF' },
    { icon: '🎯', label: 'Démarrer focus', action: 'active le mode focus', color: '#A78BFA' },
    { icon: '📊', label: 'Analyse système', action: 'analyse le système', color: '#4ADE80' },
  ];

  let presetShortcuts = [];
  try {
    const presets = await api.call('get_presets') || [];
    presetShortcuts = presets.slice(0, 1).map(p => ({
      icon: p.icon || '⚡',
      label: `Mode ${p.name || p.id}`,
      action: `active le mode ${p.name || p.id}`,
      color: '#F59E0B',
    }));
  } catch (_) {}

  const all = [...fixed, ...presetShortcuts].slice(0, 4);

  grid.innerHTML = all.map(s => `
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
  if (page === 'routines') loadPresetsPage();
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
  if (typeof window.showStyledSettingToast === 'function') {
    window.showStyledSettingToast('✓ Salutation mise à jour', '#4ADE80');
  } else {
    showToast('✓ Salutation mise à jour', 'success');
  }
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

  const ttsEl = document.getElementById('set-tts');
  if (ttsEl) ttsEl.checked = s.tts_enabled !== false;

  const ttsRateEl = document.getElementById('set-tts-rate');
  if (ttsRateEl && s.tts_rate != null) ttsRateEl.value = s.tts_rate;

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

  const deviceEl = document.getElementById('set-device-index');
  const deviceIdx = s.stt?.device_index ?? s['stt.device_index'];
  if (deviceEl && deviceIdx != null) deviceEl.value = deviceIdx;

  const whisperEl = document.getElementById('set-whisper-model');
  const whisperModel = s.stt?.model || s.whisper_model;
  if (whisperEl && whisperModel) whisperEl.value = whisperModel;
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
        const theme = state._pendingTheme || state.settings.theme || 'slate';
        const glassVal = parseInt(document.getElementById('set-glass')?.value ?? '60', 10);
        await saveSetting('theme', theme);
        await saveSetting('glass_intensity', glassVal);
        state._pendingTheme = null;

        const wp = state._pendingWallpaper;
        if (wp?.type) {
          await saveSetting('wallpaper_type', wp.type);
          if (wp.url) {
            await saveSetting('wallpaper_filename', wp.url.split('/').pop()?.split('?')[0] || '');
          }
        }

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
        break;
      }
      case 'greeting':
        applyGreeting();
        break;
      case 'voix': {
        const ttsEnabled = document.getElementById('set-tts')?.checked;
        const ttsRate = parseInt(document.getElementById('set-tts-rate')?.value || '0', 10);
        const soundsEnabled = document.getElementById('set-sounds')?.checked;
        const briefEnabled = document.getElementById('set-daily-brief')?.checked;
        const wakeEnabled = document.getElementById('set-wake-word')?.checked;
        const realtimeEnabled = document.getElementById('set-realtime-stt')?.checked;
        await saveSetting('tts_enabled', !!ttsEnabled);
        await saveSetting('tts_rate', ttsRate);
        await saveSetting('sounds_enabled', !!soundsEnabled);
        try { await api.call('set_daily_brief', !!briefEnabled); } catch (_) {}
        try { await api.call('set_wake_word', !!wakeEnabled); } catch (_) {}
        try { await api.call('set_realtime_stt', !!realtimeEnabled); } catch (_) {}
        AnimationController.play(SettingsAnimations.animTTSToggle, { enabled: !!ttsEnabled });
        setTimeout(() => {
          AnimationController.play(SettingsAnimations.animTTSRate, { rate: ttsRate });
        }, ttsEnabled ? 1100 : 400);
        if (document.getElementById('set-daily-brief')) {
          setTimeout(() => {
            AnimationController.play(SettingsAnimations.animDailyBriefToggle, { enabled: !!briefEnabled });
          }, 1600);
        }
        break;
      }
      case 'micro': {
        const deviceVal = document.getElementById('set-device-index')?.value;
        const deviceIdx = deviceVal === '' || deviceVal == null ? null : parseInt(deviceVal, 10);
        const whisperModel = document.getElementById('set-whisper-model')?.value;
        try { await api.call('set_stt_device_index', deviceIdx ?? ''); } catch (_) {}
        try { await api.call('set_whisper_model', whisperModel); } catch (_) {}
        await saveSetting('stt.device_index', deviceIdx);
        await saveSetting('stt.model', whisperModel);
        AnimationController.play(SettingsAnimations.animDeviceChange, { deviceIndex: deviceIdx });
        if (whisperModel) {
          setTimeout(() => {
            AnimationController.play(SettingsAnimations.animWhisperModelChange, { modelName: whisperModel });
          }, 1200);
        }
        break;
      }
      case 'systeme': {
        const focusEnabled = document.getElementById('set-focus')?.checked;
        const killOllama = document.getElementById('set-kill-ollama')?.checked;
        try { await api.call('set_focus_mode', !!focusEnabled); } catch (_) {}
        if (focusEnabled != null) await saveSetting('focus_mode', !!focusEnabled);
        if (killOllama != null) await saveSetting('kill_ollama_on_exit', !!killOllama);
        if (document.getElementById('set-focus')) {
          AnimationController.play(SettingsAnimations.animFocusMode, { enabled: !!focusEnabled });
        } else {
          styledSettingToast('✓ Paramètres système appliqués', '#4ADE80');
        }
        break;
      }
      default:
        styledSettingToast(`✓ Section ${section} appliquée`, '#4ADE80');
    }
  } catch (e) {
    console.warn('validateSection', e);
    styledSettingToast('Erreur lors de l\'application', '#F87171');
  }

  setTimeout(() => {
    if (btn) {
      btn.textContent = '✓ Appliquer';
      btn.disabled = false;
    }
  }, 2200);
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
      document.getElementById('preset-icon-input').value = preset.icon || '⚡';
      document.getElementById('preset-name-input').value = preset.name || preset.label || presetId;
      document.getElementById('preset-volume').value = preset.volume ?? 50;
      document.getElementById('preset-apps-open').value = (preset.apps_open || []).join(', ');
      document.getElementById('preset-apps-close').value = (preset.apps_close || []).join(', ');
      document.getElementById('preset-message').value = preset.message || '';
    }
  } else {
    document.getElementById('preset-icon-input').value = '⚡';
    document.getElementById('preset-name-input').value = '';
    document.getElementById('preset-volume').value = 50;
    document.getElementById('preset-apps-open').value = '';
    document.getElementById('preset-apps-close').value = '';
    document.getElementById('preset-message').value = '';
  }

  updatePresetPreview();
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
  const icon = document.getElementById('preset-icon-input')?.value || '⚡';
  const previewName = document.getElementById('preset-preview-name');
  const previewIcon = document.getElementById('preset-preview-icon');
  if (previewName) previewName.textContent = name;
  if (previewIcon) previewIcon.textContent = icon;
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
    icon: document.getElementById('preset-icon-input')?.value?.trim() || '⚡',
    volume: parseInt(document.getElementById('preset-volume')?.value || '50', 10),
    apps_open: (document.getElementById('preset-apps-open')?.value || '').split(',').map(s => s.trim()).filter(Boolean),
    apps_close: (document.getElementById('preset-apps-close')?.value || '').split(',').map(s => s.trim()).filter(Boolean),
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
  const inputIcon = document.getElementById('input-agent-icon');
  const inputName = document.getElementById('input-agent-name');
  const selector = document.getElementById('input-agent-selector');

  if (chipIcon) chipIcon.textContent = state._activeAgentIcon;
  if (chipName) chipName.textContent = state._activeAgentName;
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
    loadApiKeys,
    saveApiKey,
    deleteApiKey,
    testApiKey,
    showApiKeyInput,
    exportConversation: () => api.call('export_current_conversation'),
    runMicDiagnostic: () => api.call('run_mic_diagnostic'),
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
