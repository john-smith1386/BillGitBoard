from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import CellRecord, JobArtifact, RenderRequest


def test_render_request_trims_uppercases_and_normalizes_colors() -> None:
    request = RenderRequest(
        job_id="01JABCDEF01234567890123456",
        name="  hello 2u ",
        primary="#abcdef",
        secondary="#123abc",
        outline="#0a1620",
    )

    assert request.name == "HELLO 2U"
    assert request.primary == "#ABCDEF"
    assert request.secondary == "#123ABC"
    assert request.outline == "#0A1620"


def test_render_request_preserves_internal_and_repeated_spaces() -> None:
    request = RenderRequest(
        job_id="01JABCDEF01234567890123456",
        name="  hello   2u  ",
    )

    assert request.name == "HELLO   2U"


def test_render_request_checks_length_after_trimming() -> None:
    request = RenderRequest(
        job_id="01JABCDEF01234567890123456",
        name=f"   {'A' * 24}   ",
    )
    assert request.name == "A" * 24

    with pytest.raises(ValidationError):
        RenderRequest(
            job_id="01JABCDEF01234567890123456",
            name=f"   {'A' * 25}   ",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("boldness", True),
        ("boldness", "2"),
        ("boldness", 2.0),
        ("start", False),
        ("start", "3"),
        ("start", 3.0),
    ],
)
def test_render_request_requires_strict_json_integers(field: str, value: object) -> None:
    payload: dict[str, object] = {
        "job_id": "01JABCDEF01234567890123456",
        "name": "A",
        field: value,
    }

    with pytest.raises(ValidationError):
        RenderRequest.model_validate(payload)


@pytest.mark.parametrize("name", ["", "   ", "A_B", "HELLO!", "CAFÉ", "A\nB"])
def test_render_request_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValidationError):
        RenderRequest(job_id="01JABCDEF01234567890123456", name=name)


@pytest.mark.parametrize("color", ["163951", "#123", "#GG0000", "#12345678"])
def test_render_request_rejects_non_hex_colors(color: str) -> None:
    with pytest.raises(ValidationError):
        RenderRequest(
            job_id="01JABCDEF01234567890123456",
            name="A",
            primary=color,
        )


def test_render_request_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RenderRequest.model_validate(
            {
                "job_id": "01JABCDEF01234567890123456",
                "name": "A",
                "unexpected": True,
            }
        )


def test_job_artifact_normalizes_detected_hex_values() -> None:
    artifact = JobArtifact(
        rows=7,
        cols=1,
        theme="dark",
        levels=2,
        palette={"0": "#161b22", "1": "#39d353"},
        panel_color="#0d1117",
        cells=[
            CellRecord(r=row, c=0, level=row % 2, rgb="#161b22", present=True) for row in range(7)
        ],
    )

    assert artifact.palette == {"0": "#161B22", "1": "#39D353"}
    assert artifact.panel_color == "#0D1117"
    assert artifact.cells[0].rgb == "#161B22"
