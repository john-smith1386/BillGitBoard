"""Pillow compositor for a crisp, source-derived contribution card."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.color.ramp import build_primary_ramp, hex_to_rgb
from app.schemas import JobArtifact
from app.text.layout import LayoutResult

from .glyphs import build_glyph_masks


@dataclass(frozen=True, slots=True)
class CalendarGeometry:
    cols: int
    cell: int = 12
    gutter: int = 3
    radius: int = 2
    left: int = 48
    top: int = 34
    right: int = 94
    bottom: int = 48

    @property
    def pitch(self) -> int:
        return self.cell + self.gutter

    @property
    def grid_width(self) -> int:
        return self.cols * self.cell + max(0, self.cols - 1) * self.gutter

    @property
    def grid_height(self) -> int:
        return 7 * self.cell + 6 * self.gutter

    @property
    def width(self) -> int:
        return self.left + self.grid_width + self.right

    @property
    def height(self) -> int:
        return self.top + self.grid_height + self.bottom

    def cell_box(self, row: int, col: int) -> tuple[int, int, int, int]:
        x0 = self.left + col * self.pitch
        y0 = self.top + row * self.pitch
        return (x0, y0, x0 + self.cell - 1, y0 + self.cell - 1)


@dataclass(frozen=True, slots=True)
class RenderedCalendar:
    image: Image.Image
    png: bytes
    letter_cells: int
    overlap_cells: int
    empty_letter_cells: int
    primary_ramp: dict[int, str]
    geometry: CalendarGeometry


def _rgba_layer(size: tuple[int, int], color: str, mask: Image.Image) -> Image.Image:
    red, green, blue = hex_to_rgb(color)
    layer = Image.new("RGBA", size, (red, green, blue, 0))
    layer.putalpha(mask)
    return layer


def _artifact_arrays(artifact: JobArtifact) -> tuple[np.ndarray, np.ndarray]:
    present = np.zeros((7, artifact.cols), dtype=bool)
    levels = np.zeros((7, artifact.cols), dtype=np.int16)
    for cell in artifact.cells:
        if cell.c >= artifact.cols:
            raise ValueError("artifact cell column exceeds grid")
        present[cell.r, cell.c] = cell.present
        levels[cell.r, cell.c] = cell.level
    return present, levels


def _draw_chrome(
    draw: ImageDraw.ImageDraw,
    geometry: CalendarGeometry,
    artifact: JobArtifact,
) -> None:
    dark = artifact.theme == "dark"
    text_color = "#8B949E" if dark else "#57606A"
    font = ImageFont.load_default()
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    occupied_positions: set[int] = set()
    for index, month in enumerate(months):
        col = min(artifact.cols - 1, round(index * artifact.cols / 12))
        if col in occupied_positions:
            continue
        occupied_positions.add(col)
        draw.text((geometry.left + col * geometry.pitch, 13), month, fill=text_color, font=font)
    for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        draw.text((10, geometry.top + row * geometry.pitch), label, fill=text_color, font=font)

    footer_y = geometry.top + geometry.grid_height + 14
    draw.text(
        (geometry.left, footer_y),
        "Learn how we count contributions",
        fill=text_color,
        font=font,
    )
    legend_cell = 10
    legend_gap = 3
    palette = [artifact.palette[str(level)] for level in range(artifact.levels)]
    legend_width = 27 + len(palette) * (legend_cell + legend_gap) + 31
    legend_x = geometry.width - 18 - legend_width
    draw.text((legend_x, footer_y), "Less", fill=text_color, font=font)
    legend_x += 27
    for color in palette:
        draw.rounded_rectangle(
            (legend_x, footer_y, legend_x + legend_cell - 1, footer_y + legend_cell - 1),
            radius=2,
            fill=color,
        )
        legend_x += legend_cell + legend_gap
    draw.text((legend_x + 2, footer_y), "More", fill=text_color, font=font)


def render_calendar(
    artifact: JobArtifact,
    layout: LayoutResult,
    *,
    primary: str,
    secondary: str,
    outline: str = "#0A1620",
    boldness: int = 2,
    geometry: CalendarGeometry | None = None,
) -> RenderedCalendar:
    """Render the parsed grid without re-detecting or inventing any cell."""

    if layout.letter_id.shape != (7, artifact.cols):
        raise ValueError("layout does not match artifact dimensions")
    if not 0 <= boldness <= 8:
        raise ValueError("boldness must be between 0 and 8")
    # Validate all user colors before any drawing.
    hex_to_rgb(primary)
    hex_to_rgb(secondary)
    hex_to_rgb(outline)

    geometry = geometry or CalendarGeometry(cols=artifact.cols)
    if geometry.cols != artifact.cols:
        raise ValueError("geometry does not match artifact dimensions")
    present, levels = _artifact_arrays(artifact)
    if np.any((layout.letter_id > 0) & ~present):
        raise ValueError("layout paints an absent cell")

    panel = artifact.panel_color
    border = "#30363D" if artifact.theme == "dark" else "#D0D7DE"
    image = Image.new("RGB", (geometry.width, geometry.height), panel)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, geometry.width - 1, geometry.height - 1),
        radius=12,
        fill=panel,
        outline=border,
        width=1,
    )
    _draw_chrome(draw, geometry, artifact)

    glyph_masks = build_glyph_masks(
        image.size,
        layout.letter_id,
        present,
        geometry.cell_box,
        gutter=geometry.gutter,
        radius=geometry.radius,
        boldness=boldness,
    )
    composed = image.convert("RGBA")
    composed = Image.alpha_composite(
        composed, _rgba_layer(image.size, "#000000", glyph_masks.shadow)
    )
    if boldness:
        composed = Image.alpha_composite(
            composed, _rgba_layer(image.size, outline, glyph_masks.outline)
        )

    ramp = build_primary_ramp(primary, artifact.levels, artifact.theme)
    draw = ImageDraw.Draw(composed)
    overlap = 0
    empty = 0
    letter_count = 0
    for row in range(7):
        for col in range(artifact.cols):
            if not present[row, col]:
                continue
            level = int(levels[row, col])
            glyph = int(layout.letter_id[row, col])
            if glyph == 0:
                color = artifact.palette[str(level)]
            elif level == 0:
                color = secondary.upper()
                empty += 1
                letter_count += 1
            else:
                color = ramp[level]
                overlap += 1
                letter_count += 1
            draw.rounded_rectangle(
                geometry.cell_box(row, col),
                radius=geometry.radius,
                fill=color,
            )

    composed = Image.alpha_composite(composed, _rgba_layer(image.size, "#FFFFFF", glyph_masks.rim))
    output_image = composed.convert("RGB")
    buffer = BytesIO()
    output_image.save(buffer, format="PNG", optimize=True)
    return RenderedCalendar(
        image=output_image,
        png=buffer.getvalue(),
        letter_cells=letter_count,
        overlap_cells=overlap,
        empty_letter_cells=empty,
        primary_ramp=ramp,
        geometry=geometry,
    )
