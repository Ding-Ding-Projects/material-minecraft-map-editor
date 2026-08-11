"""Colour arithmetic for every colour control in the application.

A colour control in this interface is not a grid of swatches with a hex box
beside it.  It is a continuous picker whose current value can be read and
written in whichever notation the person in front of it happens to think in --
and the notations disagree about more than spelling.  ``rgb()`` cannot say
anything sRGB cannot show; ``lab()`` and ``oklch()`` can, so a value typed in
one of those may name a colour this display has no way to produce.  ``cmyk()``
has no alpha channel at all, and no meaning without an output profile.  A
translator that quietly rounded those differences away would be worse than no
translator, because it would answer confidently and be wrong.

So the rules here are:

* **Alpha survives every conversion.**  A representation that cannot carry it
  is still handed the value, in the CSS ``/ alpha`` form, rather than dropping
  it on the way through.
* **Out-of-gamut is reported, never silently clipped.**  :func:`gamut` says
  which channels fall outside sRGB and by how much; :func:`clipped` does the
  clipping only when a caller asks for it, and says what it changed.
* **CMYK is labelled as what it is** -- a naive device conversion with no ICC
  profile behind it -- rather than presented as a colorimetric answer.
* **A name is only a name when it is exact.**  :func:`name_of` returns the CSS
  colour keyword only for an exact match; :func:`nearest_name` is a separate,
  clearly-labelled convenience so the two can never be confused.

Nothing here imports ``wx`` and nothing here is a new dependency: the module is
the standard library and arithmetic, so it is testable, importable in a
headless environment, and usable by anything that needs a colour rather than
only by the picker that renders one.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = [
    "ALPHA_CARRYING",
    "Colour",
    "ColourError",
    "ContrastReport",
    "GamutReport",
    "NAMED_COLOURS",
    "REPRESENTATIONS",
    "REPRESENTATION_LABELS",
    "clipped",
    "composite",
    "contrast_report",
    "contrast_ratio",
    "format_as",
    "from_cmyk",
    "from_hsl",
    "from_hsv",
    "from_hwb",
    "from_lab",
    "from_lch",
    "from_oklab",
    "from_oklch",
    "from_rgb255",
    "gamut",
    "name_of",
    "named_colour",
    "nearest_name",
    "parse",
    "relative_luminance",
    "round_trip",
    "to_cmyk",
    "to_hsl",
    "to_hsv",
    "to_hwb",
    "to_lab",
    "to_lch",
    "to_oklab",
    "to_oklch",
    "to_rgb255",
    "translate",
]


class ColourError(ValueError):
    """A colour string this module cannot read.

    It carries a sentence a person can act on rather than a parser trace,
    because it is shown directly beside the field that was typed into.
    """


#: The representations the translator carries, in the order it offers them.
#: Every one of them round-trips: parsing what :func:`format_as` produced
#: returns the same colour, to eight-bit precision, with its alpha intact.
REPRESENTATIONS: Tuple[str, ...] = (
    "name",
    "hex",
    "hex8",
    "rgb",
    "rgba",
    "hsl",
    "hsla",
    "hsv",
    "hwb",
    "lab",
    "lch",
    "oklab",
    "oklch",
    "cmyk",
)

#: What each representation is called in the interface, and the one-line
#: explanation shown beside it.  A notation that cannot express everything the
#: colour holds says so here rather than in a footnote nobody reads.
REPRESENTATION_LABELS: Dict[str, Tuple[str, str]] = {
    "name": ("Named colour", "The CSS keyword, only when the match is exact."),
    "hex": ("HEX", "Six digits. Alpha is not carried; see HEX8."),
    "hex8": ("HEX8", "Eight digits, the last two being alpha."),
    "rgb": ("RGB", "sRGB channels, 0 to 255."),
    "rgba": ("RGBA", "sRGB channels with alpha, 0 to 1."),
    "hsl": ("HSL", "Hue in degrees, saturation and lightness as percentages."),
    "hsla": ("HSLA", "HSL with alpha."),
    "hsv": ("HSV / HSB", "Hue, saturation, value. HSB is the same notation."),
    "hwb": ("HWB", "Hue, whiteness, blackness."),
    "lab": (
        "CIELAB",
        "Perceptual, D50 white point. Can describe colours sRGB cannot show.",
    ),
    "lch": ("LCH", "CIELAB in polar form: lightness, chroma, hue."),
    "oklab": ("OKLab", "Perceptual and hue-stable. Can exceed the sRGB gamut."),
    "oklch": ("OKLCH", "OKLab in polar form: lightness, chroma, hue."),
    "cmyk": (
        "CMYK",
        "A naive device conversion with no ICC profile behind it; a printer will not match it.",
    ),
}

#: Anything at or below this counts as equal when comparing channels, and as
#: inside the gamut when checking one.  It is a hair under half an eight-bit
#: step, so a value that rounds to an in-range byte is not called out of range.
_EPSILON = 1.0 / 512.0

#: The CSS colour keywords.  Only an exact match returns one of these names;
#: everything else is reported as having no name rather than as the nearest.
NAMED_COLOURS: Dict[str, str] = {
    "aliceblue": "#F0F8FF",
    "antiquewhite": "#FAEBD7",
    "aqua": "#00FFFF",
    "aquamarine": "#7FFFD4",
    "azure": "#F0FFFF",
    "beige": "#F5F5DC",
    "bisque": "#FFE4C4",
    "black": "#000000",
    "blanchedalmond": "#FFEBCD",
    "blue": "#0000FF",
    "blueviolet": "#8A2BE2",
    "brown": "#A52A2A",
    "burlywood": "#DEB887",
    "cadetblue": "#5F9EA0",
    "chartreuse": "#7FFF00",
    "chocolate": "#D2691E",
    "coral": "#FF7F50",
    "cornflowerblue": "#6495ED",
    "cornsilk": "#FFF8DC",
    "crimson": "#DC143C",
    "cyan": "#00FFFF",
    "darkblue": "#00008B",
    "darkcyan": "#008B8B",
    "darkgoldenrod": "#B8860B",
    "darkgray": "#A9A9A9",
    "darkgreen": "#006400",
    "darkgrey": "#A9A9A9",
    "darkkhaki": "#BDB76B",
    "darkmagenta": "#8B008B",
    "darkolivegreen": "#556B2F",
    "darkorange": "#FF8C00",
    "darkorchid": "#9932CC",
    "darkred": "#8B0000",
    "darksalmon": "#E9967A",
    "darkseagreen": "#8FBC8F",
    "darkslateblue": "#483D8B",
    "darkslategray": "#2F4F4F",
    "darkslategrey": "#2F4F4F",
    "darkturquoise": "#00CED1",
    "darkviolet": "#9400D3",
    "deeppink": "#FF1493",
    "deepskyblue": "#00BFFF",
    "dimgray": "#696969",
    "dimgrey": "#696969",
    "dodgerblue": "#1E90FF",
    "firebrick": "#B22222",
    "floralwhite": "#FFFAF0",
    "forestgreen": "#228B22",
    "fuchsia": "#FF00FF",
    "gainsboro": "#DCDCDC",
    "ghostwhite": "#F8F8FF",
    "gold": "#FFD700",
    "goldenrod": "#DAA520",
    "gray": "#808080",
    "green": "#008000",
    "greenyellow": "#ADFF2F",
    "grey": "#808080",
    "honeydew": "#F0FFF0",
    "hotpink": "#FF69B4",
    "indianred": "#CD5C5C",
    "indigo": "#4B0082",
    "ivory": "#FFFFF0",
    "khaki": "#F0E68C",
    "lavender": "#E6E6FA",
    "lavenderblush": "#FFF0F5",
    "lawngreen": "#7CFC00",
    "lemonchiffon": "#FFFACD",
    "lightblue": "#ADD8E6",
    "lightcoral": "#F08080",
    "lightcyan": "#E0FFFF",
    "lightgoldenrodyellow": "#FAFAD2",
    "lightgray": "#D3D3D3",
    "lightgreen": "#90EE90",
    "lightgrey": "#D3D3D3",
    "lightpink": "#FFB6C1",
    "lightsalmon": "#FFA07A",
    "lightseagreen": "#20B2AA",
    "lightskyblue": "#87CEFA",
    "lightslategray": "#778899",
    "lightslategrey": "#778899",
    "lightsteelblue": "#B0C4DE",
    "lightyellow": "#FFFFE0",
    "lime": "#00FF00",
    "limegreen": "#32CD32",
    "linen": "#FAF0E6",
    "magenta": "#FF00FF",
    "maroon": "#800000",
    "mediumaquamarine": "#66CDAA",
    "mediumblue": "#0000CD",
    "mediumorchid": "#BA55D3",
    "mediumpurple": "#9370DB",
    "mediumseagreen": "#3CB371",
    "mediumslateblue": "#7B68EE",
    "mediumspringgreen": "#00FA9A",
    "mediumturquoise": "#48D1CC",
    "mediumvioletred": "#C71585",
    "midnightblue": "#191970",
    "mintcream": "#F5FFFA",
    "mistyrose": "#FFE4E1",
    "moccasin": "#FFE4B5",
    "navajowhite": "#FFDEAD",
    "navy": "#000080",
    "oldlace": "#FDF5E6",
    "olive": "#808000",
    "olivedrab": "#6B8E23",
    "orange": "#FFA500",
    "orangered": "#FF4500",
    "orchid": "#DA70D6",
    "palegoldenrod": "#EEE8AA",
    "palegreen": "#98FB98",
    "paleturquoise": "#AFEEEE",
    "palevioletred": "#DB7093",
    "papayawhip": "#FFEFD5",
    "peachpuff": "#FFDAB9",
    "peru": "#CD853F",
    "pink": "#FFC0CB",
    "plum": "#DDA0DD",
    "powderblue": "#B0E0E6",
    "purple": "#800080",
    "rebeccapurple": "#663399",
    "red": "#FF0000",
    "rosybrown": "#BC8F8F",
    "royalblue": "#4169E1",
    "saddlebrown": "#8B4513",
    "salmon": "#FA8072",
    "sandybrown": "#F4A460",
    "seagreen": "#2E8B57",
    "seashell": "#FFF5EE",
    "sienna": "#A0522D",
    "silver": "#C0C0C0",
    "skyblue": "#87CEEB",
    "slateblue": "#6A5ACD",
    "slategray": "#708090",
    "slategrey": "#708090",
    "snow": "#FFFAFA",
    "springgreen": "#00FF7F",
    "steelblue": "#4682B4",
    "tan": "#D2B48C",
    "teal": "#008080",
    "thistle": "#D8BFD8",
    "tomato": "#FF6347",
    "turquoise": "#40E0D0",
    "violet": "#EE82EE",
    "wheat": "#F5DEB3",
    "white": "#FFFFFF",
    "whitesmoke": "#F5F5F5",
    "yellow": "#FFFF00",
    "yellowgreen": "#9ACD32",
}

#: Reverse lookup for :func:`name_of`.  Several keywords share a value (``aqua``
#: and ``cyan``, every ``gray``/``grey`` pair), so the first spelling in
#: :data:`NAMED_COLOURS` wins and the alternative is simply not returned -- one
#: value cannot have two exact names without the answer becoming arbitrary.
_NAME_BY_HEX: Dict[str, str] = {}
for _name, _hex in NAMED_COLOURS.items():
    _NAME_BY_HEX.setdefault(_hex.upper(), _name)


@dataclass(frozen=True)
class Colour:
    """One colour, held as unbounded sRGB components plus alpha.

    The components are *not* clamped.  A value read from ``lab()``, ``lch()``,
    ``oklab()``, ``oklch()`` or ``cmyk()`` can name a colour outside what an
    sRGB display can show, and clamping it on the way in would destroy the one
    fact the picker has to report: that the colour the user asked for is not
    the colour they are going to get.  :func:`gamut` measures the excess and
    :func:`clipped` removes it, in that order and only when asked.

    ``space`` records the notation the value was last authored in, so the
    picker can say which space is active rather than guessing from the digits.
    """

    red: float
    green: float
    blue: float
    alpha: float = 1.0
    space: str = "srgb"

    @property
    def in_gamut(self) -> bool:
        """Whether every channel lies inside sRGB, within eight-bit tolerance."""
        return all(
            -_EPSILON <= value <= 1.0 + _EPSILON
            for value in (self.red, self.green, self.blue)
        )

    def with_alpha(self, alpha: float) -> "Colour":
        """Return the same colour at a different alpha."""
        return replace(self, alpha=_clamp(float(alpha)))

    def in_space(self, space: str) -> "Colour":
        """Return the same colour labelled as authored in ``space``."""
        return replace(self, space=str(space))


@dataclass(frozen=True)
class GamutReport:
    """What sRGB can and cannot show of one colour."""

    #: The notation the colour was authored in.
    space: str
    #: Whether every channel is already inside sRGB.
    in_gamut: bool
    #: Channels outside the gamut, as ``(name, value, clipped value)``.
    excursions: Tuple[Tuple[str, float, float], ...]
    #: The largest distance any channel falls outside ``0..1``.
    worst: float
    #: One sentence naming what would be lost, ready to show beside the field.
    message: str


@dataclass(frozen=True)
class ContrastReport:
    """A WCAG 2 contrast reading between an ink and the surface behind it."""

    ratio: float
    #: The ink after being composited over the surface at its own alpha, so a
    #: translucent ink is measured as it will actually appear.
    effective_foreground: Colour
    background: Colour
    passes_aa_normal: bool
    passes_aa_large: bool
    passes_aaa_normal: bool
    passes_aaa_large: bool
    summary: str


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def _cbrt(value: float) -> float:
    """Real cube root, including for negative input.

    ``x ** (1 / 3)`` raises for a negative ``x``, and every one of the OKLab
    channels can be negative, so this is not a stylistic wrapper.
    """
    return math.copysign(abs(value) ** (1.0 / 3.0), value)


def _round(value: float, digits: int) -> str:
    """Format a float without a trailing ``.0`` or a run of trailing zeroes."""
    text = f"{value:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _hue(value: float) -> float:
    """Wrap a hue into ``0 <= h < 360``."""
    result = math.fmod(float(value), 360.0)
    return result + 360.0 if result < 0 else result


# ---------------------------------------------------------------------------
# sRGB, HSL, HSV, HWB
# ---------------------------------------------------------------------------


def from_rgb255(red: int, green: int, blue: int, alpha: float = 1.0) -> Colour:
    """Build a colour from eight-bit channels."""
    return Colour(
        _clamp(float(red) / 255.0),
        _clamp(float(green) / 255.0),
        _clamp(float(blue) / 255.0),
        _clamp(float(alpha)),
        "rgb",
    )


def to_rgb255(colour: Colour) -> Tuple[int, int, int]:
    """Return the colour's eight-bit channels, clipping to sRGB first."""
    return (
        round(_clamp(colour.red) * 255),
        round(_clamp(colour.green) * 255),
        round(_clamp(colour.blue) * 255),
    )


