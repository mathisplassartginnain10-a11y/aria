"""
ui_bridge.py — Serveur WebSocket qui remplace pywebview.
Gère toute la communication entre Python et Electron via WebSocket.
"""
import asyncio
import json
import logging
import os
import socket
import tempfile
import threading
import websockets
from typing import Any, Callable

logger = logging.getLogger(__name__)

WS_HOST = "127.0.0.1"
WS_PORT = 9999

_PORT_FILE = os.path.join(tempfile.gettempdir(), "aria_ws_port.json")


def _find_free_port(start: int = 9999) -> int:
    """Trouve un port libre en partant de start."""
    for port in range(start, start + 20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((WS_HOST, port))
                return port
        except OSError:
            continue
    raise RuntimeError("Aucun port libre disponible entre 9999 et 10018")

# Callbacks enregistrés par les autres modules
_event_handlers: dict[str, list[Callable]] = {}
# Référence à toutes les connexions WebSocket actives
_connections: set = set()
# Boucle asyncio du serveur WS
_loop: asyncio.AbstractEventLoop | None = None


# ── API exposée au renderer (anciennement méthodes de la classe UI) ──────────

EXPOSED_FUNCTIONS: dict[str, Callable] = {}


def expose(func: Callable) -> Callable:
    """Décorateur pour exposer une fonction au renderer JS."""
    EXPOSED_FUNCTIONS[func.__name__] = func
    return func


# ── Emission d'événements vers le renderer ───────────────────────────────────

def emit(event_name: str, data: Any = None) -> None:
    """Envoie un événement unilatéral à tous les renderers connectés."""
    if not _connections:
        return
    msg = json.dumps({"id": None, "type": "event", "event": event_name, "data": data})
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_broadcast(msg), _loop)


async def _broadcast(message: str) -> None:
    for ws in list(_connections):
        try:
            await ws.send(message)
        except Exception:
            _connections.discard(ws)


def emit_stream_token(request_id: str, token: str) -> None:
    """Envoie un token de streaming LLM."""
    msg = json.dumps({"id": request_id, "type": "stream_token", "data": token})
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_broadcast(msg), _loop)


def emit_stream_end(request_id: str) -> None:
    """Signale la fin du streaming."""
    msg = json.dumps({"id": request_id, "type": "stream_end", "data": ""})
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_broadcast(msg), _loop)


# ── Fonctions helper (anciennement méthodes UI) ───────────────────────────────

def set_status(status: str) -> None:
    """Met à jour le statut d'ARIA dans l'UI (idle/listening/thinking/speaking)."""
    emit("status_change", status)


def show_user_text(text: str) -> None:
    """Affiche le texte de l'utilisateur dans le chat."""
    emit("user_message", text)


def append_assistant_text(text: str) -> None:
    """Ajoute du texte à la bulle ARIA en cours."""
    emit("assistant_token", text)


def finalize_assistant_message(model_name: str = "") -> None:
    """Finalise la bulle ARIA en cours."""
    emit("assistant_done", model_name or None)


def show_toast(message: str, toast_type: str = "info") -> None:
    """Affiche une notification toast."""
    emit("toast", {"message": message, "type": toast_type})


def update_waveform(rms: float) -> None:
    """Met à jour l'animation du micro."""
    emit("waveform", rms)


def show_partial_transcription(text: str) -> None:
    """Affiche la transcription partielle (temps réel)."""
    emit("stt_partial", text)


def show_final_transcription(text: str) -> None:
    """Affiche la transcription finale."""
    emit("stt_result", text)


# ── Fonctions exposées au renderer ────────────────────────────────────────────

@expose
def _get_available_models_spec() -> dict:
    import ollama_manager
    from llm import MODELS
    try:
        running = ollama_manager.is_running()
        local = ollama_manager.list_local_models() if running else []
    except Exception as e:
        running = False
        local = []
    return {
        "ollama_running": running,
        "local_models": local,
        "configured": dict(MODELS),
    }


