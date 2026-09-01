from __future__ import annotations

from io import BytesIO

import cv2
import numpy as np
from PIL import Image

from app.color.ramp import hex_to_rgb
from app.render.calendar import CalendarGeometry, render_calendar
from app.render.glyphs import build_glyph_masks
from app.text.layout import layout_name
from tests.fixtures import build_synthetic_calendar
from tests.helpers import artifact_from_synthetic


def _pixel(image: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    return image.getpixel((x, y))  # type: ignore[return-value]


def test_compositor_preserves_every_cell_interior_by_rule() -> None:
    artifact = artifact_from_synthetic(build_synthetic_calendar())
    layout = layout_name("JOBERNEY", artifact.cols)
    secondary = "#F5A623"
    rendered = render_calendar(
        artifact,
        layout,
        primary="#163951",
        secondary=secondary,
        outline="#0A1620",
        boldness=8,
    )
    levels = {(cell.r, cell.c): cell.level for cell in artifact.cells}

    overlap = empty = letter = 0
    for row in range(7):
        for col in range(artifact.cols):
            x0, y0, x1, y1 = rendered.geometry.cell_box(row, col)
            center = _pixel(rendered.image, (x0 + x1) // 2, (y0 + y1) // 2)
            level = levels[(row, col)]
            glyph = int(layout.letter_id[row, col])
            if glyph == 0:
                expected = hex_to_rgb(artifact.palette[str(level)])
            elif level == 0:
                expected = hex_to_rgb(secondary)
                empty += 1
                letter += 1
            else:
                expected = hex_to_rgb(rendered.primary_ramp[level])
                overlap += 1
                letter += 1
            assert center == expected, (row, col, glyph, level)

    assert rendered.letter_cells == letter
    assert rendered.overlap_cells == overlap
    assert rendered.empty_letter_cells == empty
    assert overlap + empty == letter
    assert rendered.png.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(rendered.png)) as reopened:
        assert reopened.size == rendered.image.size
        assert reopened.mode == "RGB"


def test_outline_shadow_and_rim_do_not_enter_non_letter_inner_80_percent() -> None:
    artifact = artifact_from_synthetic(build_synthetic_calendar())
    layout = layout_name("A", artifact.cols)
    rendered = render_calendar(
        artifact,
        layout,
        primary="#163951",
        secondary="#F5A623",
        outline="#FF00FF",
        boldness=8,
    )
    levels = {(cell.r, cell.c): cell.level for cell in artifact.cells}

    for row in range(7):
        for col in range(artifact.cols):
            if layout.letter_id[row, col] != 0:
                continue
            x0, y0, x1, y1 = rendered.geometry.cell_box(row, col)
            inset = max(1, round(rendered.geometry.cell * 0.10))
            crop = np.asarray(
                rendered.image.crop((x0 + inset, y0 + inset, x1 - inset + 1, y1 - inset + 1))
            )
            expected = np.asarray(hex_to_rgb(artifact.palette[str(levels[(row, col)])]))
            assert np.all(crop == expected), (row, col)


def test_absent_slots_remain_panel_colored() -> None:
    artifact = artifact_from_synthetic(build_synthetic_calendar(partial_weeks=True))
    layout = layout_name(
        "A",
        artifact.cols,
        [
            [
                next(cell.present for cell in artifact.cells if cell.r == row and cell.c == col)
                for col in range(artifact.cols)
            ]
            for row in range(7)
        ],
    )
    rendered = render_calendar(
        artifact,
        layout,
        primary="#163951",
        secondary="#F5A623",
    )

    for cell in artifact.cells:
        if cell.present:
            continue
        x0, y0, x1, y1 = rendered.geometry.cell_box(cell.r, cell.c)
        assert _pixel(rendered.image, (x0 + x1) // 2, (y0 + y1) // 2) == hex_to_rgb(
            artifact.panel_color
        )


def test_each_letter_union_is_connected_and_boldness_increases_outline_area() -> None:
    artifact = artifact_from_synthetic(build_synthetic_calendar())
    layout = layout_name("AB", artifact.cols)
    present = np.ones((7, artifact.cols), dtype=bool)
    geometry = CalendarGeometry(cols=artifact.cols)

    thin = build_glyph_masks(
        (geometry.width, geometry.height),
        layout.letter_id,
        present,
        geometry.cell_box,
        gutter=geometry.gutter,
        radius=geometry.radius,
        boldness=1,
    )
    thick = build_glyph_masks(
        (geometry.width, geometry.height),
        layout.letter_id,
        present,
        geometry.cell_box,
        gutter=geometry.gutter,
        radius=geometry.radius,
        boldness=8,
    )

    assert len(thin.unions) == len(thick.unions) == 2
    for union in thick.unions:
        component_count, _labels = cv2.connectedComponents((np.asarray(union) > 0).astype(np.uint8))
        assert component_count == 2  # background plus one glyph silhouette
    assert np.count_nonzero(np.asarray(thick.outline)) > np.count_nonzero(np.asarray(thin.outline))


def test_renderer_rejects_layout_that_paints_an_absent_cell() -> None:
    artifact = artifact_from_synthetic(build_synthetic_calendar())
    layout = layout_name("A", artifact.cols)
    first_letter_row, first_letter_col = np.argwhere(layout.letter_id > 0)[0]
    cells = [
        cell.model_copy(update={"present": False})
        if (cell.r, cell.c) == (first_letter_row, first_letter_col)
        else cell
        for cell in artifact.cells
    ]
    invalid_artifact = artifact.model_copy(update={"cells": cells})

    try:
        render_calendar(
            invalid_artifact,
            layout,
            primary="#163951",
            secondary="#F5A623",
        )
    except ValueError as error:
        assert "absent" in str(error)
    else:  # pragma: no cover - assertion reads better than pytest.raises here
        raise AssertionError("renderer painted an absent cell")
