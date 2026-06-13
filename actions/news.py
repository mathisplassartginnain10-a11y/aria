import logging
import time
from pathlib import Path

import requests
import yaml
import app_paths

logger = logging.getLogger(__name__)

_CONFIG_PATH = app_paths.config_path()
with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

API_KEY = _config.get("newsapi_key", "")
CACHE: dict[str, tuple[float, list]] = {}
CACHE_TTL = 900


def _fetch(url: str) -> dict | None:
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        logger.exception("News API request failed")
        return None


def get_top_headlines(category: str = "general", country: str = "fr", n: int = 5) -> list[dict]:
    cache_key = f"{category}:{country}:{n}"
    if cache_key in CACHE and time.time() - CACHE[cache_key][0] < CACHE_TTL:
        return CACHE[cache_key][1]

    if not API_KEY:
        return [{"title": "Clé API NewsAPI non configurée.", "description": ""}]

    url = (
        f"https://newsapi.org/v2/top-headlines"
        f"?country={country}&category={category}&pageSize={n}&apiKey={API_KEY}"
    )
    data = _fetch(url)
    if data is None:
        return [{"title": "Actualités indisponibles.", "description": ""}]

    articles = [
        {"title": a.get("title", ""), "description": a.get("description", "") or ""}
        for a in data.get("articles", [])[:n]
    ]
    CACHE[cache_key] = (time.time(), articles)
    return articles


def get_by_topic(topic: str, n: int = 3) -> list[dict]:
    if not API_KEY:
        return [{"title": "Clé API NewsAPI non configurée.", "description": ""}]

    url = f"https://newsapi.org/v2/everything?q={topic}&pageSize={n}&language=fr&apiKey={API_KEY}"
    data = _fetch(url)
    if data is None:
        return [{"title": "Recherche d'actualités échouée.", "description": ""}]

    return [
        {"title": a.get("title", ""), "description": a.get("description", "") or ""}
        for a in data.get("articles", [])[:n]
    ]


def format_briefing(articles: list[dict]) -> str:
    if not articles:
        return "Pas d'actualités disponibles."
    parts = []
    for i, article in enumerate(articles, 1):
        title = article.get("title", "")
        desc = article.get("description", "")
        if desc:
            parts.append(f"{i}. {title}. {desc}")
        else:
            parts.append(f"{i}. {title}")
    return " ".join(parts)


def morning_briefing() -> str:
    general = get_top_headlines("general", n=5)
    tech = get_top_headlines("technology", n=2)
    return format_briefing(general[:3] + tech)