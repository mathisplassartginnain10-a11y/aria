"""
web_research.py — Système de recherche web avancé pour ARIA.
Sources : DuckDuckGo, Wikipedia, Reddit, YouTube, Hacker News, NewsAPI.
Recherche parallèle, déduplication, scoring par pertinence, cache 10min.
"""

from __future__ import annotations

import hashlib
import logging
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── Cache en mémoire (10 minutes) ────────────────────────────────────────────
_cache: dict = {}
CACHE_TTL = 600  # 10 minutes


def _cache_key(query: str, source: str) -> str:
    return hashlib.md5(f"{source}:{query.lower().strip()}".encode()).hexdigest()


def _cache_get(key: str) -> Optional[list]:
    entry = _cache.get(key)
    if entry and __import__("time").time() - entry["ts"] < CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(key: str, data: list) -> None:
    import time

    _cache[key] = {"ts": time.time(), "data": data}


def clear_cache() -> None:
    """Vide le cache de recherche."""
    global _cache
    _cache = {}
    logger.info("Cache recherche vidé")


def _get_ddgs():
    try:
        from ddgs import DDGS

        return DDGS
    except ImportError:
        from duckduckgo_search import DDGS

        return DDGS


# ── Sources de recherche ──────────────────────────────────────────────────────

def _search_duckduckgo(query: str, max_results: int = 8) -> list[dict]:
    """Recherche DuckDuckGo — résultats web généraux."""
    key = _cache_key(query, "ddg")
    cached = _cache_get(key)
    if cached:
        return cached
    try:
        DDGS = _get_ddgs()
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results, region="fr-fr"))
        formatted = [
            {
                "source": "web",
                "title": r.get("title", ""),
                "snippet": r.get("body", ""),
                "url": r.get("href", ""),
                "score": 1.0,
            }
            for r in results
            if r.get("body")
        ]
        _cache_set(key, formatted)
        return formatted
    except Exception as e:
        logger.warning("DDG web search error: %s", e)
        return []


def _search_duckduckgo_news(
    query: str, max_results: int = 5, timelimit: str = "w"
) -> list[dict]:
    """Recherche DuckDuckGo News — actualités récentes."""
    key = _cache_key(query, f"ddg_news_{timelimit}")
    cached = _cache_get(key)
    if cached:
        return cached
    try:
        DDGS = _get_ddgs()
        with DDGS() as ddgs:
            results = list(
                ddgs.news(query, max_results=max_results, region="fr-fr", timelimit=timelimit)
            )
        formatted = [
            {
                "source": "news",
                "title": r.get("title", ""),
                "snippet": r.get("body", "") or r.get("excerpt", ""),
                "url": r.get("url", ""),
                "date": r.get("date", ""),
                "score": 1.2,
            }
            for r in results
            if r.get("title")
        ]
        _cache_set(key, formatted)
        return formatted
    except Exception as e:
        logger.warning("DDG news error: %s", e)
        return []


def _search_wikipedia(query: str, lang: str = "fr") -> list[dict]:
    """Recherche Wikipedia — résumés encyclopédiques."""
    key = _cache_key(query, f"wiki_{lang}")
    cached = _cache_get(key)
    if cached:
        return cached
    try:
        search_url = f"https://{lang}.wikipedia.org/w/api.php"
        search_resp = requests.get(
            search_url,
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": 3,
                "format": "json",
                "srprop": "snippet|titlesnippet",
            },
            timeout=5,
            headers={"User-Agent": "ARIA-Assistant/1.0"},
        )
        search_data = search_resp.json()
        results = []
        for item in search_data.get("query", {}).get("search", []):
            title = item.get("title", "")
            extract_resp = requests.get(
                search_url,
                params={
                    "action": "query",
                    "titles": title,
                    "prop": "extracts",
                    "exintro": True,
                    "explaintext": True,
                    "format": "json",
                    "exsentences": 5,
                },
                timeout=5,
                headers={"User-Agent": "ARIA-Assistant/1.0"},
            )
            extract_data = extract_resp.json()
            pages = extract_data.get("query", {}).get("pages", {})
            for page in pages.values():
                extract = page.get("extract", "")
                if extract and len(extract) > 50:
                    results.append(
                        {
                            "source": "wikipedia",
                            "title": title,
                            "snippet": extract[:600],
                            "url": f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}",
                            "score": 1.5,
                        }
                    )
        _cache_set(key, results)
        return results
    except Exception as e:
        logger.warning("Wikipedia error: %s", e)
        return []


def _search_youtube(query: str, max_results: int = 3) -> list[dict]:
    """Recherche YouTube via DDG."""
    key = _cache_key(query, "youtube")
    cached = _cache_get(key)
    if cached:
        return cached
    try:
        DDGS = _get_ddgs()
        with DDGS() as ddgs:
            results = list(
                ddgs.text(f"site:youtube.com {query}", max_results=max_results)
            )
        formatted = [
            {
                "source": "youtube",
                "title": r.get("title", "").replace("- YouTube", "").strip(),
                "snippet": r.get("body", ""),
                "url": r.get("href", ""),
                "score": 0.8,
            }
            for r in results
            if "youtube.com/watch" in r.get("href", "")
        ]
        _cache_set(key, formatted)
        return formatted
    except Exception as e:
        logger.warning("YouTube search error: %s", e)
        return []


