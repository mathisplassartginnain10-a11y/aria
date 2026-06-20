# ARIA — Spec v20 : Recherche web multi-sites + export Google Docs

## Objectif

ARIA doit pouvoir :
1. Effectuer des recherches sur plusieurs sites simultanément (Google, Wikipedia, YouTube,
   Reddit, GitHub, sites spécialisés) et synthétiser les résultats dans le chat
2. Créer un Google Doc à la demande, puis y écrire les résultats de recherches futures
3. Décider intelligemment si les résultats vont dans le chat ou dans le Doc actif

---

## Partie 1 — Recherche web multi-sites

### Module actions/web_research.py (nouveau)

```python
"""
web_research.py — Recherche web avancée multi-sources.
Combine ddgs, scraping léger et APIs publiques pour des résultats riches.
"""
import logging
import requests
import urllib.parse
from typing import Optional

logger = logging.getLogger(__name__)

# ── Sources disponibles ───────────────────────────────────────────────────────

SOURCES = {
    'google':     'https://www.google.com/search?q={query}',
    'youtube':    'https://www.youtube.com/results?search_query={query}',
    'wikipedia':  'https://fr.wikipedia.org/w/index.php?search={query}',
    'reddit':     'https://www.reddit.com/search/?q={query}',
    'github':     'https://github.com/search?q={query}',
    'stackoverflow': 'https://stackoverflow.com/search?q={query}',
    'amazon':     'https://www.amazon.fr/s?k={query}',
    'leboncoin':  'https://www.leboncoin.fr/recherche?text={query}',
    'meteofrance':'https://meteofrance.com/previsions-meteo-france/{query}',
    'seloger':    'https://www.seloger.com/list.htm?ci=&idtt=2&pxmax=&pxmin=&tri=initial&idtypebien=1,2&naturebien=1,2,4&nMax=20&txt={query}',
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
    except Exception as e:
        logger.error("DDG search error: %s", e)
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
            return list(ddgs.news(query, max_results=max_results, timelimit='w'))
    except Exception as e:
        logger.error("DDG news error: %s", e)
        return []


def wikipedia_summary(query: str, lang: str = 'fr') -> Optional[str]:
    """Résumé Wikipedia via l'API officielle (gratuite, sans clé)."""
    try:
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(query)}"
        resp = requests.get(url, timeout=5, headers={'User-Agent': 'ARIA-Assistant/1.0'})
        if resp.status_code == 200:
            data = resp.json()
            extract = data.get('extract', '')
            if extract:
                logger.info("Wikipedia: résumé trouvé pour '%s'", query)
                return extract[:800]  # max 800 chars
        # Si page exacte pas trouvée, chercher via search
        search_url = f"https://{lang}.wikipedia.org/w/api.php"
        params = {
            'action': 'query',
            'list': 'search',
            'srsearch': query,
            'format': 'json',
            'srlimit': 1,
        }
        resp = requests.get(search_url, params=params, timeout=5,
                           headers={'User-Agent': 'ARIA-Assistant/1.0'})
        if resp.status_code == 200:
            results = resp.json().get('query', {}).get('search', [])
            if results:
                title = results[0]['title']
                return wikipedia_summary(title, lang)
    except Exception as e:
        logger.debug("Wikipedia error: %s", e)
    return None


def youtube_search(query: str, max_results: int = 5) -> list[dict]:
    """Recherche YouTube via DDG (pas de clé API nécessaire)."""
    results = ddg_search(f"site:youtube.com {query}", max_results=max_results)
    videos = []
    for r in results:
        if 'youtube.com/watch' in r.get('href', ''):
            videos.append({
                'title': r.get('title', ''),
                'url': r.get('href', ''),
                'description': r.get('body', '')[:200],
            })
    return videos


def multi_search(
    query: str,
    sources: list[str] = None,
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
        sources = ['web', 'wikipedia']

    import concurrent.futures
    results = {}

    def fetch_source(source: str) -> tuple[str, list]:
        try:
            if source == 'web':
                return source, ddg_search(query, max_results=max_per_source)
            elif source == 'news':
                return source, ddg_news(query, max_results=max_per_source)
            elif source == 'wikipedia':
                summary = wikipedia_summary(query)
                return source, [{'summary': summary}] if summary else []
            elif source == 'youtube':
                return source, youtube_search(query, max_results=max_per_source)
            else:
                return source, ddg_search(f"site:{source} {query}", max_results=max_per_source)
        except Exception as e:
            logger.error("Erreur source %s: %s", source, e)
            return source, []

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_source, s): s for s in sources}
        for future in concurrent.futures.as_completed(futures, timeout=15):
            try:
                source, data = future.result()
                if data:
                    results[source] = data
            except Exception as e:
                logger.error("Future error: %s", e)

    logger.info("multi_search: %d sources, %d résultats total",
                len(results), sum(len(v) for v in results.values()))
    return results


def format_results_for_llm(results: dict, query: str) -> str:
    """
    Formate les résultats multi-sources pour les passer au LLM
    qui les synthétisera en langage naturel.
    """
    sections = [f"Résultats de recherche pour : '{query}'\n"]

    if 'wikipedia' in results:
        for r in results['wikipedia']:
            if r.get('summary'):
                sections.append(f"=== WIKIPEDIA ===\n{r['summary']}\n")

    if 'news' in results:
        sections.append("=== ACTUALITÉS ===")
        for r in results['news'][:4]:
            sections.append(f"- {r.get('title', '')}: {r.get('body', '')[:150]}")
        sections.append("")

    if 'web' in results:
        sections.append("=== WEB ===")
        for r in results['web'][:5]:
            sections.append(f"- {r.get('title', '')}: {r.get('body', '')[:150]}")
        sections.append("")

    if 'youtube' in results:
        sections.append("=== YOUTUBE ===")
        for r in results['youtube'][:3]:
            sections.append(f"- {r.get('title', '')} — {r.get('url', '')}")
        sections.append("")

    return "\n".join(sections)


def format_results_for_doc(results: dict, query: str) -> str:
    """
    Formate les résultats en texte structuré pour Google Docs.
    Plus détaillé que le format chat.
    """
    import datetime
    lines = [
        f"Recherche ARIA — {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}",
        f"Requête : {query}",
        "=" * 60,
        "",
    ]

    if 'wikipedia' in results:
        lines.append("WIKIPEDIA")
        lines.append("-" * 40)
        for r in results['wikipedia']:
            if r.get('summary'):
                lines.append(r['summary'])
        lines.append("")

    if 'news' in results:
        lines.append("ACTUALITÉS")
        lines.append("-" * 40)
        for r in results['news']:
            lines.append(f"• {r.get('title', '')}")
            lines.append(f"  {r.get('body', '')[:300]}")
            if r.get('url'):
                lines.append(f"  Source: {r.get('url', '')}")
            lines.append("")

    if 'web' in results:
        lines.append("RÉSULTATS WEB")
        lines.append("-" * 40)
        for r in results['web']:
            lines.append(f"• {r.get('title', '')}")
            lines.append(f"  {r.get('body', '')[:300]}")
            if r.get('href'):
                lines.append(f"  URL: {r.get('href', '')}")
            lines.append("")

    if 'youtube' in results:
        lines.append("VIDÉOS YOUTUBE")
        lines.append("-" * 40)
        for r in results['youtube']:
            lines.append(f"• {r.get('title', '')}")
            lines.append(f"  {r.get('url', '')}")
            lines.append("")

    return "\n".join(lines)
```

