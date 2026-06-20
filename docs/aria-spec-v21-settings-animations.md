# ARIA — Spec v21 : Animations de validation des paramètres

## Concept

Quand l'utilisateur change un paramètre et appuie sur "Valider" (ou dans certains cas
dès le changement immédiat), une animation montre visuellement l'impact du changement
dans l'interface. L'animation peut être passée en appuyant sur Échap ou en cliquant.

---

## Système de base : AnimationController

```javascript
/**
 * AnimationController — Gère le cycle de vie des animations de settings.
 * Chaque animation :
 * 1. Prend le contrôle visuel de l'élément cible
 * 2. Montre le changement "avant → après"
 * 3. Se termine et laisse l'UI dans son état final
 * 4. Peut être interrompue à tout moment
 */
const AnimationController = {
  _current: null,  // Animation en cours

  // Lance une animation. Stoppe l'animation précédente si présente.
  play(animFn, opts = {}) {
    this.stop();
    const ctrl = { stopped: false, cleanup: null };
    this._current = ctrl;
    ctrl.cleanup = animFn(ctrl, opts);
    return ctrl;
  },

  // Stoppe proprement l'animation en cours
  stop() {
    if (this._current) {
      this._current.stopped = true;
      if (typeof this._current.cleanup === 'function') {
        this._current.cleanup();
      }
      this._current = null;
    }
  },

  // Overlay "skippable" — Échap ou clic n'importe où pour passer
  makeSkippable(onSkip) {
    const overlay = document.createElement('div');
    overlay.style.cssText = `
      position: fixed; inset: 0; z-index: 8000;
      cursor: pointer;
    `;
    overlay.addEventListener('click', onSkip);
    document.addEventListener('keydown', function onKey(e) {
      if (e.key === 'Escape') { onSkip(); document.removeEventListener('keydown', onKey); }
    });
    document.body.appendChild(overlay);
    return () => overlay.remove();
  },
};
```

---

## Liste complète des animations par paramètre

### 1. Changement de thème (Slate / Warm / Forest / Rose / Mono / Contrast)

**Impact visuel** : toute l'interface change de couleurs
**Animation** : transition "flash et fondu" — un voile de la couleur du nouveau thème
recouvre l'écran, puis se dissipe révélant le nouveau thème

```javascript
animThemeChange(ctrl, { oldTheme, newTheme, accentColor }) {
  // Appliquer le nouveau thème immédiatement
  document.documentElement.setAttribute('data-theme', newTheme);

  // Créer l'overlay flash
  const flash = document.createElement('div');
  flash.style.cssText = `
    position: fixed; inset: 0; z-index: 7999;
    background: ${accentColor || 'var(--accent)'};
    opacity: 0.35;
    pointer-events: none;
    transition: opacity 0.6s ease-out;
  `;
  document.body.appendChild(flash);

  // Créer le label "Thème : [nom]" centré
  const label = document.createElement('div');
  label.style.cssText = `
    position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
    z-index: 8000; font-size: 28px; font-weight: 700; color: white;
    letter-spacing: 4px; text-transform: uppercase;
    opacity: 0; transition: opacity 0.3s;
    text-shadow: 0 2px 20px rgba(0,0,0,0.5);
    pointer-events: none;
  `;
  label.textContent = newTheme.toUpperCase();
  document.body.appendChild(label);

  // Séquence d'animation
  requestAnimationFrame(() => {
    label.style.opacity = '1';
    setTimeout(() => {
      if (ctrl.stopped) { flash.remove(); label.remove(); return; }
      flash.style.opacity = '0';
      label.style.opacity = '0';
      setTimeout(() => { flash.remove(); label.remove(); }, 650);
    }, 800);
  });

  return () => { flash.remove(); label.remove(); };
},
```

**Durée** : 1.4s | **Passable** : oui (Échap ou clic)

---

### 2. Intensité Liquid Glass (slider transparence)

**Impact visuel** : la sidebar et le header changent de transparence
**Animation** : le slider pulse, et un "rayon" lumineux balaye les surfaces glass
de gauche à droite révélant le nouveau niveau de transparence

