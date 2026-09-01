from __future__ import annotations

import numpy as np
import pytest

from tests.fixtures import PALETTES, build_synthetic_calendar, image_bytes


@pytest.mark.parametrize("scale", [0.5, 1.0, 2.0])
def test_scaled_fixtures_preserve_the_same_cell_space(scale: float) -> None:
    calendar = build_synthetic_calendar(theme="light", scale=scale)
    baseline = build_synthetic_calendar(theme="light", scale=1.0)

    assert calendar.rows == 7
    assert calendar.cols == 53
    assert calendar.levels.shape == (7, 53)
    assert np.array_equal(calendar.levels, baseline.levels)
    assert np.array_equal(calendar.present, baseline.present)
    assert calendar.image.width >= 400
    assert calendar.image.height >= 80


@pytest.mark.parametrize("theme", ["light", "dark", "halloween"])
def test_theme_fixture_uses_every_declared_palette_level(theme: str) -> None:
    calendar = build_synthetic_calendar(theme=theme)  # type: ignore[arg-type]

    assert calendar.palette == PALETTES[theme]
    assert set(np.unique(calendar.levels)) == set(range(len(calendar.palette)))
    assert image_bytes(calendar).startswith(b"\x89PNG\r\n\x1a\n")


def test_partial_fixture_only_omits_edge_week_cells() -> None:
    calendar = build_synthetic_calendar(partial_weeks=True)

    absent = {(row, col) for row, col in zip(*np.where(~calendar.present), strict=True)}
    assert absent == {(0, 0), (1, 0), (2, 0), (5, 52), (6, 52)}
    assert bool(calendar.present[:, 1:-1].all())


def test_fixture_factory_rejects_out_of_contract_geometry() -> None:
    with pytest.raises(ValueError, match="40..54"):
        build_synthetic_calendar(cols=39)
    with pytest.raises(ValueError, match="positive"):
        build_synthetic_calendar(scale=0)
