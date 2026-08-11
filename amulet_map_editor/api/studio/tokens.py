"""Colour, density, type, spacing, and shape tokens for the Amulet Studio shell.

Every Studio surface resolves its appearance through this module so a theme,
accent, density, or scale change lands in one place rather than in each painted
control.  The palette is recomputed on demand instead of being captured at
import time: theme, accent, and density can all change while the application is
running -- through the settings surfaces and through scheduled rules -- and a
token frozen at startup would quietly render the wrong appearance for the rest
of the session.

The module imports ``wx`` but constructs no window, dialog, or bitmap at import
time, so it stays importable in a headless environment.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
from pathlib import Path
import re
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api import config, preferences, scheduled_runtime, school_mode

log = logging.getLogger(__name__)

#: Every semantic colour role a Studio surface may ask for.  The names are the
#: contract other modules paint against; a surface that needs a new shade
#: blends an existing role rather than inventing a fourteenth.
ROLE_NAMES: Tuple[str, ...] = (
    "surface",
    "surface_container",
    "surface_container_high",
    "on_surface",
    "on_surface_variant",
    "outline",
    "outline_variant",
    "primary",
    "on_primary",
    "primary_container",
    "on_primary_container",
    "error",
    "scrim",
    "tint",
)

# The two palettes are the design's own values.  ``scrim`` and ``tint`` are
# translucent in the design, so each role carries its alpha alongside the hex.
LIGHT_ROLES: Dict[str, Tuple[str, int]] = {
    "surface": ("#F7FAF9", 255),
    "surface_container": ("#EDF3F2", 255),
    "surface_container_high": ("#E1EAE8", 255),
    "on_surface": ("#171D1C", 255),
    "on_surface_variant": ("#3F4948", 255),
    "outline": ("#6F7978", 255),
    "outline_variant": ("#BFC9C7", 255),
    "primary": ("#006A63", 255),
    "on_primary": ("#FFFFFF", 255),
    "primary_container": ("#A6F2E9", 255),
    "on_primary_container": ("#00504A", 255),
    "error": ("#BA1A1A", 255),
    "scrim": ("#0E1514", 128),
    "tint": ("#006A63", 15),
}

DARK_ROLES: Dict[str, Tuple[str, int]] = {
    "surface": ("#0E1514", 255),
    "surface_container": ("#182020", 255),
    "surface_container_high": ("#232C2B", 255),
    "on_surface": ("#DDE4E2", 255),
    "on_surface_variant": ("#BEC9C7", 255),
    "outline": ("#899391", 255),
    "outline_variant": ("#3F4948", 255),
    "primary": ("#82D5CC", 255),
    "on_primary": ("#003733", 255),
    "primary_container": ("#00504A", 255),
    "on_primary_container": ("#A6F2E9", 255),
    "error": ("#FFB4AB", 255),
    "scrim": ("#000000", 158),
    "tint": ("#82D5CC", 20),
}

#: Spacing scale, in device-independent pixels.  Pass these through
#: :func:`scaled` when a layout has to hold at a non-default interface scale.
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 16
SPACE_LG = 24
SPACE_XL = 32

#: Corner radii.  ``RADIUS_PILL`` is deliberately larger than any control it can
#: be applied to; the drawing helpers clamp it to half the shorter edge.
RADIUS_SM = 8
RADIUS_MD = 12
RADIUS_LG = 16
RADIUS_PILL = 999

#: Control heights per density, before the interface scale is applied.
DENSITY_HEIGHTS: Dict[str, int] = {"compact": 32, "comfortable": 36, "spacious": 44}

#: Interface faces in preference order.  IBM Plex is the design's family; the
#: rest are the platform faces most likely to be installed, ending with faces
#: that carry Traditional Chinese so bilingual copy still renders when nothing
#: earlier is present.  Nothing is ever downloaded.
UI_FONT_CANDIDATES: Tuple[str, ...] = (
    "IBM Plex Sans",
    "Segoe UI Variable Text",
    "Segoe UI",
    "Inter",
    "Noto Sans",
    "DejaVu Sans",
    "Helvetica Neue",
    "Arial",
    "Microsoft JhengHei UI",
    "Noto Sans CJK TC",
    "PingFang TC",
)

#: Where a packaging step or a user drops the design's own font files.  The
#: directory ships empty with a README beside it; nothing here is downloaded,
#: and an empty directory is the normal case rather than a failure.
BUNDLED_FONT_DIR: Path = Path(__file__).resolve().parent.parent / "image" / "fonts"

#: The file kinds :func:`wx.Font.AddPrivateFont` accepts.
BUNDLED_FONT_EXTENSIONS: Tuple[str, ...] = (".ttf", ".otf")

#: Monospaced faces for coordinates, identifiers, tags, and hashes.
MONO_FONT_CANDIDATES: Tuple[str, ...] = (
    "IBM Plex Mono",
    "Cascadia Mono",
    "Cascadia Code",
    "Consolas",
    "JetBrains Mono",
    "Menlo",
    "DejaVu Sans Mono",
    "Liberation Mono",
    "Courier New",
)

#: The smallest point size the shell will render.  Scaling below this makes
#: labels unreadable long before it makes a layout fit.
MIN_POINT_SIZE = 8

#: The accent value a profile carries when the user has never chosen one.  A
#: profile still sitting on it is treated as "no accent chosen", so a fresh
#: install shows the Studio palette rather than the generic seed colour.
DEFAULT_ACCENT = preferences.Preferences().accent

_HEX_COLOUR = re.compile(r"^#?(?P<value>[0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?$")

_theme_listeners: List[Callable[[], None]] = []
_face_cache: Optional[frozenset] = None
_bundled_fonts: Optional["BundledFonts"] = None

#: (config generation, monotonic time read, resolved presentation) the last
#: time :func:`_presentation` actually asked ``preferences``/``school_mode``
#: for an answer.  Every public token function resolves the presentation
#: fresh -- ``palette()``, ``font()``, ``scaled()``, ``control_height()``,
#: ``density()``, and ``emoji()`` each call :func:`_presentation` on their
#: own -- so one repaint that asks for a dozen tokens was doing a dozen
#: ``Preferences(...).normalised()`` builds (plus, underneath, a dozen
#: ``config.get`` calls apiece for the two identifiers) to answer what is,
#: within one paint, always the same question.
_presentation_cache: Optional[Tuple[int, float, "preferences.Preferences"]] = None


def _invalidate_presentation() -> None:
    """Drop the cached presentation so the next call resolves it fresh."""
    global _presentation_cache
    _presentation_cache = None


@dataclass(frozen=True)
class StudioPalette:
    """One resolved appearance: every colour role plus the theme it came from.

    Resolve it once per paint and pass it down.  Reading a role is free; asking
    for a new palette re-reads the persisted preferences from disk.
    """

    surface: wx.Colour
    surface_container: wx.Colour
    surface_container_high: wx.Colour
    on_surface: wx.Colour
    on_surface_variant: wx.Colour
    outline: wx.Colour
    outline_variant: wx.Colour
    primary: wx.Colour
    on_primary: wx.Colour
    primary_container: wx.Colour
    on_primary_container: wx.Colour
    error: wx.Colour
    scrim: wx.Colour
    tint: wx.Colour
    dark: bool = False

    def role(self, name: str) -> wx.Colour:
        """Return a role by name, falling back to ``surface`` for a typo.

        Data-driven surfaces (specs, ribbon definitions) name their roles as
        strings; a missing role should paint something legible rather than
        raise in the middle of a paint handler.
        """
        return getattr(self, name, self.surface)


def _colour(hex_value: str, alpha: int = 255) -> wx.Colour:
    """Build a colour from a ``#RRGGBB`` string and an explicit alpha."""
    match = _HEX_COLOUR.match(hex_value.strip())
    if match is None:
        raise ValueError(f"Not a six-digit hex colour: {hex_value!r}")
    value = match.group("value")
    return wx.Colour(
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
        max(0, min(255, int(alpha))),
    )


