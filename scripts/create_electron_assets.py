"""
Génère tous les fichiers d'icônes Electron depuis electron/assets/icon.png
Ne modifie PAS icon.png (source du nouveau logo).

Lance : .venv\\Scripts\\python.exe scripts\\create_electron_assets.py
"""

from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image
except ImportError:
    raise SystemExit("Pillow requis: pip install Pillow")

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "electron" / "assets"
SRC = ASSETS / "icon.png"


def main() -> None:
    if not SRC.is_file():
        raise SystemExit(f"Logo source introuvable: {SRC}")

    img = Image.open(SRC).convert("RGBA")
    ASSETS.mkdir(parents=True, exist_ok=True)

    # tray-icon.png — 22px pour le system tray Windows
    tray = img.resize((22, 22), Image.LANCZOS)
    tray_path = ASSETS / "tray-icon.png"
    tray.save(tray_path)
    print(f"tray-icon.png genere: {tray_path}")

    # icon-small.png — 16px
    small = img.resize((16, 16), Image.LANCZOS)
    small_path = ASSETS / "icon-small.png"
    small.save(small_path)
    print(f"icon-small.png genere: {small_path}")

    # icon.ico — multi-tailles (barre des tâches, menu Démarrer, electron-builder)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_images = [img.resize(s, Image.LANCZOS) for s in sizes]
    ico_path = ASSETS / "icon.ico"
    ico_images[0].save(
        ico_path,
        format="ICO",
        sizes=sizes,
        append_images=ico_images[1:],
    )
    print(f"icon.ico genere (multi-tailles): {ico_path}")

    print("Tous les assets sont a jour (icon.png source inchange).")


if __name__ == "__main__":
    main()
