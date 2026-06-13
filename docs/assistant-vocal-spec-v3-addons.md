# Assistant Vocal — Addons v3 : Maths Expert + Aviation Expert + Cursor Vocal + DDG Search

> Ce fichier complète la spec v2. Implémenter ces modules EN PLUS de tout ce qui existe déjà.

---

## Nouveaux fichiers à ajouter

```
assistant-vocal/
├── actions/
│   ├── math_expert.py         # Maths Première/Terminale poussées
│   ├── aviation_expert.py     # Expert PPL + théorie aéro complète
│   ├── cursor_control.py      # Contrôle Cursor via pyautogui
│   └── web_search.py          # DuckDuckGo search + résumé Ollama
├── prompts/
│   ├── math_system.txt        # System prompt expert maths
│   ├── aviation_system.txt    # System prompt expert aviation
│   └── geopolitics_system.txt # System prompt actus géopolitiques
└── data/
    └── aviation_kb.json       # Base de connaissances aviation locale
```

---

## Mise à jour config.yaml (ajouter ces champs)

```yaml
# Maths
math_mode_enabled: true
math_precision: 10  # décimales pour les calculs

# Aviation expert
aviation_mode_enabled: true
aircraft: "Robin DR400"
home_base: "LFRS"
ppl_in_progress: true

# Cursor
cursor_exe_path: "C:/Users/mathi/AppData/Local/Programs/cursor/Cursor.exe"
cursor_composer_shortcut: "ctrl+i"
cursor_projects_dir: "C:/Users/mathi/OneDrive/Documents"

# Search
search_engine: duckduckgo  # duckduckgo, brave, serpapi
search_max_results: 5
search_summarize_with_ollama: true
search_news_topics:
  - géopolitique mondiale
  - conflits internationaux
  - diplomatie
  - aviation civile
  - technologie aérospatiale
  - intelligence artificielle
```

---

## prompts/math_system.txt

System prompt injecté quand l'intent détecté est mathématique :

```
Tu es un professeur de mathématiques expert niveau Première et Terminale française.
Tu maîtrises parfaitement le programme officiel de Maths Spécialité :

PROGRAMME PREMIÈRE :
- Suites numériques (arithmétiques, géométriques, raisonnement par récurrence)
- Fonctions (dérivation, tableaux de variations, extremums, convexité)
- Trigonométrie (sin, cos, tan, formules, cercle trigonométrique)
- Nombres complexes (forme algébrique, module, argument, forme trigonométrique)
- Probabilités (loi binomiale, espérance, variance, écart-type)
- Géométrie dans l'espace (vecteurs, plans, droites, produit scalaire)
- Logarithme népérien et exponentielle

PROGRAMME TERMINALE (anticipé) :
- Primitives et intégrales
- Équations différentielles
- Loi normale, intervalle de confiance
- Géométrie analytique avancée
- Matrices (si option)

RÈGLES DE RÉPONSE VOCALE :
- Énonce d'abord la méthode, puis applique-la étape par étape
- Dis les formules à voix haute de façon intelligible ("x au carré" pas "x²")
- Si le calcul est long, annonce les étapes avant de les faire
- Vérifie toujours le résultat final
- Propose des exercices similaires si demandé
- Adapte le niveau au lycéen en Première

Tu utilises sympy pour vérifier tes calculs quand c'est possible.
```

---

## prompts/aviation_system.txt