def _search_reddit(query: str, max_results: int = 4) -> list[dict]:
    """Recherche Reddit — opinions et discussions."""
    key = _cache_key(query, "reddit")
    cached = _cache_get(key)
    if cached:
        return cached
    try:
        DDGS = _get_ddgs()
        with DDGS() as ddgs:
            results = list(
                ddgs.text(f"site:reddit.com {query}", max_results=max_results)
            )
        formatted = [
            {
                "source": "reddit",
                "title": r.get("title", ""),
                "snippet": r.get("body", ""),
                "url": r.get("href", ""),
                "score": 0.9,
            }
            for r in results
            if r.get("body")
        ]
        _cache_set(key, formatted)
        return formatted
    except Exception as e:
        logger.warning("Reddit search error: %s", e)
        return []


def _search_hackernews(query: str, max_results: int = 4) -> list[dict]:
    """Recherche Hacker News via DDG."""
    key = _cache_key(query, "hackernews")
    cached = _cache_get(key)
    if cached:
        return cached
    try:
        DDGS = _get_ddgs()
        with DDGS() as ddgs:
            results = list(
                ddgs.text(
                    f"site:news.ycombinator.com {query}", max_results=max_results
                )
            )
        formatted = [
            {
                "source": "hackernews",
                "title": r.get("title", ""),
                "snippet": r.get("body", ""),
                "url": r.get("href", ""),
                "score": 0.85,
            }
            for r in results
            if r.get("body")
        ]
        _cache_set(key, formatted)
        return formatted
    except Exception as e:
        logger.warning("Hacker News search error: %s", e)
        return []


def _search_newsapi(query: str, max_results: int = 5) -> list[dict]:
    """Actualités via NewsAPI (si clé configurée)."""
    key = _cache_key(query, "newsapi")
    cached = _cache_get(key)
    if cached:
        return cached
    try:
        import api_keys

        api_key = api_keys.get_key("newsapi")
        if not api_key:
            return []
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "pageSize": max_results,
                "language": "fr",
                "sortBy": "publishedAt",
                "apiKey": api_key,
            },
            timeout=6,
        )
        if resp.status_code != 200:
            return []
        articles = resp.json().get("articles", [])
        formatted = [
            {
                "source": "news",
                "title": a.get("title", ""),
                "snippet": a.get("description", "") or "",
                "url": a.get("url", ""),
                "date": a.get("publishedAt", ""),
                "score": 1.3,
            }
            for a in articles
            if a.get("title")
        ]
        _cache_set(key, formatted)
        return formatted
    except Exception as e:
        logger.warning("NewsAPI error: %s", e)
        return []


def _fetch_page_content(url: str, max_chars: int = 1500) -> str:
    """Récupère le contenu textuel d'une page web pour enrichir les snippets courts."""
    try:
        from html.parser import HTMLParser

        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text: list[str] = []
                self._skip = False

            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style", "nav", "header", "footer"):
                    self._skip = True

            def handle_endtag(self, tag):
                if tag in ("script", "style", "nav", "header", "footer"):
                    self._skip = False

            def handle_data(self, data):
                if not self._skip:
                    stripped = data.strip()
                    if len(stripped) > 20:
                        self.text.append(stripped)

        resp = requests.get(
            url,
            timeout=6,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                )
            },
        )
        parser = TextExtractor()
        parser.feed(resp.text)
        full_text = " ".join(parser.text)
        return full_text[:max_chars]
    except Exception:
        return ""


# ── Score de pertinence ───────────────────────────────────────────────────────

def _score_result(result: dict, query: str) -> float:
    """Score un résultat selon sa pertinence par rapport à la requête."""
    score = result.get("score", 1.0)
    query_words = set(query.lower().split())
    text = (result.get("title", "") + " " + result.get("snippet", "")).lower()

    matches = sum(1 for w in query_words if w in text and len(w) > 3)
    score += matches * 0.15

    snippet_len = len(result.get("snippet", ""))
    if snippet_len > 200:
        score += 0.2
    if snippet_len > 400:
        score += 0.1
    if result.get("source") == "wikipedia":
        score += 0.3
    if snippet_len < 50:
        score -= 0.5

    return score


def _deduplicate(results: list[dict]) -> list[dict]:
    """Supprime les doublons par URL et par similarité de titre."""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[dict] = []
    for r in results:
        url = r.get("url", "")
        title = r.get("title", "").lower()[:50]
        if url in seen_urls or title in seen_titles:
            continue
        seen_urls.add(url)
        seen_titles.add(title)
        unique.append(r)
    return unique


def _source_fetchers() -> dict[str, callable]:
    return {
        "web": lambda q, n, **kw: _search_duckduckgo(q, n),
        "news": lambda q, n, **kw: _search_duckduckgo_news(
            q, n, timelimit=kw.get("news_timelimit") or "w"
        ),
        "wikipedia": lambda q, n, **kw: _search_wikipedia(q),
        "youtube": lambda q, n, **kw: _search_youtube(q, n),
        "reddit": lambda q, n, **kw: _search_reddit(q, n),
        "hackernews": lambda q, n, **kw: _search_hackernews(q, n),
        "newsapi": lambda q, n, **kw: _search_newsapi(q, n),
    }


