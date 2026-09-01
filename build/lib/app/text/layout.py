"""Authoritative name validation, fit checking, and glyph-mask layout."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from app.errors import ServiceError

from .font_5x7 import FONT_5X7, GLYPH_WIDTH, LETTER_GAP, SPACE_WIDTH

_VALID_NAME = re.compile(r"^[A-Z0-9 ]{1,24}$")


@dataclass(frozen=True, slots=True)
class LayoutResult:
    name: str
    needed_cols: int
    start: int
    letter_id: np.ndarray
    letter_cells: int


def normalize_name(name: str) -> str:
    normalized = name.strip().upper()
    if not _VALID_NAME.fullmatch(normalized):
        raise ServiceError("INVALID_NAME", "only A-Z, 0-9, space")
    return normalized


def character_width(character: str) -> int:
    if character == " ":
        return SPACE_WIDTH
    if character in FONT_5X7:
        return GLYPH_WIDTH
    raise ServiceError("INVALID_NAME", "only A-Z, 0-9, space")


def needed_columns(name: str) -> int:
    """Return cell columns required by a normalized or raw valid name.

    Every alphanumeric glyph is five columns wide, literal spaces are three
    columns wide, and one fixed column separates each pair of glyphs. Spaces
    do not introduce extra letter gaps of their own.
    """

    normalized = normalize_name(name)
    glyph_count = sum(character != " " for character in normalized)
    space_count = len(normalized) - glyph_count
    return (
        GLYPH_WIDTH * glyph_count + LETTER_GAP * max(0, glyph_count - 1) + SPACE_WIDTH * space_count
    )


def _build_mask(name: str, cols: int, start: int) -> np.ndarray:
    mask = np.zeros((7, cols), dtype=np.int16)
    cursor = start
    glyph_count = 0
    for character in name:
        if character == " ":
            cursor += SPACE_WIDTH
            continue

        if glyph_count:
            cursor += LETTER_GAP
        glyph_id = glyph_count + 1
        glyph = FONT_5X7[character]
        for row, bitmap_row in enumerate(glyph):
            for offset, value in enumerate(bitmap_row):
                if value == "#":
                    mask[row, cursor + offset] = glyph_id
        cursor += GLYPH_WIDTH
        glyph_count += 1
    return mask


def _present_array(present: Sequence[Sequence[bool]] | np.ndarray | None, cols: int) -> np.ndarray:
    if present is None:
        return np.ones((7, cols), dtype=bool)
    array = np.asarray(present, dtype=bool)
    if array.shape != (7, cols):
        raise ValueError(f"present must have shape (7, {cols})")
    return array


def layout_name(
    name: str,
    cols: int,
    present: Sequence[Sequence[bool]] | np.ndarray | None = None,
    start: int | None = None,
) -> LayoutResult:
    """Lay a name onto a real 7-row grid without touching absent cells.

    If the initial placement intersects a partial week, the complete word is
    shifted deterministically left/right by up to three columns.  This keeps
    the glyph pixels unchanged while honoring the source occupancy map.
    """

    normalized = normalize_name(name)
    required = needed_columns(normalized)
    if required > cols:
        hint = max(1, (cols + LETTER_GAP) // (GLYPH_WIDTH + LETTER_GAP))
        raise ServiceError(
            "NAME_TOO_LONG",
            f"{normalized} needs {required} columns; this graph has {cols}",
            name=normalized,
            needed_cols=required,
            cols=cols,
            max_letters_hint=hint,
        )

    if start is None:
        initial = (cols - required) // 2
    else:
        initial = int(start)
        if initial < 0 or initial + required > cols:
            raise ServiceError(
                "NAME_OVERFLOW",
                "The requested start position exceeds the detected grid",
                start=initial,
                needed_cols=required,
                cols=cols,
            )

    occupancy = _present_array(present, cols)
    candidates = [initial]
    for distance in range(1, 4):
        candidates.extend((initial - distance, initial + distance))

    for candidate in candidates:
        if candidate < 0 or candidate + required > cols:
            continue
        mask = _build_mask(normalized, cols, candidate)
        if not np.any((mask > 0) & ~occupancy):
            return LayoutResult(
                name=normalized,
                needed_cols=required,
                start=candidate,
                letter_id=mask,
                letter_cells=int(np.count_nonzero(mask)),
            )

    raise ServiceError(
        "NAME_HITS_ABSENT_CELLS",
        "The name intersects unavailable cells in a partial week",
        needed_cols=required,
        cols=cols,
        start=initial,
    )
