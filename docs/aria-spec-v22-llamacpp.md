# ARIA — Spec v22 : Migration Ollama → llama.cpp

## Pourquoi llama.cpp ?

| Critère | Ollama (actuel) | llama.cpp |
|---|---|---|
| Dépendance | `llama-server.exe` (corrompu) | Binaire autonome `llama-server.exe` propre |
| Installation | Lourd (installateur système) | Simple (un seul exécutable) |
| Démarrage | ~3-5s | ~1-2s |
| VRAM | Même gestion | Même gestion (même moteur sous le capot) |
| API | Compatible OpenAI (`/api/generate`) | Compatible OpenAI (`/v1/chat/completions`) |
| Modèles | Format GGUF (téléchargés par Ollama) | Format GGUF (mêmes fichiers) |
| Contrôle | Limité | Total (paramètres contexte, threads, etc.) |

Les modèles déjà téléchargés par Ollama sont en format GGUF et réutilisables
directement par llama.cpp — pas besoin de les retélécharger.

---

## Étape 1 — Télécharger llama.cpp

Télécharger la release Windows pré-compilée avec support CUDA (RTX 5080) :

```
https://github.com/ggerganov/llama.cpp/releases/latest
```

Fichier à télécharger : `llama-b*-bin-win-cuda-cu12.2-x64.zip`
(ou la version CUDA correspondant à ta version de CUDA — vérifier avec `nvcc --version`)

Extraire dans : `C:\llama.cpp\` (ou tout autre dossier permanent)

Fichiers importants dans l'archive :
- `llama-server.exe` — serveur HTTP compatible OpenAI
- `llama-cli.exe` — interface ligne de commande

---

## Étape 2 — Localiser les modèles GGUF

Les modèles téléchargés par Ollama sont dans :
```
C:\Users\mathi\.ollama\models\blobs\
```

Ce sont des fichiers GGUF sans extension. Pour les utiliser avec llama.cpp,
on peut soit les pointer directement, soit créer des liens symboliques.

Pour identifier quel blob correspond à quel modèle :
```powershell
# Lister les manifestes Ollama
ls "$env:USERPROFILE\.ollama\models\manifests\registry.ollama.ai\library\"
```

Chaque dossier est un modèle. Dans chaque dossier se trouve un fichier JSON avec
le hash du blob GGUF correspondant.

Script PowerShell pour trouver les modèles :
```powershell
$manifestsPath = "$env:USERPROFILE\.ollama\models\manifests\registry.ollama.ai\library"
$blobsPath = "$env:USERPROFILE\.ollama\models\blobs"

Get-ChildItem $manifestsPath -Recurse -File | ForEach-Object {
    $manifest = Get-Content $_.FullName | ConvertFrom-Json
    $layers = $manifest.layers | Where-Object { $_.mediaType -eq "application/vnd.ollama.image.model" }
    if ($layers) {
        $hash = $layers[0].digest -replace "sha256:", "sha256-"
        $blobFile = Join-Path $blobsPath $hash
        Write-Host "Modèle: $($_.DirectoryName.Split('\')[-1])/$($_.Name)"
        Write-Host "  Fichier: $blobFile"
        Write-Host "  Taille: $([math]::Round((Get-Item $blobFile).Length / 1GB, 2)) Go"
        Write-Host ""
    }
}
```

---

## Étape 3 — Lancer llama-server manuellement (test)

```powershell
# Test avec llama3.2:1b (remplace <HASH> par le hash trouvé à l'étape 2)
C:\llama.cpp\llama-server.exe `
  --model "$env:USERPROFILE\.ollama\models\blobs\sha256-<HASH>" `
  --host 127.0.0.1 `
  --port 8080 `
  --ctx-size 4096 `
  --n-gpu-layers 99 `
  --threads 8