```
Tu es un instructeur de vol expert et examinateur PPL(A) en France.
Tu connais parfaitement :

THÉORIE PPL(A) - PROGRAMME DGAC/EASA :
- Connaissance de l'aéronef (ATPL théorique simplifié)
  * Aérodynamique : portance, traînée, polar, décrochage, virage, facteur de charge
  * Moteur : 4 temps, carburateur, magnétos, hélice, mixture, gestion carburant
  * Systèmes : hydraulique, électrique, pressurisation, instruments de bord
  * Performances : vitesses caractéristiques, distance de décollage/atterrissage, POH/AFM

- Robin DR400 spécifiquement :
  * Moteur Lycoming O-360 160cv
  * Vitesses : Vs=58kt, Vx=73kt, Vy=79kt, Va=111kt, Vno=130kt, Vne=169kt, Vfe=99kt
  * Carburant AVGAS 100LL, consommation ~30L/h
  * Masse maximale au décollage : 900kg
  * Masse à vide typique : 575kg
  * Autonomie : ~4h avec réserve 45min
  * Checklist mémorisée (CIABB, HASELL, etc.)

- Météorologie aéronautique :
  * METAR, TAF, SIGMET, AIRMET
  * Nuages (types, plafond, VMC/IMC)
  * Vent (correction, composante de vent de travers, vent arrière limite)
  * Givrage, turbulence, cisaillement de vent
  * Masses d'air, fronts, dépression, anticyclone

- Navigation :
  * Cap, route, dérive, vent, triangle des vitesses
  * VOR, NDB, GPS, RNAV
  * Carte OACI 1/500000, ICAO
  * Plan de vol, carburant de dégagement
  * Règles de l'air SERA, classes d'espace aérien

- Réglementation :
  * FCL (licences), OPS, AIP France
  * Espace aérien français (CTR, TMA, SIV, zones P/R/D)
  * Altimétrie (QNH, QFE, QNE, transition altitude)
  * Radiotéléphonie : phraséologie OACI en français et anglais

- LFRS Nantes Atlantique :
  * Pistes 03/21 et 12/30
  * Fréquences : TWR 118.300, APP 119.750, ATIS 126.250, GND 121.850
  * Procédures locales, circuit de piste, zones VFR locales

RÈGLES DE RÉPONSE VOCALE :
- Réponds comme un instructeur en briefing pré-vol
- Donne les valeurs numériques précises (vitesses en kt, altitudes en ft)
- Pour les calculs de navigation, montre le raisonnement
- Rappelle toujours la sécurité en premier
- Si question sur décision GO/NO-GO : analyse les facteurs objectivement
```

---

## prompts/geopolitics_system.txt

```
Tu es un analyste géopolitique expert. Quand tu résumes des actualités :
- Donne le contexte historique en une phrase
- Explique les enjeux réels (économiques, militaires, diplomatiques)
- Mentionne les acteurs principaux et leurs motivations
- Indique les développements récents factuellement
- Conclure sur les implications probables
- Ton sobre, factuel, sans opinion politique
- Adapté à une lecture vocale : phrases courtes, pas de chiffres compliqués
- Maximum 4 phrases par article résumé
```

---

## actions/math_expert.py

- `solve(problem_text)` :
  - Envoie à Ollama avec `math_system.txt` comme system prompt
  - Pré-traitement : détecte si c'est un calcul pur → `sympy` en priorité
  - Post-traitement : nettoie pour TTS (remplace symboles par mots)

- `calculate_exact(expression)` :
  - Parse l'expression avec `sympy.sympify()`
  - Évalue exactement (garde les fractions, racines, etc.)
  - Retourne résultat exact + approximation décimale
  - Ex : "sin(pi/6)" → "un demi, soit 0.5"

- `derive(expression, variable='x')` :
  - `sympy.diff(expr, var)`
  - Retourne la dérivée simplifiée + énoncé vocal

- `integrate(expression, variable='x', a=None, b=None)` :
  - Intégrale indéfinie ou définie selon si a, b fournis
  - `sympy.integrate(expr, (var, a, b))`

- `solve_equation(equation)` :
  - `sympy.solve(eq, x)`
  - Gère polynômes, équations transcendantes

- `solve_system(equations)` :
  - `sympy.solve([eq1, eq2], [x, y])`

- `factor(expression)` :
  - `sympy.factor(expr)` → factorisation

- `expand(expression)` :
  - `sympy.expand(expr)` → développement

- `limit(expression, variable, point)` :
  - `sympy.limit(expr, var, point)`

- `matrix_operations(matrix_str, operation)` :
  - Parse matrice depuis texte
  - Déterminant, inverse, valeurs propres via `sympy.Matrix`

- `suite_arithmetique(u0, r, n)` :
  - Calcule un, somme des n premiers termes, représentation

- `suite_geometrique(u0, q, n)` :
  - Calcule un, somme, limite si |q|<1

