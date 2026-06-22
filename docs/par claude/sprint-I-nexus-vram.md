# Sprint I — Nexus VRAM (mode économie)

## Objectif
Quand des apps gourmandes tournent (MSFS, jeux AAA, rendu 3D), ARIA
bascule en mode Nexus : seul llama3.2:1b tourne, tout le reste est arrêté.
La VRAM est libérée pour les autres apps.

## Ce que Cursor doit implémenter

### ui_bridge.py — set_nexus_mode() et get_vram_usage()

`set_nexus_mode(enabled: bool)` :
- Si `enabled=True` :
  - Sauvegarder les modèles actuels dans `config.yaml` sous `models_backup`
  - Remplacer tous les rôles par `llama3.2:1b`
  - Appeler `llamacpp_manager.stop_all_servers()` sauf le serveur 1B
  - Émettre un toast "⚡ Nexus activé — VRAM libérée"
- Si `enabled=False` :
  - Restaurer les modèles depuis `models_backup`
  - Émettre un toast "🧠 Mode normal rétabli"
- Sauvegarder `nexus_mode: bool` dans config.yaml
- Retourner `{success: bool, enabled: bool}`

`get_vram_usage()` :
- Lancer `nvidia-smi --query-gpu=memory.used,memory.total,memory.free --format=csv,noheader,nounits`
- Retourner `{used_mb, total_mb, free_mb, used_pct}`
- Si nvidia-smi absent, retourner des valeurs à 0

### llm.py — intent nexus_mode

Pattern : "active nexus", "libère la vram", "mode économie",
"mode léger", "désactive nexus", "mode normal".
Détecter si Nexus est actif et basculer dans l'autre sens.

### UI dans les paramètres — section Système

- Toggle "⚡ Mode Nexus" avec description "Libère la VRAM pour les jeux"
- Widget VRAM en temps réel : barre de progression + chiffres
  "X Mo utilisés / 16384 Mo"
- Le widget VRAM se met à jour toutes les 10 secondes via setInterval
- Couleur de la barre : vert < 50%, orange 50-80%, rouge > 80%
- Quand Nexus est actif : badge rouge "NEXUS" visible dans la sidebar

### Activation automatique optionnelle

Dans config.yaml, option `nexus_auto_apps: ["msfs", "cyberpunk", "hogwarts"]`.
Si une de ces apps est détectée comme ouverte (via `is_running()`),
activer Nexus automatiquement. Désactiver quand l'app se ferme.
Vérifier toutes les 30 secondes via un thread daemon.

## Fichiers à modifier
- `python/ui_bridge.py`
- `python/llm.py`
- `python/llamacpp_manager.py`
- `electron/renderer/app.js`
- `electron/renderer/index.html`
- `electron/renderer/styles.css`