def _palette_from(roles: Dict[str, Tuple[str, int]], dark: bool) -> StudioPalette:
    """Build a palette from one of the two design colour tables."""
    return StudioPalette(
        **{name: _colour(*roles[name]) for name in ROLE_NAMES}, dark=dark
    )


#: The shipped palettes, unreseeded.  ``palette()`` starts from one of these.
LIGHT: StudioPalette = _palette_from(LIGHT_ROLES, dark=False)
DARK: StudioPalette = _palette_from(DARK_ROLES, dark=True)


def blend(a: wx.Colour, b: wx.Colour, weight: float) -> wx.Colour:
    """Mix ``b`` into ``a`` by ``weight`` (0 keeps ``a``, 1 returns ``b``).

    Alpha follows the same mix, so blending a translucent role keeps it
    translucent instead of silently turning it opaque.
    """
    ratio = min(1.0, max(0.0, float(weight)))
    return wx.Colour(
        round(a.Red() * (1 - ratio) + b.Red() * ratio),
        round(a.Green() * (1 - ratio) + b.Green() * ratio),
        round(a.Blue() * (1 - ratio) + b.Blue() * ratio),
        round(a.Alpha() * (1 - ratio) + b.Alpha() * ratio),
    )


def on_colour(background: wx.Colour) -> wx.Colour:
    """Pick readable ink for a generated container.

    The weighting and threshold match the shared Material 3 helper so a
    generated container reads the same in the Studio shell and in the legacy
    native pages; only the dark ink differs, because the Studio palette's ink
    is its own near-black.
    """
    luminance = (
        299 * background.Red() + 587 * background.Green() + 114 * background.Blue()
    ) / 1000
    return _colour("#171D1C") if luminance >= 150 else _colour("#FFFFFF")


