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
import threading
import time

import requests as req
import yaml
from flask import Flask, Response, jsonify, request, stream_with_context

import app_paths
import llm
import memory_engine
import ollama_manager
from actions import apps, system

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

PIN_CODE = "0000"
SESSIONS: dict[str, dict] = {}
MOBILE_MODEL = "llama3.1:8b-instruct-q8_0"
CACHE_TTL = 300
_response_cache: dict[str, dict] = {}


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


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({
        "status": "ok",
        "name": "ARIA",
        "version": "2.0",
        "pc_name": socket.gethostname(),
        "ollama_running": ollama_manager.is_running(),
    })


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


if __name__ == "__main__":
    cfg = _load_config()
    ollama_manager.configure(cfg.get("ollama_path", ""))

    if not ollama_manager.is_running():
        logger.info("Démarrage Ollama...")
        ollama_manager.start()
        ollama_manager.wait_until_ready(timeout=30)

    ip = get_local_ip()
    port = 5000

    print(f"\n{'=' * 50}")
    print("  ARIA Mobile Server démarré")
    print(f"  IP locale  : {ip}")
    print(f"  Port       : {port}")
    print(f"  PIN        : {PIN_CODE}")
    print(f"  URL mobile : http://{ip}:{port}")
    print(f"{'=' * 50}")
    print("\n  Depuis ton téléphone (même WiFi) :")
    print(f"  Connecte-toi à http://{ip}:{port}")
    print(f"  Code PIN : {PIN_CODE}")
    print("\n  TOUTES les actions s'exécutent sur CE PC")
    print(f"{'=' * 50}\n")

    try:
        from gevent.pywsgi import WSGIServer

        server = WSGIServer(("0.0.0.0", port), app)
        server.serve_forever()
    except ImportError:
        app.run(host="0.0.0.0", port=port, debug=False, threaded=True)