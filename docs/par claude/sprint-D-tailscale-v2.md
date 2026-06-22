# Sprint D v2 — Liaison PC ↔ Téléphone via Tailscale

## IPs
- PC : 100.73.160.68
- Nothing Phone 2a : 100.123.180.5

## Objectif
ARIA doit être accessible depuis le téléphone via une PWA installable,
avec ports dynamiques, reconnexion automatique, et toutes les fonctions
du PC disponibles depuis le tel.

## Ce que Cursor doit implémenter

### mobile_server.py — serveur robuste

Trouver automatiquement un port libre à partir de 5000 en cas de conflit.
Sauvegarder les ports utilisés dans `data/mobile_ports.json` pour que
le téléphone sache toujours où se connecter.

Le serveur HTTP sert la PWA. Le serveur WebSocket gère la communication
en temps réel. Les deux tournent en threads daemon indépendants.

### PWA mobile — interface optimisée Nothing Phone 2a

La page HTML servie doit être une vraie PWA installable :
- `manifest.json` avec `display: standalone` et icône ARIA
- Méta viewport correct pour Android
- Design sombre adapté au Nothing Phone (fond #04080F, accents bleu-violet)
- Boutons larges (min 48px) pour le tactile
- Pas de zoom sur double-tap

L'interface doit contenir :
- Header : logo ARIA + indicateur connexion (vert/rouge) + IP Tailscale
- Zone de raccourcis rapides : météo, heure, volume, Spotify, MSFS,
  screenshot, mode gaming, mode nuit
- Zone messages : affichage du chat avec streaming des tokens
- Input + bouton envoyer + bouton micro
- Bouton "Arrêter la génération" qui apparaît pendant le streaming

### WebSocket mobile — protocole simple

Messages du tel vers le PC :
- `{action: "ask", text: "...", conv_mode: "ecrit"}`
- `{action: "stop_generation"}`
- `{action: "start_mic"}` / `{action: "stop_mic"}`
- `{action: "launch_app", name: "..."}`
- `{action: "volume", level: 50}`

Messages du PC vers le tel :
- `{type: "token", data: "..."}` — streaming LLM
- `{type: "done", data: "..."}` — fin de génération
- `{type: "status", data: "thinking"|"idle"|"listening"}`
- `{type: "stt_result", data: "..."}` — transcription vocale
- `{type: "toast", data: {message: "...", type: "success"|"error"|"info"}}`

### Reconnexion automatique côté tel

La PWA doit tenter de se reconnecter au WebSocket toutes les 3 secondes
si la connexion est perdue, avec un délai exponentiel (3s → 6s → 12s → max 30s).
Afficher l'état de connexion en temps réel dans le header.

### Accès depuis le tel

URL d'accès : `http://100.73.160.68:[PORT]`
Le port exact est dans `data/mobile_ports.json`.
Ajouter à l'écran d'accueil Chrome → installée comme app native.

## Fichiers à modifier
- `python/mobile_server.py` — réécriture complète
- `python/main.py` — démarrage après WebSocket connecté
- `python/ui_bridge.py` — relayer les events vers clients mobiles

