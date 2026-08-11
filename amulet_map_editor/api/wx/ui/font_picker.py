"""The typography editor every font control in the application opens.

A font picker that offers a family and a size is not a font picker, it is a
family and a size.  This one goes to word-processor depth: every installed and
bundled face, searchable, each name drawn in its own typeface; size as both a
stepper and free entry; weight; italic and oblique; underline with its own
style and colour; single and double strikethrough; overline; capitalisation and
small caps; superscript and subscript; text colour and highlight; character and
word spacing; line height; baseline offset; and the variable-font axes a face
actually exposes, read from the font file rather than guessed at.

The part that matters most is what happens to a property this backend cannot
apply.  It **stays on screen**, keeps its value, and says plainly why -- because
the alternative is an editor that quietly drops what it was given, and the user
finds out later, from the rendering, that half of what they set never existed.
Each property is therefore labelled with one of three levels:

``applied``
    this backend puts it into the real ``wx.Font`` (or the control's own
    colour), so every control using this font shows it;
``drawn``
    ``wx.Font`` has no field for it, so :func:`draw_styled_text` draws it and
    the Studio owner-drawn surfaces show it -- a native control given only the
    font will not;
``recorded``
    nothing in this backend can apply it at all.  The value is kept and shown,
    and the explanation says what would be needed.

Exactly one property is ``recorded`` today, and it is named honestly rather
than hidden: wxPython exposes no way to set a variable-font axis, so the axes
are read, listed with their real ranges, and stored -- and the picker says the
rendering will use the face's default instance until a backend can set them.
"""

from __future__ import annotations

import logging
import os
import struct
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api import colour as colour_api
from amulet_map_editor.api.studio import tokens, widgets
from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.wx.ui.colour_picker import (
    Note,
    PaintedControl,
    Surface,
    open_colour_picker,
)

log = logging.getLogger(__name__)

__all__ = [
    "Axis",
    "FaceList",
    "FontPickerDialog",
    "FontStyle",
    "PROPERTIES",
    "Property",
    "StylePreview",
    "apply_to_font",
    "axes_for_face",
    "capability_notes",
    "cjk_fallback_face",
    "draw_styled_text",
    "face_names",
    "open_font_picker",
    "scan_report",
    "variable_axes",
]

#: wxPython 4.1 added a medium weight; older builds fall back to normal.
_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL)

#: The weights the picker offers, and the ``wx`` constant each maps to.
WEIGHTS: Tuple[Tuple[str, int], ...] = (
    ("Thin", getattr(wx, "FONTWEIGHT_THIN", wx.FONTWEIGHT_LIGHT)),
    ("Extra light", getattr(wx, "FONTWEIGHT_EXTRALIGHT", wx.FONTWEIGHT_LIGHT)),
    ("Light", wx.FONTWEIGHT_LIGHT),
    ("Normal", wx.FONTWEIGHT_NORMAL),
    ("Medium", _MEDIUM),
    ("Semi-bold", getattr(wx, "FONTWEIGHT_SEMIBOLD", wx.FONTWEIGHT_BOLD)),
    ("Bold", wx.FONTWEIGHT_BOLD),
    ("Extra bold", getattr(wx, "FONTWEIGHT_EXTRABOLD", wx.FONTWEIGHT_BOLD)),
    ("Heavy", getattr(wx, "FONTWEIGHT_HEAVY", wx.FONTWEIGHT_BOLD)),
)

SLANTS: Tuple[str, ...] = ("Normal", "Italic", "Oblique")
UNDERLINE_STYLES: Tuple[str, ...] = ("Solid", "Double", "Dotted", "Dashed", "Wavy")
STRIKETHROUGHS: Tuple[str, ...] = ("None", "Single", "Double")
CAPITALISATIONS: Tuple[str, ...] = ("As typed", "UPPERCASE", "lowercase", "Capitalise")
BASELINES: Tuple[str, ...] = ("Normal", "Superscript", "Subscript")

#: The sample the preview and the face list draw.  It carries Latin, digits,
#: and Traditional Chinese deliberately: a face with no CJK coverage is exactly
#: the case the fallback note exists to explain, and a sample that never asks
#: for a CJK glyph would never reveal it.
SAMPLE_TEXT = "Amulet Studio · Ag 123 · 世界地圖"

#: Faces most likely to carry Traditional Chinese, in preference order.  The
#: shell's own token module keeps the same tail on its interface-face list, so
#: the picker names the family the application would really substitute rather
#: than a plausible-sounding one.
CJK_FALLBACK_CANDIDATES: Tuple[str, ...] = (
    "Microsoft JhengHei UI",
    "Microsoft JhengHei",
    "Noto Sans CJK TC",
    "Noto Sans TC",
    "PingFang TC",
    "MingLiU",
    "SimSun",
)


@dataclass(frozen=True)
class Property:
    """One editable typography property and what this backend does with it."""

    key: str
    label: str
    #: ``applied``, ``drawn``, or ``recorded`` -- see the module docstring.
    level: str
    explanation: str


#: The hand-written property inventory.  It is hand-written on purpose: a rule
#: like "every property carries a capability note" is satisfied by a file with
#: no properties in it, so a list is what makes a control that quietly lost its
#: explanation a failure rather than a silence.  Adding a control means adding
#: a line here in the same change.
PROPERTIES: Tuple[Property, ...] = (
    Property("face", "Typeface", "applied", "Set on the wx.Font as its face name."),
    Property("size", "Size", "applied", "Set on the wx.Font as its point size."),
    Property("weight", "Weight", "applied", "Set on the wx.Font as its weight."),
    Property(
        "slant",
        "Slant",
        "applied",
        "Italic and oblique are both real wx.Font styles, but wxWidgets renders "
        "oblique as italic on Windows, so the two look identical on this platform.",
    ),
    Property(
        "underline", "Underline", "applied", "Set on the wx.Font as its underline flag."
    ),
    Property(
        "underline_style",
        "Underline style",
        "drawn",
        "wx.Font carries underline as a single on/off flag with no style, so "
        "double, dotted, dashed, and wavy are drawn by this shell's text renderer. "
        "A native control given only the font shows a plain solid underline.",
    ),
    Property(
        "underline_colour",
        "Underline colour",
        "drawn",
        "wx.Font has no underline colour; the line is drawn separately, so it is "
        "coloured on Studio surfaces and takes the text colour on native ones.",
    ),
    Property(
        "strikethrough",
        "Strikethrough",
        "drawn",
        "Single strikethrough is a real wx.Font flag and is applied; the double "
        "rule has no font field, so both rules are drawn together to keep the two "
        "settings looking like one control rather than two that disagree.",
    ),
    Property(
        "overline",
        "Overline",
        "drawn",
        "wx.Font has no overline. The rule is drawn above the ascender.",
    ),
    Property(
        "capitalisation",
        "Capitalisation",
        "drawn",
        "A text transform rather than a font property: the drawn text is "
        "re-cased, and the value the control holds is never changed.",
    ),
    Property(
        "small_caps",
        "Small caps",
        "drawn",
        "This backend has no access to a face's real small-cap glyphs, so lower "
        "case is drawn as capitals at eighty per cent of the size. It is a "
        "simulation and it is labelled as one.",
    ),
    Property(
        "baseline",
        "Superscript and subscript",
        "drawn",
        "Drawn by shifting the baseline and reducing the size; wx.Font has no "
        "position field.",
    ),
    Property(
        "text_colour",
        "Text colour",
        "applied",
        "Applied as the control's foreground colour and as the drawn text colour.",
    ),
    Property(
        "highlight_colour",
        "Highlight",
        "drawn",
        "Painted behind the text. A control's own background is a separate "
        "setting, so this is drawn rather than applied to it.",
    ),
    Property(
        "letter_spacing",
        "Character spacing",
        "drawn",
        "wx.Font has no tracking field; the text is drawn character by character "
        "with the extra advance added.",
    ),
    Property(
        "word_spacing",
        "Word spacing",
        "drawn",
        "Extra advance is added at each space when the text is drawn.",
    ),
    Property(
        "line_height",
        "Line height",
        "drawn",
        "A paragraph property rather than a font one; it is applied when this "
        "shell lays out drawn text.",
    ),
    Property(
        "baseline_offset",
        "Baseline offset",
        "drawn",
        "Shifts the drawn baseline. wx.Font has nowhere to record it.",
    ),
    Property(
        "axes",
        "Variable font axes",
        "recorded",
        "wxPython exposes no way to set a variation axis, so the values are read "
        "from the font file, listed with their real ranges, and stored -- and the "
        "rendering uses the face's default instance until a backend can set them. "
        "Nothing here silently discards what you choose.",
    ),
)