def _collect_results(
    query: str,
    sources: list[str],
    max_per_source: int = 8,
    *,
    include_page_content: bool = False,
    timeout: float = 8.0,
    news_timelimit: str | None = None,
) -> list[dict]:
    """Recherche parallèle multi-sources — retourne une liste normalisée."""
    fetchers = _source_fetchers()
    all_results: list[dict] = []

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(
                fetchers[src], query, max_per_source, news_timelimit=news_timelimit
            ): src
            for src in sources
            if src in fetchers
        }
        try:
            completed = as_completed(futures, timeout=timeout)
            for future in completed:
                src = futures[future]
                try:
                    results = future.result(timeout=2)
                    all_results.extend(results)
                    logger.debug("Source %s: %d résultats", src, len(results))
                except Exception as e:
                    logger.warning("Source %s échouée: %s", src, e)
        except Exception as e:
            logger.warning("Recherche parallèle timeout/partielle: %s", e)

    if include_page_content:
        with ThreadPoolExecutor(max_workers=3) as executor:
            enrich_futures = []
            for r in all_results:
                if len(r.get("snippet", "")) < 150 and r.get("url"):
                    enrich_futures.append(
                        (r, executor.submit(_fetch_page_content, r["url"]))
                    )
            for r, future in enrich_futures:
                try:
                    content = future.result(timeout=5)
                    if content:
                        r["snippet"] = content
                except Exception:
                    pass

    for r in all_results:
        r["_score"] = _score_result(r, query)
    all_results = _deduplicate(all_results)
    all_results.sort(key=lambda x: x["_score"], reverse=True)
    return all_results


def _format_results_text(top: list[dict]) -> str:
    """Formate une liste de résultats normalisés pour le LLM."""
    sections: list[str] = []
    by_source: dict[str, list[dict]] = {}
    for r in top:
        by_source.setdefault(r.get("source", "web"), []).append(r)

    if "wikipedia" in by_source:
        sections.append("=== WIKIPEDIA ===")
        for r in by_source["wikipedia"]:
            sections.append(f"Titre: {r['title']}\n{r['snippet']}\nURL: {r['url']}")

    if "news" in by_source:
        sections.append("=== ACTUALITÉS ===")
        for r in by_source["news"]:
            date_str = f" ({r.get('date', '')})" if r.get("date") else ""
            sections.append(
                f"Titre: {r['title']}{date_str}\n{r['snippet']}\nURL: {r['url']}"
            )

    if "web" in by_source:
        sections.append("=== WEB ===")
        for r in by_source["web"]:
            sections.append(f"Titre: {r['title']}\n{r['snippet']}\nURL: {r['url']}")

    if "youtube" in by_source:
        sections.append("=== YOUTUBE ===")
        for r in by_source["youtube"]:
            sections.append(f"Vidéo: {r['title']}\nURL: {r['url']}")

    if "reddit" in by_source:
        sections.append("=== REDDIT ===")
        for r in by_source["reddit"]:
            sections.append(
                f"Discussion: {r['title']}\n{r['snippet']}\nURL: {r['url']}"
            )

    if "hackernews" in by_source:
        sections.append("=== HACKER NEWS ===")
        for r in by_source["hackernews"]:
            sections.append(f"{r['title']}\n{r['snippet']}\nURL: {r['url']}")

    return "\n\n".join(sections)


def _results_to_legacy_dict(results: list[dict]) -> dict[str, list[dict]]:
    """Convertit les résultats normalisés au format dict legacy (multi_search)."""
    legacy: dict[str, list[dict]] = {}
    for r in results:
        src = r.get("source", "web")
        bucket = src if src in ("web", "news", "wikipedia", "youtube", "reddit") else "web"
        if src == "wikipedia":
            item = {"summary": r.get("snippet", ""), "title": r.get("title", "")}
        elif src == "youtube":
            item = {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("snippet", ""),
            }
        elif src == "news":
            item = {
                "title": r.get("title", ""),
                "body": r.get("snippet", ""),
                "url": r.get("url", ""),
                "date": r.get("date", ""),
            }
        else:
            item = {
                "title": r.get("title", ""),
                "body": r.get("snippet", ""),
                "href": r.get("url", ""),
            }
        legacy.setdefault(bucket, []).append(item)
    return legacy


# ── Interfaces publiques ──────────────────────────────────────────────────────

def search_simple(query: str, max_results: int = 5) -> str:
    """Recherche rapide — DDG uniquement, retourne texte brut."""
    results = _search_duckduckgo(query, max_results)
    if not results:
        return f"Aucun résultat trouvé pour '{query}'."
    parts = []
    for r in results[:max_results]:
        parts.append(f"**{r['title']}**\n{r['snippet']}\n{r['url']}")
    return "\n\n".join(parts)


def search_multi(
    query: str,
    max_results: int = 10,
    sources: list[str] | None = None,
    include_page_content: bool = False,
    timeout: float = 8.0,
    *,
    news_timelimit: str | None = None,
) -> str:
    """
    Recherche multi-sources parallèle avec scoring et déduplication.
    Sources : web, news, wikipedia, youtube, reddit, hackernews, newsapi.
    Retourne un texte structuré prêt pour le LLM.
    """
    if sources is None:
        sources = ["web", "news", "wikipedia"]

    if "news" in sources and "newsapi" not in sources:
        sources = list(sources) + ["newsapi"]

    all_results = _collect_results(
        query,
        sources,
        max_per_source=max_results,
        include_page_content=include_page_content,
        timeout=timeout,
        news_timelimit=news_timelimit,
    )
    top = all_results[:max_results]

    if not top:
        return f"Aucun résultat trouvé pour '{query}'."

    return _format_results_text(top)


def search_and_synthesize(
    query: str,
    output_format: str = "chat",
    sources: list[str] | None = None,
    max_results: int = 8,
) -> str:
    """
    Recherche multi-sources + synthèse LLM fast.
    output_format: 'chat' ou 'doc' (structuré pour Google Doc).
    """
    import llm as _llm

    if sources is None:
        sources = ["web", "news", "wikipedia"]

    raw = search_multi(query, max_results=max_results, sources=sources)

    if output_format == "doc":
        prompt = f"""Tu es ARIA. Structure ces résultats de recherche sur "{query}" pour un Google Doc.
Format markdown avec ## pour les titres. Sois factuel et complet. Maximum 500 mots.
Inclure toujours une section ## Sources avec les URLs.

RÉSULTATS:
{raw[:3000]}"""
        max_tokens = 600
    else:
        prompt = f"""Tu es ARIA, assistant français. Réponds à "{query}" en synthétisant ces résultats.
Sois concis, factuel, en français. Maximum 200 mots.
Cite 2-3 sources pertinentes à la fin avec leurs URLs.
Format: réponse naturelle puis "Sources: [url1], [url2]"

RÉSULTATS:
{raw[:2000]}"""
        max_tokens = 300

    response = _llm.generate(
        prompt,
        model=_llm.MODELS["fast"],
        max_tokens=max_tokens,
        temperature=0.3,
        stream=False,
    )
    return response


