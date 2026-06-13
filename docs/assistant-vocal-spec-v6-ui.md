# Assistant Vocal — Spec v6 : Interface Sci-Fi Ultra Avancée

## Vision

Interface holographique sci-fi qui réagit en temps réel à la voix. Chaque élément est vivant — les couleurs pulsent, les particules bougent, le texte glitch. L'utilisateur doit avoir l'impression d'utiliser une IA du futur. Entièrement personnalisable via un panneau de thème intégré.

---

## Stack technique UI

- `tkinter` pour la fenêtre de base (sans bordure)
- `pygame` pour le rendu canvas haute performance (waveform, particules, radar)
- `PIL/Pillow` pour les effets visuels (flou, glow, glitch)
- `numpy` pour les calculs audio temps réel
- Animations via boucles `root.after()` à 60fps
- Effets glitch via manipulation pixel par pixel PIL

---

## Dimensions et positionnement

- Taille par défaut : 520×780px
- Redimensionnable par drag des bords (min 400×600, max 800×1000)
- Draggable librement sur tout l'écran
- Position sauvegardée dans `data/ui_state.json` à la fermeture
- Restaurée à la position précédente au prochain lancement
- Mode compact : 320×120px (juste waveform + statut) via double-clic sur le header
- Mode plein écran : touche `F11` quand la fenêtre est focus

---

## Thème par défaut : "HOLOGRAM"

Palette de base :
```
background:      #04040F   (noir quasi-pur, légère teinte bleue)
surface:         #080818   (cartes et panneaux)
accent_primary:  #00D4FF   (cyan holographique)
accent_secondary:#7B2FFF   (violet quantique)
accent_alert:    #FF3366   (rouge alerte)
accent_success:  #00FF88   (vert confirmation)
text_primary:    #E8F4FF   (blanc froid)
text_secondary:  #6688AA   (gris bleuté)
glow_color:      #00D4FF   (couleur du halo)
```

Thèmes alternatifs inclus (switchables en temps réel) :
- **MATRIX** : vert `#00FF41` sur noir, police monospace, pluie de caractères
- **AURORA** : dégradé violet→cyan→vert qui tourne lentement
- **BLOOD** : rouge `#FF0040` sur noir, ambiance danger
- **GOLD** : or `#FFD700` sur noir profond, style luxe
- **CUSTOM** : couleurs 100% personnalisables via color pickers

---

## Structure visuelle complète

```
┌─────────────────────────────────────────────────────┐
│  ┌─────────────────────────────────────────────────┐│
│  │  ◈ A·R·I·A          v2.0    [≡] [◉] [⊡] [✕]   ││  ← header
│  └─────────────────────────────────────────────────┘│
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │   ╔══════════════════════════════════════╗   │   │
│  │   ║                                      ║   │   │
│  │   ║        [VISUALISEUR CENTRAL]         ║   │   │
│  │   ║     cercle radar + orbe pulsant      ║   │   │
│  │   ║        réagit à la voix              ║   │   │
│  │   ║                                      ║   │   │
│  │   ╚══════════════════════════════════════╝   │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │  [WAVEFORM OSCILLOSCOPE]  ████▓▒░  ░▒▓████   │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │                                              │   │
│  │   🧑  [bulle utilisateur]          14:32    │   │
│  │                                              │   │
│  │   ◈   [bulle ARIA — tokens temps réel]      │   │
│  │                                              │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │  ◉ ÉCOUTE ACTIVE    [MIC] [VOL] [THEME] [⚙] │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

---

## Composant 1 : Header holographique

### Titre "A·R·I·A"
- Police : `Courier New Bold` 18px
- Effet glitch permanent léger : toutes les 3-8 secondes, les lettres se décalent aléatoirement de 1-3px pendant 80ms, avec une ligne horizontale colorée qui traverse le titre
- Couleur : dégradé horizontal cyan→violet animé (la position du dégradé se déplace lentement)
- Halo glow derrière les lettres via PIL (blur gaussien de la même couleur)

### Indicateur d'état (◈)
- Symbole hexagonal animé
- `idle` : contour cyan fin, rotation lente 360° en 4s
- `listening` : pulsation rapide cyan, scale 1.0→1.4→1.0 en 0.6s, couleur change dynamiquement selon le volume (cyan→blanc à fort volume)
- `transcribing` : rotation rapide jaune, effet "chargement"
- `thinking` : orbite de 3 points autour du centre, violet
- `speaking` : barres verticales qui bougent au rythme du TTS, vert

### Boutons header
- `[≡]` : ouvre panneau settings
- `[◉]` : ouvre popup presets
- `[⊡]` : mode compact/plein
- `[✕]` : désactive ARIA (équivalent F24)
- Style : fond transparent, contour `1px accent_primary`, hover → fond `accent_primary 20%`, transition 150ms
- Légère animation glitch au hover

---

## Composant 2 : Visualiseur central (LE PIÈCE MAÎTRESSE)

Canvas pygame `480×200px` embarqué dans tkinter via `pygame.display.set_mode` dans un frame.

### Orbe central réactif
- Cercle principal de rayon 50px au centre
- Couleur : cyan par défaut
- **Réagit à la voix en temps réel** :
  - Volume faible → rayon 45px, couleur cyan froid `#00AACC`
  - Volume moyen → rayon 60px, couleur cyan `#00D4FF`, halo visible
  - Volume fort → rayon 80px, couleur blanc chaud `#AADDFF`, halo intense
  - La transition est fluide (lerp 0.15 par frame)
