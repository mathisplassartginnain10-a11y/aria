# ARIA — Spec v18 : Fix complet Ollama + UI redesign + Paramètres simplifiés

## Problèmes à régler

1. ARIA n'envoie aucune requête aux modèles Ollama (ollama.exe ne se lance pas)
2. Le choix des modèles bug et ne s'affiche pas correctement
3. L'arrière-plan personnalisable ne fonctionne pas
4. Interface trop cloisonnée, peu esthétique
5. Paramètres trop complexes et inaccessibles
6. Vitesse des modèles à optimiser (1B pour les actions simples)

---

## PARTIE 1 — Fix Ollama : aucune requête envoyée

### Diagnostic

Le problème vient de plusieurs points potentiels dans llm.py :
- `ollama_manager.py` ne lance pas ollama.exe correctement
- Les fonctions `ask()` / `_conversation()` n'appellent pas Ollama
- Le modèle sélectionné n'existe pas localement → Ollama refuse silencieusement

### Fix ollama_manager.py

```python
"""
ollama_manager.py — Gestion du processus Ollama et warmup des modèles.
"""
import subprocess
import threading
import logging
import time
import requests

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"


def is_running() -> bool:
    """Vérifie si Ollama répond."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def start_ollama() -> bool:
    """Lance ollama.exe s'il ne tourne pas. Retourne True si OK."""
    if is_running():
        logger.info("Ollama already running")
        return True

    logger.info("Lancement de ollama.exe...")
    try:
        subprocess.Popen(
            ['ollama', 'serve'],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        try:
            subprocess.Popen(
                [r'C:\Users\mathi\AppData\Local\Programs\Ollama\ollama.exe', 'serve'],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.error("Impossible de lancer ollama.exe: %s", e)
            return False

    # Attendre qu'Ollama soit prêt (max 15s)
    for i in range(30):
        time.sleep(0.5)
        if is_running():
            logger.info("Ollama démarré (%.1fs)", (i + 1) * 0.5)
            return True

    logger.error("Ollama n'a pas démarré dans les 15s")
    return False


def list_local_models() -> list[str]:
    """Retourne la liste des modèles installés localement."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        data = r.json()
        return [m['name'] for m in data.get('models', [])]
    except Exception as e:
        logger.error("Erreur liste modèles: %s", e)
        return []


def model_exists(name: str) -> bool:
    """Vérifie qu'un modèle est disponible localement."""
    models = list_local_models()
    # Vérification exacte ET partielle (ex: 'qwen3:14b' matche 'qwen3:14b')
    return any(name in m or m in name for m in models)


def warmup_model(model_name: str) -> None:
    """Charge un modèle en VRAM via une requête vide."""
    if not model_exists(model_name):
        logger.warning("Modèle '%s' absent — warmup ignoré", model_name)
        return
    try:
        logger.info("Chargement modèle %s en VRAM...", model_name)
        requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": model_name, "prompt": "", "keep_alive": "10m"},
            timeout=60
        )
        logger.info("Modèle %s chargé en VRAM", model_name)
    except Exception as e:
        logger.error("Warmup %s échoué: %s", model_name, e)


def stop_ollama() -> None:
    """Tue le processus ollama.exe."""
    import psutil
    for proc in psutil.process_iter(['name', 'pid']):
        try:
            if proc.info['name'].lower() in ('ollama.exe', 'ollama'):
                proc.terminate()
                logger.info("ollama.exe tué (PID %d)", proc.info['pid'])
        except Exception:
            pass
```

### Fix llm.py — s'assurer que les requêtes sont bien envoyées

