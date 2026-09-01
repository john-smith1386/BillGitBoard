from __future__ import annotations

import colorsys

import pytest

from app.color.ramp import build_primary_ramp, hex_to_rgb, rgb_to_hex


def _hls_lightness(color: str) -> float:
    red, green, blue = hex_to_rgb(color)
    return colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)[1]


def test_standard_light_ramp_anchors_level_three_to_primary() -> None:
    ramp = build_primary_ramp("#163951", levels=5, theme="light")

    assert set(ramp) == {1, 2, 3, 4}
    assert ramp[3] == "#163951"
    lightness = [_hls_lightness(ramp[level]) for level in sorted(ramp)]
    assert lightness == sorted(lightness, reverse=True)


def test_dark_ramp_gets_brighter_with_contribution_rank() -> None:
    ramp = build_primary_ramp("#6F42C1", levels=5, theme="dark")

    assert ramp[3] == "#6F42C1"
    lightness = [_hls_lightness(ramp[level]) for level in sorted(ramp)]
    assert lightness == sorted(lightness)


@pytest.mark.parametrize("levels", [2, 3, 4, 5, 6])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_ramp_has_exactly_one_color_for_each_non_empty_rank(levels: int, theme: str) -> None:
    ramp = build_primary_ramp("#3A7CA5", levels=levels, theme=theme)

    assert set(ramp) == set(range(1, levels))
    assert all(color.startswith("#") and len(color) == 7 for color in ramp.values())


@pytest.mark.parametrize(
    ("primary", "levels", "theme"),
    [
        ("163951", 5, "light"),
        ("#GG0000", 5, "light"),
        ("#163951", 1, "light"),
        ("#163951", 7, "light"),
        ("#163951", 5, "sepia"),
    ],
)
def test_ramp_rejects_invalid_inputs(primary: str, levels: int, theme: str) -> None:
    with pytest.raises(ValueError):
        build_primary_ramp(primary, levels=levels, theme=theme)


def test_rgb_hex_conversion_clamps_output_channels() -> None:
    assert hex_to_rgb("#00AaFf") == (0, 170, 255)
    assert rgb_to_hex((-10, 127.6, 999)) == "#0080FF"
