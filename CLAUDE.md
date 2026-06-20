# CLAUDE.md — ARIA (assistant vocal local)

Mémoire projet + journal des travaux réalisés par Claude. Lis ce fichier en début de session.

## Projet

**ARIA** = assistant vocal personnel 100 % local pour Windows 11.
- **Desktop (Python)** : `main.py`, orchestration LLM `llm.py`, UI `ui.py` + `ui/index.html` (pywebview), actions dans `actions/`, STT `stt.py`, TTS `tts.py`, wake-word `wake_word.py`.
- **Mobile (Expo / React Native)** : `aria-mobile/` — client léger qui parle au PC via `aria_mobile_server.py` (Flask, même WiFi). **Tout s'exécute sur le PC** ; le téléphone est un terminal.
- **Stack** : STT faster-whisper · LLM Ollama local · TTS edge-tts · UI HTML/CSS/JS.

### Chemin des requêtes (latence)
`_fast_intent` (regex 0 ms) → sinon `_detect_intent` (LLM 1B, desktop) → `_route_with_intelligence` → action (`_execute_action`/`_dispatch_action`) **ou** `_conversation` (chat). Modèles : `MODELS` dans `llm.py`; `CHAT_MODEL` = 8B rapide, `MODEL` = qwen3:14b (lourd/réflexion).

## Contrainte dure
**Footprint Ollama < 30 Go.** Au 2026-06-19 il est DÉJÀ à ~34 Go (qwen3:14b 9.3 + bac-qwen3-14b 9.3 + llama3.1:8b-q8 8.5 + minicpm-v 5.5 + llama3.2:1b 1.3). Supprimer `bac-qwen3-14b` (doublon) → ~24,6 Go. La config référence `qwen2.5-coder:14b` et `qwen2.5:1.5b` **non installés**.

---

## Feuille de route (demandée le 2026-06-19)

1. ✅ **Vitesse**
2. ✅ **Ouvrir apps + sites fiable** ("youtube dans chrome", "ouvrir des apps facilement")
3. ✅ **Vrai système de modes** (piloter les vraies apps, sous 30 Go)
4. ⬜ **Le micro** (basse priorité, "un jour") — `stt.py`, spec v17
5. 🔧 **Liquid Glass UI** iOS 26 ultra-personnalisable (mobile + desktop) — *en cours*
6. ⬜ **Raccourcis** (moins important) — `actions/macros.py`

> Toute modif nécessite un **redémarrage d'ARIA** pour prendre effet. Aucune donnée utilisateur n'a été supprimée.

---

## Journal des travaux (2026-06-19)