def _presentation() -> preferences.Preferences:
    """Load preferences projected through School mode.

    A malformed or unreadable profile must not stop the shell painting, so the
    shipped defaults stand in and the failure is logged once per call site.

    Resolving this is more than the two cached ``config.get`` calls
    underneath it: it also builds and validates a :class:`preferences.Preferences`
    instance, and every public token function calls this on its own, so one
    paint that resolves a dozen tokens repeats that build a dozen times.  The
    answer is cached for the same window :mod:`config` already promises a
    profile write is visible within, so this can never be staler than reading
    ``preferences``/``school_mode`` directly would be.  A write *this process*
    makes is visible at once regardless of the window, because
    ``config.generation()`` changes the moment :func:`config.put` runs --
    :func:`preferences.save` and every ``school_mode`` setter go through it --
    which is what keeps a settings change from painting with a stale
    palette for up to a quarter of a second after the user made it.
    """
    global _presentation_cache
    generation = config.generation()
    now = time.monotonic()
    if _presentation_cache is not None:
        cached_generation, cached_at, cached_value = _presentation_cache
        if cached_generation == generation and now - cached_at < config.CACHE_SECONDS:
            return cached_value
    try:
        value = school_mode.presentation_preferences(preferences.load())
    except (OSError, AttributeError, TypeError, ValueError):
        log.exception("Could not read appearance preferences; using shipped defaults")
        value = preferences.Preferences().normalised()
    _presentation_cache = (generation, now, value)
    return value


def _runtime_value(key: str, fallback: str) -> str:
    """Read a scheduled override, falling back to the persisted preference."""
    try:
        value = scheduled_runtime.current_values().get(key, fallback)
    except (AttributeError, TypeError, ValueError):
        log.exception("Could not read scheduled appearance values")
        return fallback
    return str(value) if value else fallback


def _system_is_dark() -> bool:
    """Ask the platform whether it is currently in a dark appearance.

    ``wx.SystemSettings.GetAppearance`` arrived in wxPython 4.1 and is absent
    on some builds, so the call is discovered rather than assumed; anything
    unanswerable means light, which is the shipped default.
    """
    appearance_getter = getattr(wx.SystemSettings, "GetAppearance", None)
    if appearance_getter is None:
        return False
    try:
        appearance = appearance_getter()
        is_dark_getter = getattr(appearance, "IsDark", None)
        return bool(is_dark_getter()) if callable(is_dark_getter) else False
    except Exception:  # pragma: no cover - platform boundary
        log.debug("System appearance unavailable; assuming a light theme")
        return False


def _resolve_theme(theme: str) -> str:
    """Resolve ``light``/``dark``/``system`` into one of the two palettes."""
    if theme == "dark":
        return "dark"
    if theme == "light":
        return "light"
    return "dark" if _system_is_dark() else "light"


def _parse_accent(accent: str) -> Optional[wx.Colour]:
    """Parse a chosen accent, or ``None`` when it is absent or unusable.

    A profile still carrying the shipped default counts as "no accent chosen":
    reseeding from it would hide the Studio palette on every fresh install,
    which is the one appearance the design actually specifies.
    """
    value = str(accent or "").strip()
    if not value or value.lower() == DEFAULT_ACCENT.strip().lower():
        return None
    match = _HEX_COLOUR.match(value)
    if match is None:
        return None
    try:
        return _colour(match.group("value"))
    except ValueError:
        return None


@lru_cache(maxsize=16)
def _build_palette(theme: str, accent: str) -> StudioPalette:
    """Build the resolved palette for one theme and accent pair.

    Cached because the arithmetic is pure and every painted control asks for
    it; the inputs are already resolved strings, so a preference change
    produces a different key rather than a stale result.
    """
    dark = theme == "dark"
    base = DARK if dark else LIGHT
    seed = _parse_accent(accent)
    if seed is None:
        return base
    primary = seed
    container = blend(primary, base.surface_container, 0.65 if dark else 0.82)
    # The accent seeds the whole primary family, not one button colour: the
    # container, both readable inks, and the surface tint all follow it, so a
    # chosen accent never leaves half the shell on the shipped teal.
    return StudioPalette(
        surface=base.surface,
        surface_container=base.surface_container,
        surface_container_high=base.surface_container_high,
        on_surface=base.on_surface,
        on_surface_variant=base.on_surface_variant,
        outline=base.outline,
        outline_variant=base.outline_variant,
        primary=primary,
        on_primary=on_colour(primary),
        primary_container=container,
        on_primary_container=on_colour(container),
        error=base.error,
        scrim=base.scrim,
        tint=wx.Colour(
            primary.Red(), primary.Green(), primary.Blue(), base.tint.Alpha()
        ),
        dark=dark,
    )


