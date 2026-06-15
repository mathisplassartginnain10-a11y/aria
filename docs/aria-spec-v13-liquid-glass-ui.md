# ARIA — Spec v13 : UI "Liquid Glass" façon iOS 27 + arrière-plans personnalisables

## Inspiration
iOS 26/27 "Liquid Glass" : matériau translucide dynamique qui réfracte, se déforme légèrement
au scroll/interaction, avec un slider transparent ↔ opaque, texte toujours sur couche solide
au-dessus du verre, animations de morphing entre éléments (GlassEffectContainer).

ARIA doit ressembler à une app iOS native avec ce matériau, tournant sur Windows.

---

## Principe du matériau "Glass"

Chaque panneau (sidebar, header, bulles, settings, modals) est un calque de verre :

```css
.glass {
  background: rgba(255,255,255,0.06);  /* ajusté par slider transparence */
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border: 0.5px solid rgba(255,255,255,0.12);
  border-radius: 20px;
  box-shadow:
    0 1px 1px rgba(255,255,255,0.08) inset,
    0 8px 32px rgba(0,0,0,0.25);
  transition: background 0.3s, backdrop-filter 0.3s;
}
```

Le texte ne repose jamais directement sur le verre — toujours sur une sous-couche
`background: var(--surface-solid)` avec opacité 0.85+ pour la lisibilité.

---

## Slider Transparence (paramètres → Apparence)

Remplace le simple "opacité fenêtre" par un slider 0-100 qui contrôle le `backdrop-filter` :

```css
:root {
  --glass-blur: 24px;       /* 0 = opaque total, 40px = très transparent */
  --glass-alpha: 0.06;       /* 0.02 = quasi invisible, 0.18 = presque opaque */
}
```

JS :
```javascript
setGlassIntensity(value) {
  // value: 0 (opaque) à 100 (très transparent)
  const blur = 4 + (value / 100) * 36;       // 4px → 40px
  const alpha = 0.18 - (value / 100) * 0.16; // 0.18 → 0.02
  document.documentElement.style.setProperty('--glass-blur', `${blur}px`);
  document.documentElement.style.setProperty('--glass-alpha', alpha);
}
```

Slider dans Apparence :
```html
<div class="setting-row">
  <label>Intensité Liquid Glass</label>
  <input type="range" id="set-glass-intensity" min="0" max="100" value="60"
    oninput="aria.setGlassIntensity(this.value); aria.saveSettings()">
</div>
```

---

## Fonds d'écran personnalisables

### Sources de fond
1. **Couleur unie** — sélecteur de couleur
2. **Dégradé** — 2 couleurs + angle, comme les fonds iOS dynamiques
3. **Image personnalisée** — upload depuis le PC, stockée dans `data/wallpapers/`
4. **Fonds animés intégrés** — quelques presets type "Aurora", "Nébuleuse", "Dégradé doux"
5. **Live wallpaper léger** — gradient animé en CSS (mesh gradient lent)

### Structure de fond
```html
<div id="wallpaper-layer" style="position:fixed;inset:0;z-index:-1;overflow:hidden">
  <div id="wallpaper-image" style="position:absolute;inset:0;background-size:cover;background-position:center;filter:blur(0px) brightness(0.9)"></div>
  <div id="wallpaper-overlay" style="position:absolute;inset:0;background:rgba(0,0,0,0.15)"></div>
</div>
```

Tout le reste de l'UI (sidebar, chat, header) est en `.glass` au-dessus de ce fond — c'est
ce qui crée l'effet "Liquid Glass" : le fond se voit à travers le flou.

### Presets de fond intégrés (gradients CSS, pas d'images lourdes)
```css
.wp-aurora    { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 35%, #0f3460 70%, #533483 100%); }
.wp-sunset    { background: linear-gradient(135deg, #2d1b2e 0%, #5e2750 40%, #a8456b 75%, #e8845a 100%); }
.wp-forest    { background: linear-gradient(135deg, #0b1e14 0%, #163d2c 50%, #1f5c3d 100%); }
.wp-midnight  { background: linear-gradient(135deg, #050510 0%, #0a0a20 50%, #14143a 100%); }
.wp-mono      { background: #0C0C0F; }
.wp-mesh      { background:
    radial-gradient(at 20% 30%, rgba(108,142,255,0.25) 0px, transparent 50%),
    radial-gradient(at 80% 20%, rgba(167,139,250,0.2) 0px, transparent 50%),
    radial-gradient(at 50% 80%, rgba(74,222,128,0.15) 0px, transparent 50%),
    #0C0C0F;
  }
```

