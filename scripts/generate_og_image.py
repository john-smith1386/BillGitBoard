"""Draw the social preview card used by Open Graph and Twitter cards.

The card is the product explaining itself: a GitHub-like contribution panel with
BILLGITBOARD set into it using the same 5x7 glyphs the renderer uses, so the
image a crawler shows is the thing the service actually does.

Usage:
    python scripts/generate_og_image.py
    python scripts/generate_og_image.py --output frontend/public
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from app.text.font_5x7 import FONT_5X7, GLYPH_WIDTH, LETTER_GAP, SPACE_WIDTH
from app.text.layout import needed_columns

WIDTH = 1200
HEIGHT = 630

INK = (10, 22, 32)
MUTED = (104, 119, 126)
NAVY = (26, 56, 78)
AMBER = (253, 167, 2)
PAPER = (255, 254, 249)
BACKGROUND = (245, 246, 241)
LINE = (220, 226, 220)

EMPTY_CELL = (235, 237, 240)
CONTRIBUTION_RAMP = (
    (155, 233, 168),
    (64, 196, 99),
    (48, 161, 78),
    (33, 110, 57),
)

WORD = "YOUR NAME"
HEADLINE = "Put your name in the graph."
SUBLINE = "Upload a contribution-calendar screenshot. Download a PNG. No login, no commits."

# Weighted so the surrounding graph stays quiet enough for the amber word to
# read at thumbnail size: mostly empty days, a scattering of light green.
# Seeded, because the card must regenerate byte-identically.
FILLER_WEIGHTS = (88, 7, 3, 1, 1)
FILLER_SEED = 20240817

BOLD_FONT_CANDIDATES = (
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)
REGULAR_FONT_CANDIDATES = (
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def load_font(size: int, *, bold: bool) -> ImageFont.ImageFont:
    """Return a scalable font, falling back to the one Pillow bundles."""
    for candidate in BOLD_FONT_CANDIDATES if bold else REGULAR_FONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def glyph_columns(word: str) -> list[list[bool]]:
    """Return the word as columns of seven booleans.

    Spacing follows the renderer: one column between each pair of glyphs, three
    columns for a literal space, and no extra gap around a space. The result is
    checked against the authoritative width so this card cannot drift from what
    the service would actually draw.
    """
    columns: list[list[bool]] = []
    glyph_count = 0
    for character in word:
        if character == " ":
            columns.extend([False] * 7 for _ in range(SPACE_WIDTH))
            continue
        if glyph_count:
            columns.extend([False] * 7 for _ in range(LETTER_GAP))
        rows = FONT_5X7[character]
        for column in range(GLYPH_WIDTH):
            columns.append([rows[row][column] == "#" for row in range(7)])
        glyph_count += 1

    if len(columns) != needed_columns(word):
        raise AssertionError(
            f"laid out {len(columns)} columns, renderer needs {needed_columns(word)}"
        )
    return columns


def draw_background(image: Image.Image) -> None:
    """Paint the two soft brand glows the application uses behind its own page."""
    glow = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    overlay = ImageDraw.Draw(glow)
    overlay.ellipse((-320, -420, 700, 380), fill=(250, 240, 222))
    overlay.ellipse((640, -460, 1560, 300), fill=(232, 238, 243))
    image.paste(glow.filter(ImageFilter.GaussianBlur(150)), (0, 0))


def draw_brand(draw: ImageDraw.ImageDraw, left: int, top: int) -> None:
    """Draw the navy tile mark followed by the wordmark."""
    tile = 54
    draw.rounded_rectangle((left, top, left + tile, top + tile), radius=13, fill=NAVY)
    cell = 10
    gap = 3
    origin = left + (tile - (cell * 3 + gap * 2)) / 2
    amber_cells = {(0, 0), (0, 1), (1, 1), (1, 2), (2, 2)}
    for row in range(3):
        for column in range(3):
            x = origin + column * (cell + gap)
            y = top + (tile - (cell * 3 + gap * 2)) / 2 + row * (cell + gap)
            fill = AMBER if (column, row) in amber_cells else (82, 107, 125)
            draw.rounded_rectangle((x, y, x + cell, y + cell), radius=3, fill=fill)

    font = load_font(38, bold=True)
    draw.text((left + tile + 18, top + tile / 2), "BillGitBoard", font=font, fill=INK, anchor="lm")


def draw_panel(image: Image.Image, draw: ImageDraw.ImageDraw, top: int) -> int:
    """Draw the contribution panel with the word set into it. Returns its bottom edge."""
    columns = glyph_columns(WORD)
    cell = 16
    gap = 4
    pitch = cell + gap
    grid_width = len(columns) * pitch - gap
    grid_height = 7 * pitch - gap

    padding = 34
    panel_width = grid_width + padding * 2
    panel_left = (WIDTH - panel_width) / 2
    panel_bottom = top + grid_height + padding * 2

    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (panel_left, top + 10, panel_left + panel_width, panel_bottom + 12),
        radius=22,
        fill=(34, 49, 42, 34),
    )
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))

    draw.rounded_rectangle(
        (panel_left, top, panel_left + panel_width, panel_bottom),
        radius=22,
        fill=PAPER,
        outline=LINE,
        width=1,
    )

    filler = random.Random(FILLER_SEED)
    levels = (0, *range(1, len(CONTRIBUTION_RAMP) + 1))
    for column_index, column in enumerate(columns):
        for row in range(7):
            x = panel_left + padding + column_index * pitch
            y = top + padding + row * pitch
            if column[row]:
                fill = AMBER
            else:
                level = filler.choices(levels, weights=FILLER_WEIGHTS)[0]
                fill = EMPTY_CELL if level == 0 else CONTRIBUTION_RAMP[level - 1]
            draw.rounded_rectangle((x, y, x + cell, y + cell), radius=3, fill=fill)

    return int(panel_bottom)


def build_card() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw_background(image)
    image = image.convert("RGBA")
    draw = ImageDraw.Draw(image)

    draw_brand(draw, 96, 74)
    panel_bottom = draw_panel(image, draw, 206)

    draw.text(
        (WIDTH / 2, panel_bottom + 74),
        HEADLINE,
        font=load_font(52, bold=True),
        fill=INK,
        anchor="mm",
    )
    draw.text(
        (WIDTH / 2, panel_bottom + 132),
        SUBLINE,
        font=load_font(26, bold=False),
        fill=MUTED,
        anchor="mm",
    )
    return image.convert("RGB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "frontend" / "public",
        help="directory for the generated card",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    destination = args.output / "og-image.png"
    build_card().save(destination, format="PNG", optimize=True)
    print(f"wrote {destination.relative_to(REPOSITORY_ROOT)} ({destination.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
