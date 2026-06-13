# Assistant Vocal — Spec v8 : Refonte totale UI/UX

## Problèmes actuels
- Zone droite vide à 75% de l'écran
- Visualiseur trop petit, coincé en haut à gauche
- Presets moches en grille compacte
- Pas de zone de conversation visible
- Header trop chargé et mal équilibré
- Status bar basique

## Nouveau layout — centré sur le visualiseur

```
┌─────────────────────────────────────────────────────────────────┐
│  ◈ A · R · I · A    v2.0          🌤 18°C  |  12:36:01    [⚙][✕]│  header fin
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│              [VISUALISEUR CENTRAL ÉNORME]                        │
│         orbe 200px, particules, radar, waveform                  │
│                                                                  │
│    ✈ VOL   📚 ÉTUDE   🎮 GAMING   🎵 DÉTENTE   🌙 NUIT          │  presets sous l'orbe
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   [ZONE DE CONVERSATION — remplit tout l'espace restant]         │
│                                                                  │
│   🧑 Toi : texte transcrit...                    14:32          │
│                                                                  │
│   ◈ ARIA : réponse en temps réel token par token...             │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│        [🎤 gros bouton micro central pulsant]                    │  status bar
│  ◉ STANDBY...                          THEME  ⚙                 │
└─────────────────────────────────────────────────────────────────┘
```

## Règles de design

- **Pas de colonne gauche** — tout est centré ou plein largeur
- **Visualiseur occupe 40% de la hauteur** au centre
- **Zone conversation occupe 45% de la hauteur** sous le visualiseur
- **Status bar fine** en bas avec bouton micro central énorme
- **Presets** : ligne horizontale sous le visualiseur, pill buttons
- **Fond** : dégradé radial sombre depuis le centre (pas noir plat)

## Prompt Cursor

> Completely rewrite ui/index.html from scratch. The current design has a wasted right panel and poor layout. The new design must be:
>
> LAYOUT (single column, no side panels):
> - Full width header: "◈ A·R·I·A" left, weather+clock center, [⚙][✕] right. Height 48px.
> - Visualizer section: full width canvas, height = 40vh. The orb must be large (radius 120px minimum), centered. Radar circles, particles, sound rings all visible at full size.
> - Below visualizer: horizontal row of 5 preset pill buttons centered: ✈ Vol | 📚 Étude | 🎮 Gaming | 🎵 Détente | 🌙 Nuit
> - Conversation zone: full width, flex:1, scrollable. Chat bubbles left (ARIA) and right (user). Must fill all remaining vertical space between presets and status bar.
> - Status bar: height 72px, background surface. Center: large round mic button (64px, glowing when active). Left: status text. Right: THEME + ⚙ buttons.
>
> VISUAL STYLE:
> - Background: radial gradient from #080820 center to #04040F edges, not flat black
> - Accent color: #00D4FF cyan. Secondary: #7B2FFF purple.
> - Header: glassmorphism — backdrop-filter blur(10px), background rgba(8,8,24,0.85), border-bottom 1px solid rgba(0,212,255,0.3)
> - Title "A·R·I·A": font-size 20px, letter-spacing 8px, animated gradient cyan→purple→cyan cycling every 3s
> - All borders: 1px solid rgba(0,212,255,0.2), never solid opaque borders
> - Bubbles: glassmorphism — backdrop-filter blur(4px), semi-transparent backgrounds
> - Mic button: 64px circle, border 2px solid var(--accent), when active: box-shadow 0 0 20px 8px var(--accent), animation pulse 1s infinite
> - Preset pills: border-radius 999px, border 1px solid rgba(0,212,255,0.3), padding 6px 18px, hover: background rgba(0,212,255,0.15) border-color var(--accent)
> - Waveform: embedded directly below the orb inside the visualizer canvas, height 60px, mirrored oscilloscope
> - Scan lines overlay: ::after pseudo-element on body, subtle horizontal lines
> - Settings panel: slides from right, width 360px, glassmorphism background
>
> ANIMATIONS:
> - Title gradient cycles continuously
> - Orb radius interpolates smoothly with voice volume (min 100px, max 160px)
> - Orb color: cyan at silence, white at loud volume, smooth lerp
> - Mic button pulses when active (listening/thinking/speaking)
> - Bubbles animate in with translateY(12px)→0 + opacity 0→1 over 250ms
> - Particles (50) float continuously, burst outward on loud audio
> - Radar circles rotate at different speeds
> - Global glitch effect on title every 20-40s
>
> THEMES (6, switchable via CSS class on body):
> hologram (default), matrix, aurora, blood, gold, custom
> Each theme changes: --accent, --accent2, --bg, --surface, --text, --text2
>
> CRITICAL: 
> - NO side panels or columns — everything is full width stacked vertically
> - The conversation zone MUST be visible and fill available space
> - The visualizer canvas MUST be full width
> - Keep ALL existing JS API methods: show(), hide(), setStatus(), updateWaveform(), addUserBubble(), appendToken(), finalizeMessage(), showToast(), showError(), updateWeather()
> - Keep pywebview.api calls for quit_aria, toggle_activation, activate_preset, save_settings, load_settings, clear_history, open_file
>
> Generate the complete single-file index.html with all CSS and JS inline. This file will be long — that is expected. No placeholders.
