# Assistant Vocal — Spec v11 : Design Premium "Less AI, More Human"

## Philosophie
Inspiré de Claude.ai, Perplexity, Linear App.
- Beaucoup d'espace blanc (négatif)
- Typographie qui respire
- Couleurs sobres, accents rares
- Interactions subtiles, pas d'effets criards
- L'orbe existe mais est petit et discret
- L'interface ressemble à un vrai logiciel pro, pas à un screensaver

## Palette de couleurs (thème default "Slate")

```css
:root {
  --bg-primary:    #0C0C0F;   /* fond principal */
  --bg-secondary:  #111116;   /* panneaux */
  --bg-tertiary:   #17171E;   /* cards, inputs */
  --bg-hover:      #1E1E28;   /* hover states */
  --border:        rgba(255,255,255,0.06);  /* bordures très subtiles */
  --border-focus:  rgba(255,255,255,0.12);
  --accent:        #6C8EFF;   /* bleu perplexity — sobre */
  --accent-soft:   rgba(108,142,255,0.12);
  --accent2:       #A78BFA;   /* violet doux */
  --text-primary:  #F1F1F3;
  --text-secondary:#8B8B9E;
  --text-tertiary: #55555F;
  --success:       #4ADE80;
  --warning:       #FBBF24;
  --error:         #F87171;
  --orb-color:     #6C8EFF;
}
```

## Thèmes alternatifs
- **Slate** (défaut) : bleu/violet sobre sur noir profond
- **Warm** : ambre/orange doux sur brun très sombre
- **Forest** : vert sauge sur noir verdâtre
- **Rose** : rose/mauve sur noir bleuté
- **Mono** : blanc pur sur noir, zéro couleur
- **Contrast** : blanc sur noir parfait, accessibilité max

---

## LAYOUT — sidebar gauche + zone principale

```
┌──────────┬────────────────────────────────────────────┐
│          │  Header minimal (40px)                      │
│ SIDEBAR  ├────────────────────────────────────────────┤
│  (260px) │                                             │
│          │  Zone conversation (flex:1)                 │
│  - Orbe  │  Messages espacés, bulles propres           │
│  - Stats │                                             │
│  - Nav   │                                             │
│  - Prsts ├────────────────────────────────────────────┤
│          │  Input zone (72px)                          │
└──────────┴────────────────────────────────────────────┘
```

---

## SIDEBAR (260px, fixe)

```css
#sidebar {
  width: 260px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 20px 0;
  flex-shrink: 0;
}
```

### Section haut — identité
```html
<div id="sidebar-top" style="padding: 0 20px 20px; border-bottom: 1px solid var(--border)">
  <!-- Orbe compact -->
  <canvas id="orb-canvas" width="220" height="140"></canvas>
  <!-- Nom + statut -->
  <div style="text-align:center; margin-top: 12px">
    <div id="assistant-name" style="font-size:15px; font-weight:600; color:var(--text-primary); letter-spacing:0.5px">ARIA</div>
    <div id="status-text" style="font-size:11px; color:var(--text-secondary); margin-top:3px">En veille</div>
  </div>
</div>
```

### Orbe canvas (140px de hauteur, 220px large)
- Orbe centré, rayon 30px (idle) → 45px (actif)
- Glow doux, pas de particules en excès
- 3 cercles concentriques très fins et subtils
- Waveform linéaire sous l'orbe (60px largeur, 30px hauteur)
- Couleur réactive : --accent au repos, blanc à fort volume

### Section milieu — navigation
```html
<nav id="sidebar-nav" style="padding: 12px 12px; flex:1">
  <div class="nav-item active" onclick="">
    <i>💬</i> <span>Conversation</span>
  </div>
  <div class="nav-item" onclick="aria.showHistory()">
    <i>🕐</i> <span>Historique</span>
  </div>
  <div class="nav-item" onclick="aria.showSettings()">
    <i>⚙️</i> <span>Paramètres</span>
  </div>
</nav>
```

```css
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
  margin-bottom: 2px;
}
.nav-item:hover { background: var(--bg-hover); color: var(--text-primary); }
.nav-item.active { background: var(--accent-soft); color: var(--accent); }
```

### Section bas — presets
```html
<div id="sidebar-presets" style="padding: 12px; border-top: 1px solid var(--border)">
  <div style="font-size:10px; color:var(--text-tertiary); letter-spacing:1px; margin-bottom:8px; padding: 0 4px">MODES</div>
  <div class="preset-row" onclick="aria.activatePreset('vol')">✈ Vol</div>
  <div class="preset-row" onclick="aria.activatePreset('etude')">📚 Étude</div>
  <div class="preset-row" onclick="aria.activatePreset('gaming')">🎮 Gaming</div>
  <div class="preset-row" onclick="aria.activatePreset('detente')">🎵 Détente</div>
  <div class="preset-row" onclick="aria.activatePreset('nuit')">🌙 Nuit</div>
</div>
```

