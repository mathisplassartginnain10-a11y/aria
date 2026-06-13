import logging
import math
import re
from datetime import datetime
from pathlib import Path

import ephem
import requests
import yaml
import app_paths

logger = logging.getLogger(__name__)

_CONFIG_PATH = app_paths.config_path()
with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

AVWX_KEY = _config.get("avwx_api_key", "")
DEFAULT_ICAO = _config.get("default_icao", "LFRS")
LAT = _config.get("lat", 47.2167)
LON = _config.get("lon", -1.7333)


def decode_cloud_cover(code: str) -> str:
    mapping = {
        "SKC": "ciel dégagé",
        "CLR": "ciel clair",
        "FEW": "peu nuageux",
        "SCT": "partiellement nuageux",
        "BKN": "nuageux",
        "OVC": "couvert",
    }
    return mapping.get(code.upper(), code)


def decode_wind(wind_string: str) -> str:
    match = re.search(r"(\d{3})(\d{2,3})(G(\d{2,3}))?", wind_string)
    if not match:
        return wind_string
    direction = int(match.group(1))
    speed = int(match.group(2))
    gust = match.group(4)
    text = f"vent du {direction} à {speed} nœuds"
    if gust:
        text += f", rafales {gust} nœuds"
    return text


def get_metar(icao: str | None = None) -> dict:
    icao = (icao or DEFAULT_ICAO).upper()
    if AVWX_KEY:
        try:
            url = f"https://avwx.rest/api/metar/{icao}?token={AVWX_KEY}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            return {
                "icao": icao,
                "raw": data.get("raw", ""),
                "sanitized": data.get("sanitized", ""),
                "data": data.get("data", {}),
            }
        except requests.RequestException:
            logger.exception("AVWX METAR failed, trying fallback")

    try:
        url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        items = response.json()
        if items:
            raw = items[0].get("rawOb", "")
            return {"icao": icao, "raw": raw, "data": items[0]}
    except requests.RequestException:
        logger.exception("METAR fallback failed")

    return {"icao": icao, "error": f"METAR {icao} indisponible."}


def decode_metar_to_speech(raw: str) -> str:
    if not raw:
        return "METAR non disponible."
    wind_match = re.search(r"(\d{3}\d{2,3}G?\d{0,3}KT)", raw)
    temp_match = re.search(r"(\d{2})/(\d{2})", raw)
    qnh_match = re.search(r"Q(\d{4})", raw)

    parts = [f"METAR {raw[:4] if len(raw) >= 4 else ''}."]
    if wind_match:
        parts.append(decode_wind(wind_match.group(1)))
    if temp_match:
        parts.append(f"température {temp_match.group(1)} degrés, point de rosée {temp_match.group(2)}.")
    if qnh_match:
        parts.append(f"QNH {qnh_match.group(1)} hectopascals.")
    return " ".join(parts)


def get_taf(icao: str | None = None) -> dict:
    icao = (icao or DEFAULT_ICAO).upper()
    if AVWX_KEY:
        try:
            url = f"https://avwx.rest/api/taf/{icao}?token={AVWX_KEY}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            return {"icao": icao, "raw": data.get("raw", ""), "data": data.get("data", {})}
        except requests.RequestException:
            logger.exception("TAF request failed")

    try:
        url = f"https://aviationweather.gov/api/data/taf?ids={icao}&format=json"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        items = response.json()
        if items:
            return {"icao": icao, "raw": items[0].get("rawTAF", ""), "data": items[0]}
    except requests.RequestException:
        logger.exception("TAF fallback failed")

    return {"icao": icao, "error": f"TAF {icao} indisponible."}


def get_notams(icao: str | None = None) -> list[str]:
    icao = (icao or DEFAULT_ICAO).upper()
    try:
        url = f"https://aviationweather.gov/api/data/notam?ids={icao}&format=json"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        items = response.json()
        return [item.get("notamText", str(item)) for item in items[:5]]
    except requests.RequestException:
        logger.exception("NOTAM request failed")
        return [f"NOTAMs {icao} indisponibles."]


def get_atis(icao: str | None = None) -> str:
    return f"ATIS {icao or DEFAULT_ICAO} non disponible via cette source."


def get_sunrise_sunset(lat: float | None = None, lon: float | None = None) -> str:
    lat = lat or LAT
    lon = lon or LON
    obs = ephem.Observer()
    obs.lat = str(lat)
    obs.lon = str(lon)
    obs.date = datetime.now()
    sun = ephem.Sun()
    sunrise = obs.next_rising(sun).datetime().strftime("%H:%M")
    sunset = obs.next_setting(sun).datetime().strftime("%H:%M")
    return f"Lever du soleil à {sunrise}, coucher à {sunset}."


def compute_density_altitude(pressure: float, temp: float, elevation: float = 0) -> str:
    pressure_alt = (1013.25 - pressure) * 30.0 + elevation
    isa_temp = 15 - 0.00198 * pressure_alt
    da = pressure_alt + 120 * (temp - isa_temp)
    return f"Altitude densité estimée : {da:.0f} pieds."


def format_taf_speech(data: dict) -> str:
    if "error" in data:
        return data["error"]
    raw = data.get("raw", "")
    return f"TAF {data.get('icao', '')}. {raw}" if raw else "TAF non disponible."