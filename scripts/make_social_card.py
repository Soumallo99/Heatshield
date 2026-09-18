"""Draw the social share card (Open Graph / Twitter) for HeatShield.

Generated rather than hand-made so it can be regenerated when the copy changes,
and so the colours and type stay the ones the app actually uses:

    .venv/bin/python scripts/make_social_card.py

Writes frontend/web/public/social-card.png (1200x630 — the size every platform
crops from). The card is drawn with Pillow: no AI imagery, no stock photograph,
nothing whose licence has to be checked. If you want a photo of a heatwave here,
you have to source and licence it yourself — which is exactly why this is a
typographic card.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "web" / "public" / "social-card.png"

WIDTH, HEIGHT = 1200, 630
INK = (7, 8, 13)                 # --bg, the app's near-black
WARM = (255, 185, 104)           # accent, from the app icon
CREAM = (255, 232, 200)          # icon highlight
MUTED = (150, 156, 172)

SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SANS_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:                                    # pragma: no cover - fallback
        return ImageFont.load_default()


def _gradient_background() -> Image.Image:
    """Vertical wash plus a warm glow, matching the dashboard's mood."""
    image = Image.new("RGB", (WIDTH, HEIGHT), INK)
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        blend = y / HEIGHT
        row = tuple(int(INK[i] + (18 - INK[i]) * blend) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=row)
    glow = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for radius, opacity in ((520, 14), (400, 20), (280, 26), (160, 30)):
        glow_draw.ellipse(
            [WIDTH - 300 - radius, -radius + 120, WIDTH - 300 + radius, radius + 120],
            fill=(opacity * 8, opacity * 5, 0),
        )
    return Image.blend(image, Image.blend(image, glow, 0.5), 0.45)


def _text(draw: ImageDraw.ImageDraw, xy, body, font, fill, spacing=0) -> None:
    if not spacing:
        draw.text(xy, body, font=font, fill=fill)
        return
    x, y = xy
    for letter in body:
        draw.text((x, y), letter, font=font, fill=fill)
        x += draw.textlength(letter, font=font) + spacing


def main() -> Path:
    image = _gradient_background()
    draw = ImageDraw.Draw(image)

    # Left rule, the way the app frames its cards.
    draw.rectangle([64, 64, 68, HEIGHT - 64], fill=WARM)

    _text(draw, (108, 78), "HEATSHIELD", _font(SANS_BOLD, 30), WARM, spacing=6)
    _text(draw, (108, 122), "extreme heat early warning", _font(SANS, 24), MUTED)

    _text(draw, (104, 186), "141 wards.", _font(SERIF, 84), CREAM)
    _text(draw, (104, 286), "One honest number", _font(SERIF, 84), CREAM)
    _text(draw, (104, 386), "per neighbourhood.", _font(SERIF, 84), CREAM)

    body = (
        "Ward-level heat risk and thermal stress for Kolkata, with the "
        "protective action attached — on keyless open data."
    )
    lines, line, font_body = [], "", _font(SANS, 26)
    for word in body.split():
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=font_body) > WIDTH - 240:
            lines.append(line)
            line = word
        else:
            line = candidate
    lines.append(line)
    for index, text_line in enumerate(lines):
        _text(draw, (108, 500 + index * 36), text_line, font_body, MUTED)

    # Data-source strip: the claim this project actually makes.
    strip = "Open-Meteo · Census 2011 · KMC wards · OpenStreetMap"
    _text(draw, (108, HEIGHT - 52), strip, _font(SANS, 20), (110, 116, 130))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT, "PNG", optimize=True)
    return OUT


if __name__ == "__main__":
    path = main()
    size = path.stat().st_size
    print(f"social card -> {path} ({size / 1024:.1f} KB, {WIDTH}x{HEIGHT})")