def search_news(query: str, days_back: int = 7) -> str:
    """Actualités récentes uniquement."""
    del days_back
    return search_multi(query, max_results=6, sources=["news", "newsapi"])


def search_academic(query: str) -> str:
    """Recherche académique — Wikipedia + web enrichi."""
    return search_multi(
        query,
        max_results=6,
        sources=["wikipedia", "web"],
        include_page_content=True,
    )


def search_video(query: str) -> str:
    """Recherche vidéos YouTube."""
    return search_multi(query, max_results=5, sources=["youtube"])


def search_opinions(query: str) -> str:
    """Recherche opinions — Reddit + web."""
    return search_multi(query, max_results=6, sources=["reddit", "web"])


# ── API legacy (compatibilité llm.py / google_workspace.py) ───────────────────

def ddg_search(query: str, max_results: int = 8) -> list[dict]:
    """Recherche DuckDuckGo — format brut DDG."""
    return [
        {"title": r["title"], "body": r["snippet"], "href": r["url"]}
        for r in _search_duckduckgo(query, max_results)
    ]


def ddg_news(query: str, max_results: int = 6, timelimit: str = "w") -> list[dict]:
    """Actualités DuckDuckGo — format brut DDG."""
    return [
        {
            "title": r["title"],
            "body": r["snippet"],
            "url": r["url"],
            "date": r.get("date", ""),
        }
        for r in _search_duckduckgo_news(query, max_results, timelimit=timelimit)
    ]


def wikipedia_summary(query: str, lang: str = "fr") -> Optional[str]:
    """Résumé Wikipedia court."""
    results = _search_wikipedia(query, lang)
    if results:
        return results[0].get("snippet")
    try:
        url = (
            f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
            f"{urllib.parse.quote(query)}"
        )
        resp = requests.get(
            url, timeout=5, headers={"User-Agent": "ARIA-Assistant/1.0"}
        )
        if resp.status_code == 200:
            extract = resp.json().get("extract", "")
            if extract:
                return extract[:800]
    except Exception as exc:
        logger.debug("Wikipedia summary fallback: %s", exc)
    return None


def youtube_search(query: str, max_results: int = 5) -> list[dict]:
    """Recherche YouTube — format legacy."""
    return [
        {
            "title": r["title"],
            "url": r["url"],
            "description": r.get("snippet", "")[:200],
        }
        for r in _search_youtube(query, max_results)
    ]


def multi_search(
    query: str,
    sources: list[str] | None = None,
    max_per_source: int = 5,
    *,
    news_timelimit: str | None = None,
) -> dict[str, list[dict]]:
    """Recherche multi-sources — format dict legacy pour intégrations existantes."""
    if sources is None:
        sources = ["web", "wikipedia"]

    src_list = list(sources)
    if "news" in src_list and "newsapi" not in src_list:
        src_list.append("newsapi")

    results = _collect_results(
        query,
        src_list,
        max_per_source=max_per_source,
        news_timelimit=news_timelimit,
    )
    legacy = _results_to_legacy_dict(results)
    logger.info(
        "multi_search: %d sources, %d résultats total",
        len(legacy),
        sum(len(v) for v in legacy.values()),
    )
    return legacy


def _merge_result_dicts(base: dict[str, list], extra: dict[str, list]) -> dict[str, list]:
    """Fusionne deux dicts de résultats en dédupliquant par titre/URL."""
    merged = {k: list(v) for k, v in base.items()}

    def _key(item: dict) -> str:
        return (
            item.get("href")
            or item.get("url")
            or item.get("title")
            or item.get("summary")
            or ""
        ).lower()[:120]

    for source, items in extra.items():
        existing = {_key(i) for i in merged.get(source, [])}
        bucket = merged.setdefault(source, [])
        for item in items:
            k = _key(item)
            if k and k not in existing:
                existing.add(k)
                bucket.append(item)
    return merged


def multi_search_for_request(req: "ResearchRequest", max_per_source: int = 5) -> dict[str, list]:
    """Recherche intelligente avec reformulations si résultats faibles."""
    primary = multi_search(
        req.query,
        sources=req.sources,
        max_per_source=max_per_source,
        news_timelimit=req.news_timelimit,
    )
    total = sum(len(v) for v in primary.values())
    if total >= 3 or not req.alternate_queries:
        return primary

    for alt in req.alternate_queries:
        extra = multi_search(
            alt,
            sources=req.sources,
            max_per_source=max(3, max_per_source - 1),
            news_timelimit=req.news_timelimit,
        )
        primary = _merge_result_dicts(primary, extra)
        if sum(len(v) for v in primary.values()) >= 5:
            break

    return primary


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

    if "reddit" in results:
        sections.append("=== REDDIT ===")
        for item in results["reddit"][:3]:
            sections.append(f"- {item.get('title', '')}: {item.get('body', '')[:150]}")
        sections.append("")

    return "\n".join(sections)


