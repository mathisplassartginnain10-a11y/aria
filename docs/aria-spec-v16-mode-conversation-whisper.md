# ARIA — Spec v16 : Choix du mode de conversation (écrit/vocal) + Whisper

## Objectif

À chaque NOUVELLE conversation, ARIA demande à l'utilisateur s'il veut interagir en
mode **écrit** ou **vocal** :
- **Écrit** : comportement actuel (micro disponible mais optionnel, pas de TTS auto)
- **Vocal** : pipeline orienté voix — TTS activé par défaut, transcription via Whisper
  mise en avant, l'utilisateur est invité à parler directement

## Précision technique sur Whisper

Le repo téléchargé est `openai/whisper` (PyTorch, package `whisper`). ARIA utilise déjà
`faster-whisper` (CTranslate2), qui est une **réimplémentation optimisée du même modèle
Whisper** — même architecture, même qualité de transcription, mais 2-4x plus rapide et
moins gourmande en VRAM sur GPU.

**Recommandation** : garder `faster-whisper` comme moteur principal (déjà intégré et
fonctionnel avec le fix multi-sample-rate B06), car migrer vers `openai-whisper` pur
ferait perdre l'optimisation GPU sans gain de qualité.

Le dossier "voix IA" (zip `whisper-main.zip`) peut servir pour :
- Référence du code officiel si besoin de comparer le comportement
- Les modèles `.pt` qu'il contient sont compatibles avec `faster-whisper` après
  conversion via `ct2-transformers-converter` (si jamais un modèle spécifique manque
  dans le cache faster-whisper)

Cette spec implémente donc le choix écrit/vocal en réutilisant `faster-whisper`
(déjà en place), avec activation/configuration différente selon le mode choisi.

---

## Flux UI — sélection au début de chaque conversation

```
Nouvelle conversation créée
  │
  ▼
┌─────────────────────────────────────┐
│         A R I A                       │
│                                        │
│   Comment veux-tu échanger ?           │
│                                        │
│   [ 💬 Écrit ]      [ 🎙️ Vocal ]       │
│                                        │
└─────────────────────────────────────┘
  │                         │
  ▼                         ▼
Mode écrit                Mode vocal
- TTS off par défaut       - TTS on par défaut
- Micro disponible          - Micro activé immédiatement
  mais pas auto              - Message d'accueil parlé
- Input texte en focus       - Input texte présent mais
                                micro mis en avant
```

---

## Implémentation

### État de conversation — stocké par conversation

```python
# memory_engine.py — ajout

def set_conversation_mode(conv_id: str, mode: str) -> None:
    """mode: 'ecrit' | 'vocal'"""
    conv = _get_conversation(conv_id)
    conv['mode'] = mode
    save_current_conversation()

def get_conversation_mode(conv_id: str) -> str | None:
    conv = _get_conversation(conv_id)
    return conv.get('mode')  # None si pas encore choisi
```

### UI — modal de sélection à la création d'une conversation

```html
<div id="mode-select-overlay" class="glass" style="display:none;position:fixed;inset:0;z-index:9000;align-items:center;justify-content:center;flex-direction:column;gap:24px;background:rgba(0,0,0,0.4);backdrop-filter:blur(8px)">
  <div class="glass" style="padding:32px 40px;border-radius:24px;display:flex;flex-direction:column;align-items:center;gap:20px;max-width:360px">
    <div id="aria-logo-mode-select" style="transform:scale(1.3)">
      <!-- réutilise le SVG logo JARVIS v14, version statique -->
    </div>
    <div style="font-size:16px;color:var(--text);text-align:center">
      Comment veux-tu échanger avec ARIA ?
    </div>
    <div style="display:flex;gap:12px;width:100%">
      <button class="glass-btn" style="flex:1;padding:16px;display:flex;flex-direction:column;align-items:center;gap:8px" onclick="aria.selectConversationMode('ecrit')">
        <span style="font-size:24px">💬</span>
        <span style="font-size:13px">Écrit</span>
      </button>
      <button class="glass-btn" style="flex:1;padding:16px;display:flex;flex-direction:column;align-items:center;gap:8px" onclick="aria.selectConversationMode('vocal')">
        <span style="font-size:24px">🎙️</span>
        <span style="font-size:13px">Vocal</span>
      </button>
    </div>
  </div>
</div>
```

```javascript
// Appelé à la création d'une nouvelle conversation (avant d'afficher le chat)
showModeSelector() {
  document.getElementById('mode-select-overlay').style.display = 'flex';
},

async selectConversationMode(mode) {
  await this.api('set_conversation_mode', this.currentConversationId, mode);
  document.getElementById('mode-select-overlay').style.display = 'none';

  this.conversationMode = mode;

  if (mode === 'vocal') {
    // Active le TTS pour cette conversation
    this.ttsEnabledForSession = true;
    // Active le micro automatiquement
    this.startMic();
    // Message d'accueil
    const greeting = "Mode vocal activé. Je t'écoute.";
    this.addAriaBubble(greeting);
    await this.api('speak_text', greeting);
    // Met en avant le bouton micro visuellement
    document.getElementById('mic-btn')?.classList.add('mic-emphasized');
  } else {
    this.ttsEnabledForSession = false;
    document.getElementById('text-input')?.focus();
  }
},

// Au chargement d'une conversation EXISTANTE qui a déjà un mode :
async loadConversation(convId) {
  // ... code existant de chargement ...
  const mode = await this.api('get_conversation_mode', convId);
  if (!mode) {
    this.showModeSelector();
  } else {
    this.conversationMode = mode;
    this.ttsEnabledForSession = (mode === 'vocal');
    if (mode === 'vocal') {
      document.getElementById('mic-btn')?.classList.add('mic-emphasized');
    } else {
      document.getElementById('mic-btn')?.classList.remove('mic-emphasized');
    }
  }
}
```