---

## Partie 2 — Google Docs : création et écriture

### actions/gdocs.py (nouveau)

```python
"""
gdocs.py — Création et édition de Google Docs via l'API officielle.
Nécessite setup_google.py pour l'authentification OAuth2 (une seule fois).
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Stocke le Doc actif de la session (ID + titre)
_active_doc: dict | None = None  # {'id': str, 'title': str, 'url': str}


def _get_docs_service():
    """Retourne le service Google Docs authentifié."""
    from actions.google_auth import get_credentials
    from googleapiclient.discovery import build

    creds = get_credentials()
    if not creds:
        raise RuntimeError(
            "Google non configuré. Lance : python setup_google.py"
        )
    return build('docs', 'v1', credentials=creds)


def _get_drive_service():
    from actions.google_auth import get_credentials
    from googleapiclient.discovery import build

    creds = get_credentials()
    if not creds:
        raise RuntimeError("Google non configuré.")
    return build('drive', 'v3', credentials=creds)


def is_configured() -> bool:
    """Vérifie si Google est configuré."""
    try:
        from actions.google_auth import is_configured
        return is_configured()
    except Exception:
        return False


def get_active_doc() -> dict | None:
    """Retourne le doc actif de la session."""
    return _active_doc


def set_active_doc(doc_id: str, title: str, url: str) -> None:
    """Définit le doc actif."""
    global _active_doc
    _active_doc = {'id': doc_id, 'title': title, 'url': url}
    logger.info("Doc actif: %s (%s)", title, doc_id)


def clear_active_doc() -> None:
    global _active_doc
    _active_doc = None


def create_doc(title: str, initial_content: str = "") -> dict:
    """
    Crée un nouveau Google Doc.

    Returns:
        {'id': str, 'title': str, 'url': str}
    """
    if not is_configured():
        raise RuntimeError("Google non configuré. Lance : python setup_google.py")

    try:
        docs_service = _get_docs_service()

        # Créer le document
        doc = docs_service.documents().create(
            body={'title': title}
        ).execute()
        doc_id = doc['documentId']
        url = f"https://docs.google.com/document/d/{doc_id}/edit"

        # Ajouter le contenu initial si fourni
        if initial_content:
            append_to_doc(doc_id, initial_content)

        logger.info("Doc créé: '%s' → %s", title, url)
        return {'id': doc_id, 'title': title, 'url': url}

    except Exception as e:
        logger.error("Erreur création doc: %s", e)
        raise


def append_to_doc(doc_id: str, content: str) -> bool:
    """
    Ajoute du contenu à la FIN d'un Google Doc existant.

    Args:
        doc_id: ID du document
        content: Texte à ajouter

    Returns:
        True si succès
    """
    if not is_configured():
        raise RuntimeError("Google non configuré.")

    try:
        docs_service = _get_docs_service()

        # Récupérer la longueur actuelle du doc
        doc = docs_service.documents().get(documentId=doc_id).execute()
        end_index = doc['body']['content'][-1]['endIndex'] - 1

        # Insérer le texte à la fin
        requests_body = [{
            'insertText': {
                'location': {'index': end_index},
                'text': f"\n{content}"
            }
        }]

        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': requests_body}
        ).execute()

        logger.info("Contenu ajouté au doc %s (%d chars)", doc_id, len(content))
        return True

    except Exception as e:
        logger.error("Erreur append doc: %s", e)
        raise


def write_section_to_doc(
    doc_id: str,
    title: str,
    content: str,
    heading_level: int = 1,
) -> bool:
    """
    Ajoute une section avec titre formaté dans un Google Doc.

    Args:
        doc_id: ID du document
        title: Titre de la section
        content: Corps de la section
        heading_level: 1 = H1, 2 = H2, etc.
    """
    if not is_configured():
        raise RuntimeError("Google non configuré.")

    try:
        docs_service = _get_docs_service()

        # Position de fin
        doc = docs_service.documents().get(documentId=doc_id).execute()
        end_index = doc['body']['content'][-1]['endIndex'] - 1

        heading_style = {
            1: 'HEADING_1',
            2: 'HEADING_2',
            3: 'HEADING_3',
        }.get(heading_level, 'HEADING_2')

        full_text = f"\n{title}\n{content}\n"

        requests_body = [
            # Insérer le texte
            {
                'insertText': {
                    'location': {'index': end_index},
                    'text': full_text,
                }
            },
            # Formater le titre en heading
            {
                'updateParagraphStyle': {
                    'range': {
                        'startIndex': end_index + 1,
                        'endIndex': end_index + 1 + len(title),
                    },
                    'paragraphStyle': {'namedStyleType': heading_style},
                    'fields': 'namedStyleType',
                }
            },
        ]

        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': requests_body}
        ).execute()

        return True

    except Exception as e:
        logger.error("Erreur write_section: %s", e)
        raise


def get_doc_info(doc_id: str) -> dict:
    """Retourne les infos d'un doc (titre, nb de pages, dernière modif)."""
    try:
        docs_service = _get_docs_service()
        doc = docs_service.documents().get(documentId=doc_id).execute()
        return {
            'id': doc_id,
            'title': doc.get('title', ''),
            'url': f"https://docs.google.com/document/d/{doc_id}/edit",
        }
    except Exception as e:
        logger.error("Erreur get_doc_info: %s", e)
        return {}


def open_doc_in_browser(doc_id: str) -> None:
    """Ouvre le doc dans Chrome."""
    import subprocess, os
    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    chrome_paths = [
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    ]
    for path in chrome_paths:
        if os.path.exists(path):
            subprocess.Popen([path, url], creationflags=subprocess.CREATE_NO_WINDOW)
            return
    os.startfile(url)
```