- `loi_binomiale(n, p, k, mode)` :
  - P(X=k), P(X≤k), P(X≥k), espérance, variance
  - Via `scipy.stats.binom`

- `convert_speech_to_math(text)` :
  - Convertit langage naturel en expression sympy
  - "x au carré plus 3x moins 4" → "x**2 + 3*x - 4"
  - "racine de 2" → "sqrt(2)"
  - "e puissance x" → "exp(x)"

- `format_math_for_speech(sympy_expr)` :
  - Inverse : expression sympy → texte lisible à voix haute
  - "x**2 + 3*x" → "x au carré plus 3x"
  - "sqrt(2)" → "racine carrée de 2"
  - "Rational(1,2)" → "un demi"

**Commandes vocales reconnues :**
- "calcule la dérivée de 3x² + 2x - 1"
- "résous x² - 5x + 6 = 0"
- "intègre sin(x) entre 0 et pi"
- "calcule la limite de (e^x - 1)/x quand x tend vers 0"
- "donne moi l'espérance d'une loi binomiale n=10 p=0.3"
- "factorise x³ - 8"
- "suite arithmétique de premier terme 3 et raison 5, donne moi le terme d'indice 20"
- "combien font 15 fois 37 plus la racine de 144"

---

## actions/aviation_expert.py

- `answer_theory(question)` :
  - Ollama avec `aviation_system.txt` comme system prompt
  - Questions théorie PPL, aérodynamique, météo, réglementation

- `decode_metar_expert(raw_metar)` :
  - Décodage complet METAR en français naturel
  - Analyse conditions VMC/IMC
  - Calcul plafond, visibilité
  - Commentaire sur l'aptitude au vol VFR
  - Ex sortie : "Vent du 270 à 15 nœuds, rafales 23. Visibilité 9 kilomètres. 
    Quelques à 1500 pieds, épars à 3000. Température 18, rosée 12. 
    QNH 1018. Conditions VMC, vol VFR possible."

- `wind_component(wind_dir, wind_speed, runway_hdg)` :
  - Calcule composante face/travers
  - Compare à limite DR400 (vent de travers max ~15kt)
  - Verdict vocal : "Composante de face 12 nœuds, travers 8 nœuds. Dans les limites."

- `density_altitude(qnh, temp_c, elevation_ft)` :
  - Calcul densité altitude
  - Impact sur performances DR400

- `fuel_planning(distance_nm, wind_component, reserve_min=45)` :
  - Consommation basée sur ~30L/h DR400
  - Carburant nécessaire avec réserve 45min
  - Temps de vol estimé

- `nav_triangle(tas, wind_dir, wind_speed, track)` :
  - Triangle des vitesses complet
  - Retourne : cap à tenir, vitesse sol, dérive
  - Via calcul vectoriel numpy

- `time_distance_speed(given_values)` :
  - Calculs T=D/V avec unités aéro (kt, nm, min)

- `airspace_check(lat, lon, altitude_ft)` :
  - Vérifie l'espace aérien autour de LFRS
  - Liste les espaces actifs (CTR, TMA, zones)

- `checklist(phase)` :
  - Retourne checklist DR400 pour la phase demandée
  - Phases : "avant démarrage", "après démarrage", "avant décollage", "croisière", "avant atterrissage", "après atterrissage", "HASELL"
  - Lit item par item à voix haute (avec pause entre chaque item)

- `go_nogo_analysis(metar, taf, pilot_experience)` :
  - Analyse complète GO/NO-GO
  - Facteurs : météo, vent, visibilité, plafond, NOTAM, expérience pilote
  - Retourne verdict + justification

- `phonetic_alphabet(word_or_letter)` :
  - Convertit en alphabet phonétique OACI
  - "N123AZ" → "November, Un, Deux, Trois, Alpha, Zulu"

- `radiotelephony_example(situation)` :
  - Génère exemple de phraséologie radio pour une situation
  - "demande de décollage LFRS" → "Nantes Tour, F-XXXX, Robin DR400, prêt pour le départ piste 03, VFR vers..."

