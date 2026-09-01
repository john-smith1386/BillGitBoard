from __future__ import annotations

import math
import time

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.color.ramp import rgb_to_hex
from app.errors import ServiceError
from app.vision.find_grid import SquareBlob, _deduplicate, find_grid
from app.vision.pipeline import AnalysisResult, analyze_image
from app.vision.preprocess import preprocess_image
from app.vision.sample_cells import sample_cells
from tests.fixtures import PALETTES, build_synthetic_calendar


def _artifact_arrays(result: AnalysisResult) -> tuple[np.ndarray, np.ndarray]:
    levels = np.zeros((7, result.artifact.cols), dtype=np.int16)
    present = np.zeros((7, result.artifact.cols), dtype=bool)
    for cell in result.artifact.cells:
        levels[cell.r, cell.c] = cell.level
        present[cell.r, cell.c] = cell.present
    return levels, present


def test_grid_and_levels_are_exactly_scale_invariant() -> None:
    results: list[tuple[np.ndarray, np.ndarray, AnalysisResult]] = []
    for scale in (0.5, 1.0, 2.0):
        calendar = build_synthetic_calendar(theme="light", scale=scale)
        analyzed = analyze_image(calendar.image)
        levels, present = _artifact_arrays(analyzed)
        results.append((levels, present, analyzed))

        assert analyzed.artifact.rows == 7
        assert analyzed.artifact.cols == calendar.cols == 53
        assert analyzed.artifact.levels == 5
        assert np.array_equal(levels, calendar.levels)
        assert np.array_equal(present, calendar.present)
        assert analyzed.grid.mean_snap_error <= 0.25

    baseline_levels, baseline_present, baseline = results[0]
    for levels, present, analyzed in results[1:]:
        assert np.array_equal(levels, baseline_levels)
        assert np.array_equal(present, baseline_present)
        assert analyzed.artifact.palette == baseline.artifact.palette