```python
"""
llm.py — Routage et appels aux modèles Ollama.
"""
import logging
import requests as req
import json

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"

# Modèles disponibles
MODELS = {
    'intent': 'llama3.2:1b',              # Classification ultra-rapide
    'fast':   'llama3.1:8b-instruct-q8_0', # Réponses rapides
    'heavy':  'qwen3:14b',                  # Analyses profondes
    'vision': 'minicpm-v',                  # Images
}

# Mots-clés qui forcent le modèle heavy
HEAVY_KEYWORDS = [
    'calcule', 'démontre', 'résous', 'intégrale', 'dérivée',
    'équation', 'probabilité', 'explique en détail', 'analyse',
    'rédige', 'metar', 'taf', 'plan de vol',
]


def _ollama_available() -> bool:
    """Vérifie qu'Ollama répond."""
    try:
        r = req.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _ensure_ollama():
    """Lance Ollama si nécessaire."""
    if not _ollama_available():
        logger.warning("Ollama non disponible — tentative de démarrage")
        import ollama_manager
        if not ollama_manager.start_ollama():
            raise RuntimeError("Impossible de démarrer Ollama")


def _select_model(text: str, intent: str = '', conv_mode: str = 'ecrit') -> str:
    """Choisit le modèle selon le contexte."""
    # Mode vocal → toujours fast (priorité vitesse)
    if conv_mode == 'vocal':
        return MODELS['fast']

    # Mots-clés heavy
    text_lower = text.lower()
    if any(kw in text_lower for kw in HEAVY_KEYWORDS):
        return MODELS['heavy']

    return MODELS['fast']


def generate(
    prompt: str,
    model: str = None,
    system: str = None,
    stream: bool = True,
    max_tokens: int = 400,
    temperature: float = 0.7,
    on_token=None,
) -> str:
    """
    Appel principal à Ollama.
    Si stream=True et on_token fourni, appelle on_token(chunk) pour chaque token.
    Retourne le texte complet.
    """
    _ensure_ollama()

    if model is None:
        model = MODELS['fast']

    # Vérifier que le modèle existe
    import ollama_manager
    if not ollama_manager.model_exists(model):
        logger.warning("Modèle '%s' absent — fallback sur fast", model)
        model = MODELS['fast']
        if not ollama_manager.model_exists(model):
            return "Erreur : aucun modèle Ollama disponible. Vérifie ton installation."

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        }
    }
    if system:
        payload["system"] = system

    logger.info("Ollama request: model=%s, stream=%s, tokens=%d", model, stream, max_tokens)
    logger.debug("Prompt: %s", prompt[:200])

    try:
        if stream and on_token:
            full_response = []
            with req.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json=payload,
                stream=True,
                timeout=120,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        token = data.get("response", "")
                        if token:
                            full_response.append(token)
                            on_token(token)
                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue
            result = "".join(full_response)
        else:
            resp = req.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={**payload, "stream": False},
                timeout=120,
            )
            resp.raise_for_status()
            result = resp.json().get("response", "").strip()

        logger.info("Ollama response: %d chars", len(result))
        logger.debug("Response: %s", result[:200])
        return result

    except req.exceptions.ConnectionError:
        logger.error("Connexion Ollama refusée — ollama.exe tourne-t-il ?")
        return "Erreur : impossible de contacter Ollama. Vérifie qu'il tourne."
    except req.exceptions.Timeout:
        logger.error("Timeout Ollama (model=%s)", model)
        return "Erreur : Ollama a mis trop de temps à répondre."
    except Exception as e:
        logger.error("Erreur Ollama: %s", e, exc_info=True)
        return f"Erreur : {e}"


def detect_intent(text: str) -> dict:
    """
    Classification rapide via llama3.2:1b.
    Retourne {'intent': str, 'params': dict, 'confidence': float}
    """
    _ensure_ollama()

    KNOWN_INTENTS = [
        'lancer_app', 'fermer_app', 'volume', 'meteo', 'heure_date',
        'minuteur', 'search_web', 'search_news', 'aviation_metar',
        'aviation_taf', 'browser_open_site', 'browser_youtube_search',
        'preset', 'question_libre',
    ]

    model = MODELS['intent']
    import ollama_manager
    if not ollama_manager.model_exists(model):
        model = MODELS['fast']

    prompt = f"""Classifie cette commande en UN mot parmi:
{"|".join(KNOWN_INTENTS)}
Commande: "{text}"
Réponds uniquement avec la catégorie, rien d'autre:"""

    try:
        raw = generate(prompt, model=model, stream=False, max_tokens=10, temperature=0.1)
        raw = raw.strip().lower()
        for intent in KNOWN_INTENTS:
            if intent in raw:
                logger.info("Intent détecté: %s (modèle=%s)", intent, model)
                return {"intent": intent, "params": {}, "confidence": 0.85}
    except Exception as e:
        logger.error("Erreur intent detection: %s", e)

    return {"intent": "question_libre", "params": {}, "confidence": 0.5}


def ask(text: str, conv_mode: str = 'ecrit', on_token=None) -> str:
    """
    Point d'entrée principal.
    Détecte l'intent, exécute l'action ou génère une réponse.
    """
    import memory_engine as _me

    logger.warning("═══ STT→LLM: '%s' ═══", text)

    # 1. Fast intent (regex, 0ms)
    from llm_intents import fast_intent
    fast = fast_intent(text)
    if fast and fast[0] != 'question_libre':
        intent, params = fast
        logger.info("Fast intent: %s", intent)
        result = _execute_action(intent, params, text)
        if result:
            logger.warning("═══ Action→UI: '%s' ═══", str(result)[:100])
            return result

    # 2. Intent via LLM (llama3.2:1b)
    detected = detect_intent(text)
    intent = detected['intent']
    params = detected.get('params', {})

    if intent != 'question_libre':
        result = _execute_action(intent, params, text)
        if result:
            logger.warning("═══ LLM Action→UI: '%s' ═══", str(result)[:100])
            return result

    # 3. Conversation libre
    model = _select_model(text, intent, conv_mode)
    history = _me.get_current_conversation_messages()
    system = _me.build_personalized_system_prompt()

    if conv_mode == 'vocal':
        system += "\nMode vocal: réponds en 1-3 phrases max, pas de markdown ni de listes."

    # Construire le prompt avec historique
    history_text = ""
    for msg in history[-10:]:  # 10 derniers messages
        role = "Utilisateur" if msg['role'] == 'user' else "ARIA"
        history_text += f"{role}: {msg['content']}\n"

    full_prompt = f"{history_text}Utilisateur: {text}\nARIA:"

    max_tokens = 150 if conv_mode == 'vocal' else 500

    result = generate(
        full_prompt,
        model=model,
        system=system,
        stream=True,
        max_tokens=max_tokens,
        on_token=on_token,
    )

    logger.warning("═══ LLM→UI: '%s' ═══", result[:100])
    return result
```