# Tester que le serveur répond
Invoke-RestMethod http://127.0.0.1:8080/health
```

---

## Étape 4 — actions/llamacpp_manager.py (remplace ollama_manager.py)

```python
"""
llamacpp_manager.py — Gestion des serveurs llama.cpp locaux.

Architecture : un serveur llama-server.exe par modèle actif.
On démarre le(s) serveur(s) nécessaire(s) au démarrage d'ARIA.
Chaque serveur écoute sur un port différent.
"""
import subprocess
import threading
import logging
import time
import os
import json
import yaml
import requests
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

# Chemin vers llama-server.exe
LLAMA_SERVER_EXE = os.environ.get(
    'LLAMA_SERVER_PATH',
    r'C:\llama.cpp\llama-server.exe'
)

# Répertoire des blobs Ollama (modèles GGUF)
OLLAMA_BLOBS_DIR = Path(os.environ.get('USERPROFILE', 'C:/Users/mathi')) / '.ollama/models/blobs'
OLLAMA_MANIFESTS_DIR = Path(os.environ.get('USERPROFILE', 'C:/Users/mathi')) / '.ollama/models/manifests'

# Paramètres par défaut
DEFAULT_PARAMS = {
    'ctx_size': 4096,
    'n_gpu_layers': 99,     # tout sur GPU (RTX 5080 16GB)
    'threads': 8,
    'batch_size': 512,
}

# ── État des serveurs ─────────────────────────────────────────────────────────

# {model_name: {'process': Process, 'port': int, 'model_path': str}}
_servers: dict[str, dict] = {}
_port_counter = 8080  # premier port disponible
_lock = threading.Lock()


# ── Résolution des modèles ────────────────────────────────────────────────────

def _find_model_blob(model_name: str) -> Path | None:
    """
    Trouve le fichier GGUF d'un modèle depuis les blobs Ollama.
    model_name: ex 'llama3.2:1b', 'qwen3:14b', 'llama3.1:8b-instruct-q8_0'
    """
    # Normaliser le nom (enlever le tag si fourni)
    parts = model_name.split(':')
    name = parts[0].replace('.', '/').replace('-', '/')
    tag = parts[1] if len(parts) > 1 else 'latest'

    # Chercher dans les manifestes
    manifests_base = OLLAMA_MANIFESTS_DIR / 'registry.ollama.ai' / 'library'

    # Essayer différentes combinaisons de nom/tag
    candidates = [
        manifests_base / name / tag,
        manifests_base / parts[0] / tag,
        manifests_base / parts[0].split('/')[0] / tag,
    ]

    for manifest_path in candidates:
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                for layer in manifest.get('layers', []):
                    if layer.get('mediaType') == 'application/vnd.ollama.image.model':
                        digest = layer['digest'].replace('sha256:', 'sha256-')
                        blob_path = OLLAMA_BLOBS_DIR / digest
                        if blob_path.exists():
                            logger.info("Modèle '%s' → %s (%.1f Go)",
                                model_name, blob_path.name,
                                blob_path.stat().st_size / 1e9)
                            return blob_path
            except Exception as e:
                logger.debug("Erreur lecture manifeste %s: %s", manifest_path, e)

    logger.warning("Modèle '%s' non trouvé dans les blobs Ollama", model_name)
    return None


def list_available_models() -> list[str]:
    """Liste tous les modèles disponibles (blobs Ollama)."""
    models = []
    manifests_base = OLLAMA_MANIFESTS_DIR / 'registry.ollama.ai' / 'library'

    if not manifests_base.exists():
        return []

    for model_dir in manifests_base.iterdir():
        for tag_file in model_dir.iterdir():
            try:
                model_name = f"{model_dir.name}:{tag_file.name}"
                blob = _find_model_blob(model_name)
                if blob:
                    models.append(model_name)
            except Exception:
                pass

    return sorted(models)


# ── Démarrage des serveurs ────────────────────────────────────────────────────

def _next_port() -> int:
    global _port_counter
    with _lock:
        port = _port_counter
        _port_counter += 1
        return port


