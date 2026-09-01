from __future__ import annotations

from app.schemas import CellRecord, JobArtifact
from tests.fixtures import SyntheticCalendar


def artifact_from_synthetic(calendar: SyntheticCalendar) -> JobArtifact:
    """Translate a known fixture grid directly into a persisted artifact."""

    palette = {str(index): color for index, color in enumerate(calendar.palette)}
    cells: list[CellRecord] = []
    for row in range(calendar.rows):
        for col in range(calendar.cols):
            present = bool(calendar.present[row, col])
            level = int(calendar.levels[row, col]) if present else 0
            cells.append(
                CellRecord(
                    r=row,
                    c=col,
                    level=level,
                    rgb=palette[str(level)],
                    present=present,
                )
            )
    return JobArtifact(
        rows=7,
        cols=calendar.cols,
        theme="dark" if calendar.theme == "dark" else "light",
        levels=len(calendar.palette),
        palette=palette,
        panel_color="#0D1117" if calendar.theme == "dark" else "#FFFFFF",
        cells=cells,
    )