- Halo glow multicouche : 3 cercles concentriques avec opacité décroissante (40%, 20%, 10%)
- Rotation d'un anneau fin autour de l'orbe (vitesse proportionnelle au volume)

### Cercles radar
- 3 cercles concentriques pointillés autour de l'orbe
- Rotation lente et continue (vitesses différentes : 0.3°/frame, 0.5°/frame, 0.8°/frame)
- Chaque cercle a 4-8 "ticks" (petites lignes radiales) qui tournent avec lui
- Couleur : `accent_primary` à 30% d'opacité

### Ondes sonores
- Quand ARIA parle : anneaux concentriques qui partent du centre vers l'extérieur
- Comme des ondes dans l'eau
- Chaque anneau naît transparent au centre, grandit, et s'estompe
- Vitesse proportionnelle au débit de parole
- Couleur vert `#00FF88`

### Particules flottantes
- 60 particules de taille 1-3px en permanence
- Se déplacent lentement (vitesse aléatoire 0.1-0.5px/frame)
- Rebondissent sur les bords du canvas
- Couleur : `accent_primary` à 40-80% opacité aléatoire
- **Réagissent à la voix** : quand volume > seuil, les particules s'accélèrent et s'éloignent du centre (effet explosion contrôlée)
- Retour à la normale progressif en 1s

### Scan lines
- 3-5 lignes horizontales fines qui défilent de haut en bas en permanence
- Opacité 15%, couleur `accent_primary`
- Vitesses différentes pour chaque ligne
- Effet "écran CRT holographique"

### Texte de statut central (sous l'orbe)
- Affiche l'état en cours : "STANDBY", "LISTENING", "PROCESSING", "SPEAKING"
- Police monospace 10px, espacement large (letter-spacing 4px simulé)
- Effet d'apparition : les lettres s'affichent une par une de gauche à droite
- Légère pulsation d'opacité (80%→100%→80%) en 2s

---

## Composant 3 : Waveform oscilloscope

Canvas tkinter `480×60px`.

### Mode silence
- Ligne centrale fine qui oscille très légèrement (bruit brownien)
- Couleur `accent_primary` à 40% opacité
- Effet "heartbeat" très subtil toutes les 3s (petit spike)

### Mode parole active
- Forme d'onde complète de type oscilloscope
- **La couleur change selon le volume** :
  - Faible → cyan `#00D4FF`
  - Moyen → cyan-vert `#00FFAA`
  - Fort → blanc `#FFFFFF` avec halo cyan
- Remplissage sous la courbe : dégradé de la couleur vers transparent (opacité 20%)
- Miroir : la forme d'onde est symétrique (reflétée vers le bas)
- Épaisseur du trait : 1px faible, 2px fort
- Mis à jour 60fps

### Mode ARIA parle
- Forme d'onde différente : barres verticales style spectre fréquentiel
- Barres colorées en dégradé cyan→violet de gauche à droite
- Hauteur des barres générée synthétiquement en rythme avec le TTS
- Effet "égaliseur musical"

---

## Composant 4 : Zone de conversation

### Bulles utilisateur
- Alignées à droite
- Fond : `#0D1A2E` avec bordure droite `3px #00D4FF`
- Icône : `◈` en cyan
- **Effet d'apparition** : slide depuis la droite en 200ms + fade in
- Timestamp en `text_secondary` 9px