### Animation mesh gradient lente (live wallpaper léger)
```css
.wp-mesh-animated {
  background: radial-gradient(at 20% 30%, rgba(108,142,255,0.25) 0px, transparent 50%),
              radial-gradient(at 80% 20%, rgba(167,139,250,0.2) 0px, transparent 50%),
              radial-gradient(at 50% 80%, rgba(74,222,128,0.15) 0px, transparent 50%),
              #0C0C0F;
  background-size: 200% 200%;
  animation: meshShift 30s ease-in-out infinite alternate;
}
@keyframes meshShift {
  0%   { background-position: 0% 0%, 100% 0%, 50% 100%; }
  100% { background-position: 30% 20%, 70% 30%, 60% 80%; }
}
```

### Upload de fond personnalisé
```javascript
async uploadWallpaper(file) {
  const b64 = await this.fileToBase64(file);
  const path = await this.api('save_wallpaper', b64, file.name);
  this.setWallpaper('custom', path);
}

setWallpaper(type, path) {
  const layer = document.getElementById('wallpaper-image');
  layer.className = '';
  if (type === 'custom') {
    layer.style.background = `url("${path}") center/cover no-repeat`;
  } else {
    layer.style.background = '';
    layer.className = `wp-${type}`;
  }
  this.saveSettings();
}
```

Dans ui.py :
```python
def save_wallpaper(self, base64_data: str, filename: str) -> str:
    import base64, app_paths
    from pathlib import Path
    wp_dir = app_paths.data_dir() / "wallpapers"
    wp_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix or '.jpg'
    out_path = wp_dir / f"custom{ext}"
    out_path.write_bytes(base64.b64decode(base64_data))
    return f"file:///{out_path.as_posix()}"
```

### Section Paramètres → Apparence → Fond d'écran
```html
<div class="settings-section">
  <div class="settings-title">Fond d'écran</div>
  <div class="wallpaper-grid">
    <div class="wp-thumb wp-aurora" onclick="aria.setWallpaper('aurora')"></div>
    <div class="wp-thumb wp-sunset" onclick="aria.setWallpaper('sunset')"></div>
    <div class="wp-thumb wp-forest" onclick="aria.setWallpaper('forest')"></div>
    <div class="wp-thumb wp-midnight" onclick="aria.setWallpaper('midnight')"></div>
    <div class="wp-thumb wp-mesh-animated" onclick="aria.setWallpaper('mesh-animated')"></div>
    <div class="wp-thumb wp-mono" onclick="aria.setWallpaper('mono')"></div>
  </div>
  <label class="settings-btn" style="text-align:center;cursor:pointer">
    📷 Choisir une image personnelle
    <input type="file" accept="image/*" style="display:none" onchange="aria.uploadWallpaper(this.files[0])">
  </label>
</div>
```

```css
.wallpaper-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 8px; margin-bottom: 12px; }
.wp-thumb { height: 60px; border-radius: 12px; cursor: pointer; border: 2px solid transparent; transition: border-color 0.15s; }
.wp-thumb:hover, .wp-thumb.active { border-color: var(--accent); }
```

---

## Composants Liquid Glass détaillés

### Sidebar
```css
#sidebar {
  background: rgba(20,20,28, var(--glass-alpha));
  backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  border-right: 0.5px solid rgba(255,255,255,0.1);
}
```

### Header
```css
#header {
  background: rgba(20,20,28, calc(var(--glass-alpha) + 0.02));
  backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  border-bottom: 0.5px solid rgba(255,255,255,0.08);
}
```

### Bulles de conversation
Les bulles ARIA flottent en glass léger ; les bulles utilisateur sont en glass accent :

