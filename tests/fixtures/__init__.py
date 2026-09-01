"""Programmatic image fixtures used by the vision and API tests."""

from .synthetic_calendars import (
    PALETTES,
    SyntheticCalendar,
    build_synthetic_calendar,
    image_bytes,
)

__all__ = [
    "PALETTES",
    "SyntheticCalendar",
    "build_synthetic_calendar",
    "image_bytes",
]