@expose
def _set_model_spec(role: str, model_name: str) -> dict:
    import yaml, app_paths
    from llm import MODELS
    try:
        cfg_path = app_paths.config_path()
        with cfg_path.open('r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        cfg.setdefault('models', {})[role] = model_name
        with cfg_path.open('w', encoding='utf-8') as f:
            yaml.safe_dump(cfg, f, allow_unicode=True)
        MODELS[role] = model_name
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def _ask_spec(text: str, conv_mode: str = 'ecrit', request_id: str = None) -> str:
    """Traite un message utilisateur. Stream les tokens via WebSocket."""
    import llm, memory_engine as _me

    show_user_text(text)
    set_status('thinking')
    _me.add_to_conversation('user', text)

    def on_token(token: str):
        if request_id:
            emit_stream_token(request_id, token)
        else:
            append_assistant_text(token)

    result = llm.ask(text, conv_mode=conv_mode, on_token=on_token)

    if request_id:
        emit_stream_end(request_id)
    else:
        finalize_assistant_message()

    _me.add_to_conversation('assistant', result)
    set_status('idle')
    return result


@expose
def start_mic() -> dict:
    import stt
    if not stt.is_listening():
        stt.start_listening()
    return {"success": True}


@expose
def stop_mic() -> dict:
    import stt
    stt.stop_listening()
    return {"success": True}


@expose
def get_conversations() -> list:
    import memory_engine as _me
    return _me.get_conversations_list()


@expose
def new_conversation() -> dict:
    import memory_engine as _me
    conv_id = _me.new_conversation()
    return {"id": conv_id}


@expose
def load_conversation(conv_id: str) -> dict:
    import memory_engine as _me
    raw = _me.switch_conversation(conv_id)
    messages = [
        {
            "role": m.get("role", "user"),
            "content": m.get("content", m.get("text", "")),
        }
        for m in (raw or [])
    ]
    return {"id": conv_id, "messages": messages}


@expose
def delete_conversation(conv_id: str) -> dict:
    import memory_engine as _me
    success = _me.delete_conversation(conv_id)
    return {"success": success}


@expose
def delete_all_conversations() -> dict:
    import memory_engine as _me
    count = _me.delete_all_conversations()
    return {"success": True, "count": count}


@expose
def set_conversation_mode(conv_id: str, mode: str) -> dict:
    import memory_engine as _me
    _me.set_conversation_mode(conv_id, mode)
    return {"success": True}


@expose
def save_wallpaper(base64_data: str, filename: str) -> dict:
    import base64, time, app_paths
    from pathlib import Path
    try:
        wp_dir = app_paths.data_dir() / "wallpapers"
        wp_dir.mkdir(parents=True, exist_ok=True)
        if ',' in base64_data:
            base64_data = base64_data.split(',', 1)[1]
        ext = Path(filename).suffix.lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
            ext = '.jpg'
        safe_name = f"wallpaper_{int(time.time())}{ext}"
        (wp_dir / safe_name).write_bytes(base64.b64decode(base64_data))
        return {"success": True, "filename": safe_name}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def get_wallpapers() -> list:
    import app_paths
    wp_dir = app_paths.data_dir() / "wallpapers"
    if not wp_dir.exists():
        return []
    return [
        {"filename": f.name}
        for f in sorted(wp_dir.iterdir())
        if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.gif')
    ]


@expose
def delete_wallpaper(filename: str) -> dict:
    import app_paths
    from pathlib import Path
    try:
        target = app_paths.data_dir() / "wallpapers" / Path(filename).name
        if target.exists():
            target.unlink()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def get_settings() -> dict:
    import yaml, app_paths
    try:
        with app_paths.config_path().open('r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except:
        return {}


@expose
def save_settings(settings: dict) -> dict:
    import yaml, app_paths
    try:
        with app_paths.config_path().open('w', encoding='utf-8') as f:
            yaml.safe_dump(settings, f, allow_unicode=True)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def speak_text(text: str) -> dict:
    import tts
    tts.speak(text, force=True)
    return {"success": True}


@expose
def get_installed_apps() -> list:
    """Scanne les apps installées (registre + menu démarrer + Steam)."""
    import os, winreg, subprocess
    apps = set()

    # Registre Windows
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, path in keys:
        try:
            key = winreg.OpenKey(hive, path)
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                    try:
                        name, _ = winreg.QueryValueEx(sub, "DisplayName")
                        if name and 1 < len(name) < 60:
                            apps.add(name.strip())
                    except FileNotFoundError:
                        pass
                except Exception:
                    pass
        except Exception:
            pass

    # Menu Démarrer
    for d in [
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
    ]:
        for root, _, files in os.walk(d):
            for f in files:
                if f.endswith('.lnk') and 1 < len(f) < 63:
                    apps.add(f[:-4].strip())

    return sorted(apps, key=str.lower)


# ── Serveur WebSocket ─────────────────────────────────────────────────────────

async def _handle_connection(websocket) -> None:
    """Gère une connexion WebSocket entrante."""
    _connections.add(websocket)
    logger.info("Electron connecté (total: %d)", len(_connections))
    try:
        async for message in websocket:
            await _handle_message(websocket, message)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        _connections.discard(websocket)
        logger.info("Electron déconnecté (total: %d)", len(_connections))


async def _handle_message(websocket, raw: str) -> None:
    """Traite un message entrant du renderer."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Message JSON invalide: %s", raw[:100])
        return

    request_id = msg.get("id")
    action = msg.get("action")
    args = msg.get("args", [])
    kwargs = msg.get("kwargs", {})

    logger.debug("IPC reçu: %s(%s)", action, args[:1] if args else "")

    if action not in EXPOSED_FUNCTIONS:
        await websocket.send(json.dumps({
            "id": request_id,
            "type": "response",
            "data": None,
            "error": f"Action inconnue: {action}"
        }))
        return

    func = EXPOSED_FUNCTIONS[action]

    # Passer le request_id aux fonctions qui font du streaming
    if action == 'ask' and request_id:
        kwargs['request_id'] = request_id

    try:
        # Exécuter dans un thread séparé pour ne pas bloquer la boucle asyncio
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: func(*args, **kwargs)
        )
        await websocket.send(json.dumps({
            "id": request_id,
            "type": "response",
            "data": result,
            "error": None,
        }))
    except Exception as e:
        logger.error("Erreur action %s: %s", action, e, exc_info=True)
        await websocket.send(json.dumps({
            "id": request_id,
            "type": "response",
            "data": None,
            "error": str(e),
        }))


async def _run_server() -> None:
    global _loop, WS_PORT
    _loop = asyncio.get_event_loop()
    WS_PORT = _find_free_port(9999)

    with open(_PORT_FILE, "w", encoding="utf-8") as f:
        json.dump({"port": WS_PORT, "host": WS_HOST}, f)
    logger.info("Port WebSocket: %d (écrit dans %s)", WS_PORT, _PORT_FILE)

    async with websockets.serve(_handle_connection, WS_HOST, WS_PORT):
        logger.info("Serveur WebSocket ARIA démarré sur ws://%s:%d", WS_HOST, WS_PORT)
        await asyncio.Future()  # Tourne indéfiniment


def start() -> None:
    """Démarre le serveur WebSocket dans un thread daemon."""
    def _run():
        asyncio.run(_run_server())

    t = threading.Thread(target=_run, daemon=True, name="ARIA-WebSocket")
    t.start()
    logger.info("Thread WebSocket démarré")


# ── Helpers étendus (compatibilité llm.py / stt.py / main.py) ─────────────────

_pending_finalize_model: str = ""


def set_response_model(model_name: str = "") -> None:
    global _pending_finalize_model
    _pending_finalize_model = model_name or ""


def show_thinking(model_name: str = "", action: str = "Réflexion...") -> None:
    emit("thinking_start", {"model": model_name, "action": action})


def update_thinking_action(action: str) -> None:
    emit("thinking_action", action)


def hide_thinking() -> None:
    emit("thinking_hide", None)


def show_gdoc_link(title: str, url: str) -> None:
    emit("gdoc_link", {"title": title, "url": url})


def show_error(text: str) -> None:
    emit("error", text)
    show_toast(text, "error")


def update_focus_indicator(active: bool) -> None:
    emit("focus_indicator", active)


def notify_mic_state(active: bool) -> None:
    emit("mic_state", active)


def update_checklist_ui(section: str, item: int, total: int) -> None:
    emit("checklist_progress", {"section": section, "item": item, "total": total})


def hide_checklist_ui() -> None:
    emit("checklist_hide", None)


def emit_tts_finished() -> None:
    emit("tts_finished", None)


# ── Fonctions exposées supplémentaires ────────────────────────────────────────

@expose
def get_conversation_mode(conv_id: str):
    import memory_engine as _me
    return _me.get_conversation_mode(conv_id)


@expose
def get_static_port() -> int:
    return STATIC_FILE_PORT or 9998


@expose
def switch_model(model_name: str) -> str:
    import llm
    try:
        llm.set_active_model(model_name)
        return "ok"
    except Exception as e:
        logger.error("switch_model error: %s", e)
        return str(e)


@expose
def send_text(text: str) -> dict:
    import llm
    import threading

    def _run():
        set_status("thinking")
        llm.ask(text, show_user=False)
        set_status("idle")

    threading.Thread(target=_run, daemon=True).start()
    return {"success": True}


@expose
def stop_speaking() -> dict:
    import tts
    tts.stop()
    finalize_assistant_message()
    set_status("idle")
    return {"success": True}


@expose
def export_current_conversation() -> dict:
    try:
        from actions.export_pdf import export_conversation
        import memory_engine as _me
        path = export_conversation(
            _me.get_current_conversation_messages(),
            title=_me.get_current_conversation_title(),
        )
        return {"success": True, "path": path}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def run_mic_diagnostic() -> dict:
    import stt
    try:
        result = stt.run_diagnostic() if hasattr(stt, "run_diagnostic") else "Diagnostic non implémenté"
        return {"success": True, "result": str(result)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def toggle_activation() -> dict:
    import stt
    stt.toggle()
    if stt.is_listening():
        set_status("listening")
    else:
        set_status("idle")
    return {"success": True}


@expose
def get_available_models() -> dict:
    """Modèles llama.cpp locaux + cloud + config."""
    import json
    local: list[str] = []
    running_servers: dict[str, bool] = {}
    ollama_running = False
    configured: dict = {}
    try:
        import llamacpp_manager
        from llm import MODELS
        local = llamacpp_manager.list_available_models()
        running_servers = {m: llamacpp_manager.is_running(m) for m in local}
        ollama_running = llamacpp_manager.is_running() or bool(local)
        configured = dict(MODELS)
    except Exception as exc:
        logger.error("get_available_models error: %s", exc)
        try:
            from llm import MODELS as _M
            configured = dict(_M)
        except Exception:
            configured = {}

    current = "auto"
    options: list[dict] = []
    cloud_models: list[dict] = []
    try:
        import llm
        current = llm.FORCED_MODEL or "auto"

        def norm(name: str) -> str:
            return name.removesuffix(":latest") if name else ""

        options.append({
            "id": "auto",
            "label": "Auto",
            "subtitle": "Routage intelligent",
        })
        seen = {norm("auto")}
        for name in local:
            n = norm(name)
            if n and n not in seen:
                seen.add(n)
                options.append({"id": name, "label": n, "subtitle": "Installé localement"})
        try:
            from actions.cloud_llm import list_available_cloud_models
            for cm in list_available_cloud_models():
                cid = cm["id"]
                if norm(cid) not in seen:
                    seen.add(norm(cid))
                    options.append({
                        "id": cid,
                        "label": cm.get("label", cid),
                        "subtitle": cm.get("subtitle", "☁️ Cloud"),
                        "cloud": True,
                    })
                    cloud_models.append(cm)
        except Exception as exc:
            logger.debug("Cloud models: %s", exc)
    except Exception as exc:
        logger.error("get_available_models llm: %s", exc)

    return {
        "ollama_running": ollama_running,
        "local_models": local,
        "configured": configured,
        "current": current,
        "options": options,
        "running_servers": running_servers,
        "cloud_models": cloud_models,
    }


@expose
def set_model(role: str, model_name: str) -> dict:
    import llm
    try:
        llm.set_model_role(role, model_name)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def ask(text: str, conv_mode: str = "ecrit", request_id: str = None) -> str:
    import llm

    if conv_mode:
        try:
            import memory_engine as _me
            conv_id = _me.get_engine().current_conversation_id
            if conv_id:
                _me.set_conversation_mode(conv_id, conv_mode)
        except Exception:
            logger.debug("set conv_mode failed", exc_info=True)

    llm.ask(text, show_user=True)
    return ""


@expose
def get_agents() -> list:
    from actions import agents as _agents
    return _agents.get_all_agents()


@expose
def set_active_agent(agent_id: str) -> dict:
    from actions import agents as _agents
    try:
        agent = _agents.set_active_agent(agent_id)
        try:
            import llm
            llm._refresh_system_prompt()
        except Exception:
            pass
        return {"success": True, "agent": agent}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def get_cloud_providers() -> list:
    from actions import cloud_llm as _cloud
    return _cloud.get_all_providers()


@expose
def save_cloud_provider(provider_id: str, data_json: str) -> dict:
    from actions import cloud_llm as _cloud
    import json as _json
    try:
        data = _json.loads(data_json)
        provider = _cloud.update_provider(provider_id, **data)
        safe = dict(provider)
        if safe.get("api_key"):
            safe["api_key"] = "***"
        return {"success": True, "provider": safe}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def test_cloud_provider(provider_id: str) -> dict:
    from actions import cloud_llm as _cloud
    return _cloud.test_provider(provider_id)


@expose
def get_api_keys_status() -> dict:
    from actions.api_keys import get_all_status
    return get_all_status()


@expose
def save_api_key(provider: str, key: str, model: str = "") -> dict:
    from actions.api_keys import check_status, set_default_model, set_key
    try:
        set_key(provider, key)
        if model:
            set_default_model(provider, model)
        return {"success": True, "status": check_status(provider)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def delete_api_key(provider: str) -> dict:
    from actions.api_keys import set_key
    set_key(provider, "")
    return {"success": True}


@expose
def test_api_key(provider: str) -> dict:
    from actions.api_keys import generate_with_api, get_key
    if not get_key(provider):
        return {"success": False, "error": "Clé non configurée"}
    try:
        result = generate_with_api("Réponds juste: OK", provider=provider, max_tokens=5)
        ok = bool(result) and "erreur" not in result.lower()
        return {"success": ok, "response": result[:50]}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def get_weather_widget() -> dict:
    """Météo pour le widget — OpenWeatherMap si clé dispo, sinon wttr.in."""
    import requests
    import yaml
    import app_paths

    try:
        with app_paths.config_path().open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        weather_cfg = cfg.get("weather") or {}
        city = weather_cfg.get("city") or cfg.get("city", "Couëron")
        api_key = weather_cfg.get("api_key") or cfg.get("openweather_api_key", "")

        if api_key:
            r = requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": city, "appid": api_key, "units": "metric", "lang": "fr"},
                timeout=5,
            )
            if r.status_code == 200:
                d = r.json()
                return {
                    "temp": d["main"]["temp"],
                    "description": d["weather"][0]["description"],
                    "city": d["name"],
                    "humidity": d["main"]["humidity"],
                    "wind": d["wind"]["speed"],
                }

        r = requests.get(
            f"https://wttr.in/{requests.utils.quote(city)}?format=j1",
            timeout=5,
            headers={"User-Agent": "ARIA/1.0"},
        )
        if r.status_code == 200:
            d = r.json()
            current = d["current_condition"][0]
            return {
                "temp": float(current["temp_C"]),
                "description": current["weatherDesc"][0]["value"],
                "city": city,
                "humidity": int(current["humidity"]),
                "wind": float(current["windspeedKmph"]),
            }
    except Exception as e:
        logger.debug("Weather widget error: %s", e)

    return {"error": "unavailable"}


@expose
def get_memory_stats() -> dict:
    """Statistiques mémoire pour le widget (conversations, messages, sessions)."""
    import memory_engine as _me

    try:
        engine = _me.get_engine()
        total_msgs = sum(len(c.get("messages", [])) for c in engine.conversations)
        return {
            "conversations": len(engine.conversations),
            "messages": total_msgs,
            "sessions": len(engine.sessions),
        }
    except Exception as e:
        logger.error("get_memory_stats: %s", e)
        return {"conversations": 0, "messages": 0, "sessions": 0}


@expose
def get_presets() -> list:
    """Retourne les presets configurés pour les raccourcis."""
    import yaml
    import app_paths

    try:
        with app_paths.config_path().open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        presets = cfg.get("presets", {})
        return [
            {"id": k, "name": v.get("name", k), "icon": v.get("icon", "⚙️")}
            for k, v in presets.items()
        ]
    except Exception as e:
        logger.debug("get_presets: %s", e)
        return []


STATIC_FILE_PORT: int | None = None