### Fix main.py — démarrer Ollama au lancement

```python
# Dans main.py, au démarrage, AVANT le warmup :
import ollama_manager

logger.info("Vérification Ollama...")
if not ollama_manager.start_ollama():
    logger.error("Ollama non disponible — certaines fonctions seront limitées")
else:
    # Lister les modèles disponibles
    models = ollama_manager.list_local_models()
    logger.info("Modèles disponibles: %s", models)

    # Warmup uniquement les modèles qui existent
    import threading
    from llm import MODELS
    for role, model in [('intent', MODELS['intent']), ('fast', MODELS['fast'])]:
        if ollama_manager.model_exists(model):
            threading.Thread(
                target=ollama_manager.warmup_model,
                args=(model,),
                daemon=True
            ).start()
        else:
            logger.warning("Modèle '%s' (%s) absent — pas de warmup", model, role)
```

---

## PARTIE 2 — Fix sélecteur de modèles dans l'UI

### Problème
Le dropdown de sélection des modèles dans les paramètres ne s'affiche pas car il essaie
de lister des modèles depuis une source qui ne répond pas.

### Fix ui.py — exposer la liste des modèles disponibles

```python
def get_available_models(self) -> str:
    """Retourne les modèles Ollama disponibles + les modèles configurés."""
    import json
    import ollama_manager
    from llm import MODELS

    local = ollama_manager.list_local_models()

    return json.dumps({
        "local_models": local,          # Ex: ["llama3.2:1b", "qwen3:14b", ...]
        "configured": MODELS,           # {'intent': '...', 'fast': '...', ...}
        "ollama_running": ollama_manager.is_running(),
    })

def set_model(self, role: str, model_name: str) -> str:
    """Change le modèle pour un rôle donné (intent/fast/heavy/vision)."""
    import json, yaml, app_paths
    from llm import MODELS

    if role not in MODELS:
        return json.dumps({"success": False, "error": f"Rôle inconnu: {role}"})

    try:
        cfg_path = app_paths.config_path()
        with cfg_path.open('r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}

        if 'models' not in cfg:
            cfg['models'] = {}
        cfg['models'][role] = model_name

        with cfg_path.open('w', encoding='utf-8') as f:
            yaml.safe_dump(cfg, f, allow_unicode=True)

        # Mettre à jour en live
        MODELS[role] = model_name
        logger.info("Modèle %s → %s", role, model_name)
        return json.dumps({"success": True})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})
```

### Fix ui/index.html — sélecteur de modèles simplifié

