import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
import app_paths

logger = logging.getLogger(__name__)

DATA_DIR = app_paths.data_dir()
MEMORY_PATH = DATA_DIR / "memory.json"

_lock = threading.Lock()
_data: dict[str, Any] = {}


def _default_data() -> dict[str, Any]:
    return {
        "user": {
            "name": "mathi",
            "preferences": {},
            "facts": [],
            "last_session": "",
        },
        "context": {
            "last_app_launched": "",
            "last_search": "",
            "last_icao": "LFRS",
        },
        "reminders": [],
        "custom_commands": {},
    }


def init() -> None:
    global _data
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        if MEMORY_PATH.exists():
            try:
                with MEMORY_PATH.open("r", encoding="utf-8") as f:
                    _data = json.load(f)
            except (json.JSONDecodeError, OSError):
                logger.exception("Failed to load memory, using defaults")
                _data = _default_data()
        else:
            _data = _default_data()
            save()


def save() -> None:
    with _lock:
        _data["user"]["last_session"] = datetime.now().isoformat()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with MEMORY_PATH.open("w", encoding="utf-8") as f:
            json.dump(_data, f, ensure_ascii=False, indent=2)


def remember(key: str, value: Any) -> None:
    with _lock:
        parts = key.split(".")
        target = _data
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    save()


def recall(key: str, default: Any = None) -> Any:
    with _lock:
        parts = key.split(".")
        target: Any = _data
        for part in parts:
            if not isinstance(target, dict) or part not in target:
                return default
            target = target[part]
        return target


def add_reminder(text: str, when: str) -> None:
    with _lock:
        _data["reminders"].append(
            {"text": text, "datetime": when, "triggered": False}
        )
    save()


def get_due_reminders() -> list[dict[str, Any]]:
    now = datetime.now()
    due: list[dict[str, Any]] = []
    with _lock:
        for reminder in _data["reminders"]:
            if reminder.get("triggered"):
                continue
            try:
                dt = datetime.fromisoformat(reminder["datetime"])
            except (ValueError, KeyError):
                continue
            if dt <= now:
                reminder["triggered"] = True
                due.append(reminder)
    if due:
        save()
    return due


def add_custom_command(trigger: str, action: str) -> None:
    with _lock:
        _data["custom_commands"][trigger.lower()] = action
    save()


def get_custom_commands() -> dict[str, str]:
    with _lock:
        return dict(_data["custom_commands"])


def match_custom_command(text: str) -> str | None:
    text_lower = text.lower().strip()
    commands = get_custom_commands()
    for trigger, action in commands.items():
        if trigger in text_lower:
            return action
    return None


def extract_from_conversation(text: str) -> None:
    patterns = [
        (r"je m'appelle (\w+)", "user.name"),
        (r"mon prénom est (\w+)", "user.name"),
        (r"j'aime (.+)", "user.preferences.likes"),
        (r"mon aéroport favori est (\w+)", "context.last_icao"),
        (r"apprends que (.+)", None),
    ]
    for pattern, key in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        if key:
            remember(key, match.group(1).strip())
            logger.info("Memory updated: %s = %s", key, match.group(1).strip())
        elif "apprends que quand je dis" in text.lower():
            parts = re.split(r"quand je dis|tu fais", text, flags=re.IGNORECASE)
            if len(parts) >= 3:
                trigger = parts[1].strip().strip('"').strip("'")
                action = parts[2].strip().strip('"').strip("'")
                add_custom_command(trigger, action)


def get_all() -> dict[str, Any]:
    with _lock:
        return json.loads(json.dumps(_data))