def palette() -> StudioPalette:
    """Resolve the live palette from preferences and scheduled overrides."""
    prefs = _presentation()
    theme = _resolve_theme(_runtime_value("theme", prefs.theme))
    accent = _runtime_value("accent", prefs.accent)
    return _build_palette(theme, accent)


def is_dark() -> bool:
    """Return whether the shell is currently painting the dark palette."""
    return _resolve_theme(_runtime_value("theme", _presentation().theme)) == "dark"


def _density_of(prefs: preferences.Preferences) -> str:
    """Return the live density name for preferences already in hand.

    Split out so a caller that has resolved the presentation is not made to
    resolve it a second time; :func:`density` is the same question asked
    without one.
    """
    value = _runtime_value("density", prefs.density)
    return value if value in DENSITY_HEIGHTS else "comfortable"


def density() -> str:
    """Return the live density name, honouring a scheduled override."""
    return _density_of(_presentation())


def control_height() -> int:
    """Return the minimum height every interactive control must reach.

    Touch targets are a completion requirement, so this is the floor a control
    sets rather than a hint: compact 32, comfortable 36, spacious 44, each
    multiplied by the persisted interface scale.
    """
    prefs = _presentation()
    base = DENSITY_HEIGHTS.get(_density_of(prefs), DENSITY_HEIGHTS["comfortable"])
    return max(1, round(base * prefs.ui_scale * _dpi_factor))


#: The display scale the interface is currently drawing for, as a multiple of
#: the 96 DPI baseline every pixel constant in this module is written against.
#: Cached because :func:`scaled` is called thousands of times per repaint and
#: asking the toolkit each time would put a system call inside a paint loop.
_dpi_factor: float = 1.0


def dpi_factor() -> float:
    """Return the display scale the pixel constants are being drawn at."""
    return _dpi_factor


def refresh_dpi(window: "Optional[wx.Window]" = None) -> float:
    """Re-read the display scale and return it.

    Call this when a top-level window is created and again whenever the toolkit
    reports a DPI change -- a window dragged from a laptop panel to an external
    monitor crosses a scale boundary without any resize the application would
    otherwise notice.
    """
    global _dpi_factor
    factor = 1.0
    try:
        if window is not None:
            factor = float(window.GetDPIScaleFactor())
        else:
            # No window yet: ask the screen. This path runs once at startup,
            # so the cost of a ScreenDC does not matter here.
            factor = wx.ScreenDC().GetPPI().height / 96.0
    except (AttributeError, RuntimeError, ZeroDivisionError):
        log.debug("Could not read the display scale", exc_info=True)
        return _dpi_factor
    # A nonsensical reading is worse than the previous one: a zero would
    # collapse every size in the interface to a single pixel.
    if not 0.25 <= factor <= 8.0:
        return _dpi_factor
    _dpi_factor = factor
    return _dpi_factor


def scaled(value: int) -> int:
    """Scale a spacing or size token to the display, then by the user's choice.

    Two multipliers, and they answer different questions.  The display scale
    turns a constant written for a 96 DPI screen into the right *physical* size
    on whatever panel this is -- without it, declaring DPI awareness would
    simply swap an interface that was too big for one that is too small.  The
    persisted interface scale is then the user's own adjustment on top, for
    whom the correct physical size is still not the comfortable one.

    Font point sizes deliberately do NOT get the display multiplier: a point is
    a physical unit, and the toolkit already converts it using the real device
    DPI once the process is DPI-aware.  Applying it in both places is the
    doubled scaling this whole change exists to remove.
    """
    prefs = _presentation()
    return max(1, round(float(value) * prefs.ui_scale * _dpi_factor))


@dataclass(frozen=True)
class BundledFonts:
    """What one attempt to load the bundled font files actually achieved.

    Every field is a fact rather than an intention, because the About surface
    and the documentation both report this and an optimistic summary would
    claim the design's typography is present when it is not.
    """

    #: File names found in :data:`BUNDLED_FONT_DIR`, sorted.
    found: Tuple[str, ...] = ()
    #: The subset wx accepted as private faces.
    loaded: Tuple[str, ...] = ()
    #: Whether this build exposes ``wx.Font.AddPrivateFont`` at all.
    supported: bool = True
    #: A short reason the directory could not be read, or "" when it could.
    error: str = ""


