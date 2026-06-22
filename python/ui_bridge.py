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
# Callbacks appelés à la première connexion Electron (splash scan, etc.)
_client_connected_callbacks: list[Callable[[], None]] = []
_splash_scan_scheduled: bool = False
# Boucle asyncio du serveur WS
_loop: asyncio.AbstractEventLoop | None = None
_pending_finalize_model: str = ""
_ask_cycle_finalized: bool = False
_mobile_relay: Callable[[str, Any], None] | None = None
_shutdown_hook: Callable[[], None] | None = None


def set_mobile_relay(callback: Callable[[str, Any], None] | None) -> None:
    """Enregistre le relais d'événements vers les clients mobile PWA."""
    global _mobile_relay
    _mobile_relay = callback


def register_shutdown_hook(callback: Callable[[], None]) -> None:
    """Enregistre un callback d'arrêt (main.py : STT, mémoire, etc.)."""
    global _shutdown_hook
    _shutdown_hook = callback


# ── API exposée au renderer (anciennement méthodes de la classe UI) ──────────

EXPOSED_FUNCTIONS: dict[str, Callable] = {}


def expose(func: Callable) -> Callable:
    """Décorateur pour exposer une fonction au renderer JS."""
    EXPOSED_FUNCTIONS[func.__name__] = func
    return func


# ── Emission d'événements vers le renderer ───────────────────────────────────

_stt_debug: bool | None = None


def _is_stt_debug() -> bool:
    global _stt_debug
    if _stt_debug is not None:
        return _stt_debug
    try:
        import yaml
        import app_paths
        with app_paths.config_path().open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        _stt_debug = bool(cfg.get("stt_debug", False))
    except Exception:
        _stt_debug = False
    return _stt_debug


def on_client_connected(callback: Callable[[], None]) -> None:
    """Enregistre un callback invoqué à la première connexion WebSocket."""
    _client_connected_callbacks.append(callback)
    if _connections:
        _schedule_client_connected_callbacks()


def _schedule_client_connected_callbacks() -> None:
    global _splash_scan_scheduled
    if _splash_scan_scheduled or not _client_connected_callbacks:
        return
    _splash_scan_scheduled = True
    for cb in list(_client_connected_callbacks):
        try:
            cb()
        except Exception:
            logger.exception("Callback client connecté échoué")


def emit(event_name: str, data: Any = None) -> None:
    """Envoie un événement unilatéral à tous les renderers connectés."""
    if _mobile_relay:
        try:
            _mobile_relay(event_name, data)
        except Exception:
            logger.debug("Relay mobile échoué pour %s", event_name, exc_info=True)
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
    global _pending_finalize_model, _ask_cycle_finalized
    _ask_cycle_finalized = True
    label = model_name or _pending_finalize_model or None
    emit("assistant_done", label)
    _pending_finalize_model = ""


def show_toast(message: str, toast_type: str = "info") -> None:
    """Affiche une notification toast."""
    emit("toast", {"message": message, "type": toast_type})


def update_waveform(rms: float) -> None:
    """Met à jour l'animation du micro (debug STT uniquement)."""
    if not _is_stt_debug():
        return
    emit("waveform", rms)


def show_partial_transcription(text: str) -> None:
    """Affiche la transcription partielle (temps réel)."""
    emit("stt_partial", text)


def show_final_transcription(text: str) -> None:
    """Affiche la transcription finale."""
    emit("stt_result", text)
    emit("show_transcription", text)


def _on_stt_result(text: str) -> None:
    """Callback interne STT → Electron."""
    logger.info("STT résultat → UI: '%s'", text)
    show_final_transcription(text)


def _on_stt_status(status: str, value=None) -> None:
    """Callback interne statut STT → Electron (complément waveform / erreurs)."""
    logger.debug("STT status callback: %s", status)
    if status == "waveform" and value is not None:
        emit("waveform_data", {"rms": value})
    elif status == "error":
        show_toast("Erreur microphone", "error")


# ── Fonctions exposées au renderer ────────────────────────────────────────────

