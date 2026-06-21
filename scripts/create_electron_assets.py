"""Génère les icônes PNG minimales pour Electron (tray, app, small)."""

from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Pillow requis: pip install Pillow")

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "electron" / "assets"


def make_icon(size: int, path: Path) -> None:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = max(1, size // 8)
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=(108, 142, 255, 255),
        outline=(180, 200, 255, 200),
    )
    inner = size // 3
    draw.ellipse(
        [size // 2 - inner // 2, size // 2 - inner // 2,
         size // 2 + inner // 2, size // 2 + inner // 2],
        fill=(40, 60, 140, 255),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    print("Created", path)


def make_ico(path: Path) -> None:
    src = ASSETS / "icon.png"
    if not src.exists():
        make_icon(512, src)
    img = Image.open(src)
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    imgs = [img.resize(size, Image.Resampling.LANCZOS) for size in sizes]
    imgs[0].save(
        path,
        format="ICO",
        sizes=[(s[0], s[1]) for s in sizes],
        append_images=imgs[1:],
    )
    print("Created", path)


def main() -> None:
    make_icon(512, ASSETS / "icon.png")
    make_icon(256, ASSETS / "icon-small.png")
    make_icon(22, ASSETS / "tray-icon.png")
    make_ico(ASSETS / "icon.ico")
    print("Assets Electron OK:", ASSETS)


if __name__ == "__main__":
    main()
