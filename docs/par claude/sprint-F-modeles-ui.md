# Sprint F — Installer et gérer les modèles depuis l'UI

## Objectif
Depuis les paramètres ARIA, voir tous les modèles disponibles, en installer
de nouveaux via Ollama, les assigner aux rôles (intent/fast/heavy/vision),
et les désinstaller. Tout sans quitter ARIA.

## Ce que Cursor doit implémenter

### Catalogue de modèles dans ui_bridge.py

Définir MODEL_CATALOG comme une liste de dicts avec pour chaque modèle :
- `id` : identifiant Ollama (ex: "llama3.2:1b")
- `name` : nom affiché
- `description` : description courte
- `size_gb` : taille approximative
- `use_case` : "intent" | "fast" | "heavy" | "vision"
- `icon` : emoji
- `ollama_name` : nom pour `ollama pull`

Modèles à inclure : llama3.2:1b, llama3.1:8b-instruct-q8_0, qwen3:14b,
mistral:7b, phi3:mini, deepseek-r1:8b, minicpm-v:latest, codellama:7b,
qwen2.5:1.5b-instruct-q8_0.

Exposer via WebSocket :
- `get_model_catalog()` → liste avec champ `installed: bool` et `is_active: bool`
- `install_model(model_id)` → lance `ollama pull` en thread, émet des events
  `model_install_start`, `model_install_progress`, `model_install_done`
- `uninstall_model(model_id)` → `ollama rm`
- `set_model_for_role(role, model_id)` → met à jour config.yaml et MODELS dict
- `get_installed_models()` → liste via `ollama list`

### Events de progression en temps réel

Pendant `ollama pull`, parser la sortie ligne par ligne et émettre
`model_install_progress` avec le texte brut de progression.
L'UI affiche une barre de log défilant pendant l'installation.

### Interface dans les paramètres

Dans la section "Modèles IA" des paramètres, ajouter deux onglets :
- "Modèles actifs" : dropdowns pour assigner intent/fast/heavy/vision
- "Catalogue" : cards de modèles avec bouton Installer/Retirer

Chaque card de modèle affiche :
- Icône + nom + description
- Taille en Go
- Usage recommandé (intent/fast/heavy/vision)
- Badge "Installé" en vert si présent
- Badge "Actif" si assigné à un rôle
- Bouton "Installer (X Go)" ou "Retirer"
- Barre de log de progression pendant l'installation

## Fichiers à modifier
- `python/ui_bridge.py` — MODEL_CATALOG + fonctions
- `electron/renderer/app.js` — loadModelCatalog(), listeners events
- `electron/renderer/index.html` — UI onglets + cards
- `electron/renderer/styles.css` — styles cards modèles

