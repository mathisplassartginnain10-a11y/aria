"""
ARIA Mobile Server — API REST pour contrôler le PC depuis le téléphone.
Toutes les actions s'exécutent sur le PC, le téléphone est juste un terminal.

Lance avec : .venv\\Scripts\\python.exe aria_mobile_server.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import socket
import tempfile
import threading
import time
from pathlib import Path

import requests as req
import yaml
from flask import Flask, Response, jsonify, request, stream_with_context

import app_paths
import llm
import memory_engine
import ollama_manager
import stt
from actions import apps, presets, system

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

PIN_CODE = "0000"
MOBILE_PORT = 5000
SESSIONS: dict[str, dict] = {}
MOBILE_MODEL = "llama3.1:8b-instruct-q8_0"
CACHE_TTL = 300
_response_cache: dict[str, dict] = {}


def _apply_mobile_config(cfg: dict) -> None:
    global PIN_CODE, MOBILE_PORT
    if cfg.get("mobile_pin"):
        PIN_CODE = str(cfg["mobile_pin"])
    if cfg.get("mobile_port"):
        MOBILE_PORT = int(cfg["mobile_port"])


def get_cached(text: str) -> str | None:
    key = hashlib.md5(text.lower().strip().encode()).hexdigest()
    if key in _response_cache:
        cached = _response_cache[key]
        if time.time() - cached["time"] < CACHE_TTL:
            return cached["response"]
    return None


def set_cached(text: str, response: str) -> None:
    key = hashlib.md5(text.lower().strip().encode()).hexdigest()
    _response_cache[key] = {"response": response, "time": time.time()}


def _load_config() -> dict:
    with app_paths.config_path().open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    finally:
        sock.close()


def check_auth(req) -> bool:
    token = req.headers.get("X-Token", "")
    return token in SESSIONS and SESSIONS[token].get("authenticated")


def cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.after_request
def after_request(response):
    return cors_headers(response)


def get_connect_info() -> dict:
    ip = get_local_ip()
    return {
        "ip": ip,
        "local_ip": ip,
        "port": MOBILE_PORT,
        "pc_name": socket.gethostname(),
        "qr_payload": f"aria://{ip}:{MOBILE_PORT}",
    }


_server_thread: threading.Thread | None = None


def is_server_running() -> bool:
    return _server_thread is not None and _server_thread.is_alive()


@app.route("/ping", methods=["GET"])
def ping():
    info = get_connect_info()
    return jsonify({
        "status": "ok",
        "name": "ARIA",
        "version": "2.0",
        "pc_name": info["pc_name"],
        "local_ip": info["ip"],
        "port": info["port"],
        "qr_payload": info["qr_payload"],
        "ollama_running": ollama_manager.is_running(),
        "whisper_ready": stt.is_ready(),
    })


@app.route("/connect-info", methods=["GET"])
def connect_info():
    """Infos de connexion pour l'app mobile (sans auth)."""
    info = get_connect_info()
    return jsonify({"status": "ok", **info})


@app.route("/auth", methods=["POST"])
def auth():
    data = request.get_json() or {}
    if data.get("pin") == PIN_CODE:
        token = secrets.token_hex(16)
        SESSIONS[token] = {"authenticated": True, "created_at": time.time()}
        logger.info("Mobile connecté — token généré")
        return jsonify({"status": "ok", "token": token, "message": "Connecté à ARIA"})
    return jsonify({"status": "error", "message": "Code incorrect"}), 401


@app.route("/ask", methods=["POST"])
def ask():
    """Envoie un prompt — exécuté entièrement sur le PC."""
    if not check_auth(request):
        return jsonify({"error": "Non autorisé"}), 401

    data = request.get_json() or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Texte vide"}), 400

    logger.info("Mobile → PC: '%s'", text)

    result = {"response": "", "done": False}
    error: list[str | None] = [None]

    def _run():
        try:
            result["response"] = llm.ask_return_text(text)
            result["done"] = True
        except Exception as exc:
            error[0] = str(exc)
            result["done"] = True

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=90)

    if error[0]:
        return jsonify({"error": error[0]}), 500

    return jsonify({
        "response": result["response"],
        "executed_on": "PC",
    })


