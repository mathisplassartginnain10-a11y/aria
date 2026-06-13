"""Recherche web via DuckDuckGo (sans clé API)."""

import logging
import webbrowser

from actions.web_search import search_web, summarize_with_ollama

logger = logging.getLogger(__name__)


def search(query: str, n: int = 3) -> list[dict]:
    try:
        results = search_web(query, max_results=n)
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("href", r.get("url", "")),
                "description": r.get("body", r.get("snippet", "")),
            }
            for r in results
        ]
    except Exception:
        logger.exception("DuckDuckGo search failed")
        return [{"title": "Recherche web indisponible.", "url": "", "description": ""}]


def summarize_results(results: list[dict]) -> str:
    if not results or "indisponible" in results[0].get("title", "").lower():
        return results[0]["title"] if results else "Aucun résultat."

    articles = [
        {"title": r.get("title", ""), "body": r.get("description", "")}
        for r in results
        if r.get("title")
    ]
    return summarize_with_ollama(articles, context="recherche web")


def open_in_browser(url: str) -> str:
    if not url:
        return "Pas d'URL à ouvrir."
    webbrowser.open(url)
    return "Page ouverte dans le navigateur."
