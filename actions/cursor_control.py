import json
import logging
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pyautogui
import pygetwindow as gw
import pyperclip
import requests
import yaml
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
import app_paths

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_CONFIG_PATH = app_paths.config_path()

with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

CURSOR_EXE = Path(_config.get(
    "cursor_exe_path",
    "C:/Users/mathi/AppData/Local/Programs/cursor/Cursor.exe",
))
CURSOR_PROJECTS_DIR = Path(_config.get(
    "cursor_projects_dir",
    "C:/Users/mathi/OneDrive/Documents",
))
MODEL = _config.get("model", "qwen3:14b")
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

_observer: Observer | None = None
_watch_thread_started = False

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


def _ollama_chat(user_message: str) -> str:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": user_message}],
        "stream": False,
    }
    try:
        response = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()["message"]["content"].strip()
    except (requests.RequestException, KeyError, json.JSONDecodeError):
        logger.exception("Ollama cursor prompt build failed")
        return user_message


def open_cursor(file_path: str | None = None) -> str:
    if not CURSOR_EXE.exists():
        return f"Cursor introuvable à {CURSOR_EXE}."
    args = [str(CURSOR_EXE)]
    if file_path:
        args.append(str(Path(file_path).expanduser()))
    subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=CREATE_NO_WINDOW,
    )
    for _ in range(20):
        time.sleep(0.5)
        if _find_cursor_window():
            return "Cursor ouvert."
    return "Cursor lancé, fenêtre non confirmée."


def _find_cursor_window():
    windows = gw.getWindowsWithTitle("Cursor")
    return windows[0] if windows else None


def focus_cursor() -> str:
    window = _find_cursor_window()
    if not window:
        return open_cursor()
    try:
        if window.isMinimized:
            window.restore()
        window.activate()
        time.sleep(0.3)
        return "Cursor au premier plan."
    except Exception:
        logger.exception("focus_cursor failed")
        return "Impossible de mettre Cursor au premier plan."


def open_composer() -> None:
    focus_cursor()
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "i")
    time.sleep(0.5)


def type_prompt(prompt_text: str) -> None:
    open_composer()
    if prompt_text.isascii():
        pyautogui.typewrite(prompt_text, interval=0.02)
    else:
        pyperclip.copy(prompt_text)
        pyautogui.hotkey("ctrl", "v")
    time.sleep(0.2)


def send_prompt(prompt_text: str) -> str:
    type_prompt(prompt_text)
    pyautogui.press("enter")
    logger.info("Prompt sent to Cursor: %s", prompt_text[:200])
    return "Prompt envoyé à Cursor."


def open_file_in_cursor(file_path: str) -> str:
    path = Path(file_path).expanduser()
    if not path.exists():
        project_root = app_paths.app_dir()
        candidate = project_root / file_path
        if candidate.exists():
            path = candidate
        else:
            return f"Fichier introuvable : {file_path}."
    return open_cursor(str(path))


def open_project(project_name: str) -> str:
    name_lower = project_name.lower().strip()
    for path in CURSOR_PROJECTS_DIR.rglob("*"):
        if path.is_dir() and name_lower in path.name.lower():
            return open_cursor(str(path))
    return f"Projet {project_name} introuvable dans {CURSOR_PROJECTS_DIR}."


def build_coding_prompt(user_request: str) -> str:
    instruction = (
        "Transforme cette demande vocale en prompt précis et complet pour Cursor Composer. "
        "Inclus le langage, le framework si détecté, les bonnes pratiques et les cas limites. "
        "Réponds uniquement avec le prompt final en anglais, sans explication :\n\n"
        f"{user_request}"
    )
    enriched = _ollama_chat(instruction)
    return enriched if enriched else user_request


def voice_to_cursor(raw_voice_text: str) -> str:
    prompt = build_coding_prompt(raw_voice_text)
    window = _find_cursor_window()
    if not window:
        open_cursor()
        time.sleep(2)
    send_prompt(prompt)
    return "Prompt envoyé à Cursor."


class _CursorFileHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".md"}:
            logger.info("Cursor modified file: %s", path.name)
            try:
                import tts
                tts.speak(f"Cursor a modifié {path.name}")
            except Exception:
                pass


def watch_cursor_output(timeout: int = 60, watch_dir: str | None = None) -> str:
    global _observer, _watch_thread_started
    watch_path = Path(watch_dir) if watch_dir else app_paths.app_dir()

    if _observer and _observer.is_alive():
        return f"Surveillance déjà active sur {watch_path}."

    handler = _CursorFileHandler()
    _observer = Observer()
    _observer.schedule(handler, str(watch_path), recursive=True)
    _observer.start()
    _watch_thread_started = True

    def _stop_later():
        time.sleep(timeout)
        if _observer and _observer.is_alive():
            _observer.stop()
            _observer.join(timeout=5)

    threading.Thread(target=_stop_later, daemon=True).start()
    return f"Surveillance Cursor active pendant {timeout} secondes sur {watch_path.name}."


def handle(text: str) -> str:
    t = text.lower()
    if "ouvre cursor" in t and "projet" not in t and ".py" not in t and ".ts" not in t:
        return open_cursor()
    if "projet" in t and "cursor" in t:
        name = text
        for kw in ("ouvre le projet", "ouvre", "projet", "dans cursor", "cursor"):
            name = re.sub(rf"\b{re.escape(kw)}\b", "", name, flags=re.I).strip()
        return open_project(name)
    if "ouvre" in t and ("fichier" in t or ".py" in t or ".ts" in t or ".js" in t):
        file_match = re.search(r"([\w./\\-]+\.(py|ts|tsx|js|jsx|json|yaml|md))", text, re.I)
        if file_match:
            return open_file_in_cursor(file_match.group(1))
    if any(kw in t for kw in ("génère", "genere", "crée", "cree", "demande à cursor", "dans cursor", "corrige")):
        request = text
        for prefix in ("génère", "genere", "crée", "cree", "demande à cursor de", "dans cursor,"):
            if t.startswith(prefix):
                request = text[len(prefix):].strip()
                break
        return voice_to_cursor(request)
    return voice_to_cursor(text)