PROPERTY_BY_KEY: Dict[str, Property] = {item.key: item for item in PROPERTIES}


@dataclass(frozen=True)
class Axis:
    """One variable-font axis, read from the font file's ``fvar`` table."""

    tag: str
    name: str
    minimum: float
    default: float
    maximum: float


@dataclass
class FontStyle:
    """Every property the picker edits, whatever this backend can do with it."""

    face: str = ""
    size: float = 14.0
    weight: str = "Normal"
    slant: str = "Normal"
    underline: bool = False
    underline_style: str = "Solid"
    underline_colour: str = ""
    strikethrough: str = "None"
    overline: bool = False
    capitalisation: str = "As typed"
    small_caps: bool = False
    baseline: str = "Normal"
    text_colour: str = ""
    highlight_colour: str = ""
    letter_spacing: float = 0.0
    word_spacing: float = 0.0
    line_height: float = 1.25
    baseline_offset: float = 0.0
    #: Chosen axis values, keyed by four-character axis tag.
    axes: Dict[str, float] = field(default_factory=dict)

    def normalised(self) -> "FontStyle":
        """Return the style with every value inside the range its control allows."""
        weights = [name for name, _value in WEIGHTS]
        return replace(
            self,
            face=str(self.face or ""),
            size=max(4.0, min(200.0, float(self.size or 14.0))),
            weight=self.weight if self.weight in weights else "Normal",
            slant=self.slant if self.slant in SLANTS else "Normal",
            underline=bool(self.underline),
            underline_style=(
                self.underline_style
                if self.underline_style in UNDERLINE_STYLES
                else "Solid"
            ),
            strikethrough=(
                self.strikethrough if self.strikethrough in STRIKETHROUGHS else "None"
            ),
            overline=bool(self.overline),
            capitalisation=(
                self.capitalisation
                if self.capitalisation in CAPITALISATIONS
                else "As typed"
            ),
            small_caps=bool(self.small_caps),
            baseline=self.baseline if self.baseline in BASELINES else "Normal",
            letter_spacing=max(-10.0, min(40.0, float(self.letter_spacing or 0.0))),
            word_spacing=max(-10.0, min(80.0, float(self.word_spacing or 0.0))),
            line_height=max(0.6, min(4.0, float(self.line_height or 1.25))),
            baseline_offset=max(-40.0, min(40.0, float(self.baseline_offset or 0.0))),
            axes=dict(self.axes),
        )


# ---------------------------------------------------------------------------
# faces
# ---------------------------------------------------------------------------


def installed_faces() -> Tuple[str, ...]:
    """Return every face the platform reports, sorted and de-duplicated."""
    try:
        enumerator = wx.FontEnumerator()
        names = enumerator.GetFacenames()
    except Exception:  # pragma: no cover - platform boundary
        log.exception("The platform would not enumerate its installed faces")
        return ()
    return tuple(sorted({str(name) for name in names if str(name).strip()}))


def bundled_faces() -> Tuple[str, ...]:
    """Return the family names of the faces the application ships.

    ``tokens.load_bundled_fonts`` reports the *file names* it registered, which
    is not what a picker can offer: a face is chosen by family name, and a file
    called ``IBMPlexSans-Regular.ttf`` is the family ``IBM Plex Sans``.  The
    family is therefore read from each registered file's own ``name`` table
    rather than guessed from the file name.

    The bundled directory ships empty with a note beside it, so an empty result
    is the normal case rather than a failure -- and it is reported as such
    instead of being presented as a missing feature.
    """
    try:
        status = tokens.load_bundled_fonts()
    except Exception:  # pragma: no cover - defensive
        log.exception("Could not read the bundled font directory")
        return ()
    names: set = set()
    for file_name in getattr(status, "loaded", ()):
        path = tokens.BUNDLED_FONT_DIR / str(file_name)
        try:
            names.update(_family_names(path))
        except (OSError, struct.error, ValueError):
            log.debug("Could not read the family name of %s", file_name, exc_info=True)
    return tuple(sorted(name for name in names if name.strip()))


def face_names() -> Tuple[str, ...]:
    """Return every face the picker can offer: installed plus bundled."""
    return tuple(sorted(set(installed_faces()) | set(bundled_faces())))


def cjk_fallback_face() -> str:
    """Return the installed face this shell would substitute for CJK glyphs.

    wxPython exposes no glyph-coverage API, so the picker cannot say whether a
    given face carries 世界地圖.  What it *can* say honestly is which family the
    platform would fall back to, and that is what the note beside the sample
    reports rather than a claim about coverage nobody measured.
    """
    installed = set(installed_faces())
    for candidate in CJK_FALLBACK_CANDIDATES:
        if candidate in installed:
            return candidate
    return ""


# ---------------------------------------------------------------------------
# variable font axes, read from the font files themselves
# ---------------------------------------------------------------------------

#: Names for the registered axis tags, used when a font's own ``name`` table
#: does not carry one.  Anything not listed keeps its raw tag, which is still
#: the truth about the axis.
_REGISTERED_AXES: Dict[str, str] = {
    "wght": "Weight",
    "wdth": "Width",
    "opsz": "Optical size",
    "ital": "Italic",
    "slnt": "Slant",
    "GRAD": "Grade",
    "XOPQ": "Thick stroke",
    "YOPQ": "Thin stroke",
    "XTRA": "Counter width",
    "YTLC": "Lowercase height",
    "YTUC": "Uppercase height",
    "YTAS": "Ascender height",
    "YTDE": "Descender depth",
    "YTFI": "Figure height",
}