def _esc(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _link_html(href: str, label: str | None = None) -> str:
    if not href:
        return ""
    text = _esc(label or href)
    return f'<a class="search-result-url" href="{_esc(href)}" target="_blank">{text}</a>'


def format_results_for_ui(results: dict, query: str) -> str:
    """Formate les résultats en HTML pour affichage dans le chat."""
    parts = [
        f'<div class="search-source-badge badge-web">🔍 {_esc(query)}</div>',
    ]

    if "wikipedia" in results:
        parts.append('<div class="search-source-badge badge-wikipedia">Wikipedia</div>')
        for item in results["wikipedia"][:2]:
            if item.get("summary"):
                parts.append(
                    f'<div class="search-result-item">'
                    f'<div class="search-result-title">{_esc(item.get("title", query))}</div>'
                    f'<div class="search-result-snippet">{_esc(item["summary"][:220])}…</div>'
                    f"</div>"
                )

    if "news" in results:
        parts.append('<div class="search-source-badge badge-news">Actualités</div>')
        for item in results["news"][:3]:
            url = item.get("url") or ""
            parts.append(
                f'<div class="search-result-item">'
                f'<div class="search-result-title">{_esc(item.get("title", ""))}</div>'
                f'<div class="search-result-snippet">{_esc((item.get("body") or "")[:180])}</div>'
                f"{_link_html(url)}"
                f"</div>"
            )

    if "web" in results:
        parts.append('<div class="search-source-badge badge-web">Web</div>')
        for item in results["web"][:4]:
            href = item.get("href") or item.get("url") or ""
            parts.append(
                f'<div class="search-result-item">'
                f'<div class="search-result-title">{_esc(item.get("title", ""))}</div>'
                f'<div class="search-result-snippet">{_esc((item.get("body") or "")[:180])}</div>'
                f"{_link_html(href)}"
                f"</div>"
            )

    if "youtube" in results:
        parts.append('<div class="search-source-badge badge-youtube">YouTube</div>')
        for item in results["youtube"][:3]:
            url = item.get("url") or ""
            parts.append(
                f'<div class="search-result-item">'
                f'<div class="search-result-title">{_esc(item.get("title", ""))}</div>'
                f"{_link_html(url)}"
                f"</div>"
            )

    return "".join(parts)


def parse_pipe_csv_table(text: str) -> list[list]:
    """Parse un tableau CSV avec séparateur | en list[list]."""
    rows: list[list] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            cells = [c.strip() for c in line.split("|")]
        elif ";" in line:
            cells = [c.strip() for c in line.split(";")]
        else:
            cells = [line]
        if cells and any(cells):
            rows.append(cells)
    return rows[:21]


def build_doc_structure_prompt(sujet: str, resultats: str) -> str:
    """Prompt FAST pour structurer une recherche en sections Google Doc."""
    return (
        f"Tu es ARIA. Structure ces résultats de recherche sur '{sujet}' en sections "
        f"markdown claires pour un Google Doc. Utilise ## pour les titres "
        f"(Introduction, Points clés, Actualités, Sources). "
        f"Sois concis et factuel. Maximum 400 mots.\n\n"
        f"Résultats:\n{resultats}"
    )


def build_sheet_table_prompt(donnees: str) -> str:
    """Prompt FAST pour formater des données en tableau pipe-separated."""
    return (
        "Transforme ces données en tableau CSV (séparateur: |). "
        "Première ligne = en-têtes. Maximum 20 lignes.\n\n"
        f"Données:\n{donnees}"
    )


def build_email_draft_prompt(sujet: str, destinataire: str, contexte: str) -> str:
    """Prompt FAST pour rédiger un brouillon d'email."""
    return (
        "Rédige un email professionnel en français. "
        f"Objet: {sujet}. Corps: 3-4 phrases max. "
        f"Destinataire: {destinataire}. "
        f"Contexte: {contexte}. "
        "Format:\nOBJET: ...\nCORPS: ..."
    )


def extract_recherche_et_doc_topic(text: str) -> str | None:
    """Extrait le sujet d'une demande recherche → doc."""
    patterns = (
        r"(?:fais|fait|lance)\s+(?:une\s+)?recherche\s+sur\s+(.+?)\s+(?:et\s+)?"
        r"(?:écris|ecris|note|mets|crée|créer).*(?:doc|document)",
        r"(?:crée|créer|cree)\s+(?:un\s+)?(?:doc\s+(?:de\s+)?)?"
        r"(?:veille|rapport|synthèse|synthese)\s+(?:sur\s+)?(.+)",
        r"veille\s+(?:sur|concernant)\s+(.+)",
        r"rapport\s+(?:sur|concernant|de)\s+(.+)",
        r"recherche\s+sur\s+(.+?)\s+(?:et\s+)?(?:écris|ecris|note).*(?:doc|document)",
    )
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            topic = m.group(1).strip(" :'\"?.")
            if len(topic) >= 2:
                return topic
    return None


def extract_recherche_et_sheet_topic(text: str) -> str | None:
    """Extrait le sujet d'une demande recherche → sheet."""
    patterns = (
        r"(?:comparatif|comparaison)\s+(?:de\s+)?(.+?)\s+(?:dans\s+)?(?:un\s+)?(?:tableau|sheet)",
        r"(?:tableau|sheet)\s+(?:des|de|avec)\s+(.+)",
        r"crée\s+(?:un\s+)?(?:tableau|sheet)\s+(?:avec|de|des)\s+(.+)",
        r"fais\s+(?:un\s+)?(?:comparatif|tableau)\s+(?:de\s+)?(.+?)\s+(?:dans\s+)?(?:un\s+)?sheet",
    )
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            topic = m.group(1).strip(" :'\"?.")
            if len(topic) >= 2:
                return topic
    return None


def extract_sheet_title_from_topic(topic: str) -> str:
    """Titre court pour un Google Sheet."""
    title = topic.strip()[:60]
    return title or "Tableau ARIA"


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


# ── Compréhension des demandes (ResearchRequest) ─────────────────────────────

_CONVERSATIONAL_PREFIXES = (
    r"^(?:salut|bonjour|hey|coucou|aria)[,!\s]+",
    r"^(?:est-ce que tu peux|peux-tu|tu peux|pourrais-tu|j'aimerais que tu|"
    r"j'aimerai que tu|je voudrais que tu|je veux que tu|dis-moi|donne-moi|"
    r"explique-moi|aide-moi à|aide-moi a)\s+",
    r"^(?:peux-tu|tu peux|est-ce que tu peux)\s+me dire\s+",
    r"^me dire\s+",
    r"^(?:cherche|recherche|trouve|trouve-moi|cherche-moi|recherche-moi|"
    r"regarde|va voir|check|google)\s+(?:moi\s+)?",
    r"^(?:des?\s+)?infos?\s+(?:sur|concernant|à propos de|au sujet de)\s+",
    r"^(?:j'aimerais|je voudrais|je veux)\s+(?:savoir|connaître|connaitre|"
    r"des infos sur|en savoir plus sur)\s+",
    r"^(?:qu(?:'|e)\s*est-ce que|c'est quoi|c est quoi|qui est|qui sont|"
    r"quelle est|quel est|quels sont|quelles sont|définis|definis|"
    r"définition de|definition de)\s+",
    r"^(?:as-tu|tu as|avez-vous)\s+(?:des?\s+)?(?:infos?|informations?)\s+(?:sur|concernant)\s+",
    r"^(?:je me demande|question)\s*:?\s*",
)

_CONVERSATIONAL_SUFFIXES = (
    r"\s+(?:sur\s+(?:le\s+)?(?:web|internet|google|wikipedia|youtube|"
    r"plusieurs sources|partout|le net))\s*$",
    r"\s+(?:dans|sur)\s+(?:le\s*)?(?:google\s*)?doc\s*$",
    r"\s+(?:et\s+)?(?:note|mets|écris|ecris|ajoute).*(?:dans|sur)\s+"
    r"(?:le\s*)?(?:google\s*)?doc\s*$",
    r"\s+sur\s+youtube\s*$",
    r"\s+(?:s'il te plaît|stp|merci|please)\s*$",
    r"\s*\?\s*$",
)

_QUERY_TYPE_PATTERNS: list[tuple[str, str]] = [
    (
        r"\b(?:actualit[ée]s?|news|nouvelles?|derni[èe]res?\s+(?:infos?|nouvelles?)|"
        r"quoi de neuf|breaking|flash info)\b",
        "news",
    ),
    (
        r"\b(?:aujourd'?hui|hier|ce matin|ce soir|cette semaine|ce week-end|"
        r"en ce moment|r[ée]cemment|derni[èe]rement|202[4-9])\b",
        "recent",
    ),
    (
        r"\b(?:comment|tutoriel|tuto|guide|apprendre à|apprendre a|"
        r"faire pour|marche à suivre|étapes pour)\b",
        "howto",
    ),
    (
        r"\b(?:compare[rz]?|comparaison|diff[ée]rence entre|versus|\bvs\b|"
        r"mieux entre|lequel est|laquelle est)\b",
        "comparison",
    ),
    (r"\b(?:vid[ée]o|youtube|tuto vid[ée]o|regarder)\b", "video"),
    (r"\b(?:prix|co[ûu]te|acheter|avis|test|review|promo|soldes)\b", "product"),
    (
        r"\b(?:qu(?:'|e)\s*est-ce que|c'est quoi|qui est|d[ée]finition|"
        r"signifie|veut dire)\b",
        "definition",
    ),
]

_INTENT_SOURCE_MAP: dict[str, list[str]] = {
    "recherche_actualites": ["news", "web"],
    "recherche_news": ["news", "newsapi"],
    "recherche_wikipedia": ["wikipedia", "web"],
    "recherche_youtube": ["youtube", "web"],
    "recherche_video": ["youtube"],
    "recherche_opinions": ["reddit", "web"],
    "recherche_academique": ["wikipedia", "web"],
    "recherche_multi": ["web", "news", "wikipedia"],
    "recherche_web": ["web", "news", "wikipedia"],
}

_TYPE_SOURCE_MAP: dict[str, list[str]] = {
    "news": ["news", "web"],
    "recent": ["news", "web", "wikipedia"],
    "howto": ["youtube", "web"],
    "video": ["youtube", "web"],
    "comparison": ["web", "wikipedia"],
    "product": ["web", "news"],
    "definition": ["wikipedia", "web"],
    "factual": ["web", "wikipedia"],
    "general": ["web", "wikipedia"],
}


@dataclass
class ResearchRequest:
    original_text: str
    query: str
    alternate_queries: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=lambda: ["web", "wikipedia"])
    output: str = "chat"
    query_type: str = "general"
    synthesis_mode: str = "detailed"
    news_timelimit: str | None = None
    user_goal: str = ""


