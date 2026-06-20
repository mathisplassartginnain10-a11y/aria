"""
cloud_llm.py — IA externes via clés API (OpenAI, Anthropic, Groq, OpenRouter, etc.).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Callable

import requests
import yaml

import app_paths

logger = logging.getLogger(__name__)

CLOUD_PREFIX = "cloud:"

# Catalogue par défaut — fusionné avec config.yaml
DEFAULT_PROVIDERS: dict[str, dict] = {
    "openai": {
        "name": "OpenAI",
        "icon": "🟢",
        "enabled": False,
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "api_style": "openai",
        "models": [
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
            {"id": "gpt-4o", "name": "GPT-4o"},
            {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini"},
            {"id": "gpt-4.1", "name": "GPT-4.1"},
        ],
    },
    "anthropic": {
        "name": "Anthropic",
        "icon": "🟤",
        "enabled": False,
        "api_key": "",
        "base_url": "https://api.anthropic.com",
        "api_style": "anthropic",
        "models": [
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
            {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku"},
            {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet"},
        ],
    },
    "groq": {
        "name": "Groq",
        "icon": "⚡",
        "enabled": False,
        "api_key": "",
        "base_url": "https://api.groq.com/openai/v1",
        "api_style": "openai",
        "models": [
            {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B"},
            {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B Instant"},
            {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B"},
        ],
    },
    "openrouter": {
        "name": "OpenRouter",
        "icon": "🌐",
        "enabled": False,
        "api_key": "",
        "base_url": "https://openrouter.ai/api/v1",
        "api_style": "openai",
        "models": [
            {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini (via OpenRouter)"},
            {"id": "anthropic/claude-sonnet-4", "name": "Claude Sonnet 4 (via OpenRouter)"},
            {"id": "google/gemini-2.0-flash-001", "name": "Gemini 2.0 Flash"},
        ],
    },
    "mistral": {
        "name": "Mistral",
        "icon": "🌬️",
        "enabled": False,
        "api_key": "",
        "base_url": "https://api.mistral.ai/v1",
        "api_style": "openai",
        "models": [
            {"id": "mistral-small-latest", "name": "Mistral Small"},
            {"id": "mistral-large-latest", "name": "Mistral Large"},
        ],
    },
    "google": {
        "name": "Google Gemini",
        "icon": "🔵",
        "enabled": False,
        "api_key": "",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_style": "openai",
        "models": [
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash"},
            {"id": "gemini-2.0-flash-lite", "name": "Gemini 2.0 Flash Lite"},
        ],
    },
}


def is_cloud_model(model: str | None) -> bool:
    return str(model or "").startswith(CLOUD_PREFIX)


def make_cloud_model_id(provider_id: str, model_id: str) -> str:
    return f"{CLOUD_PREFIX}{provider_id}:{model_id}"


def parse_cloud_model(model: str) -> tuple[str, str]:
    if not is_cloud_model(model):
        raise ValueError(f"Modèle cloud invalide: {model}")
    rest = model[len(CLOUD_PREFIX):]
    if ":" not in rest:
        raise ValueError(f"Format cloud attendu cloud:provider:model — reçu {model}")
    provider_id, model_id = rest.split(":", 1)
    return provider_id, model_id


def _load_config() -> dict:
    try:
        with app_paths.config_path().open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _save_cloud_section(providers: dict) -> None:
    cfg_path = app_paths.config_path()
    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    cfg["cloud_providers"] = providers
    text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
    fd, tmp = tempfile.mkstemp(dir=str(cfg_path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, cfg_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _merge_providers() -> dict[str, dict]:
    cfg = _load_config()
    saved = cfg.get("cloud_providers") or {}
    merged: dict[str, dict] = {}
    for pid, default in DEFAULT_PROVIDERS.items():
        item = dict(default)
        if isinstance(saved.get(pid), dict):
            item.update(saved[pid])
            if saved[pid].get("models"):
                item["models"] = saved[pid]["models"]
        merged[pid] = item
    for pid, data in saved.items():
        if pid not in merged and isinstance(data, dict):
            merged[pid] = data
    return merged


def get_all_providers() -> list[dict]:
    """Liste des providers pour l'UI (clé API masquée)."""
    out = []
    for pid, p in _merge_providers().items():
        key = str(p.get("api_key") or "").strip()
        out.append({
            "id": pid,
            "name": p.get("name", pid),
            "icon": p.get("icon", "☁️"),
            "enabled": bool(p.get("enabled")),
            "has_key": bool(key),
            "key_preview": (key[:4] + "…" + key[-4:]) if len(key) > 10 else ("••••" if key else ""),
            "base_url": p.get("base_url", ""),
            "api_style": p.get("api_style", "openai"),
            "models": p.get("models") or [],
        })
    return out