```javascript
animGlassIntensity(ctrl, { value }) {
  // Appliquer la valeur immédiatement
  const blur = 4 + (value / 100) * 36;
  const alpha = 0.18 - (value / 100) * 0.16;
  document.documentElement.style.setProperty('--glass-blur', `${blur}px`);
  document.documentElement.style.setProperty('--glass-alpha', alpha);

  // Rayon lumineux qui balaie la sidebar
  const ray = document.createElement('div');
  ray.style.cssText = `
    position: fixed; top: 0; bottom: 0; left: -100px;
    width: 80px; z-index: 7999; pointer-events: none;
    background: linear-gradient(90deg,
      transparent 0%,
      rgba(255,255,255,0.15) 50%,
      transparent 100%
    );
    animation: glassSweep 0.9s cubic-bezier(0.4,0,0.2,1) forwards;
  `;
  document.body.appendChild(ray);

  // Ajouter le keyframe dynamiquement
  const style = document.createElement('style');
  style.textContent = `
    @keyframes glassSweep {
      0%   { left: -100px; opacity: 0; }
      10%  { opacity: 1; }
      90%  { opacity: 1; }
      100% { left: calc(100vw + 100px); opacity: 0; }
    }
  `;
  document.head.appendChild(style);

  // Label intensité en overlay
  const label = document.createElement('div');
  label.style.cssText = `
    position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%);
    z-index: 8000; background: rgba(0,0,0,0.6); backdrop-filter: blur(20px);
    padding: 8px 18px; border-radius: 20px; font-size: 13px; color: white;
    opacity: 0; transition: opacity 0.3s; pointer-events: none;
    border: 1px solid rgba(255,255,255,0.15);
  `;
  label.textContent = `Transparence : ${value}%`;
  document.body.appendChild(label);
  requestAnimationFrame(() => label.style.opacity = '1');

  setTimeout(() => {
    if (ctrl.stopped) return;
    label.style.opacity = '0';
    setTimeout(() => { ray.remove(); label.remove(); style.remove(); }, 600);
  }, 900);

  return () => { ray.remove(); label.remove(); style.remove(); };
},
```

**Durée** : 1.5s | **Passable** : oui

---

### 3. Changement de fond d'écran (preset ou image personnalisée)

**Impact visuel** : toute la zone d'arrière-plan change
**Animation** : le nouveau fond "glisse" depuis le bas avec un effet de rideau,
puis se stabilise. Un badge indique le nom du preset.

```javascript
animWallpaperChange(ctrl, { type, url, label: wallpaperLabel }) {
  // Créer un layer temporaire au-dessus du fond actuel
  const preview = document.createElement('div');
  preview.style.cssText = `
    position: fixed; inset: 0; z-index: 7990;
    background-size: cover; background-position: center;
    transform: translateY(100%);
    transition: transform 0.7s cubic-bezier(0.34,1.2,0.64,1);
    pointer-events: none;
  `;

  if (type === 'custom' && url) {
    preview.style.backgroundImage = `url("${url}")`;
  } else {
    preview.className = `wp-${type}`;
  }
  document.body.appendChild(preview);

  // Badge nom du fond
  const badge = document.createElement('div');
  badge.style.cssText = `
    position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
    z-index: 8001; background: rgba(0,0,0,0.55); backdrop-filter: blur(20px);
    padding: 10px 22px; border-radius: 24px; font-size: 14px; color: white;
    font-weight: 500; letter-spacing: 0.5px;
    border: 1px solid rgba(255,255,255,0.12);
    opacity: 0; transition: opacity 0.3s; pointer-events: none;
  `;
  badge.innerHTML = `🖼️ ${wallpaperLabel || type}`;
  document.body.appendChild(badge);

  // Déclencher l'animation
  requestAnimationFrame(() => {
    preview.style.transform = 'translateY(0)';
    badge.style.opacity = '1';
  });

  setTimeout(() => {
    if (ctrl.stopped) { applyFinal(); return; }
    // Appliquer le vrai fond et retirer le preview
    applyFinalWallpaper(type, url);
    preview.style.opacity = '0';
    preview.style.transition = 'opacity 0.4s';
    badge.style.opacity = '0';
    setTimeout(() => { preview.remove(); badge.remove(); }, 450);
  }, 1200);

  const applyFinal = () => {
    applyFinalWallpaper(type, url);
    preview.remove();
    badge.remove();
  };

  return applyFinal;
},
```

**Durée** : 1.7s | **Passable** : oui (applique le fond immédiatement)

---

### 4. Activation / Désactivation du TTS

