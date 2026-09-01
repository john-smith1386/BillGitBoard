"""End-to-end image analysis orchestration."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

from app.color.ramp import rgb_to_hex
from app.schemas import CellRecord, DetectionWarning, JobArtifact

from .cluster_shades import cluster_shades
from .find_grid import GridDetection, find_grid
from .preprocess import PreprocessedImage, encode_png, preprocess_image
from .sample_cells import sample_cells


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    artifact: JobArtifact
    source_png: bytes
    overlay_png: bytes
    preprocessing: PreprocessedImage
    grid: GridDetection


def _make_overlay(rgb: np.ndarray, grid: GridDetection) -> bytes:
    image = Image.fromarray(rgb, mode="RGB")
    draw = ImageDraw.Draw(image, mode="RGB")
    half_width = grid.cell_width / 2
    half_height = grid.cell_height / 2
    line_width = max(1, round(min(grid.cell_width, grid.cell_height) / 10))
    for row in range(7):
        for col in range(grid.cols):
            center_x, center_y = grid.centers[row, col]
            box = (
                round(center_x - half_width),
                round(center_y - half_height),
                round(center_x + half_width),
                round(center_y + half_height),
            )
            color = "#0969DA" if grid.present[row, col] else "#CF222E"
            draw.rectangle(box, outline=color, width=line_width)
    return encode_png(image)


def analyze_image(image: Image.Image) -> AnalysisResult:
    preprocessed = preprocess_image(image)
    grid = find_grid(preprocessed.filtered_rgb)
    samples = sample_cells(preprocessed.filtered_rgb, grid)
    present_cells = [cell for cell in samples.cells if cell.present]
    colors = np.asarray([cell.rgb for cell in present_cells], dtype=np.uint8)
    clustered = cluster_shades(colors, samples.panel_rgb)

    assigned: dict[tuple[int, int], int] = {}
    for cell, level in zip(present_cells, clustered.labels, strict=True):
        assigned[(cell.r, cell.c)] = int(level)

    records: list[CellRecord] = []
    for cell in samples.cells:
        level = assigned.get((cell.r, cell.c), 0)
        records.append(
            CellRecord(
                r=cell.r,
                c=cell.c,
                level=level,
                # Preserve the actual per-cell median for support/debugging.
                # Rendering uses only ``level`` plus the detected palette.
                rgb=rgb_to_hex(cell.rgb),
                present=cell.present,
            )
        )

    warnings = [DetectionWarning(code=code, detail=detail) for code, detail in grid.warnings]
    if clustered.warning:
        warnings.append(DetectionWarning(code=clustered.warning[0], detail=clustered.warning[1]))
    artifact = JobArtifact(
        rows=7,
        cols=grid.cols,
        theme=clustered.theme,
        levels=clustered.levels,
        palette={str(level): color for level, color in clustered.palette.items()},
        panel_color=rgb_to_hex(samples.panel_rgb),
        cells=records,
        warnings=warnings,
    )
    return AnalysisResult(
        artifact=artifact,
        source_png=encode_png(preprocessed.rgb),
        overlay_png=_make_overlay(preprocessed.rgb, grid),
        preprocessing=preprocessed,
        grid=grid,
    )
