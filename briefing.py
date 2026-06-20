import logging
from datetime import datetime
from pathlib import Path

import yaml

import memory
import sounds
import tts
from actions import calendar_action, news, timer, weather
import app_paths

logger = logging.getLogger(__name__)

_CONFIG_PATH = app_paths.config_path()
with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

_briefing_done_today = False


def should_run_briefing() -> bool:
    global _briefing_done_today
    if not _config.get("morning_briefing", False):
        return False
    if _briefing_done_today:
        return False

    target = _config.get("morning_briefing_time", "08:00")
    now = datetime.now()
    try:
        hour, minute = map(int, target.split(":"))
    except ValueError:
        return False

    if now.hour == hour and now.minute == minute:
        _briefing_done_today = True
        return True
    return False


def run_morning_briefing() -> None:
    logger.info("Running morning briefing")
    sounds.play("activate")

    user_name = memory.recall("user.name", "Mathi")
    now = datetime.now()
    parts = [f"Bonjour {user_name}, voici ton briefing du {now.strftime('%A %d %B')}."]

    includes = _config.get("briefing_includes", ["weather", "news", "calendar"])

    if "weather" in includes:
        data = weather.get_current()
        parts.append(weather.format_for_speech(data))

    if "news" in includes:
        articles = news.get_top_headlines(n=3)
        parts.append(news.format_briefing(articles))

    if "calendar" in includes:
        events = calendar_action.get_today_events()
        if events:
            parts.append(events)

    timers_info = timer.list_timers()
    if "Aucun" not in timers_info:
        parts.append(timers_info)

    parts.append("Bonne journée !")
    full_text = " ".join(parts)

    import ui_bridge as ui
    ui.set_status("speaking")
    tts.speak(full_text)
    ui.set_status("listening")