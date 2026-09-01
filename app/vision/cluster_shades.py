"""Discover and rank contribution colors without assuming a GitHub palette."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import cv2
import numpy as np
from sklearn.cluster import KMeans
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import silhouette_score

from app.color.ramp import rgb_to_hex


@dataclass(frozen=True, slots=True)
class ShadeClusters:
    theme: str
    levels: int
    palette: dict[int, str]
    labels: np.ndarray
    warning: tuple[str, str] | None = None


def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    pixels = np.asarray(rgb, dtype=np.uint8).reshape(-1, 1, 3)
    encoded = cv2.cvtColor(pixels, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float64)
    encoded[:, 0] *= 100.0 / 255.0
    encoded[:, 1:] -= 128.0
    return encoded


def _fit_best_k(lab: np.ndarray, maximum: int) -> tuple[KMeans, np.ndarray]:
    best: tuple[float, int, KMeans, np.ndarray] | None = None
    for clusters in range(2, maximum + 1):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            model = KMeans(n_clusters=clusters, random_state=0, n_init=10)
            labels = model.fit_predict(lab)
        actual = len(np.unique(labels))
        if actual < 2 or actual != clusters:
            continue
        score = float(silhouette_score(lab, labels)) if clusters < len(lab) else -1.0
        # A small deterministic prior favors the conventional empty + four
        # ranks when silhouette scores are effectively tied.
        bias = {2: 0.0, 3: 0.01, 4: 0.025, 5: 0.05, 6: 0.025}.get(clusters, 0.0)
        candidate = (score + bias, clusters, model, labels)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is None:
        # This occurs only when every cell has effectively one color.  Split is
        # impossible; the caller will still expose empty/filled semantics.
        jittered = lab.copy()
        jittered[::2, 0] += 0.01
        model = KMeans(n_clusters=2, random_state=0, n_init=1).fit(jittered)
        return model, model.labels_
    return best[2], best[3]


def cluster_shades(
    colors: np.ndarray | list[tuple[int, int, int]],
    panel_rgb: tuple[int, int, int] | None = None,
) -> ShadeClusters:
    """Cluster RGB cell samples in LAB and assign intensity levels.

    Returned ``labels`` are already remapped to ``0 .. K-1`` in contribution
    order; index zero corresponds to the first input color.
    """

    rgb = np.asarray(colors, dtype=np.uint8).reshape(-1, 3)
    if len(rgb) < 2:
        raise ValueError("at least two present cell colors are required")
    lab = _rgb_to_lab(rgb)
    unique = np.unique(rgb, axis=0)
    maximum = min(6, len(unique), len(rgb) - 1)
    warning: tuple[str, str] | None = None
    if maximum < 2:
        # Preserve API semantics even for a monochrome/very blurry calendar.
        palette_color = rgb_to_hex(tuple(int(value) for value in np.median(rgb, axis=0)))
        return ShadeClusters(
            theme="light" if lab[:, 0].mean() > 55 else "dark",
            levels=2,
            palette={0: palette_color, 1: palette_color},
            labels=np.zeros(len(rgb), dtype=np.int16),
            warning=(
                "NOT_ENOUGH_SHADES",
                "Not enough distinct cell colors to infer shades; using two levels",
            ),
        )

    model, raw_labels = _fit_best_k(lab, maximum)
    cluster_ids = sorted(int(value) for value in np.unique(raw_labels))
    centers = {cluster: model.cluster_centers_[cluster] for cluster in cluster_ids}
    counts = {cluster: int(np.count_nonzero(raw_labels == cluster)) for cluster in cluster_ids}

    if panel_rgb is not None:
        panel_lab = _rgb_to_lab(np.asarray([panel_rgb], dtype=np.uint8))[0]
        empty_cluster = min(
            cluster_ids,
            key=lambda cluster: float(np.linalg.norm(centers[cluster] - panel_lab)),
        )
    else:
        max_count = max(counts.values())
        # Low chroma and frequency are both robust empty-cell signals.
        empty_cluster = min(
            cluster_ids,
            key=lambda cluster: (
                float(np.linalg.norm(centers[cluster][1:]))
                + 12.0 * (1.0 - counts[cluster] / max_count)
            ),
        )

    theme = "light" if centers[empty_cluster][0] > 55 else "dark"
    non_empty = [cluster for cluster in cluster_ids if cluster != empty_cluster]
    # Light calendars become darker with intensity; dark calendars become
    # brighter.  Sorting in these directions assigns level 1 to the weakest.
    non_empty.sort(
        key=lambda cluster: float(centers[cluster][0]),
        reverse=(theme == "light"),
    )
    ordered = [empty_cluster, *non_empty]
    mapping = {cluster: level for level, cluster in enumerate(ordered)}
    labels = np.asarray([mapping[int(cluster)] for cluster in raw_labels], dtype=np.int16)

    palette: dict[int, str] = {}
    for level, cluster in enumerate(ordered):
        members = rgb[raw_labels == cluster]
        centroid_rgb = tuple(round(value) for value in np.mean(members, axis=0))
        palette[level] = rgb_to_hex(centroid_rgb)

    if len(ordered) < 3:
        warning = (
            "NOT_ENOUGH_SHADES",
            "Not enough distinct cell colors to infer shades; using two levels",
        )
    luminance_range = float(np.ptp([centers[cluster][0] for cluster in ordered]))
    if luminance_range < 6 and warning is None:
        warning = (
            "BLURRY",
            "Cell contrast is low; use a less compressed screenshot if detection looks wrong",
        )
    return ShadeClusters(
        theme=theme,
        levels=len(ordered),
        palette=palette,
        labels=labels,
        warning=warning,
    )