def _wx_version() -> str:
    """Return the wxPython version string, or a placeholder if it is unreadable."""
    try:
        return str(wx.version())
    except Exception:  # pragma: no cover - platform boundary
        return "an unknown wxPython build"


def _bundled_font_files() -> Tuple[List[Path], str]:
    """List the font files in the bundled directory and any read failure.

    A missing directory is the shipped state, not an error: the repository
    carries the directory's README and nothing else, so an installation with no
    supplied faces reports an empty list rather than a fault.
    """
    try:
        if not BUNDLED_FONT_DIR.is_dir():
            return [], ""
        files = sorted(
            path
            for path in BUNDLED_FONT_DIR.iterdir()
            if path.is_file() and path.suffix.lower() in BUNDLED_FONT_EXTENSIONS
        )
    except OSError as error:
        return [], str(error)
    return files, ""


def load_bundled_fonts() -> BundledFonts:
    """Register every bundled font file as a private face, once per process.

    Private faces have to be registered before the faces are enumerated, or the
    enumerator will not see them and :func:`font` will resolve a substitute.
    The result is cached for the life of the process because a private face
    cannot be unregistered; :func:`reset_caches` deliberately leaves it alone so
    a theme change does not register the same files again on every repaint.
    """
    global _bundled_fonts
    if _bundled_fonts is not None:
        return _bundled_fonts
    files, error = _bundled_font_files()
    if error:
        log.warning("Could not read the bundled font directory: %s", error)
        _bundled_fonts = BundledFonts(error=error)
        return _bundled_fonts
    if not files:
        _bundled_fonts = BundledFonts()
        return _bundled_fonts
    add_private_font = getattr(wx.Font, "AddPrivateFont", None)
    if not callable(add_private_font):
        log.info(
            "%s has no private font support, so the %s in %s cannot be used",
            _wx_version(),
            _file_count(len(files)),
            BUNDLED_FONT_DIR,
        )
        _bundled_fonts = BundledFonts(
            found=tuple(path.name for path in files), supported=False
        )
        return _bundled_fonts
    loaded: List[str] = []
    for path in files:
        try:
            accepted = bool(add_private_font(str(path)))
        except Exception:  # pragma: no cover - platform boundary
            log.exception("Loading the bundled font file %s failed", path.name)
            continue
        if accepted:
            loaded.append(path.name)
        else:
            log.warning("wx would not load the bundled font file %s", path.name)
    _bundled_fonts = BundledFonts(
        found=tuple(path.name for path in files), loaded=tuple(loaded)
    )
    return _bundled_fonts


def _file_count(count: int) -> str:
    """Return "1 font file" or "N font files"."""
    return "1 font file" if count == 1 else f"{count} font files"


def _face_count(count: int) -> str:
    """Return "a private face" or "private faces"."""
    return "a private face" if count == 1 else "private faces"


def bundled_font_status() -> str:
    """Return an honest one-line summary of the bundled typography.

    The design's type identity is IBM Plex Sans and IBM Plex Mono, and on a
    machine carrying neither the shell renders something else entirely.  The
    About surface and the documentation state this string verbatim so a reader
    learns which faces are actually on screen rather than which ones the design
    asked for.
    """
    state = load_bundled_fonts()
    interface = _resolve_face(UI_FONT_CANDIDATES, _presentation().ui_font)
    monospaced = _resolve_face(MONO_FONT_CANDIDATES)
    using = (
        f"Rendering with {interface or 'the system interface face'} and "
        f"{monospaced or 'the system monospaced face'}."
    )
    if state.error:
        return f"The bundled font directory could not be read ({state.error}). {using}"
    if not state.found:
        return f"No bundled font files in {BUNDLED_FONT_DIR}. {using}"
    if not state.supported:
        return (
            f"{_file_count(len(state.found))} bundled, but {_wx_version()} cannot "
            f"load private faces. {using}"
        )
    if not state.loaded:
        return (
            f"{_file_count(len(state.found))} bundled, none of which wx would "
            f"load. {using}"
        )
    if len(state.loaded) < len(state.found):
        return (
            f"{len(state.loaded)} of {_file_count(len(state.found))} loaded as "
            f"{_face_count(len(state.loaded))}. {using}"
        )
    return (
        f"{_file_count(len(state.loaded))} loaded as "
        f"{_face_count(len(state.loaded))}. {using}"
    )


