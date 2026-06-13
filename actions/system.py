import ctypes
import logging
import os
import subprocess
import sys
from pathlib import Path

import psutil
import app_paths

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _get_volume_interface():
    try:
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return interface.QueryInterface(IAudioEndpointVolume)
    except Exception:
        logger.exception("Volume interface unavailable")
        return None


def set_volume(level) -> str:
    vol = _get_volume_interface()
    if vol is None:
        return "Contrôle du volume indisponible."

    if isinstance(level, str):
        current = int(get_volume())
        level_lower = level.lower()
        if level_lower in ("monte", "augmente"):
            level = min(100, current + 10)
        elif level_lower in ("baisse", "diminue"):
            level = max(0, current - 10)
        elif level_lower in ("coupe", "muet"):
            vol.SetMute(1, None)
            return "Son coupé."
        elif level_lower in ("rétablis", "retabli", "unmute"):
            vol.SetMute(0, None)
            return "Son rétabli."
        else:
            try:
                level = int("".join(c for c in level if c.isdigit()))
            except ValueError:
                return "Niveau de volume non reconnu."

    level = max(0, min(100, int(level)))
    vol.SetMasterVolumeLevelScalar(level / 100.0, None)
    return f"Volume réglé à {level}%."


def get_volume() -> int:
    vol = _get_volume_interface()
    if vol is None:
        return 0
    return int(vol.GetMasterVolumeLevelScalar() * 100)


def set_brightness(level) -> str:
    try:
        import screen_brightness_control as sbc

        if isinstance(level, str):
            current = get_brightness()
            if "monte" in level.lower() or "augmente" in level.lower():
                level = min(100, current + 10)
            elif "baisse" in level.lower() or "diminue" in level.lower():
                level = max(0, current - 10)
            else:
                level = int("".join(c for c in level if c.isdigit()))

        level = max(0, min(100, int(level)))
        sbc.set_brightness(level)
        return f"Luminosité réglée à {level}%."
    except Exception:
        logger.exception("Brightness control failed")
        return "Contrôle de la luminosité indisponible."


def get_brightness() -> int:
    try:
        import screen_brightness_control as sbc

        return int(sbc.get_brightness()[0])
    except Exception:
        return 50


def sleep() -> str:
    os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
    return "Mise en veille."


def shutdown(delay: int = 0) -> str:
    os.system(f"shutdown /s /t {delay}")
    if delay:
        return f"Extinction dans {delay} secondes."
    return "Extinction en cours."


def reboot(delay: int = 0) -> str:
    os.system(f"shutdown /r /t {delay}")
    if delay:
        return f"Redémarrage dans {delay} secondes."
    return "Redémarrage en cours."


def cancel_shutdown() -> str:
    os.system("shutdown /a")
    return "Extinction annulée."


def lock() -> str:
    ctypes.windll.user32.LockWorkStation()
    return "Session verrouillée."


def empty_trash() -> str:
    try:
        import winshell

        winshell.recycle_bin().empty(confirm=False, show_progress=False, sound=False)
        return "Corbeille vidée."
    except Exception:
        logger.exception("Empty trash failed")
        return "Impossible de vider la corbeille."


def get_battery() -> str:
    battery = psutil.sensors_battery()
    if battery is None:
        return "Pas de batterie détectée."
    status = "en charge" if battery.power_plugged else "sur batterie"
    return f"Batterie à {battery.percent:.0f}%, {status}."


def get_cpu_temp() -> str:
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for name, entries in temps.items():
                if entries:
                    return f"Température CPU : {entries[0].current:.0f}°C."
    except Exception:
        pass
    return "Température CPU indisponible."


def get_ram_usage() -> str:
    mem = psutil.virtual_memory()
    return f"RAM utilisée : {mem.percent:.0f}% ({mem.used // (1024**3)} Go sur {mem.total // (1024**3)} Go)."


def get_disk_usage(path: str = "C:\\") -> str:
    usage = psutil.disk_usage(path)
    return f"Disque {path} : {usage.percent:.0f}% utilisé."


def screenshot(save_path: str | None = None) -> str:
    try:
        from PIL import ImageGrab

        img = ImageGrab.grab()
        if save_path is None:
            save_path = str(Path.home() / "Desktop" / "screenshot.png")
        img.save(save_path)
        return f"Capture d'écran sauvegardée : {save_path}."
    except Exception:
        logger.exception("Screenshot failed")
        return "Capture d'écran impossible."