import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, quote_plus

import requests
import yaml
from playwright.sync_api import Browser, Page, Playwright, sync_playwright
import app_paths
from actions.alias_store import lookup as lookup_extra_alias

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
EDGE_PATH64 = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"

_CONFIG_PATH = app_paths.config_path()
with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

MODEL = _config.get("model", "qwen3:14b")
BROWSER_CHANNEL = _config.get("browser", "chrome")
HEADLESS = _config.get("browser_headless", False)
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

_playwright: Playwright | None = None
_browser: Browser | None = None
_page: Page | None = None


def get_page() -> Page:
    global _playwright, _browser, _page
    if _browser is None or not _browser.is_connected():
        _playwright = sync_playwright().start()
        launch_kwargs = {"headless": HEADLESS}
        if BROWSER_CHANNEL in ("chrome", "msedge"):
            launch_kwargs["channel"] = BROWSER_CHANNEL
        else:
            launch_kwargs["channel"] = "chrome"
        try:
            _browser = _playwright.chromium.launch(**launch_kwargs)
        except Exception:
            logger.warning("Chrome channel unavailable, falling back to chromium")
            _browser = _playwright.chromium.launch(headless=HEADLESS)
        _page = _browser.new_page()
    elif _page is None or _page.is_closed():
        _page = _browser.new_page()
    return _page


# --- Contexte persistant authentifié (session Google conservée) -------------
_persist_pw: Playwright | None = None
_persist_ctx = None
_persist_page: Page | None = None


def get_authenticated_page() -> Page:
    """Page Playwright avec profil PERSISTANT dédié à ARIA.

    La session Google (et autres logins) est conservée dans data/browser_profile,
    donc l'utilisateur ne se connecte qu'une seule fois. Profil séparé du Chrome
    principal -> pas de conflit de verrou de profil."""
    global _persist_pw, _persist_ctx, _persist_page
    if _persist_ctx is None:
        _persist_pw = sync_playwright().start()
        profile_dir = str(app_paths.data_dir() / "browser_profile")
        os.makedirs(profile_dir, exist_ok=True)
        kwargs = {
            "headless": False,
            "args": ["--no-first-run", "--no-default-browser-check", "--start-maximized"],
            "no_viewport": True,
        }
        try:
            _persist_ctx = _persist_pw.chromium.launch_persistent_context(
                profile_dir, channel="chrome", **kwargs
            )
        except Exception:
            logger.warning("Chrome indisponible pour le profil persistant, fallback chromium")
            _persist_ctx = _persist_pw.chromium.launch_persistent_context(profile_dir, **kwargs)
        _persist_page = _persist_ctx.pages[0] if _persist_ctx.pages else _persist_ctx.new_page()
    elif _persist_page is None or _persist_page.is_closed():
        _persist_page = _persist_ctx.new_page()
    return _persist_page


def _needs_google_login(page: Page) -> bool:
    url = page.url or ""
    return "accounts.google.com" in url or "ServiceLogin" in url or "signin" in url


