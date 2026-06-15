# ARIA — Spec v14 : Logo JARVIS-style animé

## Concept

Le logo remplace le simple texte "ARIA" dans la sidebar par un emblème animé :
- Un cercle/orbe central avec la lettre "A" stylisée ou un symbole abstrait
- 2-3 arcs concentriques qui tournent lentement en permanence (pas seulement quand ARIA parle)
- Un arc qui s'accélère et change de couleur selon l'état (idle/listening/thinking/speaking)
- Effet "scan" lumineux qui parcourt les arcs périodiquement
- Le tout en SVG inline, taille compacte (48-64px), animé en CSS pur (pas de JS pour l'idle)

---

## Structure SVG

```html
<div id="aria-logo" class="logo-idle">
  <svg viewBox="0 0 64 64" width="48" height="48">
    <defs>
      <linearGradient id="logoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#6C8EFF"/>
        <stop offset="100%" stop-color="#A78BFA"/>
      </linearGradient>
    </defs>

    <!-- Arc externe -->
    <circle class="logo-arc logo-arc-1" cx="32" cy="32" r="29"
      fill="none" stroke="url(#logoGrad)" stroke-width="1.5"
      stroke-dasharray="100 82" stroke-linecap="round"/>

    <!-- Arc médian -->
    <circle class="logo-arc logo-arc-2" cx="32" cy="32" r="23"
      fill="none" stroke="rgba(108,142,255,0.5)" stroke-width="1.5"
      stroke-dasharray="70 75" stroke-linecap="round"/>

    <!-- Arc interne -->
    <circle class="logo-arc logo-arc-3" cx="32" cy="32" r="17"
      fill="none" stroke="rgba(167,139,250,0.4)" stroke-width="1"
      stroke-dasharray="50 56" stroke-linecap="round"/>

    <!-- Noyau central -->
    <circle class="logo-core" cx="32" cy="32" r="9" fill="url(#logoGrad)"/>

    <!-- Lettre A stylisée (forme triangulaire négative dans le noyau) -->
    <path class="logo-mark" d="M32 26 L37 38 L34 38 L32.5 34 L31.5 34 L30 38 L27 38 Z"
      fill="rgba(12,12,15,0.9)"/>
  </svg>
</div>
```

---

## Animations CSS (idle permanent)

```css
#aria-logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  filter: drop-shadow(0 0 8px rgba(108,142,255,0.3));
}

/* Rotation continue, vitesses différentes par anneau */
.logo-arc-1 {
  transform-origin: 32px 32px;
  animation: logoRotate1 12s linear infinite;
}
.logo-arc-2 {
  transform-origin: 32px 32px;
  animation: logoRotate2 8s linear infinite reverse;
}
.logo-arc-3 {
  transform-origin: 32px 32px;
  animation: logoRotate3 5s linear infinite;
}

@keyframes logoRotate1 { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
@keyframes logoRotate2 { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
@keyframes logoRotate3 { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* Pulsation douce du noyau */
.logo-core {
  animation: logoPulse 3s ease-in-out infinite;
  transform-origin: 32px 32px;
}
@keyframes logoPulse {
  0%, 100% { opacity: 0.85; transform: scale(1); }
  50%      { opacity: 1;    transform: scale(1.08); }
}
```

---

## États réactifs (idle / listening / thinking / speaking)

```css
/* IDLE — couleurs douces, rotation lente (par défaut, ci-dessus) */

/* LISTENING — accélération + teinte cyan */
.logo-listening .logo-arc-1,
.logo-listening .logo-arc-2,
.logo-listening .logo-arc-3 {
  animation-duration: 4s, 3s, 2s;
  filter: hue-rotate(-15deg);
}
.logo-listening #aria-logo,
#aria-logo.logo-listening {
  filter: drop-shadow(0 0 12px rgba(0,212,255,0.45));
}

/* THINKING — arcs en sens contraires plus rapides, teinte violette */
.logo-thinking .logo-arc-1 { animation-duration: 2s; }
.logo-thinking .logo-arc-2 { animation-duration: 1.6s; animation-direction: normal; }
.logo-thinking .logo-arc-3 { animation-duration: 1.2s; }
.logo-thinking #aria-logo {
  filter: drop-shadow(0 0 14px rgba(167,139,250,0.5));
}

/* SPEAKING — pulsation rapide du noyau, teinte verte */
.logo-speaking .logo-core {
  animation: logoPulseFast 0.6s ease-in-out infinite;
  fill: #4ADE80;
}
@keyframes logoPulseFast {
  0%, 100% { opacity: 0.8; transform: scale(1); }
  50%      { opacity: 1;   transform: scale(1.15); }
}
.logo-speaking #aria-logo {
  filter: drop-shadow(0 0 14px rgba(74,222,128,0.45));
}
```

---

## Effet "scan" périodique (balayage lumineux type JARVIS)

Un quatrième cercle invisible avec un dégradé qui tourne une fois toutes les ~6 secondes,
créant un effet de "scan radar" qui traverse les arcs :

```html
<defs>
  <linearGradient id="scanGrad" x1="0%" y1="0%" x2="100%" y2="0%">
    <stop offset="0%"  stop-color="rgba(108,142,255,0)"/>
    <stop offset="50%" stop-color="rgba(108,142,255,0.9)"/>
    <stop offset="100%" stop-color="rgba(108,142,255,0)"/>
  </linearGradient>
</defs>

<circle class="logo-scan" cx="32" cy="32" r="29"
  fill="none" stroke="url(#scanGrad)" stroke-width="2"
  stroke-dasharray="15 200" stroke-linecap="round"/>
```

```css
.logo-scan {
  transform-origin: 32px 32px;
  animation: logoScan 6s linear infinite;
  opacity: 0.8;
}
@keyframes logoScan {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
```

---

## Petits "tick marks" façon HUD (statique, décoratif)

8 petits traits radiaux autour du logo, statiques, qui s'illuminent un par un en séquence
pour évoquer un système qui s'initialise :

```html
<g class="logo-ticks">
  <line x1="32" y1="2" x2="32" y2="6" class="tick" style="--i:0"/>
  <line x1="32" y1="58" x2="32" y2="62" class="tick" style="--i:1"/>
  <line x1="2" y1="32" x2="6" y2="32" class="tick" style="--i:2"/>
  <line x1="58" y1="32" x2="62" y2="32" class="tick" style="--i:3"/>
  <!-- + 4 diagonales -->
</g>
```

```css
.tick {
  stroke: rgba(108,142,255,0.25);
  stroke-width: 1.5;
  stroke-linecap: round;
  animation: tickGlow 4s ease-in-out infinite;
  animation-delay: calc(var(--i) * 0.3s);
}
@keyframes tickGlow {
  0%, 80%, 100% { stroke: rgba(108,142,255,0.15); }
  10%           { stroke: rgba(108,142,255,0.8); }
}
```

---

## Intégration JS — synchronisation avec setStatus()

```javascript
setStatus(state) {
  // ... code existant ...

  const logo = document.getElementById('aria-logo');
  if (logo) {
    logo.classList.remove('logo-idle', 'logo-listening', 'logo-thinking', 'logo-speaking');
    const map = {
      idle: 'logo-idle',
      listening: 'logo-listening',
      transcribing: 'logo-listening',
      thinking: 'logo-thinking',
      speaking: 'logo-speaking',
    };
    logo.classList.add(map[state] || 'logo-idle');
  }
}
```

---

## Placement dans la sidebar

Remplace le texte "ARIA" seul par logo + texte côte à côte :

```html
<div style="display:flex; align-items:center; gap:10px; padding:16px 20px; border-bottom:1px solid var(--border)">
  <div id="aria-logo" class="logo-idle">
    <!-- SVG du logo ici -->
  </div>
  <div>
    <div id="assistant-name" style="font-size:16px; font-weight:600; color:var(--text); letter-spacing:1px">ARIA</div>
    <div id="status-text" style="font-size:11px; color:var(--text3)">En veille</div>
  </div>
</div>
```

---

## Variante : logo aussi utilisé comme icône d'avatar dans les bulles

Réutiliser une version simplifiée (sans les ticks, juste les arcs + noyau) à 24px comme
avatar dans `.bubble-avatar` à la place de la lettre "A" actuelle, pour cohérence visuelle.

```css
.bubble-avatar svg {
  width: 20px;
  height: 20px;
}
```

---

## Prompt Cursor

> Add an animated JARVIS-style logo to ARIA's sidebar, replacing the plain "ARIA" text logo.
>
> 1. Add this SVG structure in the sidebar header (replacing the current simple name display), keeping the assistant name text next to it:
>
> ```html
> <div style="display:flex;align-items:center;gap:10px;padding:16px 20px;border-bottom:1px solid var(--border)">
>   <div id="aria-logo" class="logo-idle">
>     <svg viewBox="0 0 64 64" width="44" height="44">
>       <defs>
>         <linearGradient id="logoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
>           <stop offset="0%" stop-color="#6C8EFF"/>
>           <stop offset="100%" stop-color="#A78BFA"/>
>         </linearGradient>
>         <linearGradient id="scanGrad" x1="0%" y1="0%" x2="100%" y2="0%">
>           <stop offset="0%" stop-color="rgba(108,142,255,0)"/>
>           <stop offset="50%" stop-color="rgba(108,142,255,0.9)"/>
>           <stop offset="100%" stop-color="rgba(108,142,255,0)"/>
>         </linearGradient>
>       </defs>
>       <g class="logo-ticks">
>         <line x1="32" y1="2" x2="32" y2="6" class="tick" style="--i:0"/>
>         <line x1="32" y1="58" x2="32" y2="62" class="tick" style="--i:1"/>
>         <line x1="2" y1="32" x2="6" y2="32" class="tick" style="--i:2"/>
>         <line x1="58" y1="32" x2="62" y2="32" class="tick" style="--i:3"/>
>         <line x1="11" y1="11" x2="14" y2="14" class="tick" style="--i:4"/>
>         <line x1="53" y1="11" x2="50" y2="14" class="tick" style="--i:5"/>
>         <line x1="11" y1="53" x2="14" y2="50" class="tick" style="--i:6"/>
>         <line x1="53" y1="53" x2="50" y2="50" class="tick" style="--i:7"/>
>       </g>
>       <circle class="logo-scan" cx="32" cy="32" r="29" fill="none" stroke="url(#scanGrad)" stroke-width="2" stroke-dasharray="15 200" stroke-linecap="round"/>
>       <circle class="logo-arc logo-arc-1" cx="32" cy="32" r="29" fill="none" stroke="url(#logoGrad)" stroke-width="1.5" stroke-dasharray="100 82" stroke-linecap="round"/>
>       <circle class="logo-arc logo-arc-2" cx="32" cy="32" r="23" fill="none" stroke="rgba(108,142,255,0.5)" stroke-width="1.5" stroke-dasharray="70 75" stroke-linecap="round"/>
>       <circle class="logo-arc logo-arc-3" cx="32" cy="32" r="17" fill="none" stroke="rgba(167,139,250,0.4)" stroke-width="1" stroke-dasharray="50 56" stroke-linecap="round"/>
>       <circle class="logo-core" cx="32" cy="32" r="9" fill="url(#logoGrad)"/>
>       <path class="logo-mark" d="M32 26 L37 38 L34 38 L32.5 34 L31.5 34 L30 38 L27 38 Z" fill="rgba(12,12,15,0.9)"/>
>     </svg>
>   </div>
>   <div>
>     <div id="assistant-name" style="font-size:16px;font-weight:600;color:var(--text);letter-spacing:1px">ARIA</div>
>     <div id="status-text" style="font-size:11px;color:var(--text3)">En veille</div>
>   </div>
> </div>
> ```
>
> 2. Add these CSS rules:
>
> ```css
> #aria-logo { display:inline-flex; align-items:center; justify-content:center; filter: drop-shadow(0 0 8px rgba(108,142,255,0.3)); flex-shrink:0; }
> .logo-arc-1 { transform-origin: 32px 32px; animation: logoRotate 12s linear infinite; }
> .logo-arc-2 { transform-origin: 32px 32px; animation: logoRotate 8s linear infinite reverse; }
> .logo-arc-3 { transform-origin: 32px 32px; animation: logoRotate 5s linear infinite; }
> @keyframes logoRotate { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
> .logo-core { animation: logoPulse 3s ease-in-out infinite; transform-origin: 32px 32px; }
> @keyframes logoPulse { 0%,100% { opacity:0.85; transform:scale(1); } 50% { opacity:1; transform:scale(1.08); } }
> .logo-scan { transform-origin: 32px 32px; animation: logoScan 6s linear infinite; opacity:0.8; }
> @keyframes logoScan { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
> .tick { stroke: rgba(108,142,255,0.25); stroke-width:1.5; stroke-linecap:round; animation: tickGlow 4s ease-in-out infinite; animation-delay: calc(var(--i) * 0.3s); }
> @keyframes tickGlow { 0%,80%,100% { stroke: rgba(108,142,255,0.15); } 10% { stroke: rgba(108,142,255,0.8); } }
>
> .logo-listening .logo-arc-1 { animation-duration: 4s; }
> .logo-listening .logo-arc-2 { animation-duration: 3s; }
> .logo-listening .logo-arc-3 { animation-duration: 2s; }
> .logo-listening { filter: drop-shadow(0 0 12px rgba(0,212,255,0.45)) !important; }
>
> .logo-thinking .logo-arc-1 { animation-duration: 2s; }
> .logo-thinking .logo-arc-2 { animation-duration: 1.6s; }
> .logo-thinking .logo-arc-3 { animation-duration: 1.2s; }
> .logo-thinking { filter: drop-shadow(0 0 14px rgba(167,139,250,0.5)) !important; }
>
> .logo-speaking .logo-core { animation: logoPulseFast 0.6s ease-in-out infinite; fill: #4ADE80; }
> @keyframes logoPulseFast { 0%,100% { opacity:0.8; transform:scale(1); } 50% { opacity:1; transform:scale(1.15); } }
> .logo-speaking { filter: drop-shadow(0 0 14px rgba(74,222,128,0.45)) !important; }
> ```
>
> 3. In setStatus(state), add logic to swap the logo's state class:
> ```javascript
> const logo = document.getElementById('aria-logo');
> if (logo) {
>   logo.classList.remove('logo-idle', 'logo-listening', 'logo-thinking', 'logo-speaking');
>   const map = { idle: 'logo-idle', listening: 'logo-listening', transcribing: 'logo-listening', thinking: 'logo-thinking', speaking: 'logo-speaking' };
>   logo.classList.add(map[state] || 'logo-idle');
> }
> ```
>
> 4. Replace the "A" letter avatar in .bubble-avatar with a small 20x20 version of the same SVG (arcs + core only, no ticks/scan, static — no animation needed for the small avatar version, just the gradient circle with the triangular mark).
>
> Only modify ui/index.html.
