import json
import logging
import math
import re
from pathlib import Path

import numpy as np
import requests
import yaml

from actions import aviation
import app_paths

logger = logging.getLogger(__name__)

_CONFIG_PATH = app_paths.config_path()
_PROMPTS_DIR = app_paths.prompts_dir()

with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

MODEL = _config.get("model", "qwen3:14b")
AIRCRAFT = _config.get("aircraft", "Robin DR400")
HOME_BASE = _config.get("home_base", "LFRS")
HOME_ICAO = _config.get("home_icao", HOME_BASE)
AVIATION_MODE_ENABLED = _config.get("aviation_mode_enabled", True)
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

AVIATION_SYSTEM_PROMPT = (_PROMPTS_DIR / "aviation_system.txt").read_text(encoding="utf-8")

DR400_SPEEDS = {"Vs": 58, "Vx": 73, "Vy": 79, "Va": 111, "Vno": 130, "Vne": 169, "Vfe": 99}
DR400_FUEL_LPH = 30
DR400_MAX_XWIND = 15

CHECKLISTS = {
    "avant démarrage": [
        "Feux : position, strobe, landing selon besoin",
        "Mixture : riche",
        "Carburant : quantité et sélecteur vérifiés",
        "Freins : testés",
        "Instruments : contrôlés",
        "Ceintures : attachées",
    ],
    "après démarrage": [
        "Pression huile : dans le vert",
        "Alternateur : ON, charge OK",
        "Mixture : ajuster au roulage",
        "Radios : ATIS et fréquences",
        "Transpondeur : ALT",
    ],
    "avant décollage": [
        "CIABB : Carburant, Instruments, Air, Briefing, Balises",
        "Portes et fenêtres : fermées",
        "Trim : takeoff",
        "Flaps : position décollage",
        "Mixture : pleine richesse",
        "Lumières : landing ON",
        "Magnetos : check",
    ],
    "croisière": [
        "Mixture : lean selon altitude",
        "Cap et altitude : stabilisés",
        "Carburant : balancement",
        "Météo : surveillance continue",
    ],
    "avant atterrissage": [
        "ATIS : dernière info",
        "Briefing : piste, vent, circuit",
        "Mixture : riche",
        "Carburant : sélecteur approprié",
        "Ceintures : ON",
    ],
    "après atterrissage": [
        "Flaps : UP",
        "Transpondeur : STBY",
        "Strobe : OFF si jour",
        "Mixture : riche au roulage",
    ],
    "hasell": [
        "Hauteur : suffisante (minimum 500 ft)",
        "Airspace : libre de trafic",
        "Sécurité : zone dégagée",
        "Engine : puissance et instruments OK",
        "Lookout : 360 degrés",
        "Location : repères choisis",
    ],
}

PHONETIC = {
    "A": "Alpha", "B": "Bravo", "C": "Charlie", "D": "Delta", "E": "Echo",
    "F": "Foxtrot", "G": "Golf", "H": "Hotel", "I": "India", "J": "Juliet",
    "K": "Kilo", "L": "Lima", "M": "Mike", "N": "November", "O": "Oscar",
    "P": "Papa", "Q": "Quebec", "R": "Romeo", "S": "Sierra", "T": "Tango",
    "U": "Uniform", "V": "Victor", "W": "Whiskey", "X": "X-ray", "Y": "Yankee",
    "Z": "Zulu",
    "0": "Zero", "1": "Un", "2": "Deux", "3": "Trois", "4": "Quatre",
    "5": "Cinq", "6": "Six", "7": "Sept", "8": "Huit", "9": "Neuf",
}

LFRS_AIRSPACES = [
    {"name": "CTR LFRS", "type": "CTR", "floor_ft": 0, "ceiling_ft": 2500, "lat": 47.153, "lon": -1.611, "radius_nm": 5},
    {"name": "TMA Nantes", "type": "TMA", "floor_ft": 2500, "ceiling_ft": 6500, "lat": 47.153, "lon": -1.611, "radius_nm": 15},
]


def _ollama_chat(system_prompt: str, user_message: str) -> str:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
    }
    try:
        response = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=120)
        response.raise_for_status()
        return response.json()["message"]["content"].strip()
    except (requests.RequestException, KeyError, json.JSONDecodeError):
        logger.exception("Ollama aviation request failed")
        return "Impossible de contacter Ollama pour cette question aviation."


