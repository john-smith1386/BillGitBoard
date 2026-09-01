from __future__ import annotations

import time

import pytest

from app.schemas import CellRecord, JobArtifact
from tests.fixtures import SyntheticCalendar, build_synthetic_calendar


@pytest.fixture
def light_calendar() -> SyntheticCalendar:
    return build_synthetic_calendar(theme="light")


@pytest.fixture
def dark_calendar() -> SyntheticCalendar:
    return build_synthetic_calendar(theme="dark")


@pytest.fixture
def halloween_calendar() -> SyntheticCalendar:
    return build_synthetic_calendar(theme="halloween")


@pytest.fixture
def partial_calendar() -> SyntheticCalendar:
    return build_synthetic_calendar(theme="light", partial_weeks=True)


@pytest.fixture
def small_job_artifact() -> JobArtifact:
    palette = {
        "0": "#EBEDF0",
        "1": "#9BE9A8",
        "2": "#40C463",
        "3": "#30A14E",
        "4": "#216E39",
    }
    cells = [
        CellRecord(
            r=row,
            c=col,
            level=(row + col) % len(palette),
            rgb=palette[str((row + col) % len(palette))],
            present=True,
        )
        for row in range(7)
        for col in range(8)
    ]
    return JobArtifact(
        created_at=time.time(),
        rows=7,
        cols=8,
        theme="light",
        levels=5,
        palette=palette,
        panel_color="#FFFFFF",
        cells=cells,
    )