### Bulles ARIA
- Alignées à gauche
- Fond : `#0A0A20` avec bordure gauche `3px #7B2FFF`
- Icône : `◈` en violet
- **Les tokens s'affichent un par un** avec un curseur clignotant `|` à la fin
- Effet de frappe machine (chaque token avec un délai 5-15ms)
- **Effet glitch sur les 3 premiers tokens** de chaque réponse (décalage horizontal 2px pendant 50ms)
- Fond légèrement plus clair pendant la génération, revient normal à la fin

### Scroll
- Scrollbar custom : fine (4px), couleur `accent_primary` à 50%, arrondie
- Auto-scroll fluide (animation easing, pas de saut brutal)

---

## Composant 5 : Barre de statut

### Indicateurs gauche
- Cercle pulsant coloré selon état
- Texte de statut avec animation de points `...`

### Boutons droite
- `[MIC]` : niveau micro en temps réel (mini-waveform 40px dans le bouton)
- `[VOL]` : slider volume TTS popup au clic
- `[THEME]` : switcher de thème (cycle entre les thèmes au clic)
- `[⚙]` : panneau settings complet

---

## Panneau Settings (slide depuis la droite)

Animation : slide en 250ms avec easing cubic

### Section Apparence
- **Sélecteur de thème** : grille de 6 pastilles colorées (HOLOGRAM/MATRIX/AURORA/BLOOD/GOLD/CUSTOM)
- **Mode CUSTOM** : 5 color pickers pour accent_primary, accent_secondary, background, text_primary, glow_color
- **Intensité du glow** : slider 0-100%
- **Vitesse des animations** : slider 0.5x → 2x
- **Opacité de la fenêtre** : slider 70-100%
- **Scan lines** : toggle on/off
- **Particules** : toggle on/off + slider densité (20-100 particules)
- **Effets glitch** : toggle on/off + slider fréquence

### Section Audio
- **Voix TTS** : dropdown (liste des voix FR edge-tts)
- **Vitesse** : slider -50% à +50%
- **Volume** : slider 0-100%
- **Sons d'ambiance** : toggle

### Section Assistant
- **Nom affiché** : champ texte (défaut "ARIA")
- **Langue** : dropdown FR/EN/DE
- **Mémoire** : bouton "Voir" + bouton "Effacer"
- **Historique** : bouton "Voir" + bouton "Effacer"
- **Modèle Ollama** : dropdown des modèles installés

### Section Système
- **Position** : dropdown (bas-droite, bas-gauche, haut-droite, haut-gauche, centre)
- **Toujours visible** : toggle
- **Mode compact au démarrage** : toggle
- **Raccourci** : affiche "F24" + bouton pour changer

Toutes les modifications sont appliquées **immédiatement en temps réel** sans redémarrage. Sauvegardées dans `data/ui_state.json`.

---

## Popup Presets

Grille 2×3 avec cartes animées :
- Chaque carte : fond `surface`, bordure `accent_primary` fine
- Icône grande (40px), nom du preset, description courte
- Hover : bordure s'illumine, fond légèrement plus clair, scale 1.02
- Active : bordure pleine `accent_primary`, fond `#0A1628`, badge "ACTIF"
- Presets : ✈ Vol | 📚 Étude | 🎮 Gaming | 🎵 Détente | 🌙 Nuit | ⚡ Custom

---

## Notifications Toast

- Apparaissent en bas à gauche de l'écran (pas dans la fenêtre ARIA)
- Fond `surface` avec bordure colorée selon type (info=cyan, success=vert, error=rouge)
- Animation : slide depuis le bas + fade in (300ms)
- Disparition : fade out après 3s
- Maximum 3 toasts simultanés (empilés)
- Types : INFO / SUCCESS / WARNING / ERROR

---

## Effets globaux

### Effet glitch global (aléatoire)
- Toutes les 15-45 secondes (aléatoire), l'interface entière "glitch" pendant 200ms :
  - Le header se décale horizontalement de 3-5px
  - Une ligne de couleur aléatoire traverse l'écran
  - L'opacité fluctue brièvement (95%→85%→100%)
  - Son glitch optionnel (court bruit blanc 50ms)
- Désactivable dans settings

### Bords lumineux
- Les 4 bords de la fenêtre ont un glow subtil de la couleur `accent_primary`
- Pendant l'écoute : le bord gauche pulse plus fort
- Pendant que ARIA parle : le bord droit pulse

### Fond dynamique
- Très légère animation de fond : gradient radial qui se déplace lentement
- Centre du gradient suit approximativement la position de l'orbe central
- Imperceptible mais donne une sensation de profondeur

---

## Réactivité vocale (LE PLUS IMPORTANT)

Tout réagit au volume en temps réel :