def _wants_doc_output(text: str) -> bool:
    return bool(
        re.search(
            r"(?:dans|sur)\s+(?:le\s*)?(?:google\s*)?doc|"
            r"note(?:r|-)?(?:les|\s)|écris.*doc|ecris.*doc|"
            r"mets.*doc|ajoute.*doc",
            text,
            re.IGNORECASE,
        )
    )


def _extract_topic_from_event_phrase(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text.strip())
    patterns = (
        r"ce qui s.?est pass[éeé]\s+(?:récemment|recemment|dernièrement|dernierement\s+)?"
        r"(?:avec|chez|sur|concernant)\s+(.+)",
        r"(?:qu['']?est-il arriv[éeé]|quoi de neuf)\s+(?:avec|chez|sur|concernant)\s+(.+)",
        r"(?:les?\s+)?(?:derni[èe]res?\s+)?(?:nouvelles?|actualit[ée]s?|infos?)\s+"
        r"(?:sur|concernant|à propos de|de)\s+(.+)",
        r"(?:parle(?:-|\s)?moi|dis(?:-|\s)?moi)\s+(?:de|du|de la|des)\s+(.+)",
    )
    for pattern in patterns:
        m = re.search(pattern, normalized, re.IGNORECASE)
        if m:
            topic = m.group(1).strip(" ?.,'\"")
            if len(topic) >= 2:
                return topic
    return None