def test_literal_lanczos_resize_preserves_grid_presence_and_cell_ranks() -> None:
    calendar = build_synthetic_calendar(theme="light", scale=1.0)
    resized = calendar.image.resize(
        (calendar.image.width // 2, calendar.image.height // 2),
        Image.Resampling.LANCZOS,
    )

    analyzed = analyze_image(resized)
    levels, present = _artifact_arrays(analyzed)

    assert analyzed.artifact.rows == 7
    assert analyzed.artifact.cols == 53
    assert int(np.count_nonzero(~present)) == 0
    assert np.array_equal(present, calendar.present)
    assert np.array_equal(levels, calendar.levels)


@pytest.mark.parametrize(
    ("fixture_theme", "detected_theme"),
    [("dark", "dark"), ("halloween", "light")],
)
def test_pipeline_learns_dark_and_non_green_palettes(
    fixture_theme: str, detected_theme: str
) -> None:
    calendar = build_synthetic_calendar(theme=fixture_theme)  # type: ignore[arg-type]

    analyzed = analyze_image(calendar.image)
    levels, present = _artifact_arrays(analyzed)

    assert analyzed.artifact.theme == detected_theme
    assert analyzed.artifact.palette == {
        str(index): color.upper() for index, color in enumerate(PALETTES[fixture_theme])
    }
    assert np.array_equal(levels, calendar.levels)
    assert np.array_equal(present, calendar.present)


def test_partial_edge_weeks_are_recorded_as_absent_without_inventing_cells() -> None:
    calendar = build_synthetic_calendar(partial_weeks=True)

    analyzed = analyze_image(calendar.image)
    levels, present = _artifact_arrays(analyzed)

    assert analyzed.artifact.cols == calendar.cols
    assert len(analyzed.artifact.cells) == 7 * calendar.cols
    assert np.array_equal(present, calendar.present)
    assert np.array_equal(levels[present], calendar.levels[present])
    assert int(np.count_nonzero(~present)) == 5
    assert all(cell.level == 0 for cell in analyzed.artifact.cells if not cell.present)
    assert analyzed.source_png.startswith(b"\x89PNG")
    assert analyzed.overlay_png.startswith(b"\x89PNG")


@pytest.mark.parametrize("cols", [39, 55, 60])
def test_out_of_contract_lattice_extent_is_rejected_without_cropping(cols: int) -> None:
    calendar = build_synthetic_calendar(
        cols=cols,
        add_legend=False,
        allow_unsupported_cols=True,
    )

    with pytest.raises(ServiceError) as exc_info:
        analyze_image(calendar.image)

    assert exc_info.value.code == "GRID_UNRELIABLE"
    assert exc_info.value.extra == {"cols": cols, "min_cols": 40, "max_cols": 54}


def test_grid_dump_preserves_each_measured_median_not_cluster_centroids() -> None:
    calendar = build_synthetic_calendar()
    # Introduce a subtle, still-empty-shade variant into one flat cell so its
    # median is intentionally different from the cluster's shared centroid.
    x0, y0, x1, y1 = calendar.boxes[(0, 0)]
    ImageDraw.Draw(calendar.image).rectangle(
        (x0 + 3, y0 + 3, x1 - 3, y1 - 3),
        fill=(228, 232, 237),
    )

    preprocessing = preprocess_image(calendar.image)
    detected = find_grid(preprocessing.filtered_rgb)
    sampled = sample_cells(preprocessing.filtered_rgb, detected)
    analyzed = analyze_image(calendar.image)

    expected = {(cell.r, cell.c): rgb_to_hex(cell.rgb) for cell in sampled.cells}
    assert all(cell.rgb == expected[(cell.r, cell.c)] for cell in analyzed.artifact.cells)
    varied = next(cell for cell in analyzed.artifact.cells if (cell.r, cell.c) == (0, 0))
    assert varied.rgb != analyzed.artifact.palette[str(varied.level)]


def _naive_deduplicate(blobs: list[SquareBlob], scale: float) -> list[SquareBlob]:
    """The original all-pairs scan, kept as the behavioural reference."""

    radius = max(1.25, scale * 0.28)
    selected: list[SquareBlob] = []
    for blob in sorted(blobs, key=lambda item: item.quality, reverse=True):
        if any(math.hypot(blob.x - other.x, blob.y - other.y) <= radius for other in selected):
            continue
        selected.append(blob)
    return selected


def test_blob_deduplication_matches_the_all_pairs_scan() -> None:
    """Bucketing must not change which blob wins a neighbourhood."""

    rng = np.random.default_rng(20260901)
    blobs = [
        SquareBlob(
            x=float(x),
            y=float(y),
            width=4.0,
            height=4.0,
            quality=float(q),
        )
        for x, y, q in zip(
            rng.uniform(0, 60, 900),
            rng.uniform(0, 60, 900),
            rng.uniform(0, 1, 900),
            strict=True,
        )
    ]
    for scale in (1.0, 3.0, 7.5):
        assert _deduplicate(blobs, scale) == _naive_deduplicate(blobs, scale)


def test_dense_blob_field_deduplicates_in_bounded_time() -> None:
    """A dense field of small squares must not cost quadratic work.

    A few hundred bytes of PNG can decode into tens of thousands of square
    components. The all-pairs scan took tens of seconds on that input and held
    the single analyze slot for the whole time, so this guards the bound rather
    than the output.
    """

    rng = np.random.default_rng(7)
    blobs = [
        SquareBlob(x=float(x), y=float(y), width=3.0, height=3.0, quality=float(q))
        for x, y, q in zip(
            rng.uniform(0, 1200, 20000),
            rng.uniform(0, 1200, 20000),
            rng.uniform(0, 1, 20000),
            strict=True,
        )
    ]
    started = time.perf_counter()
    _deduplicate(blobs, 3.0)
    assert time.perf_counter() - started < 2.0