### CSS — bouton micro mis en avant en mode vocal

```css
.mic-emphasized {
  animation: micEmphasize 2s ease-in-out infinite;
  box-shadow: 0 0 0 0 rgba(108,142,255,0.4) !important;
}
@keyframes micEmphasize {
  0%, 100% { box-shadow: 0 0 0 0 rgba(108,142,255,0.3); transform: scale(1); }
  50%      { box-shadow: 0 0 0 8px rgba(108,142,255,0); transform: scale(1.04); }
}
```

### ui.py — fonctions Python

```python
def set_conversation_mode(self, conv_id: str, mode: str) -> None:
    import memory_engine as _me
    _me.set_conversation_mode(conv_id, mode)
    logger.info("Mode conversation '%s' = %s", conv_id, mode)

def get_conversation_mode(self, conv_id: str) -> str | None:
    import memory_engine as _me
    return _me.get_conversation_mode(conv_id)

def speak_text(self, text: str) -> None:
    import tts
    tts.speak(text)
```

### llm.py — comportement TTS conditionné par le mode

```python
def _speak_response(text: str) -> None:
    """Parle uniquement si TTS activé globalement OU si la conversation est en mode vocal."""
    import memory_engine as _me
    import tts

    global_tts = _config.get('tts_enabled', False)
    conv_mode = _me.get_conversation_mode(_me.get_current_conversation_id())

    if global_tts or conv_mode == 'vocal':
        tts.speak(text)
```

### Comportement micro en mode vocal — boucle conversationnelle simplifiée

En mode vocal, après chaque réponse d'ARIA (TTS terminé), le micro se réactive
automatiquement pour la prochaine entrée — sans nécessiter F24/Ctrl+Shift+A à chaque
fois (mais ces raccourcis restent utilisables pour mettre en pause).

```javascript
// Appelé quand le TTS se termine (callback existant onTTSEnd ou équivalent)
onTTSFinished() {
  if (this.conversationMode === 'vocal' && !this.micPaused) {
    this.startMic();  // réactive automatiquement le micro
  }
}
```

```python
# tts.py — callback de fin de lecture
def speak(text: str) -> None:
    # ... code existant ...
    # À la fin de la lecture :
    import ui as _ui
    if _ui._instance:
        _ui._instance._js('aria.onTTSFinished();')
```

---

## Config

```yaml
# Pas de changement global nécessaire — le mode est par conversation (stocké dans
# memory_engine), pas dans config.yaml. tts_enabled global reste le défaut pour le
# mode écrit (false par défaut, l'utilisateur peut l'activer manuellement).
```

---

## Prompt Cursor

> Implémente le choix du mode de conversation (écrit/vocal) à chaque nouvelle
> conversation, en réutilisant le pipeline `faster-whisper` déjà en place (pas de
> migration vers `openai-whisper` — faster-whisper est une réimplémentation optimisée
> du même modèle Whisper).
>
> 1. Dans memory_engine.py, ajoute `set_conversation_mode(conv_id, mode)` et
> `get_conversation_mode(conv_id)` qui stockent/lisent un champ `mode` ('ecrit' | 'vocal')
> sur l'objet conversation.
>
> 2. Dans ui.py, ajoute :
> - `set_conversation_mode(conv_id, mode)` → appelle memory_engine
> - `get_conversation_mode(conv_id)` → retourne le mode ou None
> - `speak_text(text)` → appelle tts.speak(text) directement
>
> 3. Dans ui/index.html :
> - Ajoute l'overlay `#mode-select-overlay` comme spécifié (modal avec logo + 2 boutons
>   "💬 Écrit" / "🎙️ Vocal")
> - `showModeSelector()` : affiche l'overlay
> - `selectConversationMode(mode)` : enregistre le mode via l'API, ferme l'overlay, et
>   si mode === 'vocal' : active `ttsEnabledForSession`, démarre le micro
>   (`this.startMic()`), affiche+parle un message d'accueil "Mode vocal activé. Je
>   t'écoute.", et ajoute la classe CSS `mic-emphasized` au bouton micro. Si mode ===
>   'ecrit' : `ttsEnabledForSession = false`, focus sur le champ texte.
> - À la création d'une NOUVELLE conversation, appelle `showModeSelector()` avant
>   d'afficher le chat
> - Au CHARGEMENT d'une conversation existante, vérifie `get_conversation_mode(convId)` :
>   si null, affiche le sélecteur ; sinon applique le mode (TTS, classe CSS micro) sans
>   redemander
> - Ajoute la classe CSS `.mic-emphasized` avec l'animation `micEmphasize` (pulsation
>   douce, comme spécifié)
> - Ajoute `onTTSFinished()` : si `conversationMode === 'vocal'` et le micro n'est pas en
>   pause manuelle, relance automatiquement le micro (`this.startMic()`)
>
> 4. Dans llm.py, modifie `_speak_response(text)` : parle si `config.get('tts_enabled', False)`
> globalement activé, OU si `memory_engine.get_conversation_mode(current_conv_id) == 'vocal'`.
>
> 5. Dans tts.py, à la fin de `speak()` (après la lecture complète), appelle via
> `ui._instance._js('aria.onTTSFinished();')` pour déclencher la réactivation auto du
> micro en mode vocal.
>
> Ne touche PAS à stt.py (le pipeline faster-whisper existant reste inchangé) — cette
> feature ne fait que conditionner QUAND le TTS/micro s'activent automatiquement, pas
> COMMENT la transcription fonctionne.
>
> Modifie memory_engine.py, ui.py, ui/index.html, llm.py, tts.py.
