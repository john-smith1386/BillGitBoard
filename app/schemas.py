"""Pydantic request, response, and persisted-artifact schemas."""

from __future__ import annotations

import re
import time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
NAME_PATTERN = re.compile(r"^[A-Z0-9 ]+$")
HexColor = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DetectionWarning(StrictModel):
    code: str
    detail: str


class CellRecord(StrictModel):
    r: int = Field(ge=0, le=6)
    c: int = Field(ge=0)
    level: int = Field(ge=0)
    rgb: HexColor
    present: bool

    @field_validator("rgb")
    @classmethod
    def normalize_rgb(cls, value: str) -> str:
        return value.upper()


class JobArtifact(StrictModel):
    version: int = 1
    created_at: float = Field(default_factory=time.time)
    rows: Literal[7] = 7
    cols: int = Field(ge=1)
    theme: Literal["light", "dark"]
    levels: int = Field(ge=2, le=6)
    palette: dict[str, HexColor]
    panel_color: HexColor
    cells: list[CellRecord]
    warnings: list[DetectionWarning] = Field(default_factory=list)

    @field_validator("palette")
    @classmethod
    def normalize_palette(cls, value: dict[str, str]) -> dict[str, str]:
        return {str(key): color.upper() for key, color in value.items()}

    @field_validator("panel_color")
    @classmethod
    def normalize_panel(cls, value: str) -> str:
        return value.upper()


class AnalyzeResponse(StrictModel):
    job_id: str
    rows: Literal[7] = 7
    cols: int
    theme: Literal["light", "dark"]
    levels: int
    palette: dict[str, str]
    absent_count: int
    preview_original_url: str
    preview_overlay_url: str
    max_name_columns: int
    warnings: list[DetectionWarning] = Field(default_factory=list)


class RenderRequest(StrictModel):
    job_id: str = Field(min_length=10, max_length=64)
    name: Annotated[str, Field(strict=True)]
    primary: HexColor = "#163951"
    secondary: HexColor = "#F5A623"
    outline: HexColor = "#0A1620"
    boldness: Annotated[int, Field(strict=True, ge=0, le=8)] = 2
    start: Annotated[int, Field(strict=True, ge=0)] | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("name must contain at least one letter or digit")
        if len(normalized) > 24:
            raise ValueError("name must contain 24 characters or fewer after trimming")
        if not NAME_PATTERN.fullmatch(normalized):
            raise ValueError("only A-Z, 0-9, space")
        return normalized

    @field_validator("primary", "secondary", "outline")
    @classmethod
    def normalize_hex(cls, value: str) -> str:
        return value.upper()


class RenderResponse(StrictModel):
    fit: Literal[True] = True
    needed_cols: int
    start: int
    letter_cells: int
    overlap_cells: int
    empty_letter_cells: int
    render_url: str


class GridDumpResponse(StrictModel):
    job_id: str
    rows: Literal[7] = 7
    cols: int
    theme: Literal["light", "dark"]
    levels: int
    palette: dict[str, str]
    panel_color: str
    absent_count: int
    cells: list[CellRecord]
    warnings: list[DetectionWarning]