def start_model_server(model_name: str, params: dict = None) -> dict | None:
    """
    Démarre un serveur llama-server.exe pour un modèle donné.
    Retourne {port, url} ou None si échec.
    """
    global _servers

    # Déjà démarré ?
    if model_name in _servers:
        info = _servers[model_name]
        if info['process'].poll() is None:  # toujours vivant
            logger.info("Serveur '%s' déjà actif sur port %d", model_name, info['port'])
            return info
        else:
            logger.warning("Serveur '%s' mort — redémarrage", model_name)
            del _servers[model_name]

    # Trouver le fichier modèle
    model_path = _find_model_blob(model_name)
    if not model_path:
        logger.error("Impossible de trouver le modèle '%s'", model_name)
        return None

    # Vérifier que llama-server.exe existe
    if not Path(LLAMA_SERVER_EXE).exists():
        logger.error("llama-server.exe non trouvé: %s", LLAMA_SERVER_EXE)
        logger.error("Télécharger depuis https://github.com/ggerganov/llama.cpp/releases")
        return None

    port = _next_port()
    p = params or {}

    cmd = [
        LLAMA_SERVER_EXE,
        '--model', str(model_path),
        '--host', '127.0.0.1',
        '--port', str(port),
        '--ctx-size', str(p.get('ctx_size', DEFAULT_PARAMS['ctx_size'])),
        '--n-gpu-layers', str(p.get('n_gpu_layers', DEFAULT_PARAMS['n_gpu_layers'])),
        '--threads', str(p.get('threads', DEFAULT_PARAMS['threads'])),
        '--batch-size', str(p.get('batch_size', DEFAULT_PARAMS['batch_size'])),
        '--no-mmap',
        '--log-disable',  # moins de bruit dans les logs
    ]

    logger.info("Démarrage llama-server: modèle=%s, port=%d", model_name, port)
    logger.debug("Commande: %s", ' '.join(cmd))

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        # Attendre que le serveur soit prêt (max 30s)
        url = f"http://127.0.0.1:{port}"
        for i in range(60):  # 30s max
            time.sleep(0.5)
            if process.poll() is not None:
                logger.error("llama-server a planté immédiatement (modèle=%s)", model_name)
                return None
            try:
                r = requests.get(f"{url}/health", timeout=1)
                if r.status_code == 200:
                    logger.info("✅ Serveur '%s' prêt sur port %d", model_name, port)
                    break
            except Exception:
                pass
        else:
            logger.error("Timeout démarrage serveur '%s'", model_name)
            process.kill()
            return None

        info = {
            'process': process,
            'port': port,
            'url': url,
            'model_path': str(model_path),
            'model_name': model_name,
        }
        _servers[model_name] = info
        return info

    except Exception as e:
        logger.error("Erreur démarrage serveur '%s': %s", model_name, e)
        return None


def get_server_url(model_name: str) -> str | None:
    """Retourne l'URL d'un serveur actif, None si pas démarré."""
    info = _servers.get(model_name)
    if info and info['process'].poll() is None:
        return info['url']
    return None


def is_running(model_name: str) -> bool:
    return get_server_url(model_name) is not None


def stop_all_servers() -> None:
    """Arrête tous les serveurs llama.cpp."""
    for model_name, info in list(_servers.items()):
        try:
            info['process'].terminate()
            info['process'].wait(timeout=3)
            logger.info("Serveur '%s' arrêté", model_name)
        except Exception:
            try:
                info['process'].kill()
            except Exception:
                pass
    _servers.clear()


def stop_server(model_name: str) -> None:
    """Arrête un serveur spécifique."""
    info = _servers.pop(model_name, None)
    if info:
        try:
            info['process'].terminate()
        except Exception:
            pass
        logger.info("Serveur '%s' arrêté", model_name)
```

---

## Étape 5 — llm.py : remplacer les appels Ollama par llama.cpp

```python
"""
llm.py — Appels LLM via llama.cpp (remplace Ollama).
L'API de llama-server est compatible OpenAI /v1/chat/completions.
"""
import logging
import requests
import json

logger = logging.getLogger(__name__)

# ── Modèles configurés ────────────────────────────────────────────────────────