**Impact visuel** : le bouton stop parole change d'état, une onde sonore apparaît
**Animation** : si activation → des ondes sonores rayonnent depuis le bouton micro ;
si désactivation → les ondes "rentrent" en fondu, le bouton pulse une fois en rouge

```javascript
animTTSToggle(ctrl, { enabled }) {
  const micBtn = document.getElementById('mic-btn');
  if (!micBtn) return;

  const rect = micBtn.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;

  if (enabled) {
    // 3 anneaux sonores qui s'expandent
    for (let i = 0; i < 3; i++) {
      const ring = document.createElement('div');
      ring.style.cssText = `
        position: fixed;
        left: ${cx}px; top: ${cy}px;
        width: 40px; height: 40px;
        margin-left: -20px; margin-top: -20px;
        border-radius: 50%;
        border: 2px solid rgba(74,222,128,0.6);
        pointer-events: none;
        z-index: 7999;
        animation: soundRing 1s ${i * 0.2}s ease-out forwards;
      `;
      document.body.appendChild(ring);
      setTimeout(() => ring.remove(), 1200 + i * 200);
    }

    const style = document.createElement('style');
    style.textContent = `
      @keyframes soundRing {
        0%   { transform: scale(1); opacity: 0.8; }
        100% { transform: scale(4); opacity: 0; }
      }
    `;
    document.head.appendChild(style);

    // Toast stylé
    showStyledSettingToast('🔊 Voix activée', '#4ADE80');
    setTimeout(() => style.remove(), 1500);
    return () => style.remove();

  } else {
    // Bulle "muette" qui se réduit
    micBtn.style.transition = 'transform 0.3s, background 0.3s';
    micBtn.style.background = 'rgba(239,68,68,0.2)';
    micBtn.style.transform = 'scale(0.85)';
    setTimeout(() => {
      if (ctrl.stopped) return;
      micBtn.style.transform = 'scale(1)';
      micBtn.style.background = '';
      setTimeout(() => micBtn.style.transition = '', 300);
    }, 400);
    showStyledSettingToast('🔇 Voix désactivée', '#F87171');
    return () => {
      micBtn.style.transform = '';
      micBtn.style.background = '';
    };
  }
},
```

**Durée** : 1s | **Passable** : oui

---

### 5. Changement de modèle IA

**Impact visuel** : le logo JARVIS en sidebar change de comportement
**Animation** : le logo JARVIS accélère ses rotations pendant 1.5s (chargement),
puis un flash de couleur, puis revient normal avec le nouveau nom du modèle
affiché en petit sous "ARIA"

```javascript
animModelChange(ctrl, { role, modelName }) {
  const logo = document.getElementById('aria-logo');
  const statusEl = document.getElementById('status-text');

  // Accélérer les arcs du logo
  const arcs = logo?.querySelectorAll('.logo-arc');
  if (arcs) {
    arcs.forEach((arc, i) => {
      arc.style.animationDuration = ['1.5s', '1s', '0.7s'][i] || '1s';
    });
  }

  // Texte de chargement dans le statut
  const oldStatus = statusEl?.textContent;
  if (statusEl) statusEl.textContent = 'Chargement...';

  // Badge modèle qui apparaît sous ARIA
  const badge = document.createElement('div');
  badge.style.cssText = `
    font-size: 10px; color: var(--accent); opacity: 0;
    transition: opacity 0.3s; text-align: center;
    letter-spacing: 0.5px;
  `;
  badge.textContent = modelName;
  document.getElementById('assistant-name')?.after(badge);
  requestAnimationFrame(() => badge.style.opacity = '1');

  // Rôle → couleur
  const roleColors = {
    intent: 'rgba(74,222,128,0.4)',
    fast:   'rgba(108,142,255,0.4)',
    heavy:  'rgba(167,139,250,0.4)',
    vision: 'rgba(245,158,11,0.4)',
  };
  const color = roleColors[role] || 'rgba(108,142,255,0.4)';

  // Flash coloré sur le logo
  setTimeout(() => {
    if (ctrl.stopped) { cleanup(); return; }
    if (logo) {
      logo.style.filter = `drop-shadow(0 0 16px ${color})`;
      logo.style.transition = 'filter 0.5s';
      setTimeout(() => {
        logo.style.filter = 'drop-shadow(0 0 8px rgba(108,142,255,0.3))';
      }, 500);
    }

    // Ralentir les arcs retour
    if (arcs) {
      arcs.forEach((arc, i) => {
        arc.style.animationDuration = ['12s', '8s', '5s'][i] || '8s';
      });
    }

    if (statusEl) statusEl.textContent = oldStatus || 'En veille';

    // Toast
    const roleLabels = {
      intent: 'Classification', fast: 'Rapide', heavy: 'Approfondi', vision: 'Vision'
    };
    showStyledSettingToast(`🤖 ${roleLabels[role] || role} → ${modelName}`, '#A78BFA');

    setTimeout(() => {
      badge.style.opacity = '0';
      setTimeout(() => badge.remove(), 300);
    }, 2000);
  }, 1200);

  const cleanup = () => {
    if (arcs) arcs.forEach((arc, i) => {
      arc.style.animationDuration = ['12s', '8s', '5s'][i];
    });
    if (statusEl) statusEl.textContent = oldStatus || 'En veille';
    badge.remove();
  };

  return cleanup;
},
```

