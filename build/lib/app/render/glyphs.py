"""Connected per-glyph silhouette, outline, shadow, and rim masks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageDraw

BoxProvider = Callable[[int, int], tuple[int, int, int, int]]


@dataclass(frozen=True, slots=True)
class GlyphMasks:
    shadow: Image.Image
    outline: Image.Image
    rim: Image.Image
    unions: tuple[Image.Image, ...]


def _shift(array: np.ndarray, dx: int, dy: int) -> np.ndarray:
    shifted = np.zeros_like(array)
    source_x0 = max(0, -dx)
    source_x1 = array.shape[1] - max(0, dx)
    source_y0 = max(0, -dy)
    source_y1 = array.shape[0] - max(0, dy)
    target_x0 = max(0, dx)
    target_x1 = target_x0 + (source_x1 - source_x0)
    target_y0 = max(0, dy)
    target_y1 = target_y0 + (source_y1 - source_y0)
    if source_x1 > source_x0 and source_y1 > source_y0:
        shifted[target_y0:target_y1, target_x0:target_x1] = array[
            source_y0:source_y1, source_x0:source_x1
        ]
    return shifted


def _mask_image(array: np.ndarray, alpha: int = 255) -> Image.Image:
    return Image.fromarray(np.where(array, alpha, 0).astype(np.uint8), mode="L")


def build_glyph_masks(
    size: tuple[int, int],
    letter_id: np.ndarray,
    present: np.ndarray,
    cell_box: BoxProvider,
    *,
    gutter: int,
    radius: int,
    boldness: int,
) -> GlyphMasks:
    """Create masks while protecting the interiors of every foreign cell."""

    width, height = size
    if letter_id.shape != present.shape or letter_id.shape[0] != 7:
        raise ValueError("letter_id and present must share a 7 x C shape")

    foreign = Image.new("L", size, 0)
    foreign_draw = ImageDraw.Draw(foreign)
    for row in range(7):
        for col in range(letter_id.shape[1]):
            if letter_id[row, col] != 0:
                continue
            x0, y0, x1, y1 = cell_box(row, col)
            if not present[row, col]:
                # An absent slot must never acquire a glyph-like painted cell.
                foreign_draw.rectangle((x0, y0, x1, y1), fill=255)
                continue
            inset_x = max(1, round((x1 - x0 + 1) * 0.10))
            inset_y = max(1, round((y1 - y0 + 1) * 0.10))
            foreign_draw.rectangle(
                (x0 + inset_x, y0 + inset_y, x1 - inset_x, y1 - inset_y),
                fill=255,
            )
    protected = np.asarray(foreign, dtype=np.uint8) > 0

    shadow_total = np.zeros((height, width), dtype=bool)
    outline_total = np.zeros((height, width), dtype=bool)
    rim_total = np.zeros((height, width), dtype=bool)
    unions: list[Image.Image] = []
    merge = max(1, (gutter + 1) // 2)
    kernel = None
    if boldness > 0:
        kernel_size = boldness * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))

    for glyph_id in sorted(int(value) for value in np.unique(letter_id) if value > 0):
        union_image = Image.new("L", size, 0)
        union_draw = ImageDraw.Draw(union_image)
        rows, cols = np.nonzero(letter_id == glyph_id)
        glyph_cells = {(int(row), int(col)) for row, col in zip(rows, cols, strict=True)}
        centers: dict[tuple[int, int], tuple[int, int]] = {}
        for row, col in glyph_cells:
            x0, y0, x1, y1 = cell_box(row, col)
            centers[(row, col)] = ((x0 + x1) // 2, (y0 + y1) // 2)
        # Rounded corners can leave diagonally adjacent bitmap pixels separated
        # by one transparent pixel even after rectangle inflation.  Connect
        # only neighboring cells owned by this glyph; the narrow bridge stays
        # in their shared gutter/corner and never expands the logical mask.
        for row, col in glyph_cells:
            for delta_row, delta_col in ((0, 1), (1, -1), (1, 0), (1, 1)):
                neighbor = (row + delta_row, col + delta_col)
                if neighbor in glyph_cells:
                    union_draw.line(
                        (centers[(row, col)], centers[neighbor]),
                        fill=255,
                        width=merge * 2 + 1,
                    )
        for row, col in zip(rows, cols, strict=True):
            x0, y0, x1, y1 = cell_box(int(row), int(col))
            union_draw.rounded_rectangle(
                (x0 - merge, y0 - merge, x1 + merge, y1 + merge),
                radius=radius + merge,
                fill=255,
            )
        union = np.asarray(union_image, dtype=np.uint8) > 0
        unions.append(union_image)

        shadow = _shift(union, 2, 2) & ~protected
        shadow_total |= shadow

        if kernel is not None:
            dilated = cv2.dilate(union.astype(np.uint8), kernel, iterations=1) > 0
            outline_total |= dilated & ~union & ~protected

        # Pixels present in the union but not in its down-right shift are the
        # top/left-facing edge.  This is a restrained one-pixel highlight.
        rim_total |= union & ~_shift(union, 1, 1) & ~protected

    return GlyphMasks(
        shadow=_mask_image(shadow_total, 89),
        outline=_mask_image(outline_total),
        rim=_mask_image(rim_total, 51),
        unions=tuple(unions),
    )