def _normalize_query_text(text: str) -> str:
    q = re.sub(r"\s+", " ", text.strip())
    q = re.sub(r"\bqu est ce que\b", "qu'est-ce que", q, flags=re.I)
    q = re.sub(r"\bqu est-ce que\b", "qu'est-ce que", q, flags=re.I)
    q = re.sub(r"\bc est quoi\b", "c'est quoi", q, flags=re.I)
    q = re.sub(r"\bs est passe\b", "s'est passé", q, flags=re.I)
    return q


def _strip_conversational(text: str) -> str:
    query = _normalize_query_text(text)
    topic = _extract_topic_from_event_phrase(query)
    if topic:
        return topic

    changed = True
    while changed:
        changed = False
        for pattern in _CONVERSATIONAL_PREFIXES + _CONVERSATIONAL_SUFFIXES:
            new_query = re.sub(pattern, "", query, flags=re.IGNORECASE).strip()
            if new_query != query:
                query = new_query
                changed = True

    topic = _extract_topic_from_event_phrase(query)
    if topic:
        return topic

    who_match = re.match(r"^(?:qui est|qui sont|quelle est|quel est)\s+(.+)", query, re.I)
    if who_match:
        return who_match.group(1).strip(" ?.,'\"")

    price_match = re.match(
        r"^(?:combien co[ûu]te(?:nt)?|quel est le prix (?:de|du|d')\s*)\s*(.+)",
        query,
        re.I,
    )
    if price_match:
        item = price_match.group(1).strip(" ?.,'\"")
        return f"{item} prix"

    avec_match = re.search(r"\b(?:avec|sur|concernant)\s+(.+)$", query, re.I)
    if avec_match and re.search(
        r"\b(?:pass[éeé]|arriv[éeé]|nouvelles?|actualit)", query, re.I
    ):
        return avec_match.group(1).strip(" ?.,'\"")

    query = re.sub(r"^compare[rz]?\s+", "", query, flags=re.I).strip()
    return query


def _detect_query_type(text: str, cleaned: str) -> str:
    combined = f"{text} {cleaned}".lower()
    for pattern, qtype in _QUERY_TYPE_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return qtype
    if re.search(r"\b(combien|où|quand|pourquoi|est-ce que|depuis quand)\b", combined, re.I):
        return "factual"
    return "general"


def _synthesis_mode_for(qtype: str) -> str:
    return {
        "news": "news_brief",
        "recent": "news_brief",
        "howto": "howto",
        "comparison": "comparison",
        "definition": "brief",
        "product": "detailed",
        "video": "brief",
    }.get(qtype, "detailed")


def _news_timelimit_for(text: str, qtype: str) -> str | None:
    if qtype not in ("news", "recent"):
        return None
    t = text.lower()
    if any(k in t for k in ("aujourd'hui", "aujourdhui", "hier", "24h", "ce matin")):
        return "d"
    if any(k in t for k in ("semaine", "week", "récent", "recent")):
        return "w"
    return "w"


def _build_alternate_queries(cleaned: str, qtype: str, original: str) -> list[str]:
    alts: list[str] = []
    base = cleaned.strip()

    if qtype in ("news", "recent") and not re.search(r"\b(actualit|news)\b", base, re.I):
        alts.append(f"{base} actualités")
        alts.append(f"{base} news")

    if qtype == "definition":
        alts.append(f"{base} définition")
        alts.append(f"{base} wikipedia")

    if qtype == "howto":
        core = re.sub(r"^(?:comment|tutoriel|guide)\s+", "", base, flags=re.I).strip()
        alts.append(f"{core} tutoriel")
        alts.append(f"comment {core}")

    if qtype == "comparison":
        comp = re.sub(r"^compare[rz]?\s+", "", base, flags=re.I).strip()
        vs_match = re.search(r"(.+?)\s+(?:vs|versus|ou|et)\s+(.+)", comp, re.IGNORECASE)
        if vs_match:
            a, b = vs_match.group(1).strip(), vs_match.group(2).strip()
            alts.append(f"{a} vs {b} comparaison")
            alts.append(f"différence {a} {b}")
        else:
            alts.append(f"{comp} comparaison")

    if qtype == "product":
        alts.append(f"{base} avis test")
        alts.append(f"{base} prix")

    quoted = re.findall(r'["\']([^"\']{3,80})["\']', original)
    for q in quoted:
        if q.lower() not in base.lower():
            alts.append(q)

    seen = {base.lower()}
    unique: list[str] = []
    for q in alts:
        key = q.lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(q)
    return unique[:3]


def _select_sources(qtype: str, intent_hint: str | None, output: str) -> list[str]:
    if intent_hint and intent_hint in _INTENT_SOURCE_MAP:
        sources = list(_INTENT_SOURCE_MAP[intent_hint])
    else:
        sources = list(_TYPE_SOURCE_MAP.get(qtype, ["web", "wikipedia"]))

    if output == "doc" and "news" not in sources:
        sources.insert(0, "news")

    out: list[str] = []
    for s in sources:
        if s not in out:
            out.append(s)
    return out