```javascript
async loadModelSettings() {
  const raw = await this.api('get_available_models');
  const data = JSON.parse(raw || '{}');

  const container = document.getElementById('model-settings');
  if (!container) return;

  if (!data.ollama_running) {
    container.innerHTML = `
      <div style="color:var(--error);font-size:13px;padding:12px;background:rgba(239,68,68,0.1);border-radius:10px">
        ⚠️ Ollama non disponible — les modèles ne peuvent pas être chargés.
        <br><br>Lance Ollama puis redémarre ARIA.
      </div>`;
    return;
  }

  const roles = [
    { key: 'intent', label: 'Classification (intent)', desc: 'Ultra-rapide, actions simples' },
    { key: 'fast',   label: 'Réponses rapides',        desc: 'Conversation quotidienne' },
    { key: 'heavy',  label: 'Analyse approfondie',     desc: 'Maths, aviation, raisonnement' },
    { key: 'vision', label: 'Vision (images)',          desc: 'Analyse de photos/documents' },
  ];

  const models = data.local_models || [];
  const configured = data.configured || {};

  if (models.length === 0) {
    container.innerHTML = `
      <div style="color:var(--text3);font-size:13px">
        Aucun modèle installé. Lance dans un terminal :<br>
        <code style="background:var(--surface);padding:4px 8px;border-radius:6px;font-size:11px">
          ollama pull llama3.2:1b
        </code>
      </div>`;
    return;
  }

  container.innerHTML = roles.map(r => `
    <div style="margin-bottom:14px">
      <div style="font-size:12px;color:var(--text2);margin-bottom:4px">${r.label}</div>
      <div style="font-size:10px;color:var(--text3);margin-bottom:6px">${r.desc}</div>
      <select
        id="model-select-${r.key}"
        onchange="aria.setModel('${r.key}', this.value)"
        style="width:100%;background:var(--surface);border:1px solid var(--border);
               border-radius:8px;padding:8px 10px;color:var(--text);
               font-family:inherit;font-size:12px;cursor:pointer"
      >
        ${models.map(m => `
          <option value="${m}" ${m === configured[r.key] ? 'selected' : ''}>
            ${m}
          </option>
        `).join('')}
      </select>
    </div>
  `).join('');
},

async setModel(role, modelName) {
  const raw = await this.api('set_model', role, modelName);
  const result = JSON.parse(raw || '{}');
  if (result.success) {
    this.showToast(`Modèle ${role} → ${modelName}`, 'success');
  } else {
    this.showToast(`Erreur: ${result.error}`, 'error');
  }
},
```

---

## PARTIE 3 — Fix arrière-plan personnalisable

### Problème
L'erreur "Not allowed to load local resource: file:///" empêche le chargement des images.
Le serveur statique (port 8765) échoue à démarrer (WinError 10013 = port déjà utilisé).

### Fix ui.py — changer le port du serveur statique et ajouter un retry

```python
_STATIC_PORT = None  # Sera assigné dynamiquement

def _find_free_port(start: int = 8765) -> int:
    """Trouve un port libre en partant de start."""
    import socket
    for port in range(start, start + 20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    raise RuntimeError("Aucun port libre disponible")

def _start_static_server():
    """Démarre le serveur HTTP statique sur un port libre."""
    global _STATIC_PORT, _static_server_started
    if _static_server_started:
        return

    import http.server, socketserver, threading
    from app_paths import data_dir

    try:
        _STATIC_PORT = _find_free_port(8765)
    except Exception as e:
        logger.error("Impossible de trouver un port libre: %s", e)
        return

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(data_dir()), **kwargs)
        def log_message(self, *args):
            pass

    def _run():
        try:
            with socketserver.TCPServer(('127.0.0.1', _STATIC_PORT), Handler) as s:
                s.allow_reuse_address = True
                logger.info("Serveur statique: http://127.0.0.1:%d", _STATIC_PORT)
                s.serve_forever()
        except Exception as e:
            logger.error("Erreur serveur statique: %s", e)

    threading.Thread(target=_run, daemon=True).start()
    _static_server_started = True


def save_wallpaper(self, base64_data: str, filename: str) -> str:
    """Sauvegarde une image wallpaper et retourne une URL http://."""
    import base64, time, json
    from pathlib import Path
    from app_paths import data_dir

    try:
        wp_dir = data_dir() / "wallpapers"
        wp_dir.mkdir(parents=True, exist_ok=True)

        if ',' in base64_data:
            base64_data = base64_data.split(',', 1)[1]

        ext = Path(filename).suffix.lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
            ext = '.jpg'

        safe_name = f"wallpaper_{int(time.time())}{ext}"
        out_path = wp_dir / safe_name
        out_path.write_bytes(base64.b64decode(base64_data))

        port = _STATIC_PORT or 8765
        url = f"http://127.0.0.1:{port}/wallpapers/{safe_name}"
        logger.info("Wallpaper sauvegardé: %s → %s", safe_name, url)
        return json.dumps({"success": True, "url": url, "filename": safe_name, "port": port})

    except Exception as e:
        logger.error("Erreur save_wallpaper: %s", e)
        return json.dumps({"success": False, "error": str(e)})


def get_wallpapers(self) -> str:
    """Liste les wallpapers avec URLs http://."""
    import json
    from app_paths import data_dir

    try:
        wp_dir = data_dir() / "wallpapers"
        port = _STATIC_PORT or 8765
        files = []
        if wp_dir.exists():
            for f in sorted(wp_dir.iterdir()):
                if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
                    files.append({
                        "filename": f.name,
                        "url": f"http://127.0.0.1:{port}/wallpapers/{f.name}"
                    })
        return json.dumps(files)
    except Exception as e:
        return json.dumps([])


def delete_wallpaper(self, filename: str) -> str:
    """Supprime un wallpaper."""
    import json
    from pathlib import Path
    from app_paths import data_dir

    try:
        target = data_dir() / "wallpapers" / Path(filename).name
        if target.exists():
            target.unlink()
            return json.dumps({"success": True})
        return json.dumps({"success": False, "error": "Fichier non trouvé"})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def get_static_port(self) -> int:
    """Retourne le port du serveur statique (pour que le JS reconstruise les URLs)."""
    return _STATIC_PORT or 8765
```