MODELS = {
    'intent': 'llama3.2:1b',
    'fast':   'llama3.1:8b-instruct-q8_0',
    'heavy':  'qwen3:14b',
    'vision': 'minicpm-v:latest',
}

# Cache des URLs de serveurs (modèle → URL)
_server_urls: dict[str, str] = {}


def _get_server_url(model_name: str) -> str | None:
    """
    Retourne l'URL du serveur llama.cpp pour un modèle.
    Lance le serveur si nécessaire.
    """
    import llamacpp_manager

    url = llamacpp_manager.get_server_url(model_name)
    if url:
        return url

    # Démarrer le serveur
    logger.info("Démarrage serveur pour '%s'...", model_name)
    info = llamacpp_manager.start_model_server(model_name)
    return info['url'] if info else None


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
    Génère une réponse via llama.cpp.
    Compatible avec l'API OpenAI /v1/chat/completions.
    """
    if model is None:
        model = MODELS['fast']

    # Résolution du modèle (correspondance partielle)
    import llamacpp_manager
    available = llamacpp_manager.list_available_models()
    matched = None
    for m in available:
        if model == m or model.split(':')[0] in m:
            matched = m
            break
    if not matched:
        if available:
            matched = available[0]
            logger.warning("Modèle '%s' non trouvé — fallback sur '%s'", model, matched)
        else:
            return "Erreur : aucun modèle llama.cpp disponible."

    # Obtenir l'URL du serveur
    server_url = _get_server_url(matched)
    if not server_url:
        return f"Erreur : impossible de démarrer le serveur pour '{matched}'."

    # Construire les messages
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": matched,
        "messages": messages,
        "stream": stream,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    logger.info("llama.cpp POST %s/v1/chat/completions → model=%s stream=%s tokens=%d",
                server_url, matched, stream, max_tokens)
    logger.debug("Prompt: %s", prompt[:200])

    try:
        if stream and on_token:
            full_response = []
            with requests.post(
                f"{server_url}/v1/chat/completions",
                json=payload,
                stream=True,
                timeout=120,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    line_str = line.decode('utf-8') if isinstance(line, bytes) else line
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]
                        if data_str == '[DONE]':
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data['choices'][0]['delta']
                            token = delta.get('content', '')
                            if token:
                                full_response.append(token)
                                on_token(token)
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
            result = ''.join(full_response)
        else:
            resp = requests.post(
                f"{server_url}/v1/chat/completions",
                json={**payload, 'stream': False},
                timeout=120,
            )
            resp.raise_for_status()
            result = resp.json()['choices'][0]['message']['content'].strip()

        logger.info("llama.cpp réponse: %d chars", len(result))
        logger.debug("Réponse: %s", result[:200])
        return result

    except requests.exceptions.ConnectionError:
        logger.error("Connexion llama.cpp refusée (port %s) — serveur planté ?", server_url)
        return "Erreur : le serveur llama.cpp ne répond plus."
    except requests.exceptions.Timeout:
        logger.error("Timeout llama.cpp (model=%s)", matched)
        return "Erreur : llama.cpp a mis trop de temps à répondre."
    except requests.exceptions.HTTPError as e:
        try:
            err = e.response.json().get('error', str(e))
        except Exception:
            err = str(e)
        logger.error("Erreur HTTP llama.cpp: %s", err)
        return f"Erreur llama.cpp: {err}"
    except Exception as e:
        logger.error("Erreur llama.cpp: %s", e, exc_info=True)
        return f"Erreur: {e}"


def detect_intent(text: str) -> dict:
    """Classification via llama3.2:1b."""
    KNOWN_INTENTS = [
        'lancer_app', 'fermer_app', 'volume', 'meteo', 'heure_date',
        'minuteur', 'search_web', 'search_news', 'aviation_metar',
        'aviation_taf', 'browser_open_site', 'browser_youtube_search',
        'preset', 'question_libre',
    ]

    model = MODELS['intent']
    prompt = f"""Classifie cette commande en UN mot parmi:
{"|".join(KNOWN_INTENTS)}
Commande: "{text}"
Réponds uniquement avec la catégorie, rien d'autre:"""

    try:
        raw = generate(prompt, model=model, stream=False, max_tokens=10, temperature=0.1)
        raw = raw.strip().lower()
        for intent in KNOWN_INTENTS:
            if intent in raw:
                logger.info("Intent: %s", intent)
                return {"intent": intent, "params": {}, "confidence": 0.85}
    except Exception as e:
        logger.error("Erreur intent detection: %s", e)

    return {"intent": "question_libre", "params": {}, "confidence": 0.5}
