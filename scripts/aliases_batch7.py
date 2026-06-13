"""Catalogue alias sites — batch 7 (double + nouveaux sites)."""
from __future__ import annotations


def _merged_before_batch7() -> dict[str, str]:
    import scripts.gen_aliases_extra as gen
    from scripts.aliases_batch3 import get_batch3
    from scripts.aliases_batch4 import get_batch4
    from scripts.aliases_batch5 import get_batch5
    from scripts.aliases_batch6 import get_batch6

    merged = dict(gen.EXTRA)
    for fn in (get_batch3, get_batch4, get_batch5, get_batch6):
        for key, domain in fn().items():
            merged.setdefault(key, domain)
    return merged


def get_batch7() -> dict[str, str]:
    d: dict[str, str] = {}
    prior = _merged_before_batch7()
    existing: set[str] = set(prior.keys())

    def add_unique(alias: str, domain: str) -> None:
        key = alias.strip().lower()
        if key not in existing:
            d[key] = domain
            existing.add(key)

    def add(alias: str, domain: str) -> None:
        d[alias.strip().lower()] = domain
        existing.add(alias.strip().lower())

    def adds(items: dict[str, str]) -> None:
        for k, v in items.items():
            add(k, v)

    # Variantes vocales pour tout le catalogue existant
    for alias, domain in prior.items():
        add_unique(f"open {alias}", domain)

    # ── Nouveaux sites (batch 7) ──
    adds({
        "claude ai": "claude.ai", "claude": "claude.ai", "anthropic claude": "claude.ai",
        "chatgpt": "chatgpt.com", "chat gpt": "chatgpt.com", "openai chat": "chatgpt.com",
        "gemini google": "gemini.google.com", "google gemini": "gemini.google.com",
        "copilot microsoft": "copilot.microsoft.com", "microsoft copilot": "copilot.microsoft.com",
        "perplexity ai": "perplexity.ai", "perplexity": "perplexity.ai",
        "poe ai": "poe.com", "poe": "poe.com", "character ai": "character.ai",
        "character.ai": "character.ai", "jan ai": "jan.ai", "lm studio": "lmstudio.ai",
        "lmstudio": "lmstudio.ai", "ollama": "ollama.com", "ollama ai": "ollama.com",
        "huggingface chat": "huggingface.co/chat", "hf chat": "huggingface.co/chat",
        "replicate": "replicate.com", "together ai": "together.ai", "togetherai": "together.ai",
        "groq cloud": "groq.com", "groq": "groq.com", "fireworks ai": "fireworks.ai",
        "mistral ai": "mistral.ai", "mistral": "mistral.ai", "cohere ai": "cohere.com",
        "deepseek": "deepseek.com", "deep seek": "deepseek.com", "qwen ai": "qwen.ai",
        "cursor ai": "cursor.com", "cursor ide": "cursor.com", "windsurf ide": "codeium.com/windsurf",
        "windsurf": "codeium.com/windsurf", "codeium": "codeium.com", "tabnine": "tabnine.com",
        "github copilot": "github.com/features/copilot", "copilot github": "github.com/features/copilot",
        "bolt new": "bolt.new", "bolt": "bolt.new", "v0 dev": "v0.dev", "v0": "v0.dev",
        "lovable dev": "lovable.dev", "lovable": "lovable.dev", "replit agent": "replit.com",
        "replit": "replit.com", "stackblitz": "stackblitz.com", "codesandbox": "codesandbox.io",
        "code sandbox": "codesandbox.io", "glitch": "glitch.com", "fly io": "fly.io",
        "flyio": "fly.io", "railway app": "railway.app", "railway": "railway.app",
        "render com": "render.com", "render": "render.com", "supabase": "supabase.com",
        "planetscale": "planetscale.com", "neon tech": "neon.tech", "neon db": "neon.tech",
        "turso": "turso.tech", "upstash": "upstash.com", "cloudflare workers": "workers.cloudflare.com",
        "vercel ai": "vercel.com/ai", "openrouter": "openrouter.ai", "open router": "openrouter.ai",
        "cursor docs": "docs.cursor.com", "aria assistant": "github.com/mathisplassartginnain10-a11y/aria",
    })

    # ── Santé & bien-être ──
    adds({
        "doctolib": "doctolib.fr", "docteur lib": "doctolib.fr", "ameli": "ameli.fr",
        "assurance maladie": "ameli.fr", "sante publique france": "santepubliquefrance.fr",
        "has sante": "has-sante.fr", "vidal": "vidal.fr", "doctissimo": "doctissimo.fr",
        "passeport sante": "passeportsante.net", "webmd": "webmd.com", "mayo clinic": "mayoclinic.org",
        "mayoclinic": "mayoclinic.org", "healthline": "healthline.com", "medlineplus": "medlineplus.gov",
        "nih": "nih.gov", "pubmed": "pubmed.ncbi.nlm.nih.gov", "ncbi": "ncbi.nlm.nih.gov",
        "who": "who.int", "oms": "who.int", "cdc": "cdc.gov", "fda": "fda.gov",
        "calendly sante": "calendly.com", "mind": "mind.org.uk", "headspace": "headspace.com",
        "calm app": "calm.com", "calm": "calm.com", "betterhelp": "betterhelp.com",
        "doctolib pro": "pro.doctolib.fr", "qare": "qare.fr", "livi": "livi.fr",
        "medadom": "medadom.com", "hellocare": "hellocare.com", "mymedi": "mymedi.fr",
    })

    # ── Sport & clubs (Europe) ──
    adds({
        "psg": "psg.fr", "paris saint germain": "psg.fr", "om": "om.fr", "ol": "ol.fr",
        "olympique lyonnais": "ol.fr", "olympique marseille": "om.fr", "asse": "asse.fr",
        "saint etienne foot": "asse.fr", "losc": "losc.fr", "lille foot": "losc.fr",
        "rc lens": "rclens.fr", "lens foot": "rclens.fr", "stade rennais": "staderennais.com",
        "rennes foot": "staderennais.com", "fc nantes": "fcnantes.com", "nantes foot": "fcnantes.com",
        "real madrid": "realmadrid.com", "barcelona fc": "fcbarcelona.com", "fc barcelona": "fcbarcelona.com",
        "manchester united": "manutd.com", "man utd": "manutd.com", "manchester city": "mancity.com",
        "man city": "mancity.com", "liverpool fc": "liverpoolfc.com", "liverpool": "liverpoolfc.com",
        "arsenal": "arsenal.com", "chelsea fc": "chelseafc.com", "chelsea": "chelseafc.com",
        "tottenham": "tottenhamhotspur.com", "spurs": "tottenhamhotspur.com", "bayern munich": "fcbayern.com",
        "bayern": "fcbayern.com", "borussia dortmund": "bvb.de", "bvb": "bvb.de", "juventus": "juventus.com",
        "ac milan": "acmilan.com", "milan ac": "acmilan.com", "inter milan": "inter.it",
        "inter milano": "inter.it", "as roma": "asroma.com", "napoli": "sscnapoli.it",
        "atletico madrid": "atleticodemadrid.com", "atletico": "atleticodemadrid.com",
        "formula 1": "formula1.com", "f1": "formula1.com", "motogp": "motogp.com",
        "moto gp": "motogp.com", "wrc": "wrc.com", "rallye wrc": "wrc.com",
        "roland garros": "rolandgarros.com", "roland-garros": "rolandgarros.com",
        "wimbledon": "wimbledon.com", "us open tennis": "usopen.org", "australian open": "ausopen.com",
        "tour de france": "letour.fr", "letour": "letour.fr", "ironman": "ironman.com",
        "strava": "strava.com", "runkeeper": "runkeeper.com", "nike run club": "nike.com/nrc-app",
        "nrc": "nike.com/nrc-app", "decathlon coach": "decathlon.fr", "all trails": "alltrails.com",
        "alltrails": "alltrails.com", "komoot": "komoot.com", "garmin connect": "connect.garmin.com",
    })

    # ── Médias FR récents & streaming ──
    adds({
        "france tv": "france.tv", "francetv": "france.tv", "franceinfo": "franceinfo.fr",
        "france info": "franceinfo.fr", "bfmtv": "bfmtv.com", "bfm tv": "bfmtv.com",
        "bfm business": "bfmbusiness.bfmtv.com", "cnews": "cnews.fr", "lci": "lci.fr",
        "france24": "france24.com", "france 24": "france24.com", "rfi": "rfi.fr",
        "tv5monde": "tv5monde.com", "tv5 monde": "tv5monde.com", "arte tv": "arte.tv",
        "canal plus": "canalplus.com", "canal+": "canalplus.com", "m6 plus": "m6.fr",
        "tf1 plus": "tf1.fr", "rmc sport": "rmcsport.bfmtv.com", "eurosport fr": "eurosport.fr",
        "prime video fr": "primevideo.com", "disney plus fr": "disneyplus.com",
        "max hbo": "max.com", "hbo max": "max.com", "paramount plus fr": "paramountplus.com",
        "apple tv plus": "tv.apple.com", "apple tv+": "tv.apple.com", "molotov": "molotov.tv",
        "salto": "salto.fr", "ocs": "ocs.fr", "canal plus sport": "canalplus.com/sport",
        "rmc story": "rmcstory.bfmtv.com", "rmc decouverte": "rmcdecouverte.bfmtv.com",
        "gulli": "gulli.fr", "tiji": "tiji.fr", "pokémon tv": "watch.pokemon.com",
    })

    # ── npm batch 7 ──
    npm7 = [
        "@ai-sdk/openai", "@ai-sdk/anthropic", "ai", "vllm", "langchain", "@langchain/openai",
        "@langchain/anthropic", "@langchain/community", "llamaindex", "@llamaindex/core",
        "chromadb-default-embed", "@xenova/transformers", "onnxruntime-node", "sharp",
        "@modelcontextprotocol/sdk", "mcp-client", "zod-to-json-schema", "instructor",
        "openai-edge", "@supabase/ssr", "@supabase/auth-ui-react", "drizzle-orm",
        "@tanstack/start", "vinxi", "nitro", "h3", "unjs", "ufo", "defu", "pathe",
        "ofetch", "unstorage", "radix-vue", "shadcn-vue", "nuxt-ui", "primevue",
        "quasar", "ionic-vue", "capacitor", "@capacitor/core", "@ionic/react",
        "tamagui", "nativewind", "expo-router", "expo-sqlite", "react-native-vision-camera",
        "react-native-mmkv", "zustand", "jotai", "valtio", "xstate", "@xstate/react",
        "trpc", "@trpc/server", "@trpc/client", "orpc", "effect", "@effect/schema",
        "neverthrow", "ts-pattern", "arktype", "typebox", "@sinclair/typebox",
        "biome", "oxlint", "eslint-plugin-perfectionist", "knip", "syncpack",
        "changesets", "@changesets/changelog-github", "semantic-release", "release-it",
        "vitest-browser", "@vitest/browser", "playwright-core", "puppeteer-core",
        "happy-dom", "linkedom", "cheerio", "node-html-parser", "turndown",
        "remark-gfm", "rehype-highlight", "shiki", "@shikijs/rehype", "mdx-bundler",
        "contentlayer", "@contentlayer/core", "velite", "fumadocs", "nextra",
        "astro", "@astrojs/react", "@astrojs/tailwind", "starlight", "vitepress",
        "docusaurus", "@docusaurus/core", "redoc", "swagger-ui-react", "scalar",
        "hono", "elysia", "express-zod-api", "ts-rest", "nestjs-zod", "fastify-type-provider-zod",
        "bull-board", "@bull-board/api", "graphile-worker", "pg-boss", "temporalio",
        "@temporalio/client", "inngest", "trigger.dev", "@trigger.dev/sdk",
        "stripe-js", "@stripe/react-stripe-js", "lemonsqueezy", "paddle-js",
        "posthog-js", "mixpanel-browser", "@amplitude/analytics-browser", "plausible-tracker",
        "vercel-analytics", "@vercel/analytics", "speed-insights", "@vercel/speed-insights",
        "next-auth", "@auth/core", "lucia", "better-auth", "clerk-react", "@clerk/clerk-react",
        "uploadthing", "@uploadthing/react", "cloudinary-react", "imagekit-javascript",
        "mapbox-gl", "maplibre-gl", "react-map-gl", "deck.gl", "kepler.gl",
        "three-stdlib", "@react-three/fiber", "@react-three/drei", "react-force-graph",
        "cytoscape", "vis-network", "mermaid", "@mermaid-js/mermaid-cli",
        "excalidraw", "@excalidraw/excalidraw", "tldraw", "@tldraw/tldraw",
        "platejs", "@udecode/plate", "tiptap", "@tiptap/react", "@tiptap/starter-kit",
        "lexical", "@lexical/react", "slate", "slate-react", "prosemirror-view",
    ]
    for pkg in npm7:
        add_unique(f"npm {pkg}", f"npmjs.com/package/{pkg}")
        add_unique(f"{pkg} npm", f"npmjs.com/package/{pkg}")

    # ── PyPI batch 7 ──
    pypi7 = [
        "litellm", "instructor", "guidance", "outlines", "sglang", "vllm", "autoawq",
        "auto-gptq", "optimum", "onnxruntime", "sentencepiece", "tokenizers", "safetensors",
        "huggingface-hub", "datasets", "evaluate", "peft", "trl", "diffusers", "accelerate",
        "unsloth", "axolotl", "llama-factory", "torchtune", "mlx-lm", "ollama-python",
        "anthropic", "openai", "google-genai", "mistralai", "cohere", "groq", "together",
        "fireworks-ai", "replicate", "modal", "beam-client", "runpod", "baseten",
        "chromadb", "lancedb", "qdrant-client", "weaviate-client", "pinecone", "milvus",
        "langchain-community", "langchain-openai", "langgraph", "langsmith", "langfuse",
        "llama-index-core", "llama-index-llms-openai", "haystack-ai", "semantic-kernel",
        "crewai", "autogen-agentchat", "pyautogen", "smolagents", "phidata", "agno",
        "mcp", "fastmcp", "pydantic-ai", "instructor", "marvin", "baml-py",
        "whisper", "faster-whisper", "openai-whisper", "speechrecognition", "vosk",
        "piper-tts", "coqui-tts", "edge-tts", "gtts", "pyttsx3", "TTS",
        "opencv-python-headless", "mediapipe", "face-recognition", "deepface", "insightface",
        "ultralytics", "yolov8", "yolov5", "detectron2", "mmdetection", "segment-anything",
        "transformers", "timm", "open-clip-torch", "clip", "sentence-transformers",
        "faiss-cpu", "faiss-gpu", "annoy", "hnswlib", "nmslib", "pymilvus",
        "gradio", "streamlit", "panel", "dash", "nicegui", "reflex", "mesop",
        "fastapi", "starlette", "uvicorn", "gunicorn", "hypercorn", "granian",
        "sqlmodel", "sqlalchemy", "alembic", "asyncpg", "psycopg", "aiosqlite",
        "redis", "aioredis", "celery", "dramatiq", "rq", "huey", "apscheduler",
        "httpx", "aiohttp", "requests", "urllib3", "websockets", "socketio",
        "pydantic", "pydantic-settings", "python-dotenv", "dynaconf", "hydra-core",
        "pytest", "pytest-asyncio", "pytest-cov", "hypothesis", "factory-boy", "faker",
        "ruff", "black", "mypy", "pyright", "basedpyright", "ty", "uv",
        "poetry", "pdm", "pip-tools", "setuptools", "wheel", "build", "twine",
        "mkdocs-material", "sphinx", "pdoc", "interrogate", "coverage", "tox",
        "boto3", "google-cloud-storage", "azure-identity", "minio", "s3fs", "gcsfs",
        "playwright", "selenium", "pyppeteer", "scrapy", "beautifulsoup4", "selectolax",
        "pandas", "polars", "pyarrow", "duckdb", "ibis-framework", "dask", "vaex",
        "numpy", "scipy", "scikit-learn", "xgboost", "lightgbm", "catboost", "statsmodels",
        "matplotlib", "seaborn", "plotly", "bokeh", "altair", "holoviews", "datashader",
        "sympy", "networkx", "geopandas", "shapely", "folium", "pyproj", "rasterio",
        "pywin32", "pyautogui", "keyboard", "mouse", "pynput", "pygetwindow",
        "watchdog", "schedule", "croniter", "pendulum", "arrow", "python-dateutil",
        "cryptography", "bcrypt", "passlib", "pyjwt", "authlib", "python-jose",
        "pillow", "imageio", "moviepy", "pydub", "librosa", "soundfile", "audioread",
        "rich", "click", "typer", "loguru", "structlog", "colorama", "tqdm",
    ]
    for pkg in pypi7:
        add_unique(f"pypi {pkg}", f"pypi.org/project/{pkg}")
        add_unique(f"{pkg} pypi", f"pypi.org/project/{pkg}")

    # ── Villes mondiales (wiki) ──
    world_cities = [
        "tokyo", "delhi", "shanghai", "sao paulo", "mexico city", "cairo", "dhaka",
        "mumbai", "beijing", "osaka", "karachi", "chongqing", "istanbul", "manila",
        "tianjin", "moscow", "lahore", "bangalore", "paris", "bogota", "jakarta",
        "chennai", "lima", "bangkok", "seoul", "nagoya", "hyderabad", "london",
        "tehran", "chicago", "chengdu", "nanjing", "wuhan", "ho chi minh city",
        "luanda", "ahmedabad", "kuala lumpur", "hong kong", "baghdad", "riyadh",
        "shenzhen", "singapore", "santiago", "st petersburg", "yangon", "casablanca",
        "sydney", "melbourne", "montreal", "toronto", "vancouver", "calgary", "ottawa",
        "dubai", "abu dhabi", "doha", "kuwait city", "amman", "beirut", "tel aviv",
        "jerusalem", "athens", "thessaloniki", "bucharest", "sofia", "belgrade",
        "zagreb", "ljubljana", "bratislava", "prague", "warsaw", "krakow", "gdansk",
        "budapest", "vienna", "salzburg", "zurich", "geneva", "basel", "bern",
        "brussels", "antwerp", "ghent", "amsterdam", "rotterdam", "the hague",
        "copenhagen", "stockholm", "gothenburg", "oslo", "bergen", "helsinki",
        "tampere", "dublin", "cork", "lisbon", "porto", "madrid", "barcelona",
        "valencia", "seville", "bilbao", "milan", "rome", "naples", "turin",
        "florence", "venice", "munich", "hamburg", "cologne", "frankfurt", "stuttgart",
        "dusseldorf", "dortmund", "essen", "leipzig", "dresden", "hanover",
        "new york", "los angeles", "houston", "phoenix", "philadelphia", "san antonio",
        "san diego", "dallas", "san jose", "austin", "jacksonville", "fort worth",
        "columbus", "charlotte", "san francisco", "indianapolis", "seattle", "denver",
        "washington", "boston", "nashville", "detroit", "portland", "las vegas",
        "miami", "atlanta", "minneapolis", "tampa", "orlando", "cleveland", "pittsburgh",
        "buenos aires", "cordoba", "rosario", "santiago chile", "valparaiso",
        "montevideo", "asuncion", "la paz", "sucre", "quito", "guayaquil", "caracas",
        "medellin", "cali", "havana", "san juan", "panama city", "san jose costa rica",
        "guatemala city", "san salvador", "tegucigalpa", "managua", "kingston",
        "nairobi", "addis ababa", "dar es salaam", "kampala", "kigali", "accra",
        "lagos", "ibadan", "kinshasa", "johannesburg", "cape town", "durban",
        "pretoria", "maputo", "harare", "lusaka", "windhoek", "gaborone",
        "algiers", "tunis", "tripoli", "rabat", "marrakech", "fes", "tangier",
        "alexandria", "giza", "luxor", "marrakesh", "dakar", "abidjan", "bamako",
        "ouagadougou", "niamey", "n djamena", "khartoum", "juba", "mogadishu",
        "antananarivo", "port louis", "victoria seychelles", "prague old town",
        "krakow old town", "bruges", "ghent belgium", "salzburg austria",
        "innsbruck", "graz", "linz", "luxembourg city", "monaco", "andorra la vella",
        "san marino", "vatican city", "malta valletta", "nicosia", "paphos",
        "split croatia", "dubrovnik", "zadar", "sarajevo", "skopje", "tirana",
        "podgorica", "chisinau", "minsk", "kiev", "kyiv", "lviv", "odessa",
        "kharkiv", "dnipro", "tbilisi", "yerevan", "baku", "almaty", "astana",
        "tashkent", "bishkek", "dushanbe", "ashgabat", "ulaanbaatar", "ulaan baatar",
        "ulaanbaatar mongolia", "kathmandu", "pokhara", "thimphu", "colombo",
        "kandy", "male maldives", "port moresby", "suva", "apia", "nuku alofa",
        "auckland", "wellington", "christchurch", "queenstown", "perth", "adelaide",
        "brisbane", "gold coast", "canberra", "hobart", "darwin", "cairns",
    ]
    for city in world_cities:
        slug = city.replace(" ", "_").replace("-", "_")
        add_unique(f"ville {city}", f"fr.wikipedia.org/wiki/{slug.title().replace('_', '_')}")
        add_unique(f"city {city}", f"en.wikipedia.org/wiki/{slug.title().replace('_', '_')}")
        add_unique(f"wiki ville {city}", f"fr.wikipedia.org/wiki/{slug.title().replace('_', '_')}")

    # ── Aéroports IATA ──
    airports = {
        "cdg": "parisaeroport.fr", "ory": "parisaeroport.fr", "lhr": "heathrow.com",
        "lgw": "gatwickairport.com", "stn": "stanstedairport.com", "ams": "schiphol.nl",
        "fra": "frankfurt-airport.com", "muc": "munich-airport.com", "zrh": "zurich-airport.com",
        "gva": "gva.ch", "fcO": "adr.it", "mxp": "milanoairport.com", "mad": "aena.es",
        "bcn": "aena.es", "lis": "ana.pt", "dub": "dublinairport.com", "bru": "brusselsairport.be",
        "cph": "cph.dk", "arn": "swedavia.se", "osl": "avinor.no", "hel": "finavia.fi",
        "waw": "lot.com", "prg": "prg.aero", "bud": "bud.hu", "vie": "viennaairport.com",
        "ist": "istairport.com", "saw": "sabihaairport.com", "dxb": "dubaiairports.ae",
        "auh": "abudhabiairport.ae", "doh": "dohahamadairport.com", "jfk": "jfkairport.com",
        "lga": "laguardiaairport.com", "ewr": "newarkairport.com", "ord": "flychicago.com",
        "lax": "flylax.com", "sfo": "flysfo.com", "sea": "portseattle.org",
        "miami airport": "miami-airport.com", "atl": "atl.com", "dfw": "dfwairport.com",
        "iah": "fly2houston.com", "den": "flydenver.com", "phx": "skyharbor.com",
        "las": "harryreidairport.com", "boston logan": "massport.com",
        "yyz": "torontopearson.com", "yul": "admtl.com", "yvr": "yvr.ca",
        "gru": "gru.com.br", "gig": "riogaleao.com", "eze": "aa2000.com.ar",
        "scl": "nuevopudahuel.cl", "bog": "eldorado.aero", "lim": "lap.com.pe",
        "nrt": "narita-airport.jp", "hnd": "tokyo-haneda.com", "kix": "kansai-airport.or.jp",
        "icn": "airport.kr", "pvg": "shairport.com", "pek": "bcia.com.cn",
        "hkg": "hongkongairport.com", "sin": "changiairport.com", "bkk": "suvarnabhumi.airport",
        "kul": "klia.com.my", "cgk": "soekarnohatta-airport.co.id", "mnl": "naia.gov.ph",
        "syd": "sydneyairport.com", "mel": "melbourneairport.com.au", "akl": "aucklandairport.co.nz",
        "jnb": "airports.co.za", "cpt": "airports.co.za", "nbo": "kaa.go.ke",
        "add": "addisairport.com", "cai": "cairo-airport.com", "cmn": "onda.ma",
        "alg": "aeroportalger.dz", "tun": "oaca.nat.tn", "los": "faan.gov.ng",
    }
    for code, domain in airports.items():
        add_unique(f"aeroport {code}", domain)
        add_unique(f"airport {code}", domain)
        add_unique(f"vol {code}", domain)

    # ── Subreddits batch 7 ──
    subs7 = [
        "ArtificialInteligence", "MachineLearning", "deeplearning", "LanguageTechnology",
        "LocalLLaMA", "ollama", "OpenAI", "ChatGPT", "ClaudeAI", "singularity",
        "Futurology", "technology", "programming", "learnprogramming", "coding",
        "webdev", "javascript", "typescript", "reactjs", "nextjs", "vuejs", "sveltejs",
        "node", "python", "rust", "golang", "csharp", "java", "kotlin", "swift",
        "androiddev", "iOSProgramming", "FlutterDev", "reactnative", "expo",
        "homelab", "selfhosted", "docker", "kubernetes", "devops", "sysadmin",
        "netsec", "privacy", "vpn", "tor", "crypto", "Bitcoin", "ethereum",
        "personalfinance", "financialindependence", "Fire", "investing", "stocks",
        "wallstreetbets", "options", "daytrading", "algotrading",
        "travel", "solotravel", "backpacking", "digitalnomad", "expats",
        "france", "paris", "europe", "AskEurope", "AskFrance",
        "cooking", "MealPrepSunday", "recipes", "food", "Coffee", "tea",
        "fitness", "bodyweightfitness", "running", "cycling", "swimming",
        "photography", "analog", "filmmakers", "videography", "editors",
        "musicproduction", "WeAreTheMusicMakers", "audioengineering", "guitar", "piano",
        "gaming", "pcgaming", "PS5", "XboxSeriesX", "NintendoSwitch", "Steam",
        "buildapc", "battlestations", "MechanicalKeyboards", "monitors",
        "cars", "electricvehicles", "teslamotors", "formula1", "MotoGP",
        "aviation", "flying", "homeassistant", "smarthome", "3Dprinting",
        "woodworking", "DIY", "HomeImprovement", "InteriorDesign", "malelivingspace",
        "books", "suggestmeabook", "Fantasy", "scifi", "horrorlit",
        "anime", "manga", "OnePiece", "Naruto", "AttackOnTitan", "JujutsuKaisen",
        "movies", "television", "netflix", "hbo", "Marvel", "StarWars",
        "soccer", "football", "nba", "nfl", "baseball", "hockey", "tennis",
        "science", "space", "astronomy", "physics", "chemistry", "biology",
        "history", "AskHistorians", "geography", "MapPorn", "EarthPorn",
        "todayilearned", "explainlikeimfive", "NoStupidQuestions", "OutOfTheLoop",
        "LifeProTips", "YouShouldKnow", "coolguides", "dataisbeautiful",
    ]
    for sub in subs7:
        add_unique(f"r {sub}", f"reddit.com/r/{sub}")
        add_unique(f"reddit {sub}", f"reddit.com/r/{sub}")

    return d