### Fix ui/index.html — reconstruire les URLs avec le bon port au chargement

```javascript
// Dans init() :
async init() {
  // Récupérer le port du serveur statique
  this._staticPort = await this.api('get_static_port') || 8765;

  // ... reste de init() inchangé ...

  // Restaurer le wallpaper avec le bon port
  await this.restoreWallpaper();
  await this.loadWallpapers();
},

restoreWallpaper() {
  const s = this.loadSettings();
  if (!s.wallpaper_type) return;

  if (s.wallpaper_type === 'custom' && s.wallpaper_filename) {
    const url = `http://127.0.0.1:${this._staticPort}/wallpapers/${s.wallpaper_filename}`;
    this.setWallpaper('custom', url);
  } else if (s.wallpaper_type && s.wallpaper_type !== 'custom') {
    this.setWallpaper(s.wallpaper_type);
  }
},

async loadWallpapers() {
  const raw = await this.api('get_wallpapers');
  const wallpapers = JSON.parse(raw || '[]');
  this.renderWallpaperGrid(wallpapers);
},

async uploadWallpaper(file) {
  if (!file || !file.type.startsWith('image/')) {
    this.showToast('Fichier non supporté', 'error');
    return;
  }
  this.showToast('Import en cours...', 'info');
  try {
    const b64 = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = e => resolve(e.target.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    const raw = await this.api('save_wallpaper', b64, file.name);
    const result = JSON.parse(raw || '{}');
    if (result.success) {
      this.showToast('Image importée ✓', 'success');
      this.setWallpaper('custom', result.url);
      await this.loadWallpapers();
    } else {
      this.showToast('Erreur: ' + (result.error || 'inconnue'), 'error');
    }
  } catch(e) {
    this.showToast('Erreur import', 'error');
  }
},
```

---

## PARTIE 4 — Interface plus jolie, moins de séparations

### Principes de redesign

- Supprimer les bordures `border-bottom` / `border-right` systématiques → remplacer par
  de l'espace et des ombres douces
- Sidebar : fond semi-transparent (Liquid Glass), pas de bordure dure
- Messages : bulles sans contour rigide, juste un fond translucide
- Paramètres : regroupés en accordéon pliant, pas une liste infinie de lignes

### CSS à modifier dans ui/index.html

```css
/* Sidebar — glass sans bordure dure */
#sidebar {
  background: rgba(18, 18, 26, 0.6);
  backdrop-filter: blur(24px) saturate(180%);
  border-right: none;  /* Supprime la bordure */
  box-shadow: 4px 0 20px rgba(0,0,0,0.15);  /* Ombre douce à la place */
}

/* Header — transparent, juste une ombre */
#header {
  background: transparent;
  border-bottom: none;
  box-shadow: 0 1px 20px rgba(0,0,0,0.08);
}

/* Zone messages — plus d'espace, moins de boîtes */
#messages {
  padding: 24px 20px;
  gap: 16px;
}

