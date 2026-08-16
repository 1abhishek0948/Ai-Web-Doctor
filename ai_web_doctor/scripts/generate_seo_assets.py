"""Generate SEO assets (favicon, apple-touch-icon, og-image) with Pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path("static/img")
OUT.mkdir(parents=True, exist_ok=True)

BRAND = (37, 99, 235)  # #2563eb
BRAND_DARK = (30, 64, 175)  # #1e40af
ACCENT = (139, 92, 246)  # #8b5cf6
WHITE = (255, 255, 255)
MUTED = (203, 213, 225)  # slate-300

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
]


def font(size: int, index: int = 0) -> ImageFont.FreeTypeFont | None:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size, index=index)
        except (OSError, IndexError):
            continue
    return None


def rounded_rect(draw: ImageDraw.ImageDraw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def draw_plus(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color):
    bar = max(2, int(size * 0.22))
    half = size / 2
    draw.rectangle([cx - half, cy - bar / 2, cx + half, cy + bar / 2], fill=color)
    draw.rectangle([cx - bar / 2, cy - half, cx + bar / 2, cy + half], fill=color)


def favicon_png(size: int, path: Path):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = size * 0.22
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=BRAND)
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-size * 0.1, -size * 0.15, size * 0.55, size * 0.45], fill=(96, 165, 250, 60))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img)
    draw_plus(draw, size / 2, size / 2, size * 0.44, WHITE)
    img.save(path)


def apple_touch(size: int, path: Path):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, size - 1, size - 1], fill=BRAND)
    draw_plus(draw, size / 2, size / 2, size * 0.42, WHITE)
    img.save(path)


def og_image(path: Path):
    width, height = 1200, 630
    img = Image.new("RGB", (width, height), BRAND_DARK)
    draw = ImageDraw.Draw(img)

    for y in range(height):
        t = y / height
        r = int(BRAND[0] + (ACCENT[0] - BRAND[0]) * t)
        g = int(BRAND[1] + (ACCENT[1] - BRAND[1]) * t)
        b = int(BRAND[2] + (ACCENT[2] - BRAND[2]) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.ellipse([-200, -250, 500, 400], fill=(255, 255, 255, 18))
    od.ellipse([900, 350, 1500, 950], fill=(255, 255, 255, 14))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    title_font = font(96) or ImageFont.load_default()
    tag_font = font(38) or ImageFont.load_default()
    draw.text((80, 150), "AI Web Doctor", font=title_font, fill=WHITE)
    draw.text(
        (82, 290),
        "Website UI testing & responsive design checker",
        font=tag_font,
        fill=MUTED,
    )
    draw.text(
        (82, 380),
        "Find broken UI before your users do.",
        font=tag_font,
        fill=WHITE,
    )
    draw_plus(draw, 1120, 150, 110, WHITE)
    draw.rounded_rectangle([80, 480, 1120, 540], radius=30, outline=WHITE, width=3)
    img.save(path)


favicon_png(32, OUT / "favicon-32x32.png")
apple_touch(180, OUT / "apple-touch-icon.png")
og_image(OUT / "og-image.png")
print("generated:", sorted(p.name for p in OUT.iterdir()))