def _extract_user_goal(original: str, cleaned: str, qtype: str) -> str:
    if qtype == "news":
        return f"Actualités récentes sur : {cleaned}"
    if qtype == "definition":
        return f"Définition / explication de : {cleaned}"
    if qtype == "howto":
        return f"Guide pratique : {cleaned}"
    if qtype == "comparison":
        return f"Comparaison : {cleaned}"
    if qtype == "product":
        return f"Avis, prix et infos produit : {cleaned}"
    if qtype == "video":
        return f"Vidéos pertinentes sur : {cleaned}"
    if "?" in original:
        return original.strip().rstrip("?").strip()
    return cleaned


def parse_research_request(
    text: str,
    *,
    intent_hint: str | None = None,
    output: str | None = None,
) -> ResearchRequest:
    """Analyse une demande en langage naturel et produit une requête optimisée."""
    original = _normalize_query_text(text.strip())
    cleaned = _strip_conversational(original)
    if not cleaned:
        cleaned = original

    qtype = _detect_query_type(original, cleaned)
    out = output or ("doc" if _wants_doc_output(original) else "chat")
    sources = _select_sources(qtype, intent_hint, out)
    alts = _build_alternate_queries(cleaned, qtype, original)
    goal = _extract_user_goal(original, cleaned, qtype)

    return ResearchRequest(
        original_text=original,
        query=cleaned,
        alternate_queries=alts,
        sources=sources,
        output=out,
        query_type=qtype,
        synthesis_mode=_synthesis_mode_for(qtype),
        news_timelimit=_news_timelimit_for(original, qtype),
        user_goal=goal,
    )


def needs_llm_query_refinement(req: ResearchRequest) -> bool:
    q = req.query.lower()
    if len(q.split()) > 10:
        return True
    conversational = (
        r"\b(?:est-ce que|peux-tu|je voudrais|j'aimerais|dis-moi|donne-moi|"
        r"s'il te plaît|stp|sais-tu|connais-tu|tu sais)\b"
    )
    if re.search(conversational, q, re.I):
        return True
    if re.search(r"\b(?:qu(?:'|e)\s*est-ce que|c'est quoi|comment|pourquoi)\b", q, re.I):
        return True
    return False


def apply_refined_query(req: ResearchRequest, refined: str) -> ResearchRequest:
    refined = re.sub(r"\s+", " ", refined.strip().strip("\"'")).strip()
    if not refined or len(refined) < 2:
        return req
    if refined.lower() != req.query.lower():
        req.alternate_queries = [req.query] + [
            q for q in req.alternate_queries if q.lower() != refined.lower()
        ]
        req.query = refined
    return req


def build_synthesis_prompt(req: ResearchRequest, llm_input: str) -> str:
    """Prompt de synthèse adapté au type de demande."""
    mode_instructions = {
        "news_brief": (
            "Rédige un brief d'actualités en markdown avec EXACTEMENT ces sections :\n"
            "## Faits clés\n## Contexte\n## Ce qui est confirmé vs spéculatif\n"
            "Mentionne les dates si disponibles."
        ),
        "howto": (
            "Rédige un guide pratique en markdown :\n"
            "## Étapes\n## Prérequis\n## Conseils\n"
            "Clair et actionnable."
        ),
        "comparison": (
            "Compare objectivement en markdown :\n"
            "## Option A\n## Option B\n## Recommandation\n"
        ),
        "brief": ("Réponds en markdown concis : ## Réponse (1-2 paragraphes)."),
        "detailed": (
            "Synthétise en markdown structuré :\n"
            "## Résumé\n## Points importants\n## Sources\n"
            "3-5 paragraphes factuels."
        ),
    }
    instruction = mode_instructions.get(req.synthesis_mode, mode_instructions["detailed"])

    return (
        f"Tu es ARIA, un assistant français.\n"
        f"Demande originale de l'utilisateur : « {req.original_text} »\n"
        f"Objectif : {req.user_goal}\n\n"
        f"{instruction}\n"
        f"Réponds directement à la demande (pas de préambule type « Bien sûr »). "
        f"Cite les sources implicitement si pertinent. "
        f"Si des URLs YouTube sont présentes, mentionne-les.\n\n"
        f"Résultats de recherche pour « {req.query} » :\n\n"
        f"{llm_input}"
    )


_REQUIRED_SECTIONS: dict[str, list[str]] = {
    "news_brief": ["Faits clés", "Contexte", "Ce qui est confirmé vs spéculatif"],
    "howto": ["Étapes", "Prérequis", "Conseils"],
    "comparison": ["Option A", "Option B", "Recommandation"],
    "brief": ["Réponse"],
    "detailed": ["Résumé", "Points importants", "Sources"],
}


def normalize_structured_markdown(text: str, synthesis_mode: str = "detailed") -> str:
    """Complète les sections markdown manquantes pour un rendu doc structuré."""
    if not text or not text.strip():
        return text

    body = text.strip()
    existing = {
        m.group(1).strip().lower()
        for m in re.finditer(r"^##\s+(.+)$", body, flags=re.MULTILINE)
    }
    required = _REQUIRED_SECTIONS.get(synthesis_mode, _REQUIRED_SECTIONS["detailed"])

    missing: list[str] = []
    for section in required:
        key = section.lower()
        if not any(key in e or e in key for e in existing):
            missing.append(section)

    if not missing:
        return body

    suffix = "".join(f"\n\n## {title}\n—" for title in missing)
    return body + suffix