def _available_faces() -> frozenset:
    """Return the installed face names, cached once they can be enumerated.

    Enumeration needs a live wx application; an empty result is not cached so
    the first call made from a real window still finds the design's faces.  The
    bundled private faces are registered first, because a face the enumerator
    has not been told about is a face :func:`_resolve_face` will skip.
    """
    global _face_cache
    if _face_cache:
        return _face_cache
    load_bundled_fonts()
    try:
        faces = frozenset(wx.FontEnumerator.GetFacenames())
    except Exception:  # pragma: no cover - platform boundary
        log.debug("Font enumeration unavailable; keeping the system face")
        return frozenset()
    if faces:
        _face_cache = faces
    return faces


def _resolve_face(candidates: Sequence[str], preferred: str = "") -> str:
    """Choose the first installed face, or "" to keep the system face.

    A face the user chose wins outright.  When enumeration is unavailable the
    result is empty rather than a guess, because naming a missing face silently
    substitutes an arbitrary one on some platforms.
    """
    faces = _available_faces()
    if preferred and (not faces or preferred in faces):
        return preferred
    for candidate in candidates:
        if candidate in faces:
            return candidate
    return ""


@lru_cache(maxsize=256)
def _build_font(
    base_description: str,
    point_size: int,
    weight: int,
    mono: bool,
    ui_scale: float,
    ui_font: str,
    faces_known: bool,
) -> wx.Font:
    """Build one font from a fully resolved description of what it must be.

    Every argument is something that changes the answer, which is what makes
    this cacheable: the base font arrives as its own native description rather
    than as a live window, so two windows sharing the system face share one
    entry.  ``faces_known`` is in the key because :func:`_available_faces`
    cannot enumerate before there is a wx application, and a font resolved
    while the enumerator was empty must not be handed out once the design's
    faces have been registered.
    """
    base = wx.Font()
    base.SetNativeFontInfo(base_description)
    result = wx.Font(base)
    result.SetPointSize(max(MIN_POINT_SIZE, round(point_size * ui_scale)))
    result.SetWeight(weight)
    if mono:
        # The family is set first and the face second, and the order matters:
        # setting the family afterwards replaces the resolved face with the
        # platform's generic one, so a chosen monospaced face would be quietly
        # thrown away.  The family stands in only when no candidate face is
        # installed, which still yields a monospaced font rather than a
        # proportional one.
        result.SetFamily(wx.FONTFAMILY_TELETYPE)
        face = _resolve_face(MONO_FONT_CANDIDATES)
    else:
        face = _resolve_face(UI_FONT_CANDIDATES, ui_font)
    if face:
        result.SetFaceName(face)
    return result


def font(
    window: Optional[wx.Window],
    point_size: int,
    weight: int = wx.FONTWEIGHT_NORMAL,
    mono: bool = False,
) -> wx.Font:
    """Return the interface font at a point size, scaled and weighted.

    ``preferences.ui_font`` overrides the interface family when the user has
    chosen one; it never overrides the monospaced family, because a coordinate
    or an identifier stops being readable the moment its columns stop lining
    up.

    Building the font is cached, because a text-bearing control asks for one
    every time it paints and constructing it measured at 126us -- six fonts for
    a single row of the recent-worlds table.  The cache is keyed on everything
    that changes the result, so a new scale, a new chosen face, or a window
    with its own font all produce a different entry rather than a stale font.
    """
    prefs = _presentation()
    base = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
    if window is not None:
        try:
            current = window.GetFont()
            if current.IsOk():
                base = current
        except RuntimeError:  # pragma: no cover - window torn down mid-paint
            pass
    built = _build_font(
        base.GetNativeFontInfoDesc(),
        int(point_size),
        int(weight),
        bool(mono),
        float(prefs.ui_scale),
        str(prefs.ui_font or ""),
        bool(_available_faces()),
    )
    # Handed out as a copy, because reading the answer out of a cache must not
    # change what a caller may do with it: the uncached version returned a
    # fresh font every time, and something that mutated one would otherwise be
    # editing every later caller's font too.
    return wx.Font(built)


def mono_font(
    window: Optional[wx.Window],
    point_size: int,
    weight: int = wx.FONTWEIGHT_NORMAL,
) -> wx.Font:
    """Return the monospaced font used for coordinates, ids, tags, and hashes."""
    return font(window, point_size, weight, mono=True)


def emoji(glyph: str) -> str:
    """Return a decorative glyph, or "" when the user has turned them off.

    School mode projects the same preference to off, so one check covers both
    and no surface has to ask about the mode separately.
    """
    if not glyph:
        return ""
    return str(glyph) if _presentation().show_dialog_emojis else ""