---

## Partie 3 — Intégration dans le routage llm.py

### Nouveaux intents à détecter

```python
# Dans llm.py, ajouter dans KNOWN_INTENTS :
'recherche_web',         # Recherche générale sur le web
'recherche_actualites',  # Recherche d'actualités
'recherche_youtube',     # Recherche sur YouTube
'recherche_wikipedia',   # Recherche sur Wikipedia
'recherche_multi',       # Recherche sur plusieurs sources
'gdoc_create',           # Créer un Google Doc
'gdoc_write_search',     # Écrire résultats de recherche dans le doc actif
'gdoc_open',             # Ouvrir le doc actif dans Chrome
'gdoc_status',           # Statut du doc actif (est-ce qu'il y en a un ?)
```

### Patterns regex à ajouter dans _fast_intent()

```python
# Recherche web
import re

# Patterns recherche
RECHERCHE_PATTERNS = [
    (r'(?:cherche|recherche|trouve|dis-moi|donne-moi)\s+.+\s+sur\s+(?:le web|internet|google)',
     'recherche_web'),
    (r'(?:cherche|recherche)\s+les?\s+(?:dernières?|récentes?)\s+(?:actualités|news|infos)',
     'recherche_actualites'),
    (r'(?:qu(?:\'|e)\s*est.ce que|c\'est quoi|qui est|quelle est)\s+.+',
     'recherche_wikipedia'),
    (r'(?:cherche|trouve|recherche)\s+.+\s+sur youtube',
     'browser_youtube_search'),  # déjà existant
    (r'(?:cherche|recherche|trouve)\s+.+\s+sur\s+(?:plusieurs sources|le web et wikipedia|partout)',
     'recherche_multi'),
    # Google Docs
    (r'(?:crée|créer|ouvre|génère)\s+(?:un|le)\s+(?:google\s*)?doc',
     'gdoc_create'),
    (r'(?:écris|mets|note|ajoute)\s+.+\s+(?:dans|sur)\s+(?:le\s*)?(?:google\s*)?doc',
     'gdoc_write_search'),
    (r'(?:ouvre|affiche|montre)\s+(?:le\s*)?(?:google\s*)?doc',
     'gdoc_open'),
    (r'(?:quel est\s+le\s+)?(?:doc|document)\s+(?:actif|ouvert|en cours)',
     'gdoc_status'),
]

# Dans _fast_intent() :
for pattern, intent in RECHERCHE_PATTERNS:
    if re.search(pattern, text_lower, re.IGNORECASE):
        return intent, {}
```

