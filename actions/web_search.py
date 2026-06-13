import logging
import re
import webbrowser
from pathlib import Path

import requests
import yaml
from duckduckgo_search import DDGS

import app_paths

logger = logging.getLogger(__name__)

_CONFIG_PATH = app_paths.config_path()
_PROMPTS_DIR = app_paths.prompts_dir()

with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

MODEL = _config.get("model", "qwen3:14b")
SEARCH_MAX_RESULTS = int(_config.get("search_max_results", 5))
SEARCH_NEWS_TOPICS = _config.get("search_news_topics", [
    "géopolitique mondiale",
    "conflits internationaux",
    "diplomatie",
    "aviation civile",
    "technologie aérospatiale",
    "intelligence artificielle",
])
OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"

GEOPOLITICS_PROMPT = (_PROMPTS_DIR / "geopolitics_system.txt").read_text(encoding="utf-8")


def search_web(query: str, max_results: int = 5) -> list[dict]:
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        logger.error("DDG error: %s", e)
        return []


def search_news(query: str, max_results: int = 5, timelimit: str = "d") -> list[dict]:
    try:
        with DDGS() as ddgs:
            return list(ddgs.news(query, max_results=max_results, timelimit=timelimit))
    except Exception as e:
        logger.error("DDG error: %s", e)
        return []


def summarize_with_ollama(results: list[dict], context: str = "") -> str:
    if not results:
        return "Aucun résultat trouvé."
    content = "\n\n".join(
        [
            f"- {r.get('title', '')}: {r.get('body', r.get('snippet', ''))}"
            for r in results[:5]
        ]
    )
    prompt = f"Résume ces résultats de recherche en français de façon détaillée ({context}):\n\n{content}"
    try:
        resp = requests.post(
            OLLAMA_GENERATE_URL,
            json={"model": MODEL, "prompt": prompt, "stream": False},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("response", content).strip()
    except Exception:
        logger.exception("Ollama summarize failed")
        return content


def summarize_results_with_ollama(articles: list[dict], system_prompt: str | None = None) -> str:
    context = system_prompt or GEOPOLITICS_PROMPT
    label = "géopolitique et actualités"
    if system_prompt and len(system_prompt) < 120:
        label = system_prompt
    return summarize_with_ollama(articles, label)


def extract_query(text: str) -> str:
    return _extract_query(text)


def _extract_query(text: str) -> str:
    query = text.strip()
    for prefix in (
        r"^cherche(?:-moi)?\s+",
        r"^recherche(?:-moi)?\s+",
        r"^search\s+",
        r"^sur internet\s+",
        r"^les dernières nouvelles sur\s+",
        r"^les dernières actualités sur\s+",
        r"^les actualités sur\s+",
        r"^actualités sur\s+",
        r"^nouvelles sur\s+",
        r"^la dernière actu sur\s+",
        r"^la dernière actualité sur\s+",
    ):
        query = re.sub(prefix, "", query, flags=re.I).strip()
    return query or text.strip()


def _is_news_query(text: str) -> bool:
    t = text.lower()
    return any(
        kw in t
        for kw in ("nouvelles", "actualité", "actualites", "actu", "news", "briefing")
    )


def search_aviation_news() -> str:
    queries = [
        "aviation civile actualités",
        "DGAC nouvelles réglementation",
        "accident aérien dernières 24h",
    ]
    all_articles: list[dict] = []
    for q in queries:
        all_articles.extend(search_news(q, max_results=2, timelimit="d"))
    if not all_articles:
        return "Pas d'actualités aviation trouvées pour les dernières 24 heures."
    return summarize_with_ollama(all_articles[:SEARCH_MAX_RESULTS], "actualités aviation")


def search_geopolitics() -> str:
    queries = [
        "géopolitique internationale",
        "conflits monde actualités",
        "diplomatie actualités",
    ]
    all_articles: list[dict] = []
    for q in queries:
        all_articles.extend(search_news(q, max_results=3, timelimit="w"))
    if not all_articles:
        for topic in SEARCH_NEWS_TOPICS[:3]:
            all_articles.extend(search_news(topic, max_results=2, timelimit="w"))
    if not all_articles:
        return "Pas d'actualités géopolitiques trouvées."
    return summarize_with_ollama(all_articles[:SEARCH_MAX_RESULTS], "géopolitique internationale")


def open_article(url: str) -> str:
    if not url:
        return "Pas d'URL fournie."
    webbrowser.open(url)
    return "Article ouvert dans le navigateur."


def morning_news_briefing() -> str:
    geo = search_news("géopolitique internationale actualités", max_results=3, timelimit="d")
    avia = search_news("aviation civile actualités", max_results=2, timelimit="w")
    tech = search_news("intelligence artificielle actualités", max_results=2, timelimit="d")

    all_articles = geo + avia + tech
    if not all_articles:
        return "Briefing actualités indisponible pour le moment."

    summary = summarize_with_ollama(all_articles, "briefing actualités du jour")
    return f"Briefing du jour. {summary}"


def handle(text: str) -> str:
    t = text.lower()
    if "géopolitique" in t or "geopolitique" in t:
        return search_geopolitics()
    if "aviation" in t and ("actu" in t or "nouvelles" in t or "news" in t):
        return search_aviation_news()
    if "briefing" in t and "actu" in t:
        return morning_news_briefing()
    if "ouvre" in t and "article" in t:
        articles = search_web(text, max_results=1)
        if articles and articles[0].get("url"):
            return open_article(articles[0]["url"])
        return "Aucun article à ouvrir."

    query = _extract_query(text)
    if _is_news_query(text) or "intelligence artificielle" in t:
        results = search_news(query, max_results=SEARCH_MAX_RESULTS, timelimit="d")
        if results:
            return summarize_with_ollama(results, f"actualités : {query}")
        results = search_web(query, max_results=SEARCH_MAX_RESULTS)
        if results:
            return summarize_with_ollama(results, query)
        return f"Aucun résultat pour : {query}"

    results = search_web(query, max_results=SEARCH_MAX_RESULTS)
    if not results:
        results = search_news(query, max_results=SEARCH_MAX_RESULTS, timelimit="w")
    if not results:
        return f"Aucun résultat pour : {query}"
    return summarize_with_ollama(results, query)