def to_hsl(colour: Colour) -> Tuple[float, float, float]:
    """Return hue in degrees and saturation/lightness as fractions."""
    red, green, blue = (_clamp(colour.red), _clamp(colour.green), _clamp(colour.blue))
    high = max(red, green, blue)
    low = min(red, green, blue)
    lightness = (high + low) / 2.0
    span = high - low
    if span <= 0:
        return 0.0, 0.0, lightness
    saturation = span / (1.0 - abs(2.0 * lightness - 1.0))
    if high == red:
        hue = 60.0 * (((green - blue) / span) % 6.0)
    elif high == green:
        hue = 60.0 * (((blue - red) / span) + 2.0)
    else:
        hue = 60.0 * (((red - green) / span) + 4.0)
    return _hue(hue), _clamp(saturation), lightness


def from_hsl(
    hue: float, saturation: float, lightness: float, alpha: float = 1.0
) -> Colour:
    """Build a colour from hue in degrees and fractional saturation/lightness."""
    hue = _hue(hue)
    saturation = _clamp(saturation)
    lightness = _clamp(lightness)
    chroma = (1.0 - abs(2.0 * lightness - 1.0)) * saturation
    second = chroma * (1.0 - abs(math.fmod(hue / 60.0, 2.0) - 1.0))
    offset = lightness - chroma / 2.0
    sector = int(hue // 60) % 6
    table = (
        (chroma, second, 0.0),
        (second, chroma, 0.0),
        (0.0, chroma, second),
        (0.0, second, chroma),
        (second, 0.0, chroma),
        (chroma, 0.0, second),
    )[sector]
    return Colour(
        _clamp(table[0] + offset),
        _clamp(table[1] + offset),
        _clamp(table[2] + offset),
        _clamp(alpha),
        "hsl",
    )


def to_hsv(colour: Colour) -> Tuple[float, float, float]:
    """Return hue in degrees and saturation/value as fractions."""
    red, green, blue = (_clamp(colour.red), _clamp(colour.green), _clamp(colour.blue))
    high = max(red, green, blue)
    low = min(red, green, blue)
    span = high - low
    if span <= 0:
        hue = 0.0
    elif high == red:
        hue = 60.0 * (((green - blue) / span) % 6.0)
    elif high == green:
        hue = 60.0 * (((blue - red) / span) + 2.0)
    else:
        hue = 60.0 * (((red - green) / span) + 4.0)
    saturation = 0.0 if high <= 0 else span / high
    return _hue(hue), _clamp(saturation), high


def from_hsv(hue: float, saturation: float, value: float, alpha: float = 1.0) -> Colour:
    """Build a colour from hue in degrees and fractional saturation/value."""
    hue = _hue(hue)
    saturation = _clamp(saturation)
    value = _clamp(value)
    chroma = value * saturation
    second = chroma * (1.0 - abs(math.fmod(hue / 60.0, 2.0) - 1.0))
    offset = value - chroma
    sector = int(hue // 60) % 6
    table = (
        (chroma, second, 0.0),
        (second, chroma, 0.0),
        (0.0, chroma, second),
        (0.0, second, chroma),
        (second, 0.0, chroma),
        (chroma, 0.0, second),
    )[sector]
    return Colour(
        _clamp(table[0] + offset),
        _clamp(table[1] + offset),
        _clamp(table[2] + offset),
        _clamp(alpha),
        "hsv",
    )


def to_hwb(colour: Colour) -> Tuple[float, float, float]:
    """Return hue in degrees with fractional whiteness and blackness."""
    hue, _saturation, _value = to_hsv(colour)
    red, green, blue = (_clamp(colour.red), _clamp(colour.green), _clamp(colour.blue))
    return hue, min(red, green, blue), 1.0 - max(red, green, blue)


def from_hwb(
    hue: float, whiteness: float, blackness: float, alpha: float = 1.0
) -> Colour:
    """Build a colour from hue in degrees with fractional whiteness/blackness."""
    whiteness = _clamp(whiteness)
    blackness = _clamp(blackness)
    if whiteness + blackness >= 1.0:
        grey = whiteness / (whiteness + blackness)
        return Colour(grey, grey, grey, _clamp(alpha), "hwb")
    base = from_hsv(hue, 1.0, 1.0)
    scale = 1.0 - whiteness - blackness
    return Colour(
        base.red * scale + whiteness,
        base.green * scale + whiteness,
        base.blue * scale + whiteness,
        _clamp(alpha),
        "hwb",
    )


# ---------------------------------------------------------------------------
# CIELAB / LCH, by way of linear light and XYZ
# ---------------------------------------------------------------------------

#: CIE standard illuminant D50, the white point CSS ``lab()`` is defined
#: against.  Using D65 here instead would shift every reading by a visible
#: amount while still looking plausible, which is the worst kind of wrong.
_D50 = (0.3457 / 0.3585, 1.0, (1.0 - 0.3457 - 0.3585) / 0.3585)

_LINEAR_TO_XYZ_D65 = (
    (0.41239079926595934, 0.357584339383878, 0.1804807884018343),
    (0.21263900587151027, 0.715168678767756, 0.07219231536073371),
    (0.01933081871559182, 0.11919477979462598, 0.9505321522496607),
)
_XYZ_D65_TO_LINEAR = (
    (3.2409699419045226, -1.537383177570094, -0.4986107602930034),
    (-0.9692436362808796, 1.8759675015077202, 0.04155505740717559),
    (0.05563007969699366, -0.20397695888897652, 1.0569715142428786),
)
_D65_TO_D50 = (
    (1.0479298208405488, 0.022946793341019088, -0.05019222954313557),
    (0.029627815688159344, 0.990434484573249, -0.01707382502938514),
    (-0.009243058152591178, 0.015055144896577895, 0.7518742899580008),
)
_D50_TO_D65 = (
    (0.9554734527042182, -0.023098536874261423, 0.0632593086610217),
    (-0.028369706963208136, 1.0099954580058226, 0.021041398966943008),
    (0.012314001688319899, -0.020507696433477912, 1.3303659366080753),
)

_LAB_EPSILON = 216.0 / 24389.0
_LAB_KAPPA = 24389.0 / 27.0


def _apply(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> List[float]:
    return [sum(row[i] * vector[i] for i in range(3)) for row in matrix]


def _to_linear(value: float) -> float:
    """sRGB transfer function, inverted, defined for values outside 0..1 too."""
    sign = -1.0 if value < 0 else 1.0
    magnitude = abs(value)
    if magnitude <= 0.04045:
        return value / 12.92
    return sign * ((magnitude + 0.055) / 1.055) ** 2.4


def _from_linear(value: float) -> float:
    sign = -1.0 if value < 0 else 1.0
    magnitude = abs(value)
    if magnitude <= 0.0031308:
        return value * 12.92
    return sign * (1.055 * magnitude ** (1.0 / 2.4) - 0.055)


def to_lab(colour: Colour) -> Tuple[float, float, float]:
    """Return CIELAB ``L`` (0-100) and ``a``/``b`` against the D50 white point."""
    linear = [_to_linear(colour.red), _to_linear(colour.green), _to_linear(colour.blue)]
    xyz = _apply(_D65_TO_D50, _apply(_LINEAR_TO_XYZ_D65, linear))
    scaled = [xyz[i] / _D50[i] for i in range(3)]
    f = [
        _cbrt(value) if value > _LAB_EPSILON else (_LAB_KAPPA * value + 16.0) / 116.0
        for value in scaled
    ]
    return (
        116.0 * f[1] - 16.0,
        500.0 * (f[0] - f[1]),
        200.0 * (f[1] - f[2]),
    )


def from_lab(
    lightness: float, a_axis: float, b_axis: float, alpha: float = 1.0
) -> Colour:
    """Build a colour from CIELAB against D50, leaving it unclipped."""
    fy = (float(lightness) + 16.0) / 116.0
    fx = fy + float(a_axis) / 500.0
    fz = fy - float(b_axis) / 200.0

    def _invert(value: float, is_y: bool) -> float:
        cubed = value**3
        if is_y:
            return (
                cubed
                if float(lightness) > _LAB_KAPPA * _LAB_EPSILON
                else float(lightness) / _LAB_KAPPA
            )
        return cubed if cubed > _LAB_EPSILON else (116.0 * value - 16.0) / _LAB_KAPPA

    xyz_d50 = [
        _invert(fx, False) * _D50[0],
        _invert(fy, True) * _D50[1],
        _invert(fz, False) * _D50[2],
    ]
    linear = _apply(_XYZ_D65_TO_LINEAR, _apply(_D50_TO_D65, xyz_d50))
    return Colour(
        _from_linear(linear[0]),
        _from_linear(linear[1]),
        _from_linear(linear[2]),
        _clamp(alpha),
        "lab",
    )


def to_lch(colour: Colour) -> Tuple[float, float, float]:
    """Return CIELAB in polar form: lightness, chroma, hue in degrees."""
    lightness, a_axis, b_axis = to_lab(colour)
    chroma = math.hypot(a_axis, b_axis)
    hue = 0.0 if chroma < 1e-6 else _hue(math.degrees(math.atan2(b_axis, a_axis)))
    return lightness, chroma, hue


def from_lch(lightness: float, chroma: float, hue: float, alpha: float = 1.0) -> Colour:
    """Build a colour from polar CIELAB, leaving it unclipped."""
    radians = math.radians(_hue(hue))
    return replace(
        from_lab(
            lightness, chroma * math.cos(radians), chroma * math.sin(radians), alpha
        ),
        space="lch",
    )


# ---------------------------------------------------------------------------
# OKLab / OKLCH
# ---------------------------------------------------------------------------


def to_oklab(colour: Colour) -> Tuple[float, float, float]:
    """Return OKLab ``L`` (0-1) with its ``a`` and ``b`` axes."""
    red = _to_linear(colour.red)
    green = _to_linear(colour.green)
    blue = _to_linear(colour.blue)
    long_ = _cbrt(0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue)
    medium = _cbrt(0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue)
    short = _cbrt(0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue)
    return (
        0.2104542553 * long_ + 0.7936177850 * medium - 0.0040720468 * short,
        1.9779984951 * long_ - 2.4285922050 * medium + 0.4505937099 * short,
        0.0259040371 * long_ + 0.7827717662 * medium - 0.8086757660 * short,
    )


def from_oklab(
    lightness: float, a_axis: float, b_axis: float, alpha: float = 1.0
) -> Colour:
    """Build a colour from OKLab, leaving it unclipped."""
    lightness = float(lightness)
    a_axis = float(a_axis)
    b_axis = float(b_axis)
    long_ = (lightness + 0.3963377774 * a_axis + 0.2158037573 * b_axis) ** 3
    medium = (lightness - 0.1055613458 * a_axis - 0.0638541728 * b_axis) ** 3
    short = (lightness - 0.0894841775 * a_axis - 1.2914855480 * b_axis) ** 3
    red = 4.0767416621 * long_ - 3.3077115913 * medium + 0.2309699292 * short
    green = -1.2684380046 * long_ + 2.6097574011 * medium - 0.3413193965 * short
    blue = -0.0041960863 * long_ - 0.7034186147 * medium + 1.7076147010 * short
    return Colour(
        _from_linear(red),
        _from_linear(green),
        _from_linear(blue),
        _clamp(alpha),
        "oklab",
    )


def to_oklch(colour: Colour) -> Tuple[float, float, float]:
    """Return OKLab in polar form: lightness, chroma, hue in degrees."""
    lightness, a_axis, b_axis = to_oklab(colour)
    chroma = math.hypot(a_axis, b_axis)
    hue = 0.0 if chroma < 1e-9 else _hue(math.degrees(math.atan2(b_axis, a_axis)))
    return lightness, chroma, hue


def from_oklch(
    lightness: float, chroma: float, hue: float, alpha: float = 1.0
) -> Colour:
    """Build a colour from polar OKLab, leaving it unclipped."""
    radians = math.radians(_hue(hue))
    return replace(
        from_oklab(
            lightness, chroma * math.cos(radians), chroma * math.sin(radians), alpha
        ),
        space="oklch",
    )


# ---------------------------------------------------------------------------
# CMYK
# ---------------------------------------------------------------------------


def to_cmyk(colour: Colour) -> Tuple[float, float, float, float]:
    """Return a naive device CMYK, each component a fraction.

    There is no ICC profile behind this and there is no honest way to pretend
    otherwise: the conversion is the arithmetic one every drawing program calls
    "CMYK" when it has not been told which press it is printing on.  It is
    offered because people work in it, and it is labelled everywhere it is
    shown so nobody mistakes it for a proof.
    """
    red, green, blue = (_clamp(colour.red), _clamp(colour.green), _clamp(colour.blue))
    key = 1.0 - max(red, green, blue)
    if key >= 1.0 - 1e-9:
        return 0.0, 0.0, 0.0, 1.0
    divisor = 1.0 - key
    return (
        (1.0 - red - key) / divisor,
        (1.0 - green - key) / divisor,
        (1.0 - blue - key) / divisor,
        key,
    )


def from_cmyk(
    cyan: float,
    magenta: float,
    yellow: float,
    key: float,
    alpha: float = 1.0,
) -> Colour:
    """Build a colour from naive device CMYK fractions."""
    cyan = _clamp(cyan)
    magenta = _clamp(magenta)
    yellow = _clamp(yellow)
    key = _clamp(key)
    return Colour(
        (1.0 - cyan) * (1.0 - key),
        (1.0 - magenta) * (1.0 - key),
        (1.0 - yellow) * (1.0 - key),
        _clamp(alpha),
        "cmyk",
    )


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------


def named_colour(name: str) -> Optional[Colour]:
    """Return the colour for a CSS keyword, or ``None`` when there is no such name."""
    key = str(name or "").strip().lower()
    if key == "transparent":
        return Colour(0.0, 0.0, 0.0, 0.0, "name")
    value = NAMED_COLOURS.get(key)
    return None if value is None else replace(parse(value), space="name")


def name_of(colour: Colour) -> Optional[str]:
    """Return the CSS keyword for an exact match, or ``None``.

    Alpha is part of the match: a half-transparent red is not ``red``, because
    writing it as ``red`` would silently drop the transparency.  A fully
    transparent black is ``transparent``, which is the keyword that means it.
    """
    if abs(colour.alpha) <= _EPSILON:
        return "transparent"
    if abs(colour.alpha - 1.0) > _EPSILON or not colour.in_gamut:
        return None
    red, green, blue = to_rgb255(colour)
    return _NAME_BY_HEX.get(f"#{red:02X}{green:02X}{blue:02X}")


def nearest_name(colour: Colour) -> Tuple[str, float]:
    """Return the closest CSS keyword and its distance, in eight-bit units.

    This is a convenience and it is labelled as one wherever it is shown.  A
    distance of zero means :func:`name_of` would have returned the same name;
    anything else means the keyword is near, not right.
    """
    red, green, blue = to_rgb255(colour)
    best_name = "black"
    best_distance = float("inf")
    for name, value in NAMED_COLOURS.items():
        other = value.lstrip("#")
        distance = math.dist(
            (red, green, blue),
            (int(other[0:2], 16), int(other[2:4], 16), int(other[4:6], 16)),
        )
        if distance < best_distance:
            best_distance = distance
            best_name = name
    return best_name, best_distance


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

_FUNCTION = re.compile(r"^([a-z][a-z0-9-]*)\((.*)\)$", re.IGNORECASE | re.DOTALL)
_HEX = re.compile(r"^#?([0-9a-fA-F]{3,8})$")


def _split_arguments(body: str) -> Tuple[List[str], Optional[str]]:
    """Split a function body into components and an optional alpha.

    Both CSS spellings are accepted -- commas, and space separation with the
    alpha after a slash -- because both are what people paste in.
    """
    text = body.strip()
    alpha: Optional[str] = None
    if "/" in text:
        text, _, tail = text.partition("/")
        alpha = tail.strip() or None
    if "," in text:
        parts = [part.strip() for part in text.split(",")]
        if alpha is None and len(parts) in (4, 5):
            alpha = parts.pop()
    else:
        parts = [part for part in re.split(r"\s+", text.strip()) if part]
    return [part for part in parts if part], alpha


def _number(text: str) -> float:
    """Read a bare number, a percentage, or a ``deg`` angle."""
    value = str(text).strip().lower()
    if value.endswith("%"):
        try:
            return float(value[:-1]) / 100.0
        except ValueError as error:
            raise ColourError(f"{text!r} is not a percentage.") from error
    if value.endswith("deg"):
        value = value[:-3]
    try:
        return float(value)
    except ValueError as error:
        raise ColourError(f"{text!r} is not a number.") from error


def _alpha(text: Optional[str]) -> float:
    if text is None or str(text).strip().lower() in ("", "none"):
        return 1.0
    return _clamp(_number(text))


def _parse_hex(digits: str) -> Colour:
    if len(digits) in (3, 4):
        digits = "".join(character * 2 for character in digits)
    if len(digits) not in (6, 8):
        raise ColourError(
            "A hexadecimal colour needs 3, 4, 6, or 8 digits, for example #6750A4."
        )
    red = int(digits[0:2], 16)
    green = int(digits[2:4], 16)
    blue = int(digits[4:6], 16)
    alpha = int(digits[6:8], 16) / 255.0 if len(digits) == 8 else 1.0
    return replace(
        from_rgb255(red, green, blue, alpha),
        space="hex8" if len(digits) == 8 else "hex",
    )


def parse(text: str) -> Colour:
    """Read any representation this module can write, or raise :class:`ColourError`.

    The returned colour records which notation it came from, so the picker can
    name the active space instead of inferring it, and a value from a
    wider-than-sRGB notation is returned *unclipped* so the gamut report has
    something to report.
    """
    raw = str(text or "").strip()
    if not raw:
        raise ColourError("Type a colour, for example #6750A4 or oklch(0.7 0.1 180).")

    named = named_colour(raw)
    if named is not None:
        return named

    match = _HEX.match(raw)
    if match is not None and (raw.startswith("#") or len(match.group(1)) in (6, 8)):
        return _parse_hex(match.group(1))

    function = _FUNCTION.match(raw)
    if function is None:
        raise ColourError(
            f"{raw!r} is not a colour this translator reads. "
            "Try a hexadecimal value, a CSS keyword, or one of the listed notations."
        )
    name = function.group(1).lower()
    parts, alpha_text = _split_arguments(function.group(2))
    alpha = _alpha(alpha_text)

    try:
        if name in ("rgb", "rgba"):
            if len(parts) < 3:
                raise ColourError("rgb() needs three channels.")
            channels = [
                (_number(part) * 255.0 if part.strip().endswith("%") else _number(part))
                for part in parts[:3]
            ]
            return replace(
                from_rgb255(
                    round(channels[0]), round(channels[1]), round(channels[2]), alpha
                ),
                space="rgba" if name == "rgba" or alpha_text is not None else "rgb",
            )
        if name in ("hsl", "hsla"):
            if len(parts) < 3:
                raise ColourError("hsl() needs a hue, a saturation, and a lightness.")
            return replace(
                from_hsl(
                    _number(parts[0]), _number(parts[1]), _number(parts[2]), alpha
                ),
                space="hsla" if name == "hsla" or alpha_text is not None else "hsl",
            )
        if name in ("hsv", "hsb"):
            if len(parts) < 3:
                raise ColourError("hsv() needs a hue, a saturation, and a value.")
            return from_hsv(
                _number(parts[0]), _number(parts[1]), _number(parts[2]), alpha
            )
        if name == "hwb":
            if len(parts) < 3:
                raise ColourError("hwb() needs a hue, a whiteness, and a blackness.")
            return from_hwb(
                _number(parts[0]), _number(parts[1]), _number(parts[2]), alpha
            )
        if name == "lab":
            if len(parts) < 3:
                raise ColourError("lab() needs a lightness and two axes.")
            lightness = (
                _number(parts[0]) * 100.0
                if parts[0].strip().endswith("%")
                else _number(parts[0])
            )
            return from_lab(lightness, _number(parts[1]), _number(parts[2]), alpha)
        if name == "lch":
            if len(parts) < 3:
                raise ColourError("lch() needs a lightness, a chroma, and a hue.")
            lightness = (
                _number(parts[0]) * 100.0
                if parts[0].strip().endswith("%")
                else _number(parts[0])
            )
            return from_lch(lightness, _number(parts[1]), _number(parts[2]), alpha)
        if name == "oklab":
            if len(parts) < 3:
                raise ColourError("oklab() needs a lightness and two axes.")
            return from_oklab(
                _number(parts[0]), _number(parts[1]), _number(parts[2]), alpha
            )
        if name == "oklch":
            if len(parts) < 3:
                raise ColourError("oklch() needs a lightness, a chroma, and a hue.")
            return from_oklch(
                _number(parts[0]), _number(parts[1]), _number(parts[2]), alpha
            )
        if name in ("cmyk", "device-cmyk"):
            if len(parts) < 4:
                raise ColourError("cmyk() needs four components.")
            return from_cmyk(
                _number(parts[0]),
                _number(parts[1]),
                _number(parts[2]),
                _number(parts[3]),
                alpha,
            )
    except ColourError:
        raise
    except (TypeError, ValueError, IndexError) as error:
        raise ColourError(f"{raw!r} could not be read as {name}(): {error}") from error

    raise ColourError(
        f"{name}() is not one of the notations this translator reads: "
        + ", ".join(
            sorted({"rgb", "hsl", "hsv", "hwb", "lab", "lch", "oklab", "oklch", "cmyk"})
        )
    )


# ---------------------------------------------------------------------------
# formatting
# ---------------------------------------------------------------------------


#: Representations that carry alpha.  The four that do not are offered anyway,
#: beside the twin that does, because they are what people paste into a
#: stylesheet -- and the translator says which is which rather than letting
#: somebody copy ``hex`` and discover later that the transparency went missing.
ALPHA_CARRYING: Tuple[str, ...] = (
    "hex8",
    "rgba",
    "hsla",
    "hsv",
    "hwb",
    "lab",
    "lch",
    "oklab",
    "oklch",
    "cmyk",
)


def format_as(colour: Colour, representation: str) -> str:
    """Write ``colour`` in one notation.

    Every notation in :data:`ALPHA_CARRYING` writes the alpha, in the CSS
    ``/ alpha`` form for the ones with no channel of their own, so a value
    copied out of one of those rows and pasted into another is the same colour.
    ``hex``, ``rgb`` and ``hsl`` cannot say alpha at all and are offered beside
    their twins that can; ``name`` returns an empty string when no CSS keyword
    matches exactly, rather than inventing the nearest one.
    """
    key = str(representation)
    alpha = _clamp(colour.alpha)
    red, green, blue = to_rgb255(colour)

    if key == "name":
        return name_of(colour) or ""
    if key == "hex":
        return f"#{red:02X}{green:02X}{blue:02X}"
    if key == "hex8":
        return f"#{red:02X}{green:02X}{blue:02X}{round(alpha * 255):02X}"
    if key == "rgb":
        return f"rgb({red}, {green}, {blue})"
    if key == "rgba":
        return f"rgba({red}, {green}, {blue}, {_round(alpha, 4)})"
    if key in ("hsl", "hsla"):
        hue, saturation, lightness = to_hsl(colour)
        body = (
            f"{_round(hue, 3)}, {_round(saturation * 100, 3)}%, "
            f"{_round(lightness * 100, 3)}%"
        )
        if key == "hsla":
            return f"hsla({body}, {_round(alpha, 4)})"
        return f"hsl({body})"
    if key == "hsv":
        hue, saturation, value = to_hsv(colour)
        return (
            f"hsv({_round(hue, 3)} {_round(saturation * 100, 3)}% "
            f"{_round(value * 100, 3)}% / {_round(alpha, 4)})"
        )
    if key == "hwb":
        hue, whiteness, blackness = to_hwb(colour)
        return (
            f"hwb({_round(hue, 3)} {_round(whiteness * 100, 3)}% "
            f"{_round(blackness * 100, 3)}% / {_round(alpha, 4)})"
        )
    if key == "lab":
        lightness, a_axis, b_axis = to_lab(colour)
        return (
            f"lab({_round(lightness, 4)} {_round(a_axis, 4)} "
            f"{_round(b_axis, 4)} / {_round(alpha, 4)})"
        )
    if key == "lch":
        lightness, chroma, hue = to_lch(colour)
        return (
            f"lch({_round(lightness, 4)} {_round(chroma, 4)} "
            f"{_round(hue, 4)} / {_round(alpha, 4)})"
        )
    if key == "oklab":
        lightness, a_axis, b_axis = to_oklab(colour)
        return (
            f"oklab({_round(lightness, 6)} {_round(a_axis, 6)} "
            f"{_round(b_axis, 6)} / {_round(alpha, 4)})"
        )
    if key == "oklch":
        lightness, chroma, hue = to_oklch(colour)
        return (
            f"oklch({_round(lightness, 6)} {_round(chroma, 6)} "
            f"{_round(hue, 4)} / {_round(alpha, 4)})"
        )
    if key == "cmyk":
        cyan, magenta, yellow, black = to_cmyk(colour)
        return (
            f"device-cmyk({_round(cyan * 100, 4)}% {_round(magenta * 100, 4)}% "
            f"{_round(yellow * 100, 4)}% {_round(black * 100, 4)}% / "
            f"{_round(alpha, 4)})"
        )
    raise ColourError(f"{representation!r} is not a representation this module writes.")


def translate(colour: Colour) -> Dict[str, str]:
    """Return ``colour`` written in every representation, keyed by name."""
    return {key: format_as(colour, key) for key in REPRESENTATIONS}


# ---------------------------------------------------------------------------
# gamut, compositing, contrast
# ---------------------------------------------------------------------------


def gamut(colour: Colour) -> GamutReport:
    """Report whether sRGB can show ``colour``, and what clipping would cost."""
    excursions: List[Tuple[str, float, float]] = []
    worst = 0.0
    for name, value in (
        ("red", colour.red),
        ("green", colour.green),
        ("blue", colour.blue),
    ):
        if value < -_EPSILON or value > 1.0 + _EPSILON:
            clipped_value = _clamp(value)
            excursions.append((name, value, clipped_value))
            worst = max(worst, abs(value - clipped_value))
    if not excursions:
        return GamutReport(
            colour.space,
            True,
            (),
            0.0,
            f"Inside the sRGB gamut · authored in {colour.space}",
        )
    names = ", ".join(name for name, _value, _clipped in excursions)
    return GamutReport(
        colour.space,
        False,
        tuple(excursions),
        worst,
        (
            f"Outside the sRGB gamut · {names} would be clipped by up to "
            f"{worst * 255:.1f}/255. This display cannot show the colour as "
            f"written in {colour.space}; the swatch shows the clipped value."
        ),
    )


def clipped(colour: Colour) -> Colour:
    """Return ``colour`` forced inside sRGB, keeping its alpha and its space."""
    return replace(
        colour,
        red=_clamp(colour.red),
        green=_clamp(colour.green),
        blue=_clamp(colour.blue),
    )


def composite(top: Colour, bottom: Colour) -> Colour:
    """Return ``top`` drawn over ``bottom``, source-over, in sRGB.

    Contrast against a translucent ink is meaningless until the ink has been
    composited, so this runs first and the reading is taken from the result.
    """
    top_alpha = _clamp(top.alpha)
    bottom_alpha = _clamp(bottom.alpha)
    out_alpha = top_alpha + bottom_alpha * (1.0 - top_alpha)
    if out_alpha <= 0:
        return Colour(0.0, 0.0, 0.0, 0.0, top.space)

    def mix(top_value: float, bottom_value: float) -> float:
        return (
            _clamp(top_value) * top_alpha
            + _clamp(bottom_value) * bottom_alpha * (1.0 - top_alpha)
        ) / out_alpha

    return Colour(
        mix(top.red, bottom.red),
        mix(top.green, bottom.green),
        mix(top.blue, bottom.blue),
        out_alpha,
        top.space,
    )


def relative_luminance(colour: Colour) -> float:
    """Return the WCAG 2 relative luminance of a colour, clipped to sRGB."""
    red = _to_linear(_clamp(colour.red))
    green = _to_linear(_clamp(colour.green))
    blue = _to_linear(_clamp(colour.blue))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: Colour, background: Colour) -> float:
    """Return the WCAG 2 contrast ratio between an ink and a surface, 1 to 21."""
    effective = composite(foreground, background)
    lighter = max(relative_luminance(effective), relative_luminance(background))
    darker = min(relative_luminance(effective), relative_luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


def contrast_report(foreground: Colour, background: Colour) -> ContrastReport:
    """Return the contrast reading and which WCAG thresholds it clears."""
    effective = composite(foreground, background)
    ratio = contrast_ratio(foreground, background)
    aa_normal = ratio >= 4.5
    aa_large = ratio >= 3.0
    aaa_normal = ratio >= 7.0
    aaa_large = ratio >= 4.5
    if aaa_normal:
        verdict = "clears AAA at every size"
    elif aa_normal:
        verdict = "clears AA at every size and AAA at large sizes"
    elif aa_large:
        verdict = "clears AA only at large sizes"
    else:
        verdict = "clears no WCAG threshold"
    return ContrastReport(
        ratio,
        effective,
        background,
        aa_normal,
        aa_large,
        aaa_normal,
        aaa_large,
        f"{ratio:.2f}:1 · {verdict}",
    )


def round_trip(colour: Colour) -> Dict[str, Tuple[str, str, str]]:
    """Write ``colour`` in every representation and read each one back.

    Returns ``{representation: (written, read back as HEX8, verdict)}`` where
    the verdict is one of:

    ``exact``
        the colour and its alpha both survived the trip;
    ``opaque``
        the colour survived and the alpha did not, because the notation has no
        way to say it -- ``hex``, ``rgb`` and ``hsl``, each of which is offered
        beside a twin that does carry alpha;
    ``absent``
        the notation had nothing to write, which only happens for ``name``
        when no CSS keyword matches exactly;
    ``lost``
        a genuine failure, and the reason is in the second field.

    It lives beside the conversions rather than in a test file so a
    verification run, the suite, and anything else that wants the guarantee all
    exercise the same :func:`format_as` and :func:`parse` pair the picker
    renders with, rather than a second copy that can drift from it.
    """
    reference = format_as(clipped(colour), "hex8")
    opaque_reference = format_as(clipped(colour).with_alpha(1.0), "hex8")
    results: Dict[str, Tuple[str, str, str]] = {}
    for key in REPRESENTATIONS:
        written = format_as(colour, key)
        if not written:
            results[key] = ("", "", "absent")
            continue
        try:
            recovered = format_as(clipped(parse(written)), "hex8")
        except ColourError as error:
            results[key] = (written, f"unreadable: {error}", "lost")
            continue
        if recovered == reference:
            verdict = "exact"
        elif key not in ALPHA_CARRYING and recovered == opaque_reference:
            verdict = "opaque"
        else:
            verdict = "lost"
        results[key] = (written, recovered, verdict)
    return results