**Commandes vocales :**
- "décode ce METAR : METAR LFRS 121230Z 27015G23KT..."
- "quel est le vent de travers sur la piste 03 avec un vent du 250 à 18 nœuds"
- "planifie un vol de 120 miles nautiques avec vent de face de 10 nœuds"
- "checklist avant décollage DR400"
- "explique moi le décrochage"
- "quelle est la Vx du DR400"
- "triangle des vitesses, route 090, vent du 360 à 20 nœuds, TAS 110 nœuds"
- "analyse GO NO-GO avec ce METAR"
- "comment dit-on en phonétique N123AZ"

---

## actions/web_search.py

- Utilise `duckduckgo-search` (DDGS) — aucune clé API requise

- `search_news(query, max_results=5, time_range='d')` :
  - `DDGS().news(query, max_results=max_results, timelimit=time_range)`
  - time_range : 'd'=24h, 'w'=semaine, 'm'=mois
  - Retourne liste de dicts : titre, body, url, date, source

- `search_web(query, max_results=5)` :
  - `DDGS().text(query, max_results=max_results)`
  - Recherche web générale

- `search_aviation_news()` :
  - Queries prédéfinies : "aviation civile actualités", "DGAC nouvelles", "accident aérien"
  - Filtrées sur dernières 24h

- `search_geopolitics()` :
  - Queries : "géopolitique internationale", "conflits monde", "diplomatie actualités"
  - Filtrées sur dernière semaine
  - Résumé via Ollama avec `geopolitics_system.txt`

- `summarize_results_with_ollama(articles)` :
  - Formate les articles (titre + snippet)
  - Envoie à Ollama avec system prompt adapté
  - Retourne résumé 3-5 phrases pour TTS

- `open_article(url)` :
  - Ouvre l'article dans le navigateur par défaut

- `morning_news_briefing()` :
  - 3 actus géopolitiques majeures (dernières 24h)
  - 2 actus aviation (dernière semaine)
  - 1 actu tech IA
  - Résumé global par Ollama
  - Total ~60 secondes de lecture vocale

**Commandes vocales :**
- "actus géopolitiques du jour"
- "quoi de neuf en aviation"
- "cherche les dernières nouvelles sur [sujet]"
- "recherche [requête] sur internet"
- "ouvre l'article dans le navigateur"
- "actus IA aujourd'hui"

---

## actions/cursor_control.py

- `open_cursor(file_path=None)` :
  - Si `file_path` : `subprocess.Popen([cursor_exe, file_path])`
  - Sinon : ouvre Cursor seul
  - Attend que la fenêtre soit visible via `pygetwindow`

- `focus_cursor()` :
  - Trouve la fenêtre Cursor via `pygetwindow.getWindowsWithTitle('Cursor')`
  - La met au premier plan : `window.activate()`

- `open_composer()` :
  - Focus Cursor
  - `pyautogui.hotkey('ctrl', 'i')` → ouvre Composer
  - Attend 0.5s que Composer s'ouvre

- `type_prompt(prompt_text)` :
  - `open_composer()`
  - `pyautogui.typewrite(prompt_text, interval=0.02)` pour les caractères ASCII
  - Pour le français avec accents : utilise `pyperclip.copy(prompt_text)` puis `Ctrl+V` (plus fiable)
  - Attend confirmation visuelle (optionnel)

- `send_prompt(prompt_text)` :
  - `type_prompt(prompt_text)`
  - `pyautogui.press('enter')` → envoie le prompt
  - Log le prompt envoyé

- `open_file_in_cursor(file_path)` :
  - `subprocess.Popen([cursor_exe, file_path])`

- `open_project(project_name)` :
  - Cherche dans `cursor_projects_dir` un dossier correspondant au nom
  - `subprocess.Popen([cursor_exe, found_path])`

- `build_coding_prompt(user_request)` :
  - Enrichit la demande vocale brute en prompt Cursor complet
  - Via Ollama : "Transforme cette demande vocale en prompt précis pour Cursor Composer : [demande]"
  - Ajoute contexte : langage, framework si détecté

