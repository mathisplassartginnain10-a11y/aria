# 03 — Animation System

## Orbe ARIA — Spécification complète

### Structure HTML
```html
<div class="orbe-container"> <!-- 200×200px -->
  <!-- Halos de glow (derrière) -->
  <div class="halo halo-outer"></div>
  <div class="halo halo-inner"></div>

  <!-- Anneaux concentriques -->
  <div class="ring ring-5"></div>  <!-- -20px, pointillé, 16s -->
  <div class="ring ring-4"></div>  <!-- -8px, pointillé, violet, 12s inverse -->
  <div class="ring ring-3"></div>  <!-- +5px, tirets, 12s inverse -->
  <div class="ring ring-2"></div>  <!-- +18px, arc partiel bleu, 6s -->
  <div class="ring ring-1"></div>  <!-- +30px, solide bleu, 8s -->

  <!-- Scan lines -->
  <div class="scan scan-blue"></div>   <!-- conic-gradient bleu, 2.5s -->
  <div class="scan scan-violet"></div> <!-- conic-gradient violet, 3s inverse -->

  <!-- Crosshair -->
  <div class="crosshair"></div>

  <!-- Tick marks (cercle externe) -->
  <div class="ticks"></div>

  <!-- Core -->
  <div class="orbe-core">
    <span class="orbe-letter">A</span>
  </div>
</div>
```

### CSS Orbe
```css
.orbe-container {
  position: relative;
  width: 200px; height: 200px;
  display: flex; align-items: center; justify-content: center;
}

/* Halos de glow */
.halo {
  position: absolute; border-radius: 50%; pointer-events: none;
}
.halo-outer {
  inset: -30px;
  background: radial-gradient(circle, rgba(100,150,255,0.08) 0%, transparent 70%);
  z-index: 0;
}
.halo-inner {
  inset: 10px;
  background: radial-gradient(circle, rgba(150,180,255,0.15) 0%, transparent 70%);
  z-index: 1;
}

/* Anneaux */
.ring {
  position: absolute; border-radius: 50%;
  border: 1.5px solid transparent;
  pointer-events: none;
}

.ring-1 {
  inset: 30px;
  border-color: rgba(150,180,255,0.7);
  animation: orbRotate 8s linear infinite;
}
.ring-2 {
  inset: 18px;
  border-top-color: rgba(100,140,255,0.8);
  border-right-color: rgba(100,140,255,0.8);
  border-bottom-color: transparent;
  border-left-color: transparent;
  animation: orbRotate 6s linear infinite;
}
.ring-3 {
  inset: 5px;
  border-color: rgba(180,160,255,0.5);
  border-style: dashed;
  border-width: 1px;
  animation: orbRotate 12s linear infinite reverse;
}
.ring-4 {
  inset: -8px;
  border-color: rgba(80,100,200,0.3);
  border-style: dotted;
  border-width: 1px;
  animation: orbRotate 16s linear infinite;
}
.ring-5 {
  inset: -20px;
  border-top-color: rgba(120,80,255,0.6);
  border-right-color: rgba(120,80,255,0.6);
  border-bottom-color: transparent;
  border-left-color: transparent;
  animation: orbRotate 4s linear infinite reverse;
}

/* Scan lines */
.scan {
  position: absolute; border-radius: 50%;
  mix-blend-mode: screen;
}
.scan-blue {
  inset: 18px;
  background: conic-gradient(from 0deg,
    transparent 0deg, rgba(150,200,255,0.5) 12deg, transparent 24deg);
  animation: orbRotate 2.5s linear infinite;
}
.scan-violet {
  inset: 30px;
  background: conic-gradient(from 180deg,
    transparent 0deg, rgba(180,120,255,0.4) 12deg, transparent 24deg);
  animation: orbRotate 3s linear infinite reverse;
}

/* Crosshair */
.crosshair {
  position: absolute;
  inset: 25px; z-index: 2; pointer-events: none;
}
.crosshair::before, .crosshair::after {
  content: '';
  position: absolute;
  background: rgba(100,200,255,0.4);
}
.crosshair::before {
  left: 50%; top: 0;
  width: 1px; height: 100%;
  transform: translateX(-50%);
}
.crosshair::after {
  top: 50%; left: 0;
  height: 1px; width: 100%;
  transform: translateY(-50%);
}

/* Core */
.orbe-core {
  width: 70px; height: 70px; border-radius: 50%;
  background: radial-gradient(circle,
    #ffffff 0%, #a0c0ff 25%, #6080ff 50%, #3040c0 80%, #1020a0 100%);
  position: relative; z-index: 3;
  box-shadow:
    0 0 30px rgba(100,150,255,0.9),
    0 0 60px rgba(80,120,255,0.5),
    0 0 90px rgba(60,80,200,0.3);
  display: flex; align-items: center; justify-content: center;
}
.orbe-letter {
  font-size: 26px; font-weight: 900; color: white;
  text-shadow: 0 0 10px rgba(255,255,255,0.8);
}

@keyframes orbRotate {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
```

## États de l'orbe

