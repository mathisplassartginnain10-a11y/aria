from pathlib import Path


def generate_icon():
    assets_dir = Path("assets")
    assets_dir.mkdir(exist_ok=True)
    ico_path = assets_dir / "aria.ico"

    if ico_path.exists():
        return

    try:
        from PIL import Image, ImageDraw, ImageFont

        sizes = [16, 32, 48, 64, 128, 256]
        images = []

        for size in sizes:
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            margin = size // 8
            draw.ellipse(
                [margin, margin, size - margin, size - margin],
                fill=(8, 8, 16, 255),
                outline=(74, 158, 255, 255),
                width=max(1, size // 16),
            )

            font_size = size // 2
            try:
                font = ImageFont.truetype("consola.ttf", font_size)
            except OSError:
                font = ImageFont.load_default()

            text = "A"
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            x = (size - text_w) // 2
            y = (size - text_h) // 2
            draw.text((x, y), text, fill=(74, 158, 255, 255), font=font)

            images.append(img)

        images[0].save(
            ico_path,
            format="ICO",
            sizes=[(s, s) for s in sizes],
            append_images=images[1:],
        )
        print(f"Icône générée : {ico_path}")

    except ImportError:
        print("PIL absent, icône par défaut utilisée")


if __name__ == "__main__":
    generate_icon()