### Exécution des intents de recherche dans _execute_action()

```python
elif intent == 'recherche_web':
    return _do_web_research(text, sources=['web'], output='chat')

elif intent == 'recherche_actualites':
    return _do_web_research(text, sources=['news'], output='chat')

elif intent == 'recherche_wikipedia':
    # Extraire le sujet
    query = re.sub(
        r"(?:qu(?:'|e)\s*est.ce que|c'est quoi|qui est|quelle est)\s+",
        '', text, flags=re.IGNORECASE
    ).strip()
    return _do_web_research(query, sources=['wikipedia'], output='chat')

elif intent == 'recherche_multi':
    return _do_web_research(text, sources=['web', 'news', 'wikipedia'], output='chat')

elif intent == 'gdoc_create':
    return _create_gdoc(text)

elif intent == 'gdoc_write_search':
    return _write_search_to_gdoc(text)

elif intent == 'gdoc_open':
    return _open_gdoc()

elif intent == 'gdoc_status':
    return _gdoc_status()
```

### Fonctions d'exécution

```python
def _extract_search_query(text: str) -> str:
    """Extrait la requête de recherche depuis le texte utilisateur."""
    # Supprimer les verbes d'introduction
    patterns_to_remove = [
        r'^(?:cherche|recherche|trouve|donne-moi|dis-moi)\s+(?:moi\s+)?(?:des?\s+infos?\s+sur\s+)?',
        r'^(?:qu(?:\'|e)\s*est.ce que|c\'est quoi|qui est|quelle est)\s+',
        r'\s+sur\s+(?:le web|internet|google|wikipedia|plusieurs sources|partout)$',
        r'\s+(?:dans|sur)\s+(?:le\s*)?(?:google\s*)?doc$',
    ]
    query = text.strip()
    for p in patterns_to_remove:
        query = re.sub(p, '', query, flags=re.IGNORECASE).strip()
    return query or text


def _do_web_research(
    text: str,
    sources: list[str] = None,
    output: str = 'chat',  # 'chat' ou 'doc'
) -> str:
    """
    Effectue une recherche web et retourne/écrit les résultats.

    Args:
        text: Texte de la demande utilisateur
        sources: Sources à utiliser
        output: 'chat' pour afficher dans le chat, 'doc' pour écrire dans le Doc actif
    """
    from actions.web_research import multi_search, format_results_for_llm, format_results_for_doc
    import ui_bridge  # ou ui selon l'architecture

    query = _extract_search_query(text)
    if not query:
        return "Je n'ai pas compris ta requête de recherche."

    logger.info("Recherche: '%s' sur %s → %s", query, sources, output)

    # Afficher un indicateur de chargement
    ui_bridge.set_status('thinking')
    ui_bridge.show_toast(f"Recherche en cours : {query}...", 'info')

    # Effectuer la recherche
    results = multi_search(query, sources=sources or ['web', 'wikipedia'])

    if not results:
        return f"Aucun résultat trouvé pour '{query}'."

    if output == 'doc':
        # Écrire dans le Doc actif
        from actions import gdocs
        active_doc = gdocs.get_active_doc()
        if not active_doc:
            return (
                "Aucun Google Doc actif. Dis-moi d'abord 'crée un Google Doc [titre]' "
                "ou 'ouvre le doc [titre]'."
            )
        doc_content = format_results_for_doc(results, query)
        try:
            gdocs.write_section_to_doc(
                active_doc['id'],
                title=f"Recherche : {query}",
                content=doc_content,
                heading_level=2
            )
            return (
                f"Résultats de la recherche '{query}' ajoutés dans le doc "
                f"'{active_doc['title']}'. {active_doc['url']}"
            )
        except Exception as e:
            return f"Erreur écriture dans le doc : {e}"

    else:
        # Synthétiser avec le LLM et afficher dans le chat
        llm_input = format_results_for_llm(results, query)

        synthesis_prompt = (
            f"Tu es ARIA, un assistant français. Voici des résultats de recherche "
            f"sur '{query}'. Synthétise-les en un compte-rendu clair et utile en français, "
            f"en 3-5 paragraphes. Si des URLs YouTube sont présentes, mentionne-les. "
            f"Sois factuel et précis.\n\n"
            f"{llm_input}"
        )

        # Utiliser le modèle heavy pour une bonne synthèse
        synthesis = generate(
            synthesis_prompt,
            model=MODELS['heavy'],
            stream=True,
            max_tokens=600,
            temperature=0.3,
            on_token=lambda t: ui_bridge.emit_stream_token('search_result', t) if hasattr(ui_bridge, 'emit_stream_token') else None,
        )

        return synthesis


def _create_gdoc(text: str) -> str:
    """Crée un nouveau Google Doc et le définit comme actif."""
    from actions import gdocs

    if not gdocs.is_configured():
        return (
            "Google n'est pas configuré. Lance 'python setup_google.py' "
            "pour connecter ton compte Google."
        )

    # Extraire le titre du doc depuis le texte
    title_match = re.search(
        r'(?:crée|créer|ouvre|génère)\s+(?:un|le)\s+(?:google\s*)?doc\s+(?:intitulé\s+|nommé\s+|appelé\s+)?["\']?(.+?)["\']?$',
        text, re.IGNORECASE
    )
    if title_match:
        title = title_match.group(1).strip().strip('"\'')
    else:
        from datetime import datetime
        title = f"Recherche ARIA — {datetime.now().strftime('%d/%m/%Y')}"

    try:
        doc_info = gdocs.create_doc(
            title=title,
            initial_content=f"Document créé par ARIA le {__import__('datetime').datetime.now().strftime('%d/%m/%Y à %H:%M')}\n\n"
        )
        gdocs.set_active_doc(doc_info['id'], doc_info['title'], doc_info['url'])

        # Ouvrir dans Chrome
        gdocs.open_doc_in_browser(doc_info['id'])

        return (
            f"Google Doc '{title}' créé et ouvert dans Chrome. "
            f"Je peux maintenant y écrire tes recherches. "
            f"Dis-moi 'note les résultats dans le doc' après une recherche."
        )
    except Exception as e:
        return f"Erreur création doc : {e}"


def _write_search_to_gdoc(text: str) -> str:
    """Détecte une recherche dans le texte et l'écrit dans le doc actif."""
    # Extraire la requête de recherche depuis le texte
    search_match = re.search(
        r'(?:écris|mets|note|ajoute)\s+(?:les?\s+)?(?:résultats?\s+(?:de\s+)?)?(?:la\s+)?(?:recherche\s+(?:sur\s+)?)?["\']?(.+?)["\']?\s+(?:dans|sur)\s+(?:le\s*)?(?:google\s*)?doc',
        text, re.IGNORECASE
    )
    if search_match:
        query = search_match.group(1).strip()
    else:
        # Essayer d'extraire juste ce qu'il faut chercher
        query = _extract_search_query(
            re.sub(r'(?:dans|sur)\s+(?:le\s*)?(?:google\s*)?doc', '', text, flags=re.IGNORECASE)
        )

    if not query:
        return "Précise ce que tu veux rechercher et écrire dans le doc."

    return _do_web_research(query, sources=['web', 'wikipedia', 'news'], output='doc')


def _open_gdoc() -> str:
    """Ouvre le doc actif dans Chrome."""
    from actions import gdocs
    active = gdocs.get_active_doc()
    if not active:
        return "Aucun Google Doc actif. Crée-en un d'abord : 'crée un doc [titre]'."

    gdocs.open_doc_in_browser(active['id'])
    return f"Doc '{active['title']}' ouvert dans Chrome."


def _gdoc_status() -> str:
    """Retourne le statut du doc actif."""
    from actions import gdocs
    active = gdocs.get_active_doc()
    if not active:
        return "Aucun Google Doc actif pour cette session. Dis-moi 'crée un doc [titre]' pour en créer un."
    return (
        f"Doc actif : '{active['title']}'\n"
        f"URL : {active['url']}\n"
        f"Toutes tes prochaines recherches avec 'note dans le doc' y seront ajoutées."
    )
```

