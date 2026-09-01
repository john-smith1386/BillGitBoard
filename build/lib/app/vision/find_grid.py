"""Detect a 7-row contribution lattice from repeated square blobs."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise

import cv2
import numpy as np

from app.errors import ServiceError


@dataclass(frozen=True, slots=True)
class SquareBlob:
    x: float
    y: float
    width: float
    height: float
    quality: float = 1.0

    @property
    def side(self) -> float:
        return (self.width + self.height) / 2.0


@dataclass(frozen=True, slots=True)
class GridDetection:
    rows: int
    cols: int
    centers: np.ndarray
    present: np.ndarray
    cell_width: float
    cell_height: float
    pitch_x: float
    pitch_y: float
    origin_x: float
    origin_y: float
    mean_snap_error: float
    blobs_found: int
    warnings: tuple[tuple[str, str], ...] = ()


def _valid_component(
    x: int,
    y: int,
    width: int,
    height: int,
    area: float,
    image_shape: tuple[int, int],
) -> bool:
    del x, y
    image_height, image_width = image_shape
    if width < 3 or height < 3:
        return False
    if width > min(160, image_width * 0.16) or height > min(160, image_height * 0.35):
        return False
    ratio = width / height
    if ratio < 0.72 or ratio > 1.28:
        return False
    fill = float(area) / max(1.0, width * height)
    return 0.24 <= fill <= 1.12


def _components_from_quantized(rgb: np.ndarray) -> list[SquareBlob]:
    height, width = rgb.shape[:2]
    blobs: list[SquareBlob] = []
    for quantum in (8, 16):
        # Pack quantized RGB into uint16 in place.  The previous HxWx3 int32
        # temporary cost ~69 MB at the 2400-square working bound.
        identifiers = rgb[:, :, 0].astype(np.uint16)
        identifiers //= quantum
        identifiers <<= 11
        channel = rgb[:, :, 1].astype(np.uint16)
        channel //= quantum
        channel <<= 6
        identifiers |= channel
        channel = rgb[:, :, 2].astype(np.uint16)
        channel //= quantum
        identifiers |= channel
        del channel
        values, counts = np.unique(identifiers, return_counts=True)
        # Calendar shades and panel colors dominate.  A generous cap still
        # bounds work on noisy JPEGs.
        order = np.argsort(counts)[::-1][:32]
        for value in values[order]:
            mask = cv2.compare(identifiers, int(value), cv2.CMP_EQ)
            count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
            for index in range(1, count):
                x, y, component_width, component_height, area = stats[index]
                if not _valid_component(
                    int(x),
                    int(y),
                    int(component_width),
                    int(component_height),
                    int(area),
                    (height, width),
                ):
                    continue
                center_x, center_y = centroids[index]
                fill = area / max(1, component_width * component_height)
                blobs.append(
                    SquareBlob(
                        float(center_x),
                        float(center_y),
                        float(component_width),
                        float(component_height),
                        quality=float(fill + 0.5),
                    )
                )
    return blobs


def _components_from_edges(rgb: np.ndarray) -> list[SquareBlob]:
    height, width = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    edge_mask = np.zeros_like(gray)
    for channel in (gray, lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]):
        edge_mask |= cv2.Canny(channel, 4, 24, apertureSize=3, L2gradient=True)
    edge_mask = cv2.morphologyEx(
        edge_mask,
        cv2.MORPH_CLOSE,
        np.ones((3, 3), dtype=np.uint8),
    )

    masks = [edge_mask]
    block = max(15, min(51, (min(height, width) // 12) | 1))
    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        block,
        3,
    )
    masks.extend((adaptive, cv2.bitwise_not(adaptive)))

    blobs: list[SquareBlob] = []
    for mask in masks:
        contours, _hierarchy = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, component_width, component_height = cv2.boundingRect(contour)
            area = abs(cv2.contourArea(contour))
            if not _valid_component(
                x,
                y,
                component_width,
                component_height,
                area,
                (height, width),
            ):
                continue
            blobs.append(
                SquareBlob(
                    x + (component_width - 1) / 2,
                    y + (component_height - 1) / 2,
                    float(component_width),
                    float(component_height),
                    quality=float(area / max(1, component_width * component_height)),
                )
            )
    return blobs


def detect_square_blobs(rgb: np.ndarray) -> list[SquareBlob]:
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("rgb must be an H x W x 3 array")
    return _components_from_quantized(rgb) + _components_from_edges(rgb)


def _deduplicate(blobs: Iterable[SquareBlob], scale: float) -> list[SquareBlob]:
    radius = max(1.25, scale * 0.28)
    selected: list[SquareBlob] = []
    for blob in sorted(blobs, key=lambda item: item.quality, reverse=True):
        if any(math.hypot(blob.x - other.x, blob.y - other.y) <= radius for other in selected):
            continue
        selected.append(blob)
    return selected


def _cluster_axis(
    values: list[tuple[float, SquareBlob]], tolerance: float
) -> list[tuple[float, list[SquareBlob]]]:
    groups: list[list[SquareBlob]] = []
    for value, blob in sorted(values, key=lambda item: item[0]):
        if not groups:
            groups.append([blob])
            continue
        previous_center = float(np.median([member.y for member in groups[-1]]))
        if value - previous_center <= tolerance:
            groups[-1].append(blob)
        else:
            groups.append([blob])
    return [(float(np.median([blob.y for blob in group])), group) for group in groups]


def _choose_seven_bands(
    bands: list[tuple[float, list[SquareBlob]]],
    scale: float,
) -> tuple[list[tuple[float, list[SquareBlob]]], float] | None:
    if len(bands) < 7:
        return None
    best: tuple[float, list[tuple[float, list[SquareBlob]]], float] | None = None
    for first_index, (first_y, _first_members) in enumerate(bands):
        for second_index in range(first_index + 1, len(bands)):
            pitch = bands[second_index][0] - first_y
            if pitch < scale * 0.78 or pitch > scale * 2.2:
                continue
            selected: list[tuple[float, list[SquareBlob]]] = []
            total_error = 0.0
            used: set[int] = set()
            for row in range(7):
                target = first_y + row * pitch
                nearest_index = min(
                    range(len(bands)),
                    key=lambda index: abs(bands[index][0] - target),
                )
                error = abs(bands[nearest_index][0] - target)
                if nearest_index in used or error > max(1.5, pitch * 0.22):
                    selected = []
                    break
                used.add(nearest_index)
                selected.append(bands[nearest_index])
                total_error += error
            if len(selected) != 7:
                continue
            points = sum(len(members) for _center, members in selected)
            minimum_row = min(len(members) for _center, members in selected)
            score = points + minimum_row * 2 - total_error * 4
            if best is None or score > best[0]:
                fitted_pitch = float(np.median(np.diff([center for center, _ in selected])))
                best = (score, selected, fitted_pitch)
    if best is None:
        return None
    return best[1], best[2]


def _horizontal_pitch(rows: list[list[SquareBlob]], scale: float, pitch_y: float) -> float:
    differences: list[float] = []
    for members in rows:
        xs = sorted(blob.x for blob in members)
        differences.extend(right - left for left, right in pairwise(xs))
    plausible = [
        difference
        for difference in differences
        if max(scale * 0.72, pitch_y * 0.7) <= difference <= min(scale * 1.8, pitch_y * 1.3)
    ]
    if not plausible:
        return pitch_y
    # Deltas are nearly integer-valued in screenshots; using the strongest
    # quarter-pixel bin avoids false contours between two real cells.
    bins = Counter(round(value * 4) for value in plausible)
    peak, _count = max(
        bins.items(),
        key=lambda item: (item[1], -abs(item[0] / 4 - pitch_y)),
    )
    neighborhood = [value for value in plausible if abs(value - peak / 4) <= 0.5]
    return float(np.median(neighborhood))


def _choose_phase(points: list[SquareBlob], pitch: float) -> float:
    best_phase = points[0].x % pitch
    best_score = -1.0
    for candidate in points:
        phase = candidate.x % pitch
        errors = [abs(((point.x - phase + pitch / 2) % pitch) - pitch / 2) for point in points]
        inliers = [error for error in errors if error <= pitch * 0.25]
        score = len(inliers) - sum(inliers) / max(1.0, pitch)
        if score > best_score:
            best_score = score
            best_phase = phase
    return best_phase


def _select_column_extent(
    snapped: list[tuple[int, int, SquareBlob, float]],
) -> tuple[int, int] | None:
    """Return the complete dominant contiguous lattice, without v1 cropping."""

    support: dict[int, set[int]] = defaultdict(set)
    quality: dict[int, float] = defaultdict(float)
    for row, raw_col, blob, _error in snapped:
        support[raw_col].add(row)
        quality[raw_col] = max(quality[raw_col], blob.quality)
    core = sorted(column for column, rows in support.items() if len(rows) >= 2)
    if not core:
        return None

    groups: list[list[int]] = [[core[0]]]
    for column in core[1:]:
        # One completely missed low-contrast column is recovered later from
        # pixels, but bridge that gap only between strongly supported columns.
        previous = groups[-1][-1]
        gap = column - previous
        if gap == 1 or (gap == 2 and len(support[previous]) >= 4 and len(support[column]) >= 4):
            groups[-1].append(column)
        else:
            groups.append([column])

    candidates: list[tuple[float, int, int]] = []
    for group in groups:
        start, end = group[0], group[-1]
        # A partial first/last week can have only one confirmed square. Include
        # such a boundary when it is directly adjacent to the strong run.
        # Extend by at most one week on either side. A real GitHub boundary
        # week may contain a single high-quality cell, but allowing repeated
        # extension lets aligned day-label/text contours become extra weeks.
        if support.get(start - 1) and (len(support[start - 1]) >= 2 or quality[start - 1] >= 1.0):
            start -= 1
        if support.get(end + 1) and (len(support[end + 1]) >= 2 or quality[end + 1] >= 1.0):
            end += 1
        length = end - start + 1
        if not 20 <= length <= 200:
            continue
        points = sum(len(support.get(column, ())) for column in range(start, end + 1))
        missing = sum(not support.get(column) for column in range(start, end + 1))
        candidates.append((points - missing * 8, start, length))
    if not candidates:
        return None
    _score, start, length = max(candidates)
    return start, length


def _estimate_panel_rgb(
    rgb: np.ndarray,
    *,
    origin_x: float,
    origin_y: float,
    cols: int,
    pitch_x: float,
    pitch_y: float,
    cell_width: float,
    cell_height: float,
) -> np.ndarray:
    """Estimate panel color from strips immediately outside the lattice."""

    height, width = rgb.shape[:2]
    grid_right = origin_x + (cols - 1) * pitch_x
    grid_bottom = origin_y + 6 * pitch_y
    regions: list[np.ndarray] = []
    boxes = (
        (
            max(0, round(origin_x - pitch_x * 1.5)),
            max(0, round(origin_y - cell_height / 2)),
            max(0, round(origin_x - cell_width / 2 - 1)),
            min(height, round(grid_bottom + cell_height / 2 + 1)),
        ),
        (
            min(width, round(grid_right + cell_width / 2 + 1)),
            max(0, round(origin_y - cell_height / 2)),
            min(width, round(grid_right + pitch_x * 1.5)),
            min(height, round(grid_bottom + cell_height / 2 + 1)),
        ),
        (
            max(0, round(origin_x - cell_width / 2)),
            max(0, round(origin_y - pitch_y * 1.4)),
            min(width, round(grid_right + cell_width / 2 + 1)),
            max(0, round(origin_y - cell_height / 2 - 1)),
        ),
        (
            max(0, round(origin_x - cell_width / 2)),
            min(height, round(grid_bottom + cell_height / 2 + 1)),
            min(width, round(grid_right + cell_width / 2 + 1)),
            min(height, round(grid_bottom + pitch_y * 1.4)),
        ),
    )
    for x0, y0, x1, y1 in boxes:
        if x1 > x0 and y1 > y0:
            regions.append(rgb[y0:y1, x0:x1].reshape(-1, 3))
    if not regions:
        return np.median(rgb.reshape(-1, 3), axis=0)
    return np.median(np.concatenate(regions, axis=0), axis=0)


def _recover_low_contrast_cells(
    rgb: np.ndarray,
    centers: np.ndarray,
    present: np.ndarray,
    *,
    panel_rgb: np.ndarray,
    cell_width: float,
    cell_height: float,
) -> None:
    """Recover real cells whose subtle border produced no contour.

    Empty GitHub cells can become almost edge-free after an arbitrary
    downscale.  Their inner pixels still differ from the panel, while a truly
    absent first/last-week slot samples the panel itself.
    """

    height, width = rgb.shape[:2]
    half_width = max(1, round(cell_width * 0.22))
    half_height = max(1, round(cell_height * 0.22))
    for row, col in zip(*np.nonzero(~present), strict=True):
        center_x, center_y = centers[row, col]
        x0 = max(0, round(center_x) - half_width)
        x1 = min(width, round(center_x) + half_width + 1)
        y0 = max(0, round(center_y) - half_height)
        y1 = min(height, round(center_y) + half_height + 1)
        patch = rgb[y0:y1, x0:x1]
        if not patch.size:
            continue
        center_rgb = np.median(patch.reshape(-1, 3), axis=0)
        if float(np.linalg.norm(center_rgb - panel_rgb)) >= 5.0:
            present[row, col] = True


def _fit_scale(blobs: list[SquareBlob], scale: float, rgb: np.ndarray) -> GridDetection | None:
    matching = [blob for blob in blobs if scale * 0.68 <= blob.side <= scale * 1.36]
    points = _deduplicate(matching, scale)
    if len(points) < 200:
        return None

    bands = _cluster_axis([(blob.y, blob) for blob in points], max(1.25, scale * 0.28))
    selected = _choose_seven_bands(bands, scale)
    if selected is None:
        return None
    chosen_bands, pitch_y = selected
    row_tolerance = max(1.5, pitch_y * 0.22)
    rows: list[list[SquareBlob]] = []
    for center, members in chosen_bands:
        rows.append([blob for blob in members if abs(blob.y - center) <= row_tolerance])

    pitch_x = _horizontal_pitch(rows, scale, pitch_y)
    if pitch_x <= 0:
        return None
    all_points = [blob for row in rows for blob in row]
    phase = _choose_phase(all_points, pitch_x)
    snapped: list[tuple[int, int, SquareBlob, float]] = []
    row_centers = [center for center, _members in chosen_bands]
    for row, members in enumerate(rows):
        for blob in members:
            raw_col = round((blob.x - phase) / pitch_x)
            predicted_x = phase + raw_col * pitch_x
            x_error = abs(blob.x - predicted_x) / pitch_x
            y_error = abs(blob.y - row_centers[row]) / pitch_y
            error = math.hypot(x_error, y_error)
            if x_error <= 0.25 and y_error <= 0.25:
                snapped.append((row, raw_col, blob, error))

    extent = _select_column_extent(snapped)
    if extent is None:
        return None
    first_col, cols = extent
    selected_points = [item for item in snapped if first_col <= item[1] < first_col + cols]
    if len(selected_points) < 200:
        return None

    centers = np.zeros((7, cols, 2), dtype=np.float64)
    present = np.zeros((7, cols), dtype=bool)
    best_by_slot: dict[tuple[int, int], tuple[SquareBlob, float]] = {}
    for row, raw_col, blob, error in selected_points:
        slot = (row, raw_col - first_col)
        if slot not in best_by_slot or error < best_by_slot[slot][1]:
            best_by_slot[slot] = (blob, error)

    origin_x = phase + first_col * pitch_x
    origin_y = row_centers[0]
    for row in range(7):
        for col in range(cols):
            centers[row, col] = (origin_x + col * pitch_x, origin_y + row * pitch_y)
            if (row, col) in best_by_slot:
                present[row, col] = True

    errors = [error for _blob, error in best_by_slot.values()]
    mean_error = float(np.mean(errors)) if errors else math.inf
    if mean_error > 0.25:
        return None

    used_blobs = [blob for blob, _error in best_by_slot.values()]
    cell_width = float(np.median([blob.width for blob in used_blobs]))
    cell_height = float(np.median([blob.height for blob in used_blobs]))
    panel_rgb = _estimate_panel_rgb(
        rgb,
        origin_x=origin_x,
        origin_y=origin_y,
        cols=cols,
        pitch_x=pitch_x,
        pitch_y=pitch_y,
        cell_width=cell_width,
        cell_height=cell_height,
    )
    _recover_low_contrast_cells(
        rgb,
        centers,
        present,
        panel_rgb=panel_rgb,
        cell_width=cell_width,
        cell_height=cell_height,
    )
    interior = present[:, 1:-1] if cols > 2 else present
    interior_holes = int(interior.size - np.count_nonzero(interior))
    warnings: list[tuple[str, str]] = []
    if interior.size and interior_holes / interior.size > 0.08:
        warnings.append(
            (
                "PARTIAL_GRID",
                "More than 8% of interior lattice positions could not be confirmed",
            )
        )
    return GridDetection(
        rows=7,
        cols=cols,
        centers=centers,
        present=present,
        cell_width=cell_width,
        cell_height=cell_height,
        pitch_x=pitch_x,
        pitch_y=pitch_y,
        origin_x=origin_x,
        origin_y=origin_y,
        mean_snap_error=mean_error,
        blobs_found=len(best_by_slot),
        warnings=tuple(warnings),
    )


def find_grid(rgb: np.ndarray) -> GridDetection:
    """Find the strongest 7 x C lattice, where ``40 <= C <= 54``."""

    blobs = detect_square_blobs(rgb)
    if len(blobs) < 200:
        raise ServiceError(
            "NO_GRID",
            "Could not find a 7-row contribution grid. Crop closer to the calendar.",
        )

    side_counts = Counter(round(blob.side) for blob in blobs)
    candidate_scales = [
        float(side)
        for side, _count in sorted(side_counts.items(), key=lambda item: item[1], reverse=True)
        if side >= 3
    ][:12]
    fits = [fit for scale in candidate_scales if (fit := _fit_scale(blobs, scale, rgb)) is not None]
    if not fits:
        raise ServiceError(
            "NOT_SEVEN_ROWS",
            "Could not lock the detected cells to a reliable 7-row lattice",
        )
    best = max(
        fits,
        key=lambda fit: (fit.blobs_found - fit.mean_snap_error * 25, fit.cols),
    )
    if not 40 <= best.cols <= 54:
        raise ServiceError(
            "GRID_UNRELIABLE",
            "Detected grid column count is outside the supported 40 to 54 range",
            cols=best.cols,
            min_cols=40,
            max_cols=54,
        )
    return best