@expose
def _get_available_models_spec() -> dict:
    return get_available_models()


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
    """Démarre l'écoute du microphone."""
    import stt
    import yaml
    import app_paths

    logger.info("=== start_mic() appelé ===")
    if stt.is_listening():
        emit("mic_active", True)
        return {"success": True, "message": "Micro déjà actif"}

    try:
        with app_paths.config_path().open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        stt_cfg = cfg.get("stt") or {}
        device_index = stt_cfg.get("device_index")
        language = stt_cfg.get("language", cfg.get("language", "fr"))

        logger.info("Config STT: device=%s lang=%s", device_index, language)

        stt.start_listening(
            device_index=device_index,
            language=language,
            on_result=_on_stt_result,
            on_status=_on_stt_status,
        )
        emit("mic_active", True)
        return {"success": True, "message": "Micro démarré"}
    except Exception as e:
        logger.error("Erreur start_mic: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


@expose
def stop_mic() -> dict:
    """Arrête l'écoute du microphone."""
    import stt

    logger.info("=== stop_mic() appelé ===")
    stt.stop_listening()
    emit("mic_active", False)
    set_status("idle")
    return {"success": True}


@expose
def toggle_mic() -> dict:
    """Bascule le microphone ON/OFF."""
    import stt

    logger.info("=== toggle_mic() appelé (listening=%s) ===", stt.is_listening())
    if stt.is_listening():
        return stop_mic()
    return start_mic()


@expose
def get_conversations() -> list:
    import memory_engine as _me
    return _me.get_conversations_list()


@expose
def new_conversation() -> dict:
    import llm
    import memory_engine as _me

    conv_id = _me.new_conversation()
    llm.clear_history()
    return {"id": conv_id}


@expose
def load_conversation(conv_id: str) -> dict:
    import llm
    import memory_engine as _me

    raw = _me.switch_conversation(conv_id)
    messages = [
        {
            "role": m.get("role", "user"),
            "content": m.get("content", m.get("text", "")),
        }
        for m in (raw or [])
    ]
    llm.clear_history()
    llm.load_conversation_messages(messages)
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
        path = app_paths.config_path()
        with path.open('r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}

        merged = dict(settings)
        stt_updates = {}
        for flat_key in ('stt.device_index', 'stt.model'):
            if flat_key in merged:
                stt_updates[flat_key.split('.', 1)[1]] = merged.pop(flat_key)
        if stt_updates:
            cfg.setdefault('stt', {}).update(stt_updates)

        cfg.update(merged)

        with path.open('w', encoding='utf-8') as f:
            yaml.safe_dump(cfg, f, allow_unicode=True)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def set_tts_rate(rate: str) -> dict:
    import tts
    import llm

    tts.set_rate(rate)
    llm._patch_config({"tts_rate": rate})
    return {"success": True}


@expose
def set_tts_enabled(enabled: bool) -> dict:
    import tts
    import llm

    tts.set_enabled(bool(enabled))
    llm._patch_config({"tts_enabled": bool(enabled)})
    return {"success": True}


@expose
def speak_text(text: str) -> dict:
    import tts
    tts.speak(text, force=True)
    return {"success": True}


_apps_scan_done = False


def scan_apps_with_progress() -> None:
    """Scan toutes les apps et émet la progression en temps réel (splash)."""
    global _apps_scan_done
    import actions.apps as apps_module

    steps: list[tuple[str, str]] = [
        ("Scan registre Windows...", "registry"),
        ("Scan menu Démarrer...", "start_menu"),
        ("Scan Microsoft Store...", "uwp"),
        ("Scan Steam et Epic...", "gaming"),
        ("Scan Program Files...", "program_files"),
        ("Finalisation de l'index...", "finalize"),
    ]
    total = len(steps)
    all_entries: dict[str, dict] = {}
    uwp_map: dict[str, str] = {}

    def _emit_progress(step: int, label: str, *, done: bool = False) -> None:
        pct = 100 if done else int(((step - 1) / total) * 100)
        emit("splash_scan", {
            "step": step,
            "total": total,
            "label": label,
            "pct": pct,
            "count": len(all_entries),
            "done": done,
        })

    for i, (label, key) in enumerate(steps, start=1):
        _emit_progress(i, label)
        try:
            if key == "registry":
                apps_module._merge_entries(all_entries, apps_module._scan_registry())
            elif key == "start_menu":
                apps_module._merge_entries(all_entries, apps_module._scan_start_menu())
            elif key == "uwp":
                uwp_apps, uwp_map = apps_module._scan_uwp()
                apps_module._merge_entries(all_entries, uwp_apps)
            elif key == "gaming":
                apps_module._merge_entries(all_entries, apps_module._scan_gaming())
            elif key == "program_files":
                apps_module._merge_entries(all_entries, apps_module._scan_program_files())
            elif key == "finalize":
                apps_module._save_index(all_entries, uwp_map)
        except Exception as exc:
            logger.warning("Scan %s échoué: %s", label, exc)

    _apps_scan_done = True
    _emit_progress(
        total,
        f"{len(all_entries)} applications trouvées",
        done=True,
    )
    logger.info("Scan apps terminé: %d apps", len(all_entries))


def _scan_installed_apps() -> tuple[list, dict[str, str]]:
    """Scan registre + menu démarrer + UWP + gaming + Program Files."""
    from actions import apps as apps_module

    all_entries, uwp_map = apps_module.scan_all_apps()
    names = sorted({str(e.get("name", "")) for e in all_entries.values() if e.get("name")}, key=str.lower)
    return names, uwp_map


@expose
def launch_app(name: str) -> str:
    from actions.apps import launch

    return launch(name)


@expose
def close_app(name: str) -> str:
    from actions.apps import close

    return close(name)


@expose
def is_app_running(name: str) -> bool:
    from actions.apps import is_running

    return is_running(name)


@expose
def get_running_apps() -> list:
    from actions.apps import get_running_apps as _running

    return _running()


@expose
def get_apps_index() -> list:
    """Retourne la liste des apps indexées pour l'autocomplete UI."""
    from actions.apps import load_apps_index

    apps = load_apps_index()
    return [
        {
            "name": v.get("name", k),
            "type": v.get("type", "unknown"),
            "key": k,
        }
        for k, v in apps.items()
        if v.get("name")
    ]


@expose
def search_apps(query: str) -> list:
    """Recherche dans l'index d'apps — autocomplete temps réel."""
    from actions.apps import load_apps_index

    idx = load_apps_index()
    q = (query or "").lower().strip()
    if not q:
        return [
            {
                "name": v.get("name", k),
                "type": v.get("type", "unknown"),
                "key": k,
            }
            for k, v in sorted(idx.items(), key=lambda item: str(item[1].get("name", item[0])).lower())
            if v.get("name")
        ][:15]

    results = []
    for k, v in idx.items():
        name = str(v.get("name", k))
        if q in k or q in name.lower():
            results.append({
                "name": name,
                "type": v.get("type", "unknown"),
                "key": k,
            })
    return sorted(results, key=lambda x: len(x["name"]))[:15]


@expose
def get_active_doc() -> dict:
    """Doc Google actif de la session."""
    from actions.google_workspace import get_session_active_doc

    return get_session_active_doc() or {}


@expose
def web_search(query: str, sources: str = "web,news,wikipedia") -> str:
    from actions.web_research import search_and_synthesize

    src_list = [s.strip() for s in sources.split(",") if s.strip()]
    return search_and_synthesize(query, sources=src_list)


@expose
def clear_search_cache() -> dict:
    from actions.web_research import clear_cache

    clear_cache()
    return {"success": True}


@expose
def research_and_write_doc(topic: str, title: str = "") -> dict:
    from actions.google_workspace import research_and_write_doc as _write

    return _write(topic, title or None)


@expose
def research_and_write_sheet(topic: str, title: str = "") -> dict:
    from actions.google_workspace import research_and_write_sheet as _sheet

    return _sheet(topic, title or None)


@expose
def create_form(topic: str, title: str = "") -> dict:
    from actions.google_workspace import create_form_from_topic

    return create_form_from_topic(topic, title or None)


@expose
def get_installed_apps() -> list:
    """Liste des noms d'apps installées (index cache si disponible)."""
    import json

    try:
        import app_paths
        path = app_paths.data_dir() / "apps_index.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f) or {}
            cached = data.get("apps")
            if cached:
                return cached
    except Exception:
        pass
    apps, _uwp = _scan_installed_apps()
    return apps


@expose
def refresh_apps_index() -> dict:
    """Scanne et persiste l'index des applications."""
    global _apps_scan_done
    import json
    import time

    if _apps_scan_done:
        return get_apps_index_stats()

    apps, uwp = _scan_installed_apps()
    payload = {
        "count": len(apps),
        "updated_at": time.time(),
        "apps": apps,
        "uwp": uwp,
    }
    try:
        import app_paths
        path = app_paths.data_dir() / "apps_index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        _apps_scan_done = True
        return {"success": True, **payload}
    except Exception as exc:
        return {"success": False, "error": str(exc), "count": len(apps)}


@expose
def get_apps_index_stats() -> dict:
    """Retourne les stats de l'index apps (scan si absent)."""
    import json
    import time

    try:
        import app_paths
        path = app_paths.data_dir() / "apps_index.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f) or {}
            return {
                "success": True,
                "count": data.get("count", len(data.get("apps", []))),
                "updated_at": data.get("updated_at"),
            }
    except Exception:
        pass
    result = refresh_apps_index()
    return {
        "success": result.get("success", False),
        "count": result.get("count", 0),
        "updated_at": result.get("updated_at", time.time()),
    }


# ── Serveur WebSocket ─────────────────────────────────────────────────────────

async def _handle_connection(websocket) -> None:
    """Gère une connexion WebSocket entrante."""
    _connections.add(websocket)
    logger.info("Electron connecté (total: %d)", len(_connections))
    _schedule_client_connected_callbacks()
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

def set_response_model(model_name: str = "") -> None:
    global _pending_finalize_model
    _pending_finalize_model = model_name or ""
    if model_name:
        emit("response_model", model_name)


def show_thinking(model_name: str = "", action: str = "Réflexion...") -> None:
    emit("thinking_start", {"model": model_name, "action": action})


def update_thinking_action(action: str) -> None:
    emit("thinking_action", action)


def hide_thinking() -> None:
    emit("thinking_hide", None)


def show_gdoc_link(title: str, url: str) -> None:
    emit("gdoc_link", {"title": title, "url": url})


def notify_active_gdoc(doc: dict | None) -> None:
    """Notifie l'UI du doc Google actif (widget résumé)."""
    payload = doc or {}
    emit("active_gdoc", payload)
    emit("active_doc_changed", payload)


def show_search_results(html: str) -> None:
    emit("search_results", html)


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
def get_audio_devices() -> list:
    """Retourne la liste des devices audio disponibles (PyAudio)."""
    import stt

    return stt.get_available_devices()


@expose
def test_microphone(device_index: int | None = None) -> dict:
    """Test rapide du microphone — ~2 secondes d'enregistrement."""
    try:
        import numpy as np
        import pyaudio

        pa = pyaudio.PyAudio()
        chunk = 1024
        idx = int(device_index) if device_index is not None else None
        stream = pa.open(
            format=pyaudio.paFloat32,
            channels=1,
            rate=16000,
            input=True,
            input_device_index=idx,
            frames_per_buffer=chunk,
        )
        rms_values: list[float] = []
        for _ in range(20):
            data = stream.read(chunk, exception_on_overflow=False)
            samples = np.frombuffer(data, dtype=np.float32)
            rms_values.append(float(np.sqrt(np.mean(samples**2))))
        stream.stop_stream()
        stream.close()
        pa.terminate()
        avg_rms = sum(rms_values) / len(rms_values) if rms_values else 0.0
        active = avg_rms > 0.001
        return {
            "success": True,
            "avg_rms": avg_rms,
            "is_active": active,
            "message": "Microphone détecté ✓" if active else "Aucun son détecté",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@expose
def set_stt_device(device_index: int) -> dict:
    """Change le device microphone utilisé par STT."""
    return set_stt_device_index(device_index)


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
def stop_generation() -> dict:
    """Arrête immédiatement la génération LLM en cours."""
    import llm
    import tts

    llm.request_stop()
    try:
        tts.stop()
    except Exception:
        pass
    hide_thinking()
    logger.info("Génération arrêtée par l'utilisateur")
    finalize_assistant_message()
    set_status("idle")
    return {"success": True}


@expose
def ask(text: str, conv_mode: str = "ecrit", request_id: str = None) -> str:
    """Traite un message utilisateur et garantit la fin du cycle UI (assistant_done + idle)."""
    global _ask_cycle_finalized
    import llm

    _ask_cycle_finalized = False
    llm.clear_stop()

    if conv_mode:
        try:
            import memory_engine as _me
            conv_id = _me.get_engine().current_conversation_id
            if conv_id:
                _me.set_conversation_mode(conv_id, conv_mode)
        except Exception:
            logger.debug("set conv_mode failed", exc_info=True)

    result = ""
    try:
        llm.ask(text, show_user=True)
    except Exception as e:
        logger.error("Erreur ask(): %s", e, exc_info=True)
        result = f"Désolé, une erreur est survenue : {e}"
        append_assistant_text(result)
        finalize_assistant_message()
    finally:
        if not _ask_cycle_finalized:
            finalize_assistant_message()
        set_status("idle")

    return result


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
    from actions import presets as _presets

    try:
        merged = _presets.get_merged_presets()
        return [
            {"id": k, "name": v.get("name", k), "icon": v.get("icon", "⚙️")}
            for k, v in merged.items()
        ]
    except Exception as e:
        logger.debug("get_presets: %s", e)
        return []


@expose
def create_agent(data_json: str) -> dict:
    from actions import agents as _agents
    import json as _json
    try:
        data = _json.loads(data_json)
        agent = _agents.create_agent(
            name=data.get("name", "Agent"),
            icon=data.get("icon", "🤖"),
            color=data.get("color", "#6C8EFF"),
            model=data.get("model"),
            system_prompt=data.get("system_prompt", ""),
            rules=data.get("rules"),
            git_repos=data.get("git_repos"),
        )
        return {"success": True, "agent": agent}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def update_agent(agent_id: str, data_json: str) -> dict:
    from actions import agents as _agents
    import json as _json
    try:
        data = _json.loads(data_json)
        agent = _agents.update_agent(agent_id, **data)
        try:
            import llm
            llm._refresh_system_prompt()
        except Exception:
            pass
        return {"success": True, "agent": agent}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def delete_agent(agent_id: str) -> dict:
    from actions import agents as _agents
    try:
        ok = _agents.delete_agent(agent_id)
        return {"success": ok}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def get_active_agent() -> dict:
    from actions import agents as _agents
    return _agents.get_active_agent()


@expose
def validate_git_repo(path: str) -> dict:
    from pathlib import Path
    p = Path(path)
    valid = p.exists() and (p / ".git").exists()
    return {"valid": valid, "path": str(p.resolve()) if valid else None}


@expose
def run_preset(preset_id: str) -> dict:
    from actions import presets as _presets
    try:
        msg = _presets.activate(preset_id)
        return {"success": True, "message": msg}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def save_preset(preset_id: str, data_json: str) -> dict:
    from actions import presets as _presets
    import json as _json
    try:
        data = _json.loads(data_json)
        msg = _presets.create_preset(preset_id, data)
        return {"success": True, "message": msg}
    except Exception as e:
        return {"success": False, "error": str(e)}


@expose
def get_presets_full() -> list:
    from actions import presets as _presets
    merged = _presets.get_merged_presets()
    return [{"id": k, **v} for k, v in merged.items()]


@expose
def get_day_summary() -> dict:
    """Résumé du jour pour le widget (tâches + rappels)."""
    from datetime import date, datetime

    import memory
    from actions import checklist as _checklist

    memory.init()
    reminders = memory.recall("reminders", []) or []
    today = date.today()
    pending_today = 0
    upcoming = 0

    for reminder in reminders:
        if reminder.get("triggered"):
            continue
        try:
            dt = datetime.fromisoformat(reminder["datetime"])
            if dt.date() == today:
                pending_today += 1
            elif dt.date() > today:
                upcoming += 1
        except (ValueError, KeyError, TypeError):
            continue

    if _checklist.is_active():
        progress = _checklist.get_progress()
        tasks_label = progress["section"] if progress else "Checklist en cours"
        tasks_count = progress["item"] if progress else 1
        tasks_detail = f"{progress['item']}/{progress['total']}" if progress else "1"
    else:
        tasks_label = "Aucune tâche planifiée"
        tasks_count = 0
        tasks_detail = ""

    if pending_today:
        rappels_label = f"{pending_today} aujourd'hui"
    elif upcoming:
        rappels_label = f"{upcoming} à venir"
    else:
        rappels_label = "Aucun rappel"

    active_gdoc = None
    try:
        from actions.gdocs import get_active_doc

        active_gdoc = get_active_doc()
    except Exception:
        pass

    return {
        "tasks_count": tasks_count,
        "tasks_label": tasks_label,
        "tasks_detail": tasks_detail,
        "rappels_count": pending_today + upcoming,
        "rappels_label": rappels_label,
        "active_gdoc": active_gdoc,
    }


def _update_config_field(key: str, value) -> None:
    import yaml
    import app_paths

    cfg_path = app_paths.config_path()
    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg[key] = value
    with cfg_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def _update_stt_field(key: str, value) -> None:
    import yaml
    import app_paths

    cfg_path = app_paths.config_path()
    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    stt_cfg = cfg.setdefault("stt", {})
    stt_cfg[key] = value
    with cfg_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


@expose
def set_daily_brief(enabled: bool) -> dict:
    _update_config_field("daily_brief_enabled", bool(enabled))
    return {"success": True}


_wake_word_running = False


def _wake_word_trigger() -> None:
    """Active le micro quand le wake word est détecté."""
    import stt

    if stt.is_listening():
        return
    stt.start_listening()
    set_status("listening")
    notify_mic_state(True)
    show_toast("Wake word détecté — écoute...", "info")


def apply_wake_word(enabled: bool | None = None) -> None:
    """Démarre ou arrête la détection wake word."""
    global _wake_word_running
    import wake_word

    if enabled is None:
        try:
            enabled = bool(get_settings().get("wake_word_enabled"))
        except Exception:
            enabled = False

    if enabled and not _wake_word_running:
        model = get_settings().get("wake_word_model", "hey_jarvis_v0.1")
        wake_word.start(_wake_word_trigger, model_name=model)
        _wake_word_running = True
        logger.info("Wake word activé (%s)", model)
    elif not enabled and _wake_word_running:
        wake_word.stop()
        _wake_word_running = False
        logger.info("Wake word désactivé")


@expose
def set_wake_word(enabled: bool) -> dict:
    _update_config_field("wake_word_enabled", bool(enabled))
    apply_wake_word(bool(enabled))
    return {"success": True}


@expose
def set_light_vram_mode(enabled: bool) -> dict:
    """Mode économie VRAM — arrête les serveurs heavy/vision."""
    import llamacpp_manager
    from llm import MODELS

    _update_config_field("light_vram_mode", bool(enabled))
    if enabled:
        keep = {MODELS.get("intent"), MODELS.get("fast")}
        llamacpp_manager.stop_servers_except(keep)
    return {"success": True, "enabled": bool(enabled)}


@expose
def get_model_catalog() -> list:
    from actions import model_manager
    return model_manager.get_model_catalog()


@expose
def get_installed_models() -> list:
    from actions import model_manager
    return model_manager.get_installed_models()


@expose
def install_model(model_id: str) -> dict:
    from actions import model_manager
    return model_manager.install_model(model_id)


@expose
def uninstall_model(model_id: str) -> dict:
    from actions import model_manager
    return model_manager.uninstall_model(model_id)


@expose
def set_model_for_role(role: str, model_id: str) -> dict:
    from actions import model_manager
    return model_manager.set_model_for_role(role, model_id)


@expose
def get_profiles() -> dict:
    from actions import profiles
    return {
        "current_user": profiles.get_current_user_key(),
        "profiles": profiles.get_all_profiles(),
        "current": profiles.get_current_profile(),
    }


@expose
def switch_profile(name: str) -> dict:
    from actions import profiles
    return profiles.switch_profile(name)


@expose
def create_profile(name: str) -> dict:
    from actions import profiles
    return profiles.create_profile(name)


@expose
def delete_profile(name: str) -> dict:
    from actions import profiles
    return profiles.delete_profile(name)


@expose
def check_for_updates() -> dict:
    from actions import update_manager
    return update_manager.check_for_updates()


@expose
def apply_update() -> dict:
    from actions import update_manager
    return update_manager.apply_update()


@expose
def get_app_version() -> str:
    from actions import update_manager
    return update_manager.get_app_version()


@expose
def set_nexus_mode(enabled: bool) -> dict:
    """Mode Nexus VRAM — ne garde que llama3.2:1b actif."""
    import llamacpp_manager
    import yaml
    import app_paths
    from llm import MODELS, set_model_role

    cfg_path = app_paths.config_path()
    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    nexus_model = "llama3.2:1b"
    if enabled:
        if not cfg.get("models_backup"):
            cfg["models_backup"] = dict(MODELS)
        for role in ("intent", "fast", "heavy", "vision"):
            set_model_role(role, nexus_model)
        llamacpp_manager.stop_servers_except({nexus_model})
        show_toast("⚡ Nexus activé — VRAM libérée", "success")
    else:
        backup = cfg.get("models_backup") or {}
        if backup:
            for role, model in backup.items():
                if role in MODELS and model:
                    set_model_role(role, str(model))
        else:
            for role in ("intent", "fast", "heavy", "vision"):
                model = (cfg.get("models") or {}).get(role)
                if model:
                    set_model_role(role, str(model))
        show_toast("🧠 Mode normal rétabli", "info")

    cfg["nexus_mode"] = bool(enabled)
    with cfg_path.open("w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    emit("nexus_mode_changed", {"enabled": bool(enabled)})
    return {"success": True, "enabled": bool(enabled)}


@expose
def get_nexus_mode() -> dict:
    try:
        import yaml
        import app_paths
        with app_paths.config_path().open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return {"enabled": bool(cfg.get("nexus_mode", False))}
    except Exception:
        return {"enabled": False}


@expose
def get_vram_usage() -> dict:
    import shutil
    import subprocess
    import sys

    if not shutil.which("nvidia-smi"):
        return {"used_mb": 0, "total_mb": 0, "free_mb": 0, "used_pct": 0}
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        parts = [p.strip() for p in (out.stdout or "").split(",")]
        if len(parts) >= 3:
            used, total, free = int(float(parts[0])), int(float(parts[1])), int(float(parts[2]))
            pct = round(used / total * 100) if total else 0
            return {"used_mb": used, "total_mb": total, "free_mb": free, "used_pct": pct}
    except Exception as exc:
        logger.debug("nvidia-smi failed: %s", exc)
    return {"used_mb": 0, "total_mb": 0, "free_mb": 0, "used_pct": 0}


@expose
def shutdown() -> dict:
    """Arrêt propre du backend ARIA (appelé par Electron)."""
    import sys
    import threading

    logger.info("=== Arrêt ARIA demandé par Electron ===")

    try:
        import stt
        stt.stop_listening()
    except Exception:
        logger.debug("STT stop skipped", exc_info=True)

    try:
        import tts
        tts.stop()
    except Exception:
        pass

    try:
        import llamacpp_manager
        llamacpp_manager.stop_all_servers()
    except Exception:
        logger.debug("llama stop skipped", exc_info=True)

    if _shutdown_hook:
        try:
            _shutdown_hook()
        except Exception:
            logger.exception("Shutdown hook failed")

    try:
        import yaml
        import app_paths
        import subprocess

        with app_paths.config_path().open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        if cfg.get("kill_ollama_on_exit", True) and sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/IM", "ollama.exe"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
    except Exception:
        logger.debug("Ollama kill skipped", exc_info=True)

    threading.Timer(0.5, lambda: sys.exit(0)).start()
    return {"success": True}


@expose
def register_local_model(file_path: str) -> dict:
    """Enregistre un modèle GGUF local (copie vers le dossier llama.cpp)."""
    import shutil
    from pathlib import Path

    import llamacpp_manager

    src = Path(file_path).expanduser()
    if not src.exists() or src.suffix.lower() != ".gguf":
        return {"success": False, "error": "Fichier GGUF introuvable"}

    models_dir = llamacpp_manager.CUSTOM_MODELS_DIR
    if not models_dir:
        return {"success": False, "error": "models_dir non configuré dans config.yaml"}
    models_dir = Path(models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    dst = models_dir / src.name
    try:
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        return {
            "success": True,
            "filename": dst.name,
            "models": llamacpp_manager.list_available_models(),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@expose
def type_to_active_window(text: str) -> dict:
    from actions.type_anywhere import type_to_active_window as _type

    message = _type(text)
    return {"success": "Impossible" not in message, "message": message}


@expose
def set_realtime_stt(enabled: bool) -> dict:
    _update_config_field("realtime_transcription", bool(enabled))
    return {"success": True}


@expose
def set_focus_mode(enabled: bool) -> dict:
    import focus

    focus.set_focus_mode(bool(enabled))
    update_focus_indicator(focus.is_focus_active())
    return {"success": True}


@expose
def set_stt_device_index(value) -> dict:
    idx = None
    if value is not None and str(value).strip() != "":
        try:
            idx = int(value)
        except ValueError:
            idx = None
    _update_stt_field("device_index", idx)
    return {"success": True}


@expose
def set_whisper_model(model: str) -> dict:
    _update_config_field("whisper_model", model)
    _update_stt_field("model", model)
    return {"success": True}


@expose
def send_files_with_prompt(files_json: str, prompt: str) -> dict:
    import base64
    import json
    import os
    import subprocess
    import sys
    import tempfile
    import threading
    from pathlib import Path

    def _process() -> None:
        try:
            files = json.loads(files_json)
            if not files:
                return

            set_status("thinking")

            images_b64: list[str] = []
            text_contents: list[str] = []
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

            for f in files:
                mime = f.get("type", "")
                name = f.get("name", "fichier")
                data = base64.b64decode(f["b64"])
                ext = Path(name).suffix or ".bin"

                tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                tmp.write(data)
                tmp.close()
                tmp_path = tmp.name

                try:
                    if mime.startswith("image/"):
                        images_b64.append(f["b64"])
                    elif mime == "application/pdf" or name.lower().endswith(".pdf"):
                        from pypdf import PdfReader

                        reader = PdfReader(tmp_path)
                        text = "\n".join(p.extract_text() or "" for p in reader.pages[:10])
                        text_contents.append(f"[PDF: {name}]\n{text[:5000]}")
                    elif mime.startswith("video/"):
                        frame = tempfile.mktemp(suffix=".jpg")
                        subprocess.run(
                            [
                                "ffmpeg", "-i", tmp_path, "-ss", "00:00:01",
                                "-frames:v", "1", frame, "-y",
                            ],
                            capture_output=True,
                            timeout=15,
                            creationflags=flags,
                        )
                        if os.path.exists(frame):
                            with open(frame, "rb") as img:
                                images_b64.append(base64.b64encode(img.read()).decode())
                            os.unlink(frame)
                    else:
                        with open(tmp_path, "r", encoding="utf-8", errors="ignore") as tf:
                            text_contents.append(f"[{name}]\n{tf.read(5000)}")
                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)

            csv_files = [
                f for f in files
                if f.get("name", "").lower().endswith((".csv", ".xlsx", ".xls"))
            ]
            if csv_files and not images_b64:
                from actions.data_analysis import analyze_file

                tmp_csv = tempfile.NamedTemporaryFile(
                    suffix=Path(csv_files[0]["name"]).suffix, delete=False
                )
                tmp_csv.write(base64.b64decode(csv_files[0]["b64"]))
                tmp_csv.close()
                try:
                    result = analyze_file(tmp_csv.name, prompt)
                    append_assistant_text(result)
                    finalize_assistant_message()
                    set_status("idle")
                    return
                finally:
                    if os.path.exists(tmp_csv.name):
                        os.unlink(tmp_csv.name)

            import llm

            if images_b64:
                homework = any(
                    kw in prompt.lower()
                    for kw in ("devoir", "corrige", "correction", "exercice", "bac", "note")
                )
                if homework and len(images_b64) == 1:
                    result = llm.analyze_homework_image(images_b64[0], prompt)
                    append_assistant_text(result)
                    finalize_assistant_message()
                    set_status("idle")
                else:
                    llm.ask_with_images_and_text(prompt, images_b64, text_contents)
            elif text_contents:
                combined = "\n\n".join(text_contents)
                llm.ask(f"{prompt}\n\nContenu des fichiers:\n{combined}", show_user=False)
            else:
                show_error("Aucun contenu exploitable dans les fichiers envoyés.")
                set_status("idle")
        except Exception as e:
            logger.error("send_files_with_prompt error: %s", e)
            show_error(f"Erreur: {e}")
            set_status("idle")

    threading.Thread(target=_process, daemon=True).start()
    return {"success": True}


@expose
def get_memory_engine_stats() -> dict:
    """Statistiques détaillées du profil mémoire (satisfaction, apps, sujets)."""
    import memory_engine as _me
    try:
        return _me.get_memory_stats()
    except Exception as e:
        logger.debug("get_memory_engine_stats: %s", e)
        return {}


@expose
def optimize_memory() -> dict:
    """Nettoie les conversations vides et compresse la mémoire."""
    import memory_engine as _me

    try:
        engine = _me.get_engine()
        removed = 0
        empty_ids = [
            c.get("id") for c in list(engine.conversations)
            if c.get("id") and not c.get("messages")
        ]
        for cid in empty_ids:
            if engine.delete_conversation(cid):
                removed += 1
        engine.save_current_conversation()
        return {
            "success": True,
            "message": f"Mémoire optimisée — {removed} conversation(s) vide(s) supprimée(s).",
            "removed": removed,
        }
    except Exception as e:
        logger.error("optimize_memory: %s", e)
        return {"success": False, "error": str(e)}


@expose
def get_google_status() -> dict:
    """Statut OAuth Google Workspace."""
    from actions.google_auth import credentials_path, is_authenticated, is_configured

    path = credentials_path()
    return {
        "success": True,
        "configured": is_configured(),
        "authenticated": is_authenticated(),
        "credentials_path": str(path) if path else "",
    }


@expose
def run_google_setup() -> dict:
    """Lance le flux OAuth Google (ouvre le navigateur)."""
    try:
        from actions.google_auth import get_credentials

        get_credentials(interactive=True)
        return {"success": True, "message": "Google connecté"}
    except Exception as exc:
        logger.exception("run_google_setup")
        return {"success": False, "error": str(exc)}


@expose
def get_calendar_widget() -> dict:
    """Prochains événements du jour pour le widget résumé."""
    try:
        from actions.gcalendar import get_today_events
        from actions.google_auth import is_authenticated, is_configured

        if not is_configured() or not is_authenticated():
            return {"success": False, "events": []}
        events = get_today_events()
        return {"success": True, "events": events}
    except Exception as exc:
        return {"success": False, "error": str(exc), "events": []}


STATIC_FILE_PORT: int | None = None
