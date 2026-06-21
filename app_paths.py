"""Chemins applicatifs compatibles PyInstaller (source + exe gelé)."""

import shutil
import sys
from pathlib import Path

# Toujours ancré sur l'emplacement de ce fichier — jamais os.getcwd()
_PROJECT_ROOT = Path(__file__).resolve().parent


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """Répertoire de l'application (writable) — dossier de l'exe ou du projet."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _PROJECT_ROOT


def bundle_dir() -> Path:
    """Ressources embarquées (_internal / _MEIPASS)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", str(app_dir()))).resolve()
    return _PROJECT_ROOT


def resource_path(*parts: str) -> Path:
    """Cherche une ressource à côté de l'exe, sinon dans le bundle."""
    local = app_dir().joinpath(*parts)
    if local.exists():
        return local.resolve()
    return bundle_dir().joinpath(*parts).resolve()


def config_path() -> Path:
    return resource_path("config.yaml")


def sounds_dir() -> Path:
    local = app_dir() / "sounds"
    if local.exists():
        return local.resolve()
    return resource_path("sounds")


def prompts_dir() -> Path:
    return resource_path("prompts")


def data_dir() -> Path:
    path = (app_dir() / "data").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def voix_ia_whisper_dir() -> Path | None:
    """Chemin vers la copie locale openai/whisper (dossier voix ia/whisper-main)."""
    candidates = (
        app_dir() / "voix ia" / "whisper-main",
        app_dir() / "voix-ia" / "whisper-main",
        _PROJECT_ROOT / "voix ia" / "whisper-main",
        _PROJECT_ROOT / "voix-ia" / "whisper-main",
    )
    for root in candidates:
        if (root / "whisper" / "__init__.py").is_file():
            return root.resolve()
    return None


def whisper_models_dir() -> Path:
    """Cache des poids Whisper (.pt) — hors git."""
    path = (data_dir() / "whisper_models").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_runtime_layout() -> None:
    """Copie config/data/prompts/sounds à côté de l'exe au premier lancement."""
    if not is_frozen():
        return

    root = app_dir()
    bundle = bundle_dir()

    for filename in ("config.yaml",):
        dest = root / filename
        src = bundle / filename
        if not dest.exists() and src.exists():
            shutil.copy2(src, dest)

    for folder in ("data", "prompts", "sounds", "assets"):
        src_dir = bundle / folder
        if not src_dir.exists():
            continue
        dest_dir = root / folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        for src_file in src_dir.rglob("*"):
            if src_file.is_file():
                rel = src_file.relative_to(src_dir)
                dest_file = dest_dir / rel
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                if not dest_file.exists():
                    shutil.copy2(src_file, dest_file)
