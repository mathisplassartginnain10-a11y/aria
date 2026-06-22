# Sprint A v2 — Ouvrir TOUTES les apps (jamais l'explorateur)

## Objectif
ARIA doit lancer la vraie application demandée — pas un fichier, pas l'explorateur,
pas un dossier. Si l'app n'est pas trouvée immédiatement, elle cherche partout
avant d'abandonner.

---

## Le problème actuel
Windows a plusieurs façons d'ouvrir une app. Si on utilise la mauvaise,
on ouvre l'explorateur de fichiers à la place. Il faut une hiérarchie de
stratégies qui essaie chaque méthode dans l'ordre jusqu'à ce que ça marche.

---

## Ce que Cursor doit implémenter dans actions/apps.py

### Règle absolue
Avant TOUT lancement, vérifier que le chemin ne pointe pas vers
`explorer.exe` ou un dossier. Si c'est le cas, abandonner cette méthode
et passer à la suivante. Ne jamais appeler `os.startfile()` sur un dossier
ou un chemin qui n'est pas un `.exe`, `.lnk`, ou URI scheme.

### Hiérarchie de lancement à implémenter

**Méthode 1 — Exe direct via subprocess.Popen**
Prendre le chemin exe depuis l'index, vérifier qu'il existe et que c'est
un vrai exécutable (pas explorer.exe, pas un dossier), puis le lancer
avec `subprocess.Popen([exe_path], creationflags=DETACHED_PROCESS)`.

**Méthode 2 — Raccourci .lnk via win32api.ShellExecute**
Utiliser `win32api.ShellExecute(0, 'open', lnk_path, ...)` sur les fichiers
`.lnk` du menu Démarrer. Ne jamais faire `os.startfile()` sur un `.lnk`
dont la cible est un dossier.

**Méthode 3 — UWP via Get-StartApps PowerShell**
Lancer `Get-StartApps | Where-Object {$_.Name -like "*nom*"} | Select -First 1`
pour obtenir l'`AppId`, puis `explorer shell:AppsFolder\{AppId}`.
C'est la seule façon fiable de lancer les apps Microsoft Store.

**Méthode 4 — URI schemes Windows**
Certaines apps ont un URI propre : `spotify:`, `discord:`, `steam:`,
`ms-paint:`, `calculator:`, `ms-settings:`, `xbox:`, `msteams:`, etc.
Construire une table de correspondance nom → URI et l'essayer avant le
path search.

**Méthode 5 — Steam via steam://rungameid/{appid}**
Scanner les fichiers `appmanifest_*.acf` dans le dossier steamapps pour
trouver l'appid correspondant au nom du jeu, puis `os.startfile(steam://rungameid/{id})`.

**Méthode 6 — Epic Games via le fichier .item du manifest**
Lire `%PROGRAMDATA%\Epic\EpicGamesLauncher\Data\Manifests\*.item` pour
trouver le `LaunchExecutable` + `InstallLocation` et lancer le bon exe.

**Méthode 7 — Recherche dans Program Files avec scoring**
Parcourir `C:\Program Files`, `C:\Program Files (x86)`, `%LOCALAPPDATA%`,
`%APPDATA%` pour trouver un exe dont le nom ressemble à la requête.
Scorer les correspondances (exact > contient > partiel). Ignorer tout exe
qui contient "unins", "setup", "install", "update", "crash", "helper",
"updater" dans son nom. Ne jamais retourner explorer.exe.

**Méthode 8 — PowerShell Start-Process**
Dernier recours : `Start-Process "nom_app" -ErrorAction SilentlyContinue`.
Windows cherche lui-même dans le PATH.

### Détection et blocage de l'explorateur
Créer une fonction `_is_explorer_path(path)` qui retourne True si :
- Le chemin se termine par `explorer.exe`
- Le chemin est un dossier (pas un fichier)
- La cible d'un .lnk est un dossier
Appeler cette fonction avant CHAQUE tentative de lancement.

### Fonction find_app() améliorée
Chercher dans l'index avec correspondance floue :
1. Correspondance exacte sur le nom
2. La requête contient le nom de l'app
3. Le nom de l'app contient la requête
4. Les mots de la requête matchent les mots du nom
5. Distance de Levenshtein si tout échoue

### Re-scan automatique si app non trouvée
Si aucune méthode ne fonctionne après avoir tout essayé,
relancer un scan complet de `scan_and_save_apps()` et réessayer une fois.
Ce re-scan doit être non-bloquant (thread daemon).

### Fonction close() améliorée
Utiliser `psutil` pour trouver tous les processus dont le nom correspond
à la requête. Essayer `terminate()` d'abord (propre), puis `kill()` si
le processus ne répond pas après 3 secondes.

### Nouvelles fonctions à exposer dans ui_bridge.py
- `launch_app(name)` — lance une app
- `close_app(name)` — ferme une app
- `is_app_running(name)` → bool
- `get_running_apps()` → liste des apps ouvertes
- `get_apps_index()` → liste pour l'autocomplete UI
- `search_apps(query)` → recherche dans l'index

### Intents llm.py à améliorer
- Détecter "lance", "ouvre", "démarre", "joue à", "je veux utiliser"
- Extraire proprement le nom de l'app en supprimant les mots parasites
  ("l'application", "le logiciel", "le jeu", "stp", "maintenant", etc.)
- Si l'app est déjà ouverte (`is_running()`), le signaler plutôt que
  de la relancer
- Ajouter l'intent `apps_ouvertes` : "quelles apps sont ouvertes ?"

---

## Ce que Cursor NE doit PAS faire
- Appeler `os.startfile()` sur un chemin de dossier
- Utiliser `subprocess.run(['explorer', chemin_dossier])`
- Retourner une erreur sans avoir essayé toutes les méthodes
- Hardcoder des chemins d'apps dans le code (tout vient de l'index)

---

## Fichiers à modifier
- `python/actions/apps.py` — réécriture complète
- `python/llm.py` — amélioration détection intent + extraction nom app
- `python/ui_bridge.py` — exposer les nouvelles fonctions