**Durée** : 2.2s | **Passable** : oui

---

### 6. Changement du modèle Whisper

**Impact visuel** : le bouton micro est concerné
**Animation** : le bouton micro pulse, des ondes de scan balaient vers le haut
(effet "calibration"), puis un texte "Whisper [modèle]" apparaît brièvement

```javascript
animWhisperModelChange(ctrl, { modelName }) {
  const micBtn = document.getElementById('mic-btn');
  const rect = micBtn?.getBoundingClientRect();

  // Scan vertical depuis le bas du micro vers le haut
  const scan = document.createElement('div');
  scan.style.cssText = `
    position: fixed;
    left: ${rect?.left - 10 || 0}px;
    width: ${rect?.width + 20 || 60}px;
    height: 2px;
    background: linear-gradient(90deg, transparent, rgba(108,142,255,0.9), transparent);
    z-index: 7999; pointer-events: none;
    animation: scanUp 0.8s ease-in-out 3 forwards;
    bottom: ${window.innerHeight - (rect?.bottom || 0)}px;
  `;
  document.body.appendChild(scan);

  const style = document.createElement('style');
  style.textContent = `
    @keyframes scanUp {
      0%   { transform: translateY(0); opacity: 1; }
      100% { transform: translateY(-${rect?.height || 40}px); opacity: 0; }
    }
  `;
  document.head.appendChild(style);

  // Badge modèle
  const badge = document.createElement('div');
  badge.style.cssText = `
    position: fixed;
    left: ${rect?.left || 0}px;
    top: ${(rect?.top || 60) - 40}px;
    background: rgba(0,0,0,0.7); backdrop-filter: blur(16px);
    padding: 4px 10px; border-radius: 8px;
    font-size: 11px; color: rgba(108,142,255,0.9);
    opacity: 0; transition: opacity 0.3s; pointer-events: none;
    z-index: 8000; white-space: nowrap;
    border: 1px solid rgba(108,142,255,0.2);
  `;
  badge.textContent = `Whisper ${modelName}`;
  document.body.appendChild(badge);
  requestAnimationFrame(() => badge.style.opacity = '1');

  setTimeout(() => {
    if (ctrl.stopped) return;
    badge.style.opacity = '0';
    scan.remove(); style.remove();
    setTimeout(() => badge.remove(), 300);
    showStyledSettingToast(`🎤 Whisper → ${modelName}`, '#6C8EFF');
  }, 1500);

  return () => { scan.remove(); style.remove(); badge.remove(); };
},
```

**Durée** : 1.8s | **Passable** : oui

---

### 7. Device index micro changé

**Impact visuel** : le sélecteur de device est concerné
**Animation** : une animation de "détection" pulse sur le bouton micro,
avec un texte "Device [index] détecté" qui apparaît

```javascript
animDeviceChange(ctrl, { deviceIndex }) {
  const micBtn = document.getElementById('mic-btn');
  if (!micBtn) return;

  // Pulse x3 — vert si succès
  let count = 0;
  const interval = setInterval(() => {
    if (ctrl.stopped || count >= 3) {
      clearInterval(interval);
      micBtn.style.boxShadow = '';
      return;
    }
    micBtn.style.boxShadow = `0 0 0 ${count % 2 === 0 ? '8px' : '0px'} rgba(74,222,128,0.35)`;
    micBtn.style.transition = 'box-shadow 0.25s';
    count++;
  }, 250);

  showStyledSettingToast(`🎤 Device ${deviceIndex ?? 'auto'} sélectionné`, '#4ADE80');

  setTimeout(() => {
    clearInterval(interval);
    micBtn.style.boxShadow = '';
    micBtn.style.transition = '';
  }, 1000);

  return () => {
    clearInterval(interval);
    micBtn.style.boxShadow = '';
  };
},
```

