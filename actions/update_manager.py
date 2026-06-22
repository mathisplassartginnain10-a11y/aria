"""Vérification et application des mises à jour Git (Sprint H)."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from pathlib import Path

import app_paths

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
ROOT = app_paths.app_dir()


def _git(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )


def get_app_version() -> str:
    try:
        out = _git("describe", "--tags", "--always", timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    pkg = ROOT / "electron" / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            return str(data.get("version", "dev"))
        except Exception:
            pass
    return "dev"


def check_for_updates() -> dict:
    try:
        fetch = _git("fetch", "origin", "main", timeout=120)
        if fetch.returncode != 0:
            return {
                "available": False,
                "commits_behind": 0,
                "latest_message": "",
                "error": (fetch.stderr or fetch.stdout or "git fetch failed").strip(),
                "version": get_app_version(),
            }
        count_out = _git("rev-list", "HEAD..origin/main", "--count")
        msg_out = _git("log", "origin/main", "-1", "--pretty=format:%s")
        behind = int((count_out.stdout or "0").strip() or "0")
        latest = (msg_out.stdout or "").strip()
        return {
            "available": behind > 0,
            "commits_behind": behind,
            "latest_message": latest,
            "version": get_app_version(),
        }
    except Exception as exc:
        logger.exception("check_for_updates")
        return {
            "available": False,
            "commits_behind": 0,
            "latest_message": "",
            "error": str(exc),
            "version": get_app_version(),
        }


def apply_update() -> dict:
    bat = ROOT / "scripts" / "update_aria.bat"
    if not bat.is_file():
        return {"success": False, "error": "scripts/update_aria.bat introuvable"}
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "cmd", "/k", str(bat)],
            cwd=ROOT,
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
        )

        def _quit_later() -> None:
            import time
            time.sleep(3)
            try:
                import ui_bridge as ui
                ui.emit("request_app_quit", {})
            except Exception:
                pass

        threading.Thread(target=_quit_later, daemon=True, name="ARIA-UpdateQuit").start()
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
