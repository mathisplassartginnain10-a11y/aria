/**
 * settings-animations.js — Animations de validation des paramètres ARIA
 * Porté depuis ui/index.html (spec v21)
 */

(function ensureKeyframes() {
  if (document.getElementById('settings-anim-keyframes')) return;
  let hasGlass = false;
  try {
    for (const sheet of document.styleSheets) {
      try {
        for (const rule of sheet.cssRules) {
          if (rule.name === 'glassSweep') { hasGlass = true; break; }
        }
      } catch (_) { /* cross-origin */ }
      if (hasGlass) break;
    }
  } catch (_) {}
  if (hasGlass) return;
  const style = document.createElement('style');
  style.id = 'settings-anim-keyframes';
  style.textContent = `
    @keyframes glassSweep {
      0%   { left: -100px; opacity: 0; }
      10%  { opacity: 1; }
      90%  { opacity: 1; }
      100% { left: calc(100vw + 100px); opacity: 0; }
    }
    @keyframes soundRing {
      0%   { transform: scale(1); opacity: 0.8; }
      100% { transform: scale(2.5); opacity: 0; }
    }
    @keyframes scanUp {
      0%   { transform: translateY(0); opacity: 0; }
      20%  { opacity: 1; }
      80%  { opacity: 1; }
      100% { transform: translateY(-60px); opacity: 0; }
    }
  `;
  document.head.appendChild(style);
})();

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

