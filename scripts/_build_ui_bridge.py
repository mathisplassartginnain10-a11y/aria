"""Build python/ui_bridge.py from spec + project extensions."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = (ROOT / "docs" / "aria-spec-v19-electron.md").read_text(encoding="utf-8")
start = spec.find("```python", spec.find("FICHIER 1"))
start = spec.find("\n", start) + 1
end = spec.find("```", start)
core = spec[start:end]

extensions = r'''
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
    import memory_engine as _me

    show_user_text(text)
    set_status("thinking")
    _me.add_to_conversation("user", text)

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

    _me.add_to_conversation("assistant", result)
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


STATIC_FILE_PORT: int | None = None
'''

# Fix spec get_available_models - we override with extended version
core = core.replace("@expose\ndef get_available_models() -> dict:", "@expose\ndef _get_available_models_spec() -> dict:")
core = core.replace("@expose\ndef set_model(role: str, model_name: str) -> dict:", "@expose\ndef _set_model_spec(role: str, model_name: str) -> dict:")
core = core.replace("@expose\ndef ask(text: str, conv_mode: str = 'ecrit', request_id: str = None) -> str:", "@expose\ndef _ask_spec(text: str, conv_mode: str = 'ecrit', request_id: str = None) -> str:")

# Fix emit to handle missing loop
core = core.replace(
    "def emit(event_name: str, data: Any = None) -> None:",
    "def emit(event_name: str, data: Any = None) -> None:",
)
core = core.replace(
    "    asyncio.run_coroutine_threadsafe(_broadcast(msg), _loop)",
    "    if _loop is None:\n        return\n    asyncio.run_coroutine_threadsafe(_broadcast(msg), _loop)",
)

out = core + "\n" + extensions
(ROOT / "python" / "ui_bridge.py").write_text(out, encoding="utf-8")
print("ui_bridge.py", len(out), "chars")
