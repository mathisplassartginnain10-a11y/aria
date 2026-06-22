# Sprint H — Mises à jour en 1 clic

## Objectif
Depuis les paramètres ARIA, vérifier si une mise à jour est disponible
sur GitHub et l'appliquer en un clic. La mise à jour update Python,
npm, et redémarre ARIA automatiquement.

## Ce que Cursor doit implémenter

### scripts/update_aria.bat

Script batch qui :
1. `git pull origin main`
2. `.venv\Scripts\python.exe -m pip install -r requirements.txt -q`
3. `cd electron && npm install --silent && cd ..`
4. Supprime le cache Electron si présent
5. Affiche "Mise à jour terminée — relancez ARIA"

### ui_bridge.py — check_for_updates() et apply_update()

`check_for_updates()` :
- `git fetch` en silent
- `git rev-list HEAD..origin/main --count` pour compter les commits en retard
- `git log origin/main -1 --pretty=format:%s` pour le dernier message
- Retourner `{available: bool, commits_behind: int, latest_message: str}`

`apply_update()` :
- Lancer `scripts/update_aria.bat` dans un nouveau terminal visible
- Retourner `{success: bool}`
- L'utilisateur voit la progression dans le terminal
- ARIA se ferme après 3 secondes pour laisser le script finir

### UI dans les paramètres — section Système

Ajouter dans l'accordéon Système :
- Bouton "Vérifier les mises à jour" → appelle check_for_updates()
- Zone de résultat : "✅ À jour" ou "🔄 X commit(s) disponible(s)"
- Si disponible : afficher le dernier message de commit
- Bouton "Mettre à jour maintenant" → appelle apply_update() + confirmation
- Version actuelle affichée (lire depuis `git describe --tags` ou package.json)

## Fichiers à modifier
- `python/ui_bridge.py`
- `scripts/update_aria.bat` (créer)
- `electron/renderer/app.js`
- `electron/renderer/index.html`