```css
.bubble-user {
  background: rgba(108,142,255, 0.18);
  backdrop-filter: blur(20px) saturate(160%);
  border: 0.5px solid rgba(108,142,255,0.3);
  border-radius: 20px 20px 6px 20px;
  box-shadow: 0 1px 0 rgba(255,255,255,0.1) inset, 0 4px 16px rgba(0,0,0,0.15);
}

.bubble-aria-wrap .bubble-content {
  background: rgba(255,255,255, 0.05);
  backdrop-filter: blur(16px) saturate(150%);
  border: 0.5px solid rgba(255,255,255,0.08);
  border-radius: 6px 20px 20px 20px;
  padding: 14px 18px;
}
```

### Boutons et pills (effet "morph" au clic)
```css
.glass-btn {
  background: rgba(255,255,255,0.08);
  backdrop-filter: blur(20px) saturate(180%);
  border: 0.5px solid rgba(255,255,255,0.12);
  border-radius: 14px;
  transition: all 0.25s cubic-bezier(0.34, 1.2, 0.64, 1);
}
.glass-btn:hover {
  background: rgba(255,255,255,0.14);
  transform: scale(1.03);
}
.glass-btn:active {
  transform: scale(0.97);
  background: rgba(255,255,255,0.18);
}
```

### Panneau Paramètres (slide + glass morph)
```css
#settings-panel {
  background: rgba(18,18,26, calc(var(--glass-alpha) + 0.08));
  backdrop-filter: blur(40px) saturate(180%);
  border-left: 0.5px solid rgba(255,255,255,0.1);
  box-shadow: -8px 0 40px rgba(0,0,0,0.3);
}
```

### Input zone — "Dynamic Island" style
Le champ de saisie + bouton micro + bouton envoyer forment un seul bloc glass arrondi en pilule,
qui s'agrandit légèrement quand on tape (comme la Dynamic Island) :

```css
#input-zone {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(255,255,255,0.07);
  backdrop-filter: blur(28px) saturate(180%);
  border: 0.5px solid rgba(255,255,255,0.12);
  border-radius: 26px;
  padding: 8px 8px 8px 18px;
  margin: 12px 20px;
  transition: border-radius 0.3s, transform 0.2s;
  box-shadow: 0 4px 24px rgba(0,0,0,0.2);
}

#input-zone:focus-within {
  border-radius: 20px;
  transform: scale(1.01);
  border-color: rgba(108,142,255,0.4);
}

#text-input {
  background: transparent;
  border: none;
  flex: 1;
}

#send-btn {
  background: var(--accent);
  border-radius: 50%;
  width: 38px; height: 38px;
}
```

---

## Animations "Liquid" (morphing)

### Transition entre états du bouton micro (idle → listening → speaking)
```css
#mic-btn {
  background: rgba(255,255,255,0.08);
  backdrop-filter: blur(20px);
  border-radius: 50%;
  transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

#mic-btn.listening {
  background: rgba(108,142,255,0.25);
  box-shadow: 0 0 0 0 rgba(108,142,255,0.4);
  animation: glassPulse 2s ease-in-out infinite;
}

@keyframes glassPulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(108,142,255,0.3); }
  50%      { box-shadow: 0 0 0 12px rgba(108,142,255,0); }
}

#mic-btn.speaking {
  background: rgba(74,222,128,0.25);
  border-color: rgba(74,222,128,0.4);
}
```

### Apparition des bulles (morph depuis le bas)
```css
@keyframes glassMorphIn {
  from {
    opacity: 0;
    transform: translateY(20px) scale(0.92);
    backdrop-filter: blur(0px);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
    backdrop-filter: blur(16px);
  }
}
.bubble-user, .bubble-aria-wrap {
  animation: glassMorphIn 0.4s cubic-bezier(0.34, 1.4, 0.64, 1);
}
```

### Toasts façon notification iOS (glass pill en haut)
```css
.toast {
  background: rgba(40,40,50,0.5);
  backdrop-filter: blur(30px) saturate(200%);
  border: 0.5px solid rgba(255,255,255,0.15);
  border-radius: 18px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.3);
  animation: toastDropIn 0.4s cubic-bezier(0.34, 1.4, 0.64, 1);
}
@keyframes toastDropIn {
  from { opacity: 0; transform: translateY(-20px) scale(0.9); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}
```

---