```css
.preset-row {
  padding: 7px 12px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
  margin-bottom: 1px;
}
.preset-row:hover { background: var(--bg-hover); color: var(--text-primary); }
.preset-row.active { color: var(--accent); background: var(--accent-soft); }
```

---

## HEADER (40px)

```css
#header {
  height: 40px;
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  flex-shrink: 0;
}
```

Contenu :
- Gauche : breadcrumb "ARIA / Conversation" en 12px text-tertiary
- Centre : rien (espace vide)
- Droite : météo + heure en 11px text-tertiary | bouton mic (24px, sobre) | bouton settings (24px)

```css
.header-btn {
  width: 28px; height: 28px;
  border-radius: 6px;
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px;
  transition: all 0.15s;
}
.header-btn:hover { background: var(--bg-hover); border-color: var(--border-focus); color: var(--text-primary); }
.header-btn.active { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); }
```

---

## ZONE CONVERSATION

```css
#chat-zone {
  flex: 1;
  overflow-y: auto;
  padding: 32px 40px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
```

### Message vide (état initial)
```html
<div id="empty-state" style="flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:12px; color:var(--text-tertiary)">
  <div style="font-size:32px; opacity:0.4">◎</div>
  <div style="font-size:14px">Comment puis-je t'aider ?</div>
  <div style="font-size:12px; opacity:0.6">Parle ou écris un message</div>
</div>
```

### Bulles utilisateur
```css
.bubble-user {
  align-self: flex-end;
  max-width: 65%;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: 16px 16px 4px 16px;
  padding: 12px 16px;
  font-size: 14px;
  color: var(--text-primary);
  line-height: 1.6;
  animation: slideIn 0.2s ease-out;
}
```

### Bulles ARIA
```css
.bubble-aria {
  align-self: flex-start;
  max-width: 75%;
  display: flex;
  gap: 12px;
  align-items: flex-start;
  animation: slideIn 0.2s ease-out;
}

.bubble-aria-avatar {
  width: 28px; height: 28px;
  border-radius: 8px;
  background: var(--accent-soft);
  border: 1px solid rgba(108,142,255,0.2);
  display: flex; align-items: center; justify-content: center;
  font-size: 12px;
  flex-shrink: 0;
  color: var(--accent);
}

.bubble-aria-content {
  background: transparent;
  font-size: 14px;
  color: var(--text-primary);
  line-height: 1.7;
  padding-top: 4px;
}
```

### Timestamps
```css
.bubble-time {
  font-size: 10px;
  color: var(--text-tertiary);
  margin-top: 4px;
  text-align: right;
}
```

### Animation d'entrée
```css
@keyframes slideIn {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

### Curseur de streaming
```css
.streaming-cursor {
  display: inline-block;
  width: 2px; height: 16px;
  background: var(--accent);
  margin-left: 2px;
  vertical-align: text-bottom;
  animation: blink 1s step-end infinite;
}
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
```

---

## INPUT ZONE (72px)

```css
#input-zone {
  padding: 12px 20px;
  background: var(--bg-primary);
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

#text-input {
  flex: 1;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 16px;
  color: var(--text-primary);
  font-family: inherit;
  font-size: 14px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
  resize: none;
  height: 48px;
  line-height: 1.4;
}

#text-input::placeholder { color: var(--text-tertiary); }

#text-input:focus {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px rgba(108,142,255,0.08);
}

