"""Small, wx-independent helpers for the native Appearance editor.

The desktop editor deliberately keeps the persisted schema in
``appearance_presets.AppearanceValues``.  This module supplies the bounded
colour translations and installed-font filtering that the wx surface needs,
without pretending that wx can provide every Word-specific typography axis.
"""

from __future__ import annotations

import colorsys
import math
import re
from typing import Iterable, Tuple

RGB = Tuple[int, int, int]
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})(?:([0-9a-fA-F]{2}))?$")
_RGB = re.compile(
    r"^rgba?\(\s*([0-9]{1,3})\s*[, ]\s*([0-9]{1,3})\s*[, ]\s*([0-9]{1,3})\s*\)?$",
    re.IGNORECASE,
)
_HSL = re.compile(
    r"^hsla?\(\s*([-+]?[0-9]+(?:\.[0-9]+)?)\s*[, ]\s*"
    r"([0-9]+(?:\.[0-9]+)?)%\s*[, ]\s*([0-9]+(?:\.[0-9]+)?)%\s*\)?$",
    re.IGNORECASE,
)


def parse_hex(value: str) -> RGB:
    """Parse ``#RRGGBB``/``#RRGGBBAA`` and ignore alpha for wx previews."""
    match = _HEX.fullmatch(value.strip())
    if match is None:
        raise ValueError("colour must be #RRGGBB or #RRGGBBAA")
    return tuple(int(match.group(1)[offset : offset + 2], 16) for offset in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb: RGB) -> str:
    """Return the canonical uppercase six-digit hex form."""
    _validate_rgb(rgb)
    return "#" + "".join(f"{component:02X}" for component in rgb)


def parse_rgb(value: str) -> RGB:
    """Parse comma-separated RGB or a CSS ``rgb(...)`` value."""
    text = value.strip()
    match = _RGB.fullmatch(text)
    if match is None and not text.lower().startswith(("rgb(", "rgba(")):
        pieces = [piece.strip() for piece in text.split(",")]
        if len(pieces) == 3 and all(piece.isdigit() for piece in pieces):
            match = (pieces[0], pieces[1], pieces[2])
    if match is None:
        raise ValueError("RGB must be three integers between 0 and 255")
    if isinstance(match, tuple):
        rgb = tuple(int(piece) for piece in match)
    else:
        rgb = tuple(int(match.group(index)) for index in range(1, 4))
    _validate_rgb(rgb)  # type: ignore[arg-type]
    return rgb  # type: ignore[return-value]


def rgb_to_hsl(rgb: RGB) -> Tuple[float, float, float]:
    """Return HSL as degrees and percentages."""
    _validate_rgb(rgb)
    hue, lightness, saturation = colorsys.rgb_to_hls(
        *(component / 255 for component in rgb)
    )
    return (round(hue * 360, 2), round(saturation * 100, 2), round(lightness * 100, 2))


def parse_hsl(value: str) -> RGB:
    """Parse CSS-like ``hsl(H, S%, L%)`` into an RGB triple."""
    text = value.strip()
    match = _HSL.fullmatch(text)
    if match is None and not text.lower().startswith(("hsl(", "hsla(")):
        pieces = [piece.strip().rstrip("%") for piece in text.split(",")]
        if len(pieces) == 3:
            try:
                match = (float(pieces[0]), float(pieces[1]), float(pieces[2]))
            except ValueError:
                match = None
    if match is None:
        raise ValueError("HSL must be hue, saturation%, lightness%")
    if isinstance(match, tuple):
        hue_value, saturation_value, lightness_value = match
    else:
        hue_value = float(match.group(1))
        saturation_value = float(match.group(2))
        lightness_value = float(match.group(3))
    hue = hue_value % 360 / 360
    saturation = saturation_value / 100
    lightness = lightness_value / 100
    if not 0 <= saturation <= 1 or not 0 <= lightness <= 1:
        raise ValueError("HSL saturation and lightness must be 0–100%")
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return tuple(round(component * 255) for component in (red, green, blue))  # type: ignore[return-value]


def format_rgb(rgb: RGB) -> str:
    _validate_rgb(rgb)
    return f"{rgb[0]}, {rgb[1]}, {rgb[2]}"


def format_hsl(rgb: RGB) -> str:
    hue, saturation, lightness = rgb_to_hsl(rgb)
    return f"{hue:g}, {saturation:g}%, {lightness:g}%"


def contrast_ratio(first: RGB, second: RGB) -> float:
    """Return the WCAG contrast ratio for two opaque RGB colours."""
    _validate_rgb(first)
    _validate_rgb(second)

    def luminance(rgb: RGB) -> float:
        channels = []
        for value in rgb:
            channel = value / 255
            channels.append(
                channel / 12.92
                if channel <= 0.03928
                else ((channel + 0.055) / 1.055) ** 2.4
            )
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    lighter = max(luminance(first), luminance(second))
    darker = min(luminance(first), luminance(second))
    return round((lighter + 0.05) / (darker + 0.05), 2)


def contrast_summary(rgb: RGB) -> str:
    """Describe contrast against both common text surfaces."""
    white = contrast_ratio(rgb, (255, 255, 255))
    black = contrast_ratio(rgb, (0, 0, 0))
    return f"Contrast: {white:g}:1 on white · {black:g}:1 on black"


def filter_font_names(fonts: Iterable[str], query: str) -> Tuple[str, ...]:
    """Return deterministic, case-insensitive installed-font search results."""
    needle = query.strip().casefold()
    values = {font.strip() for font in fonts if isinstance(font, str) and font.strip()}
    return tuple(
        sorted(
            (font for font in values if not needle or needle in font.casefold()),
            key=str.casefold,
        )
    )


def _validate_rgb(rgb: RGB) -> None:
    if len(rgb) != 3 or any(
        type(component) is not int or not 0 <= component <= 255 for component in rgb
    ):
        raise ValueError("RGB values must be integers between 0 and 255")
