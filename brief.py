"""Brief quotidien (master-doc §3.3)."""

from __future__ import annotations

import logging
from datetime import datetime

import yaml

import app_paths
import memory_engine
from actions.weather import get_current, get_current_free
from actions.web_search import search_news

logger = logging.getLogger(__name__)


def _config() -> dict:
    with app_paths.config_path().open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def generate_daily_brief() -> str:
    import api_keys

    cfg = _config()
    parts = []
    now = datetime.now()
    parts.append(f"Voici ton brief du {now.strftime('%A %d %B')}.")

    city = cfg.get("city", "Couëron")
    status = api_keys.check_status("openweather")
    weather_data = get_current(city) if status["status"] == "ok" else get_current_free(city)
    if isinstance(weather_data, dict) and "error" not in weather_data:
        parts.append(
            f"Côté météo : {weather_data.get('description')}, "
            f"{weather_data.get('temp')}°C (ressenti {weather_data.get('feels_like')}°C), "
            f"vent à {weather_data.get('wind')} km/h."
        )

    try:
        from actions import gcalendar

        events = gcalendar.get_today_events()
        if events:
            event_lines = [f"{e['time']} : {e['title']}" for e in events]
            parts.append("Au programme aujourd'hui : " + ", ".join(event_lines) + ".")
        else:
            parts.append("Pas d'événement particulier prévu aujourd'hui.")
    except Exception:
        pass

    news_results = search_news("actualité France", max_results=3)
    if news_results:
        titles = [r.get("title", "") for r in news_results[:3] if r.get("title")]
        if titles:
            parts.append("En actualité : " + " ; ".join(titles) + ".")

    prefs = memory_engine.get_engine().profile.get("preferences", {})
    if prefs.get("next_flight_date") == now.strftime("%Y-%m-%d"):
        icao = prefs.get("home_icao", cfg.get("home_icao", "LFRS"))
        try:
            from actions.aviation import get_metar

            metar = get_metar(icao)
            if metar:
                parts.append(f"Pour ton vol prévu aujourd'hui à {icao} : {metar[:200]}.")
        except Exception:
            pass

    return " ".join(parts)
