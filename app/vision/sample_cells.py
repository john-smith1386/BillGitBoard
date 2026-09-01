"""Robust inner-cell color sampling."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .find_grid import GridDetection


@dataclass(frozen=True, slots=True)
class SampledCell:
    r: int
    c: int
    rgb: tuple[int, int, int]
    present: bool


@dataclass(frozen=True, slots=True)
class CellSamples:
    cells: tuple[SampledCell, ...]
    panel_rgb: tuple[int, int, int]


def _median_rgb(pixels: np.ndarray) -> tuple[int, int, int]:
    values = np.median(pixels.reshape(-1, 3), axis=0)
    return tuple(round(channel) for channel in values)  # type: ignore[return-value]


def sample_cells(rgb: np.ndarray, grid: GridDetection) -> CellSamples:
    """Sample the inner 60% of each present cell using channel medians."""

    height, width = rgb.shape[:2]
    half_width = max(1, round(grid.cell_width * 0.30))
    half_height = max(1, round(grid.cell_height * 0.30))
    cells: list[SampledCell] = []
    for row in range(7):
        for col in range(grid.cols):
            center_x, center_y = grid.centers[row, col]
            x0 = max(0, round(center_x) - half_width)
            x1 = min(width, round(center_x) + half_width + 1)
            y0 = max(0, round(center_y) - half_height)
            y1 = min(height, round(center_y) + half_height + 1)
            sampled = rgb[y0:y1, x0:x1]
            color = _median_rgb(sampled) if sampled.size else (0, 0, 0)
            cells.append(
                SampledCell(
                    r=row,
                    c=col,
                    rgb=color,
                    present=bool(grid.present[row, col]),
                )
            )

    # The gaps inside the lattice are a reliable panel-background sample and
    # work for both light and dark themes.  Exclude a slightly enlarged cell
    # square from that region before taking the median.
    grid_x0 = max(0, int(grid.origin_x - grid.pitch_x / 2))
    grid_y0 = max(0, int(grid.origin_y - grid.pitch_y / 2))
    grid_x1 = min(width, int(grid.origin_x + (grid.cols - 1) * grid.pitch_x + grid.pitch_x / 2))
    grid_y1 = min(height, int(grid.origin_y + 6 * grid.pitch_y + grid.pitch_y / 2))
    region = rgb[grid_y0:grid_y1, grid_x0:grid_x1]
    keep = np.ones(region.shape[:2], dtype=bool)
    protect_x = max(1, round(grid.cell_width / 2) + 1)
    protect_y = max(1, round(grid.cell_height / 2) + 1)
    for row in range(7):
        for col in range(grid.cols):
            center_x, center_y = grid.centers[row, col]
            local_x = round(center_x) - grid_x0
            local_y = round(center_y) - grid_y0
            keep[
                max(0, local_y - protect_y) : min(keep.shape[0], local_y + protect_y + 1),
                max(0, local_x - protect_x) : min(keep.shape[1], local_x + protect_x + 1),
            ] = False
    panel_pixels = region[keep]
    if not panel_pixels.size:
        panel_rgb = _median_rgb(rgb)
    else:
        panel_rgb = _median_rgb(panel_pixels)
    return CellSamples(cells=tuple(cells), panel_rgb=panel_rgb)