def write_in_google_doc(content: str, title: str | None = None) -> str:
    """Crée un nouveau Google Doc et y écrit `content`.

    Nécessite d'être connecté à Google (1re fois : la fenêtre s'ouvre sur la page
    de connexion, l'utilisateur se connecte, puis la session est mémorisée)."""
    if not content or not content.strip():
        return "Que veux-tu que j'écrive dans le doc ?"
    try:
        page = get_authenticated_page()
        page.goto("https://docs.google.com/document/create",
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)

        if _needs_google_login(page):
            return ("Connecte-toi à ton compte Google dans la fenêtre qui vient de s'ouvrir, "
                    "puis redemande-moi d'écrire dans le doc (je m'en souviendrai ensuite).")

        try:
            page.wait_for_selector(".kix-appview-editor", timeout=30000)
        except Exception:
            logger.warning("Éditeur Google Docs non détecté, tentative de saisie quand même")
        page.wait_for_timeout(800)

        # Focus le corps du document
        try:
            page.locator(".kix-appview-editor").click(timeout=5000)
        except Exception:
            vp = page.viewport_size or {"width": 1280, "height": 800}
            page.mouse.click(vp["width"] // 2, vp["height"] // 3)
        page.wait_for_timeout(300)

        if title:
            page.keyboard.type(title, delay=8)
            page.keyboard.press("Enter")
            page.keyboard.press("Enter")
        page.keyboard.type(content, delay=6)
        logger.info("Texte écrit dans Google Docs (%d caractères)", len(content))
        short = content[:60] + ("…" if len(content) > 60 else "")
        return f"C'est écrit dans Google Docs : « {short} »"
    except Exception as exc:
        logger.error("write_in_google_doc error: %s", exc)
        return f"Erreur Google Docs : {exc}"


def resolve_site_url(site_name: str) -> str:
    """
    Résout n'importe quel nom de site en URL.
    Fonctionne pour des millions de sites sans liste hardcodée.
    """
    name = site_name.strip().lower()

    if name.startswith("http://") or name.startswith("https://"):
        return site_name

    if "." in name and " " not in name:
        return f"https://{name}"

    aliases = {
        "x": "x.com", "twitter": "x.com", "fb": "facebook.com",
        "insta": "instagram.com", "ig": "instagram.com",
        "yt": "youtube.com", "tube": "youtube.com",
        "tt": "tiktok.com", "snap": "snapchat.com",
        "li": "linkedin.com", "reddit": "reddit.com",
        "discord": "discord.com", "twitch": "twitch.tv",
        "pinterest": "pinterest.fr",
        "spotify": "open.spotify.com", "deezer": "deezer.com",
        "netflix": "netflix.com", "prime": "primevideo.com",
        "disney": "disneyplus.com", "canal": "canalplus.com",
        "arte": "arte.tv", "ina": "ina.fr", "tf1": "tf1.fr",
        "france 2": "france.tv", "france 3": "france.tv",
        "molotov": "molotov.tv", "soundcloud": "soundcloud.com",
        "gh": "github.com", "gl": "gitlab.com",
        "so": "stackoverflow.com", "sf": "stackoverflow.com",
        "mdn": "developer.mozilla.org", "devdocs": "devdocs.io",
        "npm": "npmjs.com", "pypi": "pypi.org",
        "vercel": "vercel.com", "netlify": "netlify.com",
        "render": "render.com", "railway": "railway.app",
        "hf": "huggingface.co", "colab": "colab.research.google.com",
        "kaggle": "kaggle.com", "replit": "replit.com",
        "codepen": "codepen.io", "jsfiddle": "jsfiddle.net",
        "claude": "claude.ai", "chatgpt": "chatgpt.com",
        "gpt": "chatgpt.com", "gemini": "gemini.google.com",
        "copilot": "copilot.microsoft.com", "mistral": "chat.mistral.ai",
        "perplexity": "perplexity.ai", "pplx": "perplexity.ai",
        "groq": "groq.com", "ollama": "ollama.com",
        "midjourney": "midjourney.com", "stability": "stability.ai",
        "skybriefing": "skybriefing.com",
        "sia": "sia.aviation-civile.gouv.fr",
        "aviation weather": "aviationweather.gov",
        "avwx": "avwx.rest", "metar": "aviationweather.gov",
        "notam": "notams.aim.faa.gov",
        "liveatc": "liveatc.net",
        "flightradar": "flightradar24.com", "fr24": "flightradar24.com",
        "flightaware": "flightaware.com",
        "skyvector": "skyvector.com",
        "windy": "windy.com", "ventusky": "ventusky.com",
        "meteoblue": "meteoblue.com",
        "dgac": "dgac.fr",
        "meteo": "meteofrance.com", "météo": "meteofrance.com",
        "meteo france": "meteofrance.com",
        "accuweather": "accuweather.com",
        "weather": "weather.com",
        "lemonde": "lemonde.fr", "le monde": "lemonde.fr",
        "lefigaro": "lefigaro.fr", "figaro": "lefigaro.fr",
        "liberation": "liberation.fr", "libé": "liberation.fr",
        "bfm": "bfmtv.com", "cnews": "cnews.fr",
        "france info": "francetvinfo.fr", "franceinfo": "francetvinfo.fr",
        "bbc": "bbc.com", "cnn": "cnn.com", "reuters": "reuters.com",
        "the verge": "theverge.com", "techcrunch": "techcrunch.com",
        "hn": "news.ycombinator.com", "hacker news": "news.ycombinator.com",
        "amazon": "amazon.fr", "cdiscount": "cdiscount.com",
        "fnac": "fnac.com", "darty": "darty.com", "ldlc": "ldlc.com",
        "topachat": "topachat.com", "materiel": "materiel.net",
        "aliexpress": "aliexpress.com", "ebay": "ebay.fr",
        "leboncoin": "leboncoin.fr", "vinted": "vinted.fr",
        "google": "google.fr", "gmail": "mail.google.com",
        "drive": "drive.google.com", "docs": "docs.google.com",
        "sheets": "sheets.google.com", "slides": "slides.google.com",
        "maps": "maps.google.com", "gmaps": "maps.google.com",
        "translate": "translate.google.com", "traduction": "translate.google.com",
        "meet": "meet.google.com", "photos": "photos.google.com",
        "calendar": "calendar.google.com", "agenda": "calendar.google.com",
        "classroom": "classroom.google.com",
        "outlook": "outlook.live.com", "teams": "teams.microsoft.com",
        "onedrive": "onedrive.live.com", "office": "office.com",
        "azure": "portal.azure.com", "bing": "bing.com",
        "wikipedia": "fr.wikipedia.org", "wiki": "fr.wikipedia.org",
        "khan academy": "fr.khanacademy.org", "khan": "fr.khanacademy.org",
        "coursera": "coursera.org", "udemy": "udemy.com",
        "wolfram": "wolframalpha.com", "alpha": "wolframalpha.com",
        "desmos": "desmos.com", "geogebra": "geogebra.org",
        "steam": "store.steampowered.com",
        "epicgames": "epicgames.com", "epic": "epicgames.com",
        "gog": "gog.com", "itch": "itch.io",
        "xbox": "xbox.com", "playstation": "playstation.com",
        "nintendo": "nintendo.fr",
        "msfs": "flightsimulator.com",
        "notion": "notion.so", "obsidian": "obsidian.md",
        "trello": "trello.com", "jira": "atlassian.com",
        "figma": "figma.com", "canva": "canva.com",
        "excalidraw": "excalidraw.com", "drawio": "app.diagrams.net",
        "deepl": "deepl.com", "reverso": "reverso.net",
        "wakatime": "wakatime.com",
        "ameli": "ameli.fr", "impots": "impots.gouv.fr",
        "caf": "caf.fr", "pole emploi": "francetravail.fr",
        "service public": "service-public.fr",
        "legifrance": "legifrance.gouv.fr",
        # Réseaux sociaux supplémentaires
        "mastodon": "mastodon.social", "bluesky": "bsky.app",
        "threads": "threads.net", "bereal": "bereal.com",
        "tumblr": "tumblr.com", "flickr": "flickr.com",
        "vimeo": "vimeo.com", "dailymotion": "dailymotion.com",
        "twitch clips": "clips.twitch.tv", "kick": "kick.com",
        "rumble": "rumble.com", "odysee": "odysee.com",
        "peertube": "joinpeertube.org", "bilibili": "bilibili.com",
        "niconico": "nicovideo.jp", "weibo": "weibo.com",
        "wechat": "web.wechat.com", "telegram": "web.telegram.org",
        "signal": "signal.org", "viber": "viber.com",
        "skype": "web.skype.com", "zoom": "zoom.us",
        "meet jit": "meet.jit.si", "whereby": "whereby.com",
        "clubhouse": "joinclubhouse.com", "substack": "substack.com",
        "medium": "medium.com", "hashnode": "hashnode.com",
        "devto": "dev.to", "dev": "dev.to",
        # Dev supplémentaire
        "bitbucket": "bitbucket.org", "sourceforge": "sourceforge.net",
        "codeberg": "codeberg.org", "gitea": "gitea.io",
        "gist": "gist.github.com", "pastebin": "pastebin.com",
        "hastebin": "hastebin.com", "paste": "paste.ee",
        "regex101": "regex101.com", "regexr": "regexr.com",
        "json": "jsonformatter.curiousconcept.com",
        "jsonlint": "jsonlint.com", "jwt": "jwt.io",
        "base64": "base64encode.org", "md5": "md5hashgenerator.com",
        "caniuse": "caniuse.com", "bundlephobia": "bundlephobia.com",
        "packagephobia": "packagephobia.com", "snyk": "snyk.io",
        "sonarcloud": "sonarcloud.io", "codecov": "codecov.io",
        "travis": "travis-ci.org", "circleci": "circleci.com",
        "jenkins": "jenkins.io", "ansible": "ansible.com",
        "terraform": "registry.terraform.io", "docker": "hub.docker.com",
        "dockerhub": "hub.docker.com", "kubernetes": "kubernetes.io",
        "helm": "helm.sh", "portainer": "portainer.io",
        "nginx": "nginx.org", "apache": "apache.org",
        "digitalocean": "digitalocean.com", "linode": "linode.com",
        "vultr": "vultr.com", "ovh": "ovh.com", "scaleway": "scaleway.com",
        "aws": "aws.amazon.com", "gcp": "console.cloud.google.com",
        "firebase": "console.firebase.google.com",
        "supabase": "supabase.com", "planetscale": "planetscale.com",
        "neon": "neon.tech", "xata": "xata.io",
        "prisma": "prisma.io", "drizzle": "orm.drizzle.team",
        "turso": "turso.tech", "upstash": "upstash.com",
        "redis": "redis.io", "mongodb": "mongodb.com",
        "postgres": "postgresql.org", "mysql": "mysql.com",
        "sqlite": "sqlite.org", "cockroachdb": "cockroachlabs.com",
        "elasticsearch": "elastic.co", "kibana": "elastic.co",
        "grafana": "grafana.com", "prometheus": "prometheus.io",
        "datadog": "datadoghq.com", "sentry": "sentry.io",
        "logtail": "logtail.com", "axiom": "axiom.co",
        "posthog": "posthog.com", "mixpanel": "mixpanel.com",
        "amplitude": "amplitude.com", "hotjar": "hotjar.com",
        "segment": "segment.com", "heap": "heapanalytics.com",
        # Langages / docs
        "python docs": "docs.python.org", "pydocs": "docs.python.org",
        "rust": "doc.rust-lang.org", "rustbook": "doc.rust-lang.org/book",
        "go": "go.dev", "golang": "go.dev",
        "java docs": "docs.oracle.com/en/java",
        "cppreference": "en.cppreference.com",
        "crates": "crates.io", "rubygems": "rubygems.org",
        "packagist": "packagist.org", "nuget": "nuget.org",
        "mvnrepository": "mvnrepository.com",
        "react": "react.dev", "reactjs": "react.dev",
        "vue": "vuejs.org", "vuejs": "vuejs.org",
        "angular": "angular.io", "svelte": "svelte.dev",
        "nextjs": "nextjs.org", "next": "nextjs.org",
        "nuxt": "nuxt.com", "remix": "remix.run",
        "astro": "astro.build", "gatsby": "gatsbyjs.com",
        "tailwind": "tailwindcss.com", "bootstrap": "getbootstrap.com",
        "chakra": "chakra-ui.com", "shadcn": "ui.shadcn.com",
        "radix": "radix-ui.com", "headlessui": "headlessui.com",
        "framer motion": "www.framer.com/motion",
        "gsap": "greensock.com", "threejs": "threejs.org",
        "three": "threejs.org", "d3": "d3js.org",
        "plotly": "plotly.com", "chartjs": "chartjs.org",
        "recharts": "recharts.org", "vega": "vega.github.io",
        "pandas": "pandas.pydata.org", "numpy": "numpy.org",
        "scipy": "scipy.org", "matplotlib": "matplotlib.org",
        "sklearn": "scikit-learn.org", "tensorflow": "tensorflow.org",
        "pytorch": "pytorch.org", "keras": "keras.io",
        "fastai": "fast.ai", "jax": "jax.readthedocs.io",
        "langchain": "python.langchain.com",
        "llamaindex": "docs.llamaindex.ai",
        "unsloth": "unsloth.ai", "trl": "huggingface.co/docs/trl",
        "transformers": "huggingface.co/docs/transformers",
        "diffusers": "huggingface.co/docs/diffusers",
        "flask": "flask.palletsprojects.com",
        "django": "djangoproject.com", "fastapi": "fastapi.tiangolo.com",
        "express": "expressjs.com", "nestjs": "nestjs.com",
        "starlette": "starlette.io", "uvicorn": "uvicorn.org",
        "pydantic": "docs.pydantic.dev", "sqlalchemy": "sqlalchemy.org",
        "celery": "docs.celeryq.dev", "redis py": "redis-py.readthedocs.io",
        # IA supplémentaire
        "anthropic": "anthropic.com", "openai": "platform.openai.com",
        "cohere": "cohere.com", "ai21": "ai21.com",
        "together": "together.ai", "replicate": "replicate.com",
        "modal": "modal.com", "banana": "banana.dev",
        "runpod": "runpod.io", "vast": "vast.ai",
        "paperspace": "paperspace.com", "lambda": "lambdalabs.com",
        "civitai": "civitai.com", "lexica": "lexica.art",
        "playground": "playground.com", "adobe firefly": "firefly.adobe.com",
        "kling": "klingai.com", "runway": "runwayml.com",
        "pika": "pika.art", "sora": "sora.com",
        "elevenlabs": "elevenlabs.io", "murf": "murf.ai",
        "descript": "descript.com", "assemblyai": "assemblyai.com",
        "whisper": "openai.com/research/whisper",
        "gamma": "gamma.app", "tome": "tome.app",
        "beautiful": "beautiful.ai", "pitch": "pitch.com",
        "jasper": "jasper.ai", "copy": "copy.ai",
        "writesonic": "writesonic.com", "anyword": "anyword.com",
        "cursor ai": "cursor.sh", "cursor": "cursor.sh",
        "tabnine": "tabnine.com", "codeium": "codeium.com",
        "continue": "continue.dev", "aider": "aider.chat",
        # Aviation supplémentaire
        "skydemon": "skydemon.com", "garmin pilot": "buy.garmin.com",
        "foreflight": "foreflight.com", "jeppesen": "jeppesen.com",
        "vatsim": "vatsim.net", "ivao": "ivao.aero",
        "pilotedge": "pilotedge.net", "poscon": "poscon.net",
        "say intentions": "sayintentions.ai",
        "airmate": "airmate.aero", "sag": "sia.aviation-civile.gouv.fr",
        "aopa": "aopa.org", "faa": "faa.gov",
        "easa": "easa.europa.eu", "eurocontrol": "eurocontrol.int",
        "autorouter": "autorouter.aero", "ifps": "ifps.eurocontrol.int",
        "atis": "atis.aero", "acars": "acars.aero",
        "chartfox": "chartfox.org",
        "navigraph": "navigraph.com", "simbrief": "simbrief.com",
        "volanta": "volanta.app", "vsr": "vsr.aero",
        "aeroweb": "aviation.meteo.fr",
        "metar taf": "aviationweather.gov/metar",
        "pirep": "aviationweather.gov/pirep",
        "notam faa": "notams.aim.faa.gov",
        "sua": "sua.faa.gov", "tfr": "tfr.faa.gov",
        "airport info": "airportinfo.live",
        "flight plan": "flightplan.aero",
        "little navmap": "albar.de/littlenavmap",
        # Jeux / gaming supplémentaire
        "battle net": "battle.net", "battlenet": "battle.net",
        "uplay": "ubisoft.com", "ubisoft": "ubisoft.com",
        "ea": "ea.com", "origin": "ea.com",
        "rockstar": "rockstargames.com", "bethesda": "bethesda.net",
        "2k": "2k.com", "activision": "activision.com",
        "humble bundle": "humblebundle.com", "fanatical": "fanatical.com",
        "isthereanydeal": "isthereanydeal.com", "gg deals": "gg.deals",
        "protondb": "protondb.com", "lutris": "lutris.net",
        "winehq": "winehq.org", "pcgamingwiki": "pcgamingwiki.com",
        "nexusmods": "nexusmods.com", "moddb": "moddb.com",
        "thunderstore": "thunderstore.io",
        "curseforge": "curseforge.com",
        "modrinth": "modrinth.com",
        "curseforge mc": "www.curseforge.com/minecraft",
        "gamebanana": "gamebanana.com",
        "speedrun": "speedrun.com", "srcom": "speedrun.com",
        "howlongtobeat": "howlongtobeat.com", "hltb": "howlongtobeat.com",
        "metacritic": "metacritic.com", "opencritic": "opencritic.com",
        "ign": "ign.com", "gamespot": "gamespot.com",
        "jeuxvideo": "jeuxvideo.com", "jvc": "jeuxvideo.com",
        "gamekult": "gamekult.com", "millenium": "millenium.org",
        # Finance / crypto
        "binance": "binance.com", "coinbase": "coinbase.com",
        "kraken": "kraken.com", "kucoin": "kucoin.com",
        "coingecko": "coingecko.com", "coinmarketcap": "coinmarketcap.com",
        "tradingview": "tradingview.com", "investing": "investing.com",
        "boursorama": "boursorama.com", "yahoo finance": "finance.yahoo.com",
        "bloomberg": "bloomberg.com", "wsj": "wsj.com",
        "ft": "ft.com", "les echos": "lesechos.fr",
        # Santé
        "doctolib": "doctolib.fr",
        "vidal": "vidal.fr", "who": "who.int",
        "inserm": "inserm.fr", "has": "has-sante.fr",
        # Education supplémentaire
        "pluralsight": "pluralsight.com",
        "oreilly": "oreilly.com", "manning": "manning.com",
        "packt": "packtpub.com", "apress": "apress.com",
        "edx": "edx.org", "mit ocw": "ocw.mit.edu",
        "coursera free": "coursera.org", "fun mooc": "fun-mooc.fr",
        "france université": "fun-mooc.fr",
        "lumni": "lumni.fr", "eduscol": "eduscol.education.fr",
        "education nationale": "education.gouv.fr",
        "parcoursup": "parcoursup.fr", "onisep": "onisep.fr",
        "letudiant": "letudiant.fr", "studyrama": "studyrama.com",
        "chegg": "chegg.com", "quizlet": "quizlet.com",
        "anki": "apps.ankiweb.net", "brainscape": "brainscape.com",
        "duolingo": "duolingo.com", "babbel": "babbel.com",
        "lingvist": "lingvist.com", "pimsleur": "pimsleur.com",
        "reverso context": "context.reverso.net",
        "linguee": "linguee.fr", "wordreference": "wordreference.com",
        "larousse": "larousse.fr", "cnrtl": "cnrtl.fr",
        "btb termium": "btb.termiumplus.gc.ca",
        # Outils supplémentaires
        "airtable": "airtable.com", "coda": "coda.io",
        "clickup": "clickup.com", "asana": "asana.com",
        "linear": "linear.app", "height": "height.app",
        "basecamp": "basecamp.com", "monday": "monday.com",
        "slack": "slack.com", "mattermost": "mattermost.com",
        "zulip": "zulip.com", "rocket chat": "rocket.chat",
        "crisp": "crisp.chat", "intercom": "intercom.com",
        "zendesk": "zendesk.com", "freshdesk": "freshdesk.com",
        "hubspot": "hubspot.com", "salesforce": "salesforce.com",
        "mailchimp": "mailchimp.com", "brevo": "brevo.com",
        "convertkit": "convertkit.com", "beehiiv": "beehiiv.com",
        "stripe": "stripe.com", "paypal": "paypal.com",
        "wise": "wise.com", "revolut": "revolut.com",
        "n8n": "n8n.io", "zapier": "zapier.com",
        "make": "make.com", "pipedream": "pipedream.com",
        "ifttt": "ifttt.com", "automate": "automate.io",
        "typeform": "typeform.com", "tally": "tally.so",
        "google forms": "forms.google.com",
        "surveymonkey": "surveymonkey.com",
        "hotglue": "hotglue.me", "apify": "apify.com",
        "phantombuster": "phantombuster.com",
        "browserless": "browserless.io",
        "puppeteer": "pptr.dev", "playwright": "playwright.dev",
        "selenium": "selenium.dev", "cypress": "cypress.io",
        "testcafe": "testcafe.io", "vitest": "vitest.dev",
        "jest": "jestjs.io", "mocha": "mochajs.org",
        "storybook": "storybook.js.org",
        "chromatic": "chromatic.com",
        # France spécifique
        "france travail": "francetravail.fr",
        "cpf": "mon-cpf.fr", "opco": "opco.fr",
        "urssaf": "urssaf.fr", "inpi": "inpi.fr",
        "insee": "insee.fr", "data gouv": "data.gouv.fr",
        "etalab": "etalab.gouv.fr",
        "france connect": "franceconnect.gouv.fr",
        "mon espace sante": "monespacesante.fr",
        "vitale": "ameli.fr", "carte vitale": "ameli.fr",
        "mairie": "service-public.fr",
        "prefecture": "service-public.fr",
        "permis de conduire": "permisdeconduire.gouv.fr",
        "code de la route": "securite-routiere.gouv.fr",
        "sncf": "sncf-connect.com", "ouigo": "ouigo.com",
        "intercites": "sncf-connect.com",
        "ratp": "ratp.fr", "transilien": "transilien.com",
        "blablacar": "blablacar.fr", "ouibus": "blablacarbus.com",
        "flixbus": "flixbus.fr", "eurolines": "flixbus.fr",
        "air france": "airfrance.fr", "easyjet": "easyjet.com",
        "ryanair": "ryanair.com", "transavia": "transavia.com",
        "booking": "booking.com", "airbnb": "airbnb.fr",
        "tripadvisor": "tripadvisor.fr",
        # Projets Mathi
        "impero": "impero-game.fr",
        "impero-game": "impero-game.fr",
        "impero game": "impero-game.fr",
    }

    if name in aliases:
        return f"https://{aliases[name]}"

    extra = lookup_extra_alias(name)
    if extra:
        return f"https://{extra}"

    for alias, domain in aliases.items():
        if alias in name or name in alias:
            return f"https://{domain}"

    clean = name.replace(" ", "").replace("'", "")
    if clean in aliases:
        return f"https://{aliases[clean]}"

    french_keywords = ["france", "français", "gouv", "actu", "info"]
    if any(k in name for k in french_keywords):
        return f"https://{clean}.fr"

    return f"https://{clean}.com"


def open_site(site_name: str, browser: str | None = None) -> str:
    """Ouvre un site par son nom — optionnellement dans un navigateur spécifique."""
    url = resolve_site_url(site_name)
    return open_url(url, browser=browser)


def search_within_site(site: str, query: str) -> str:
    """Recherche à l'intérieur d'un site spécifique."""
    q = quote(query)
    site_lower = site.lower().strip()

    site_search_patterns = {
        "youtube": f"https://www.youtube.com/results?search_query={q}",
        "github": f"https://github.com/search?q={q}",
        "stackoverflow": f"https://stackoverflow.com/search?q={q}",
        "reddit": f"https://www.reddit.com/search/?q={q}",
        "amazon": f"https://www.amazon.fr/s?k={q}",
        "wikipedia": f"https://fr.wikipedia.org/wiki/Special:Search?search={q}",
        "wiki": f"https://fr.wikipedia.org/wiki/Special:Search?search={q}",
        "npm": f"https://www.npmjs.com/search?q={q}",
        "pypi": f"https://pypi.org/search/?q={q}",
        "notion": f"https://www.notion.so/search?q={q}",
        "twitter": f"https://x.com/search?q={q}",
        "x": f"https://x.com/search?q={q}",
        "twitch": f"https://www.twitch.tv/search?term={q}",
        "spotify": f"https://open.spotify.com/search/{q}",
        "linkedin": f"https://www.linkedin.com/search/results/all/?keywords={q}",
        "ebay": f"https://www.ebay.fr/sch/i.html?_nkw={q}",
        "leboncoin": f"https://www.leboncoin.fr/recherche?text={q}",
        "vinted": f"https://www.vinted.fr/catalog?search_text={q}",
        "fnac": f"https://www.fnac.com/SearchResult/ResultList.aspx?Search={q}",
        "steam": f"https://store.steampowered.com/search/?term={q}",
        "imdb": f"https://www.imdb.com/find?q={q}",
        "allocine": f"https://www.allocine.fr/recherche/?q={q}",
        "google drive": f"https://drive.google.com/drive/search?q={q}",
        "drive": f"https://drive.google.com/drive/search?q={q}",
        "gmail": f"https://mail.google.com/mail/u/0/#search/{q}",
        "google maps": f"https://www.google.com/maps/search/{q}",
        "maps": f"https://www.google.com/maps/search/{q}",
        "google scholar": f"https://scholar.google.com/scholar?q={q}",
        "scholar": f"https://scholar.google.com/scholar?q={q}",
        "arxiv": f"https://arxiv.org/search/?query={q}",
        "huggingface": f"https://huggingface.co/search/full-text?q={q}",
        "hf": f"https://huggingface.co/search/full-text?q={q}",
        "devto": f"https://dev.to/search?q={q}",
        "dev.to": f"https://dev.to/search?q={q}",
        "medium": f"https://medium.com/search?q={q}",
        "coursera": f"https://www.coursera.org/search?query={q}",
        "udemy": f"https://www.udemy.com/courses/search/?q={q}",
        "lemonde": f"https://www.lemonde.fr/recherche/?keywords={q}",
        "figma": f"https://www.figma.com/search?q={q}",
        "canva": f"https://www.canva.com/search?q={q}",
        "jeuxvideo": f"https://www.jeuxvideo.com/recherche/?q={q}",
        "jvc": f"https://www.jeuxvideo.com/recherche/?q={q}",
        "nexusmods": f"https://www.nexusmods.com/search/?gsearch={q}",
        "aviation weather": f"https://aviationweather.gov/metar/data?ids={q}",
        "metar": f"https://aviationweather.gov/metar/data?ids={q}",
        "skyvector": f"https://skyvector.com/?search={q}",
    }

    for key, url in site_search_patterns.items():
        if key in site_lower or site_lower in key:
            return open_url(url)

    site_domain = resolve_site_url(site_lower).replace("https://", "").replace("http://", "").strip("/")
    google_url = f"https://www.google.com/search?q=site:{site_domain}+{quote_plus(query)}"
    return open_url(google_url)


def search_current_page(query: str) -> str:
    """Recherche dans la page actuellement ouverte (Ctrl+F)."""
    try:
        page = get_page()
        page.keyboard.press("Control+f")
        time.sleep(0.3)
        page.keyboard.type(query)
        return f"Recherche '{query}' dans la page"
    except Exception as e:
        logger.exception("In-page search failed")
        return f"Erreur: {e}"


def _get_browser_exe() -> str:
    """Retourne le chemin du navigateur disponible."""
    for path in CHROME_PATHS:
        if os.path.exists(path):
            return path
    for path in (EDGE_PATH64, EDGE_PATH):
        if os.path.exists(path):
            return path
    return "start"


def _resolve_browser_exe(browser: str | None = None) -> str:
    """Retourne l'exécutable du navigateur demandé, ou Chrome/Edge par défaut."""
    if browser:
        browser_lower = browser.lower()
        if "edge" in browser_lower:
            for path in (EDGE_PATH64, EDGE_PATH):
                if os.path.exists(path):
                    return path
        elif "firefox" in browser_lower:
            firefox = r"C:\Program Files\Mozilla Firefox\firefox.exe"
            if os.path.exists(firefox):
                return firefox
        elif "opera" in browser_lower:
            opera = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Opera GX\opera.exe")
            if os.path.exists(opera):
                return opera
    return _get_browser_exe()


def open_url(url: str, browser: str | None = None) -> str:
    """Ouvre une URL dans Chrome/Edge ou le navigateur demandé."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    exe = _resolve_browser_exe(browser)
    try:
        if exe == "start":
            os.startfile(url)
        else:
            subprocess.Popen(
                [exe, url],
                creationflags=CREATE_NO_WINDOW,
            )
        logger.info("URL ouverte: %s (%s)", url, exe)
        return f"Page ouverte : {url}"
    except Exception as exc:
        logger.error("open_url error: %s", exc)
        try:
            os.startfile(url)
            return f"Page ouverte : {url}"
        except Exception as exc2:
            return f"Erreur ouverture: {exc2}"


def search_google(query: str) -> str:
    q = re.sub(r"^(recherche|cherche|google)\s*", "", query, flags=re.I).strip()
    return open_url(f"https://www.google.com/search?q={quote_plus(q)}")


def search_youtube(query: str) -> str:
    q = re.sub(r".*youtube.*?(?:cherche|lance|joue|mets)\s*", "", query, flags=re.I).strip()
    if not q:
        q = re.sub(r".*youtube\s*", "", query, flags=re.I).strip()
    return open_url(f"https://www.youtube.com/results?search_query={quote_plus(q)}")


def youtube_control(action: str) -> str:
    page = get_page()
    action = action.lower().strip()
    mapping = {
        "play": "k", "pause": "k", "lecture": "k", "pause la vidéo": "k",
        "mute": "m", "coupe le son": "m", "son": "m",
        "fullscreen": "f", "plein écran": "f",
        "rewind": "j", "recule": "j",
        "forward": "l", "avance": "l",
    }
    if action in mapping:
        page.keyboard.press(mapping[action])
        return f"YouTube : {action}."
    if action in ("next", "suivante", "suivant", "passe à la suivante"):
        try:
            page.locator(".ytp-next-button").click(timeout=3000)
        except Exception:
            page.keyboard.press("Shift+n")
        return "YouTube : vidéo suivante."
    if "volume" in action and ("monte" in action or "up" in action):
        for _ in range(5):
            page.keyboard.press("ArrowUp")
        return "Volume YouTube augmenté."
    if "volume" in action and ("baisse" in action or "down" in action):
        for _ in range(5):
            page.keyboard.press("ArrowDown")
        return "Volume YouTube diminué."
    page.keyboard.press("k")
    return f"Commande YouTube : {action}."


def spotify_web_control(action: str, query: str = "") -> str:
    page = get_page()
    if "open.spotify.com" not in page.url:
        page.goto("https://open.spotify.com", wait_until="domcontentloaded", timeout=30000)

    action_lower = action.lower()
    if query or "cherche" in action_lower or "lance" in action_lower:
        q = query or re.sub(r".*(?:cherche|lance|joue)\s*", "", action, flags=re.I).strip()
        page.goto(f"https://open.spotify.com/search/{quote_plus(q)}", wait_until="domcontentloaded")
        try:
            page.locator("[data-testid='tracklist-row']").first.click(timeout=8000)
            return f"Spotify : lecture de {q}."
        except Exception:
            return f"Spotify : recherche {q}."
    if action_lower in ("play", "pause", "lecture", "pause"):
        page.keyboard.press("Space")
        return "Spotify : lecture/pause."
    if action_lower in ("next", "suivante", "suivant"):
        page.keyboard.press("Control+ArrowRight")
        return "Spotify : piste suivante."
    if action_lower in ("previous", "précédente", "precedent"):
        page.keyboard.press("Control+ArrowLeft")
        return "Spotify : piste précédente."
    page.keyboard.press("Space")
    return f"Spotify : {action}."


def open_new_tab(url: str | None = None) -> str:
    global _page
    if _browser is None:
        get_page()
    assert _browser is not None
    _page = _browser.new_page()
    if url:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        _page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return f"Nouvel onglet ouvert : {url}."
    return "Nouvel onglet ouvert."


def close_tab() -> str:
    page = get_page()
    page.keyboard.press("Control+w")
    return "Onglet fermé."


def close_browser() -> str:
    global _playwright, _browser, _page
    try:
        if _browser:
            _browser.close()
    except Exception:
        pass
    try:
        if _playwright:
            _playwright.stop()
    except Exception:
        pass
    _browser = None
    _page = None
    _playwright = None
    return "Navigateur fermé."


def get_current_url() -> str:
    page = get_page()
    return page.url


def get_page_title() -> str:
    page = get_page()
    title = page.title()
    return f"Page active : {title}."


def scroll(direction: str, amount: int = 3) -> str:
    page = get_page()
    direction = direction.lower()
    if direction in ("down", "bas", "bas"):
        page.evaluate(f"window.scrollBy(0, {300 * amount})")
    elif direction in ("up", "haut"):
        page.evaluate(f"window.scrollBy(0, {-300 * amount})")
    elif direction in ("top", "haut page"):
        page.keyboard.press("Home")
    elif direction in ("bottom", "bas page"):
        page.keyboard.press("End")
    else:
        page.evaluate(f"window.scrollBy(0, {300 * amount})")
    return f"Défilement {direction}."


def click_element(description: str) -> str:
    page = get_page()
    try:
        page.get_by_text(description, exact=False).first.click(timeout=5000)
        return f"Élément cliqué : {description}."
    except Exception:
        try:
            page.get_by_label(description).first.click(timeout=5000)
            return f"Élément cliqué : {description}."
        except Exception:
            logger.exception("click_element failed")
            return f"Élément introuvable : {description}."


def fill_search_bar(query: str) -> str:
    page = get_page()
    selectors = ["input[type='search']", "input[name='q']", "textarea[name='q']", "input[aria-label*='earch']"]
    for sel in selectors:
        loc = page.locator(sel).first
        if loc.count() > 0:
            loc.fill(query)
            loc.press("Enter")
            return f"Recherche : {query}."
    page.keyboard.type(query)
    page.keyboard.press("Enter")
    return f"Recherche saisie : {query}."


def type_on_current_page(text: str) -> str:
    """Tape du texte dans le champ actif de la page courante."""
    try:
        page = get_page()
        page.keyboard.type(text, delay=30)
        return f"Texte tapé : {text[:50]}..."
    except Exception as e:
        logger.error("Type error: %s", e)
        return f"Erreur: {e}"


def type_and_send(text: str) -> str:
    """Tape du texte ET appuie sur Entrée pour envoyer."""
    try:
        page = get_page()
        page.keyboard.type(text, delay=30)
        page.keyboard.press("Enter")
        return f"Message envoyé : {text[:50]}"
    except Exception as e:
        logger.error("Type and send error: %s", e)
        return f"Erreur: {e}"


def focus_and_type(selector: str, text: str) -> str:
    """Trouve un champ par description et tape dedans."""
    try:
        page = get_page()
        selectors = [
            selector,
            "textarea",
            'input[type="text"]',
            '[contenteditable="true"]',
            '[role="textbox"]',
            ".cm-content",
            "#prompt-textarea",
            '[data-testid="chat-input"]',
            ".ProseMirror",
        ]
        for sel in selectors:
            if not sel:
                continue
            try:
                element = page.locator(sel).first
                if element.is_visible():
                    element.click()
                    element.type(text, delay=30)
                    return f"Texte tapé dans {sel}"
            except Exception:
                continue
        return "Aucun champ de texte trouvé"
    except Exception as e:
        logger.error("Focus and type error: %s", e)
        return f"Erreur: {e}"


def type_in_claude(text: str) -> str:
    """Ouvre Claude.ai et tape un message."""
    try:
        page = get_page()
        if "claude.ai" not in page.url:
            page.goto("https://claude.ai")
            page.wait_for_load_state("networkidle", timeout=10000)
        element = page.locator('[data-testid="chat-input"], .ProseMirror, [contenteditable]').first
        element.click()
        element.type(text, delay=30)
        return "Message tapé dans Claude"
    except Exception as e:
        logger.error("Claude type error: %s", e)
        return f"Erreur Claude: {e}"


def type_in_cursor_composer(text: str) -> str:
    """Ouvre Cursor et envoie un prompt dans Composer."""
    try:
        import time

        import pyautogui
        import pygetwindow as gw
        import pyperclip

        windows = [w for w in gw.getAllWindows() if "cursor" in w.title.lower()]
        if windows:
            windows[0].activate()
            time.sleep(0.5)
        pyautogui.hotkey("ctrl", "i")
        time.sleep(0.8)
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.3)
        return "Prompt envoyé à Cursor Composer"
    except Exception as e:
        logger.error("Cursor composer error: %s", e)
        return f"Erreur Cursor: {e}"


def _summarize_with_ollama(text: str) -> str:
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": f"Résume ce contenu web en 3-4 phrases courtes pour une lecture vocale :\n\n{text[:4000]}",
            }
        ],
        "stream": False,
    }
    try:
        response = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=90)
        response.raise_for_status()
        return response.json()["message"]["content"].strip()
    except (requests.RequestException, KeyError, json.JSONDecodeError):
        logger.exception("Page summarize failed")
        return text[:500]


def read_page_content() -> str:
    page = get_page()
    try:
        body_text = page.inner_text("body")
    except Exception:
        body_text = page.content()[:2000]
    summary = _summarize_with_ollama(body_text)
    return summary


def take_screenshot(save_path: str | None = None) -> str:
    page = get_page()
    if save_path is None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            save_path = tmp.name
    path = Path(save_path)
    page.screenshot(path=str(path), full_page=False)
    return f"Capture navigateur : {path}."


def _extract_site_name(text: str) -> str | None:
    match = re.search(
        r"(?:va sur|ouvre(?:-moi)?|ouvrir|lance(?:-moi)?|démarre(?:-moi)?|mets?(?:-moi)? sur)\s+(.+)",
        text.strip(),
        re.I,
    )
    if not match:
        return None
    site = match.group(1).strip().rstrip(".")
    site = re.sub(r"\s+en route$", "", site, flags=re.I)
    return site or None


def handle(text: str) -> str:
    t = text.lower()

    if "ferme chrome" in t or "ferme le navigateur" in t or "browser_close" in t:
        return close_browser()
    if "ferme" in t and ("onglet" in t or "tab" in t):
        return close_tab()
    if "nouvel onglet" in t or "new tab" in t:
        url_match = re.search(r"https?://\S+|(?:sur |vers )(\S+\.\S+)", text, re.I)
        url = url_match.group(0) if url_match else None
        return open_new_tab(url)

    if "youtube" in t and ("cherche" in t or "joue" in t or "lance" in t or "mets" in t):
        return search_youtube(text)
    if "youtube" in t or "vidéo" in t:
        if any(w in t for w in ("pause", "play", "son", "suivante", "volume", "muet", "coupe")):
            return youtube_control(text)
        return youtube_control("pause")

    if "spotify" in t:
        return spotify_web_control(text)

    if "google" in t and ("recherche" in t or "cherche" in t):
        return search_google(text)

    if "lis" in t and ("page" in t or "cette page" in t or "site" in t):
        return read_page_content()

    if "capture" in t and ("navigateur" in t or "écran" in t or "page" in t):
        return take_screenshot()

    if "défile" in t or "scroll" in t or "descend" in t:
        direction = "down" if "bas" in t or "descend" in t else "up" if "haut" in t else "down"
        return scroll(direction)

    if "titre" in t and "page" in t:
        return get_page_title()

    url_match = re.search(r"(https?://\S+|\b[\w-]+\.(com|fr|org|net|io)\S*)", text, re.I)
    site_name = _extract_site_name(text)

    if site_name and not url_match:
        return open_site(site_name)
    if "va sur" in t or ("ouvre" in t and url_match):
        return open_url(url_match.group(1))

    page_search = re.search(
        r"(?:cherche|trouve|recherche)\s+(.+?)\s+(?:dans|sur)\s+"
        r"(?:la page(?: ouverte)?|cette page|la page actuelle)",
        text.strip(),
        re.I,
    )
    if page_search:
        return search_current_page(page_search.group(1).strip())

    site_search = re.search(
        r"(?:cherche|trouve|recherche)\s+(.+?)\s+(?:sur|dans)\s+(.+?)(?:\.|$)",
        text.strip(),
        re.I,
    )
    if site_search:
        query, site = site_search.group(1).strip(), site_search.group(2).strip()
        if not re.search(r"internet|google\b|la page|cette page", site, re.I):
            return search_within_site(site, query)

    if "recherche" in t or "cherche" in t:
        q = re.sub(r"^(recherche|cherche)\s*(sur google\s*)?", "", text, flags=re.I).strip()
        if q:
            return search_google(q)

    if url_match:
        return open_url(url_match.group(1))

    return "Commande navigateur non reconnue."