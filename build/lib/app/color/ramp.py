"""Theme-aware primary-color shade ramp generation."""

from __future__ import annotations

import colorsys
import re

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    if not _HEX.fullmatch(value):
        raise ValueError("color must use #RRGGBB")
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))  # type: ignore[return-value]


def rgb_to_hex(rgb: tuple[int, int, int] | list[int]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(channel))):02X}" for channel in rgb)


def _interpolate(left: float, right: float, amount: float) -> float:
    return left + (right - left) * amount


def build_primary_ramp(
    primary: str,
    levels: int,
    theme: str,
) -> dict[int, str]:
    """Build colors for contribution levels ``1 .. levels-1``.

    Hue and saturation remain those of ``primary``.  The upper-middle rank is
    anchored exactly to the supplied color (for the standard five-cluster
    palette, level 3 is the anchor), and lightness progresses monotonically in
    the theme-appropriate direction.
    """

    if levels < 2 or levels > 6:
        raise ValueError("levels must be between 2 and 6")
    if theme not in {"light", "dark"}:
        raise ValueError("theme must be light or dark")

    red, green, blue = hex_to_rgb(primary)
    hue, lightness, saturation = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
    max_level = levels - 1
    anchor = min(max_level, (max_level + 2) // 2)

    if theme == "light":
        weak = max(lightness, 0.62)
        strong = min(lightness, 0.18)
    else:
        weak = min(lightness, 0.38)
        strong = max(lightness, 0.82)

    ramp: dict[int, str] = {}
    for level in range(1, max_level + 1):
        if level == anchor:
            ramp[level] = primary.upper()
            continue
        if level < anchor:
            amount = (level - 1) / max(1, anchor - 1)
            rank_lightness = _interpolate(weak, lightness, amount)
        else:
            amount = (level - anchor) / max(1, max_level - anchor)
            rank_lightness = _interpolate(lightness, strong, amount)
        rgb = colorsys.hls_to_rgb(hue, max(0.0, min(1.0, rank_lightness)), saturation)
        ramp[level] = rgb_to_hex(tuple(round(channel * 255) for channel in rgb))
    return ramp