---

## Partie 4 — Affichage des résultats dans l'UI

### Format visuel des résultats de recherche dans le chat

Ajouter dans `ui/index.html` (ou `electron/renderer/styles.css`) le style des
cartes de résultats de recherche :

```css
/* Cartes de résultats de recherche */
.search-results-card {
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 14px 16px;
  margin-top: 10px;
  font-size: 13px;
}

.search-source-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 20px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

.badge-web { background: rgba(108,142,255,0.15); color: #6C8EFF; }
.badge-wikipedia { background: rgba(74,222,128,0.15); color: #4ADE80; }
.badge-youtube { background: rgba(239,68,68,0.15); color: #F87171; }
.badge-news { background: rgba(245,158,11,0.15); color: #F59E0B; }

.search-result-item {
  padding: 8px 0;
  border-bottom: 1px solid rgba(255,255,255,0.05);
}

.search-result-item:last-child { border-bottom: none; }

.search-result-title {
  font-size: 13px;
  color: var(--text);
  font-weight: 500;
  margin-bottom: 3px;
}

.search-result-snippet {
  font-size: 11px;
  color: var(--text3);
  line-height: 1.5;
}

.search-result-url {
  font-size: 10px;
  color: var(--accent);
  margin-top: 3px;
  cursor: pointer;
  text-decoration: none;
}

.gdoc-link-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  background: rgba(74,222,128,0.08);
  border: 1px solid rgba(74,222,128,0.2);
  border-radius: 12px;
  margin-top: 8px;
  cursor: pointer;
  text-decoration: none;
}

.gdoc-link-card:hover { background: rgba(74,222,128,0.14); }
.gdoc-link-icon { font-size: 20px; }
.gdoc-link-text { font-size: 13px; color: var(--text); }
.gdoc-link-sub { font-size: 11px; color: var(--text3); margin-top: 2px; }
```

