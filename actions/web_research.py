"""
web_research.py — Recherche web avancée multi-sources.
Combine ddgs, scraping léger et APIs publiques pour des résultats riches.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from dataclasses import dataclass, field
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


# ── Compréhension des demandes ────────────────────────────────────────────────

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
    (r"\b(?:actualit[ée]s?|news|nouvelles?|derni[èe]res?\s+(?:infos?|nouvelles?)|"
     r"quoi de neuf|breaking|flash info)\b", "news"),
    (r"\b(?:aujourd'?hui|hier|ce matin|ce soir|cette semaine|ce week-end|"
     r"en ce moment|r[ée]cemment|derni[èe]rement|202[4-9])\b", "recent"),
    (r"\b(?:comment|tutoriel|tuto|guide|apprendre à|apprendre a|"
     r"faire pour|marche à suivre|étapes pour)\b", "howto"),
    (r"\b(?:compare[rz]?|comparaison|diff[ée]rence entre|versus|\bvs\b|"
     r"mieux entre|lequel est|laquelle est)\b", "comparison"),
    (r"\b(?:vid[ée]o|youtube|tuto vid[ée]o|regarder)\b", "video"),
    (r"\b(?:prix|co[ûu]te|acheter|avis|test|review|promo|soldes)\b", "product"),
    (r"\b(?:qu(?:'|e)\s*est-ce que|c'est quoi|qui est|d[ée]finition|"
     r"signifie|veut dire)\b", "definition"),
]

_INTENT_SOURCE_MAP: dict[str, list[str]] = {
    "recherche_actualites": ["news", "web"],
    "recherche_wikipedia": ["wikipedia", "web"],
    "recherche_youtube": ["youtube", "web"],
    "recherche_multi": ["web", "news", "wikipedia"],
    "recherche_web": ["web", "wikipedia"],
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
    """« ce qui s'est passé avec SpaceX » → SpaceX."""
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
    """Nettoie espaces et variantes courantes sans apostrophe."""
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

    # Second passe : sujet après nettoyage des formules de politesse
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
    if avec_match and re.search(r"\b(?:pass[éeé]|arriv[éeé]|nouvelles?|actualit)", query, re.I):
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
        vs_match = re.search(
            r"(.+?)\s+(?:vs|versus|ou|et)\s+(.+)",
            comp,
            re.IGNORECASE,
        )
        if vs_match:
            a, b = vs_match.group(1).strip(), vs_match.group(2).strip()
            alts.append(f"{a} vs {b} comparaison")
            alts.append(f"différence {a} {b}")
        else:
            alts.append(f"{comp} comparaison")

    if qtype == "product":
        alts.append(f"{base} avis test")
        alts.append(f"{base} prix")

    # Extraire sujet entre guillemets
    quoted = re.findall(r'["\']([^"\']{3,80})["\']', original)
    for q in quoted:
        if q.lower() not in base.lower():
            alts.append(q)

    # Dédupliquer en préservant l'ordre
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

    # Dédupliquer
    out: list[str] = []
    for s in sources:
        if s not in out:
            out.append(s)
    return out


def _extract_user_goal(original: str, cleaned: str, qtype: str) -> str:
    """Résumé court de ce que l'utilisateur veut — pour guider la synthèse."""
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
    """
    Analyse une demande en langage naturel et produit une requête de recherche
    optimisée + sources + mode de synthèse adaptés.
    """
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
    """Vrai si la requête extraite semble encore trop conversationnelle."""
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
            "Rédige un brief d'actualités structuré : faits clés, contexte, "
            "ce qui est confirmé vs spéculatif. Mentionne les dates si disponibles."
        ),
        "howto": (
            "Rédige un guide pratique étape par étape, clair et actionnable. "
            "Mentionne les prérequis si nécessaire."
        ),
        "comparison": (
            "Compare objectivement les options : points forts, faiblesses, "
            "pour qui c'est adapté. Utilise des listes si utile."
        ),
        "brief": (
            "Réponds de façon concise et précise en 1-2 paragraphes."
        ),
        "detailed": (
            "Synthétise en 3-5 paragraphes clairs, factuels et utiles."
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


def ddg_news(query: str, max_results: int = 6, timelimit: str = "w") -> list[dict]:
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
            return list(ddgs.news(query, max_results=max_results, timelimit=timelimit))
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
    *,
    news_timelimit: str | None = None,
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
                tl = news_timelimit or "w"
                return source, ddg_news(query, max_results=max_per_source, timelimit=tl)
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


def _merge_result_dicts(base: dict[str, list], extra: dict[str, list]) -> dict[str, list]:
    """Fusionne deux dicts de résultats en dédupliquant par titre/URL."""
    merged = {k: list(v) for k, v in base.items()}

    def _key(item: dict) -> str:
        return (
            item.get("href") or item.get("url") or item.get("title") or item.get("summary") or ""
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


def multi_search_for_request(req: ResearchRequest, max_per_source: int = 5) -> dict[str, list]:
    """
    Recherche intelligente : requête principale + reformulations si résultats faibles.
    """
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