@app.route("/ask/fast", methods=["POST"])
def ask_fast():
    """Réponse rapide pour mobile — cache, regex intent, modèle léger."""
    if not check_auth(request):
        return jsonify({"error": "Non autorisé"}), 401

    data = request.get_json() or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Texte vide"}), 400

    cached = get_cached(text)
    if cached:
        return jsonify({"response": cached, "source": "cache"})

    fast = llm._fast_intent(text) if hasattr(llm, "_fast_intent") else None
    if fast and fast != "question_libre":
        try:
            params = llm._fast_intent_params(fast, text)
            result = llm._dispatch_action(fast, params, text)
            set_cached(text, result)
            return jsonify({"response": result, "source": "action", "executed_on": "PC"})
        except Exception:
            pass

    try:
        response = req.post(
            "http://localhost:11434/api/generate",
            json={
                "model": MOBILE_MODEL,
                "prompt": text,
                "stream": False,
                "options": {
                    "num_predict": 150,
                    "temperature": 0.7,
                    "top_p": 0.9,
                },
            },
            timeout=30,
        )
        response.raise_for_status()
        result = response.json().get("response", "")
        set_cached(text, result)
        return jsonify({"response": result, "source": "llm"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/warmup", methods=["POST"])
def warmup():
    """Pré-charge le modèle mobile dans Ollama."""
    if not check_auth(request):
        return jsonify({"error": "Non autorisé"}), 401

    def _warm():
        try:
            req.post(
                "http://localhost:11434/api/generate",
                json={"model": MOBILE_MODEL, "prompt": "", "keep_alive": "30m"},
                timeout=30,
            )
        except Exception as exc:
            logger.warning("Warmup Ollama échoué: %s", exc)

    threading.Thread(target=_warm, daemon=True).start()
    return jsonify({"status": "warming up"})


@app.route("/transcribe", methods=["POST"])
def transcribe():
    """Transcrit un enregistrement vocal du mobile via Whisper sur le PC."""
    if not check_auth(request):
        return jsonify({"error": "Non autorisé"}), 401

    upload = request.files.get("audio")
    if not upload or not upload.filename:
        return jsonify({"error": "Fichier audio manquant"}), 400

    suffix = Path(upload.filename).suffix or ".m4a"
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            upload.save(tmp.name)
            tmp_path = tmp.name

        logger.info("Transcription mobile — fichier %s (%.1f Ko)", suffix, Path(tmp_path).stat().st_size / 1024)
        text = stt.transcribe_file(tmp_path)
        if not text:
            return jsonify({"error": "Transcription vide — réessaie en parlant plus fort"}), 422
        return jsonify({"text": text, "transcribed_on": "PC"})
    except Exception as exc:
        logger.exception("Erreur /transcribe")
        return jsonify({"error": str(exc)}), 500
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass


@app.route("/ask/stream", methods=["POST"])
def ask_stream():
    """Stream la réponse token par token vers le mobile — actions sur PC."""
    if not check_auth(request):
        return jsonify({"error": "Non autorisé"}), 401

    data = request.get_json() or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Texte vide"}), 400

    def generate():
        intent_data = llm._detect_intent(text)
        intent = intent_data.get("intent", "question_libre")
        confidence = intent_data.get("confidence", 0)

        if confidence > 0.8 and intent != "question_libre":
            try:
                action_result = llm._dispatch_action(
                    intent,
                    intent_data.get("params", {}),
                    text,
                )
                if action_result:
                    yield f"data: {json.dumps({'token': action_result, 'type': 'action'})}\n\n"
                    yield f"data: {json.dumps({'done': True})}\n\n"
                    return
            except Exception as exc:
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"
                return

        llm._refresh_system_prompt()
        llm._history.append({"role": "user", "content": text})
        llm._trim_history()
        memory_engine.add_to_conversation("user", text)

        response = llm._ollama_request(llm._history, stream=True)
        if response is None:
            yield f"data: {json.dumps({'error': 'Ollama indisponible'})}\n\n"
            return

        full = ""
        try:
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                token = chunk.get("message", {}).get("content", "")
                if token:
                    full += token
                    yield f"data: {json.dumps({'token': token})}\n\n"
                if chunk.get("done"):
                    break
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            return

        if full.strip():
            llm._history.append({"role": "assistant", "content": full})
            llm._trim_history()
            llm._save_history()
            memory_engine.add_to_conversation("assistant", full)

        yield f"data: {json.dumps({'done': True})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@app.route("/conversations", methods=["GET"])
def get_conversations():
    if not check_auth(request):
        return jsonify({"error": "Non autorisé"}), 401
    return jsonify(memory_engine.get_conversations_list())


@app.route("/conversation/<conv_id>", methods=["GET"])
def get_conversation(conv_id):
    if not check_auth(request):
        return jsonify({"error": "Non autorisé"}), 401
    messages = memory_engine.load_conversation(conv_id)
    return jsonify(messages)


@app.route("/history/clear", methods=["POST"])
def clear_history():
    if not check_auth(request):
        return jsonify({"error": "Non autorisé"}), 401
    llm.clear_history()
    memory_engine.new_conversation()
    return jsonify({"status": "ok"})


@app.route("/status", methods=["GET"])
def status():
    if not check_auth(request):
        return jsonify({"error": "Non autorisé"}), 401
    import psutil

    return jsonify({
        "ollama_running": ollama_manager.is_running(),
        "cpu_percent": psutil.cpu_percent(),
        "ram_percent": psutil.virtual_memory().percent,
        "pc_name": socket.gethostname(),
    })


@app.route("/apps/launch", methods=["POST"])
def launch_app():
    """Lance une app sur le PC depuis le mobile."""
    if not check_auth(request):
        return jsonify({"error": "Non autorisé"}), 401
    data = request.get_json() or {}
    app_name = data.get("app", "")
    result = apps.launch(app_name)
    return jsonify({"result": result, "executed_on": "PC"})


@app.route("/system/volume", methods=["POST"])
def set_volume():
    """Change le volume du PC depuis le mobile."""
    if not check_auth(request):
        return jsonify({"error": "Non autorisé"}), 401
    data = request.get_json() or {}
    level = data.get("level", 50)
    result = system.set_volume(level)
    return jsonify({"result": result, "executed_on": "PC"})


@app.route("/presets", methods=["GET"])
def list_presets():
    """Liste les presets disponibles sur le PC."""
    if not check_auth(request):
        return jsonify({"error": "Non autorisé"}), 401
    merged = presets.get_merged_presets()
    items = [
        {
            "key": key,
            "label": data.get("label", key),
            "icon": data.get("icon", "⚡"),
            "active": presets.get_active_preset() == key,
        }
        for key, data in merged.items()
    ]
    return jsonify({"presets": items, "active": presets.get_active_preset()})


@app.route("/presets/<name>/activate", methods=["POST"])
def activate_preset(name: str):
    """Active un preset sur le PC."""
    if not check_auth(request):
        return jsonify({"error": "Non autorisé"}), 401
    result = presets.activate(name)
    return jsonify({"result": result, "preset": name, "executed_on": "PC"})


@app.route("/presets/deactivate", methods=["POST"])
def deactivate_preset():
    if not check_auth(request):
        return jsonify({"error": "Non autorisé"}), 401
    result = presets.deactivate()
    return jsonify({"result": result, "executed_on": "PC"})


def _print_startup_banner() -> None:
    info = get_connect_info()
    print(f"\n{'=' * 50}")
    print("  ARIA Mobile Server démarré")
    print(f"  IP locale  : {info['ip']}")
    print(f"  Port       : {info['port']}")
    print(f"  PIN        : {PIN_CODE}")
    print(f"  QR         : {info['qr_payload']}")
    print(f"  URL mobile : http://{info['ip']}:{info['port']}")
    print(f"{'=' * 50}")
    print("\n  Depuis ton téléphone (même WiFi) :")
    print(f"  Scanne le QR ou connecte-toi à http://{info['ip']}:{info['port']}")
    print(f"  Code PIN : {PIN_CODE}")
    print("\n  TOUTES les actions s'exécutent sur CE PC")
    print(f"{'=' * 50}\n")


def _serve_forever(port: int) -> None:
    try:
        try:
            from gevent.pywsgi import WSGIServer

            server = WSGIServer(("0.0.0.0", port), app)
            server.serve_forever()
        except ImportError:
            app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
    except OSError as exc:
        if getattr(exc, "errno", None) == 10048 or "10048" in str(exc) or "Address already in use" in str(exc):
            logger.warning(
                "Serveur mobile désactivé : port %d déjà utilisé "
                "(une autre instance d'ARIA tourne peut-être).", port
            )
        else:
            logger.error("Serveur mobile : erreur socket : %s", exc)
    except Exception:
        logger.exception("Serveur mobile : arrêt inattendu")


def start_mobile_server(
    config: dict | None = None,
    *,
    block: bool = False,
    ensure_ollama: bool = False,
    banner: bool = True,
) -> bool:
    """Démarre le serveur mobile (thread daemon ou bloquant)."""
    global _server_thread

    if is_server_running():
        return True

    cfg = config or _load_config()
    _apply_mobile_config(cfg)
    ollama_manager.configure(cfg.get("ollama_path", ""))

    if ensure_ollama and not ollama_manager.is_running():
        logger.info("Démarrage Ollama pour le serveur mobile...")
        ollama_manager.start()
        ollama_manager.wait_until_ready(timeout=30)

    port = MOBILE_PORT

    def _run() -> None:
        if banner:
            _print_startup_banner()
        _serve_forever(port)

    if block:
        _run()
        return True

    _server_thread = threading.Thread(
        target=_run, daemon=True, name="aria-mobile-server"
    )
    _server_thread.start()
    return True


if __name__ == "__main__":
    start_mobile_server(block=True, ensure_ollama=True, banner=True)