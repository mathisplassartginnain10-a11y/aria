# Sprint G — Multi-utilisateurs

## Objectif
ARIA s'adapte à plusieurs utilisateurs sur le même PC.
Changer d'utilisateur par commande vocale ou depuis les paramètres.
Chaque utilisateur a ses préférences, son historique, son style.

## Ce que Cursor doit implémenter

### Structure config.yaml

```yaml
current_user: "mathis"
profiles:
  mathis:
    name: "Mathis"
    firstname: "Mathis"
    hello_text: ""
    sub_text: ""
    theme: "slate"
    wallpaper: "aurora"
    tts_enabled: false
    tts_rate: 0
    system_prompt_extra: ""
    models:
      intent: "llama3.2:1b"
      fast: "llama3.1:8b-instruct-q8_0"
      heavy: "qwen3:14b"
```

### actions/profiles.py

Fonctions à implémenter :
- `get_all_profiles()` → dict de tous les profils
- `get_current_profile()` → profil actif
- `switch_profile(name)` → changer de profil, retourner le profil chargé
- `create_profile(name)` → créer un nouveau profil avec valeurs par défaut
- `update_profile(key, value)` → mettre à jour une valeur du profil actif
- `delete_profile(name)` → supprimer un profil (pas le current)

La recherche du profil par nom doit être floue : "passe en mode bro"
doit trouver un profil nommé "brother" ou "bro".

### ui_bridge.py — exposer les fonctions

Exposer : `get_profiles()`, `switch_profile(name)`, `create_profile(name)`,
`delete_profile(name)`.

Quand le profil change, émettre `profile_changed` avec les données du
nouveau profil pour que l'UI mette à jour la salutation, le thème,
les paramètres en temps réel sans redémarrer.

### llm.py — intent switch_user

Pattern : "passe en mode [prénom]", "switch sur [prénom]",
"change de profil [prénom]", "profil [prénom]".

Après le switch, répondre "Bonjour [prénom] ! Profil chargé." et
mettre à jour le system prompt avec les préférences du nouveau profil.

### app.js — réagir à profile_changed

Quand l'event `profile_changed` est reçu :
- Mettre à jour la salutation dans la zone principale
- Appliquer le thème du profil
- Mettre à jour le wallpaper
- Afficher un toast "Profil [prénom] chargé"

### Paramètres — section Profils

Dans les paramètres, ajouter une section "👤 Profils" avec :
- Liste des profils existants avec bouton "Activer" et "Supprimer"
- Bouton "+ Créer un profil" avec input de nom
- Profil actif mis en évidence

## Fichiers à modifier
- `python/actions/profiles.py` (créer)
- `python/ui_bridge.py`
- `python/llm.py`
- `python/config.yaml`
- `electron/renderer/app.js`
- `electron/renderer/index.html`