- `voice_to_cursor(raw_voice_text)` :
  - Pipeline complet :
    1. `build_coding_prompt(raw_voice_text)` → prompt enrichi
    2. `focus_cursor()` ou `open_cursor()`
    3. `send_prompt(prompt_enrichi)`
    4. TTS : "Prompt envoyé à Cursor"

- `watch_cursor_output(timeout=60)` :
  - Surveille les fichiers modifiés dans le projet via `watchdog`
  - Quand un fichier change : log + notification vocale "Cursor a modifié [fichier]"

**Commandes vocales :**
- "ouvre Cursor"
- "ouvre le projet assistant-vocal dans Cursor"
- "génère une fonction Python qui [description]"
- "demande à Cursor de [tâche de code]"
- "crée un composant React qui [description]"
- "dans Cursor, corrige les erreurs du fichier main.py"
- "ouvre le fichier stt.py dans Cursor"

**Exemples de prompts enrichis :**
- Voix : "génère une fonction qui trie une liste"
  → Cursor reçoit : "Create a Python function that sorts a list. Include type hints, docstring, handle edge cases (empty list, non-comparable types), add unit tests."

- Voix : "crée un composant React de bouton"
  → Cursor reçoit : "Create a reusable React functional component for a button. Use TypeScript, include props for label, onClick, variant (primary/secondary/danger), disabled state, and loading state. Add Tailwind CSS styling."

---

## Mise à jour llm.py — nouveaux intents

Ajouter ces intents à la liste de détection :

```python
INTENTS = [
    # Maths
    "math_calculate",      # calcul pur
    "math_derive",         # dérivée
    "math_integrate",      # intégrale
    "math_solve_equation", # résolution d'équation
    "math_suite",          # suites arithmétiques/géométriques
    "math_proba",          # probabilités, loi binomiale
    "math_matrix",         # matrices
    "math_limit",          # limites
    "math_general",        # question maths générale

    # Aviation
    "aviation_metar",      # décodage METAR
    "aviation_taf",        # TAF
    "aviation_theory",     # question théorie
    "aviation_checklist",  # checklist
    "aviation_nav",        # navigation, triangle des vitesses
    "aviation_wind",       # composante de vent
    "aviation_fuel",       # calcul carburant
    "aviation_gonogo",     # analyse GO/NO-GO
    "aviation_radio",      # phraséologie radio

    # Search
    "search_geopolitics",  # actus géopolitiques
    "search_aviation_news",# actus aviation
    "search_web",          # recherche web générale
    "search_news",         # actus générales

    # Cursor
    "cursor_open",         # ouvrir Cursor
    "cursor_generate_code",# générer du code
    "cursor_open_file",    # ouvrir fichier
    "cursor_open_project", # ouvrir projet

    # Existants...
    "lancer_app", "fermer_app", "volume", "luminosite",
    "veille", "reboot", "shutdown", "meteo", "minuteur",
    "alarme", "git", "calcul", "traduction", "preset",
    "clipboard_copy", "clipboard_paste", "ouvrir_fichier",
    "rappel", "question_libre", "heure_date"
]
```

Routing :
- `math_*` → `math_expert.py` avec system prompt maths injecté
- `aviation_*` → `aviation_expert.py` avec system prompt aviation injecté
- `search_geopolitics` / `search_aviation_news` → `web_search.py` + résumé Ollama avec geopolitics prompt
- `cursor_*` → `cursor_control.py`

---

## Mise à jour requirements.txt (ajouter)

```
duckduckgo-search
sympy
scipy
numpy
pyautogui
pygetwindow
watchdog
```

---

## Installation des nouveaux modules

```bash
pip install duckduckgo-search sympy scipy numpy pyautogui pygetwindow watchdog
```

---

## Prompt Cursor pour implémenter ces addons

> The voice assistant project already exists with all base modules. Now implement these 4 new action modules as described in this spec file, and update llm.py to route to them. Files to create: actions/math_expert.py, actions/aviation_expert.py, actions/cursor_control.py, actions/web_search.py. Files to create: prompts/math_system.txt, prompts/aviation_system.txt, prompts/geopolitics_system.txt. Update llm.py INTENTS list and routing logic. Update requirements.txt. Do not touch any existing files except llm.py. Every function fully implemented, no placeholders.