def get_provider(provider_id: str) -> dict | None:
    return _merge_providers().get(provider_id)


def update_provider(provider_id: str, **kwargs) -> dict:
    providers = _merge_providers()
    if provider_id not in providers and provider_id not in DEFAULT_PROVIDERS:
        raise ValueError(f"Provider '{provider_id}' inconnu")
    base = dict(DEFAULT_PROVIDERS.get(provider_id, {}))
    base.update(providers.get(provider_id, {}))
    if "api_key" in kwargs and kwargs["api_key"] in ("", None):
        kwargs.pop("api_key")
    base.update(kwargs)
    providers[provider_id] = base
    _save_cloud_section(providers)
    return base


def list_available_cloud_models() -> list[dict]:
    """Modèles cloud activés avec clé API configurée."""
    models: list[dict] = []
    for pid, p in _merge_providers().items():
        if not p.get("enabled"):
            continue
        if not str(p.get("api_key") or "").strip():
            continue
        icon = p.get("icon", "☁️")
        pname = p.get("name", pid)
        for m in p.get("models") or []:
            mid = m.get("id") if isinstance(m, dict) else str(m)
            mname = m.get("name", mid) if isinstance(m, dict) else mid
            if not mid:
                continue
            full_id = make_cloud_model_id(pid, mid)
            models.append({
                "id": full_id,
                "provider_id": pid,
                "provider_name": pname,
                "provider_icon": icon,
                "model_id": mid,
                "label": mname,
                "subtitle": f"{icon} {pname}",
            })
    return models