**Durée** : 1s | **Passable** : oui

---

### 8. Mode focus ON / OFF

**Impact visuel** : toute l'interface
**Animation** :
- **Activation** : un voile légèrement plus sombre s'étend sur l'écran (réduction
  des distractions), le logo JARVIS ralentit, et un badge "Mode Focus" s'installe
  en coin haut-droit avec une animation de slide
- **Désactivation** : le voile se dissipe, le logo reprend son rythme normal

```javascript
animFocusMode(ctrl, { enabled }) {
  const logo = document.getElementById('aria-logo');
  const focusIndicator = document.getElementById('focus-indicator');

  if (enabled) {
    // Voile sombre progressif sur l'écran
    const veil = document.createElement('div');
    veil.id = 'focus-veil';
    veil.style.cssText = `
      position: fixed; inset: 0; z-index: 7980;
      background: rgba(0,0,0,0.12);
      opacity: 0; transition: opacity 0.8s ease;
      pointer-events: none;
    `;
    document.body.appendChild(veil);
    requestAnimationFrame(() => veil.style.opacity = '1');

    // Ralentir le logo
    logo?.querySelectorAll('.logo-arc').forEach((arc, i) => {
      arc.style.animationDuration = ['20s', '15s', '10s'][i] || '15s';
    });

    // Indicateur focus (slide depuis la droite)
    if (focusIndicator) {
      focusIndicator.style.display = 'block';
      focusIndicator.style.transform = 'translateX(120%)';
      focusIndicator.style.transition = 'transform 0.5s cubic-bezier(0.34,1.4,0.64,1)';
      requestAnimationFrame(() => focusIndicator.style.transform = 'translateX(0)');
    }

    showStyledSettingToast('🎯 Mode focus activé — distractions réduites', '#A78BFA');

    return () => {
      veil.style.opacity = '0';
      setTimeout(() => veil.remove(), 800);
      logo?.querySelectorAll('.logo-arc').forEach((arc, i) => {
        arc.style.animationDuration = ['12s', '8s', '5s'][i];
      });
    };

  } else {
    // Dissiper le voile
    const veil = document.getElementById('focus-veil');
    if (veil) {
      veil.style.opacity = '0';
      setTimeout(() => veil.remove(), 800);
    }

    // Reprendre le rythme normal du logo
    logo?.querySelectorAll('.logo-arc').forEach((arc, i) => {
      arc.style.animationDuration = ['12s', '8s', '5s'][i];
    });

    // Masquer l'indicateur (slide vers la droite)
    if (focusIndicator) {
      focusIndicator.style.transform = 'translateX(120%)';
      setTimeout(() => {
        focusIndicator.style.display = 'none';
        focusIndicator.style.transform = '';
      }, 500);
    }

    showStyledSettingToast('🎯 Mode focus désactivé', '#6C8EFF');
    return () => {};
  }
},
```

**Durée** : 1.2s | **Passable** : oui

---

### 9. Brief quotidien ON / OFF

**Impact visuel** : icône du logo en sidebar
**Animation** : une petite animation "réveil" — le logo clignote une fois,
et un badge "Brief : ON/OFF" apparaît brièvement en dessous du status-text

```javascript
animDailyBriefToggle(ctrl, { enabled }) {
  const statusEl = document.getElementById('status-text');
  const original = statusEl?.textContent;

  if (statusEl) {
    statusEl.style.transition = 'color 0.3s, opacity 0.3s';
    statusEl.style.color = enabled ? '#4ADE80' : '#F87171';
    statusEl.textContent = enabled ? '☀️ Brief quotidien activé' : 'Brief désactivé';
    setTimeout(() => {
      if (ctrl.stopped) return;
      statusEl.style.color = '';
      statusEl.textContent = original || 'En veille';
    }, 1800);
  }

  showStyledSettingToast(
    enabled ? '☀️ Brief du matin activé' : '🌙 Brief désactivé',
    enabled ? '#4ADE80' : '#F87171'
  );

  return () => {
    if (statusEl) {
      statusEl.style.color = '';
      statusEl.textContent = original || 'En veille';
    }
  };
},
```