---

## Partie 5 — Exemples de conversations

### Exemple 1 — Recherche simple dans le chat

```
Utilisateur: "cherche des infos sur le Nothing Phone 4a"
ARIA: [recherche sur web + wikipedia]
     → Synthèse LLM affichée dans le chat avec sources
```

### Exemple 2 — Créer un doc puis y écrire

```
Utilisateur: "crée un Google Doc 'Veille Nothing Phone'"
ARIA: "Google Doc 'Veille Nothing Phone' créé et ouvert dans Chrome."

Utilisateur: "cherche les dernières actus sur le Nothing Phone 4a et note-les dans le doc"
ARIA: [recherche news + web]
     → Écrit dans le Doc
     → "Résultats ajoutés dans le doc 'Veille Nothing Phone'. [lien]"
```

### Exemple 3 — Recherche + écriture directe

```
Utilisateur: "mets les résultats d'une recherche sur Nantes météo dans le doc"
ARIA: [recherche météo Nantes]
     → Écrit dans le Doc actif
```

### Exemple 4 — Multi-sources

```
Utilisateur: "cherche tout ce que tu peux sur l'IA en 2026 sur plusieurs sources"
ARIA: [web + news + wikipedia simultanément]
     → Synthèse complète dans le chat
```

---

## Installation des dépendances