def _graphics_context(dc: wx.DC) -> Optional[wx.GraphicsContext]:
    """Return a graphics context for ``dc``, or ``None`` on a backend without one."""
    if isinstance(dc, wx.GCDC):
        try:
            return dc.GetGraphicsContext()
        except RuntimeError:  # pragma: no cover - platform boundary
            return None
    try:
        context = wx.GraphicsContext.Create(dc)
    except Exception:  # pragma: no cover - platform boundary
        return None
    return context if context is not None and context.IsOk() else None


def draw_round_rect(
    dc: wx.DC,
    rect: wx.Rect,
    radius: int,
    fill: Optional[wx.Colour] = None,
    border: Optional[wx.Colour] = None,
    border_width: int = 1,
) -> None:
    """Paint a rounded rectangle, antialiased where the backend allows it.

    Every Studio shape goes through here so corner radii stay consistent and a
    backend without a graphics context still draws the shape rather than
    nothing at all.
    """
    rect = wx.Rect(rect)
    if rect.width <= 0 or rect.height <= 0:
        return
    corner = max(0, min(int(radius), min(rect.width, rect.height) // 2))
    context = _graphics_context(dc)
    if context is not None:
        context.SetBrush(wx.Brush(fill) if fill is not None else wx.TRANSPARENT_BRUSH)
        if border is not None:
            context.SetPen(wx.Pen(border, max(1, int(border_width))))
            inset = max(1, int(border_width)) / 2.0
            context.DrawRoundedRectangle(
                rect.x + inset,
                rect.y + inset,
                max(0.0, rect.width - inset * 2),
                max(0.0, rect.height - inset * 2),
                corner,
            )
        else:
            context.SetPen(wx.TRANSPARENT_PEN)
            context.DrawRoundedRectangle(
                rect.x, rect.y, rect.width, rect.height, corner
            )
        return
    dc.SetBrush(wx.Brush(fill) if fill is not None else wx.TRANSPARENT_BRUSH)
    dc.SetPen(
        wx.Pen(border, max(1, int(border_width)))
        if border is not None
        else wx.TRANSPARENT_PEN
    )
    dc.DrawRoundedRectangle(rect, corner)
    dc.SetBrush(wx.NullBrush)
    dc.SetPen(wx.NullPen)


# Offset, spread, and peak opacity per elevation level, matching the design's
# three shadow tokens.  Dark surfaces need a deeper shadow to read at all.
_ELEVATION_LIGHT: Dict[int, Tuple[int, int, float]] = {
    1: (1, 3, 0.16),
    2: (4, 12, 0.20),
    3: (10, 24, 0.34),
}
_ELEVATION_DARK: Dict[int, Tuple[int, int, float]] = {
    1: (1, 3, 0.50),
    2: (6, 16, 0.55),
    3: (14, 30, 0.68),
}
_ELEVATION_STEPS = 6


def draw_elevation(
    dc: wx.DC,
    rect: wx.Rect,
    radius: int,
    level: int,
    dark: Optional[bool] = None,
) -> None:
    """Paint a soft shadow underneath ``rect`` before its surface is drawn.

    The shadow is approximated with concentric translucent rounded rectangles
    because wx has no blur primitive; six overlapping rings read as a gradient
    at every elevation the design uses.  Pass ``dark`` when the caller already
    holds a palette -- resolving the theme again costs a preferences read on
    every paint.
    """
    level = min(3, int(level))
    if level <= 0:
        return
    rect = wx.Rect(rect)
    if rect.width <= 0 or rect.height <= 0:
        return
    context = _graphics_context(dc)
    theme_is_dark = is_dark() if dark is None else bool(dark)
    offset, spread, peak = (_ELEVATION_DARK if theme_is_dark else _ELEVATION_LIGHT)[
        level
    ]
    if context is None:
        # No alpha available: a single hairline under the bottom edge still
        # separates the surface from what is behind it.
        edge = DARK.outline if theme_is_dark else LIGHT.outline_variant
        dc.SetPen(wx.Pen(edge))
        dc.DrawLine(
            rect.x + radius,
            rect.y + rect.height,
            rect.x + rect.width - radius,
            rect.y + rect.height,
        )
        dc.SetPen(wx.NullPen)
        return
    base = (0, 0, 0) if theme_is_dark else (14, 21, 20)
    alpha = max(1, round(peak / _ELEVATION_STEPS * 255))
    context.SetPen(wx.TRANSPARENT_PEN)
    context.SetBrush(wx.Brush(wx.Colour(base[0], base[1], base[2], alpha)))
    for step in range(_ELEVATION_STEPS, 0, -1):
        grow = spread * step / _ELEVATION_STEPS
        drop = offset * step / _ELEVATION_STEPS
        context.DrawRoundedRectangle(
            rect.x - grow,
            rect.y - grow + drop,
            rect.width + grow * 2,
            rect.height + grow * 2,
            max(0.0, radius + grow),
        )


def elevation_tint(
    backdrop: wx.Colour, level: int, dark: Optional[bool] = None
) -> wx.Colour:
    """Return the colour :func:`draw_elevation` leaves *under* its own surface.

    The shadow is drawn as six translucent rounded rectangles grown outwards
    from the lifted rectangle, so every one of them also covers the rectangle's
    interior: an opaque surface painted on top hides that, and a translucent
    one -- a scrim -- does not.  Two surfaces at the same elevation therefore
    only match if both account for it, which is why this is a function rather
    than a number somebody copies.

    ``backdrop`` is what is behind the shadow.  The answer is what a control
    sitting on that surface must clear itself to.
    """
    level = min(3, int(level))
    if level <= 0:
        return wx.Colour(backdrop)
    theme_is_dark = is_dark() if dark is None else bool(dark)
    _offset, _spread, peak = (_ELEVATION_DARK if theme_is_dark else _ELEVATION_LIGHT)[
        level
    ]
    alpha = max(1, round(peak / _ELEVATION_STEPS * 255)) / 255.0
    # Six layers of the same translucent ink, each over the last.
    coverage = 1.0 - (1.0 - alpha) ** _ELEVATION_STEPS
    base = (0, 0, 0) if theme_is_dark else (14, 21, 20)
    return blend(backdrop, wx.Colour(base[0], base[1], base[2], 255), coverage)


def register_theme_listener(listener: Callable[[], None]) -> Callable[[], None]:
    """Register a repaint callback and return its own unregister callable.

    The shell calls every listener when the appearance changes so open windows
    repaint together; without this a dialog opened before a theme switch keeps
    the old palette until it is closed and reopened.
    """
    if not callable(listener):
        raise TypeError("A theme listener must be callable.")
    if listener not in _theme_listeners:
        _theme_listeners.append(listener)
    return lambda: unregister_theme_listener(listener)


def unregister_theme_listener(listener: Callable[[], None]) -> None:
    """Drop a previously registered repaint callback; unknown ones are ignored."""
    try:
        _theme_listeners.remove(listener)
    except ValueError:
        pass


def theme_listener_count() -> int:
    """Return how many repaint callbacks are registered (used by tests)."""
    return len(_theme_listeners)


def reset_caches() -> None:
    """Drop the derived palette, presentation, and installed-face caches.

    The bundled private faces are deliberately left registered: wx offers no
    way to unregister one, and a theme change calls this on every switch, so
    clearing that state would re-register the same files for the life of the
    session.  The next enumeration still sees them.

    ``_build_font``'s cache is also deliberately left alone: its key already
    carries every input that changes the answer (scale, chosen face, weight,
    the caller's own base font), so a stale entry cannot be served -- a
    changed input is a changed key, not a hit -- and clearing it here would
    only throw away fonts that are still correct.
    """
    global _face_cache
    _build_palette.cache_clear()
    _face_cache = None
    _invalidate_presentation()


def notify_theme_changed() -> None:
    """Invalidate the caches and ask every open surface to repaint.

    A listener bound to a window that wx has already destroyed raises rather
    than returning, so it is dropped here instead of breaking the repaint of
    every surface after it.
    """
    reset_caches()
    for listener in tuple(_theme_listeners):
        try:
            listener()
        except RuntimeError as error:
            if "deleted" in str(error):
                unregister_theme_listener(listener)
                continue
            log.exception("A theme listener failed; continuing with the rest")
        except Exception:
            log.exception("A theme listener failed; continuing with the rest")


__all__ = [
    "BUNDLED_FONT_DIR",
    "BUNDLED_FONT_EXTENSIONS",
    "BundledFonts",
    "DARK",
    "DARK_ROLES",
    "DEFAULT_ACCENT",
    "DENSITY_HEIGHTS",
    "LIGHT",
    "LIGHT_ROLES",
    "MIN_POINT_SIZE",
    "MONO_FONT_CANDIDATES",
    "RADIUS_LG",
    "RADIUS_MD",
    "RADIUS_PILL",
    "RADIUS_SM",
    "ROLE_NAMES",
    "SPACE_LG",
    "SPACE_MD",
    "SPACE_SM",
    "SPACE_XL",
    "SPACE_XS",
    "StudioPalette",
    "UI_FONT_CANDIDATES",
    "blend",
    "bundled_font_status",
    "control_height",
    "density",
    "draw_elevation",
    "draw_round_rect",
    "emoji",
    "font",
    "is_dark",
    "load_bundled_fonts",
    "mono_font",
    "notify_theme_changed",
    "on_colour",
    "palette",
    "register_theme_listener",
    "reset_caches",
    "scaled",
    "theme_listener_count",
    "unregister_theme_listener",
]