### IDLE (en veille)
```css
.orbe-idle .ring-1 { opacity: 0.5; animation-duration: 10s; }
.orbe-idle .ring-2 { opacity: 0.4; }
.orbe-idle .ring-3 { opacity: 0.3; }
.orbe-idle .ring-4 { opacity: 0.15; }
.orbe-idle .ring-5 { opacity: 0.2; }
.orbe-idle .scan-blue { opacity: 0.4; animation-duration: 4s; }
.orbe-idle .scan-violet { opacity: 0.2; }
.orbe-idle .orbe-core {
  animation: coreBreath 4s ease-in-out infinite;
}
@keyframes coreBreath {
  0%,100% { box-shadow: 0 0 30px rgba(100,150,255,0.9), 0 0 60px rgba(80,120,255,0.5), 0 0 90px rgba(60,80,200,0.3); transform: scale(1); }
  50%     { box-shadow: 0 0 40px rgba(100,150,255,1.0), 0 0 80px rgba(80,120,255,0.7), 0 0 120px rgba(60,80,200,0.4); transform: scale(1.04); }
}
```

### LISTENING (écoute micro)
```css
.orbe-listening .ring-1 { opacity: 1; animation-duration: 6s; border-color: rgba(74,222,128,0.7); }
.orbe-listening .ring-2 { opacity: 1; animation-duration: 4s; }
.orbe-listening .ring-3 { opacity: 0.7; }
.orbe-listening .ring-4 { opacity: 0.4; }
.orbe-listening .ring-5 { opacity: 0.5; animation-duration: 3s; }
.orbe-listening .scan-blue { opacity: 1; animation-duration: 1.5s; }
.orbe-listening .orbe-core {
  background: radial-gradient(circle, #ffffff 0%, #80ffb0 25%, #40c070 50%, #108040 80%, #054020 100%);
  box-shadow: 0 0 30px rgba(74,222,128,0.9), 0 0 60px rgba(74,222,128,0.5), 0 0 90px rgba(74,222,128,0.3);
  animation: coreListenPulse 1.2s ease-in-out infinite;
}
@keyframes coreListenPulse {
  0%,100% { transform: scale(1); }
  50%     { transform: scale(1.06); }
}
```

### THINKING (réflexion LLM)
```css
.orbe-thinking .ring-1 { opacity: 1; animation-duration: 2s; }
.orbe-thinking .ring-2 { opacity: 1; animation-duration: 1.5s; }
.orbe-thinking .ring-3 { opacity: 0.9; animation-duration: 1s; }
.orbe-thinking .ring-4 { opacity: 0.6; animation-duration: 0.8s; }
.orbe-thinking .ring-5 { opacity: 0.7; animation-duration: 0.6s; }
.orbe-thinking .scan-blue { opacity: 1; animation-duration: 0.8s; }
.orbe-thinking .scan-violet { opacity: 0.8; animation-duration: 1s; }
.orbe-thinking .orbe-core {
  background: radial-gradient(circle, #ffffff 0%, #d0b0ff 25%, #9060ff 50%, #5030c0 80%, #2010a0 100%);
  box-shadow: 0 0 40px rgba(167,139,250,0.9), 0 0 80px rgba(167,139,250,0.6), 0 0 120px rgba(167,139,250,0.3);
  animation: coreThink 0.6s ease-in-out infinite;
}
@keyframes coreThink {
  0%,100% { transform: scale(1); }
  50%     { transform: scale(1.08); }
}
```

### SPEAKING (parole TTS)
```css
/* Réactif au volume RMS */
.orbe-speaking .ring-1 { opacity: 1; animation-duration: 3s; border-color: rgba(74,222,128,0.8); }
.orbe-speaking .scan-blue { opacity: 0.8; animation-duration: 2s; }
.orbe-speaking .orbe-core {
  background: radial-gradient(circle, #ffffff 0%, #b0ffb0 25%, #60e060 50%, #20a020 80%, #105010 100%);
  box-shadow: 0 0 35px rgba(74,222,128,0.9), 0 0 70px rgba(74,222,128,0.5);
}
/* Le scale du core est animé via JS selon le RMS audio */
```

## Animations globales

### Spring physics (pour tous les éléments)
```javascript
// Utiliser Framer Motion ou CSS spring
const springConfig = {
  type: "spring",
  stiffness: 400,
  damping: 30,
  mass: 0.8,
};
```

### Transition page home → conversation
```css
/* Logo se réduit */
.orbe-container.shrunk {
  transform: scale(0.45);
  margin-bottom: -40px;
  transition: all 0.5s cubic-bezier(0.34, 1.2, 0.64, 1);
}
/* Texte hello disparaît */
.hello-text.shrunk { opacity: 0; transform: translateY(-10px); transition: all 0.3s; }
/* Zone messages apparaît */
.messages-zone { animation: fadeInUp 0.4s ease; }
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

### Micro-animations obligatoires
- Chaque nav-item : hover avec `transform: translateX(3px)` spring
- Bouton mic : hover `transform: scale(1.08)`, press `scale(0.95)`
- Widget cards : hover `border-color` transition 0.2s
- Bulles de chat : entrée `fadeInUp` 0.3s
- Tokens LLM streaming : chaque token fade-in 0.1s

## Sons (optionnels mais premium)
```javascript
const sounds = {
  activate: new Audio('sounds/activate.mp3'),    // 80ms, subtil
  listening: new Audio('sounds/listening.mp3'),  // 120ms, doux
  response: new Audio('sounds/response.mp3'),    // 100ms, confirmation
};
// Volume: 0.15 max
```
