import logging
import subprocess
import sys
from pathlib import Path
import app_paths

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def open_path(path_str: str) -> str:
    path = Path(path_str).expanduser()
    if not path.exists():
        return f"Fichier ou dossier introuvable : {path_str}."
    try:
        if sys.platform == "win32":
            os_startfile = getattr(__import__("os"), "startfile")
            os_startfile(str(path))
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return f"Ouverture de {path.name}."
    except Exception:
        logger.exception("Failed to open %s", path)
        return f"Impossible d'ouvrir {path_str}."


def open_folder(path_str: str) -> str:
    path = Path(path_str).expanduser()
    if path.is_file():
        path = path.parent
    if not path.exists():
        return f"Dossier introuvable : {path_str}."
    try:
        subprocess.Popen(
            ["explorer", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
        )
        return f"Dossier ouvert : {path}."
    except Exception:
        logger.exception("Failed to open folder %s", path)
        return f"Impossible d'ouvrir le dossier {path_str}."