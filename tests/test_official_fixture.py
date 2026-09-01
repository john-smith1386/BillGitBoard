from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from app.vision.pipeline import analyze_image

FIXTURE = Path(__file__).parent / "fixtures" / "official_github_light.png"


def _artifact_arrays(cells: list[object], cols: int) -> tuple[np.ndarray, np.ndarray]:
    levels = np.full((7, cols), -1, dtype=np.int16)
    present = np.zeros((7, cols), dtype=bool)
    for cell in cells:
        levels[cell.r, cell.c] = cell.level  # type: ignore[attr-defined]
        present[cell.r, cell.c] = cell.present  # type: ignore[attr-defined]
    return levels, present


def test_official_github_light_grid_is_stable_across_literal_lanczos_scales() -> None:
    with Image.open(FIXTURE) as opened:
        source = opened.convert("RGB")

    results: list[tuple[np.ndarray, np.ndarray]] = []
    for scale in (0.5, 1.0, 2.0):
        resized = source.resize(
            (round(source.width * scale), round(source.height * scale)),
            Image.Resampling.LANCZOS,
        )
        analyzed = analyze_image(resized)
        artifact = analyzed.artifact
        levels, present = _artifact_arrays(artifact.cells, artifact.cols)

        assert artifact.rows == 7, scale
        assert artifact.cols == 53, scale
        assert artifact.levels == 5, scale
        assert artifact.theme == "light", scale
        assert np.array_equal(present[:, 0], [False] * 6 + [True]), scale
        assert bool(present[:, 1:].all()), scale
        assert not np.any(levels < 0), scale
        results.append((levels, present))

    baseline_levels, baseline_present = results[1]
    for levels, present in results:
        assert np.array_equal(present, baseline_present)
        assert np.array_equal(levels, baseline_levels)