```bash
# Dans le venv ARIA
.\.venv\Scripts\python.exe -m pip install google-auth google-auth-oauthlib google-api-python-client

# Déjà installés normalement :
# ddgs, requests
```

Ajouter à requirements.txt :
```
google-auth>=2.0
google-auth-oauthlib>=1.0
google-api-python-client>=2.0
```

---

## Prompt Cursor

> Implémenter la recherche web multi-sources et l'intégration Google Docs dans ARIA.
>
> **FICHIER 1 — Créer actions/web_research.py** avec le contenu complet ci-dessus :
> - `ddg_search(query, max_results)` : recherche DDG avec fallback ddgs/duckduckgo_search
> - `ddg_news(query, max_results)` : actualités DDG, timelimit='w' (semaine)
> - `wikipedia_summary(query, lang='fr')` : résumé via API REST Wikipedia officielle
> - `youtube_search(query, max_results)` : via DDG site:youtube.com
> - `multi_search(query, sources, max_per_source)` : parallélisation via ThreadPoolExecutor
> - `format_results_for_llm(results, query)` : format compact pour synthèse LLM
> - `format_results_for_doc(results, query)` : format détaillé pour Google Docs
>
> **FICHIER 2 — Créer actions/gdocs.py** avec le contenu complet ci-dessus :
> - `_active_doc` : variable de session (dict ou None)
> - `get_active_doc()`, `set_active_doc()`, `clear_active_doc()`
> - `is_configured()` : vérifie google_auth
> - `create_doc(title, initial_content)` : crée un Google Doc, retourne {id, title, url}
> - `append_to_doc(doc_id, content)` : ajoute à la fin
> - `write_section_to_doc(doc_id, title, content, heading_level)` : section formatée avec H2
> - `open_doc_in_browser(doc_id)` : ouvre dans Chrome
>
> **FICHIER 3 — llm.py** : ajouter les intents et les fonctions d'exécution :
> - Ajouter dans KNOWN_INTENTS : `recherche_web`, `recherche_actualites`, `recherche_wikipedia`, `recherche_multi`, `gdoc_create`, `gdoc_write_search`, `gdoc_open`, `gdoc_status`
> - Ajouter RECHERCHE_PATTERNS dans `_fast_intent()` avant les patterns existants
> - Ajouter dans `_execute_action()` les elif pour chaque nouvel intent
> - Ajouter les fonctions : `_extract_search_query()`, `_do_web_research()`, `_create_gdoc()`, `_write_search_to_gdoc()`, `_open_gdoc()`, `_gdoc_status()`
> - `_do_web_research()` utilise `generate()` avec `MODELS['heavy']` pour la synthèse, `stream=True`
> - Si le doc actif est défini ET que la phrase contient "dans le doc" / "note" / "écris" → router vers `output='doc'` automatiquement
>
> **FICHIER 4 — ui/index.html (ou styles.css)** : ajouter les classes CSS de présentation
> des résultats de recherche et des cartes Google Doc comme spécifié.
>
> **FICHIER 5 — requirements.txt** : ajouter google-auth, google-auth-oauthlib, google-api-python-client
>
> **Tests à vérifier après implémentation :**
> - "cherche des infos sur ARIA voice assistant" → résultats web synthétisés dans le chat
> - "cherche les actus d'aujourd'hui sur l'IA" → actualités de la semaine
> - "c'est quoi l'avionique" → résumé Wikipedia en français
> - "crée un Google Doc 'test'" → si Google configuré: crée et ouvre ; si non: message d'aide clair
> - "note les résultats dans le doc" après une recherche → écrit dans le doc actif
>
> Créer : actions/web_research.py, actions/gdocs.py
> Modifier : llm.py, requirements.txt, ui/index.html
