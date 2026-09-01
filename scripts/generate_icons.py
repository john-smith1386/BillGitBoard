"""Rasterize the BillGitBoard brand mark into the browser icon set.

The icons committed under `frontend/public/` are the design originals. This
script reproduces the same mark - an amber staircase across a three-by-three
grid on a navy squircle, over a near-white ground - so the set can be restyled
or rebuilt at other sizes. Its geometry and palette were measured from
`web-app-manifest-512x512.png` and render within about 2/255 of it, but running
it overwrites the originals, so keep a copy first.

`frontend/public/favicon.svg` is the vector twin of the same mark and is
maintained by hand; keep its numbers in step with the fractions below.

Usage:
    python scripts/generate_icons.py
    python scripts/generate_icons.py --output frontend/public
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

GROUND = (253, 253, 253, 255)
NAVY = (26, 56, 78, 255)
AMBER = (253, 167, 2, 255)
SLATE = (82, 107, 125, 255)

# Fractions of the icon edge, measured from the 512 px original.
TILE_LEFT = 48 / 512
TILE_TOP = 37 / 512
TILE_WIDTH = 415 / 512
TILE_HEIGHT = 407 / 512
TILE_RADIUS = 95 / 512
GRID_LEFT = 129 / 512
GRID_TOP = 107 / 512
CELL = 67 / 512
GAP = 27 / 512
CELL_RADIUS = 0.25  # of one cell

# Cell coordinates as (column, row) in the three-by-three grid.
AMBER_CELLS = ((0, 0), (0, 1), (1, 1), (1, 2), (2, 2))

SUPERSAMPLE = 8


def draw_mark(size: int) -> Image.Image:
    """Return one RGBA icon at `size` pixels square."""
    canvas = size * SUPERSAMPLE
    image = Image.new("RGBA", (canvas, canvas), GROUND)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (
            TILE_LEFT * canvas,
            TILE_TOP * canvas,
            (TILE_LEFT + TILE_WIDTH) * canvas,
            (TILE_TOP + TILE_HEIGHT) * canvas,
        ),
        radius=TILE_RADIUS * canvas,
        fill=NAVY,
    )

    cell = CELL * canvas
    pitch = cell + GAP * canvas
    for row in range(3):
        for column in range(3):
            left = GRID_LEFT * canvas + column * pitch
            top = GRID_TOP * canvas + row * pitch
            draw.rounded_rectangle(
                (left, top, left + cell, top + cell),
                radius=cell * CELL_RADIUS,
                fill=AMBER if (column, row) in AMBER_CELLS else SLATE,
            )

    # SUPERSAMPLE makes every reduction an exact integer ratio, where a box
    # filter is the ideal average and leaves no ringing around the cells.
    return image.resize((size, size), Image.BOX)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "frontend" / "public",
        help="directory for the generated icon files",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    # Pillow drops any requested ICO size larger than the base image, so the
    # base frame must be the biggest one.
    favicon = args.output / "favicon.ico"
    frames = [draw_mark(16), draw_mark(32), draw_mark(48)]
    frames[-1].save(
        favicon,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
        append_images=frames[:-1],
    )
    written.append(favicon)

    for name, size in (
        ("favicon-96x96.png", 96),
        ("apple-touch-icon.png", 180),
        ("web-app-manifest-192x192.png", 192),
        ("web-app-manifest-512x512.png", 512),
    ):
        path = args.output / name
        draw_mark(size).save(path, format="PNG", optimize=True)
        written.append(path)

    for path in written:
        print(f"wrote {path.relative_to(REPOSITORY_ROOT)}")
    print("favicon.svg is maintained by hand; keep its geometry in step with this script.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