### 1. Vitesse — `aria_mobile_server.py`
Le mobile était lent à cause de 3 bugs dans `/ask/stream` :
- répondait avec le **14B** (qwen3) au lieu du 8B (le `model=` n'était pas passé → retombait sur `MODEL`) ;
- `/warmup` chauffait un modèle différent de celui du stream → cold-load au 1er message ;
- aucun fast-path : appelait le classifieur 1B sur chaque message → 3 modèles en VRAM.

Corrigé :
- `/ask/stream` : `_fast_intent` (regex) d'abord → action via `_route_with_intelligence(..., stream_to_ui=False)` ; sinon stream sur `_chat_model()`.
- `_chat_model()` = `llm.FORCED_MODEL or llm.CHAT_MODEL` (jamais le 14B sauf sélecteur).
- `_filter_think()` masque `<think>…</think>` en streaming (testé sur balises coupées entre tokens).
- `/warmup` et `/ask/fast` alignés sur `_chat_model()`; bug du tuple `_fast_intent` dans `/ask/fast` corrigé; `MOBILE_MODEL` mort supprimé; `import re` ajouté.

### 2. Apps + sites — `llm.py`, `actions/apps.py`, `actions/browser.py`
Diagnostic en testant les vraies fonctions de résolution sur la machine. Bugs réels corrigés :
- **« ouvre <app installée> » ouvrait un SITE** (ex. « ouvre spotify » → spotify.com). → `_fast_intent` PRIORITY 3 appelle `apps.resolve_known()` (rapide, sans scan disque) : app installée → `lancer_app`, sinon → site. Gère « ouvre discord et spotify ».
- `apps.resolve_known()` ajouté (KNOWN_APPS + config, ~3 ms).
- **Cache** `_RESOLVE_CACHE` dans `apps.py` (hit 1 h / miss 30 s) : une app introuvable crawlait le disque 1–4 s à CHAQUE fois (notion 1107 ms → 0 ms au 2e appel). `_resolve_launch_target` wrappe `_resolve_launch_target_uncached`.
- Intent regex élargi (`SITE_OPEN_PATTERN`/`_OPEN_VERB`) : séparateur « avec », verbes « lance-moi/ouvre-moi/démarre/mets », brave/vivaldi. `_clean_site()` retire « le site / la page » sans casser « le monde » (lemonde.fr).
- `browser._resolve_browser_exe` honore Firefox/Brave/Vivaldi/Opera (chemins connus + repli config/registre via `apps`). Avant, tout sauf chrome/edge/opera retombait sur Chrome.

### 3. Modes / presets — `actions/presets.py`, `llm.py`
**Découverte** : la section `presets:` de `config.yaml` était **totalement ignorée** (modes codés en dur + customs `data/ui_state.json`).
**Décision utilisateur** : garder l'éditeur de l'app (`ui_state.json`) comme source de vérité — NE PAS toucher/réécrire ses données. Précédence : défauts `PRESETS` < `config.yaml` < customs `ui_state.json`.
Fait :
- `get_merged_presets()` fusionne les 3 sources (config.yaml enfin lue, en base).
- `activate()` : transition propre (ferme `apps_close` + ce que le mode précédent avait ouvert et absent du nouveau), **retour réel** (« ouvert : … ; introuvable : … »).
- `deactivate()` : ferme ce que le mode avait ouvert (vrai « sortir du mode »).
- Persistance dans `ui_state.json` (`active_preset`, `active_preset_opened`) → survit au redémarrage.
- `match_in_text()` + fast-path `_fast_intent` PRIORITY 2.8 → « mode étude / active le mode gaming / désactive le mode » reconnus (donc **actifs sur mobile**, qui ne s'appuie que sur le regex). Les 2 handlers `preset` de `llm.py` utilisent `match_in_text`.
- Vérifié : etude→Edge, vol→MSFS 2024 résolvent ; l'entrée « MSFS Plugin » est parasite (signalée « introuvable »).
- **À retirer côté utilisateur** : l'entrée parasite "Microsoft Flight Simulator Plugin" du mode "vol" (via l'éditeur de l'app).

### 5. Liquid Glass — *en cours*
- Le desktop `ui/index.html` a déjà une base glass (vars `--glass-blur/--glass-alpha`, panneaux floutés, wallpaper, thèmes). Le mobile n'a aucun glass.
- Créé : **`docs/liquid-glass-playground.html`** — vrai `backdrop-filter` fidèle iOS 26 (arête lumineuse, sheen de bord en `mix-blend-mode:screen`, profondeur, teinte réglable) + tous les réglages (flou, transparence, saturation, reflet, rayon, teinte, accent, glow, 5 fonds, 4 presets) + bouton « Copier le thème » (exporte un bloc de variables CSS).
- **Suite** : l'utilisateur règle le look dans le playground → renvoie le bloc CSS → porter dans (a) `ui/index.html` (matériau `.glass` + contrôles teinte/presets dans Apparence) et (b) mobile (ajouter `expo-blur` + `<GlassView>` réutilisant les mêmes valeurs) puis rebuild APK (EAS).

### ⚠ Incident config.yaml (2026-06-19) — corrigé
`config.yaml` a été **tronqué à 5 clés** (tout perdu : tts, micro, system_prompt, apps, presets, API…).
Cause : `llm.py` appelait `apply_model_settings()` → `_patch_config()` (écriture non atomique) **à chaque import**, déclenché par les clés modèle présentes dans `ui_state.json`. Des imports concurrents (runs de test + lancement) ont fait qu'un process lisait config.yaml pendant qu'un autre le tronquait → réécriture avec seulement les patches.
Corrigé dans `llm.py` :
- `_atomic_write()` : tmp + `os.replace` (jamais de fichier partiel).
- `_patch_config()` : **refuse d'écrire si la lecture est vide/illisible** (anti-cascade) + écriture atomique.
- `_patch_ui_state()` : écriture atomique.
- `apply_model_settings(..., persist=False)` à l'import : applique aux variables en mémoire **sans réécrire** config/ui_state (les valeurs viennent déjà de ui_state).
**Leçon** : ne jamais importer en parallèle des modules qui écrivent sur disque à l'import. Tester les imports en série.

---

## Méthode de vérif utilisée (sans effets de bord)
- Résolution apps/sites : appeler les vraies fonctions (`_fast_intent`, `apps.resolve_known`, `browser.resolve_site_url`) **sans rien lancer**.
- Modes : mocker `apps.launch/close`, `system.set_volume`, `_load_ui_state/_patch_ui_state` (en mémoire) → tester activate/deactivate sans lancer d'app ni écrire sur disque.
- Console venv : `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe` (les emojis cassent cp1252).
- `python -m py_compile <fichiers>` après chaque lot d'edits.

## Fichiers touchés cette session
`aria_mobile_server.py`, `llm.py`, `actions/apps.py`, `actions/browser.py`, `actions/presets.py`, `docs/liquid-glass-playground.html` (nouveau), `CLAUDE.md` (nouveau).