```

---

## Étape 6 — main.py : démarrer les serveurs llama.cpp

```python
# Dans main.py, remplacer le bloc Ollama par llama.cpp

import llamacpp_manager
import threading

# Vérifier que llama-server.exe existe
if not Path(llamacpp_manager.LLAMA_SERVER_EXE).exists():
    logger.error("llama-server.exe non trouvé: %s", llamacpp_manager.LLAMA_SERVER_EXE)
    logger.error("Télécharger depuis https://github.com/ggerganov/llama.cpp/releases")
else:
    from llm import MODELS
    available = llamacpp_manager.list_available_models()
    logger.info("Modèles disponibles: %s", available)

    # Démarrer le serveur intent (llama3.2:1b) en priorité
    def _start_servers():
        for role, model in [('intent', MODELS['intent']), ('fast', MODELS['fast'])]:
            matching = next((m for m in available if model.split(':')[0] in m), None)
            if matching:
                llamacpp_manager.start_model_server(matching)
            else:
                logger.warning("Modèle %s (%s) absent — skipped", role, model)

    threading.Thread(target=_start_servers, daemon=True).start()

# À la fermeture :
import atexit
atexit.register(llamacpp_manager.stop_all_servers)
```

---

## Étape 7 — ui.py : adapter get_available_models

```python
def get_available_models(self) -> str:
    import json
    try:
        import llamacpp_manager
        from llm import MODELS
        available = llamacpp_manager.list_available_models()
        running = {
            m: llamacpp_manager.is_running(m)
            for m in available
        }
        return json.dumps({
            'local_models': available,
            'configured': dict(MODELS),
            'ollama_running': True,  # compatibilité UI
            'running_servers': running,
        })
    except Exception as e:
        logger.error("get_available_models error: %s", e)
        return json.dumps({'local_models': [], 'configured': {}, 'ollama_running': False})
```

---

## Étape 8 — config.yaml : nouvelles clés

```yaml
# llama.cpp
llamacpp:
  server_path: "C:\\llama.cpp\\llama-server.exe"
  n_gpu_layers: 99      # tout sur GPU RTX 5080
  ctx_size: 4096
  threads: 8
  base_port: 8080       # premier port utilisé

# Modèles (noms exacts comme dans ollama list)
models:
  intent: "llama3.2:1b"
  fast: "llama3.1:8b-instruct-q8_0"
  heavy: "qwen3:14b"
  vision: "minicpm-v:latest"
```

---

## Étape 9 — Script PowerShell pour trouver et lier les modèles

```powershell
# scripts/find_models.ps1
# Lance ce script pour voir tous les modèles disponibles et leurs chemins GGUF

$manifestsPath = "$env:USERPROFILE\.ollama\models\manifests\registry.ollama.ai\library"
$blobsPath = "$env:USERPROFILE\.ollama\models\blobs"

Write-Host "=== Modèles GGUF disponibles ===" -ForegroundColor Cyan

if (-not (Test-Path $manifestsPath)) {
    Write-Host "Aucun modèle Ollama trouvé dans $manifestsPath" -ForegroundColor Red
    exit
}

