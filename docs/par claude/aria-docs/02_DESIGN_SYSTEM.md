# 02 — Design System

## Typographie

```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;

/* Tailles */
--fs-xs:   9px;
--fs-sm:   10px;
--fs-base: 12px;
--fs-md:   13px;
--fs-lg:   14px;
--fs-xl:   17px;
--fs-2xl:  20px;
--fs-3xl:  26px;
--fs-4xl:  32px;
--fs-hero: 38px;

/* Poids */
--fw-normal: 400;
--fw-medium: 500;
--fw-semibold: 600;
--fw-bold: 700;
--fw-black: 800;
```

## Couleurs complètes

```css
:root {
  /* Backgrounds */
  --bg-app:      #060B1A;
  --bg-sidebar:  rgba(8,12,28,0.70);
  --bg-widgets:  rgba(8,12,28,0.60);
  --bg-card:     rgba(255,255,255,0.03);
  --bg-input:    rgba(20,30,70,0.50);
  --bg-pill:     rgba(20,30,80,0.60);
  --bg-nav-act:  rgba(80,100,220,0.25);
  --bg-btn-mic:  linear-gradient(135deg,#5060E0,#7080FF);

  /* Borders */
  --border-app:    rgba(255,255,255,0.06);
  --border-card:   rgba(255,255,255,0.07);
  --border-input:  rgba(80,110,220,0.20);
  --border-pill:   rgba(100,130,255,0.20);
  --border-logo:   rgba(108,142,255,0.40);

  /* Text */
  --text-primary:   #FFFFFF;
  --text-secondary: rgba(255,255,255,0.55);
  --text-muted:     rgba(255,255,255,0.35);
  --text-hint:      rgba(255,255,255,0.25);
  --text-accent:    #4488FF;
  --text-nav:       rgba(255,255,255,0.45);
  --text-nav-act:   #FFFFFF;

  /* Accents */
  --accent-blue:    #4060FF;
  --accent-violet:  #8060E0;
  --accent-cyan:    #40C0FF;
  --accent-glow:    rgba(100,150,255,0.90);

  /* Glass */
  --glass-blur:  20px;
  --glass-sat:   180%;
}
```

## Thèmes (personnalisables dans paramètres)

```css
[data-theme="slate"]  { --accent-blue: #4060FF; --accent-violet: #8060E0; }
[data-theme="warm"]   { --accent-blue: #FF8040; --accent-violet: #E06020; }
[data-theme="forest"] { --accent-blue: #40C060; --accent-violet: #20A040; }
[data-theme="rose"]   { --accent-blue: #FF6080; --accent-violet: #E04060; }
[data-theme="mono"]   { --accent-blue: #808080; --accent-violet: #606060; }
```

## Border radius

```css
--radius-sm: 8px;
--radius-md: 10px;
--radius-lg: 14px;
--radius-xl: 16px;
--radius-2xl: 20px;
--radius-pill: 9999px;
```

## Shadows & Glows

```css
/* Glow orbe */
--glow-core: 0 0 30px rgba(100,150,255,0.9), 0 0 60px rgba(80,120,255,0.5), 0 0 90px rgba(60,80,200,0.3);

/* Glow logo sidebar */
--glow-logo: 0 0 12px rgba(108,142,255,0.5);

/* Glow mic button */
--glow-mic: 0 0 15px rgba(80,100,255,0.4);
```

## Composants réutilisables

### Pill badge
```css
.pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 16px;
  background: var(--bg-pill);
  border: 1px solid var(--border-pill);
  border-radius: var(--radius-pill);
  font-size: 12px;
  color: rgba(255,255,255,0.7);
  backdrop-filter: blur(10px);
  cursor: pointer;
}
```

### Bouton micro rond
```css
.mic-round {
  width: 36px; height: 36px;
  border-radius: 50%;
  background: var(--bg-btn-mic);
  border: none;
  color: white;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px;
  box-shadow: var(--glow-mic);
}
```

### Widget card
```css
.widget {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.widget-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 11px 14px;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  font-size: 12px; font-weight: 600;
  color: rgba(255,255,255,0.6);
  letter-spacing: 0.3px;
}
```