def answer_theory(question: str) -> str:
    if not AVIATION_MODE_ENABLED:
        return "Le mode aviation expert est désactivé."
    return _ollama_chat(AVIATION_SYSTEM_PROMPT, question)


def decode_metar_expert(raw_metar: str) -> str:
    raw = raw_metar.strip().upper()
    if not raw.startswith("METAR"):
        match = re.search(r"METAR\s+[A-Z]{4}.*", raw)
        raw = match.group(0) if match else raw

    wind_match = re.search(r"(\d{3})(\d{2,3})(G(\d{2,3}))?KT", raw)
    vis_match = re.search(r"(\d{4})|CAVOK", raw)
    cloud_matches = re.findall(r"(SKC|CLR|FEW|SCT|BKN|OVC)(\d{3})", raw)
    temp_match = re.search(r"\s(M?\d{2})/(M?\d{2})\s", raw)
    qnh_match = re.search(r"Q(\d{4})", raw)

    parts = []
    if wind_match:
        direction = int(wind_match.group(1))
        speed = int(wind_match.group(2))
        gust = wind_match.group(4)
        wind_text = f"Vent du {direction} à {speed} nœuds"
        if gust:
            wind_text += f", rafales {gust}"
        parts.append(wind_text + ".")

    if "CAVOK" in raw:
        parts.append("Visibilité supérieure à 10 kilomètres, pas de nuage significatif.")
        vmc = True
        ceiling = 99999
    else:
        if vis_match and vis_match.group(1):
            vis_m = int(vis_match.group(1))
            vis_km = vis_m / 1000 if vis_m >= 1000 else vis_m
            parts.append(f"Visibilité {vis_km} kilomètres.")
        else:
            vis_km = 10
        cloud_texts = []
        ceiling = 99999
        for cover, alt in cloud_matches:
            alt_ft = int(alt) * 100
            ceiling = min(ceiling, alt_ft)
            labels = {"FEW": "Quelques", "SCT": "Épars", "BKN": "Nuageux", "OVC": "Couvert"}
            cloud_texts.append(f"{labels.get(cover, cover)} à {alt_ft} pieds")
        if cloud_texts:
            parts.append(", ".join(cloud_texts) + ".")
        vmc = vis_km >= 5 and ceiling >= 3000

    if temp_match:
        temp = temp_match.group(1).replace("M", "-")
        dew = temp_match.group(2).replace("M", "-")
        parts.append(f"Température {temp}, point de rosée {dew}.")

    if qnh_match:
        parts.append(f"QNH {qnh_match.group(1)} hectopascals.")

    vmc_text = "Conditions VMC, vol VFR possible." if vmc else "Attention, conditions IMC ou VFR limite."
    parts.append(vmc_text)
    return " ".join(parts)


def wind_component(wind_dir: float, wind_speed: float, runway_hdg: float) -> str:
    angle_diff = math.radians((wind_dir - runway_hdg + 360) % 360)
    if angle_diff > math.pi:
        angle_diff = 2 * math.pi - angle_diff
    headwind = wind_speed * math.cos(angle_diff)
    crosswind = abs(wind_speed * math.sin(angle_diff))
    head_label = "face" if headwind >= 0 else "arrière"
    verdict = "Dans les limites." if crosswind <= DR400_MAX_XWIND else f"Dépasse la limite DR400 de {DR400_MAX_XWIND} nœuds de travers."
    return (
        f"Composante de {head_label} {abs(headwind):.0f} nœuds, "
        f"composante de travers {crosswind:.0f} nœuds. {verdict}"
    )


def density_altitude(qnh: float, temp_c: float, elevation_ft: float = 0) -> str:
    pressure_alt = (1013.25 - qnh) * 30.0 + elevation_ft
    isa_temp = 15 - 0.00198 * pressure_alt
    da = pressure_alt + 120 * (temp_c - isa_temp)
    impact = "Performances réduites, distance de décollage augmentée." if da > elevation_ft + 1000 else "Impact modéré sur les performances."
    return f"Altitude densité estimée : {da:.0f} pieds. {impact}"