| Volume (RMS) | Orbe | Waveform | Particules | Bords | Couleur dominante |
|---|---|---|---|---|---|
| 0 (silence) | 45px cyan froid | ligne plate | lentes | glow faible | #00AACC |
| 20% | 52px | légère ondulation | normales | glow moyen | #00C4EE |
| 50% | 65px | forme d'onde active | accélérées | glow fort | #00D4FF |
| 80% | 78px | forme pleine | explosion | glow max | #44DDFF |
| 100% | 90px | saturée blanche | chaos | pulse blanc | #AAEEFF |

La transition entre états est toujours fluide (lerp factor 0.12 par frame à 60fps).

---

## Personnalisation sauvegardée (data/ui_state.json)

```json
{
  "theme": "HOLOGRAM",
  "custom_colors": {
    "accent_primary": "#00D4FF",
    "accent_secondary": "#7B2FFF",
    "background": "#04040F",
    "text_primary": "#E8F4FF",
    "glow_color": "#00D4FF"
  },
  "glow_intensity": 70,
  "animation_speed": 1.0,
  "opacity": 0.95,
  "scan_lines": true,
  "particles": true,
  "particles_count": 60,
  "glitch_effects": true,
  "glitch_frequency": 0.3,
  "window_position": [1400, 100],
  "window_size": [520, 780],
  "compact_mode": false,
  "always_on_top": true,
  "assistant_name": "ARIA",
  "tts_voice": "fr-FR-DeniseNeural",
  "tts_rate": "+5%",
  "tts_volume": 90,
  "sounds_enabled": true
}
```

---

## Performance

- Rendu séparé : pygame canvas dans un thread, tkinter dans le thread principal
- Les calculs audio (RMS, FFT) dans le thread STT, résultats partagés via `threading.Event` + variable partagée thread-safe
- Cible 60fps pour le canvas pygame, 30fps pour la waveform tkinter
- Si CPU > 80% : réduction automatique à 30fps
- Désactivation des particules automatique si performances insuffisantes

---

## Accessibilité et robustesse

- Si pygame non disponible : fallback sur canvas tkinter pur (waveform simple)
- Si PIL non disponible : effets glow désactivés, reste fonctionnel
- Toutes les animations respectent `prefers-reduced-motion` (détecté via registre Windows)
- La fenêtre ne peut pas sortir des bords de l'écran

---

## Prompt Cursor

> Rewrite ui.py completely from scratch based on this v6 spec. This is the most important file in the project — it must be visually stunning.
>
> TECHNICAL REQUIREMENTS:
> - tkinter for the main window (no border, always on top)
> - pygame canvas embedded in tkinter frame for the central visualizer and waveform (high performance 60fps rendering)
> - PIL/Pillow for glow effects
> - numpy for audio calculations
> - ALL animations via root.after() loops at 60fps
> - ALL cross-thread UI updates via root.after(0, callback)
>
> IMPLEMENT IN ORDER:
> 1. Color system: 6 themes (HOLOGRAM, MATRIX, AURORA, BLOOD, GOLD, CUSTOM) switchable at runtime
> 2. Header: glitch-animated ARIA title with gradient, hexagonal state indicator with 5 states
> 3. Central visualizer (pygame canvas): reactive orb (radius changes with voice volume via lerp), rotating radar circles, sound wave rings when speaking, 60 floating particles that react to voice volume, scan lines
> 4. Oscilloscope waveform: color changes with volume level (cyan→white), mirrored, filled gradient below
> 5. Conversation zone: animated bubble appearance (slide+fade), real-time token display with typing cursor, glitch effect on first tokens
> 6. Status bar with live mic level mini-waveform in MIC button
> 7. Settings panel (slide from right, all settings applied in real-time)
> 8. Preset popup grid with hover animations
> 9. Toast notifications (bottom-left, stacked, slide+fade)
> 10. Global glitch effect (random every 15-45s)
> 11. Glowing window borders that react to state
> 12. Save/restore all settings and window position from data/ui_state.json
>
> VOICE REACTIVITY (CRITICAL):
> - update_waveform(rms) must be called from stt.py every audio chunk
> - The orb radius, particle speed, border glow, and waveform color ALL change based on rms value
> - Use linear interpolation (lerp factor 0.12) for all smooth transitions
>
> Every method from the existing ui.py interface must still work:
> show(), hide(), show_user_text(text), append_assistant_text(token),
> finalize_assistant_message(), set_status(state), update_waveform(rms),
> show_toast(message, type), show_notification(text)
>
> No placeholders. Full implementation. This file will be long — that is expected and required.