#send-btn {
  width: 40px; height: 40px;
  border-radius: 10px;
  background: var(--accent);
  border: none;
  color: white;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 15px;
  transition: all 0.15s;
  flex-shrink: 0;
}
#send-btn:hover { background: #7B9FFF; transform: scale(1.03); }
#send-btn:disabled { background: var(--bg-tertiary); color: var(--text-tertiary); transform: none; cursor: not-allowed; }
```

---

## PANNEAU PARAMÈTRES (complet et persistant)

Slide depuis la droite (400px), remplace toute la zone droite.

### Sections :

**1. Apparence**
- Sélecteur de thème : grille 3x2 de swatches colorées (Slate/Warm/Forest/Rose/Mono/Contrast)
- Slider opacité fenêtre (70-100%)
- Toggle scan lines
- Toggle réduction mouvement

**2. Voix & Audio**
- Dropdown voix TTS (Denise/Henri/Eloise/Vivienne)
- Slider vitesse TTS (-50% à +50%) avec aperçu en temps réel
- Slider volume TTS (0-100%)
- Toggle sons d'ambiance
- Bouton "Tester la voix"

**3. Assistant**
- Champ nom (défaut "ARIA")
- Dropdown langue (FR/EN/DE)
- Slider longueur des réponses (Courte/Normale/Détaillée)
- Toggle mémoire persistante
- Bouton "Voir la mémoire"
- Bouton "Effacer la mémoire"
- Bouton "Effacer l'historique"

**4. Modèles**
- Liste déroulante modèle rapide (qwen3:4b)
- Liste déroulante modèle moyen (qwen3:8b)
- Liste déroulante modèle lourd (qwen3:14b)
- Liste déroulante modèle code (qwen2.5-coder:7b)
- Toggle routage automatique

**5. Micro & STT**
- Dropdown périphérique micro (liste des micros disponibles)
- Slider seuil de silence (100-2000)
- Slider durée silence (0.5-3s)
- Toggle activation automatique au démarrage
- Bouton "Tester le micro" (barre de niveau en temps réel)

**6. Raccourcis**
- Affichage touche active (F24)
- Affichage Ctrl+Shift+A (test)
- Bouton pour changer le raccourci principal

**7. Système**
- Toggle démarrage automatique Windows
- Toggle toujours visible
- Dropdown position (bas-droite, etc.)
- Bouton "Ouvrir config.yaml"
- Bouton "Voir les logs"
- Version + info build

### Persistance des paramètres
Tous les changements sont sauvegardés **immédiatement** dans `data/ui_state.json` via `window.pywebview.api.save_settings(JSON.stringify(settings))`. Au rechargement, tous les paramètres sont restaurés via `load_settings()`.

```javascript
// Pattern de sauvegarde immédiate pour chaque contrôle
document.getElementById('tts-rate').addEventListener('input', function() {
  aria.settings.tts_rate = this.value;
  aria.saveSettings();
  // Appliquer en temps réel
  window.pywebview.api.set_tts_rate(this.value);
});
```

---

## Polices
```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 14px;
  line-height: 1.5;
}
```

---

## Body background
```css
body {
  background: var(--bg-primary);
  color: var(--text-primary);
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: row;  /* sidebar à gauche, main à droite */
}

#main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
```

---

## Toasts
Position bas-gauche (dans la sidebar au-dessus des presets ou bas-centre), style sobre :
```css
.toast {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-focus);
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 12px;
  color: var(--text-primary);
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  animation: toastIn 0.25s ease-out;
}
.toast.success { border-left: 3px solid var(--success); }
.toast.error   { border-left: 3px solid var(--error); }
.toast.warning { border-left: 3px solid var(--warning); }
.toast.info    { border-left: 3px solid var(--accent); }
```

---

## Scroll subtil
```css
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-focus); border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-tertiary); }
```

---

## Prompt Cursor

> Rewrite ui/index.html completely from scratch with the premium "Less AI, More Human" design from this spec. This must look like Claude.ai or Perplexity — clean, spacious, professional. NOT a sci-fi screensaver.
>
> LAYOUT: sidebar (260px fixed left) + main area (flex:1 right). Sidebar has: compact orb canvas (140px height), nav items, preset rows. Main has: header (40px) + conversation zone (flex:1) + input zone (72px).
>
> DESIGN RULES:
> - Font: Inter from Google Fonts + system fallback
> - Colors: CSS custom properties from the spec (--bg-primary #0C0C0F, --accent #6C8EFF, etc.)
> - Borders: always rgba(255,255,255,0.06), never solid opaque
> - No glitch effects, no scan lines, no particles outside the orb canvas
> - Lots of whitespace — padding 32px 40px in chat zone
> - Bubbles: user = right-aligned card, ARIA = left-aligned with small avatar icon
> - Empty state shown when no messages: centered "◎" icon + "Comment puis-je t'aider ?"
>
> ORB CANVAS (220x140px in sidebar):
> - Small orb radius 28-42px, smooth lerp
> - 2 subtle rotating arcs (very thin, low opacity)
> - Linear waveform below orb (not circular)
> - Color: --accent, barely glowing
>
> SETTINGS PANEL (400px, slides from right over main area):
> 7 sections as described: Apparence, Voix & Audio, Assistant, Modèles, Micro & STT, Raccourcis, Système
> ALL settings saved immediately to ui_state.json via pywebview.api.save_settings()
> ALL settings restored on load via pywebview.api.load_settings()
>
> THEMES: 6 themes via CSS custom properties on body (Slate/Warm/Forest/Rose/Mono/Contrast)
>
> PRESERVE ALL JS API:
> show(), hide(), setStatus(state), updateWaveform(rms), addUserBubble(text), appendToken(token), finalizeMessage(), showToast(msg, type, duration), showError(text), updateWeather(text), setModel(name)
>
> PRESERVE ALL pywebview.api calls:
> quit_aria, toggle_activation, activate_preset, send_text, save_settings, load_settings, clear_history, open_file, set_tts_rate, set_tts_volume, set_voice
>
> INPUT: rounded textarea (not input), Enter sends, Shift+Enter = newline
> QUIT: confirmation modal on window close or ✕ button
>
> Generate complete single-file index.html. Use Inter font. Make it look like a premium product. No placeholders.