**Durée** : 1.8s | **Passable** : oui

---

### 10. Vitesse TTS (slider)

**Impact visuel** : feedback auditif immédiat (si TTS actif)
**Animation** : une onde de fréquence animée apparaît à côté du slider,
dont la vitesse visuelle correspond à la valeur du slider

```javascript
animTTSRate(ctrl, { rate }) {
  const slider = document.getElementById('set-tts-rate');
  const rect = slider?.getBoundingClientRect();
  if (!rect) return;

  // Onde animée à côté du slider
  const wave = document.createElement('canvas');
  wave.width = 120; wave.height = 30;
  wave.style.cssText = `
    position: fixed;
    left: ${rect.right + 10}px; top: ${rect.top - 5}px;
    z-index: 8000; pointer-events: none; opacity: 0;
    transition: opacity 0.3s;
  `;
  document.body.appendChild(wave);
  requestAnimationFrame(() => wave.style.opacity = '1');

  const ctx = wave.getContext('2d');
  let t = 0;
  const speed = 0.05 + (rate + 50) / 100 * 0.15;  // vitesse selon rate
  const amplitude = 10;
  const freq = 0.1;

  const drawWave = () => {
    if (ctrl.stopped) return;
    ctx.clearRect(0, 0, 120, 30);
    ctx.strokeStyle = 'rgba(108,142,255,0.7)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let x = 0; x < 120; x++) {
      const y = 15 + Math.sin((x * freq + t)) * amplitude;
      x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.stroke();
    t += speed;
    requestAnimationFrame(drawWave);
  };

  drawWave();

  // Badge vitesse
  const label = document.createElement('div');
  label.style.cssText = `
    position: fixed;
    left: ${rect.right + 10}px; top: ${rect.top + 30}px;
    font-size: 10px; color: var(--accent); z-index: 8000;
    pointer-events: none; opacity: 0; transition: opacity 0.3s;
  `;
  label.textContent = `${rate > 0 ? '+' : ''}${rate}% vitesse`;
  document.body.appendChild(label);
  requestAnimationFrame(() => label.style.opacity = '1');

  setTimeout(() => {
    if (ctrl.stopped) return;
    wave.style.opacity = '0'; label.style.opacity = '0';
    setTimeout(() => { wave.remove(); label.remove(); }, 350);
  }, 1500);

  return () => { wave.remove(); label.remove(); };
},
```

**Durée** : 1.8s | **Passable** : oui

---

### 11. Import de wallpaper personnalisé

**Impact visuel** : la grille de wallpapers et le fond d'écran
**Animation** : l'image importée "tombe" depuis le bouton d'import vers la grille
(effet de drag simulé), puis le fond change

```javascript
animWallpaperImport(ctrl, { filename, url }) {
  const importBtn = document.querySelector('label.settings-btn-outline');
  const grid = document.getElementById('wallpaper-custom-grid');
  if (!importBtn || !grid) return;

  const fromRect = importBtn.getBoundingClientRect();
  const toRect = grid.getBoundingClientRect();

  // Miniature qui vole du bouton vers la grille
  const fly = document.createElement('div');
  fly.style.cssText = `
    position: fixed;
    left: ${fromRect.left + fromRect.width / 2 - 36}px;
    top: ${fromRect.top}px;
    width: 72px; height: 50px; border-radius: 8px;
    background-image: url("${url}");
    background-size: cover; background-position: center;
    z-index: 8001; pointer-events: none;
    transition: all 0.6s cubic-bezier(0.34,1.2,0.64,1);
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    border: 2px solid var(--accent);
  `;
  document.body.appendChild(fly);

  // Déclencher le vol vers la grille
  requestAnimationFrame(() => {
    setTimeout(() => {
      fly.style.left = `${toRect.left}px`;
      fly.style.top = `${toRect.top}px`;
      fly.style.transform = 'scale(1)';
      fly.style.opacity = '1';
    }, 50);
  });

  setTimeout(() => {
    if (ctrl.stopped) return;
    fly.style.opacity = '0';
    fly.style.transform = 'scale(0.8)';
    setTimeout(() => fly.remove(), 400);
    showStyledSettingToast('📷 Image ajoutée', '#4ADE80');
  }, 750);

  return () => fly.remove();
},
```

