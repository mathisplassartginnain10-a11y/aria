import logging
import time
from urllib.parse import quote

import requests
import yaml
import app_paths

logger = logging.getLogger(__name__)

_CONFIG_PATH = app_paths.config_path()
with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

DEFAULT_CITY = _config.get("city", "Couëron")
CACHE: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 1800


def get_current_free(city: str = "Coueron") -> dict:
    try:
        resp = requests.get(f"https://wttr.in/{quote(city)}?format=j1", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        current = data["current_condition"][0]
        return {
            "temp": float(current["temp_C"]),
            "feels_like": float(current["FeelsLikeC"]),
            "description": current["weatherDesc"][0]["value"],
            "humidity": int(current["humidity"]),
            "wind": float(current["windspeedKmph"]) / 3.6,
            "city": city,
        }
    except Exception as e:
        logger.error("wttr.in error: %s", e)
        return {"error": str(e)}


def _api_key() -> str:
    import api_keys

    return api_keys.get_key("openweather")


def _get_current_owm(city: str) -> dict | None:
    api_key = _api_key()
    if not api_key:
        return None
    url = (
        f"https://api.openweathermap.org/data/2.5/weather"
        f"?q={city}&appid={api_key}&units=metric&lang=fr"
    )
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return {
            "city": data.get("name", city),
            "temp": data["main"]["temp"],
            "feels_like": data["main"]["feels_like"],
            "description": data["weather"][0]["description"],
            "humidity": data["main"]["humidity"],
            "wind": data["wind"]["speed"],
        }
    except requests.RequestException:
        logger.warning("OWM failed, fallback wttr.in", exc_info=True)
        return None


def _fetch(url: str) -> dict | None:
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        logger.exception("Weather API request failed")
        return None


def get_current(city: str | None = None) -> dict:
    city = city or DEFAULT_CITY
    cache_key = f"current:{city}"
    if cache_key in CACHE and time.time() - CACHE[cache_key][0] < CACHE_TTL:
        return CACHE[cache_key][1]

    result = None
    if _api_key():
        result = _get_current_owm(city)
    if result is None:
        result = get_current_free(city)

    if "error" not in result:
        CACHE[cache_key] = (time.time(), result)
    return result


def get_forecast(city: str | None = None, days: int = 3) -> dict:
    city = city or DEFAULT_CITY
    api_key = _api_key()
    if not api_key:
        return {"error": "Clé API OpenWeatherMap non configurée."}

    url = (
        f"https://api.openweathermap.org/data/2.5/forecast"
        f"?q={city}&appid={api_key}&units=metric&lang=fr&cnt={days * 8}"
    )
    data = _fetch(url)
    if data is None:
        return {"error": "Prévisions indisponibles."}

    forecasts = []
    for item in data.get("list", [])[: days * 8 : 8]:
        forecasts.append({
            "date": item["dt_txt"],
            "temp": item["main"]["temp"],
            "description": item["weather"][0]["description"],
        })
    return {"city": city, "forecasts": forecasts}


def get_hourly(city: str | None = None) -> dict:
    forecast = get_forecast(city, days=1)
    if "error" in forecast:
        return forecast
    return {"city": forecast["city"], "hourly": forecast.get("forecasts", [])}


def format_for_speech(data: dict) -> str:
    if "error" in data:
        return data["error"]
    return (
        f"À {data['city']}, il fait {data['temp']:.0f} degrés, "
        f"ressenti {data['feels_like']:.0f} degrés. "
        f"{data['description'].capitalize()}. "
        f"Vent {data['wind']:.0f} mètres par seconde, humidité {data['humidity']}%."
    )