def _font_directories() -> Tuple[Path, ...]:
    """Return the directories searched for font files on this platform.

    Nothing is downloaded and nothing outside these is opened.
    """
    directories: List[Path] = [tokens.BUNDLED_FONT_DIR]
    if os.name == "nt":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        directories.append(Path(windir) / "Fonts")
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            directories.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":  # pragma: no cover - platform boundary
        home = Path.home()
        directories.extend(
            (
                Path("/System/Library/Fonts"),
                Path("/Library/Fonts"),
                home / "Library" / "Fonts",
            )
        )
    else:  # pragma: no cover - platform boundary
        home = Path.home()
        directories.extend(
            (
                Path("/usr/share/fonts"),
                Path("/usr/local/share/fonts"),
                home / ".fonts",
                home / ".local" / "share" / "fonts",
            )
        )
    return tuple(directories)


#: How many font files one scan will open.  A font directory is normally a few
#: hundred files; the bound is what keeps a pathological one from stalling the
#: window that asked.
MAX_FONT_FILES = 4000

_FONT_EXTENSIONS = (".ttf", ".otf", ".ttc", ".otc")

_axis_cache: Optional[Dict[str, Tuple[Axis, ...]]] = None
_scan_report: Dict[str, object] = {}


def _read_table_directory(handle, offset: int) -> Dict[str, Tuple[int, int]]:
    """Return ``{tag: (offset, length)}`` for one font inside a file."""
    handle.seek(offset)
    header = handle.read(12)
    if len(header) < 12:
        return {}
    table_count = struct.unpack_from(">H", header, 4)[0]
    if not 0 < table_count <= 512:
        return {}
    raw = handle.read(table_count * 16)
    tables: Dict[str, Tuple[int, int]] = {}
    for index in range(min(table_count, len(raw) // 16)):
        tag, _checksum, table_offset, length = struct.unpack_from(
            ">4sIII", raw, index * 16
        )
        try:
            tables[tag.decode("ascii")] = (table_offset, length)
        except UnicodeDecodeError:
            continue
    return tables


def _font_offsets(handle) -> Tuple[int, ...]:
    """Return the offset of each font in the file, handling collections."""
    handle.seek(0)
    tag = handle.read(4)
    if tag == b"ttcf":
        handle.seek(8)
        raw = handle.read(4)
        if len(raw) < 4:
            return ()
        count = struct.unpack(">I", raw)[0]
        count = min(count, 64)
        offsets = handle.read(count * 4)
        return tuple(
            struct.unpack_from(">I", offsets, index * 4)[0]
            for index in range(min(count, len(offsets) // 4))
        )
    return (0,)


def _read_names(handle, offset: int, length: int) -> Dict[int, str]:
    """Return the readable strings of a ``name`` table, keyed by name id."""
    if length < 6 or length > 1 << 20:
        return {}
    handle.seek(offset)
    raw = handle.read(length)
    if len(raw) < 6:
        return {}
    count, string_offset = struct.unpack_from(">HH", raw, 2)
    names: Dict[int, str] = {}
    windows: set = set()
    for index in range(min(count, 4096)):
        record = 6 + index * 12
        if record + 12 > len(raw):
            break
        platform, _encoding, _language, name_id, str_len, str_off = struct.unpack_from(
            ">6H", raw, record
        )
        start = string_offset + str_off
        chunk = raw[start : start + str_len]
        if not chunk:
            continue
        if platform == 3:
            try:
                text = chunk.decode("utf-16-be")
            except UnicodeDecodeError:
                continue
        elif platform == 1:
            try:
                text = chunk.decode("mac-roman")
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            continue
        text = text.replace("\x00", "").strip()
        if not text:
            continue
        # A Windows record wins over a Macintosh one for the same id, so a
        # family name never comes back in the wrong encoding's spelling.
        if name_id in names and name_id in windows and platform != 3:
            continue
        names[name_id] = text
        if platform == 3:
            windows.add(name_id)
    return names


def _read_axes(
    handle, offset: int, length: int, names: Dict[int, str]
) -> Tuple[Axis, ...]:
    """Return the axes of an ``fvar`` table."""
    if length < 16:
        return ()
    handle.seek(offset)
    header = handle.read(16)
    if len(header) < 16:
        return ()
    _major, _minor, axes_offset, _reserved, axis_count, axis_size = struct.unpack_from(
        ">6H", header, 0
    )
    if not 0 < axis_count <= 64 or axis_size < 20:
        return ()
    handle.seek(offset + axes_offset)
    raw = handle.read(axis_count * axis_size)
    axes: List[Axis] = []
    for index in range(axis_count):
        start = index * axis_size
        if start + 20 > len(raw):
            break
        tag, minimum, default, maximum, _flags, name_id = struct.unpack_from(
            ">4siiiHH", raw, start
        )
        try:
            tag_text = tag.decode("ascii")
        except UnicodeDecodeError:
            continue
        axes.append(
            Axis(
                tag_text,
                names.get(name_id) or _REGISTERED_AXES.get(tag_text, tag_text),
                minimum / 65536.0,
                default / 65536.0,
                maximum / 65536.0,
            )
        )
    return tuple(axes)


def _scan_file(path: Path) -> Dict[str, Tuple[Axis, ...]]:
    """Return ``{lowercased family or full name: axes}`` for one font file."""
    found: Dict[str, Tuple[Axis, ...]] = {}
    with path.open("rb") as handle:
        for offset in _font_offsets(handle):
            tables = _read_table_directory(handle, offset)
            fvar = tables.get("fvar")
            if fvar is None:
                continue
            name_table = tables.get("name")
            names = _read_names(handle, *name_table) if name_table else {}
            axes = _read_axes(handle, fvar[0], fvar[1], names)
            if not axes:
                continue
            for name_id in (16, 1, 4):
                label = names.get(name_id, "")
                if label:
                    found[label.lower()] = axes
    return found


def _family_names(path: Path) -> Tuple[str, ...]:
    """Return the family names declared inside one font file."""
    found: List[str] = []
    with path.open("rb") as handle:
        for offset in _font_offsets(handle):
            tables = _read_table_directory(handle, offset)
            name_table = tables.get("name")
            if name_table is None:
                continue
            names = _read_names(handle, *name_table)
            family = names.get(16) or names.get(1)
            if family:
                found.append(family)
    return tuple(dict.fromkeys(found))


def variable_axes(*, refresh: bool = False) -> Dict[str, Tuple[Axis, ...]]:
    """Return every variable family this host has, keyed by lowercased name.

    The axes come from each font file's own ``fvar`` table.  There is no other
    honest source: a list of "fonts that are usually variable" would be a guess
    about the reader's machine, and a picker that offered a Weight axis a face
    does not have would be offering a control that does nothing.
    """
    global _axis_cache, _scan_report
    if _axis_cache is not None and not refresh:
        return _axis_cache

    families: Dict[str, Tuple[Axis, ...]] = {}
    scanned = 0
    failed = 0
    directories: List[str] = []
    for directory in _font_directories():
        try:
            if not directory.is_dir():
                continue
        except OSError:  # pragma: no cover - unreadable mount
            continue
        directories.append(str(directory))
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            failed += 1
            continue
        for entry in entries:
            if scanned >= MAX_FONT_FILES:
                break
            if entry.suffix.lower() not in _FONT_EXTENSIONS:
                continue
            scanned += 1
            try:
                families.update(_scan_file(entry))
            except (OSError, struct.error, ValueError):
                failed += 1
                continue
    _axis_cache = families
    _scan_report = {
        "directories": tuple(directories),
        "files_scanned": scanned,
        "files_unreadable": failed,
        "variable_families": len(families),
    }
    return families


def scan_report() -> Dict[str, object]:
    """Return what the last axis scan actually did, for the note that shows it."""
    if _axis_cache is None:
        variable_axes()
    return dict(_scan_report)


def axes_for_face(face: str) -> Tuple[Axis, ...]:
    """Return the axes a face exposes, or an empty tuple when it exposes none.

    A face is looked up by its exact name and then by the family name with a
    trailing style word removed, because the platform enumerates
    ``"Segoe UI Variable Display"`` while the file's typographic family may be
    ``"Segoe UI Variable"``.
    """
    key = str(face or "").strip().lower()
    if not key:
        return ()
    families = variable_axes()
    if key in families:
        return families[key]
    words = key.split()
    while len(words) > 1:
        words.pop()
        candidate = " ".join(words)
        if candidate in families:
            return families[candidate]
    return ()


# ---------------------------------------------------------------------------
# applying a style
# ---------------------------------------------------------------------------


def apply_to_font(style: FontStyle, base: Optional[wx.Font] = None) -> wx.Font:
    """Return a ``wx.Font`` carrying every property this backend can express.

    What it cannot express is not silently dropped: :func:`capability_notes`
    reports it, the picker shows it, and :func:`draw_styled_text` draws the ones
    that can be drawn.
    """
    style = style.normalised()
    font = wx.Font(base) if base is not None else wx.Font(wx.FontInfo(10))
    size = max(4, min(200, round(style.size * 0.75)))
    font.SetPointSize(size)
    if style.face:
        font.SetFaceName(style.face)
    weights = dict(WEIGHTS)
    font.SetWeight(weights.get(style.weight, wx.FONTWEIGHT_NORMAL))
    font.SetStyle(
        {
            "Normal": wx.FONTSTYLE_NORMAL,
            "Italic": wx.FONTSTYLE_ITALIC,
            "Oblique": getattr(wx, "FONTSTYLE_SLANT", wx.FONTSTYLE_ITALIC),
        }.get(style.slant, wx.FONTSTYLE_NORMAL)
    )
    font.SetUnderlined(bool(style.underline))
    setter = getattr(font, "SetStrikethrough", None)
    if callable(setter):
        setter(style.strikethrough in ("Single", "Double"))
    return font


def capability_notes(style: FontStyle) -> Tuple[Tuple[Property, str], ...]:
    """Return every property with the value currently set on it.

    Every property appears, at every level, whether or not it is at its
    default: this is the list the picker renders under "What this backend can
    apply", and a list that hid the satisfied ones would leave the reader
    unable to tell a property that is fine from one that was never shown.
    """
    style = style.normalised()
    axes = ", ".join(f"{tag} {value:g}" for tag, value in sorted(style.axes.items()))
    readings: Dict[str, str] = {
        "face": style.face or "the platform default face",
        "size": f"{style.size:g} px",
        "weight": style.weight,
        "slant": style.slant,
        "underline": "on" if style.underline else "off",
        "underline_style": style.underline_style,
        "underline_colour": style.underline_colour or "same as the text",
        "strikethrough": style.strikethrough,
        "overline": "on" if style.overline else "off",
        "capitalisation": style.capitalisation,
        "small_caps": "on" if style.small_caps else "off",
        "baseline": style.baseline,
        "text_colour": style.text_colour or "the surface's own ink",
        "highlight_colour": style.highlight_colour or "none",
        "letter_spacing": f"{style.letter_spacing:g} px",
        "word_spacing": f"{style.word_spacing:g} px",
        "line_height": f"{style.line_height:g}×",
        "baseline_offset": f"{style.baseline_offset:g} px",
        "axes": axes or "none chosen",
    }
    return tuple((item, readings.get(item.key, "")) for item in PROPERTIES)


# ---------------------------------------------------------------------------
# drawing a style
# ---------------------------------------------------------------------------


def _transform(text: str, style: FontStyle) -> str:
    if style.capitalisation == "UPPERCASE":
        return text.upper()
    if style.capitalisation == "lowercase":
        return text.lower()
    if style.capitalisation == "Capitalise":
        return " ".join(word[:1].upper() + word[1:] for word in text.split(" "))
    return text


def _underline_pen(colour: wx.Colour, style_name: str, width: int) -> wx.Pen:
    pen = wx.Pen(colour, max(1, width))
    pen.SetStyle(
        {
            "Dotted": wx.PENSTYLE_DOT,
            "Dashed": wx.PENSTYLE_SHORT_DASH,
        }.get(style_name, wx.PENSTYLE_SOLID)
    )
    return pen


def _draw_wave(dc: wx.DC, x: int, y: int, width: int, colour: wx.Colour) -> None:
    """Draw the wavy underline the pen styles cannot express."""
    dc.SetPen(wx.Pen(colour, 1))
    step = 3
    up = True
    previous = (x, y)
    for position in range(x, x + width, step):
        point = (position, y - 2 if up else y + 2)
        dc.DrawLine(previous[0], previous[1], point[0], point[1])
        previous = point
        up = not up


def draw_styled_text(
    dc: wx.DC,
    rect: wx.Rect,
    text: str,
    style: FontStyle,
    *,
    ink: Optional[wx.Colour] = None,
) -> int:
    """Draw ``text`` in ``rect`` with everything this shell can render.

    Returns the height used.  The properties whose level is ``drawn`` are the
    ones implemented here -- underline style and colour, the double rule,
    overline, capitalisation, small caps, super and subscript, letter and word
    spacing, line height, baseline offset, and the highlight -- so a Studio
    surface shows the whole style while a native control given only the
    ``wx.Font`` shows the ``applied`` subset.  That difference is exactly what
    the capability list tells the user about.
    """
    style = style.normalised()
    palette = tokens.palette()
    text_colour = _parse_colour(style.text_colour, ink or palette.on_surface)
    highlight = _parse_colour(style.highlight_colour, None)
    underline_colour = _parse_colour(style.underline_colour, text_colour)

    font = apply_to_font(style)
    scale = {"Normal": 1.0, "Superscript": 0.66, "Subscript": 0.66}[style.baseline]
    if scale != 1.0:
        font = wx.Font(font)
        font.SetPointSize(max(4, round(font.GetPointSize() * scale)))
    dc.SetFont(font)
    line_height = max(1, round(dc.GetCharHeight() * style.line_height))
    shift = round(style.baseline_offset)
    if style.baseline == "Superscript":
        shift -= round(dc.GetCharHeight() * 0.28)
    elif style.baseline == "Subscript":
        shift += round(dc.GetCharHeight() * 0.20)

    y = rect.y
    for raw_line in _transform(str(text), style).split("\n"):
        top = y + shift
        width = _draw_line(
            dc, rect.x, top, raw_line, style, font, text_colour, highlight
        )
        height = dc.GetCharHeight()
        if style.underline:
            line_y = top + height - max(1, height // 8)
            if style.underline_style == "Wavy":
                _draw_wave(dc, rect.x, line_y, width, underline_colour)
            else:
                dc.SetPen(_underline_pen(underline_colour, style.underline_style, 1))
                dc.DrawLine(rect.x, line_y, rect.x + width, line_y)
                if style.underline_style == "Double":
                    dc.DrawLine(rect.x, line_y + 3, rect.x + width, line_y + 3)
        if style.strikethrough in ("Single", "Double"):
            middle = top + height // 2
            dc.SetPen(wx.Pen(text_colour, 1))
            dc.DrawLine(rect.x, middle, rect.x + width, middle)
            if style.strikethrough == "Double":
                dc.DrawLine(rect.x, middle - 3, rect.x + width, middle - 3)
        if style.overline:
            dc.SetPen(wx.Pen(text_colour, 1))
            dc.DrawLine(rect.x, top + 1, rect.x + width, top + 1)
        y += line_height
    return y - rect.y


def _draw_line(
    dc: wx.DC,
    x: int,
    y: int,
    text: str,
    style: FontStyle,
    font: wx.Font,
    ink: wx.Colour,
    highlight: Optional[wx.Colour],
) -> int:
    """Draw one line character by character and return the width it used."""
    tracking = round(style.letter_spacing)
    word_gap = round(style.word_spacing)
    small = wx.Font(font)
    small.SetPointSize(max(4, round(font.GetPointSize() * 0.8)))

    advance = 0
    positions: List[Tuple[str, int, bool]] = []
    for character in text:
        use_small = style.small_caps and character.islower()
        dc.SetFont(small if use_small else font)
        drawn = character.upper() if use_small else character
        positions.append((drawn, advance, use_small))
        advance += dc.GetTextExtent(drawn)[0] + tracking
        if character == " ":
            advance += word_gap
    width = max(0, advance - tracking)

    if highlight is not None:
        dc.SetFont(font)
        dc.SetBrush(wx.Brush(highlight))
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.DrawRectangle(x - 2, y, width + 4, dc.GetCharHeight())

    dc.SetTextForeground(ink)
    for drawn, offset, use_small in positions:
        dc.SetFont(small if use_small else font)
        dc.DrawText(drawn, x + offset, y)
    dc.SetFont(font)
    return width


def _parse_colour(value: str, fallback: Optional[wx.Colour]) -> Optional[wx.Colour]:
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        parsed = colour_api.parse(text)
    except colour_api.ColourError:
        return fallback
    red, green, blue = colour_api.to_rgb255(parsed)
    return wx.Colour(red, green, blue, round(max(0.0, min(1.0, parsed.alpha)) * 255))


# ---------------------------------------------------------------------------
# controls
# ---------------------------------------------------------------------------


class FaceList(PaintedControl):
    """Every face, each drawn in its own typeface, scrolled inside one control.

    One owner-drawn control rather than one window per face: a host with four
    hundred families would otherwise create four hundred windows, and a capture
    would have to composite every one of them.  It scrolls with the wheel, the
    arrow keys, Page Up and Page Down, Home and End, so it is fully operable
    without a pointer.
    """

    ROW_HEIGHT = 30
    VISIBLE_ROWS = 8

    def __init__(
        self,
        parent: wx.Window,
        faces: Sequence[str],
        *,
        on_select: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.faces: Tuple[str, ...] = tuple(faces)
        self.selected = self.faces[0] if self.faces else ""
        self.offset = 0
        self.on_select = on_select
        super().__init__(
            parent,
            "Typeface list",
            wx.Size(
                tokens.scaled(320), tokens.scaled(self.ROW_HEIGHT * self.VISIBLE_ROWS)
            ),
        )
        self._announce()
        self.Bind(wx.EVT_LEFT_DOWN, self._on_click)
        self.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)

    def set_faces(self, faces: Sequence[str]) -> None:
        """Replace the visible faces, keeping the selection when it survives."""
        self.faces = tuple(faces)
        if self.selected not in self.faces:
            self.selected = self.faces[0] if self.faces else ""
        self.offset = 0
        self._announce()
        self.Refresh()

    def select(self, face: str, *, notify: bool = True) -> None:
        """Select a face by name and scroll it into view."""
        if face not in self.faces:
            return
        self.selected = face
        index = self.faces.index(face)
        rows = max(1, self.GetClientSize().height // tokens.scaled(self.ROW_HEIGHT))
        if index < self.offset:
            self.offset = index
        elif index >= self.offset + rows:
            self.offset = index - rows + 1
        self._announce()
        self.Refresh()
        if notify:
            widgets.invoke(self.on_select, face)

    def _announce(self) -> None:
        self.SetName(
            f"Typeface list · {len(self.faces)} face(s) · "
            f"{self.selected or 'nothing'} selected"
        )

    def _row_at(self, y: int) -> int:
        return self.offset + max(0, y) // max(1, tokens.scaled(self.ROW_HEIGHT))

    def _on_click(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        index = self._row_at(event.GetPosition().y)
        if 0 <= index < len(self.faces):
            self.select(self.faces[index])

    def _on_wheel(self, event: wx.MouseEvent) -> None:
        rows = max(1, self.GetClientSize().height // tokens.scaled(self.ROW_HEIGHT))
        step = 3 if event.GetWheelRotation() < 0 else -3
        self.offset = max(0, min(max(0, len(self.faces) - rows), self.offset + step))
        self.Refresh()

    def _on_key(self, event: wx.KeyEvent) -> None:
        if not self.faces:
            event.Skip()
            return
        rows = max(1, self.GetClientSize().height // tokens.scaled(self.ROW_HEIGHT))
        index = self.faces.index(self.selected) if self.selected in self.faces else 0
        key = event.GetKeyCode()
        if key == wx.WXK_UP:
            index -= 1
        elif key == wx.WXK_DOWN:
            index += 1
        elif key == wx.WXK_PAGEUP:
            index -= rows
        elif key == wx.WXK_PAGEDOWN:
            index += rows
        elif key == wx.WXK_HOME:
            index = 0
        elif key == wx.WXK_END:
            index = len(self.faces) - 1
        else:
            event.Skip()
            return
        self.select(self.faces[max(0, min(len(self.faces) - 1, index))])

    def draw(self, dc: wx.DC, rect: wx.Rect) -> None:
        palette = self.palette()
        tokens.draw_round_rect(
            dc,
            rect,
            tokens.scaled(8),
            palette.surface_container,
            palette.outline_variant,
        )
        row_height = tokens.scaled(self.ROW_HEIGHT)
        rows = max(1, rect.height // row_height)
        if not self.faces:
            dc.SetFont(tokens.font(self, widgets.point_size(13)))
            dc.SetTextForeground(palette.on_surface_variant)
            dc.DrawText(
                "No face matches this search.",
                rect.x + tokens.scaled(12),
                rect.y + tokens.scaled(10),
            )
            return
        for row in range(rows):
            index = self.offset + row
            if index >= len(self.faces):
                break
            face = self.faces[index]
            top = rect.y + row * row_height
            row_rect = wx.Rect(
                rect.x + tokens.scaled(3),
                top + 1,
                rect.width - tokens.scaled(6),
                row_height - 2,
            )
            if face == self.selected:
                tokens.draw_round_rect(
                    dc, row_rect, tokens.scaled(6), palette.primary_container
                )
            ink = (
                palette.on_primary_container
                if face == self.selected
                else palette.on_surface
            )
            dc.SetTextForeground(ink)
            try:
                sample = wx.Font(
                    widgets.point_size(15),
                    wx.FONTFAMILY_DEFAULT,
                    wx.FONTSTYLE_NORMAL,
                    wx.FONTWEIGHT_NORMAL,
                    faceName=face,
                )
            except Exception:  # pragma: no cover - a face the platform refuses
                sample = tokens.font(self, widgets.point_size(15))
            dc.SetFont(sample)
            label = widgets.elide(
                dc, f"{face} — Ag 世", max(0, row_rect.width - tokens.scaled(16))
            )
            dc.DrawText(
                label,
                row_rect.x + tokens.scaled(8),
                top + max(0, (row_height - dc.GetCharHeight()) // 2),
            )
        if self.HasFocus():
            widgets.draw_focus_ring(dc, rect, tokens.scaled(8), palette.primary)


class StylePreview(PaintedControl):
    """The sample, drawn with every property this shell can render."""

    def __init__(self, parent: wx.Window, style: FontStyle) -> None:
        self.style = style
        super().__init__(
            parent, "Font preview", wx.Size(tokens.scaled(400), tokens.scaled(120))
        )

    def set_style(self, style: FontStyle) -> None:
        self.style = style
        self.SetName(
            "Font preview · "
            f"{style.face or 'default face'} {style.size:g}px {style.weight}"
        )
        self.Refresh()

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def draw(self, dc: wx.DC, rect: wx.Rect) -> None:
        palette = self.palette()
        tokens.draw_round_rect(
            dc,
            rect,
            tokens.scaled(10),
            palette.surface_container,
            palette.outline_variant,
        )
        inner = wx.Rect(
            rect.x + tokens.scaled(14),
            rect.y + tokens.scaled(12),
            max(0, rect.width - tokens.scaled(28)),
            max(0, rect.height - tokens.scaled(24)),
        )
        draw_styled_text(dc, inner, SAMPLE_TEXT, self.style, ink=palette.on_surface)


# ---------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------


class FontPickerDialog(wx.Dialog):
    """The typography editor, shown non-modally.

    ``on_apply`` receives the finished :class:`FontStyle` when the user
    confirms; nothing is called when they cancel.
    """

    def __init__(
        self,
        parent: wx.Window,
        style: Optional[FontStyle] = None,
        *,
        on_apply: Optional[Callable[[FontStyle], None]] = None,
        title: str = "Typography",
        subject: str = "Appearance",
    ) -> None:
        super().__init__(
            parent,
            title=title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            name=f"{subject}: {title}",
        )
        self.style = (style or FontStyle()).normalised()
        if not self.style.face:
            faces = face_names()
            self.style = replace(self.style, face=faces[0] if faces else "")
        self.original = replace(self.style, axes=dict(self.style.axes))
        self.on_apply = on_apply
        self._opener = wx.Window.FindFocus()
        self._focus_returned = False
        self.face_search = SearchState(label="Typefaces")
        self._theme_unsubscribe = tokens.register_theme_listener(self.refresh_theme)
        self.axis_controls: Dict[str, widgets.Stepper] = {}

        self.root = Surface(self)
        header = self._build_header()
        body = self._build_body()
        footer = self._build_footer()
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(header, 0, wx.EXPAND)
        layout.Add(body, 1, wx.EXPAND)
        layout.Add(footer, 0, wx.EXPAND)
        self.root.SetSizer(layout)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.root, 1, wx.EXPAND)
        self.SetSizer(outer)
        self.SetMinSize(wx.Size(tokens.scaled(720), tokens.scaled(640)))
        self.SetSize(wx.Size(tokens.scaled(780), tokens.scaled(820)))
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self._rebuild_axes()
        self._sync()

    # -- construction --------------------------------------------------------
    def _build_header(self) -> wx.Window:
        header = Surface(self.root, role="surface_container")
        self.eyebrow = Note(header, "Appearance", role="primary", size_px=11)
        self.title_label = Note(
            header, "Typography", role="on_surface", size_px=22, name="Typography"
        )
        close = widgets.StudioButton(
            header,
            "✕",
            variant="icon",
            on_click=self.cancel,
            name="Close the typography editor",
            hint="Close the typography editor",
            height=30,
            min_width=34,
        )
        titles = wx.BoxSizer(wx.VERTICAL)
        titles.Add(self.eyebrow, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(4))
        titles.Add(self.title_label, 0, wx.EXPAND)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(titles, 1, wx.ALIGN_CENTER_VERTICAL)
        row.Add(close, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, tokens.scaled(8))
        padded = wx.BoxSizer(wx.VERTICAL)
        padded.Add(row, 0, wx.EXPAND | wx.ALL, tokens.scaled(16))
        header.SetSizer(padded)
        return header

    def _section(self, sizer: wx.Sizer, title: str) -> None:
        sizer.Add(
            widgets.SectionLabel(self.body, title),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM,
            tokens.scaled(16),
        )

    #: How wide a property label is before its control.  Fixed rather than
    #: measured so every control in the window lines up in one column, which is
    #: what makes twenty settings scannable instead of a ragged list.
    LABEL_WIDTH = 190

    def _row(self, sizer: wx.Sizer, label: str, control: wx.Window) -> None:
        holder = wx.BoxSizer(wx.HORIZONTAL)
        holder.Add(
            Note(
                self.body,
                label,
                role="on_surface",
                size_px=13,
                width=self.LABEL_WIDTH,
                name=label or "Continued",
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            tokens.scaled(12),
        )
        holder.Add(control, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(holder, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, tokens.scaled(16))

    def _build_body(self) -> wx.Window:
        body = wx.ScrolledWindow(self.root, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        body.SetScrollRate(0, tokens.scaled(12))
        body.SetBackgroundColour(tokens.palette().surface)
        self.body = body
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.preview = StylePreview(body, self.style)
        sizer.Add(self.preview, 0, wx.EXPAND | wx.ALL, tokens.scaled(16))

        # -- typeface ---------------------------------------------------------
        self._section(sizer, "Typeface")
        self.face_bar = widgets.SearchBar(
            body, "Search typefaces", self.face_search, on_change=self._on_face_search
        )
        sizer.Add(
            self.face_bar,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )
        self.all_faces = face_names()
        self.face_list = FaceList(body, self.all_faces, on_select=self._on_face)
        if self.style.face in self.all_faces:
            self.face_list.select(self.style.face, notify=False)
        sizer.Add(
            self.face_list,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )
        bundled = bundled_faces()
        fallback = cjk_fallback_face()
        self.face_note = Note(
            body,
            f"{len(self.all_faces)} face(s): {len(installed_faces())} installed and "
            f"{len(bundled)} bundled with the application. "
            + (
                f"Characters a face does not carry are substituted by the platform; "
                f"this host would use {fallback}."
                if fallback
                else "No Traditional Chinese fallback face is installed on this host, "
                "so CJK characters may render as missing-glyph boxes."
            ),
            size_px=11,
        )
        sizer.Add(
            self.face_note,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )

        # -- size and weight --------------------------------------------------
        self._section(sizer, "Size and weight")
        self.size_stepper = widgets.Stepper(
            body, self.style.size, 4, 200, on_change=self._on_size, suffix="px"
        )
        self._row(sizer, "Size", self.size_stepper)
        self.size_field = widgets.OutlinedField(
            body,
            "Size, typed",
            f"{self.style.size:g}",
            placeholder="Any size from 4 to 200 pixels",
            on_change=self._on_size_typed,
        )
        self._row(sizer, "", self.size_field)
        self.weight_choice = widgets.SearchableChoice(
            body,
            "Weight",
            [name for name, _value in WEIGHTS],
            self.style.weight,
            on_change=self._on_weight,
        )
        self._row(sizer, "Weight", self.weight_choice)

        # -- slant, case, position -------------------------------------------
        self._section(sizer, "Slant, case, and position")
        self.slant_choice = widgets.SearchableChoice(
            body, "Slant", list(SLANTS), self.style.slant, on_change=self._on_slant
        )
        self._row(sizer, "Slant", self.slant_choice)
        self.caps_choice = widgets.SearchableChoice(
            body,
            "Capitalisation",
            list(CAPITALISATIONS),
            self.style.capitalisation,
            on_change=self._on_caps,
        )
        self._row(sizer, "Capitalisation", self.caps_choice)
        self.small_caps_switch = widgets.ToggleSwitch(
            body, self.style.small_caps, on_change=self._on_small_caps
        )
        self._row(sizer, "Small caps", self.small_caps_switch)
        self.baseline_choice = widgets.SearchableChoice(
            body,
            "Position",
            list(BASELINES),
            self.style.baseline,
            on_change=self._on_baseline,
        )
        self._row(sizer, "Superscript / subscript", self.baseline_choice)

        # -- rules -------------------------------------------------------------
        self._section(sizer, "Underline, strikethrough, and overline")
        self.underline_switch = widgets.ToggleSwitch(
            body, self.style.underline, on_change=self._on_underline
        )
        self._row(sizer, "Underline", self.underline_switch)
        self.underline_style_choice = widgets.SearchableChoice(
            body,
            "Underline style",
            list(UNDERLINE_STYLES),
            self.style.underline_style,
            on_change=self._on_underline_style,
        )
        self._row(sizer, "Underline style", self.underline_style_choice)
        self.underline_colour_button = self._colour_button(
            body, "underline_colour", "Underline colour"
        )
        self._row(sizer, "Underline colour", self.underline_colour_button)
        self.strike_choice = widgets.SearchableChoice(
            body,
            "Strikethrough",
            list(STRIKETHROUGHS),
            self.style.strikethrough,
            on_change=self._on_strike,
        )
        self._row(sizer, "Strikethrough", self.strike_choice)
        self.overline_switch = widgets.ToggleSwitch(
            body, self.style.overline, on_change=self._on_overline
        )
        self._row(sizer, "Overline", self.overline_switch)

        # -- colour ------------------------------------------------------------
        self._section(sizer, "Colour")
        self.text_colour_button = self._colour_button(
            body, "text_colour", "Text colour"
        )
        self._row(sizer, "Text colour", self.text_colour_button)
        self.highlight_button = self._colour_button(
            body, "highlight_colour", "Highlight"
        )
        self._row(sizer, "Highlight", self.highlight_button)

        # -- spacing -----------------------------------------------------------
        self._section(sizer, "Spacing")
        self.letter_stepper = widgets.Stepper(
            body,
            self.style.letter_spacing,
            -10,
            40,
            on_change=self._on_letter_spacing,
            suffix="px",
        )
        self._row(sizer, "Character spacing", self.letter_stepper)
        self.word_stepper = widgets.Stepper(
            body,
            self.style.word_spacing,
            -10,
            80,
            on_change=self._on_word_spacing,
            suffix="px",
        )
        self._row(sizer, "Word spacing", self.word_stepper)
        self.line_stepper = widgets.Stepper(
            body,
            round(self.style.line_height * 100),
            60,
            400,
            on_change=self._on_line_height,
            suffix="%",
        )
        self._row(sizer, "Line height", self.line_stepper)
        self.offset_stepper = widgets.Stepper(
            body,
            self.style.baseline_offset,
            -40,
            40,
            on_change=self._on_baseline_offset,
            suffix="px",
        )
        self._row(sizer, "Baseline offset", self.offset_stepper)

        # -- variable axes -----------------------------------------------------
        self._section(sizer, "Variable font axes")
        self.axes_holder = Surface(body)
        self.axes_sizer = wx.BoxSizer(wx.VERTICAL)
        self.axes_holder.SetSizer(self.axes_sizer)
        sizer.Add(
            self.axes_holder,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )
        self.axes_note = Note(body, "", size_px=11)
        sizer.Add(
            self.axes_note,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )

        # -- capability list ---------------------------------------------------
        self._section(sizer, "What this backend can apply")
        self.capability_notes_holder = Surface(body)
        self.capability_sizer = wx.BoxSizer(wx.VERTICAL)
        self.capability_labels: Dict[str, Note] = {}
        for item in PROPERTIES:
            note = Note(self.capability_notes_holder, "", size_px=11)
            self.capability_labels[item.key] = note
            self.capability_sizer.Add(note, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(6))
        self.capability_notes_holder.SetSizer(self.capability_sizer)
        sizer.Add(
            self.capability_notes_holder,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )

        body.SetSizer(sizer)
        return body

    def _colour_button(
        self, parent: wx.Window, key: str, label: str
    ) -> widgets.StudioButton:
        return widgets.StudioButton(
            parent,
            f"{label}…",
            variant="outlined",
            on_click=lambda name=key, text=label: self._choose_colour(name, text),
            name=f"Choose the {label.lower()}",
            hint=f"Open the colour picker for the {label.lower()}",
        )

    def _build_footer(self) -> wx.Window:
        footer = Surface(self.root, role="surface_container")
        reset = widgets.StudioButton(
            footer,
            "Reset",
            variant="text",
            on_click=self.reset,
            name="Reset to the style this opened with",
        )
        cancel = widgets.StudioButton(
            footer, "Cancel", variant="outlined", on_click=self.cancel, name="Cancel"
        )
        confirm = widgets.StudioButton(
            footer,
            "Use this font",
            variant="filled",
            on_click=self.confirm,
            name="Use this font",
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(reset, 0)
        row.AddStretchSpacer(1)
        row.Add(cancel, 0, wx.RIGHT, tokens.scaled(8))
        row.Add(confirm, 0)
        padded = wx.BoxSizer(wx.VERTICAL)
        padded.Add(row, 0, wx.EXPAND | wx.ALL, tokens.scaled(16))
        footer.SetSizer(padded)
        return footer

    # -- axes ----------------------------------------------------------------
    def _rebuild_axes(self) -> None:
        """Rebuild the axis controls for the selected face."""
        self.axes_sizer.Clear(True)
        self.axis_controls = {}
        axes = axes_for_face(self.style.face)
        for axis in axes:
            value = self.style.axes.get(axis.tag, axis.default)
            stepper = widgets.Stepper(
                self.axes_holder,
                value,
                axis.minimum,
                axis.maximum,
                on_change=lambda new, tag=axis.tag: self._on_axis(tag, new),
                suffix=axis.tag,
            )
            self.axis_controls[axis.tag] = stepper
            label = Note(
                self.axes_holder,
                f"{axis.name} ({axis.tag}) · {axis.minimum:g} to {axis.maximum:g}, "
                f"default {axis.default:g}",
                size_px=11,
            )
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(stepper, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, tokens.scaled(12))
            row.Add(label, 1, wx.ALIGN_CENTER_VERTICAL)
            self.axes_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(6))
        report = scan_report()
        capability = PROPERTY_BY_KEY["axes"].explanation
        if axes:
            self.axes_note.set_text(
                f"{self.style.face} exposes {len(axes)} axis/axes, read from its own "
                f"font file. Choosing a different typeface clears these values, "
                f"because another face's axes are not these axes. {capability}"
            )
        else:
            self.axes_note.set_text(
                f"{self.style.face or 'This face'} exposes no variable axes in the "
                f"{report.get('files_scanned', 0)} font file(s) scanned on this host, "
                f"of which {report.get('variable_families', 0)} family/families are "
                f"variable. {capability}"
            )
        self.axes_holder.Layout()

    # -- events --------------------------------------------------------------
    def _on_face_search(self, _state: SearchState) -> None:
        self.face_list.set_faces(
            [face for face in self.all_faces if self.face_search.matches(face)]
        )

    def _on_face(self, face: str) -> None:
        self.style = replace(self.style, face=face, axes={})
        self._rebuild_axes()
        self._sync()

    def _on_size(self, value: float) -> None:
        self.style = replace(self.style, size=float(value))
        self.size_field.set_value(f"{self.style.size:g}")
        self._sync()

    def _on_size_typed(self, text: str) -> None:
        try:
            value = float(str(text).strip())
        except ValueError:
            return
        self.style = replace(self.style, size=value).normalised()
        self.size_stepper.set_value(self.style.size, notify=False)
        self._sync()

    def _on_weight(self, value: str) -> None:
        self.style = replace(self.style, weight=value)
        self._sync()

    def _on_slant(self, value: str) -> None:
        self.style = replace(self.style, slant=value)
        self._sync()

    def _on_caps(self, value: str) -> None:
        self.style = replace(self.style, capitalisation=value)
        self._sync()

    def _on_small_caps(self, value: bool) -> None:
        self.style = replace(self.style, small_caps=bool(value))
        self._sync()

    def _on_baseline(self, value: str) -> None:
        self.style = replace(self.style, baseline=value)
        self._sync()

    def _on_underline(self, value: bool) -> None:
        self.style = replace(self.style, underline=bool(value))
        self._sync()

    def _on_underline_style(self, value: str) -> None:
        self.style = replace(self.style, underline_style=value)
        self._sync()

    def _on_strike(self, value: str) -> None:
        self.style = replace(self.style, strikethrough=value)
        self._sync()

    def _on_overline(self, value: bool) -> None:
        self.style = replace(self.style, overline=bool(value))
        self._sync()

    def _on_letter_spacing(self, value: float) -> None:
        self.style = replace(self.style, letter_spacing=float(value))
        self._sync()

    def _on_word_spacing(self, value: float) -> None:
        self.style = replace(self.style, word_spacing=float(value))
        self._sync()

    def _on_line_height(self, value: float) -> None:
        self.style = replace(self.style, line_height=float(value) / 100.0)
        self._sync()

    def _on_baseline_offset(self, value: float) -> None:
        self.style = replace(self.style, baseline_offset=float(value))
        self._sync()

    def _on_axis(self, tag: str, value: float) -> None:
        axes = dict(self.style.axes)
        axes[tag] = float(value)
        self.style = replace(self.style, axes=axes)
        self._sync()

    def _choose_colour(self, key: str, label: str) -> None:
        current = getattr(self.style, key) or "#000000FF"

        def apply(value: str) -> None:
            self.style = replace(self.style, **{key: value})
            self._sync()

        open_colour_picker(
            self, current, on_apply=apply, title=label, subject="Typography"
        )

    # -- state ---------------------------------------------------------------
    def _sync(self) -> None:
        self.style = self.style.normalised()
        self.preview.set_style(self.style)
        for item, reading in capability_notes(self.style):
            note = self.capability_labels.get(item.key)
            if note is None:
                continue
            note.set_text(
                f"{item.label} — {reading} · {item.level}: {item.explanation}",
                role="error" if item.level == "recorded" else "on_surface_variant",
            )
        self.body.Layout()
        self.body.FitInside()

    def refresh_theme(self) -> None:
        try:
            if self.IsBeingDeleted():
                return
            self.root.refresh_theme()
            self.body.SetBackgroundColour(tokens.palette().surface)
            for child in self.body.GetChildren():
                refresh = getattr(child, "refresh_theme", None)
                if callable(refresh):
                    refresh()
            self.Refresh()
        except RuntimeError:  # pragma: no cover - window already gone
            self._theme_unsubscribe = None

    # -- lifecycle -----------------------------------------------------------
    def reset(self) -> None:
        """Return every property to the value this window opened with."""
        self.style = replace(self.original, axes=dict(self.original.axes))
        self.size_stepper.set_value(self.style.size, notify=False)
        self.size_field.set_value(f"{self.style.size:g}")
        self.weight_choice.set_value(self.style.weight)
        self.slant_choice.set_value(self.style.slant)
        self.caps_choice.set_value(self.style.capitalisation)
        self.small_caps_switch.set_value(self.style.small_caps)
        self.baseline_choice.set_value(self.style.baseline)
        self.underline_switch.set_value(self.style.underline)
        self.underline_style_choice.set_value(self.style.underline_style)
        self.strike_choice.set_value(self.style.strikethrough)
        self.overline_switch.set_value(self.style.overline)
        self.letter_stepper.set_value(self.style.letter_spacing, notify=False)
        self.word_stepper.set_value(self.style.word_spacing, notify=False)
        self.line_stepper.set_value(round(self.style.line_height * 100), notify=False)
        self.offset_stepper.set_value(self.style.baseline_offset, notify=False)
        if self.style.face in self.all_faces:
            self.face_list.select(self.style.face, notify=False)
        self._rebuild_axes()
        self._sync()

    def confirm(self) -> None:
        """Hand the finished style back and close."""
        widgets.invoke(self.on_apply, self.style.normalised())
        self.close()

    def cancel(self) -> None:
        """Close without changing anything."""
        self.close()

    def close(self) -> None:
        self.Close()

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.cancel()
            return
        event.Skip()

    def _return_focus(self) -> None:
        if self._focus_returned:
            return
        self._focus_returned = True
        opener = self._opener
        if opener is None:
            return
        try:
            if opener and not opener.IsBeingDeleted():
                opener.SetFocus()
        except RuntimeError:  # pragma: no cover - the opener has gone
            pass

    def _on_close(self, event: wx.CloseEvent) -> None:
        if self._theme_unsubscribe is not None:
            self._theme_unsubscribe()
            self._theme_unsubscribe = None
        self._return_focus()
        event.Skip()
        self.Destroy()


def open_font_picker(
    parent: wx.Window,
    style: Optional[FontStyle] = None,
    *,
    on_apply: Optional[Callable[[FontStyle], None]] = None,
    title: str = "Typography",
    subject: str = "Appearance",
) -> FontPickerDialog:
    """Open the typography editor beside ``parent`` and return it.

    This is the entry point every font control in the application calls.  It is
    non-blocking: ``on_apply`` receives the finished :class:`FontStyle`, and
    nothing is called if the user cancels.
    """
    dialog = FontPickerDialog(
        parent, style, on_apply=on_apply, title=title, subject=subject
    )
    dialog.CentreOnParent()
    dialog.Show()
    return dialog