/* Bulles ARIA — sans bordure visible */
.bubble-aria-wrap .bubble-content {
  background: rgba(255,255,255,0.04);
  border: none;
  border-radius: 4px 18px 18px 18px;
  padding: 14px 18px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
}

/* Bulles utilisateur — couleur accent douce */
.bubble-user {
  background: rgba(108,142,255,0.12);
  border: none;
  border-radius: 18px 18px 4px 18px;
  box-shadow: 0 2px 12px rgba(108,142,255,0.1);
}

/* Input zone — pilule unifiée */
#input-zone {
  margin: 8px 16px 16px;
  background: rgba(255,255,255,0.06);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 24px;
  padding: 6px 6px 6px 16px;
  transition: border-color 0.2s, box-shadow 0.2s;
}
#input-zone:focus-within {
  border-color: rgba(108,142,255,0.35);
  box-shadow: 0 0 0 3px rgba(108,142,255,0.08);
}

/* Supprimer les séparateurs dans les paramètres */
.setting-row {
  border-bottom: none;
  padding: 6px 0;
}
.settings-section {
  border-bottom: none;
  margin-bottom: 20px;
}
.settings-section + .settings-section {
  padding-top: 0;
}

/* Sections paramètres en accordéon */
.settings-accordion-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: rgba(255,255,255,0.04);
  border-radius: 10px;
  cursor: pointer;
  margin-bottom: 4px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text2);
  transition: background 0.15s;
}
.settings-accordion-header:hover {
  background: rgba(255,255,255,0.07);
}
.settings-accordion-body {
  padding: 8px 14px 12px;
  overflow: hidden;
  transition: max-height 0.25s ease;
}
.settings-accordion-body.collapsed {
  max-height: 0;
  padding: 0 14px;
}
```

---

## PARTIE 5 — Paramètres simplifiés et accessibles

### Nouveau layout des paramètres — 5 sections en accordéon

```html
<!-- Dans ui/index.html, remplacer le contenu de #settings-panel par : -->