def _resolve_provider(model: str) -> tuple[dict, str]:
    provider_id, model_id = parse_cloud_model(model)
    provider = get_provider(provider_id)
    if not provider:
        raise RuntimeError(f"Provider '{provider_id}' introuvable")
    if not provider.get("enabled"):
        raise RuntimeError(f"Provider '{provider.get('name', provider_id)}' désactivé")
    api_key = str(provider.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError(f"Clé API manquante pour {provider.get('name', provider_id)}")
    return provider, model_id


def _split_messages(messages: list) -> tuple[str, list[dict]]:
    system_parts: list[str] = []
    chat: list[dict] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            if content:
                system_parts.append(str(content))
        elif role in ("user", "assistant"):
            chat.append({"role": role, "content": str(content)})
    return "\n\n".join(system_parts), chat


def _openai_chat(
    provider: dict,
    model_id: str,
    messages: list,
    *,
    stream: bool,
    max_tokens: int,
    temperature: float,
    on_token: Callable[[str], None] | None = None,
) -> str:
    base_url = str(provider.get("base_url", "")).rstrip("/")
    api_key = str(provider.get("api_key", "")).strip()
    endpoint = f"{base_url}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if provider.get("id") == "openrouter" or "openrouter" in base_url:
        headers["HTTP-Referer"] = "https://aria.local"
        headers["X-Title"] = "ARIA Assistant"

    payload = {
        "model": model_id,
        "messages": messages,
        "stream": stream,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    if stream and on_token:
        parts: list[str] = []
        with requests.post(endpoint, headers=headers, json=payload, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8") if isinstance(line, bytes) else line
                if not line_str.startswith("data: "):
                    continue
                data_str = line_str[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    token = data["choices"][0]["delta"].get("content", "") or ""
                    if token:
                        parts.append(token)
                        on_token(token)
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
        return "".join(parts)

    resp = requests.post(
        endpoint,
        headers=headers,
        json={**payload, "stream": False},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _anthropic_chat(
    provider: dict,
    model_id: str,
    messages: list,
    *,
    stream: bool,
    max_tokens: int,
    temperature: float,
    on_token: Callable[[str], None] | None = None,
) -> str:
    base_url = str(provider.get("base_url", "https://api.anthropic.com")).rstrip("/")
    api_key = str(provider.get("api_key", "")).strip()
    endpoint = f"{base_url}/v1/messages"

    system_text, chat = _split_messages(messages)
    if not chat:
        chat = [{"role": "user", "content": ""}]

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_id,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": chat,
    }
    if system_text:
        payload["system"] = system_text

    if stream and on_token:
        payload["stream"] = True
        parts: list[str] = []
        with requests.post(endpoint, headers=headers, json=payload, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8") if isinstance(line, bytes) else line
                if not line_str.startswith("data: "):
                    continue
                try:
                    data = json.loads(line_str[6:])
                    if data.get("type") == "content_block_delta":
                        token = data.get("delta", {}).get("text", "")
                        if token:
                            parts.append(token)
                            on_token(token)
                except json.JSONDecodeError:
                    continue
        return "".join(parts)

    resp = requests.post(endpoint, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    blocks = data.get("content") or []
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


def chat_completion(
    messages: list,
    model: str,
    *,
    stream: bool = False,
    max_tokens: int = 400,
    temperature: float = 0.7,
    on_token: Callable[[str], None] | None = None,
) -> str:
    """Chat multi-messages pour un modèle cloud."""
    provider, model_id = _resolve_provider(model)
    provider = dict(provider)
    provider["id"] = parse_cloud_model(model)[0]

    api_style = provider.get("api_style", "openai")
    logger.info("Cloud LLM: %s / %s (style=%s)", provider.get("name"), model_id, api_style)

    if api_style == "anthropic":
        return _anthropic_chat(
            provider, model_id, messages,
            stream=stream, max_tokens=max_tokens, temperature=temperature, on_token=on_token,
        )
    return _openai_chat(
        provider, model_id, messages,
        stream=stream, max_tokens=max_tokens, temperature=temperature, on_token=on_token,
    )


def generate(
    prompt: str,
    model: str,
    *,
    system: str | None = None,
    stream: bool = True,
    max_tokens: int = 400,
    temperature: float = 0.7,
    on_token: Callable[[str], None] | None = None,
) -> str:
    """Génération simple (prompt + system optionnel)."""
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        return chat_completion(
            messages,
            model,
            stream=stream and on_token is not None,
            max_tokens=max_tokens,
            temperature=temperature,
            on_token=on_token,
        )
    except requests.exceptions.HTTPError as exc:
        resp = exc.response
        if resp is not None:
            try:
                err = resp.json()
                msg = err.get("error", err)
                if isinstance(msg, dict):
                    msg = msg.get("message", str(msg))
            except Exception:
                msg = resp.text or str(exc)
            return f"Erreur API cloud: {msg}"
        return f"Erreur API cloud: {exc}"
    except Exception as exc:
        logger.exception("Cloud LLM error")
        return f"Erreur : {exc}"


def test_provider(provider_id: str) -> dict:
    """Teste la connexion à un provider."""
    provider = get_provider(provider_id)
    if not provider:
        return {"success": False, "error": "Provider inconnu"}
    api_key = str(provider.get("api_key") or "").strip()
    if not api_key:
        return {"success": False, "error": "Clé API non configurée"}

    models = provider.get("models") or []
    if not models:
        return {"success": False, "error": "Aucun modèle configuré"}
    test_model = models[0]["id"] if isinstance(models[0], dict) else str(models[0])
    full_id = make_cloud_model_id(provider_id, test_model)

    try:
        result = generate(
            "Réponds uniquement par le mot OK.",
            full_id,
            stream=False,
            max_tokens=10,
            temperature=0,
        )
        if result.startswith("Erreur"):
            return {"success": False, "error": result}
        return {"success": True, "message": f"Connexion OK — réponse: {result[:80]}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def display_label(model: str) -> str:
    if not is_cloud_model(model):
        return model
    try:
        provider_id, model_id = parse_cloud_model(model)
        provider = get_provider(provider_id) or {}
        for m in provider.get("models") or []:
            if isinstance(m, dict) and m.get("id") == model_id:
                return str(m.get("name", model_id))
        return model_id
    except Exception:
        return model
