import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import tts
import app_paths

logger = logging.getLogger(__name__)

DATA_PATH = app_paths.data_dir() / "timers.json"
_timers: list[dict] = []
_lock = threading.Lock()
_loop_started = False


def _load() -> None:
    global _timers
    if DATA_PATH.exists():
        try:
            with DATA_PATH.open("r", encoding="utf-8") as f:
                _timers = json.load(f)
        except (json.JSONDecodeError, OSError):
            _timers = []


def _save() -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATA_PATH.open("w", encoding="utf-8") as f:
        json.dump(_timers, f, ensure_ascii=False, indent=2)


def _parse_duration(text: str) -> int | None:
    text = text.lower()
    total = 0
    hours = re.search(r"(\d+)\s*h", text)
    minutes = re.search(r"(\d+)\s*min", text)
    seconds = re.search(r"(\d+)\s*s", text)
    if hours:
        total += int(hours.group(1)) * 3600
    if minutes:
        total += int(minutes.group(1)) * 60
    if seconds:
        total += int(seconds.group(1))
    if total == 0:
        nums = re.findall(r"\d+", text)
        if nums:
            total = int(nums[0]) * 60
    return total if total > 0 else None


def _parse_alarm_time(time_str: str) -> datetime | None:
    match = re.search(r"(\d{1,2})[h:](\d{2})?", time_str)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    now = datetime.now()
    alarm = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if alarm <= now:
        alarm += timedelta(days=1)
    return alarm


def set_timer(duration_seconds: int, label: str = "minuteur") -> str:
    expires = datetime.now() + timedelta(seconds=duration_seconds)
    with _lock:
        _timers.append({
            "type": "timer",
            "label": label,
            "expires": expires.isoformat(),
            "triggered": False,
        })
        _save()
    _ensure_loop()
    mins = duration_seconds // 60
    return f"Minuteur {label} de {mins} minutes lancé."


def set_alarm(time_str: str, label: str = "alarme") -> str:
    alarm_time = _parse_alarm_time(time_str)
    if alarm_time is None:
        return "Heure d'alarme non reconnue."
    with _lock:
        _timers.append({
            "type": "alarm",
            "label": label,
            "expires": alarm_time.isoformat(),
            "triggered": False,
        })
        _save()
    _ensure_loop()
    return f"Alarme {label} programmée à {alarm_time.strftime('%H:%M')}."


def parse_and_set(text: str) -> str:
    if "alarme" in text.lower() or re.search(r"\d{1,2}[h:]", text):
        return set_alarm(text)
    duration = _parse_duration(text)
    if duration:
        return set_timer(duration)
    return "Durée du minuteur non reconnue."


def cancel_timer(label: str) -> str:
    with _lock:
        before = len(_timers)
        _timers[:] = [t for t in _timers if t.get("label", "").lower() != label.lower()]
        _save()
    removed = before - len(_timers)
    return f"{removed} minuteur(s) annulé(s)." if removed else "Aucun minuteur trouvé."


def list_timers() -> str:
    with _lock:
        active = [t for t in _timers if not t.get("triggered")]
    if not active:
        return "Aucun minuteur actif."
    parts = []
    for t in active:
        expires = datetime.fromisoformat(t["expires"])
        remaining = expires - datetime.now()
        mins = max(0, int(remaining.total_seconds() // 60))
        parts.append(f"{t.get('label', 'minuteur')} dans {mins} minutes")
    return ". ".join(parts) + "."


def _ensure_loop() -> None:
    global _loop_started
    if not _loop_started:
        _loop_started = True
        threading.Thread(target=_timer_loop, daemon=True).start()


def _timer_loop() -> None:
    _load()
    while True:
        now = datetime.now()
        triggered = []
        with _lock:
            for timer in _timers:
                if timer.get("triggered"):
                    continue
                try:
                    expires = datetime.fromisoformat(timer["expires"])
                except (ValueError, KeyError):
                    continue
                if expires <= now:
                    timer["triggered"] = True
                    triggered.append(timer)
            if triggered:
                _save()

        for timer in triggered:
            msg = f"Minuteur {timer.get('label', '')} terminé !"
            logger.info(msg)
            tts.speak(msg)

        time.sleep(1)


_load()
_ensure_loop()