def fuel_planning(distance_nm: float, wind_component: float, reserve_min: int = 45) -> str:
    tas = 110
    gs = max(40, tas - wind_component)
    time_h = distance_nm / gs
    fuel_l = time_h * DR400_FUEL_LPH
    reserve_l = (reserve_min / 60) * DR400_FUEL_LPH
    total = fuel_l + reserve_l
    return (
        f"Distance {distance_nm} nm, vent de face {wind_component} kt. "
        f"Temps estimé {time_h * 60:.0f} minutes. "
        f"Carburant {fuel_l:.0f} litres plus réserve {reserve_min} min ({reserve_l:.0f} L), total {total:.0f} litres."
    )


def nav_triangle(tas: float, wind_dir: float, wind_speed: float, track: float) -> str:
    wind_angle = math.radians(wind_dir - track)
    wind_x = wind_speed * math.sin(wind_angle)
    wind_y = wind_speed * math.cos(wind_angle)
    gs = math.sqrt(max(1, tas**2 + wind_speed**2 - 2 * tas * wind_speed * math.cos(wind_angle)))
    drift = math.degrees(math.asin(max(-1, min(1, wind_x / tas))))
    heading = (track - drift + 360) % 360
    return (
        f"Triangle des vitesses : route {track:.0f}, TAS {tas:.0f} kt, vent {wind_dir:.0f}/{wind_speed:.0f}. "
        f"Cap à tenir {heading:.0f}, vitesse sol {gs:.0f} kt, dérive {drift:.1f} degrés."
    )


def time_distance_speed(given_values: dict) -> str:
    d = given_values.get("distance_nm")
    v = given_values.get("speed_kt")
    t = given_values.get("time_min")
    if d is not None and v is not None:
        time_min = (d / v) * 60
        return f"Temps = {time_min:.1f} minutes pour {d} nm à {v} kt."
    if d is not None and t is not None:
        speed = d / (t / 60)
        return f"Vitesse = {speed:.1f} kt pour {d} nm en {t} minutes."
    if v is not None and t is not None:
        distance = v * (t / 60)
        return f"Distance = {distance:.1f} nm à {v} kt en {t} minutes."
    return "Fournis deux parmi distance, vitesse et temps."


def airspace_check(lat: float, lon: float, altitude_ft: float) -> str:
    active = []
    for space in LFRS_AIRSPACES:
        dlat = (lat - space["lat"]) * 60
        dlon = (lon - space["lon"]) * 60 * math.cos(math.radians(lat))
        dist_nm = math.sqrt(dlat**2 + dlon**2)
        if dist_nm <= space["radius_nm"] and space["floor_ft"] <= altitude_ft <= space["ceiling_ft"]:
            active.append(f"{space['name']} ({space['type']}) actif entre {space['floor_ft']} et {space['ceiling_ft']} ft")
    if not active:
        return f"Aucun espace restreint majeur autour de LFRS à {altitude_ft:.0f} ft."
    return "Espaces actifs : " + ". ".join(active) + "."


def checklist(phase: str) -> str:
    phase_lower = phase.lower().strip()
    for key, items in CHECKLISTS.items():
        if key in phase_lower or phase_lower in key:
            return f"Checklist {key} {AIRCRAFT} : " + " — ".join(items) + "."
    return f"Phases disponibles : {', '.join(CHECKLISTS.keys())}."


def go_nogo_analysis(metar: str, taf: str = "", pilot_experience: str = "eleve") -> str:
    decoded = decode_metar_expert(metar)
    factors = [decoded]
    if "IMC" in decoded or "limite" in decoded.lower():
        factors.append("Météo limite pour VFR.")
    if pilot_experience.lower() in ("debutant", "faible", "low"):
        factors.append("Expérience pilote limitée, prudence accrue.")
    if taf and ("BKN" in taf.upper() or "OVC" in taf.upper() or "TS" in taf.upper()):
        factors.append("TAF défavorable prévu.")
    verdict = "NO-GO recommandé." if any("NO" in f or "IMC" in f or "limite" in f.lower() for f in factors[1:]) else "GO possible avec vigilance."
    return f"Analyse GO/NO-GO : {' '.join(factors)} Verdict : {verdict}"


