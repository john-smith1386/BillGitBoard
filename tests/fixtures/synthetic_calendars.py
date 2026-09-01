"""Deterministic GitHub-like contribution-calendar fixtures.

The production detector must learn geometry and colors from pixels rather than
from hard-coded GitHub dimensions or green shades.  These fixtures deliberately
vary scale, theme, hue, and partial-week occupancy while preserving an exactly
known 7 x C source grid.

They are generated at test time, so the repository does not need opaque binary
screenshots and a failing sample can be reproduced at any requested scale.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ThemeName = Literal["light", "dark", "halloween"]


PALETTES: dict[ThemeName, tuple[str, ...]] = {
    # Familiar GitHub-like colors are useful as a baseline, but the detector is
    # still expected to discover these values from the rendered cells.
    "light": ("#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"),
    "dark": ("#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"),
    # A deliberately non-green palette catches implementations that classify
    # shades by hue or hard-code the standard GitHub ramp.
    "halloween": ("#eee7f5", "#ffc680", "#ff9b42", "#d95d39", "#6f2dbd"),
}


@dataclass(frozen=True, slots=True)
class SyntheticCalendar:
    """Rendered image plus the pixel-space and cell-space source of truth."""

    image: Image.Image
    theme: ThemeName
    palette: tuple[str, ...]
    levels: np.ndarray
    present: np.ndarray
    boxes: dict[tuple[int, int], tuple[int, int, int, int]]
    rows: int
    cols: int
    scale: float
    cell_size: int
    gutter: int
    origin: tuple[int, int]

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.image.save(target, format="PNG", optimize=True)


def _level_for(row: int, col: int, shade_count: int) -> int:
    """Return a repeatable, non-trivial empty/filled contribution pattern."""

    # Roughly 60% empty, with every non-empty rank represented many times.
    if (row * 13 + col * 7) % 20 < 12:
        return 0
    return 1 + ((row * 5 + col * 3) % (shade_count - 1))


def _scaled(value: int, scale: float, *, minimum: int = 1) -> int:
    return max(minimum, round(value * scale))


def build_synthetic_calendar(
    *,
    theme: ThemeName = "light",
    scale: float = 1.0,
    cols: int = 53,
    partial_weeks: bool = False,
    add_legend: bool = True,
    allow_unsupported_cols: bool = False,
) -> SyntheticCalendar:
    """Build a crisp, reasonably cropped GitHub-style contribution screenshot.

    ``scale`` changes every grid measurement, not just the canvas size.  That
    makes half-, normal-, and double-resolution fixtures represent the same
    logical calendar without introducing resize interpolation artifacts.
    """

    if theme not in PALETTES:
        raise ValueError(f"unknown synthetic theme: {theme}")
    if scale <= 0:
        raise ValueError("scale must be positive")
    if not allow_unsupported_cols and not 40 <= cols <= 54:
        raise ValueError("synthetic calendars use the supported 40..54 columns")

    rows = 7
    palette = PALETTES[theme]
    cell = _scaled(12, scale, minimum=4)
    gutter = _scaled(3, scale)
    pitch = cell + gutter
    left = _scaled(48, scale)
    top = _scaled(34, scale)
    right_padding = _scaled(24, scale)
    footer = _scaled(42, scale)
    width = left + cols * pitch - gutter + right_padding
    height = top + rows * pitch - gutter + footer

    dark = theme == "dark"
    canvas = "#0d1117" if dark else "#ffffff"
    panel = "#0d1117" if dark else "#ffffff"
    ink = "#8b949e" if dark else "#57606a"
    border = "#30363d" if dark else "#d0d7de"

    image = Image.new("RGB", (width, height), canvas)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=_scaled(8, scale),
        fill=panel,
        outline=border,
        width=max(1, _scaled(1, scale)),
    )

    levels = np.zeros((rows, cols), dtype=np.uint8)
    present = np.ones((rows, cols), dtype=bool)
    if partial_weeks:
        # GitHub year views can omit dates before the range starts and after it
        # ends.  Interior holes are intentionally not generated here.
        present[0:3, 0] = False
        present[5:7, cols - 1] = False

    boxes: dict[tuple[int, int], tuple[int, int, int, int]] = {}
    radius = max(1, _scaled(2, scale))
    for row in range(rows):
        for col in range(cols):
            level = _level_for(row, col, len(palette))
            levels[row, col] = level
            x0 = left + col * pitch
            y0 = top + row * pitch
            box = (x0, y0, x0 + cell - 1, y0 + cell - 1)
            boxes[(row, col)] = box
            if present[row, col]:
                draw.rounded_rectangle(box, radius=radius, fill=palette[level])

    # Chrome deliberately creates non-grid contours.  A correct detector drops
    # these based on lattice membership rather than assuming a bare crop.
    font = ImageFont.load_default()
    month_names = ("Jan", "Mar", "May", "Jul", "Sep", "Nov")
    for index, month in enumerate(month_names):
        x = left + round(index * (cols - 1) * pitch / (len(month_names) - 1))
        draw.text((x, _scaled(12, scale)), month, fill=ink, font=font)
    for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        draw.text((_scaled(8, scale), top + row * pitch), label, fill=ink, font=font)

    footer_y = top + rows * pitch + _scaled(9, scale)
    draw.text(
        (left, footer_y),
        "Learn how we count contributions",
        fill=ink,
        font=font,
    )
    if add_legend:
        legend_x = width - right_padding - (len(palette) * pitch + _scaled(58, scale))
        draw.text((legend_x, footer_y), "Less", fill=ink, font=font)
        legend_x += _scaled(27, scale)
        legend_cell = max(4, _scaled(10, scale))
        legend_gap = max(2, _scaled(3, scale))
        for level, color in enumerate(palette):
            x0 = legend_x + level * (legend_cell + legend_gap)
            draw.rounded_rectangle(
                (x0, footer_y, x0 + legend_cell - 1, footer_y + legend_cell - 1),
                radius=max(1, radius - 1),
                fill=color,
            )
        more_x = legend_x + len(palette) * (legend_cell + legend_gap) + _scaled(2, scale)
        draw.text((more_x, footer_y), "More", fill=ink, font=font)

    return SyntheticCalendar(
        image=image,
        theme=theme,
        palette=palette,
        levels=levels,
        present=present,
        boxes=boxes,
        rows=rows,
        cols=cols,
        scale=scale,
        cell_size=cell,
        gutter=gutter,
        origin=(left, top),
    )


def image_bytes(calendar: SyntheticCalendar, image_format: str = "PNG") -> bytes:
    """Encode a generated fixture for multipart API tests."""

    buffer = BytesIO()
    save_kwargs: dict[str, int | bool] = {"optimize": True}
    if image_format.upper() == "JPEG":
        save_kwargs = {"quality": 92, "subsampling": 0}
    calendar.image.save(buffer, format=image_format, **save_kwargs)
    return buffer.getvalue()
