# 01 — UI Bible

## Layout 3 colonnes

```
┌──────────────┬────────────────────────────┬───────────────┐
│  Sidebar     │     Zone principale        │  Widgets      │
│  (230px)    │     (flex: 1)             │  (265px)      │
│              │                            │               │
│  Logo ARIA   │  [Orbe ARIA central]       │  Résumé jour  │
│  ──────────  │  Bonjour, Mathis.          │  Mémoire      │
│  🏠 Accueil  │  Comment puis-je aider ?   │  Raccourcis   │
│  💬 Convs    │                            │               │
│  🧠 Mémoire  │  [Messages chat]           │               │
│  🤖 Agents   │                            │               │
│  ⚡ Routines │  [Input zone]              │               │
│  ─────────── │                            │               │
│  🤖 Agent    │                            │               │
│  ⚙️ Params   │                            │               │
└──────────────┴────────────────────────────┴───────────────┘
```

## Couleurs exactes (référence mockup ChatGPT)

```css
--bg-deep:        #060B1A;   /* fond principal bleu nuit */
--bg-sidebar:     rgba(8,12,28,0.7);
--bg-widgets:     rgba(8,12,28,0.6);
--bg-main:        transparent; /* gradient radial par-dessus */
--accent-blue:    #4060FF;
--accent-violet:  #8060E0;
--accent-text:    #4488FF;   /* "Bonjour." */
--border-subtle:  rgba(255,255,255,0.06);
--text-primary:   #FFFFFF;
--text-secondary: rgba(255,255,255,0.55);
--text-muted:     rgba(255,255,255,0.3);
```

## Fond principal

```css
background: #060B1A;
/* gradient par-dessus : */
background: 
  radial-gradient(ellipse 80% 60% at 60% 30%, rgba(15,35,90,0.8) 0%, transparent 70%),
  radial-gradient(ellipse 40% 40% at 75% 10%, rgba(20,60,140,0.5) 0%, transparent 60%),
  #060B1A;
```

## Sidebar

```css
background: rgba(8,12,28,0.7);
backdrop-filter: blur(20px) saturate(180%);
border-right: 1px solid rgba(255,255,255,0.06);
```

### Logo ARIA en sidebar
- Cercle 42px avec bordure rgba(108,142,255,0.4)
- "A" blanc en gras, fond gradient bleu foncé
- 2 anneaux rotatifs autour (8s et 12s, inverse)

### Navigation
```css
.nav-item {
  padding: 11px 14px;
  border-radius: 14px;
  font-size: 13px;
  font-weight: 500;
  color: rgba(255,255,255,0.45);
}
.nav-item.active {
  background: rgba(80,100,220,0.25);
  color: #FFFFFF;
  font-weight: 600;
}
```

## Zone principale — Page Accueil

### Header
- Badge "🔒 Mode Privé ▾" centré en haut
- Bouton micro 🎙 en haut à droite
- Background: transparent (laisse voir le fond bleu)

### Orbe ARIA (voir 03_ANIMATION_SYSTEM.md)
- Centré verticalement et horizontalement
- Noyau : 70px, radial gradient blanc→bleu→violet→bleu foncé
- Box-shadow triple glow bleu
- 5 anneaux concentriques avec animations différentes
- 2 scan lines rotatifs (mix-blend-mode: screen)
- Crosshair lines (lignes bleues en croix)

### Texte sous l'orbe
```css
.hello-text {
  font-size: 38px;
  font-weight: 800;
  color: #4488FF;
  text-shadow: 0 0 30px rgba(80,150,255,0.5);
}
.sub-text {
  font-size: 14px;
  color: rgba(255,255,255,0.4);
}
```

### Input zone
```css
background: rgba(20,30,70,0.5);
border: 1px solid rgba(80,110,220,0.2);
border-radius: 16px;
backdrop-filter: blur(10px);
```
Contient :
1. Textarea "Demandez à ARIA..." (ligne 1)
2. Row 2 : bouton "+" | sélecteur "🤖 Assistant Avancé ▾" | bouton micro rond violet

## Widgets droite

```css
background: rgba(8,12,28,0.6);
backdrop-filter: blur(20px);
border-left: 1px solid rgba(255,255,255,0.06);
```

### Widget card
```css
background: rgba(255,255,255,0.03);
border: 1px solid rgba(255,255,255,0.07);
border-radius: 14px;
```

### Widget Résumé du jour
Rows : ✅ tâches | 🔔 rappels | 🌤 météo (vraie) | ⚡ énergie (batterie)

### Widget Mémoire
- Donut chart canvas 110x110
- Gradient bleu→violet
- Stats : conversations, messages
- Bouton "Optimiser"

### Widget Raccourcis
- Grille 2×2
- ✉️ Rédiger un email | 🎯 Démarrer focus
- 📊 Analyse système | 🌙 Routine Soir