Get-ChildItem $manifestsPath -Recurse -File | ForEach-Object {
    try {
        $manifest = Get-Content $_.FullName -Raw | ConvertFrom-Json
        $layers = $manifest.layers | Where-Object { $_.mediaType -eq "application/vnd.ollama.image.model" }
        if ($layers) {
            $hash = $layers[0].digest -replace "sha256:", "sha256-"
            $blobFile = Join-Path $blobsPath $hash
            if (Test-Path $blobFile) {
                $sizGo = [math]::Round((Get-Item $blobFile).Length / 1GB, 2)
                $modelName = "$($_.Directory.Name):$($_.Name)"
                Write-Host "`n$modelName" -ForegroundColor Green
                Write-Host "  Taille : $sizGo Go"
                Write-Host "  Chemin : $blobFile"
            }
        }
    } catch {}
}
Write-Host "`n=== Fin ===" -ForegroundColor Cyan
```

---

## Prompt Cursor

> Migrer ARIA d'Ollama vers llama.cpp comme moteur d'inférence.
>
> **FICHIER 1 — Créer llamacpp_manager.py** avec le contenu complet ci-dessus :
> - `LLAMA_SERVER_EXE` : chemin vers `llama-server.exe` (configurable via env var)
> - `OLLAMA_BLOBS_DIR` / `OLLAMA_MANIFESTS_DIR` : chemins vers les modèles Ollama
> - `_find_model_blob(model_name)` : résolution du nom de modèle vers le fichier GGUF
> - `list_available_models()` : liste les modèles disponibles depuis les manifestes
> - `start_model_server(model_name, params)` : lance `llama-server.exe` sur un port libre,
>   attend que `/health` réponde (max 30s), stocke dans `_servers`
> - `get_server_url(model_name)` : URL si serveur actif, None sinon
> - `is_running(model_name)` : bool
> - `stop_all_servers()` : arrête tous les process llama-server.exe
>
> **FICHIER 2 — Modifier llm.py** :
> - Remplacer tous les appels `requests.post(http://localhost:11434/api/generate, ...)` par
>   des appels à `generate(prompt, model, system, stream, max_tokens, temperature, on_token)`
>   qui utilise `llamacpp_manager.get_server_url()` + `/v1/chat/completions` (format OpenAI)
> - La fonction `generate()` gère le streaming SSE (lignes `data: {...}`) et appelle
>   `on_token(token)` pour chaque token si `stream=True` et `on_token` fourni
> - `detect_intent(text)` utilise le modèle `MODELS['intent']` via `generate()`
> - Remplacer `_ensure_ollama()` par `_ensure_llamacpp(model_name)` qui appelle
>   `llamacpp_manager.start_model_server()` si le serveur n'est pas démarré
>
> **FICHIER 3 — Modifier main.py** :
> - Supprimer tous les imports et appels à `ollama_manager`
> - Importer `llamacpp_manager`
> - Au démarrage : vérifier que `llama-server.exe` existe, lister les modèles via
>   `llamacpp_manager.list_available_models()`, démarrer les serveurs intent + fast
>   en threads daemon
> - `atexit.register(llamacpp_manager.stop_all_servers)`
>
> **FICHIER 4 — Modifier ui.py** :
> - `get_available_models()` : utiliser `llamacpp_manager.list_available_models()` au lieu
>   d'Ollama, inclure `running_servers` dict dans la réponse JSON
>
> **FICHIER 5 — config.yaml** : ajouter section `llamacpp` comme spécifié
>
> **FICHIER 6 — Créer scripts/find_models.ps1** : script PowerShell pour lister les modèles
>
> **FICHIER 7 — Archiver ollama_manager.py → _archive/ollama_manager.py**
>
> **Note importante** : ne pas modifier `_find_model_blob()` pour qu'elle cherche les
> modèles UNIQUEMENT dans les blobs Ollama — si l'utilisateur place des fichiers GGUF
> dans un autre dossier (ex: `C:\models\`), ajouter un fallback qui cherche aussi dans
> le dossier défini par `llamacpp.models_dir` dans config.yaml.
>
> Créer : llamacpp_manager.py, scripts/find_models.ps1
> Modifier : llm.py, main.py, ui.py, config.yaml
> Archiver : ollama_manager.py → _archive/ollama_manager.py