**Durée** : 1.2s | **Passable** : oui

---

## Toast stylé commun à toutes les animations

```javascript
function showStyledSettingToast(message, color = 'var(--accent)') {
  const toast = document.createElement('div');
  toast.style.cssText = `
    position: fixed; top: 50px; right: 20px; z-index: 9000;
    background: rgba(20,20,30,0.7); backdrop-filter: blur(30px) saturate(180%);
    border: 1px solid ${color}40;
    border-left: 3px solid ${color};
    border-radius: 12px; padding: 11px 18px;
    font-size: 13px; color: white;
    opacity: 0; transform: translateX(20px);
    transition: opacity 0.25s, transform 0.25s;
    box-shadow: 0 8px 32px rgba(0,0,0,0.25);
    pointer-events: none; max-width: 280px;
  `;
  toast.textContent = message;
  document.body.appendChild(toast);

  requestAnimationFrame(() => {
    toast.style.opacity = '1';
    toast.style.transform = 'translateX(0)';
  });

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    setTimeout(() => toast.remove(), 300);
  }, 2500);
}
```

---

## Bouton "Valider" dans les sections accordéon

Chaque section de paramètres a un bouton "Valider" qui :
1. Sauvegarde les nouvelles valeurs
2. Lance l'animation correspondante
3. Permet de passer avec Échap ou clic

```html
<!-- Template bouton Valider à ajouter en bas de chaque .acc-body -->
<button class="settings-validate-btn" onclick="aria.validateSection('${sectionId}')">
  ✓ Appliquer
</button>
```

```css
.settings-validate-btn {
  width: 100%;
  margin-top: 12px;
  padding: 10px;
  background: linear-gradient(135deg, rgba(108,142,255,0.15), rgba(167,139,250,0.1));
  border: 1px solid rgba(108,142,255,0.25);
  border-radius: 10px;
  color: var(--accent);
  font-family: inherit;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, transform 0.1s;
  letter-spacing: 0.3px;
}

.settings-validate-btn:hover {
  background: linear-gradient(135deg, rgba(108,142,255,0.25), rgba(167,139,250,0.18));
  transform: translateY(-1px);
}

.settings-validate-btn:active {
  transform: scale(0.98);
}
```