const SettingsAnimations = {
  themeColors: {
    slate: '#FF6B35', warm: '#F59E0B', forest: '#4ADE80',
    rose: '#F472B6', mono: '#ECECEC', contrast: '#ffffff',
  },

  wallpaperLabels: {
    aurora: 'Aurora', sunset: 'Sunset', forest: 'Forest', midnight: 'Midnight',
    mesh: 'Mesh', 'mesh-animated': 'Mesh', mono: 'Mono', custom: 'Personnalisé',
  },

  _getMicBtn() {
    return document.getElementById('mic-btn')
      || document.getElementById('input-mic-btn')
      || document.getElementById('mic-visual-btn');
  },

  _getOrbeEl() {
    return document.getElementById('home-orbe')
      || document.getElementById('home-logo');
  },

  _getSidebarOrbeWrap() {
    return document.getElementById('sidebar-orbe-wrap')
      || document.getElementById('sidebar-logo-wrap');
  },

  animThemeChange(ctrl, { newTheme, accentColor }) {
    const themeName = newTheme || 'slate';
    document.documentElement.setAttribute('data-theme', themeName);

    const flash = document.createElement('div');
    flash.style.cssText = `
      position: fixed; inset: 0; z-index: 7999;
      background: ${accentColor || this.themeColors[themeName] || 'var(--accent)'};
      opacity: 0.35; pointer-events: none; transition: opacity 0.6s ease-out;
    `;
    document.body.appendChild(flash);

    const label = document.createElement('div');
    label.style.cssText = `
      position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
      z-index: 8000; font-size: 28px; font-weight: 700; color: white;
      letter-spacing: 4px; text-transform: uppercase;
      opacity: 0; transition: opacity 0.3s;
      text-shadow: 0 2px 20px rgba(0,0,0,0.5); pointer-events: none;
    `;
    label.textContent = themeName.toUpperCase();
    document.body.appendChild(label);

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

  animGlassIntensity(ctrl, { value, light }) {
    const v = Math.max(0, Math.min(100, Number(value) || 60));
    const blur = 4 + (v / 100) * 36;
    const alpha = 0.18 - (v / 100) * 0.16;
    document.documentElement.style.setProperty('--glass-blur', `${blur}px`);
    document.documentElement.style.setProperty('--glass-alpha', alpha);

    const ray = document.createElement('div');
    ray.style.cssText = `
      position: fixed; top: 0; bottom: 0; left: -100px;
      width: 80px; z-index: 7999; pointer-events: none;
      background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.15) 50%, transparent 100%);
      animation: glassSweep 0.9s cubic-bezier(0.4,0,0.2,1) forwards;
    `;
    document.body.appendChild(ray);

    let label = null;
    if (!light) {
      label = document.createElement('div');
      label.style.cssText = `
        position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%);
        z-index: 8000; background: rgba(0,0,0,0.6); backdrop-filter: blur(20px);
        padding: 8px 18px; border-radius: 20px; font-size: 13px; color: white;
        opacity: 0; transition: opacity 0.3s; pointer-events: none;
        border: 1px solid rgba(255,255,255,0.15);
      `;
      label.textContent = `Transparence : ${v}%`;
      document.body.appendChild(label);
      requestAnimationFrame(() => { label.style.opacity = '1'; });
    }

    setTimeout(() => {
      if (ctrl.stopped) return;
      if (label) label.style.opacity = '0';
      setTimeout(() => { ray.remove(); label?.remove(); }, 600);
    }, 900);

    return () => { ray.remove(); label?.remove(); };
  },

  animWallpaperChange(ctrl, { type, url, label: wallpaperLabel }) {
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

    const applyFinal = () => {
      if (typeof window.__applyWallpaperImmediate === 'function') {
        window.__applyWallpaperImmediate(type, url);
      }
      preview.remove();
      badge.remove();
    };

    requestAnimationFrame(() => {
      preview.style.transform = 'translateY(0)';
      badge.style.opacity = '1';
    });

    setTimeout(() => {
      if (ctrl.stopped) { applyFinal(); return; }
      applyFinal();
      preview.style.opacity = '0';
      preview.style.transition = 'opacity 0.4s';
      badge.style.opacity = '0';
      setTimeout(() => { preview.remove(); badge.remove(); }, 450);
    }, 1200);

    return applyFinal;
  },

  animTTSToggle(ctrl, { enabled }) {
    const micBtn = this._getMicBtn();
    if (!micBtn) return () => {};

    const rect = micBtn.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;

    if (enabled) {
      for (let i = 0; i < 3; i++) {
        const ring = document.createElement('div');
        ring.style.cssText = `
          position: fixed; left: ${cx}px; top: ${cy}px;
          width: 40px; height: 40px; margin-left: -20px; margin-top: -20px;
          border-radius: 50%; border: 2px solid rgba(74,222,128,0.6);
          pointer-events: none; z-index: 7999;
          animation: soundRing 1s ${i * 0.2}s ease-out forwards;
        `;
        document.body.appendChild(ring);
        setTimeout(() => ring.remove(), 1200 + i * 200);
      }
      showStyledSettingToast('🔊 Voix activée', '#4ADE80');
      return () => {};
    }

    micBtn.style.transition = 'transform 0.3s, background 0.3s';
    micBtn.style.background = 'rgba(239,68,68,0.2)';
    micBtn.style.transform = 'scale(0.85)';
    setTimeout(() => {
      if (ctrl.stopped) return;
      micBtn.style.transform = 'scale(1)';
      micBtn.style.background = '';
      setTimeout(() => { micBtn.style.transition = ''; }, 300);
    }, 400);
    showStyledSettingToast('🔇 Voix désactivée', '#F87171');
    return () => {
      micBtn.style.transform = '';
      micBtn.style.background = '';
      micBtn.style.transition = '';
    };
  },

  animModelChange(ctrl, { role, modelName }) {
    const orbe = this._getOrbeEl();
    const core = orbe?.querySelector('.orbe-core');
    const subtitle = document.getElementById('sidebar-subtitle');
    const oldStatus = subtitle?.textContent;

    if (subtitle) subtitle.textContent = 'Chargement...';
    orbe?.classList.add('orbe-thinking');

    const badge = document.createElement('div');
    badge.style.cssText = `
      position: fixed; bottom: 100px; left: 50%; transform: translateX(-50%);
      z-index: 8000; background: rgba(0,0,0,0.6); backdrop-filter: blur(20px);
      padding: 8px 16px; border-radius: 20px; font-size: 12px; color: var(--accent);
      opacity: 0; transition: opacity 0.3s; pointer-events: none;
      border: 1px solid rgba(108,142,255,0.2);
    `;
    badge.textContent = modelName;
    document.body.appendChild(badge);
    requestAnimationFrame(() => { badge.style.opacity = '1'; });

    const roleColors = {
      intent: 'rgba(74,222,128,0.4)',
      fast: 'rgba(108,142,255,0.4)',
      heavy: 'rgba(167,139,250,0.4)',
      vision: 'rgba(245,158,11,0.4)',
    };
    const color = roleColors[role] || 'rgba(108,142,255,0.4)';

    const cleanup = () => {
      orbe?.classList.remove('orbe-thinking');
      if (subtitle) subtitle.textContent = oldStatus || 'En veille';
      if (core) {
        core.style.filter = '';
        core.style.transform = '';
        core.style.transition = '';
      }
      badge.remove();
    };

    setTimeout(() => {
      if (ctrl.stopped) { cleanup(); return; }
      if (core) {
        core.style.transition = 'filter 0.5s, transform 0.5s';
        core.style.filter = `drop-shadow(0 0 16px ${color})`;
        core.style.transform = 'scale(1.08)';
        setTimeout(() => {
          core.style.filter = 'drop-shadow(0 0 8px rgba(108,142,255,0.3))';
          core.style.transform = 'scale(1)';
        }, 500);
      }
      orbe?.classList.remove('orbe-thinking');
      if (subtitle) subtitle.textContent = oldStatus || 'En veille';

      const roleLabels = { intent: 'Classification', fast: 'Rapide', heavy: 'Approfondi', vision: 'Vision' };
      showStyledSettingToast(`🤖 ${roleLabels[role] || role} → ${modelName}`, '#A78BFA');

      setTimeout(() => {
        badge.style.opacity = '0';
        setTimeout(() => badge.remove(), 300);
      }, 2000);
    }, 1200);

    return cleanup;
  },

  animWhisperModelChange(ctrl, { modelName }) {
    const micBtn = this._getMicBtn();
    const rect = micBtn?.getBoundingClientRect();

    const scan = document.createElement('div');
    scan.style.cssText = `
      position: fixed;
      left: ${(rect?.left ?? 0) - 10}px;
      width: ${(rect?.width ?? 60) + 20}px;
      height: 2px;
      background: linear-gradient(90deg, transparent, rgba(108,142,255,0.9), transparent);
      z-index: 7999; pointer-events: none;
      animation: scanUp 0.8s ease-in-out 3 forwards;
      bottom: ${window.innerHeight - (rect?.bottom || 0)}px;
    `;
    document.body.appendChild(scan);

    const badge = document.createElement('div');
    badge.style.cssText = `
      position: fixed; left: ${rect?.left || 0}px; top: ${(rect?.top || 60) - 40}px;
      background: rgba(0,0,0,0.7); backdrop-filter: blur(16px);
      padding: 4px 10px; border-radius: 8px;
      font-size: 11px; color: rgba(108,142,255,0.9);
      opacity: 0; transition: opacity 0.3s; pointer-events: none;
      z-index: 8000; white-space: nowrap;
      border: 1px solid rgba(108,142,255,0.2);
    `;
    badge.textContent = `Whisper ${modelName}`;
    document.body.appendChild(badge);
    requestAnimationFrame(() => { badge.style.opacity = '1'; });

    setTimeout(() => {
      if (ctrl.stopped) return;
      badge.style.opacity = '0';
      scan.remove();
      setTimeout(() => badge.remove(), 300);
      showStyledSettingToast(`🎤 Whisper → ${modelName}`, '#6C8EFF');
    }, 1500);

    return () => { scan.remove(); badge.remove(); };
  },

  animDeviceChange(ctrl, { deviceIndex }) {
    const micBtn = this._getMicBtn();
    if (!micBtn) return () => {};

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
      micBtn.style.transition = '';
    };
  },

  animFocusMode(ctrl, { enabled }) {
    const orbe = this._getOrbeEl();
    const focusIndicator = document.getElementById('focus-indicator');

    if (enabled) {
      const veil = document.createElement('div');
      veil.id = 'focus-veil';
      veil.style.cssText = `
        position: fixed; inset: 0; z-index: 7980;
        background: rgba(0,0,0,0.12); opacity: 0;
        transition: opacity 0.8s ease; pointer-events: none;
      `;
      document.body.appendChild(veil);
      requestAnimationFrame(() => { veil.style.opacity = '1'; });

      orbe?.querySelectorAll('.ring').forEach((ring, i) => {
        ring.style.animationDuration = ['20s', '15s', '12s', '10s', '8s'][i] || '15s';
      });

      if (focusIndicator) {
        focusIndicator.style.display = 'block';
        focusIndicator.style.transform = 'translateX(120%)';
        focusIndicator.style.transition = 'transform 0.5s cubic-bezier(0.34,1.4,0.64,1)';
        requestAnimationFrame(() => { focusIndicator.style.transform = 'translateX(0)'; });
      }

      showStyledSettingToast('🎯 Mode focus activé — distractions réduites', '#A78BFA');

      return () => {
        veil.style.opacity = '0';
        setTimeout(() => veil.remove(), 800);
        orbe?.querySelectorAll('.ring').forEach((ring, i) => {
          ring.style.animationDuration = ['8s', '6s', '12s', '16s', '4s'][i] || '8s';
        });
      };
    }

    const veil = document.getElementById('focus-veil');
    if (veil) {
      veil.style.opacity = '0';
      setTimeout(() => veil.remove(), 800);
    }

    orbe?.querySelectorAll('.ring').forEach((ring, i) => {
      ring.style.animationDuration = ['8s', '6s', '12s', '16s', '4s'][i] || '8s';
    });

    if (focusIndicator) {
      focusIndicator.style.transform = 'translateX(120%)';
      setTimeout(() => {
        focusIndicator.style.display = 'none';
        focusIndicator.style.transform = '';
      }, 500);
    }

    showStyledSettingToast('🎯 Mode focus désactivé', '#6C8EFF');
    return () => {};
  },

  animDailyBriefToggle(ctrl, { enabled }) {
    const subtitle = document.getElementById('sidebar-subtitle');
    const original = subtitle?.textContent;

    if (subtitle) {
      subtitle.style.transition = 'color 0.3s, opacity 0.3s';
      subtitle.style.color = enabled ? '#4ADE80' : '#F87171';
      subtitle.textContent = enabled ? '☀️ Brief quotidien activé' : 'Brief désactivé';
      setTimeout(() => {
        if (ctrl.stopped) return;
        subtitle.style.color = '';
        subtitle.textContent = original || 'En veille';
      }, 1800);
    }

    showStyledSettingToast(
      enabled ? '☀️ Brief du matin activé' : '🌙 Brief désactivé',
      enabled ? '#4ADE80' : '#F87171'
    );

    return () => {
      if (subtitle) {
        subtitle.style.color = '';
        subtitle.textContent = original || 'En veille';
      }
    };
  },

  animTTSRate(ctrl, { rate }) {
    const slider = document.getElementById('set-tts-rate');
    const rect = slider?.getBoundingClientRect();
    if (!rect) return () => {};

    const wave = document.createElement('canvas');
    wave.width = 120;
    wave.height = 30;
    wave.style.cssText = `
      position: fixed; left: ${rect.right + 10}px; top: ${rect.top - 5}px;
      z-index: 8000; pointer-events: none; opacity: 0; transition: opacity 0.3s;
    `;
    document.body.appendChild(wave);
    requestAnimationFrame(() => { wave.style.opacity = '1'; });

    const ctx = wave.getContext('2d');
    let t = 0;
    const speed = 0.05 + (rate + 50) / 100 * 0.15;
    let rafId = 0;

    const drawWave = () => {
      if (ctrl.stopped) return;
      ctx.clearRect(0, 0, 120, 30);
      ctx.strokeStyle = 'rgba(108,142,255,0.7)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let x = 0; x < 120; x++) {
        const y = 15 + Math.sin(x * 0.1 + t) * 10;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      t += speed;
      rafId = requestAnimationFrame(drawWave);
    };
    drawWave();

    const label = document.createElement('div');
    label.style.cssText = `
      position: fixed; left: ${rect.right + 10}px; top: ${rect.top + 30}px;
      font-size: 10px; color: var(--accent); z-index: 8000;
      pointer-events: none; opacity: 0; transition: opacity 0.3s;
    `;
    label.textContent = `${rate > 0 ? '+' : ''}${rate}% vitesse`;
    document.body.appendChild(label);
    requestAnimationFrame(() => { label.style.opacity = '1'; });

    setTimeout(() => {
      if (ctrl.stopped) return;
      cancelAnimationFrame(rafId);
      wave.style.opacity = '0';
      label.style.opacity = '0';
      setTimeout(() => { wave.remove(); label.remove(); }, 350);
    }, 1500);

    return () => {
      cancelAnimationFrame(rafId);
      wave.remove();
      label.remove();
    };
  },

  animWallpaperImport(ctrl, { filename, url }) {
    void filename;
    const importBtn = document.querySelector('label.settings-btn-outline') || document.querySelector('label.settings-btn');
    const grid = document.getElementById('wallpaper-custom-grid');
    if (!importBtn || !grid) return () => {};

    const fromRect = importBtn.getBoundingClientRect();
    const toRect = grid.getBoundingClientRect();

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

    requestAnimationFrame(() => {
      setTimeout(() => {
        fly.style.left = `${toRect.left}px`;
        fly.style.top = `${toRect.top}px`;
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
};

if (typeof window !== 'undefined') {
  window.SettingsAnimations = SettingsAnimations;
  window.showStyledSettingToast = showStyledSettingToast;
}
