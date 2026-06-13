# Assistant Vocal — Spec v10 : Design JARVIS-level

## Inspiration
- JARVIS (Iron Man) : arcs rotatifs, HUD éléments, données en overlay
- Figma "Voice Assistant Futuristic" : glassmorphism, panneaux flottants
- Dashboard sombre avec éléments lumineux réactifs à la voix

## Prompt Cursor

> Rewrite ui/index.html completely with a stunning JARVIS-inspired sci-fi design. This must look like a real futuristic AI interface, not a basic dark website.
>
> ## LAYOUT (single column, full screen)
>
> ```
> ┌─────────────────────────────────────────────────────┐
> │  HUD TOP BAR (32px) — coordinates, time, status     │
> ├─────────────────────────────────────────────────────┤
> │                                                      │
> │              VISUALIZER (45vh)                       │
> │   JARVIS-style: rotating arcs + reactive orb        │
> │   + circular waveform + HUD overlays                │
> │                                                      │
> ├─────────────────────────────────────────────────────┤
> │   PRESET PILLS (44px) — horizontal centered         │
> ├─────────────────────────────────────────────────────┤
> │                                                      │
> │   CONVERSATION (flex:1, scrollable)                  │
> │   glassmorphism bubbles, tokens real-time           │
> │                                                      │
> ├─────────────────────────────────────────────────────┤
> │   TEXT INPUT (56px) — pill input + send button      │
> ├─────────────────────────────────────────────────────┤
> │   STATUS BAR (64px) — mic button + status + btns    │
> └─────────────────────────────────────────────────────┘
> ```
>
> ## VISUALIZER (the centerpiece — must be spectacular)
>
> Full-width canvas (45vh height). Everything drawn with canvas 2D API:
>
> **Background of canvas:**
> - Deep space: radial gradient `#000510` center → `#000008` edges
> - Subtle star field: 80 static dots of varying sizes and opacity
>
> **Orb (center):**
> - Base radius: lerps between 60px (silence) and 100px (loud voice)
> - Fill: radial gradient from `rgba(0,212,255,0.9)` center to `rgba(0,100,180,0.3)` edge
> - Outer glow: 3 concentric circles with decreasing opacity (0.4, 0.2, 0.08) and increasing radius (+15, +30, +50)
> - Color shifts: cyan at idle, white-cyan at medium volume, pure white at max volume
> - All transitions use lerp factor 0.08 for ultra-smooth animation
>
> **JARVIS rotating arcs (most important visual element):**
> - Arc 1: radius 130px, arc span 240°, rotates clockwise at 0.4°/frame, stroke 1.5px cyan, opacity 0.7
> - Arc 2: radius 160px, arc span 180°, rotates counter-clockwise at 0.6°/frame, stroke 1px cyan, opacity 0.5
> - Arc 3: radius 195px, arc span 120°, rotates clockwise at 0.3°/frame, stroke 0.5px cyan, opacity 0.35
> - Each arc has 4 "tick marks" (small perpendicular lines 6px long) spaced along it
> - Arc color shifts to purple (#7B2FFF) when ARIA is thinking, green (#00FF88) when speaking
>
> **Circular waveform (around the orb):**
> - Ring of 128 bars arranged in a circle at radius 115px
> - Each bar extends outward from the ring
> - Height of each bar = RMS value mapped to 0-25px
> - Color: cyan to white based on height
> - When idle: subtle breathing animation (bars oscillate gently with sin waves)
> - When speaking: bars animate with fake frequency data (sin waves at different frequencies)
>
> **HUD overlay elements (drawn on canvas):**
> - Top-left corner bracket: `┌` style lines 40px each side, cyan, opacity 0.4
> - Top-right corner bracket: `┐` style
> - Bottom-left: `└` style
> - Bottom-right: `┘` style
> - Left side text (10px Courier, cyan 0.4 opacity): "SYS.AUDIO" / RMS value / "FREQ.ANAL"
> - Right side text: "LAT: 47.22N" / "LON: 1.73W" / "ALT: 12M"
> - Bottom center: horizontal scan line that moves up slowly (opacity 0.06)
>
> **Sound rings (when speaking):**
> - Concentric rings expand from orb center
> - Born at orb radius, expand to 200px, fade from 0.8 to 0
> - Speed proportional to voice volume
> - Color: green (#00FF88)
>
> **Particles:**
> - 60 particles floating slowly
> - On loud audio: burst outward from center, return slowly
> - Color: cyan, opacity 0.3-0.7
>
> **Status text below orb:**
> - "S T A N D B Y" with letter spacing, reveal letter by letter on status change
> - 11px Courier, cyan, subtle pulse opacity
>
> ## HUD TOP BAR
> ```css
> #hud-bar {
>   height: 32px;
>   background: rgba(0,8,20,0.9);
>   border-bottom: 1px solid rgba(0,212,255,0.15);
>   display: flex;
>   align-items: center;
>   justify-content: space-between;
>   padding: 0 20px;
>   font-size: 10px;
>   color: rgba(0,212,255,0.5);
>   letter-spacing: 2px;
>   font-family: 'Courier New';
> }
> ```
> Content: left = "ARIA SYS v2.0 | NODE: LOCAL | ENC: AES-256", center = "A · R · I · A" (animated gradient, 14px, letter-spacing 6px), right = clock + weather
>
> ## MAIN TITLE STYLE
> - Font: Courier New Bold, 14px in HUD bar
> - Letter spacing: 6px
> - Animated gradient: background-clip text, cyan→purple→cyan cycling 4s
> - Subtle glitch every 20-40s: translateX ±3px for 100ms + hue-rotate
>
> ## GLASSMORPHISM PANELS
> All panels (conversation, settings, presets) use:
> ```css
> background: rgba(4, 8, 20, 0.75);
> backdrop-filter: blur(12px);
> -webkit-backdrop-filter: blur(12px);
> border: 1px solid rgba(0, 212, 255, 0.15);
> box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(0,212,255,0.1);
> ```
>
> ## CONVERSATION BUBBLES
>
> User bubble:
> ```css
> background: rgba(0, 212, 255, 0.08);
> border: 1px solid rgba(0, 212, 255, 0.25);
> border-radius: 12px 2px 12px 12px;
> backdrop-filter: blur(8px);
> box-shadow: 0 0 20px rgba(0,212,255,0.05);
> ```
>
> ARIA bubble:
> ```css
> background: rgba(123, 47, 255, 0.08);
> border: 1px solid rgba(123, 47, 255, 0.25);
> border-radius: 2px 12px 12px 12px;
> backdrop-filter: blur(8px);
> box-shadow: 0 0 20px rgba(123,47,255,0.05);
> ```
>
> Bubble animation: `@keyframes bubbleIn { from { opacity:0; transform: translateY(16px) scale(0.97) } to { opacity:1; transform: translateY(0) scale(1) } }` duration 300ms cubic-bezier(0.34, 1.56, 0.64, 1)
>
> Streaming cursor: `|` blinking, color var(--accent2), inserted before end of text
>
> ## PRESET PILLS
> ```css
> .preset-pill {
>   background: rgba(0,212,255,0.05);
>   border: 1px solid rgba(0,212,255,0.2);
>   border-radius: 999px;
>   padding: 7px 20px;
>   font-size: 12px;
>   letter-spacing: 1px;
>   cursor: pointer;
>   transition: all 0.2s;
>   color: rgba(232,244,255,0.7);
> }
> .preset-pill:hover {
>   background: rgba(0,212,255,0.15);
>   border-color: #00D4FF;
>   color: #E8F4FF;
>   box-shadow: 0 0 16px rgba(0,212,255,0.2);
> }
> .preset-pill.active {
>   background: rgba(0,212,255,0.2);
>   border-color: #00D4FF;
>   box-shadow: 0 0 20px rgba(0,212,255,0.3);
> }
> ```
>
> ## TEXT INPUT
> ```css
> #text-input-zone {
>   padding: 10px 24px;
>   background: rgba(0,4,12,0.8);
>   border-top: 1px solid rgba(0,212,255,0.1);
>   display: flex;
>   gap: 12px;
>   align-items: center;
> }
> #text-input {
>   flex: 1;
>   background: rgba(0,212,255,0.04);
>   border: 1px solid rgba(0,212,255,0.2);
>   border-radius: 28px;
>   padding: 12px 24px;
>   color: #E8F4FF;
>   font-family: 'Courier New', monospace;
>   font-size: 13px;
>   outline: none;
>   transition: all 0.25s;
>   letter-spacing: 0.5px;
> }
> #text-input::placeholder { color: rgba(102,136,170,0.6); }
> #text-input:focus {
>   border-color: rgba(0,212,255,0.6);
>   background: rgba(0,212,255,0.07);
>   box-shadow: 0 0 0 3px rgba(0,212,255,0.08), 0 0 20px rgba(0,212,255,0.1);
> }
> #send-btn {
>   width: 46px; height: 46px;
>   border-radius: 50%;
>   background: rgba(0,212,255,0.1);
>   border: 1px solid rgba(0,212,255,0.4);
>   color: #00D4FF;
>   font-size: 16px;
>   cursor: pointer;
>   transition: all 0.2s;
>   display: flex; align-items: center; justify-content: center;
> }
> #send-btn:hover {
>   background: rgba(0,212,255,0.2);
>   box-shadow: 0 0 20px rgba(0,212,255,0.3);
>   transform: scale(1.05);
> }
> ```
>
> ## STATUS BAR
> ```css
> #status-bar {
>   height: 64px;
>   background: rgba(0,4,12,0.9);
>   border-top: 1px solid rgba(0,212,255,0.15);
>   display: flex;
>   align-items: center;
>   justify-content: space-between;
>   padding: 0 24px;
> }
> #mic-btn {
>   width: 52px; height: 52px;
>   border-radius: 50%;
>   background: rgba(0,212,255,0.08);
>   border: 2px solid rgba(0,212,255,0.4);
>   color: #00D4FF;
>   font-size: 22px;
>   cursor: pointer;
>   transition: all 0.3s;
>   position: absolute;
>   left: 50%;
>   transform: translateX(-50%);
> }
> #mic-btn.active {
>   background: rgba(0,212,255,0.15);
>   border-color: #00D4FF;
>   box-shadow: 0 0 0 0 rgba(0,212,255,0.4);
>   animation: micPulse 1.2s ease-in-out infinite;
> }
> @keyframes micPulse {
>   0% { box-shadow: 0 0 0 0 rgba(0,212,255,0.4); }
>   70% { box-shadow: 0 0 0 16px rgba(0,212,255,0); }
>   100% { box-shadow: 0 0 0 0 rgba(0,212,255,0); }
> }
> ```
>
> ## STATUS INDICATOR
> Small dot left of status text, color changes with state:
> - idle: rgba(102,136,170,0.5)
> - listening: #00D4FF with pulse animation
> - transcribing: #FFB800 with fast pulse
> - thinking: #7B2FFF with medium pulse
> - speaking: #00FF88 with slow pulse
>
> Status text format: "◉ STANDBY..." with animated dots
>
> ## SETTINGS PANEL (slide from right)
> Width 380px, glassmorphism background, slides in 300ms cubic-bezier
> All existing settings preserved (themes, audio, assistant, system)
> Close button top right
>
> ## QUIT CONFIRMATION MODAL
> Dark overlay with blur, centered card, "Fermer ARIA ?" with Oui/Annuler buttons
>
> ## THEMES (6, via CSS custom properties on body)
> - hologram: accent=#00D4FF, accent2=#7B2FFF (default)
> - matrix: accent=#00FF41, accent2=#00AA22, bg=#000800
> - aurora: accent=#7B2FFF, accent2=#00D4FF, bg=#060612
> - blood: accent=#FF0040, accent2=#AA0028, bg=#0A0004
> - gold: accent=#FFD700, accent2=#B8860B, bg=#0A0800
> - midnight: accent=#4488FF, accent2=#0044AA, bg=#000010
>
> ## BODY BACKGROUND
> ```css
> body {
>   background: radial-gradient(ellipse at 50% 40%, #050518 0%, #020208 60%, #010105 100%);
>   min-height: 100vh;
> }
> ```
>
> ## SCAN LINES EFFECT
> ```css
> body::before {
>   content: '';
>   position: fixed;
>   inset: 0;
>   background: repeating-linear-gradient(
>     0deg,
>     transparent,
>     transparent 3px,
>     rgba(0,212,255,0.012) 3px,
>     rgba(0,212,255,0.012) 4px
>   );
>   pointer-events: none;
>   z-index: 1000;
> }
> ```
>
> ## CRITICAL REQUIREMENTS
> - Keep ALL existing JS API: show(), hide(), setStatus(), updateWaveform(rms), addUserBubble(text), appendToken(token), finalizeMessage(), showToast(msg, type, duration), showError(text), updateWeather(text)
> - Keep pywebview.api calls: quit_aria, toggle_activation, activate_preset, send_text, save_settings, load_settings, clear_history, open_file
> - The visualizer MUST update at 60fps via requestAnimationFrame
> - The circular waveform MUST react to updateWaveform(rms) calls
> - The orb MUST smoothly resize with voice volume
> - Enter key in text input sends message
> - Settings panel preserved with all controls
> - Quit confirmation modal on ✕ click
>
> Generate the complete single-file index.html. This is the most important file. Make it spectacular. No placeholders.