```javascript
async validateSection(sectionId) {
  const btn = document.querySelector(`#acc-${sectionId} .settings-validate-btn`);
  if (btn) {
    btn.textContent = '⟳ Application...';
    btn.disabled = true;
  }

  // Sauvegarder + lancer l'animation selon la section
  switch(sectionId) {
    case 'apparence':
      await aria.saveSetting('theme', aria._pendingTheme || aria.loadSettings().theme);
      await aria.saveSetting('glass_intensity', document.getElementById('set-glass')?.value);
      AnimationController.play(aria.animThemeChange.bind(aria), {
        newTheme: aria._pendingTheme || 'slate',
        accentColor: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
      });
      break;

    case 'voix':
      const ttsEnabled = document.getElementById('set-tts')?.checked;
      const ttsRate = parseInt(document.getElementById('set-tts-rate')?.value || '0');
      await aria.saveSetting('tts_enabled', ttsEnabled);
      await aria.saveSetting('tts_rate', ttsRate);
      AnimationController.play(aria.animTTSToggle.bind(aria), { enabled: ttsEnabled });
      break;

    case 'modeles':
      // Les modèles sont sauvegardés au changement du <select>
      // L'animation a déjà été jouée
      showStyledSettingToast('✓ Modèles sauvegardés', '#4ADE80');
      break;

    case 'micro':
      const deviceIdx = parseInt(document.getElementById('set-device-index')?.value) || null;
      const whisperModel = document.getElementById('set-whisper-model')?.value;
      await aria.saveSetting('stt.device_index', deviceIdx);
      await aria.saveSetting('stt.model', whisperModel);
      AnimationController.play(aria.animDeviceChange.bind(aria), { deviceIndex: deviceIdx });
      if (whisperModel) {
        setTimeout(() => AnimationController.play(aria.animWhisperModelChange.bind(aria), { modelName: whisperModel }), 1200);
      }
      break;

    case 'systeme':
      const focusEnabled = document.getElementById('set-focus')?.checked;
      const briefEnabled = document.getElementById('set-daily-brief')?.checked;
      await aria.saveSetting('focus_mode', focusEnabled);
      await aria.saveSetting('daily_brief_enabled', briefEnabled);
      AnimationController.play(aria.animFocusMode.bind(aria), { enabled: focusEnabled });
      break;
  }

  // Rétablir le bouton après l'animation
  setTimeout(() => {
    if (btn) { btn.textContent = '✓ Appliquer'; btn.disabled = false; }
  }, 500);
},
```

---

## Tableau récapitulatif

| Paramètre | Animation | Durée | Éléments touchés |
|---|---|---|---|
| Thème | Flash couleur + label centré | 1.4s | Toute l'UI |
| Transparence glass | Rayon lumineux horizontal | 1.5s | Sidebar, header |
| Fond d'écran | Rideau depuis le bas | 1.7s | Arrière-plan |
| TTS ON | Anneaux sonores verts | 1s | Bouton micro |
| TTS OFF | Pulse rouge + contraction | 0.8s | Bouton micro |
| Modèle IA | Logo accélère + flash couleur | 2.2s | Logo JARVIS |
| Whisper model | Scan vertical + badge | 1.8s | Bouton micro |
| Device micro | Pulse vert x3 | 1s | Bouton micro |
| Mode focus ON | Voile sombre + logo ralentit | 1.2s | Toute l'UI |
| Mode focus OFF | Voile disparaît + logo reprend | 1s | Toute l'UI |
| Brief quotidien | Status-text change couleur | 1.8s | Sidebar status |
| Vitesse TTS | Onde de fréquence canvas | 1.8s | Zone slider |
| Import wallpaper | Image "vole" vers la grille | 1.2s | Grille wallpapers |

---

## Prompt Cursor

> Implémenter le système d'animations de validation des paramètres.
>
> **1. Ajouter `AnimationController` en haut de app.js (ou ui/index.html)** avec les
> méthodes `play(animFn, opts)`, `stop()`, `makeSkippable(onSkip)`. L'objet est global.
>
> **2. Ajouter la fonction `showStyledSettingToast(message, color)`** indépendante du
> système de toast existant — toast avec bordure gauche colorée, slide depuis la droite,
> auto-disparaît après 2.5s.
>
> **3. Ajouter toutes les fonctions d'animation dans l'objet `aria` (ou `app`)** :
> `animThemeChange`, `animGlassIntensity`, `animWallpaperChange`, `animTTSToggle`,
> `animModelChange`, `animWhisperModelChange`, `animDeviceChange`, `animFocusMode`,
> `animDailyBriefToggle`, `animTTSRate`, `animWallpaperImport`.
> Chaque fonction reçoit `(ctrl, opts)` et retourne une fonction de cleanup.
>
> **4. Ajouter le CSS** pour `.settings-validate-btn` (bouton dégradé accent, hover élève),
> et les keyframes : `glassSweep`, `soundRing`, `scanUp`.
>
> **5. Ajouter le bouton "✓ Appliquer"** en bas de chaque `.acc-body` dans les sections
> paramètres (apparence, voix, micro, système). La section modèles n'a pas de bouton
> Appliquer — les dropdowns sauvegardent et animent au changement direct.
>
> **6. Ajouter `validateSection(sectionId)`** qui sauvegarde les valeurs et lance
> l'animation correspondante comme spécifié.
>
> **7. Brancher les animations sur les changements directs (sans Appliquer) pour** :
> - Le slider glass → `animGlassIntensity` à chaque `oninput`
>   (légère — juste le rayon, pas le label)
> - Le slider TTS rate → `animTTSRate` à chaque `oninput`
> - Les dropdowns de modèles → `animModelChange` au `onchange`
>
> **8. Brancher `animWallpaperChange`** dans `setWallpaper()` existant.
> Brancher `animWallpaperImport`** dans `uploadWallpaper()` existant après succès.
>
> **9. Rendre toutes les animations passables** : ajouter un listener global `keydown`
> sur `Escape` qui appelle `AnimationController.stop()`, et un overlay transparent
> (z-index 7998) cliquable pendant chaque animation.
>
> Modifie uniquement ui/index.html (ou electron/renderer/app.js + styles.css si
> migration Electron déjà faite).