def phonetic_alphabet(word_or_letter: str) -> str:
    chars = re.sub(r"[^A-Z0-9-]", "", word_or_letter.upper())
    return ", ".join(PHONETIC.get(c, c) for c in chars)


def radiotelephony_example(situation: str) -> str:
    examples = {
        "décollage": "Nantes Tour, F-GXXX, Robin DR400, prêt pour le départ piste 03, VFR vers Angers, première rotation.",
        "atterrissage": "Nantes Tour, F-GXXX, Robin DR400, en finale piste 03.",
        "taxi": "Nantes Sol, F-GXXX, au parking Alpha, demande taxi départ piste 03 avec ATIS Charlie.",
    }
    for key, phrase in examples.items():
        if key in situation.lower():
            return phrase
    return _ollama_chat(
        AVIATION_SYSTEM_PROMPT,
        f"Donne un exemple de phraséologie radio OACI en français pour : {situation}",
    )


def handle(text: str) -> str:
    t = text.lower()
    metar_match = re.search(r"METAR\s+[A-Z]{4}\s+.*", text.upper())
    if metar_match or "décode" in t and "metar" in t:
        raw = metar_match.group(0) if metar_match else text
        if not metar_match:
            icao = re.search(r"\b([A-Z]{4})\b", text.upper())
            if icao:
                data = aviation.get_metar(icao.group(1))
                raw = data.get("raw", "")
        return decode_metar_expert(raw)

    if "checklist" in t:
        phase = re.sub(r".*checklist\s*", "", text, flags=re.I)
        return checklist(phase or "avant décollage")

    if "phonétique" in t or "phonetique" in t:
        callsign = re.sub(r".*phon[ée]tique\s*", "", text, flags=re.I).strip()
        return phonetic_alphabet(callsign or "N123AZ")

    if "go no go" in t or "go/no-go" in t or "gonogo" in t:
        metar = metar_match.group(0) if metar_match else ""
        if not metar:
            data = aviation.get_metar(HOME_ICAO)
            metar = data.get("raw", "")
        return go_nogo_analysis(metar)

    wind_match = re.search(r"vent du (\d{3}).*?(\d{2,3}).*piste (\d{2})", t)
    if wind_match or ("vent de travers" in t and "piste" in t):
        if wind_match:
            return wind_component(float(wind_match.group(1)), float(wind_match.group(2)), float(wind_match.group(3)) * 10)
        nums = re.findall(r"\d+", text)
        if len(nums) >= 3:
            return wind_component(float(nums[0]), float(nums[1]), float(nums[2]) * 10 if len(nums[2]) == 2 else float(nums[2]))

    if "planifie" in t and ("vol" in t or "mile" in t or "nautique" in t):
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]
        if nums:
            wind = nums[1] if len(nums) > 1 else 0
            return fuel_planning(nums[0], wind)

    if "triangle" in t:
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]
        if len(nums) >= 4:
            return nav_triangle(nums[3], nums[1], nums[2], nums[0])

    if re.search(r"\bv[xysane]\b", t) or "vitesse" in t and "dr400" in t:
        speed_key = re.search(r"v([xysane]+|no|ne|fe)", t)
        if speed_key:
            key = "V" + speed_key.group(1).capitalize()
            if key == "VNo":
                key = "Vno"
            val = DR400_SPEEDS.get(key.replace("V", "V") if key.startswith("V") else key)
            for k, v in DR400_SPEEDS.items():
                if k.lower() in t:
                    return f"La {k} du DR400 est {v} nœuds."
        return f"Vitesses DR400 : Vs {DR400_SPEEDS['Vs']}, Vx {DR400_SPEEDS['Vx']}, Vy {DR400_SPEEDS['Vy']}, Va {DR400_SPEEDS['Va']} nœuds."

    if "densité altitude" in t or "density altitude" in t:
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]
        if len(nums) >= 2:
            return density_altitude(nums[0], nums[1], nums[2] if len(nums) > 2 else 0)

    if "espace aérien" in t or "airspace" in t:
        return airspace_check(_config.get("lat", 47.2167), _config.get("lon", -1.7333), 2500)

    if "radio" in t or "phraséologie" in t:
        return radiotelephony_example(text)

    return answer_theory(text)