<div id="settings-panel">
  <div style="padding:16px 16px 8px;font-size:15px;font-weight:600;color:var(--text)">
    Paramètres
  </div>

  <!-- 1. Apparence -->
  <div class="settings-accordion">
    <div class="settings-accordion-header" onclick="aria.toggleAccordion('apparence')">
      🎨 Apparence <span id="chevron-apparence">▾</span>
    </div>
    <div class="settings-accordion-body" id="acc-apparence">
      <!-- Thème -->
      <div class="setting-row">
        <label>Thème</label>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button class="theme-btn" onclick="aria.setTheme('slate')">Slate</button>
          <button class="theme-btn" onclick="aria.setTheme('warm')">Warm</button>
          <button class="theme-btn" onclick="aria.setTheme('forest')">Forest</button>
          <button class="theme-btn" onclick="aria.setTheme('rose')">Rose</button>
        </div>
      </div>
      <!-- Glass intensity -->
      <div class="setting-row">
        <label>Transparence</label>
        <input type="range" id="set-glass" min="0" max="100" value="60"
          oninput="aria.setGlassIntensity(this.value)">
      </div>
      <!-- Fond d'écran -->
      <div style="font-size:11px;color:var(--text3);margin:8px 0 6px">Fond d'écran</div>
      <div class="wallpaper-grid" style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:10px">
        <div class="wp-thumb wp-aurora" onclick="aria.setWallpaper('aurora')"></div>
        <div class="wp-thumb wp-sunset" onclick="aria.setWallpaper('sunset')"></div>
        <div class="wp-thumb wp-midnight" onclick="aria.setWallpaper('midnight')"></div>
        <div class="wp-thumb wp-forest" onclick="aria.setWallpaper('forest')"></div>
        <div class="wp-thumb wp-mesh-animated" onclick="aria.setWallpaper('mesh-animated')"></div>
        <div class="wp-thumb wp-mono" onclick="aria.setWallpaper('mono')"></div>
      </div>
      <div id="wallpaper-custom-grid" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px"></div>
      <label class="settings-btn" style="cursor:pointer;display:flex;align-items:center;gap:6px;justify-content:center">
        📷 Importer une image
        <input type="file" accept="image/*" style="display:none"
          onchange="aria.uploadWallpaper(this.files[0]);this.value=''">
      </label>
    </div>
  </div>

  <!-- 2. Voix -->
  <div class="settings-accordion">
    <div class="settings-accordion-header" onclick="aria.toggleAccordion('voix')">
      🎙️ Voix <span id="chevron-voix">▸</span>
    </div>
    <div class="settings-accordion-body collapsed" id="acc-voix">
      <div class="setting-row">
        <label>TTS activé</label>
        <input type="checkbox" id="set-tts" onchange="aria.toggleTTS(this.checked)">
      </div>
      <div class="setting-row">
        <label>Vitesse voix</label>
        <input type="range" id="set-tts-rate" min="-50" max="50" value="0"
          oninput="aria.setTTSRate(this.value)">
      </div>
      <div class="setting-row">
        <label>Wake word</label>
        <input type="checkbox" id="set-wake" onchange="aria.toggleWakeWord(this.checked)">
      </div>
    </div>
  </div>

  <!-- 3. Modèles IA -->
  <div class="settings-accordion">
    <div class="settings-accordion-header" onclick="aria.toggleAccordion('modeles')">
      🤖 Modèles IA <span id="chevron-modeles">▸</span>
    </div>
    <div class="settings-accordion-body collapsed" id="acc-modeles">
      <div id="model-settings">
        <div style="color:var(--text3);font-size:12px">Chargement...</div>
      </div>
      <button class="settings-btn" onclick="aria.loadModelSettings()" style="margin-top:8px">
        🔄 Rafraîchir
      </button>
    </div>
  </div>

  <!-- 4. Micro -->
  <div class="settings-accordion">
    <div class="settings-accordion-header" onclick="aria.toggleAccordion('micro')">
      🎤 Micro <span id="chevron-micro">▸</span>
    </div>
    <div class="settings-accordion-body collapsed" id="acc-micro">
      <div class="setting-row">
        <label>Device index</label>
        <input type="number" id="set-device-index" placeholder="auto" min="0" max="200"
          style="width:70px;background:var(--surface);border:1px solid var(--border);
                 border-radius:6px;padding:4px 8px;color:var(--text);font-size:12px"
          onchange="aria.setDeviceIndex(this.value)">
      </div>
      <div class="setting-row">
        <label>Modèle Whisper</label>
        <select id="set-whisper-model" onchange="aria.setWhisperModel(this.value)"
          style="background:var(--surface);border:1px solid var(--border);border-radius:6px;
                 padding:4px 8px;color:var(--text);font-size:12px">
          <option value="tiny">Tiny (rapide)</option>
          <option value="base">Base</option>
          <option value="small" selected>Small (recommandé)</option>
          <option value="medium">Medium (précis)</option>
        </select>
      </div>
    </div>
  </div>

  <!-- 5. Système -->
  <div class="settings-accordion">
    <div class="settings-accordion-header" onclick="aria.toggleAccordion('systeme')">
      ⚙️ Système <span id="chevron-systeme">▸</span>
    </div>
    <div class="settings-accordion-body collapsed" id="acc-systeme">
      <div class="setting-row">
        <label>Brief quotidien</label>
        <input type="checkbox" id="set-daily-brief" onchange="aria.toggleDailyBrief(this.checked)">
      </div>
      <div class="setting-row">
        <label>Mode focus</label>
        <input type="checkbox" id="set-focus" onchange="aria.toggleFocusMode(this.checked)">
      </div>
      <div class="setting-row">
        <label>Quitter Ollama à la fermeture</label>
        <input type="checkbox" id="set-kill-ollama" checked
          onchange="aria.setSetting('kill_ollama_on_exit', this.checked)">
      </div>
      <div style="margin-top:12px">
        <div style="font-size:11px;color:var(--text3);margin-bottom:6px">Nexus (code local)</div>
        <span id="nexus-status" style="font-size:11px;color:var(--text3)">Non configuré</span>
        <button class="settings-btn" onclick="aria.checkNexusStatus()" style="margin-top:6px">
          Vérifier
        </button>
      </div>
    </div>
  </div>
</div>

<!-- JS pour l'accordéon -->
<script>
toggleAccordion(id) {
  const body = document.getElementById(`acc-${id}`);
  const chevron = document.getElementById(`chevron-${id}`);
  if (!body) return;
  const isCollapsed = body.classList.contains('collapsed');
  body.classList.toggle('collapsed', !isCollapsed);
  if (chevron) chevron.textContent = isCollapsed ? '▾' : '▸';

  // Charger les modèles quand on ouvre la section IA
  if (id === 'modeles' && isCollapsed) {
    this.loadModelSettings();
  }
},
</script>
```

---

## PARTIE 6 — Rapidité : modèle 1B pour les actions simples

### Dans llm.py — routing optimisé

```python
# Actions qui utilisent TOUJOURS llama3.2:1b (0 token de contexte nécessaire)
ACTIONS_1B = {
    'lancer_app', 'fermer_app', 'volume', 'heure_date',
    'minuteur', 'preset', 'browser_open_site', 'browser_youtube_search',
}

