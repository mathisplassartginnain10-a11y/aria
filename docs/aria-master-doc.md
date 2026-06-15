# ARIA — Document maître : architecture, bugs, roadmap complète et prompts

> Document de référence exhaustif pour le projet ARIA (assistant vocal local Windows,
> Python, repo `mathisplassartginnain10-a11y/aria`).
> Chaque section est autonome : contexte, état actuel, spec détaillée, code, et
> prompt Cursor prêt à coller. Les sections "priorité haute" sont traitées en détail
> complet (code + prompt) ; les sections "priorité moyenne/basse" ont une spec allégée
> avec idée d'implémentation et amorce de prompt, à approfondir plus tard si besoin.

---

## Sommaire

**Partie 0 — État du projet**
- 0.1 Architecture actuelle (vue d'ensemble)
- 0.2 Stack technique
- 0.3 Conventions de code et règles métier

**Partie 1 — Bugs : historique et état actuel**
- 1.1 Bugs résolus (traçabilité)
- 1.2 Bugs actifs / surveillance continue
- 1.3 Bugs potentiels identifiés (préventif)

**Partie 2 — Fonctionnalités en cours / partiellement faites**
- 2.1 Warmup modèles au démarrage
- 2.2 Google Drive — écriture réelle
- 2.3 Vision images — workflow corrigé BAC
- 2.4 APK mobile — build et test
- 2.5 Clés API NewsAPI / AVWX

**Partie 3 — Priorité haute (détail complet)**
- 3.1 Wake word "Hey ARIA"
- 3.2 Transcription en temps réel
- 3.3 Brief quotidien automatique
- 3.4 Checklist DR400 interactive vocale
- 3.5 Synchronisation Google Calendar
- 3.6 Mode focus / ne pas déranger
- 3.7 Export conversation PDF

**Partie 4 — Priorité moyenne (spec allégée)**
- 4.1 Quiz PPL théorique interactif
- 4.2 Analyse CSV/Excel
- 4.3 Journal de vol vocal
- 4.4 Planning révision BAC automatique
- 4.5 Correction de devoirs par photo
- 4.6 Macros vocaux (séquences d'actions)
- 4.7 Mode allemand immersif

**Partie 5 — Priorité basse (idées + amorce)**
- 5.1 Smart home / IoT
- 5.2 Intégrations réseaux sociaux
- 5.3 Agent autonome multi-étapes
- 5.4 Interface AR
- 5.5 Voix TTS clonée

**Partie 6 — En attente de précisions utilisateur**
- 6.1 Voix bascule "modèle ChatGPT" + débug micro associé
- 6.2 Meilleure compréhension des prompts
- 6.3 Nexus — finalisation et intégration complète

**Partie 7 — Architecture cible finale**
- 7.1 Schéma global des modules
- 7.2 Flux de données bout-en-bout
- 7.3 Checklist de cohérence avant chaque session Cursor

---

*(Les parties suivantes sont générées séquentiellement dans des fichiers séparés
puis assemblées en un seul document final.)*
# Partie 0 — État du projet

## 0.1 Architecture actuelle (vue d'ensemble)

```
assistant-vocal/
├── main.py                  # Point d'entrée, warmup modèles, hooks clavier (F24)
├── ui.py                     # Pont Python ↔ JS (pywebview API), gestion fichiers/wallpapers/presets
├── llm.py                     # Routage intelligent, modèles, conversation, intents
├── stt.py                     # Speech-to-text (faster-whisper)
├── tts.py                     # Text-to-speech (edge-tts + pygame)
├── memory_engine.py            # Mémoire permanente, conversations, préférences
├── ollama_manager.py            # Gestion warmup/chargement modèles Ollama
├── app_paths.py                # Chemins compatibles PyInstaller
├── api_keys.py                  # (v15) Registre centralisé clés API
├── config.yaml / config.example.yaml
├── aria_mobile_server.py        # Serveur Flask mobile (PIN, cache, endpoints)
├── train_aria.py / auto_train.py # Fine-tuning Unsloth/LoRA
│
├── actions/
│   ├── apps.py                  # Lancement/fermeture apps (~200 + scan dynamique)
│   ├── browser.py                # Navigation web, alias sites, recherche
│   ├── weather.py                 # Météo (OpenWeather + wttr.in fallback)
│   ├── aviation.py                 # METAR/TAF (AVWX + aviationweather.gov fallback)
│   ├── web_search.py               # Recherche DDG (ddgs)
│   ├── alias_store.py               # Base SQLite alias sites (~112M entrées, 18.6Go)
│   ├── presets.py                    # Presets Vol/Étude/Gaming/Détente/Nuit
│   ├── system.py                      # Volume, luminosité, veille...
│   ├── timer.py                        # Minuteurs
│   ├── cache.py                        # (v15) Cache générique TTL par catégorie
│   └── nexus.py                         # (v15) Slot connexion Nexus (code local)
│
├── ui/
│   └── index.html               # Interface complète (chat, sidebar, settings, thèmes)
│
├── data/
│   ├── memory.json               # Mémoire permanente
│   ├── conversations/             # Historique conversations
│   ├── site_aliases.db             # Base alias sites (gitignored, ~18.6Go)
│   ├── wallpapers/                   # (v13) Fonds d'écran personnalisés
│   └── fine_tune_dataset.jsonl       # Dataset d'entraînement
│
├── scripts/
│   ├── double_sites.py            # Doublement alias (max 20Go, usage manuel uniquement)
│   ├── shrink_aliases_db.py        # Réduction taille DB
│   └── run_double_sites_x3.ps1
│
├── aria-mobile/                  # App Expo (PIN+IP, chat streaming)
│   ├── app.json / package.json / eas.json
│   ├── app/ (index.tsx, chat.tsx, settings.tsx)
│   ├── components/ (MessageBubble, VoiceButton, OrbAnimation)
│   └── hooks/useARIA.ts
│
└── tests/ (à développer — actuellement peu de couverture)
```

---

## 0.2 Stack technique

| Composant | Technologie | Rôle |
|---|---|---|
| UI desktop | pywebview + HTML/CSS/JS | Interface principale |
| LLM local | Ollama | llama3.2:1b (intent), llama3.1:8b (rapide), qwen3:14b (approfondi), minicpm-v (vision) |
| Code local | Nexus (qwen2.5-coder:14b) — en préparation | Génération de code |
| STT | faster-whisper | Transcription vocale |
| TTS | edge-tts (fr-FR-DeniseNeural) + pygame | Synthèse vocale |
| Recherche web | ddgs (DuckDuckGo) | Fallback gratuit recherche |
| Météo | OpenWeatherMap (optionnel) + wttr.in (fallback) | Données météo |
| Aviation | AVWX (optionnel) + aviationweather.gov (fallback) | METAR/TAF |
| Base alias | SQLite | ~112M entrées, navigation par alias vocal |
| Fine-tuning | Unsloth/LoRA sur llama3.1:8B-bnb-4bit | Personnalisation modèle |
| Mobile | Flask+gevent (serveur) / Expo React Native (client) | Accès distant |
| Hardware | MSI laptop RTX 5080 (16GB VRAM) | Inférence locale |

---

## 0.3 Conventions de code et règles métier

### Règles générales
- Toutes les réponses ARIA sont en **français**
- `msfs` sans précision → MSFS2024 par défaut (MSFS2020 et MSFS2024 sont des entrées séparées)
- Préfixes vocaux pour les alias de sites, cycle : open → ouvrir → go to → va sur → lance → visite → site → ...
- Ne **jamais** committer `data/site_aliases.db` (gitignored)
- "continue" / "double les sites" → exécuter `python scripts/double_sites.py` (max 20Go, vérif espace disque obligatoire)

### Routage modèles (rappel v15)
- Intent classification → `llama3.2:1b`
- Conversation/formatage rapide → `llama3.1:8b-instruct-q8_0`
- Maths/aviation/analyses longues → `qwen3:14b`
- Images → `minicpm-v`
- Code → Nexus (qwen2.5-coder:14b) avec fallback `qwen3:14b` si Nexus indisponible

### Conventions de fichiers de specs
- Chaque feature majeure = un fichier `aria-spec-vXX-nom.md` dans `/mnt/user-data/outputs/`
- Chaque spec contient : contexte, design, code, **prompt Cursor prêt à coller en bloc cité**
- Un seul prompt par feature, qui liste explicitement les fichiers à modifier ("Only modify X, Y")

### Style utilisateur (pour fine-tuning / mémoire)
- Communique en français, style direct et concis
- Préfère le concret/actionnable à la théorie
- Fautes récurrentes type "ducoup", "focntionne" — à connaître pour le fine-tuning mais
  ARIA ne doit PAS les reproduire dans ses réponses (corriger silencieusement)
# Partie 1 — Bugs : historique et état actuel

## 1.1 Bugs résolus (traçabilité)

| # | Bug | Symptôme | Cause | Correction | Statut |
|---|---|---|---|---|---|
| B01 | Fenêtre pywebview invisible au démarrage | "UI init done" loggé mais aucune fenêtre visible | `pygame.mixer.init()` bloquant au chargement du module tts.py | Init paresseuse du mixer (`_ensure_mixer()` appelé seulement à l'usage) | ✅ Résolu, confirmé par l'utilisateur |
| B02 | `ensure_db()` relance des batches massifs | Doublement automatique au démarrage, DB explose | `ensure_db()` appelait la logique de doublement à chaque lancement | `ensure_db()` ne fait plus que vérifier/créer le schéma, jamais de traitement par lots | ✅ Résolu |
| B03 | "ouvre youtube sur chrome" n'ouvre que Chrome | Chrome s'ouvre vide, pas de navigation vers YouTube | Intent `lancer_app` matchait "chrome" au lieu d'extraire le site | `SITE_OPEN_PATTERN` regex prioritaire qui extrait le SITE avant le nom du navigateur | ✅ Résolu |
| B04 | `duckduckgo_search` renommé | RuntimeWarning à chaque recherche | Package renommé en `ddgs` | Import avec fallback `try: from ddgs import DDGS except: from duckduckgo_search import DDGS` | ✅ Résolu |
| B05 | ResourceWarning fichier non fermé | `ui.py` ligne 430, fichier jsonl ouvert sans `with` | `dataset_path.open()` sans context manager | `with dataset_path.open(...) as f:` | ✅ Résolu |
| B06 | Micro "Invalid sample rate -9997" | STT ne démarre jamais, erreur PortAudio | 16000Hz non supporté nativement par le device | `_open_mic_stream()` essaie native_rate → 48000 → 44100 → 16000 → 22050, puis resample vers 16kHz pour Whisper | ✅ Résolu |
| B07 | `site_aliases.db` ~160Go (DB 79Go + WAL 82Go) | Disque C: saturé, `database or disk is full` | Batches de doublement répétés sans limite, INSERT SELECT massif (~223M lignes), COUNT(*) bloquant | Réécriture `alias_store.py` (INSERT SELECT par lots, `fast_count()` via MAX(rowid), `shrink_db()`), `double_sites.py` limité à 20Go max avec vérif espace disque | ✅ Résolu (shrink → 18.6Go, 112M entrées) |
| B08 | History cleared en boucle (5x) | Logs montrent 5 appels consécutifs `History cleared` | `clear_history()` appelé sans debounce depuis plusieurs handlers UI | Debounce 1s ajouté (`_last_clear_time`) | ✅ Résolu |

---

## 1.2 Bugs actifs / surveillance continue

| # | Élément | Risque | Mitigation actuelle | Action si ça se reproduit |
|---|---|---|---|---|
| A01 | `data/site_aliases.db` (~18.6Go) | Peut regrossir si `double_sites.py` relancé sans vérif | `double_sites.py` plafonné à 20Go avec check espace disque avant exécution | Lancer `shrink_aliases_db.py --max-gb 15` si dépassement |
| A02 | `ensure_db()` au démarrage | Régression possible si du code futur réintroduit un appel automatique à doublement | Code actuel passif (vérif schéma uniquement) | Grep `apply_prefix\|double_sites\|rebuild_db` dans tout appel au démarrage avant chaque session Cursor touchant alias_store.py |
| A03 | Warmup double modèle au démarrage (qwen3:14b + llama3.1:8b simultanés) | ~35s de démarrage, consomme beaucoup de VRAM en même temps | Prompt envoyé pour ne warmup que `MODELS['fast']` — **statut non confirmé** | Vérifier les logs de démarrage : un seul "Chargement modèle ... en VRAM" doit apparaître au lieu de deux |
| A04 | Encodage terminal (CP850 vs UTF-8) | Caractères accentués mal affichés dans les logs (`initialisÚ` au lieu de `initialisé`) | `$env:PYTHONUTF8=1` à définir avant lancement | Ajouter `PYTHONUTF8=1` dans le script de lancement permanent (`.bat` ou raccourci) pour ne pas avoir à le taper chaque fois |
| A05 | Process Python qui se termine silencieusement | `main.py` finit son init puis se ferme sans erreur visible si exception non catchée dans `webview.start()` | Logging ajouté autour de `webview.start()` avec try/except + `exc_info=True` | Si ça se reproduit, vérifier les logs pour la trace complète de l'exception |

---

## 1.3 Bugs potentiels identifiés (préventif)

Ces points n'ont pas (encore) causé de crash mais représentent des risques identifiés
en lisant le code actuel — à surveiller lors des prochaines sessions Cursor.

| # | Risque potentiel | Pourquoi c'est un risque | Recommandation |
|---|---|---|---|
| P01 | `_active_images` sans limite de taille | Si l'utilisateur importe beaucoup d'images au fil d'une longue conversation, le contexte envoyé au LLM vision peut devenir énorme et ralentir/échouer | Limiter `_active_images` aux N dernières images (ex: 5), avec purge automatique |
| P02 | Cache `actions/cache.py` (v15) sans limite de taille mémoire | Le cache est un dict Python en mémoire sans cap — sur une session très longue (jours), pourrait grossir indéfiniment | Ajouter une limite (ex: 500 entrées max, éviction LRU) ou un TTL de purge globale |
| P03 | `_installed_apps_cache` (scan apps, v-prompt 5) basé sur scan registre + start menu + Steam | Si l'utilisateur installe une nouvelle app pendant qu'ARIA tourne, elle n'apparaît qu'après le cache de 1h ou un refresh manuel | Le bouton "🔄 Rafraîchir" existe déjà — s'assurer qu'il est visible et documenté |
| P04 | `nexus.py` avec `requests.post(timeout=60)` | Si Nexus devient lent (gros modèle qwen2.5-coder:14b en cours de chargement), ARIA peut sembler figé 60s | Envisager un message intermédiaire "Nexus réfléchit..." via `ui.set_status('thinking')` avant l'appel bloquant, ou passer en async |
| P05 | PIN hardcodé "0000" en dur dans le JS (`ui/index.html`) | Le code source est dans le repo Git (même si data/ est gitignored) — le PIN est visible par quiconque lit le code | Acceptable pour usage perso, mais si le repo devient public il faudrait déplacer le PIN dans `config.yaml` (gitignored) |
| P06 | `aria_mobile_server.py` écoute sur `0.0.0.0:5000` | Accessible à n'importe qui sur le réseau local, protégé seulement par PIN+token | OK pour réseau domestique de confiance ; si réseau partagé (université, etc.), envisager de restreindre l'écoute à l'IP locale spécifique ou ajouter un rate-limit sur `/auth` |
| P07 | `_resample_to_16k()` avec `scipy.signal.resample` | Le resampling FFT-based peut introduire des artefacts (ringing) sur des signaux courts | Si la qualité de transcription semble mauvaise après le fix B06, essayer `scipy.signal.resample_poly` (filtrage polyphase, moins d'artefacts) |
| P08 | Pas de tests automatisés | Toute régression doit être détectée manuellement en relisant les logs | Envisager (priorité basse) un petit script `tests/smoke_test.py` qui vérifie : Ollama accessible, modèles présents, DB alias accessible, mixer initialisable — exécuté avant chaque lancement |
# Partie 2 — Fonctionnalités en cours / partiellement faites

## 2.1 Warmup modèles au démarrage

**État** : prompt envoyé pour ne warmup que `MODELS['fast']` (llama3.1:8b) + `MODELS['intent']`
(llama3.2:1b) au démarrage, en laissant `qwen3:14b` se charger à la première utilisation —
**non confirmé appliqué**.

### Vérification à faire
Relancer ARIA et vérifier dans les logs :
```
[ollama_manager] [INFO] Chargement modèle llama3.1:8b-instruct-q8_0 en VRAM...
[ollama_manager] [INFO] Chargement modèle llama3.2:1b en VRAM...
```
Il ne doit PAS y avoir de ligne "Chargement modèle qwen3:14b en VRAM..." au démarrage.

### Si pas encore appliqué — prompt Cursor
> Dans main.py, vérifie la fonction qui fait le warmup des modèles au démarrage. Elle doit
> UNIQUEMENT démarrer `llm.MODELS['fast']` et `llm.MODELS['intent']` en arrière-plan
> (threads daemon), et NE PAS appeler `ollama_manager.warmup_model` pour `llm.MODELS['heavy']`
> (qwen3:14b). qwen3:14b doit se charger naturellement lors de son premier usage réel
> (premier appel à `_conversation()` qui sélectionne le modèle heavy).
>
> ```python
> import threading
> threading.Thread(target=ollama_manager.warmup_model, args=(llm.MODELS['fast'],), daemon=True).start()
> threading.Thread(target=ollama_manager.warmup_model, args=(llm.MODELS['intent'],), daemon=True).start()
> # PAS de warmup pour MODELS['heavy']
> ```
>
> Modifie uniquement main.py.

---

## 2.2 Google Drive — écriture réelle

**État** : le routing d'intent existe (drive_search, drive_list dans API_THEN_LLM), mais
utilise actuellement un fallback navigateur (ouvre drive.google.com) plutôt que le MCP
Google Drive avec lecture/écriture réelle de fichiers.

### Cas d'usage cible
- "Crée un document Google Docs avec [contenu]"
- "Cherche le fichier [nom] dans mon Drive"
- "Ajoute cette note à mon fichier [nom]"
- "Liste mes fichiers récents"

### Approche recommandée
ARIA tourne en local, donc l'intégration MCP Google Drive (telle que disponible côté
Claude.ai) n'est pas directement appelable depuis le Python local. Deux options :

**Option A — Google Drive API directe (recommandée)**
Utiliser `google-api-python-client` avec OAuth2, credentials stockés localement
(`data/google_credentials.json`, gitignored).

```python
# actions/gdrive.py
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

def get_service():
    creds = Credentials.from_authorized_user_file('data/google_token.json')
    return build('drive', 'v3', credentials=creds)

def search_files(query: str, max_results: int = 10) -> list:
    service = get_service()
    results = service.files().list(
        q=f"name contains '{query}'",
        pageSize=max_results,
        fields="files(id, name, mimeType, modifiedTime)"
    ).execute()
    return results.get('files', [])

def create_doc(title: str, content: str) -> str:
    """Crée un Google Doc avec le contenu donné."""
    from googleapiclient.discovery import build
    docs_service = build('docs', 'v1', credentials=Credentials.from_authorized_user_file('data/google_token.json'))
    drive_service = get_service()

    doc = docs_service.documents().create(body={'title': title}).execute()
    doc_id = doc['documentId']

    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={'requests': [{'insertText': {'location': {'index': 1}, 'text': content}}]}
    ).execute()

    return f"Document '{title}' créé : https://docs.google.com/document/d/{doc_id}"
```

**Option B — Rester en fallback navigateur** (plus simple, moins puissant)
Garder le comportement actuel (ouvrir drive.google.com avec une recherche), suffisant
si l'usage est occasionnel.

### Prompt Cursor (Option A)
> Implémente l'intégration Google Drive réelle via l'API officielle.
>
> 1. Installe les dépendances :
> ```bash
> pip install google-auth google-auth-oauthlib google-api-python-client
> ```
> Ajoute à requirements.txt : `google-auth`, `google-auth-oauthlib`, `google-api-python-client`
>
> 2. Crée `actions/gdrive.py` avec :
> - `get_service()` : charge les credentials depuis `data/google_token.json` (gitignored)
> - `search_files(query, max_results=10)` : recherche par nom
> - `create_doc(title, content)` : crée un Google Doc
> - `append_to_doc(doc_id, content)` : ajoute du texte à un doc existant
> - `list_recent(max_results=10)` : fichiers récents
> - Gestion d'erreur : si `data/google_token.json` absent, retourne un message clair
>   "Google Drive non configuré. Lance `python setup_gdrive.py` pour l'authentifier."
>
> 3. Crée `setup_gdrive.py` (script one-shot) qui fait le flow OAuth2 (ouvre le navigateur,
> demande l'autorisation, sauvegarde le token dans `data/google_token.json`)
>
> 4. Dans llm.py, route les intents `drive_search`, `drive_create_doc`, `drive_list`,
> `drive_append` vers `actions/gdrive.py`, avec fallback vers l'ouverture navigateur si
> non configuré.
>
> 5. Ajoute `data/google_token.json` et `data/google_credentials.json` au .gitignore
>
> Crée actions/gdrive.py, setup_gdrive.py. Modifie requirements.txt, llm.py, .gitignore.

---

## 2.3 Vision images — workflow corrigé BAC

**État** : `minicpm-v` est configuré dans MODELS mais n'a jamais été testé en conditions
réelles avec une photo de corrigé/exercice BAC.

### Workflow cible
1. L'utilisateur prend une photo d'un exercice ou d'un corrigé (via le bouton 📎, déjà
   fonctionnel pour multi-fichiers depuis le prompt précédent)
2. ARIA analyse l'image avec `minicpm-v`
3. Selon le contenu détecté :
   - Si c'est un **énoncé** → ARIA propose de le résoudre (bascule vers `qwen3:14b` pour
     la résolution mathématique, en utilisant la description de l'image comme contexte)
   - Si c'est un **corrigé/correction** → ARIA explique les points clés, identifie les
     erreurs si l'utilisateur a aussi soumis sa propre copie

### Code — fonction d'analyse d'image dédiée
```python
# Dans llm.py
def analyze_homework_image(image_b64: str, user_prompt: str = "") -> str:
    """Analyse une image de devoir/exercice avec minicpm-v, puis route vers qwen3 si calcul nécessaire."""

    vision_prompt = (
        "Décris précisément le contenu de cette image : s'agit-il d'un énoncé d'exercice, "
        "d'une correction, d'un graphique, ou d'autre chose ? Transcris le texte/les formules "
        "mathématiques visibles le plus fidèlement possible."
    )

    description = ask_with_image(image_b64, vision_prompt, model=MODELS['vision'])

    # Heuristique : si la description contient des indices de calcul à faire
    needs_solving = any(kw in description.lower() for kw in [
        'énoncé', 'exercice', 'calculer', 'démontrer', 'résoudre', 'déterminer'
    ])

    if needs_solving and not user_prompt:
        # Bascule vers qwen3:14b pour résoudre, avec la description comme contexte
        solve_prompt = f"Voici un exercice transcrit depuis une photo:\n\n{description}\n\nRésous-le étape par étape."
        return ask_return_text(solve_prompt, model=MODELS['heavy'])

    if user_prompt:
        # L'utilisateur a posé une question spécifique sur l'image
        combined = f"Contexte de l'image: {description}\n\nQuestion: {user_prompt}"
        return ask_return_text(combined, model=MODELS['heavy'])

    return description
```

### Prompt Cursor
> Ajoute `analyze_homework_image(image_b64, user_prompt="")` dans llm.py comme spécifié
> ci-dessus (description via minicpm-v, puis bascule vers qwen3:14b si un calcul/résolution
> est détecté ou si l'utilisateur a posé une question).
>
> Route l'intent vers cette fonction quand une image est présente dans `_active_images`
> ET que le texte contient des mots-clés comme "corrige", "vérifie", "résous", "explique
> cet exercice", "qu'est-ce que tu en penses" — ou par défaut si une image est envoyée
> sans texte.
>
> Modifie uniquement llm.py.

---

## 2.4 APK mobile — build et test

**État** : code généré (app Expo complète avec PIN, chat streaming, hooks), jamais buildé
ni testé sur un téléphone réel. **Explicitement mis en pause** par l'utilisateur — "à faire
quand tout est fini".

### Checklist pour quand ce sera le moment
1. `cd aria-mobile && npm install`
2. `eas login` (créer un compte Expo si besoin)
3. `eas build:configure`
4. `eas build --platform android --profile preview` → génère un APK téléchargeable
5. Installer l'APK sur le téléphone (activer "sources inconnues")
6. Vérifier que `aria_mobile_server.py` tourne sur le PC et que le téléphone est sur le
   même réseau WiFi
7. Dans l'app, entrer l'IP du PC (visible dans la page d'accueil du serveur, voir fix
   précédent qui affiche IP+PIN sur `http://<IP>:5000/`)
8. Tester : ping, auth PIN, premier message, streaming, action sur PC (lancer une app)

### Points de vigilance identifiés à l'avance
- Le PIN mobile et le PIN desktop sont-ils le même ? (actuellement oui, "0000" — à
  centraliser dans config.yaml si besoin de PINs différents)
- `/ask/fast` utilise `MOBILE_MODEL = llama3.1:8b` — vérifier que ce choix reste pertinent
- Latence réseau WiFi vs latence locale : le `/warmup` doit être appelé au lancement de
  l'app mobile pour éviter un premier message lent

Pas de prompt pour l'instant — à reprendre en fin de projet comme convenu.

---

## 2.5 Clés API NewsAPI / AVWX

**État** : le système `api_keys.py` (v15) est prêt à gérer ces clés, mais elles ne sont
pas encore renseignées dans `config.yaml`.

### Pour activer NewsAPI (optionnel)
1. Créer un compte sur https://newsapi.org (gratuit, 100 requêtes/jour)
2. Récupérer la clé API
3. Ajouter dans `config.yaml` :
```yaml
newsapi_key: "ta_cle_ici"
```
4. Relancer ARIA — `api_keys.check_status('newsapi')` devrait passer à `ok`

### Pour activer AVWX (optionnel, recommandé pour aviation)
1. Créer un compte sur https://avwx.rest (gratuit avec limite)
2. Récupérer le token API
3. Ajouter dans `config.yaml` :
```yaml
avwx_api_key: "ton_token_ici"
```
4. Avantage AVWX vs aviationweather.gov : données décodées plus riches (JSON structuré),
   utile pour le mode "checklist DR400" (partie 3.4) et "go/no-go" (intent `aviation_gonogo`)

### Sans ces clés
Le système fonctionne déjà via les fallbacks gratuits (`ddgs` pour les actus,
`aviationweather.gov` pour METAR/TAF brut) — ces clés sont des améliorations, pas des
prérequis.

Pas de prompt nécessaire — c'est une action manuelle de l'utilisateur (créer comptes +
éditer config.yaml). `api_keys.py` détecte automatiquement la présence des clés.
# Partie 3 — Priorité haute (détail complet)

## 3.1 Wake word "Hey ARIA"

### Contexte
Actuellement, le micro est activé/désactivé via la touche F24 (Copilot remappée) ou
Ctrl+Shift+A. Objectif : ajouter un mode optionnel où ARIA écoute en permanence un
mot-clé ("Hey ARIA" / "Dis ARIA") pour s'activer sans toucher le clavier — utile pendant
le vol (mains occupées) ou en jeu.

### Approche technique
Un wake word detector léger tourne EN CONTINU sur un thread séparé, à très faible coût
CPU, et ne déclenche le pipeline STT complet (faster-whisper) que lorsqu'il détecte le
mot-clé.

**Choix de librairie** : `openwakeword` (open-source, modèles pré-entraînés légers,
fonctionne offline, CPU-only). Alternative : Porcupine (Picovoice) mais nécessite une
clé API gratuite avec limite.

### Installation
```bash
pip install openwakeword
```
Ajouter `openwakeword` à requirements.txt.

openwakeword fournit des modèles pré-entraînés pour des mots communs anglais
("hey jarvis", "alexa"...) mais PAS nativement "Hey ARIA" en français. Deux options :

**Option A (rapide)** : utiliser le modèle pré-entraîné "hey_jarvis" tel quel — l'utilisateur
dit "Hey Jarvis" pour activer ARIA (fonctionne immédiatement, juste une convention différente)

**Option B (sur mesure)** : entraîner un modèle custom "Hey ARIA" avec
`openwakeword.train` — nécessite ~30min d'enregistrements + augmentation de données,
processus documenté sur le repo openwakeword. Plus long mais cohérent avec le nom.

Recommandation : démarrer avec l'**Option A** (hey_jarvis) pour valider le concept,
migrer vers Option B si satisfaisant.

### Architecture du module wake word

```python
# wake_word.py — nouveau fichier
"""
Détection de mot-clé en continu, faible coût CPU.
Tourne sur un thread séparé du pipeline STT principal.
"""
import logging
import threading
import numpy as np
import sounddevice as sd
from openwakeword.model import Model

logger = logging.getLogger(__name__)

_stop_event = threading.Event()
_wake_callback = None

def start(callback, model_name: str = "hey_jarvis_v0.1"):
    """Démarre l'écoute du wake word. callback() est appelé quand détecté."""
    global _wake_callback
    _wake_callback = callback
    _stop_event.clear()
    thread = threading.Thread(target=_listen_loop, args=(model_name,), daemon=True)
    thread.start()
    logger.info("Wake word detection démarrée (modèle: %s)", model_name)

def stop():
    _stop_event.set()

def _listen_loop(model_name: str):
    try:
        oww_model = Model(wakeword_models=[model_name], inference_framework="onnx")
    except Exception as e:
        logger.error("Impossible de charger le modèle wake word: %s", e)
        return

    SAMPLE_RATE = 16000
    CHUNK = 1280  # 80ms à 16kHz, requis par openwakeword

    try:
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16', blocksize=CHUNK)
        stream.start()
    except Exception as e:
        logger.error("Impossible d'ouvrir le micro pour wake word: %s", e)
        return

    logger.info("En écoute du wake word...")
    cooldown = 0

    while not _stop_event.is_set():
        try:
            audio, _ = stream.read(CHUNK)
            audio = audio.flatten()

            if cooldown > 0:
                cooldown -= 1
                continue

            prediction = oww_model.predict(audio)
            for mdl, score in prediction.items():
                if score > 0.5:  # seuil de confiance
                    logger.info("Wake word détecté (%s, score=%.2f)", mdl, score)
                    cooldown = 20  # ~1.6s de pause pour éviter les déclenchements multiples
                    if _wake_callback:
                        _wake_callback()
        except Exception as e:
            logger.warning("Erreur boucle wake word: %s", e)

    stream.stop()
    stream.close()
```

### Intégration dans main.py
```python
import wake_word

def on_wake_word_detected():
    """Appelé quand 'Hey Jarvis' est détecté — active le pipeline STT comme F24."""
    logger.info("Activation par wake word")
    stt.toggle()  # même fonction que F24/Ctrl+Shift+A

# Au démarrage, si activé dans config :
if _config.get('wake_word_enabled', False):
    wake_word.start(on_wake_word_detected)
```

### Config
```yaml
wake_word_enabled: false  # désactivé par défaut, opt-in
wake_word_model: "hey_jarvis_v0.1"
```

### UI — toggle dans paramètres
```html
<div class="setting-row">
  <label>Activation vocale ("Hey Jarvis")</label>
  <input type="checkbox" id="set-wake-word" onchange="aria.toggleWakeWord(this.checked)">
</div>
<div style="font-size:11px;color:var(--text3);margin-top:-4px">
  Dis "Hey Jarvis" pour activer le micro sans toucher le clavier
</div>
```

```javascript
async toggleWakeWord(enabled) {
  await this.api('set_wake_word', enabled);
  this.showToast(enabled ? 'Activation vocale activée' : 'Activation vocale désactivée', 'success');
  if (enabled) {
    this.showToast('Redémarre ARIA pour activer le wake word', 'info');
  }
}
```

```python
# ui.py
def set_wake_word(self, enabled: bool) -> None:
    import yaml, app_paths
    cfg_path = app_paths.config_path()
    with cfg_path.open('r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    cfg['wake_word_enabled'] = enabled
    with cfg_path.open('w', encoding='utf-8') as f:
        yaml.safe_dump(cfg, f, allow_unicode=True)
```

### Prompt Cursor
> Implémente la détection de wake word "Hey Jarvis" comme système d'activation vocale
> optionnel, en plus de F24/Ctrl+Shift+A (qui restent fonctionnels).
>
> 1. Installe `openwakeword` :
> ```bash
> pip install openwakeword
> ```
> Ajoute `openwakeword` à requirements.txt.
>
> 2. Crée `wake_word.py` avec le contenu complet ci-dessus (`start(callback, model_name)`,
> `stop()`, `_listen_loop()`).
>
> 3. Dans main.py :
> - Importe `wake_word`
> - Ajoute `on_wake_word_detected()` qui appelle `stt.toggle()` (la même fonction utilisée
>   par F24)
> - Si `config.get('wake_word_enabled', False)` est True, appelle `wake_word.start(on_wake_word_detected)`
>   au démarrage
>
> 4. Dans config.yaml et config.example.yaml, ajoute :
> ```yaml
> wake_word_enabled: false
> wake_word_model: "hey_jarvis_v0.1"
> ```
>
> 5. Dans ui.py, ajoute `set_wake_word(enabled: bool)` qui met à jour config.yaml.
>
> 6. Dans ui/index.html, section Paramètres → Voix, ajoute un toggle "Activation vocale
> (Hey Jarvis)" avec `toggleWakeWord(enabled)` qui appelle `set_wake_word` et affiche un
> toast indiquant qu'un redémarrage est nécessaire.
>
> Crée wake_word.py. Modifie main.py, config.yaml, config.example.yaml, requirements.txt,
> ui.py, ui/index.html.

---

## 3.2 Transcription en temps réel

### Contexte
Actuellement, STT enregistre jusqu'au silence puis transcrit le bloc entier d'un coup.
Objectif : afficher la transcription mot-à-mot pendant que l'utilisateur parle, comme
Siri/Google Assistant — feedback visuel immédiat.

### Approche technique
faster-whisper ne fait pas de streaming natif "mot par mot" facilement, mais on peut
simuler un effet temps réel en transcrivant des **fenêtres glissantes courtes** (ex: 1.5s
toutes les 0.5s) et en affichant le résultat partiel, qui se stabilise au fur et à mesure.

C'est plus coûteux en CPU/GPU que l'approche actuelle (un seul passage en fin de phrase),
donc cette fonctionnalité doit être **opt-in** (toggle dans paramètres), avec avertissement
sur la consommation ressources si le modèle whisper utilisé est gros.

### Modèle recommandé pour le temps réel
Utiliser `tiny` ou `base` (faster-whisper) pour les fenêtres glissantes (très rapide),
puis faire une transcription finale avec le modèle normal (ex: `small`/`medium`) une fois
le silence détecté — combinant réactivité ET précision finale.

### Code

```python
# Dans stt.py — ajout d'un mode temps réel

import faster_whisper

_realtime_model = None  # modèle léger pour le streaming

def _get_realtime_model():
    global _realtime_model
    if _realtime_model is None:
        _realtime_model = faster_whisper.WhisperModel("tiny", device="cuda", compute_type="int8")
    return _realtime_model


def _record_loop_realtime():
    """Variante de _record_loop avec transcription en temps réel par fenêtres glissantes."""
    stream, actual_rate, blocksize = _open_mic_stream()
    ui.set_status('listening')

    WINDOW_SECONDS = 1.5
    SLIDE_SECONDS = 0.5
    window_size = int(actual_rate * WINDOW_SECONDS)
    slide_size = int(actual_rate * SLIDE_SECONDS)

    rolling_buffer = np.zeros(0, dtype=np.float32)
    full_buffer = []  # pour la transcription finale précise
    speaking = False
    silence_frames = 0
    SILENCE_LIMIT = int(actual_rate / blocksize * 2.0)

    realtime_model = _get_realtime_model()

    while not _stop_event.is_set():
        data, _ = stream.read(blocksize)
        flat = data.flatten()
        rms = float(np.sqrt(np.mean(flat ** 2)) * 32768)

        if rms > THRESHOLD:
            speaking = True
            silence_frames = 0
            full_buffer.append(flat.copy())
            rolling_buffer = np.concatenate([rolling_buffer, flat])

            # Transcription temps réel sur la fenêtre glissante
            if len(rolling_buffer) >= window_size:
                window = rolling_buffer[-window_size:]
                window_16k = _resample_to_16k(window, actual_rate)
                segments, _ = realtime_model.transcribe(window_16k, language='fr', beam_size=1)
                partial_text = ' '.join(s.text for s in segments).strip()
                if partial_text:
                    # Affiche le texte partiel dans l'input (sans valider)
                    ui.show_partial_transcription(partial_text)

                rolling_buffer = rolling_buffer[-slide_size:]  # glisse la fenêtre

        elif speaking:
            silence_frames += 1
            full_buffer.append(flat.copy())
            if silence_frames >= SILENCE_LIMIT:
                # Transcription FINALE précise avec le modèle complet
                audio_np = np.concatenate(full_buffer).astype(np.float32)
                audio_16k = _resample_to_16k(audio_np, actual_rate)
                segments, info = _whisper_model.transcribe(audio_16k, language='fr', beam_size=5, vad_filter=True)
                final_text = ' '.join(s.text for s in segments).strip()

                if final_text:
                    ui.show_final_transcription(final_text)

                full_buffer = []
                rolling_buffer = np.zeros(0, dtype=np.float32)
                speaking = False
                silence_frames = 0
```

### UI — affichage de la transcription partielle

```javascript
showPartialTranscription(text) {
  const input = document.getElementById('text-input');
  input.value = text;
  input.style.color = 'var(--text3)';  // grisé pour indiquer "en cours"
  input.dispatchEvent(new Event('input'));
}

showFinalTranscription(text) {
  const input = document.getElementById('text-input');
  input.value = text;
  input.style.color = 'var(--text)';  // couleur normale = stabilisé
  input.focus();
}
```

### Config + toggle UI
```yaml
realtime_transcription: false  # opt-in, coût CPU/GPU supplémentaire
```

```html
<div class="setting-row">
  <label>Transcription en temps réel</label>
  <input type="checkbox" id="set-realtime-stt" onchange="aria.toggleRealtimeSTT(this.checked)">
</div>
<div style="font-size:11px;color:var(--text3);margin-top:-4px">
  Affiche le texte au fur et à mesure que tu parles (utilise plus de ressources GPU)
</div>
```

### Prompt Cursor
> Ajoute un mode de transcription en temps réel (opt-in) dans stt.py.
>
> 1. Ajoute `_get_realtime_model()` qui charge un modèle faster-whisper "tiny" en int8
> pour les fenêtres glissantes (séparé du modèle principal utilisé pour la transcription
> finale).
>
> 2. Ajoute `_record_loop_realtime()` comme spécifié : fenêtres glissantes de 1.5s
> (slide 0.5s) transcrites avec le modèle "tiny" pendant que l'utilisateur parle, puis
> transcription finale précise avec le modèle principal (`_whisper_model`, actuel) au
> silence détecté.
>
> 3. Dans `_record_loop()` (la fonction existante), ajoute un branchement au début :
> ```python
> if _config.get('realtime_transcription', False):
>     return _record_loop_realtime()
> # ... reste du code existant inchangé
> ```
>
> 4. Dans ui.py, ajoute :
> - `show_partial_transcription(text)` : injecte le texte dans #text-input avec une
>   couleur grisée (`var(--text3)`)
> - `show_final_transcription(text)` : remplace par le texte final, couleur normale, focus
>
> 5. Dans config.yaml et config.example.yaml, ajoute `realtime_transcription: false`
>
> 6. Dans ui/index.html, section Paramètres → Voix, ajoute le toggle "Transcription en
> temps réel" avec `toggleRealtimeSTT(enabled)` qui sauvegarde dans config.yaml via une
> nouvelle fonction `set_realtime_stt(enabled)` dans ui.py (même pattern que
> `set_wake_word`).
>
> Modifie stt.py, ui.py, ui/index.html, config.yaml, config.example.yaml.
## 3.3 Brief quotidien automatique

### Contexte
Au premier lancement d'ARIA chaque jour (ou sur demande "fais-moi mon brief"), ARIA donne
un résumé vocal/textuel : météo du jour, agenda (une fois Google Calendar intégré, voir
3.5), actualités principales, et éventuellement infos aviation (METAR de l'aérodrome
favori si une sortie vol est prévue).

### Architecture

```python
# Dans llm.py ou nouveau module brief.py

def generate_daily_brief() -> str:
    """Génère le brief quotidien en combinant plusieurs sources."""
    from actions.weather import get_current, get_current_free
    from actions.web_search import search_news
    from actions import api_keys, cache
    from datetime import datetime
    import memory_engine as _me

    parts = []
    now = datetime.now()
    parts.append(f"Voici ton brief du {now.strftime('%A %d %B')}.")

    # 1. Météo
    city = _config.get('city', 'Coueron')
    status = api_keys.check_status('openweather')
    weather_data = get_current(city) if status['status'] == 'ok' else get_current_free(city)
    if 'error' not in weather_data:
        parts.append(
            f"Côté météo : {weather_data.get('description')}, "
            f"{weather_data.get('temp')}°C (ressenti {weather_data.get('feels_like')}°C), "
            f"vent à {weather_data.get('wind')} km/h."
        )

    # 2. Agenda du jour (si Google Calendar intégré — voir 3.5)
    try:
        from actions import gcalendar
        events = gcalendar.get_today_events()
        if events:
            event_lines = [f"{e['time']} : {e['title']}" for e in events]
            parts.append("Au programme aujourd'hui : " + ", ".join(event_lines) + ".")
        else:
            parts.append("Pas d'événement particulier prévu aujourd'hui.")
    except ImportError:
        pass  # gcalendar pas encore intégré

    # 3. Actualités principales (2-3 titres)
    news_results = search_news("actualité France", max_results=3)
    if news_results:
        titles = [r.get('title', '') for r in news_results[:3]]
        parts.append("En actualité : " + " ; ".join(titles) + ".")

    # 4. Aviation — si une sortie vol est notée dans la mémoire pour aujourd'hui
    prefs = _me.get_preferences()
    if prefs.get('next_flight_date') == now.strftime('%Y-%m-%d'):
        icao = prefs.get('home_icao', _config.get('home_icao', 'LFRS'))
        from actions.aviation import get_metar
        metar = get_metar(icao)
        if metar:
            # Formate avec LLM
            formatted = _llm_format(f"Décode ce METAR en une phrase simple pour un pilote PPL: {metar}")
            parts.append(f"Pour ton vol prévu aujourd'hui à {icao} : {formatted}")

    return " ".join(parts)
```

### Déclenchement automatique au premier lancement du jour

```python
# memory_engine.py — tracking de la dernière date de brief
def should_show_daily_brief() -> bool:
    """Vrai si le brief n'a pas encore été montré aujourd'hui."""
    from datetime import date
    last_brief = _memory.get('last_brief_date')
    today = date.today().isoformat()
    return last_brief != today

def mark_brief_shown():
    from datetime import date
    _memory['last_brief_date'] = date.today().isoformat()
    save_memory()
```

```python
# main.py — au démarrage, après que l'UI soit prête
import memory_engine as _me

if _config.get('daily_brief_enabled', True) and _me.should_show_daily_brief():
    def _show_brief():
        import time
        time.sleep(3)  # laisser l'UI se stabiliser
        brief = llm.generate_daily_brief()
        ui.show_assistant_text(brief)
        tts.speak(brief)
        _me.mark_brief_shown()

    threading.Thread(target=_show_brief, daemon=True).start()
```

### Commande manuelle
Ajouter l'intent `daily_brief` dans `PURE_ACTIONS` ou `API_THEN_LLM` (c'est plutôt
API_THEN_LLM car combine plusieurs sources) :

```python
elif intent == 'daily_brief':
    brief = generate_daily_brief()
    _speak_response(brief)
    return brief
```

Phrases déclenchantes : "fais-moi mon brief", "résumé de la journée", "quoi de neuf
aujourd'hui", "brief du jour"

### Config + toggle UI
```yaml
daily_brief_enabled: true
```

```html
<div class="setting-row">
  <label>Brief quotidien automatique</label>
  <input type="checkbox" id="set-daily-brief" checked onchange="aria.toggleDailyBrief(this.checked)">
</div>
```

### Prompt Cursor
> Implémente le brief quotidien automatique.
>
> 1. Dans llm.py, ajoute `generate_daily_brief()` comme spécifié ci-dessus (météo +
> actualités + agenda si dispo + aviation si vol prévu aujourd'hui). Gère l'absence de
> `actions/gcalendar` avec un `try/except ImportError` (ce module n'existe pas encore,
> voir partie 3.5).
>
> 2. Ajoute l'intent `daily_brief` dans `API_THEN_LLM` avec les phrases déclenchantes
> "fais-moi mon brief", "résumé de la journée", "quoi de neuf aujourd'hui", "brief du jour"
> dans `_fast_intent()` ou `_detect_intent()`.
>
> 3. Dans memory_engine.py, ajoute `should_show_daily_brief()` et `mark_brief_shown()`
> comme spécifié (tracking `last_brief_date` dans la mémoire).
>
> 4. Dans main.py, au démarrage (après l'init UI), si `config.get('daily_brief_enabled', True)`
> et `memory_engine.should_show_daily_brief()`, lance un thread qui attend 3s, génère le
> brief, l'affiche dans l'UI (`ui.show_assistant_text`), le lit en TTS, puis appelle
> `memory_engine.mark_brief_shown()`.
>
> 5. Dans config.yaml et config.example.yaml, ajoute `daily_brief_enabled: true`
>
> 6. Dans ui/index.html, section Paramètres → Assistant, ajoute le toggle "Brief
> quotidien automatique" avec `toggleDailyBrief(enabled)` (même pattern que les toggles
> précédents, sauvegarde via une nouvelle fonction `set_daily_brief(enabled)` dans ui.py).
>
> Modifie llm.py, memory_engine.py, main.py, ui.py, ui/index.html, config.yaml,
> config.example.yaml.

---

## 3.4 Checklist DR400 interactive vocale

### Contexte
Pour la préparation PPL, une checklist avant-vol interactive : ARIA énonce chaque item de
la checklist DR400 (Robin DR400), attend une confirmation vocale ("fait", "ok", "vérifié")
avant de passer au suivant, et peut répéter ou revenir en arrière sur demande.

### Structure des données — checklist DR400

```yaml
# data/checklists/dr400_pre_vol.yaml
nom: "DR400 — Visite pré-vol"
items:
  - section: "Extérieur"
    points:
      - "Documents de bord présents (carnet de route, certificats)"
      - "Niveau carburant vérifié visuellement aux deux réservoirs"
      - "Pas de fuite de carburant ou d'huile sous le moteur"
      - "Hélice : pas de fissure, pas d'impact"
      - "Capot moteur bien fermé et verrouillé"
      - "Pneus : pression et usure correctes"
      - "Antennes en bon état"
      - "Gouvernes libres, pas de jeu anormal"
      - "Surfaces : pas de givre, neige, ou dommage"

  - section: "Habitacle"
    points:
      - "Ceintures et harnais en bon état"
      - "Documents avion à bord (certificat d'immatriculation, assurance, manuel de vol)"
      - "Masse et centrage calculés et dans les limites"
      - "Carburant suffisant pour le vol + réserve réglementaire"

  - section: "Moteur — avant démarrage"
    points:
      - "Parking brake serré"
      - "Mixture riche"
      - "Volets configurés pour le décollage"
      - "Trim réglé en position neutre"
      - "Zone hélice dégagée — annoncer 'contact'"
```

### Module checklist vocale

```python
# actions/checklist.py
"""
Checklist interactive vocale — avance item par item avec confirmation vocale.
"""
import logging
import yaml
import app_paths

logger = logging.getLogger(__name__)

# État de la checklist en cours (un seul à la fois)
_active_checklist = None
_current_section = 0
_current_item = 0


def load_checklist(name: str) -> dict:
    path = app_paths.data_dir() / "checklists" / f"{name}.yaml"
    with path.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def start_checklist(name: str) -> str:
    """Démarre une checklist. Retourne le premier item."""
    global _active_checklist, _current_section, _current_item
    _active_checklist = load_checklist(name)
    _current_section = 0
    _current_item = 0
    return _format_current_item(intro=True)


def _format_current_item(intro: bool = False) -> str:
    if not _active_checklist:
        return "Aucune checklist en cours."

    sections = _active_checklist['items']
    if _current_section >= len(sections):
        return "Checklist terminée. Tous les points ont été vérifiés."

    section = sections[_current_section]
    points = section['points']

    if _current_item >= len(points):
        return "Section terminée."

    point = points[_current_item]
    progress = f"({_current_item + 1}/{len(points)})"

    prefix = f"Checklist '{_active_checklist['nom']}' démarrée. " if intro else ""
    section_intro = ""
    if _current_item == 0:
        section_intro = f"Section : {section['section']}. "

    return f"{prefix}{section_intro}{progress} {point}. Dis 'vérifié' quand c'est fait."


def confirm_current_item() -> str:
    """L'utilisateur confirme l'item courant ('vérifié', 'ok', 'fait')."""
    global _current_section, _current_item

    if not _active_checklist:
        return "Aucune checklist en cours. Dis 'démarre la checklist DR400' pour commencer."

    sections = _active_checklist['items']
    section = sections[_current_section]
    points = section['points']

    _current_item += 1
    if _current_item >= len(points):
        _current_section += 1
        _current_item = 0
        if _current_section >= len(sections):
            result = "✅ Checklist terminée. Tous les points sont vérifiés. Bon vol !"
            stop_checklist()
            return result

    return _format_current_item()


def repeat_current_item() -> str:
    """Répète l'item courant sans avancer."""
    return _format_current_item()


def go_back() -> str:
    """Revient à l'item précédent."""
    global _current_section, _current_item
    if _current_item > 0:
        _current_item -= 1
    elif _current_section > 0:
        _current_section -= 1
        _current_item = len(_active_checklist['items'][_current_section]['points']) - 1
    return "Retour à l'item précédent. " + _format_current_item()


def stop_checklist() -> None:
    global _active_checklist, _current_section, _current_item
    _active_checklist = None
    _current_section = 0
    _current_item = 0


def is_active() -> bool:
    return _active_checklist is not None
```

### Intégration dans le routage llm.py

La checklist est un **mode conversationnel spécial** : une fois démarrée, les commandes
"vérifié", "suivant", "répète", "retour", "stop" sont interceptées en priorité avant le
routage normal.

```python
# Dans ask(), avant le _fast_intent normal :

from actions import checklist

if checklist.is_active():
    text_lower = text.lower().strip()
    if any(w in text_lower for w in ['vérifié', 'vérifie', 'ok', 'fait', 'check', 'suivant']):
        result = checklist.confirm_current_item()
    elif any(w in text_lower for w in ['répète', 'repete', 'redis', 'encore']):
        result = checklist.repeat_current_item()
    elif any(w in text_lower for w in ['retour', 'précédent', 'arrière']):
        result = checklist.go_back()
    elif any(w in text_lower for w in ['stop', 'arrête', 'annule', 'termine']):
        checklist.stop_checklist()
        result = "Checklist interrompue."
    else:
        # L'utilisateur a dit autre chose — on continue quand même la checklist
        # mais on traite aussi sa demande normalement (ex: question météo en plein milieu)
        result = _route_with_intelligence(intent, params, text)  # flux normal

    ui.append_assistant_text(result)
    ui.finalize_assistant_message()
    _speak_response(result)
    return

# Démarrage
if any(phrase in text.lower() for phrase in ['démarre la checklist', 'commence la checklist', 'checklist dr400', 'checklist pré-vol']):
    result = checklist.start_checklist('dr400_pre_vol')
    _speak_response(result)
    return
```

### UI — affichage visuel de la progression (optionnel mais utile)

```javascript
// Affiche une barre de progression de checklist en haut du chat pendant qu'elle est active
showChecklistProgress(section, item, total) {
  let bar = document.getElementById('checklist-progress');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'checklist-progress';
    bar.className = 'glass';
    bar.style.cssText = 'position:sticky;top:0;margin:8px 16px;padding:10px 16px;border-radius:14px;font-size:13px;z-index:10';
    document.getElementById('messages').prepend(bar);
  }
  bar.innerHTML = `📋 ${section} — item ${item}/${total}`;
}

hideChecklistProgress() {
  document.getElementById('checklist-progress')?.remove();
}
```

### Prompt Cursor
> Implémente une checklist DR400 interactive vocale.
>
> 1. Crée `data/checklists/dr400_pre_vol.yaml` avec le contenu YAML spécifié ci-dessus
> (sections Extérieur/Habitacle/Moteur avec leurs points de vérification).
>
> 2. Crée `actions/checklist.py` avec les fonctions complètes spécifiées : `load_checklist()`,
> `start_checklist()`, `_format_current_item()`, `confirm_current_item()`,
> `repeat_current_item()`, `go_back()`, `stop_checklist()`, `is_active()`.
>
> 3. Dans llm.py, dans `ask()`, AVANT le routage normal d'intent, ajoute l'interception
> de checklist active comme spécifié : si `checklist.is_active()`, route "vérifié/ok/fait"
> → `confirm_current_item()`, "répète" → `repeat_current_item()`, "retour" → `go_back()`,
> "stop/arrête" → `stop_checklist()`. Sinon, traite normalement.
>
> Ajoute aussi la détection de démarrage : phrases "démarre la checklist", "commence la
> checklist", "checklist dr400", "checklist pré-vol" → `checklist.start_checklist('dr400_pre_vol')`.
>
> 4. Dans ui/index.html, ajoute `showChecklistProgress(section, item, total)` et
> `hideChecklistProgress()` comme spécifié — une barre sticky en haut du chat affichant
> la progression. Appelle-la depuis les réponses de checklist (parse la réponse pour
> extraire section/progression, ou passe ces infos séparément depuis Python via un appel
> JS dédié `ui.update_checklist_ui(section, item, total)`).
>
> 5. Dans ui.py, ajoute `update_checklist_ui(section: str, item: int, total: int)` qui
> appelle `showChecklistProgress` côté JS, et `hide_checklist_ui()` qui appelle
> `hideChecklistProgress`.
>
> Crée data/checklists/dr400_pre_vol.yaml, actions/checklist.py. Modifie llm.py, ui.py,
> ui/index.html.
## 3.5 Synchronisation Google Calendar

### Contexte
ARIA doit pouvoir lire l'agenda Google de l'utilisateur (cours, vols planifiés,
événements) pour : le brief quotidien (3.3), répondre à "qu'est-ce que j'ai aujourd'hui",
"ajoute un rendez-vous", "quand est mon prochain cours de maths".

### Approche technique
Même mécanisme OAuth2 que Google Drive (2.2) — idéalement un module d'auth Google
partagé pour éviter de dupliquer le flow.

### Module partagé d'authentification Google

```python
# actions/google_auth.py
"""
Authentification Google partagée (Drive, Calendar, Docs).
Un seul token, scopes combinés.
"""
import logging
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import app_paths

logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/calendar',
]

TOKEN_PATH = lambda: app_paths.data_dir() / "google_token.json"
CREDS_PATH = lambda: app_paths.data_dir() / "google_credentials.json"


def get_credentials() -> Credentials | None:
    """Retourne les credentials valides, ou None si pas configuré."""
    token_path = TOKEN_PATH()
    if not token_path.exists():
        return None

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding='utf-8')

    return creds


def is_configured() -> bool:
    return TOKEN_PATH().exists()


def run_oauth_flow():
    """À exécuter une seule fois (setup_google.py) — ouvre le navigateur pour autoriser."""
    creds_path = CREDS_PATH()
    if not creds_path.exists():
        raise FileNotFoundError(
            f"Place ton fichier credentials.json (depuis Google Cloud Console) dans {creds_path}"
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH().write_text(creds.to_json(), encoding='utf-8')
    logger.info("Authentification Google réussie, token sauvegardé.")
```

### Module Calendar

```python
# actions/gcalendar.py
"""
Intégration Google Calendar.
"""
import logging
from datetime import datetime, timedelta, time as dtime
from googleapiclient.discovery import build
from actions.google_auth import get_credentials, is_configured

logger = logging.getLogger(__name__)


def _service():
    creds = get_credentials()
    if not creds:
        raise RuntimeError("Google Calendar non configuré")
    return build('calendar', 'v3', credentials=creds)


def get_today_events() -> list[dict]:
    """Retourne les événements d'aujourd'hui, triés par heure."""
    if not is_configured():
        return []

    try:
        service = _service()
        now = datetime.utcnow()
        start = datetime.combine(now.date(), dtime.min).isoformat() + 'Z'
        end = datetime.combine(now.date(), dtime.max).isoformat() + 'Z'

        events_result = service.events().list(
            calendarId='primary',
            timeMin=start,
            timeMax=end,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = []
        for e in events_result.get('items', []):
            start_raw = e['start'].get('dateTime', e['start'].get('date'))
            if 'T' in start_raw:
                dt = datetime.fromisoformat(start_raw.replace('Z', '+00:00'))
                time_str = dt.strftime('%H:%M')
            else:
                time_str = "Toute la journée"
            events.append({'time': time_str, 'title': e.get('summary', 'Sans titre')})

        return events
    except Exception as e:
        logger.error("Erreur Google Calendar: %s", e)
        return []


def get_upcoming_events(days: int = 7) -> list[dict]:
    """Événements des N prochains jours."""
    if not is_configured():
        return []

    try:
        service = _service()
        now = datetime.utcnow().isoformat() + 'Z'
        future = (datetime.utcnow() + timedelta(days=days)).isoformat() + 'Z'

        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            timeMax=future,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = []
        for e in events_result.get('items', []):
            start_raw = e['start'].get('dateTime', e['start'].get('date'))
            events.append({'start': start_raw, 'title': e.get('summary', 'Sans titre')})

        return events
    except Exception as e:
        logger.error("Erreur Google Calendar: %s", e)
        return []


def create_event(title: str, start_dt: datetime, duration_minutes: int = 60, description: str = "") -> str:
    """Crée un événement."""
    if not is_configured():
        return "Google Calendar non configuré."

    try:
        service = _service()
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        event = {
            'summary': title,
            'description': description,
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Europe/Paris'},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Europe/Paris'},
        }

        created = service.events().insert(calendarId='primary', body=event).execute()
        return f"Événement '{title}' créé pour le {start_dt.strftime('%d/%m à %H:%M')}."
    except Exception as e:
        logger.error("Erreur création événement: %s", e)
        return f"Erreur lors de la création : {e}"
```

### Routage LLM

```python
# Dans llm.py

elif intent == 'calendar_today':
    from actions import gcalendar
    if not gcalendar.is_configured():
        result = "Google Calendar n'est pas encore configuré. Lance setup_google.py pour l'activer."
    else:
        events = gcalendar.get_today_events()
        if events:
            lines = [f"{e['time']} : {e['title']}" for e in events]
            result = "Aujourd'hui tu as : " + ", ".join(lines) + "."
        else:
            result = "Tu n'as rien de prévu aujourd'hui."
    _speak_response(result)
    return result

elif intent == 'calendar_upcoming':
    from actions import gcalendar
    if not gcalendar.is_configured():
        result = "Google Calendar n'est pas encore configuré."
    else:
        events = gcalendar.get_upcoming_events(7)
        if events:
            lines = [f"{e['title']} ({e['start'][:10]})" for e in events[:5]]
            result = "Dans les 7 prochains jours : " + ", ".join(lines) + "."
        else:
            result = "Rien de prévu dans les 7 prochains jours."
    _speak_response(result)
    return result

elif intent == 'calendar_create':
    from actions import gcalendar
    from datetime import datetime
    # params extraits par le LLM intent : title, date, time, duration
    title = params.get('title', text)
    # Parsing date/heure — utiliser dateparser pour le langage naturel français
    import dateparser
    dt = dateparser.parse(params.get('datetime_text', text), languages=['fr'])
    if not dt:
        result = "Je n'ai pas compris la date/heure. Précise par exemple 'demain à 14h'."
    else:
        result = gcalendar.create_event(title, dt, params.get('duration', 60))
    _speak_response(result)
    return result
```

### Setup script

```python
# setup_google.py
"""
Script one-shot pour configurer l'accès Google (Drive + Calendar + Docs).
1. Va sur https://console.cloud.google.com/
2. Crée un projet, active les APIs Drive/Calendar/Docs
3. Crée des credentials OAuth2 "Desktop app"
4. Télécharge credentials.json → place-le dans data/google_credentials.json
5. Lance ce script : python setup_google.py
"""
from actions.google_auth import run_oauth_flow

if __name__ == '__main__':
    print("Authentification Google pour ARIA...")
    print("Une fenêtre de navigateur va s'ouvrir.")
    run_oauth_flow()
    print("✅ Configuration terminée. Redémarre ARIA.")
```

### Dépendances et .gitignore
```bash
pip install dateparser
```
Ajoute `dateparser` à requirements.txt.

`.gitignore` :
```
data/google_token.json
data/google_credentials.json
```

### Prompt Cursor
> Implémente l'intégration Google Calendar (et prépare l'auth Google partagée pour
> Drive aussi).
>
> 1. Installe les dépendances :
> ```bash
> pip install google-auth google-auth-oauthlib google-api-python-client dateparser
> ```
> Ajoute à requirements.txt.
>
> 2. Crée `actions/google_auth.py` avec le contenu complet ci-dessus (`get_credentials()`,
> `is_configured()`, `run_oauth_flow()`, SCOPES incluant Drive+Calendar+Docs).
>
> 3. Crée `actions/gcalendar.py` avec `get_today_events()`, `get_upcoming_events(days)`,
> `create_event(title, start_dt, duration_minutes, description)`.
>
> 4. Crée `setup_google.py` (script one-shot avec instructions en commentaire) qui
> appelle `google_auth.run_oauth_flow()`.
>
> 5. Dans llm.py, ajoute les intents `calendar_today`, `calendar_upcoming`,
> `calendar_create` comme spécifié, dans `API_THEN_LLM`. Phrases déclenchantes :
> "qu'est-ce que j'ai aujourd'hui", "mon agenda", "mes rendez-vous", "ajoute un
> rendez-vous", "programme un événement".
>
> 6. Ajoute à .gitignore :
> ```
> data/google_token.json
> data/google_credentials.json
> ```
>
> 7. Si tu modifies aussi `actions/gdrive.py` (partie 2.2), fais-le utiliser
> `google_auth.get_credentials()` au lieu de charger ses propres credentials, pour
> partager le même token.
>
> Crée actions/google_auth.py, actions/gcalendar.py, setup_google.py. Modifie llm.py,
> requirements.txt, .gitignore, et actions/gdrive.py si présent.

---

## 3.6 Mode focus / ne pas déranger

### Contexte
Pendant les révisions BAC ou un vol, l'utilisateur veut qu'ARIA limite ses interruptions :
pas de brief automatique, pas de notifications/toasts non essentiels, micro toujours actif
pour les commandes explicites mais ARIA reste plus "discrète" (réponses plus courtes,
TTS désactivé par défaut en mode focus).

### Implémentation

```python
# Dans config.yaml
focus_mode: false
focus_mode_until: null  # ISO datetime, optionnel — désactivation auto après une durée
```

```python
# memory_engine.py ou un nouveau focus.py
import yaml, app_paths
from datetime import datetime, timedelta

def is_focus_active() -> bool:
    cfg = _load_config()
    if not cfg.get('focus_mode', False):
        return False

    until = cfg.get('focus_mode_until')
    if until:
        if datetime.fromisoformat(until) < datetime.now():
            set_focus_mode(False)  # auto-désactivation
            return False
    return True


def set_focus_mode(enabled: bool, duration_minutes: int = None):
    cfg_path = app_paths.config_path()
    with cfg_path.open('r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)

    cfg['focus_mode'] = enabled
    if enabled and duration_minutes:
        until = datetime.now() + timedelta(minutes=duration_minutes)
        cfg['focus_mode_until'] = until.isoformat()
    else:
        cfg['focus_mode_until'] = None

    with cfg_path.open('w', encoding='utf-8') as f:
        yaml.safe_dump(cfg, f, allow_unicode=True)
```

### Effets du mode focus

1. **Brief quotidien** : ne se déclenche pas automatiquement si focus actif
   ```python
   if _config.get('daily_brief_enabled', True) and not is_focus_active() and _me.should_show_daily_brief():
   ```

2. **TTS désactivé par défaut** (l'utilisateur peut le réactiver manuellement quand même)

3. **Toasts limités** : seuls les toasts `error` s'affichent en mode focus, les `info`/`success`
   sont supprimés

4. **Réponses plus courtes** : ajout d'une instruction au system prompt
   ```python
   if is_focus_active():
       system_addition = "\nMode focus actif : sois bref et direct, évite les digressions."
   ```

### Activation/désactivation vocale et UI

Phrases : "active le mode focus", "mode concentration", "ne me dérange pas pendant
[durée]", "désactive le mode focus"

```python
elif intent == 'focus_mode_on':
    duration = params.get('duration_minutes')  # extrait par LLM si présent ("pendant 2 heures")
    focus.set_focus_mode(True, duration)
    result = "Mode focus activé." + (f" Pendant {duration} minutes." if duration else "")
    return result  # pas de _speak_response — cohérent avec le mode silencieux

elif intent == 'focus_mode_off':
    focus.set_focus_mode(False)
    result = "Mode focus désactivé."
    _speak_response(result)
    return result
```

### UI — indicateur visuel
```html
<div id="focus-indicator" style="display:none;position:fixed;top:12px;right:12px;background:rgba(167,139,250,0.15);border:1px solid rgba(167,139,250,0.3);color:#A78BFA;font-size:11px;padding:4px 10px;border-radius:8px;z-index:50">
  🎯 Mode focus
</div>
```

```javascript
updateFocusIndicator(active) {
  document.getElementById('focus-indicator').style.display = active ? 'block' : 'none';
}
```

### Prompt Cursor
> Implémente le mode focus / ne pas déranger.
>
> 1. Crée `focus.py` avec `is_focus_active()` et `set_focus_mode(enabled, duration_minutes=None)`
> comme spécifié (lecture/écriture dans config.yaml, avec auto-désactivation après
> `focus_mode_until` si dépassé).
>
> 2. Dans config.yaml et config.example.yaml, ajoute :
> ```yaml
> focus_mode: false
> focus_mode_until: null
> ```
>
> 3. Dans llm.py :
> - Ajoute les intents `focus_mode_on` et `focus_mode_off` dans PURE_ACTIONS, avec les
>   phrases déclenchantes spécifiées. `focus_mode_on` extrait une durée optionnelle
>   (ex: "pendant 2 heures" → 120 minutes) si présente dans le texte.
> - Dans la construction du system prompt (`build_personalized_system_prompt` ou
>   équivalent), si `focus.is_focus_active()`, ajoute "Mode focus actif : sois bref et
>   direct, évite les digressions."
>
> 4. Dans main.py, le déclenchement du brief quotidien (partie 3.3) doit vérifier
> `not focus.is_focus_active()` en plus des conditions existantes.
>
> 5. Dans ui/index.html, ajoute l'indicateur visuel `#focus-indicator` (coin haut-droit,
> visible seulement si focus actif) avec `updateFocusIndicator(active)`. Dans
> `showToast()`, si le mode focus est actif (vérifié via un appel `aria.api('is_focus_active')`
> mis en cache côté JS), n'affiche que les toasts de type 'error'.
>
> 6. Dans ui.py, ajoute `is_focus_active()` (wrapper Python→JS) et expose-le.
>
> Crée focus.py. Modifie config.yaml, config.example.yaml, llm.py, main.py, ui.py,
> ui/index.html.

---

## 3.7 Export conversation PDF

### Contexte
Permettre d'exporter une conversation (ou un résumé de session de révision) en PDF,
utile pour archiver une séance de travail BAC ou un debrief de vol.

### Approche
Utiliser `fpdf2` (léger, pas de dépendance lourde comme wkhtmltopdf) pour générer un PDF
propre à partir de l'historique de conversation.

```bash
pip install fpdf2
```

### Module export

```python
# actions/export_pdf.py
"""
Export d'une conversation en PDF.
"""
import logging
from datetime import datetime
from fpdf import FPDF
import app_paths

logger = logging.getLogger(__name__)


class ConversationPDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 14)
        self.set_text_color(108, 142, 255)
        self.cell(0, 10, 'ARIA — Export de conversation', ln=True, align='C')
        self.set_font('Helvetica', '', 9)
        self.set_text_color(120, 120, 130)
        self.cell(0, 6, datetime.now().strftime('%d/%m/%Y %H:%M'), ln=True, align='C')
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')


def export_conversation(messages: list[dict], title: str = "Conversation") -> str:
    """
    messages: liste de {'role': 'user'|'assistant', 'content': str, 'timestamp': str}
    Retourne le chemin du fichier PDF généré.
    """
    pdf = ConversationPDF()
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 12)
    pdf.set_text_color(20, 20, 25)
    # Titre — encode en latin-1 avec remplacement pour fpdf2 (pas d'unicode complet par défaut)
    safe_title = title.encode('latin-1', 'replace').decode('latin-1')
    pdf.cell(0, 10, safe_title, ln=True)
    pdf.ln(4)

    for msg in messages:
        role = msg.get('role')
        content = msg.get('content', '')
        timestamp = msg.get('timestamp', '')

        if role == 'user':
            pdf.set_font('Helvetica', 'B', 10)
            pdf.set_text_color(70, 100, 220)
            label = f"Toi ({timestamp})" if timestamp else "Toi"
        else:
            pdf.set_font('Helvetica', 'B', 10)
            pdf.set_text_color(30, 130, 100)
            label = f"ARIA ({timestamp})" if timestamp else "ARIA"

        safe_label = label.encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(0, 6, safe_label, ln=True)

        pdf.set_font('Helvetica', '', 10)
        pdf.set_text_color(30, 30, 35)
        safe_content = content.encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(0, 5.5, safe_content)
        pdf.ln(2)

    out_dir = app_paths.data_dir() / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"aria_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    out_path = out_dir / filename
    pdf.output(str(out_path))
    logger.info("Export PDF créé: %s", out_path)
    return str(out_path)
```

> **Note importante sur l'encodage** : fpdf2 par défaut utilise latin-1, ce qui pose
> problème pour certains caractères français spéciaux ou emojis. Pour un support complet
> de l'UTF-8 (accents, etc. — pas de souci normalement), on peut utiliser une police TTF
> (DejaVu Sans) avec `pdf.add_font()`. Si des caractères apparaissent mal dans le PDF
> généré, c'est la prochaine étape à corriger (ajouter une police Unicode).

### Routage et UI

```python
# Dans llm.py
elif intent == 'export_pdf':
    from actions.export_pdf import export_conversation
    import memory_engine as _me

    current_conv = _me.get_current_conversation_messages()
    path = export_conversation(current_conv, title=_me.get_current_conversation_title())
    result = f"Conversation exportée : {path}"
    return result
```

Phrases : "exporte cette conversation", "exporte en pdf", "fais-moi un pdf de cette
session"

### UI — bouton d'export dans le header de conversation
```html
<button class="glass-btn" title="Exporter en PDF" onclick="aria.exportCurrentConversation()">
  📄
</button>
```

```javascript
async exportCurrentConversation() {
  const result = await this.api('export_current_conversation');
  this.showToast('PDF exporté : ' + result, 'success');
}
```

```python
# ui.py
def export_current_conversation(self) -> str:
    from actions.export_pdf import export_conversation
    import memory_engine as _me
    messages = _me.get_current_conversation_messages()
    title = _me.get_current_conversation_title()
    return export_conversation(messages, title)
```

### Prompt Cursor
> Implémente l'export de conversation en PDF.
>
> 1. Installe `fpdf2` :
> ```bash
> pip install fpdf2
> ```
> Ajoute à requirements.txt.
>
> 2. Crée `actions/export_pdf.py` avec la classe `ConversationPDF` et la fonction
> `export_conversation(messages, title)` comme spécifié. Gère l'encodage avec
> `.encode('latin-1', 'replace').decode('latin-1')` pour éviter les crashs sur
> caractères spéciaux (note dans le code qu'une amélioration future serait d'ajouter
> une police TTF Unicode).
>
> 3. Vérifie dans memory_engine.py si les fonctions `get_current_conversation_messages()`
> et `get_current_conversation_title()` existent déjà. Si non, ajoute-les (elles doivent
> retourner respectivement la liste de messages `{'role', 'content', 'timestamp'}` de la
> conversation active, et son titre).
>
> 4. Dans llm.py, ajoute l'intent `export_pdf` dans PURE_ACTIONS avec les phrases
> déclenchantes "exporte cette conversation", "exporte en pdf", "fais-moi un pdf de cette
> session".
>
> 5. Dans ui.py, ajoute `export_current_conversation()` qui appelle `export_conversation`.
>
> 6. Dans ui/index.html, ajoute un bouton 📄 dans le header de conversation qui appelle
> `exportCurrentConversation()` et affiche un toast avec le chemin du fichier généré.
>
> Crée actions/export_pdf.py. Modifie requirements.txt, memory_engine.py (si besoin),
> llm.py, ui.py, ui/index.html.
# Partie 4 — Priorité moyenne (spec allégée)

Ces fonctionnalités ont un niveau de détail moindre : idée d'implémentation + amorce de
prompt. À approfondir au moment de les traiter (générer un `.md` dédié type v13-v19 si
besoin de code complet).

---

## 4.1 Quiz PPL théorique interactif

### Idée
Réutiliser la base de 200 questions PPL déjà générée (4 documents officiels : Communications,
Aircraft Knowledge, Meteorology, Regulations) mais l'intégrer DANS ARIA plutôt que dans
l'app HTML séparée — ARIA pose les questions à voix haute, l'utilisateur répond
vocalement, ARIA corrige et adapte la difficulté (algorithme de probabilité déjà conçu
pour le mode "weak points").

### Implémentation envisagée
- `data/ppl_questions.json` (200 questions, déjà existant côté app HTML — réutiliser
  le même fichier)
- `actions/quiz.py` : module similaire à `checklist.py` (état de session, question
  courante, score)
- Mode vocal : ARIA lit la question + les 4 choix, attend "A", "B", "C" ou "D" en
  réponse vocale
- À la fin : statistiques par catégorie, identification des points faibles

### Amorce de prompt
> Crée `actions/quiz_ppl.py` sur le modèle de `actions/checklist.py` : charge
> `data/ppl_questions.json` (200 questions PPL avec catégories Communications/Aircraft
> Knowledge/Meteorology/Regulations), gère une session de quiz interactive (question
> courante, score, mode "points faibles" qui repondère vers les catégories où le score
> est bas). Intègre dans llm.py comme mode conversationnel spécial (même pattern que
> checklist : interception prioritaire de "A/B/C/D" pendant qu'un quiz est actif).
> Phrases de démarrage : "lance un quiz PPL", "quiz sur la météo", "teste-moi sur la
> réglementation".

---

## 4.2 Analyse CSV/Excel

### Idée
ARIA peut analyser un fichier CSV/Excel importé (via le système multi-fichiers déjà en
place) : statistiques de base, graphiques simples, réponses à des questions sur les
données ("quelle est la moyenne de la colonne X", "trie par Y").

### Implémentation envisagée
- `pandas` + `openpyxl` pour la lecture
- Le fichier est chargé en mémoire (DataFrame), ARIA génère du code pandas via le LLM
  pour répondre aux questions (pattern "code generation + exec sécurisé" — attention à
  la sécurité de l'exec)
- Pour les graphiques : génération matplotlib → image → affichée dans le chat

### Points de vigilance
- **Sécurité** : exécuter du code généré par LLM sur les données de l'utilisateur
  nécessite un sandboxing (au minimum : `exec()` dans un namespace restreint sans accès
  à `os`, `subprocess`, etc.)
- Fichiers volumineux : limiter la taille de prévisualisation envoyée au LLM (ex: `df.head(20)`
  + `df.describe()` au lieu du fichier complet)

### Amorce de prompt
> Crée `actions/data_analysis.py` : `load_dataframe(file_path)` (pandas, supporte
> csv/xlsx), `get_summary(df)` (describe + dtypes + head), `answer_question(df, question)`
> qui génère du code pandas via `MODELS['heavy']` avec un prompt qui inclut le résumé du
> DataFrame, exécute ce code dans un namespace restreint (`{'df': df, 'pd': pd}` uniquement,
> pas de `__builtins__` dangereux), et retourne le résultat formaté. Pour les graphiques,
> génère avec matplotlib, sauvegarde en PNG dans `data/exports/`, retourne le chemin pour
> affichage dans le chat.

---

## 4.3 Journal de vol vocal

### Idée
Après chaque vol, ARIA pose quelques questions ("durée du vol ?", "aérodrome de
destination ?", "conditions météo rencontrées ?", "remarques ?") et enregistre une
entrée structurée dans un journal de vol (format compatible avec un futur export vers
un logbook officiel).

### Implémentation envisagée
- `data/logbook.json` : liste d'entrées `{date, duree, depart, arrivee, type_vol,
  conditions, remarques, heures_totales_cumulees}`
- Mode conversationnel guidé (même pattern checklist/quiz) : ARIA pose les questions une
  par une
- Calcul automatique des heures cumulées
- Possibilité d'export PDF (réutilise 3.7) au format logbook

### Amorce de prompt
> Crée `actions/logbook.py` sur le pattern checklist.py : session guidée qui pose
> successivement les questions définies (date auto, durée, départ/arrivée ICAO, type de
> vol, conditions, remarques), sauvegarde dans `data/logbook.json`, calcule les heures
> totales cumulées. Intègre dans llm.py : "enregistre mon vol", "ajoute une entrée au
> logbook". Ajoute aussi `get_logbook_summary()` pour répondre à "combien d'heures de vol
> j'ai au total".

---

## 4.4 Planning révision BAC automatique

### Idée
À partir des 10 chapitres de maths spé + chapitres BAC français déjà couverts par les
apps HTML existantes, ARIA génère un planning de révision personnalisé en fonction du
temps disponible avant l'épreuve et des points faibles identifiés (scores des mocks
exams déjà réalisés).

### Implémentation envisagée
- Lire les scores des mock exams (si stockés — sinon demander à l'utilisateur ses scores
  approximatifs par chapitre)
- Algorithme simple : répartir le temps disponible proportionnellement à (1 - score)
  par chapitre, avec un minimum de révision par chapitre même si le score est bon
- Génère un planning jour par jour jusqu'à la date du BAC
- Intégration possible avec Google Calendar (3.5) : crée des événements "Révision
  [chapitre]" automatiquement

### Amorce de prompt
> Crée `actions/revision_planner.py` : `generate_plan(days_remaining, chapter_scores: dict)`
> répartit `days_remaining` jours entre les chapitres proportionnellement à
> `(1 - score)`, avec un plancher minimum de 0.5 jour par chapitre. Retourne une liste
> `{date, chapitre, duree_recommandee}`. Si Google Calendar est configuré (`gcalendar.is_configured()`),
> propose de créer les événements correspondants via `gcalendar.create_event()`. Intègre
> dans llm.py : "fais-moi un planning de révision", "plan de révision pour le bac".

---

## 4.5 Correction de devoirs par photo

### Idée
Extension du workflow vision (2.3) : l'utilisateur prend une photo de SA COPIE
(manuscrite), ARIA compare avec un corrigé connu OU évalue directement la pertinence du
raisonnement, identifie les erreurs, donne un feedback constructif.

### Implémentation envisagée
- Réutilise `analyze_homework_image()` (2.3) mais avec un prompt orienté correction :
  "Voici la copie d'un élève sur cet exercice. Identifie les erreurs de méthode ou de
  calcul, sans donner directement la solution complète — guide l'élève vers la correction."
- Distinction importante : ARIA doit **guider**, pas juste donner la réponse — pédagogie
  active (cohérent avec l'usage scolaire)

### Amorce de prompt
> Étends `analyze_homework_image()` (llm.py, voir partie 2.3) : si l'utilisateur indique
> "corrige ma copie" / "vérifie mon travail" / "j'ai fait ça, c'est juste ?", utilise un
> prompt de correction pédagogique : décrire l'image, identifier les étapes du
> raisonnement de l'élève, repérer les erreurs (calcul, méthode, unités), donner un
> feedback qui guide vers la correction sans la révéler entièrement (sauf si l'élève
> insiste explicitement "donne-moi la réponse").

---

## 4.6 Macros vocaux (séquences d'actions)

### Idée
Permettre à l'utilisateur de définir des séquences d'actions personnalisées déclenchées
par une phrase unique — au-delà des presets existants (qui sont fixes : ouvrir/fermer
apps + volume/luminosité). Exemple : "routine du soir" → ferme les apps de travail,
ouvre Spotify avec une playlist précise, baisse la luminosité, active le mode focus
jusqu'au lendemain matin.

### Implémentation envisagée
- `data/macros.yaml` : liste de macros `{nom, phrases_declenchantes, actions: [...]}`
- Chaque action est un appel à une fonction existante (`apps.launch`, `apps.close`,
  `system.set_volume`, `focus.set_focus_mode`, `browser.open_site`, etc.) avec ses
  paramètres
- Exécution séquentielle avec gestion d'erreur par étape (si une action échoue, continue
  les suivantes et rapporte à la fin)
- Éditeur de macros dans l'UI (similaire à l'éditeur de presets, mais avec plus de
  flexibilité — ordre des actions, types d'actions variés)

### Amorce de prompt
> Crée `actions/macros.py` : charge `data/macros.yaml` (liste de
> `{nom, phrases, actions: [{type, params}]}`), `execute_macro(nom)` exécute chaque
> action séquentiellement via un dispatcher (`type` ∈ 'launch_app', 'close_app',
> 'set_volume', 'open_site', 'set_focus', 'speak', 'wait') en capturant les erreurs par
> étape. Intègre dans llm.py : matching des phrases déclenchantes en priorité haute
> (avant le routage normal). Dans l'UI, ajoute une section "Macros" dans les paramètres
> avec un éditeur basique (liste de macros existantes, ajout/suppression d'actions).

---

## 4.7 Mode allemand immersif

### Idée
Pour la pratique de l'allemand (matière de spécialité d'IMPERO), un mode où ARIA répond
en allemand, corrige la grammaire/syntaxe des messages de l'utilisateur en allemand, et
peut basculer entre français et allemand sur commande.

### Implémentation envisagée
- Toggle "Mode allemand" : quand actif, le system prompt instruit le LLM de répondre en
  allemand ET de signaler les erreurs de l'utilisateur (s'il écrit en allemand) avec une
  correction + explication brève en français
- TTS : edge-tts supporte l'allemand (`de-DE-...Neural`) — bascule de la voix selon la
  langue de la réponse
- STT : faster-whisper supporte la transcription multilingue — détection automatique de
  la langue parlée (déjà présent dans le code via `info.language`)

### Amorce de prompt
> Ajoute un mode "Allemand immersif" : toggle dans paramètres qui ajoute au system prompt
> "Réponds en allemand. Si l'utilisateur écrit en allemand, corrige discrètement ses
> erreurs de grammaire/syntaxe en donnant la version correcte suivie d'une brève
> explication en français entre parenthèses." Dans tts.py, si le mode est actif et que
> la réponse est en allemand (détection simple via langdetect ou via la langue STT
> détectée), utilise la voix `de-DE-KatjaNeural` au lieu de `fr-FR-DeniseNeural`.
> Phrases : "active le mode allemand", "passons à l'allemand", "désactive le mode
> allemand".
# Partie 5 — Priorité basse (idées + amorce)

Ces idées sont notées pour mémoire, sans implémentation détaillée — elles ne sont pas
prioritaires actuellement et certaines dépendent de choix matériels/techniques non
encore arrêtés.

---

## 5.1 Smart home / IoT

### Idée
Contrôle d'appareils domestiques (prises connectées, ampoules, thermostat) via protocoles
type Tasmota/MQTT, Home Assistant, ou Tuya/SmartLife API selon l'écosystème utilisé.

### Pourquoi basse priorité
Nécessite du matériel IoT que l'utilisateur ne possède pas forcément encore, et un choix
d'écosystème (Home Assistant local serait le plus cohérent avec la philosophie "tout en
local" d'ARIA, mais représente un projet à part entière).

### Amorce
Si l'utilisateur a/prend Home Assistant : `actions/smarthome.py` qui appelle l'API REST
locale de Home Assistant (`http://homeassistant.local:8123/api/`) avec un token long-lived,
intents `domotique_allumer`, `domotique_eteindre`, `domotique_temperature`.

---

## 5.2 Intégrations réseaux sociaux

### Idée
Lecture de notifications, envoi de messages courts via Discord/Telegram (déjà dans
KNOWN_APPS pour le lancement, mais pas d'intégration API).

### Pourquoi basse priorité
Risques de confidentialité/sécurité plus élevés (tokens d'API avec accès à des comptes
personnels), et usage incertain — à ne considérer que si un besoin précis émerge
(exemple concret : "lis-moi mes derniers messages Discord non lus").

### Amorce
Discord : bot personnel via `discord.py` avec un token de bot (pas le compte utilisateur
directement, pour rester dans les ToS Discord). Telegram : Bot API officielle, plus
simple et plus sûre que Discord pour ce genre d'usage.

---

## 5.3 Agent autonome multi-étapes

### Idée
ARIA capable d'enchaîner plusieurs actions de façon autonome pour atteindre un objectif
("organise mon week-end de révision : crée le planning, bloque les créneaux dans mon
agenda, et désactive les notifications pendant ces créneaux") sans confirmation à chaque
étape.

### Pourquoi basse priorité
Risque élevé d'actions non désirées en cascade si le LLM interprète mal une étape
intermédiaire. Nécessite un système de confirmation/aperçu avant exécution
("voici ce que je vais faire : ... confirme ?") qui est un développement substantiel en
lui-même — à envisager seulement une fois TOUTES les briques individuelles (3.1-4.7)
sont stables et fiables, puisque l'agent autonome les orchestrerait.

### Amorce
Pattern "plan puis exécute" : le LLM génère d'abord un plan structuré (liste d'actions
avec leurs paramètres, format JSON), ARIA l'affiche à l'utilisateur pour validation, puis
exécute séquentiellement chaque action du plan validé en réutilisant les dispatchers déjà
créés (macros.py de la partie 4.6 serait la base technique).

---

## 5.4 Interface AR

### Idée
Affichage d'informations ARIA (statut, transcription, réponses courtes) en
réalité augmentée — par exemple via des lunettes connectées, ou une fenêtre toujours-au-
dessus en mode "overlay" pendant le vol (informations affichées discrètement sans
masquer la vue extérieure).

### Pourquoi basse priorité
Dépend fortement du matériel (pas de lunettes AR actuellement). Une version "AR pauvre"
réalisable sans matériel spécial serait un widget overlay Windows toujours au-dessus
(transparent, click-through) — déjà partiellement faisable avec pywebview en mode
transparent, mais nécessite des tests sur l'impact en vol (lisibilité, distraction).

### Amorce (version "overlay desktop" réaliste sans matériel AR)
Une seconde fenêtre pywebview, `transparent=True`, `on_top=True`, `frameless=True`,
positionnée en coin d'écran, affichant uniquement le statut/logo JARVIS (partie v14) et
la dernière réponse courte d'ARIA — utile en jeu ou en simulateur de vol sans changer de
fenêtre.

---

## 5.5 Voix TTS clonée

### Idée
Remplacer la voix edge-tts (fr-FR-DeniseNeural) par une voix clonée/personnalisée
(voix de l'utilisateur, ou une voix custom type JARVIS).

### Pourquoi basse priorité
- Nécessite un moteur TTS local supportant le voice cloning (ex: Coqui TTS, XTTS-v2,
  ou des solutions type RVC) — beaucoup plus lourd en ressources GPU que edge-tts (qui
  est un service cloud léger)
- Qualité actuelle (edge-tts Denise) déjà satisfaisante pour l'usage quotidien
- Risque de complexité technique élevé pour un gain perçu incertain
- Chevauche potentiellement le sujet "voix bascule modèle ChatGPT" (partie 6.1, en
  attente de précisions) — pourrait être traité ensemble une fois ce sujet clarifié

### Amorce
Si poursuivi : `Coqui XTTS-v2` (open-source, clonage depuis ~10s d'audio de référence,
tourne sur GPU local). Remplacerait `tts.py` avec une API similaire (`speak(text)`) mais
backend différent. À tester d'abord en standalone (script séparé) avant intégration,
pour évaluer la latence réelle sur le RTX 5080 — si la latence dépasse ~2s pour une
phrase courte, l'expérience conversationnelle s'en trouverait dégradée par rapport à
edge-tts actuel.
# Partie 6 — En attente de précisions utilisateur

Ces sujets sont identifiés mais nécessitent des informations supplémentaires de
l'utilisateur avant de pouvoir générer une spec actionnable. Cette section recense ce
qui est su, ce qui manque, et les questions à poser quand l'utilisateur sera prêt.

---

## 6.1 Voix bascule "modèle ChatGPT" + débug micro associé

### Ce qui est su
- L'utilisateur travaille en parallèle sur un changement de "modèle" pour la voix,
  comparé au mode vocal de ChatGPT (probablement le mode "Advanced Voice" / conversation
  vocale fluide en temps réel avec interruption possible, contrairement au pipeline
  actuel STT→texte→validation manuelle→LLM→TTS)
- Le debug du micro (calibration, sample rate, seuils — déjà partiellement traité en B06)
  est explicitement lié à ce changement : "devra être réglé avec le truc ChatGPT"
- Ceci est en pause, l'utilisateur "bosse dessus" séparément

### Hypothèses sur la direction probable
Le mode vocal "façon ChatGPT" impliquerait typiquement :
1. **Conversation continue sans validation manuelle** : contrairement au comportement
   actuel ("transcription → champ texte, validation manuelle"), le flux serait
   transcription → envoi automatique → réponse → TTS, en boucle continue
2. **Interruption possible** : l'utilisateur peut parler pendant que ARIA répond en TTS,
   ce qui coupe la réponse en cours et traite la nouvelle entrée — nécessite une
   détection VAD (Voice Activity Detection) qui tourne MÊME pendant le TTS, et un
   mécanisme d'interruption du flux TTS (`tts.stop()` existe déjà)
3. **Latence bout-en-bout réduite** : pour que ça paraisse "fluide", il faudrait
   idéalement du streaming à chaque étage (STT streaming → LLM streaming → TTS streaming),
   ce qui rejoint la partie 3.2 (transcription temps réel) mais pousse plus loin avec un
   pipeline complet sans étapes bloquantes

### Ce qui manque pour avancer
- Confirmation : est-ce bien "conversation continue + interruption" que l'utilisateur
  vise, ou autre chose de spécifique au mode vocal ChatGPT qu'il a en tête ?
- Le debug micro associé : est-ce un problème de seuil de détection de fin de parole trop
  agressif/permissif dans ce nouveau mode continu, ou un problème matériel (device,
  sample rate) distinct du fix B06 déjà appliqué ?
- Préférence : ce mode continu doit-il être un toggle séparé (coexister avec le mode
  actuel "validation manuelle"), ou remplacer complètement le comportement actuel ?

### Lien avec l'existant
- `tts.stop()` existe déjà (bouton stop UI + raccourci Escape) — réutilisable pour
  l'interruption
- `_record_loop_realtime()` (partie 3.2) pose les bases du STT en continu par fenêtres
  glissantes — base technique probablement réutilisable
- Le wake word (3.1) pourrait aussi s'articuler avec ce mode : "Hey Jarvis" pour démarrer
  une session de conversation continue, puis silence prolongé pour la terminer

**À reprendre dès que l'utilisateur précise sa vision du "modèle ChatGPT" visé.**

---

## 6.2 Meilleure compréhension des prompts

### Ce qui est su
- L'utilisateur a indiqué vouloir détailler ce point séparément, dans un message dédié
  plus développé
- Aucun détail technique fourni à ce stade

### Hypothèses larges sur ce que ça pourrait couvrir
Sans plus d'info, plusieurs interprétations possibles à clarifier avec l'utilisateur :
1. **Compréhension d'intent plus fine** : aller au-delà des intents actuels (lancer_app,
   meteo, etc.) pour gérer des phrases plus complexes/composées ("ouvre Chrome et lance
   aussi Spotify, et baisse le volume" — actions multiples dans une seule phrase)
2. **Contexte conversationnel** : ARIA comprend mieux les références ("fais la même chose
   pour demain", "et pour LFPO ?" après une question METAR sur LFRS — résolution de
   référence implicite)
3. **Tolérance aux fautes/variantes** : meilleure robustesse face aux fautes de frappe ou
   formulations inhabituelles dans la transcription STT (qui peut produire des erreurs)
4. **Apprentissage des habitudes** : ARIA apprend les formulations préférées de
   l'utilisateur au fil du temps (lié au système de fine-tuning déjà en place)

### Ce qui manque pour avancer
Tout — il faut le message détaillé annoncé par l'utilisateur. Ne pas générer de spec
prématurément sur ce sujet pour éviter de partir dans une mauvaise direction.

**À reprendre intégralement quand l'utilisateur fournit les détails.**

---

## 6.3 Nexus — finalisation et intégration complète

### Ce qui est su
- Nexus = assistant de code local type Cursor, basé sur `qwen2.5-coder:14b`
- En cours de finalisation par l'utilisateur ("également en train de finaliser Nexus")
- Le slot de configuration côté ARIA est déjà préparé (v15 prompt 6) :
  - `actions/nexus.py` avec `is_enabled()`, `is_available()`, `send_prompt(prompt)`
  - Section `nexus` dans `config.yaml` (`enabled`, `endpoint`, `api_key`)
  - Intent `nexus_prompt` routé dans llm.py
  - Indicateur de statut dans l'UI (`check_nexus()`)
  - `MODELS['code']` retiré de llm.py, remplacé par routage conditionnel vers Nexus
    (fallback `qwen3:14b` si Nexus indisponible)

### Ce qui manque pour la finalisation complète
1. **Endpoint réel** : Nexus tourne sur quel port/protocole une fois lancé ? Le slot
   actuel suppose un serveur HTTP local avec endpoints `/ping` et `/prompt` — si Nexus
   expose une API différente (ex: compatible OpenAI `/v1/chat/completions`, ou un
   protocole MCP), `actions/nexus.py` devra être adapté
2. **Authentification** : `api_key` est prévu dans la config — Nexus nécessite-t-il
   vraiment une clé, ou est-ce purement local sans auth (dans ce cas le champ resterait
   vide, ce qui est déjà géré par le code actuel)
3. **Capacités exposées** : Nexus fait-il uniquement de la génération de code "one-shot"
   (prompt → code), ou a-t-il des capacités d'édition de fichiers / exécution comme
   Cursor (lecture de fichiers du projet, édition multi-fichiers, exécution de
   commandes) ? Si Nexus a des capacités d'agent complet, `send_prompt()` est
   insuffisant — il faudrait exposer plus de méthodes (`edit_file`, `run_command`, etc.)
4. **Cas d'usage depuis ARIA** : concrètement, quand l'utilisateur dit "demande à Nexus
   de corriger ce bug", quel est le résultat attendu ? Un texte de réponse (code suggéré)
   affiché dans le chat ARIA, ou Nexus modifie directement les fichiers du projet ARIA
   lui-même (méta : ARIA pilote Nexus pour se modifier elle-même) ?

### Action immédiate possible (sans attendre)
Une fois Nexus lancé localement par l'utilisateur, la première étape de test simple :
```bash
# Vérifier que l'endpoint répond
curl http://localhost:8420/ping
```
Si ça répond, `nexus.is_available()` devrait déjà fonctionner avec la config actuelle
(`enabled: true`, `endpoint: "http://localhost:8420"`). Si le format de `/ping` ou
`/prompt` diffère de ce qu'attend `actions/nexus.py`, ce sera visible immédiatement dans
les logs ARIA (`Erreur Nexus: ...`).

**À reprendre avec : (1) confirmation de l'endpoint/protocole réel de Nexus, (2) test du
`/ping` actuel, (3) clarification des capacités exposées et du cas d'usage souhaité.**
# Partie 7 — Architecture cible finale

## 7.1 Schéma global des modules (vue cible, une fois tout implémenté)

```
                              ┌─────────────────────┐
                              │   ui/index.html      │
                              │ (Liquid Glass v13,   │
                              │  logo JARVIS v14)    │
                              └──────────┬───────────┘
                                          │ pywebview API
                              ┌──────────▼───────────┐
                              │       ui.py           │
                              │  (pont Python↔JS,     │
                              │   fichiers, presets,   │
                              │   wallpapers, focus)   │
                              └──────────┬───────────┘
                                          │
        ┌─────────────────────────────────┼─────────────────────────────────┐
        │                                  │                                  │
┌───────▼────────┐              ┌──────────▼──────────┐            ┌─────────▼─────────┐
│   stt.py         │              │       llm.py          │            │     tts.py          │
│ - faster-whisper  │◄────────────┤ - Routage intelligent  ├───────────►│ - edge-tts          │
│ - wake_word.py     │             │   (v15: api_keys,      │            │ - voix FR/DE (4.7)   │
│   (3.1)             │             │    cache, HEAVY_KW)    │            │ - voix continue      │
│ - mode temps réel   │             │ - MODELS:              │            │   (6.1, en attente)  │
│   (3.2)              │             │   intent/fast/heavy/   │            └─────────────────────┘
│ - mode continu       │             │   vision               │
│   (6.1, en attente)  │             │ - Modes conversation-  │
└─────────────────────┘             │   nels spéciaux:       │
                                     │   checklist (3.4),     │
                                     │   quiz (4.1),          │
                                     │   logbook (4.3)        │
                                     └──────────┬─────────────┘
                                                 │
                  ┌──────────────────────────────┼──────────────────────────────┐
                  │                              │                              │
        ┌─────────▼─────────┐         ┌──────────▼──────────┐        ┌─────────▼─────────┐
        │   actions/          │         │     api_keys.py       │        │   actions/nexus.py  │
        │  - apps.py           │         │  (registre clés API,  │        │  (code, qwen2.5-     │
        │  - browser.py          │       │   check_status,        │       │   coder via Nexus,    │
        │  - weather.py            │     │   fallback auto)        │      │   6.3 en attente)      │
        │  - aviation.py             │   └──────────┬──────────────┘      └───────────────────────┘
        │  - web_search.py             │             │
        │  - alias_store.py               │  ┌──────▼──────┐
        │  - presets.py                     │  │  cache.py    │
        │  - system.py                        │  │ (TTL multi-  │
        │  - checklist.py (3.4)                 │  │  niveaux)    │
        │  - quiz_ppl.py (4.1)                    │  └─────────────┘
        │  - logbook.py (4.3)
        │  - data_analysis.py (4.2)
        │  - export_pdf.py (3.7)
        │  - macros.py (4.6)
        │  - revision_planner.py (4.4)
        │  - google_auth.py / gcalendar.py /
        │    gdrive.py (3.5, 2.2)
        │  - focus.py (3.6)
        └─────────────────────┘
                  │
        ┌─────────▼─────────┐
        │  memory_engine.py    │
        │ - mémoire permanente  │
        │ - daily_brief tracking │
        │ - préférences          │
        └────────────────────────┘
                  │
        ┌─────────▼─────────┐
        │     Ollama           │
        │ - llama3.2:1b (intent)│
        │ - llama3.1:8b (fast)   │
        │ - qwen3:14b (heavy)     │
        │ - minicpm-v (vision)     │
        └─────────────────────────┘

        ┌─────────────────────────┐
        │  aria_mobile_server.py    │
        │  (Flask+gevent)            │
        │  → aria-mobile/ (Expo)      │
        │     (2.4, en pause)          │
        └─────────────────────────────┘
```

---

## 7.2 Flux de données bout-en-bout (exemple : "Quel temps fait-il à Nantes ?")

```
1. Utilisateur parle → stt.py (ou texte tapé directement)
   │
2. Texte → llm.ask(text)
   │
3. Vérification modes conversationnels actifs (checklist/quiz/logbook) → aucun actif
   │
4. _fast_intent(text) → pas de match regex direct
   │
5. _detect_intent(text) via MODELS['intent'] (llama3.2:1b, ~80ms)
   → {"intent": "meteo", "params": {}, "confidence": 0.85}
   │
6. _route_with_intelligence("meteo", {}, text)
   → intent ∈ API_THEN_LLM
   │
7. _fetch_api_data("meteo", {}, text)
   │
   ├─ cache.get('meteo', text) → MISS (première fois)
   │
   ├─ api_keys.check_status('openweather')
   │   ├─ Si clé configurée et valide → get_current(city) [OpenWeather]
   │   └─ Sinon → get_current_free(city) [wttr.in, gratuit]
   │
   ├─ Résultat formaté en texte brut "Données météo pour Nantes: température 18°C..."
   │
   └─ cache.set('meteo', text, result)  [TTL 600s]
   │
8. _build_format_prompt("meteo", api_data, text)
   → "Formate ces données météo en une phrase naturelle en français..."
   │
9. _llm_format(prompt) via MODELS['fast'] (llama3.1:8b, température 0.3)
   → "Il fait actuellement 18°C à Nantes, avec un ciel partiellement nuageux..."
   │
10. _speak_response(result) → tts.speak() (si TTS activé et pas en mode focus silencieux)
    │
11. ui.append_assistant_text(result) → affichage dans le chat (Liquid Glass bubble)
    │
12. memory_engine : ajout à la conversation, sauvegarde auto (60s + par message)
```

---

## 7.3 Checklist de cohérence avant chaque session Cursor

À vérifier systématiquement avant de lancer une nouvelle session de modifications, pour
éviter les régressions sur les points déjà corrigés :

### Avant de toucher à `actions/alias_store.py` ou `scripts/double_sites.py`
- [ ] Vérifier l'espace disque actuel (`Get-PSDrive C`)
- [ ] Confirmer que `ensure_db()` reste passive (pas de `apply_prefix`/`rebuild_db`/
  `double_sites` appelés automatiquement)
- [ ] Si doublement nécessaire, vérifier que `double_sites.py` respecte toujours
  `MAX_DB_GB = 20`

### Avant de toucher à `llm.py` (routage)
- [ ] Vérifier que `MODELS` ne contient PAS `'code'` (remplacé par Nexus, 6.3)
- [ ] Vérifier que les nouveaux intents sont bien classés dans une des catégories :
  `PURE_ACTIONS`, `API_ONLY`, `API_THEN_LLM`, `HEAVY_REQUIRED`, ou laissés en
  `question_libre`
- [ ] Si un mode conversationnel spécial est ajouté (checklist/quiz/logbook/macro), il
  doit être intercepté EN PRIORITÉ dans `ask()`, avant `_fast_intent()`

### Avant de toucher à `stt.py`
- [ ] Vérifier que `_open_mic_stream()` (multi-sample-rate + resampling) n'est pas
  cassé par la modification
- [ ] Si ajout d'un mode (temps réel 3.2, continu 6.1, wake word 3.1), vérifier la
  cohabitation avec le mode actuel (toggle clair, pas de conflit de threads sur le
  même device micro)

### Avant de toucher à `tts.py`
- [ ] Vérifier que `_ensure_mixer()` (init paresseuse) reste en place — ne PAS
  réintroduire un `pygame.mixer.init()` au niveau module (régression B01)

### Avant de toucher à `ui/index.html`
- [ ] Vérifier que le PIN obligatoire au démarrage (`checkPin()`, sans sessionStorage)
  n'est pas contourné par une nouvelle modification
- [ ] Si modification du style, vérifier la compatibilité avec le slider Liquid Glass
  (v13) — les nouveaux éléments doivent utiliser `var(--glass-blur)`/`var(--glass-alpha)`
  s'ils sont des containers, et garder un plancher d'opacité pour le texte

### Avant de toucher à `main.py`
- [ ] Vérifier que le warmup ne charge QUE `MODELS['fast']` et `MODELS['intent']` au
  démarrage (pas `MODELS['heavy']`, partie 2.1)
- [ ] Vérifier que `webview.start()` reste entouré d'un try/except avec logging complet
  (régression A05)

### Avant toute session impliquant des clés API
- [ ] Vérifier que `api_keys.py` reste le point d'entrée unique — pas de nouvelle
  lecture directe de `config.yaml` pour des clés API ailleurs dans le code
- [ ] S'assurer qu'un fallback gratuit existe et fonctionne même sans clé configurée

### Général
- [ ] `PYTHONUTF8=1` toujours actif au lancement (A04) — vérifier que le script de
  lancement le définit
- [ ] Chaque nouveau fichier de données sensibles (`google_token.json`,
  `google_credentials.json`, etc.) ajouté au `.gitignore` immédiatement
- [ ] Un seul prompt par feature, qui liste explicitement "Only modify X, Y, Z" pour
  limiter le rayon d'impact de chaque session Cursor
