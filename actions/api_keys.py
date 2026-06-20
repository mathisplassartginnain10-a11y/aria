"""
api_keys.py — Gestion des clés API pour les IAs externes.
Les clés sont stockées dans config.yaml avec obfuscation base64 locale.
"""
from __future__ import annotations

import base64
import json
import logging

import requests
import yaml

import app_paths

logger = logging.getLogger(__name__)

PROVIDERS = {
    "openai": {
        "name": "OpenAI",
        "icon": "🟢",
        "url": "https://platform.openai.com/api-keys",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1-mini"],
        "base_url": "https://api.openai.com/v1",
    },
    "anthropic": {
        "name": "Anthropic",
        "icon": "🟠",
        "url": "https://console.anthropic.com/keys",
        "models": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        "base_url": "https://api.anthropic.com/v1",
    },
    "mistral": {
        "name": "Mistral AI",
        "icon": "🔵",
        "url": "https://console.mistral.ai/api-keys",
        "models": ["mistral-large-latest", "mistral-small-latest", "codestral-latest"],
        "base_url": "https://api.mistral.ai/v1",
    },
    "groq": {
        "name": "Groq",
        "icon": "⚡",
        "url": "https://console.groq.com/keys",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "base_url": "https://api.groq.com/openai/v1",
    },
    "gemini": {
        "name": "Google Gemini",
        "icon": "💎",
        "url": "https://aistudio.google.com/app/apikey",
        "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
    },
}


def _obfuscate(key: str) -> str:
    if not key:
        return ""
    return base64.b64encode(key.encode()).decode()


def _deobfuscate(key: str) -> str:
    if not key:
        return ""
    try:
        return base64.b64decode(key.encode()).decode()
    except Exception:
        return key


def _load_cfg() -> dict:
    with app_paths.config_path().open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_cfg(cfg: dict) -> None:
    with app_paths.config_path().open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def get_key(provider: str) -> str:
    cfg = _load_cfg()
    raw = cfg.get("api_keys", {}).get(provider, {}).get("key", "")
    return _deobfuscate(raw)


def set_key(provider: str, key: str) -> None:
    cfg = _load_cfg()
    cfg.setdefault("api_keys", {}).setdefault(provider, {})
    cfg["api_keys"][provider]["key"] = _obfuscate(key)
    cfg["api_keys"][provider]["enabled"] = bool(key)
    _save_cfg(cfg)
    logger.info("Clé API %s %s", provider, "configurée" if key else "supprimée")


def is_enabled(provider: str) -> bool:
    cfg = _load_cfg()
    entry = cfg.get("api_keys", {}).get(provider, {})
    return bool(entry.get("enabled")) and bool(_deobfuscate(entry.get("key", "")))


def get_default_model(provider: str) -> str:
    cfg = _load_cfg()
    return cfg.get("api_keys", {}).get(provider, {}).get(
        "default_model",
        PROVIDERS.get(provider, {}).get("models", [""])[0],
    )


def set_default_model(provider: str, model: str) -> None:
    cfg = _load_cfg()
    cfg.setdefault("api_keys", {}).setdefault(provider, {})["default_model"] = model
    _save_cfg(cfg)


def check_status(provider: str) -> dict:
    key = get_key(provider)
    if not key:
        return {"status": "not_configured", "message": "Clé non configurée"}
    if provider == "openai" and not key.startswith("sk-"):
        return {"status": "invalid", "message": "Format invalide (doit commencer par sk-)"}
    if provider == "anthropic" and not key.startswith("sk-ant-"):
        return {"status": "invalid", "message": "Format invalide (doit commencer par sk-ant-)"}
    return {"status": "ok", "message": "Clé configurée"}


def get_all_status() -> dict:
    return {
        provider: {
            **check_status(provider),
            "name": info["name"],
            "icon": info["icon"],
            "models": info["models"],
            "url": info["url"],
            "enabled": is_enabled(provider),
            "default_model": get_default_model(provider),
            "has_key": bool(get_key(provider)),
        }
        for provider, info in PROVIDERS.items()
    }


def generate_with_api(
    prompt: str,
    provider: str,
    model: str | None = None,
    system: str | None = None,
    max_tokens: int = 500,
    temperature: float = 0.7,
    stream: bool = False,
    on_token=None,
) -> str:
    key = get_key(provider)
    if not key:
        return f"Erreur : clé API {provider} non configurée."

    model = model or get_default_model(provider)
    info = PROVIDERS.get(provider, {})
    base_url = info.get("base_url", "")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    headers = {"Content-Type": "application/json"}
    if provider == "anthropic":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {key}"

    if provider == "anthropic":
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [m for m in messages if m["role"] != "system"],
        }
        if system:
            payload["system"] = system
        endpoint = f"{base_url}/messages"
    elif provider == "gemini":
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
        }
        endpoint = f"{base_url}/models/{model}:generateContent?key={key}"
        headers.pop("Authorization", None)
    else:
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        endpoint = f"{base_url}/chat/completions"

    logger.info("API %s → %s (model=%s)", provider, endpoint, model)

    try:
        if stream and on_token and provider not in ("anthropic", "gemini"):
            full = []
            with requests.post(
                endpoint, json=payload, headers=headers, stream=True, timeout=60
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    s = line.decode() if isinstance(line, bytes) else line
                    if s.startswith("data: "):
                        s = s[6:]
                        if s == "[DONE]":
                            break
                        try:
                            token = json.loads(s)["choices"][0]["delta"].get("content", "")
                            if token:
                                full.append(token)
                                on_token(token)
                        except Exception:
                            continue
            return "".join(full)

        resp = requests.post(
            endpoint,
            json={**payload, "stream": False},
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        if provider == "anthropic":
            return data["content"][0]["text"]
        if provider == "gemini":
            return data["candidates"][0]["content"]["parts"][0]["text"]
        return data["choices"][0]["message"]["content"].strip()
    except requests.exceptions.HTTPError as e:
        try:
            err = e.response.json()
            msg = err.get("error", {}).get("message", str(e))
        except Exception:
            msg = str(e)
        logger.error("Erreur API %s: %s", provider, msg)
        return f"Erreur API {provider}: {msg}"
    except Exception as e:
        logger.error("Erreur API %s: %s", provider, e)
        return f"Erreur: {e}"