def _select_model(text: str, intent: str = '', conv_mode: str = 'ecrit') -> str:
    """
    Sélection du modèle :
    - Actions simples → llama3.2:1b (le plus rapide)
    - Mode vocal → llama3.1:8b max (rapidité)
    - Mots-clés complexes → qwen3:14b
    - Sinon → llama3.1:8b
    """
    # Actions simples : 1B suffit largement
    if intent in ACTIONS_1B:
        return MODELS['intent']  # llama3.2:1b

    # Mode vocal : jamais le gros modèle
    if conv_mode == 'vocal':
        return MODELS['fast']  # llama3.1:8b

    # Contenu complexe
    if any(kw in text.lower() for kw in HEAVY_KEYWORDS):
        return MODELS['heavy']  # qwen3:14b

    return MODELS['fast']  # llama3.1:8b par défaut
```

---

## Prompt Cursor (à coller tel quel)

> Appliquer TOUTES les corrections suivantes. Lire chaque section attentivement avant de modifier.
>
> **FICHIER 1 — ollama_manager.py** : réécrire complètement avec `is_running()`, `start_ollama()` (lance `ollama serve` si absent, attend jusqu'à 15s), `list_local_models()`, `model_exists(name)`, `warmup_model(model_name)` (ignore si modèle absent), `stop_ollama()` (via psutil). Ajouter les chemins de fallback courants pour `ollama.exe` en cas de `FileNotFoundError`.
>
> **FICHIER 2 — llm.py** : réécrire les fonctions d'appel Ollama. Ajouter `_ensure_ollama()` qui appelle `ollama_manager.start_ollama()` si nécessaire. Réécrire `generate(prompt, model, system, stream, max_tokens, temperature, on_token)` qui envoie vraiment une requête POST à `http://localhost:11434/api/generate`, gère le streaming token par token via `on_token(chunk)`, et log les requêtes/réponses. Ajouter `detect_intent(text)` qui utilise `MODELS['intent']` (llama3.2:1b). Ajouter `_select_model(text, intent, conv_mode)` avec la logique : actions simples → 1B, vocal → fast, heavy_keywords → heavy, sinon → fast.
>
> **FICHIER 3 — main.py** : au démarrage, appeler `ollama_manager.start_ollama()`, logger les modèles disponibles via `ollama_manager.list_local_models()`, et ne warmup que les modèles qui existent localement (`ollama_manager.model_exists()`).
>
> **FICHIER 4 — ui.py** : ajouter `get_available_models()` (retourne JSON avec local_models, configured, ollama_running), `set_model(role, model_name)` (modifie config.yaml et MODELS en live), `get_static_port()` (retourne le port actuel du serveur statique). Corriger `_start_static_server()` pour trouver un port libre dynamiquement (`_find_free_port(8765)`) au lieu de s'obstiner sur 8765. Corriger `save_wallpaper()`, `get_wallpapers()`, `delete_wallpaper()` pour utiliser le port dynamique.
>
> **FICHIER 5 — ui/index.html** :
> - Ajouter `this._staticPort = await this.api('get_static_port') || 8765` dans `init()`
> - Corriger `restoreWallpaper()` pour utiliser `this._staticPort`
> - Corriger `loadWallpapers()` pour utiliser `this._staticPort`
> - Remplacer le contenu de `#settings-panel` par le layout accordéon à 5 sections (Apparence/Voix/Modèles IA/Micro/Système) comme spécifié
> - Ajouter `toggleAccordion(id)` qui ouvre/ferme les sections et charge les modèles à l'ouverture de "Modèles IA"
> - Ajouter `loadModelSettings()` qui appelle `get_available_models()` et génère les dropdowns de sélection de modèles
> - Ajouter `setModel(role, modelName)` qui appelle `set_model()`
> - Appliquer le CSS de redesign : supprimer les bordures dures (border-right, border-bottom systématiques), remplacer par box-shadow douces, bulles sans contour rigide, input zone en pilule
> - Ajouter les CSS `.settings-accordion`, `.settings-accordion-header`, `.settings-accordion-body`, `.settings-accordion-body.collapsed`
>
> Modifie : ollama_manager.py, llm.py, main.py, ui.py, ui/index.html.