## Modal de fermeture (glass overlay)
```css
#quit-modal {
  background: rgba(0,0,0,0.4);
  backdrop-filter: blur(8px);
}
#quit-modal > div {
  background: rgba(30,30,38,0.7);
  backdrop-filter: blur(40px) saturate(180%);
  border: 0.5px solid rgba(255,255,255,0.15);
  border-radius: 24px;
  box-shadow: 0 16px 48px rgba(0,0,0,0.4);
}
```

---

## Couleurs et accessibilité

Comme sur iOS, le texte ne touche jamais directement le verre transparent :
- Tout texte important repose sur une `bubble-content` ou `bubble-user` qui a son propre fond solide à 80%+ d'opacité indépendamment du slider glass
- Le slider glass affecte uniquement les CONTAINERS (sidebar, header, settings, input-zone), jamais les bulles de texte
- Contraste minimum maintenu : `--text` reste toujours #F1F1F3 sur fond sombre

---

## Prompt Cursor

> Rewrite the visual styling of ui/index.html to implement a "Liquid Glass" design system inspired by iOS 26/27. Apply ALL of the following:
>
> 1. CUSTOMIZABLE WALLPAPER LAYER:
> - Add `#wallpaper-layer` as a fixed full-screen background div BEHIND everything (z-index: -1)
> - Add 6 wallpaper presets as CSS classes: wp-aurora, wp-sunset, wp-forest, wp-midnight, wp-mono, wp-mesh-animated (gradients as specified in this spec)
> - Add wp-mesh-animated with the meshShift keyframe animation (30s loop)
> - Add a "Fond d'écran" section in Settings → Apparence with a 3x3 grid of clickable preset thumbnails + a file upload button for custom wallpaper images
> - uploadWallpaper() converts to base64, calls pywebview.api.save_wallpaper(), sets the background
> - setWallpaper(type, path) applies the chosen background and saves to settings
> - In ui.py, add save_wallpaper(base64_data, filename) that writes to data/wallpapers/ and returns a file:// URL
>
> 2. LIQUID GLASS MATERIAL — apply to ALL these elements:
> - #sidebar: rgba(20,20,28, var(--glass-alpha)) + backdrop-filter blur(var(--glass-blur)) saturate(180%)
> - #header: same with slightly higher alpha
> - #settings-panel: blur(40px) saturate(180%), higher alpha
> - #input-zone: redesign as a single rounded pill (border-radius 26px) containing textarea + mic button + send button, with glass background, that slightly grows (border-radius shrinks to 20px, scale 1.01) on focus-within
> - .bubble-user: rgba(108,142,255,0.18) with blur(20px), rounded 20px 20px 6px 20px
> - .bubble-aria-wrap .bubble-content: rgba(255,255,255,0.05) with blur(16px), rounded 6px 20px 20px 20px
> - .toast: rgba(40,40,50,0.5) blur(30px), rounded 18px, drop-in animation from top
> - #quit-modal > div: rgba(30,30,38,0.7) blur(40px), rounded 24px
>
> 3. GLASS INTENSITY SLIDER:
> - Add CSS custom properties --glass-blur (default 24px) and --glass-alpha (default 0.06) on :root
> - Add setGlassIntensity(value) JS function: blur = 4 + (value/100)*36, alpha = 0.18 - (value/100)*0.16
> - Add a slider in Settings → Apparence labeled "Intensité Liquid Glass" (0-100, default 60) that calls setGlassIntensity on input
> - Save/restore this setting via saveSettings()/loadSettings()
>
> 4. MORPHING ANIMATIONS:
> - #mic-btn: add .listening class with glassPulse animation (pulsing box-shadow ring), .speaking class with green tint
> - All bubbles use glassMorphIn animation (slide up + scale + blur-in) on appearance
> - All buttons (.glass-btn class) use cubic-bezier(0.34, 1.2, 0.64, 1) transitions with scale on hover/active
>
> 5. TEXT READABILITY:
> - The glass intensity slider must NEVER make text on bubbles unreadable — bubble backgrounds keep a minimum opacity floor of 0.05 for ARIA bubbles and 0.18 for user bubbles regardless of slider, only the blur amount changes with the slider
>
> Keep ALL existing JS API methods and pywebview.api calls unchanged. This is a visual/CSS rewrite — don't change functionality, only the styling and add wallpaper + glass intensity features.
>
> Only modify ui/index.html and ui.py (only for save_wallpaper).
