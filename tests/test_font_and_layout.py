from __future__ import annotations

import numpy as np
import pytest

from app.errors import ServiceError
from app.text.font_5x7 import FONT_5X7, GLYPH_HEIGHT, GLYPH_WIDTH
from app.text.layout import layout_name, needed_columns, normalize_name


def test_font_contains_every_supported_letter_and_digit() -> None:
    assert set(FONT_5X7) == set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    assert all(len(rows) == GLYPH_HEIGHT for rows in FONT_5X7.values())
    assert all(len(row) == GLYPH_WIDTH for rows in FONT_5X7.values() for row in rows)
    assert all(set(row) <= {"#", "."} for rows in FONT_5X7.values() for row in rows)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("A", 5),
        ("AB", 11),
        ("JOBERNEY", 47),
        ("A B", 14),
        ("1 2", 14),
        ("A  B", 17),
    ],
)
def test_needed_columns_uses_fixed_font_gap_and_space_width(name: str, expected: int) -> None:
    assert needed_columns(name) == expected


def test_name_normalization_is_case_insensitive_but_strict() -> None:
    assert normalize_name("  job 42 ") == "JOB 42"
    assert normalize_name("  job   42 ") == "JOB   42"
    with pytest.raises(ServiceError) as exc_info:
        normalize_name("hello-world")
    assert exc_info.value.code == "INVALID_NAME"


def test_layout_centers_joberny_without_enlarging_glyphs() -> None:
    result = layout_name("joberney", cols=53)

    assert result.name == "JOBERNEY"
    assert result.needed_cols == 47
    assert result.start == 3
    assert result.letter_id.shape == (7, 53)
    assert result.letter_cells == int(np.count_nonzero(result.letter_id))
    assert set(np.unique(result.letter_id)) <= set(range(9))
    assert not np.any(result.letter_id[:, :3])
    assert not np.any(result.letter_id[:, 50:])


def test_layout_keeps_space_columns_empty_and_preserves_letter_ids() -> None:
    result = layout_name("A B", cols=14, start=0)

    # A occupies 0..4, the three-column space is 5..7, the fixed glyph gap is
    # 8, and B occupies 9..13. Glyph IDs remain contiguous across spaces.
    assert not np.any(result.letter_id[:, 5:9])
    assert set(np.unique(result.letter_id)) == {0, 1, 2}


def test_layout_preserves_repeated_space_columns() -> None:
    result = layout_name("A  B", cols=17, start=0)

    assert result.name == "A  B"
    assert result.needed_cols == 17
    assert not np.any(result.letter_id[:, 5:12])
    assert set(np.unique(result.letter_id)) == {0, 1, 2}


def test_name_too_long_returns_machine_readable_fit_context() -> None:
    with pytest.raises(ServiceError) as exc_info:
        layout_name("JOBERNEY99", cols=53)

    error = exc_info.value
    assert error.code == "NAME_TOO_LONG"
    assert error.extra["needed_cols"] == 59
    assert error.extra["cols"] == 53


def test_explicit_start_must_keep_the_whole_word_on_grid() -> None:
    with pytest.raises(ServiceError) as exc_info:
        layout_name("AB", cols=20, start=10)

    assert exc_info.value.code == "NAME_OVERFLOW"
    assert exc_info.value.extra == {"start": 10, "needed_cols": 11, "cols": 20}


def test_partial_week_collision_shifts_the_entire_word() -> None:
    present = np.ones((7, 9), dtype=bool)
    present[0, 3] = False

    result = layout_name("A", cols=9, present=present)

    assert result.start != 2  # centered placement collided
    assert abs(result.start - 2) <= 3
    assert not np.any((result.letter_id > 0) & ~present)


def test_unavoidable_partial_week_collision_is_rejected() -> None:
    present = np.zeros((7, 5), dtype=bool)

    with pytest.raises(ServiceError) as exc_info:
        layout_name("A", cols=5, present=present)

    assert exc_info.value.code == "NAME_HITS_ABSENT_CELLS"


def test_present_mask_shape_is_checked() -> None:
    with pytest.raises(ValueError, match="shape"):
        layout_name("A", cols=5, present=np.ones((6, 5), dtype=bool))
