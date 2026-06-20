"""
web_research.py — Recherche web avancée multi-sources.
Combine ddgs, scraping léger et APIs publiques pour des résultats riches.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SOURCES = {
    "google": "https://www.google.com/search?q={query}",
    "youtube": "https://www.youtube.com/results?search_query={query}",
    "wikipedia": "https://fr.wikipedia.org/w/index.php?search={query}",
    "reddit": "https://www.reddit.com/search/?q={query}",
    "github": "https://github.com/search?q={query}",
    "stackoverflow": "https://stackoverflow.com/search?q={query}",
    "amazon": "https://www.amazon.fr/s?k={query}",
    "leboncoin": "https://www.leboncoin.fr/recherche?text={query}",
    "meteofrance": "https://meteofrance.com/previsions-meteo-france/{query}",
    "seloger": (
        "https://www.seloger.com/list.htm?ci=&idtt=2&pxmax=&pxmin=&tri=initial"
        "&idtypebien=1,2&naturebien=1,2,4&nMax=20&txt={query}"
    ),
}


def ddg_search(query: str, max_results: int = 8) -> list[dict]:
    """Recherche DuckDuckGo avec fallback robuste."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            logger.error("ddgs non installé")
            return []

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            logger.info("DDG: %d résultats pour '%s'", len(results), query)
            return results
    except Exception as exc:
        logger.error("DDG search error: %s", exc)
        return []


def ddg_news(query: str, max_results: int = 6) -> list[dict]:
    """Actualités DuckDuckGo."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return []

    try:
        with DDGS() as ddgs:
            return list(ddgs.news(query, max_results=max_results, timelimit="w"))
    except Exception as exc:
        logger.error("DDG news error: %s", exc)
        return []


def wikipedia_summary(query: str, lang: str = "fr") -> Optional[str]:
    """Résumé Wikipedia via l'API officielle (gratuite, sans clé)."""
    try:
        url = (
            f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
            f"{urllib.parse.quote(query)}"
        )
        resp = requests.get(url, timeout=5, headers={"User-Agent": "ARIA-Assistant/1.0"})
        if resp.status_code == 200:
            data = resp.json()
            extract = data.get("extract", "")
            if extract:
                logger.info("Wikipedia: résumé trouvé pour '%s'", query)
                return extract[:800]

        search_url = f"https://{lang}.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": 1,
        }
        resp = requests.get(
            search_url,
            params=params,
            timeout=5,
            headers={"User-Agent": "ARIA-Assistant/1.0"},
        )
        if resp.status_code == 200:
            results = resp.json().get("query", {}).get("search", [])
            if results:
                title = results[0]["title"]
                if title.lower() != query.lower():
                    return wikipedia_summary(title, lang)
    except Exception as exc:
        logger.debug("Wikipedia error: %s", exc)
    return None


def youtube_search(query: str, max_results: int = 5) -> list[dict]:
    """Recherche YouTube via DDG (pas de clé API nécessaire)."""
    results = ddg_search(f"site:youtube.com {query}", max_results=max_results)
    videos = []
    for item in results:
        href = item.get("href", "")
        if "youtube.com/watch" in href:
            videos.append(
                {
                    "title": item.get("title", ""),
                    "url": href,
                    "description": item.get("body", "")[:200],
                }
            )
    return videos


def multi_search(
    query: str,
    sources: list[str] | None = None,
    max_per_source: int = 5,
) -> dict[str, list[dict]]:
    """
    Effectue une recherche sur plusieurs sources simultanément.

    Args:
        query: La requête de recherche
        sources: Liste de sources ('web', 'news', 'wikipedia', 'youtube')
                 Si None, utilise ['web', 'wikipedia']
        max_per_source: Nombre max de résultats par source

    Returns:
        Dict {source: [résultats]}
    """
    if sources is None:
        sources = ["web", "wikipedia"]

    import concurrent.futures

    results: dict[str, list] = {}

    def fetch_source(source: str) -> tuple[str, list]:
        try:
            if source == "web":
                return source, ddg_search(query, max_results=max_per_source)
            if source == "news":
                return source, ddg_news(query, max_results=max_per_source)
            if source == "wikipedia":
                summary = wikipedia_summary(query)
                return source, [{"summary": summary}] if summary else []
            if source == "youtube":
                return source, youtube_search(query, max_results=max_per_source)
            return source, ddg_search(
                f"site:{source} {query}", max_results=max_per_source
            )
        except Exception as exc:
            logger.error("Erreur source %s: %s", source, exc)
            return source, []

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_source, source): source for source in sources}
        for future in concurrent.futures.as_completed(futures, timeout=15):
            try:
                source, data = future.result()
                if data:
                    results[source] = data
            except Exception as exc:
                logger.error("Future error: %s", exc)

    logger.info(
        "multi_search: %d sources, %d résultats total",
        len(results),
        sum(len(value) for value in results.values()),
    )
    return results


def format_results_for_llm(results: dict, query: str) -> str:
    """Formate les résultats multi-sources pour les passer au LLM."""
    sections = [f"Résultats de recherche pour : '{query}'\n"]

    if "wikipedia" in results:
        for item in results["wikipedia"]:
            if item.get("summary"):
                sections.append(f"=== WIKIPEDIA ===\n{item['summary']}\n")

    if "news" in results:
        sections.append("=== ACTUALITÉS ===")
        for item in results["news"][:4]:
            sections.append(f"- {item.get('title', '')}: {item.get('body', '')[:150]}")
        sections.append("")

    if "web" in results:
        sections.append("=== WEB ===")
        for item in results["web"][:5]:
            sections.append(f"- {item.get('title', '')}: {item.get('body', '')[:150]}")
        sections.append("")

    if "youtube" in results:
        sections.append("=== YOUTUBE ===")
        for item in results["youtube"][:3]:
            sections.append(f"- {item.get('title', '')} — {item.get('url', '')}")
        sections.append("")

    return "\n".join(sections)


def format_results_for_doc(results: dict, query: str) -> str:
    """Formate les résultats en texte structuré pour Google Docs."""
    import datetime

    lines = [
        f"Recherche ARIA — {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}",
        f"Requête : {query}",
        "=" * 60,
        "",
    ]

    if "wikipedia" in results:
        lines.append("WIKIPEDIA")
        lines.append("-" * 40)
        for item in results["wikipedia"]:
            if item.get("summary"):
                lines.append(item["summary"])
        lines.append("")

    if "news" in results:
        lines.append("ACTUALITÉS")
        lines.append("-" * 40)
        for item in results["news"]:
            lines.append(f"• {item.get('title', '')}")
            lines.append(f"  {item.get('body', '')[:300]}")
            if item.get("url"):
                lines.append(f"  Source: {item.get('url', '')}")
            lines.append("")

    if "web" in results:
        lines.append("RÉSULTATS WEB")
        lines.append("-" * 40)
        for item in results["web"]:
            lines.append(f"• {item.get('title', '')}")
            lines.append(f"  {item.get('body', '')[:300]}")
            if item.get("href"):
                lines.append(f"  URL: {item.get('href', '')}")
            lines.append("")

    if "youtube" in results:
        lines.append("VIDÉOS YOUTUBE")
        lines.append("-" * 40)
        for item in results["youtube"]:
            lines.append(f"• {item.get('title', '')}")
            lines.append(f"  {item.get('url', '')}")
            lines.append("")

    return "\n".join(lines)
