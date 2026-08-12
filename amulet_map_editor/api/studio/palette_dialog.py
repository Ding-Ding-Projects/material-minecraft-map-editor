"""The Amulet Studio command palette: one search box over the whole product.

``Ctrl+Shift+F`` opens it from anywhere in the application and it answers with
three kinds of result, all in the same list:

* every **command** the shell can run, with its accelerator;
* every **surface** -- window, dialog, tool, and pane -- with the group it
  belongs to;
* every **individual setting** on every settings surface, rendered as its own
  live control so a switch can be flipped, a value stepped, a slider moved, an
  option chosen, a colour picked, or a string typed without leaving the palette.

Two things make it more than a launcher.  A setting changed here goes through
exactly the validation and persistence its own surface uses -- a real
preference is written with :func:`amulet_map_editor.api.preferences.update`, the
same normalising, bounded write the Options window performs -- and activating
any result **teleports**: the owning surface opens, the element is found,
scrolled into view, focused, and briefly ringed.

Teleporting is a protocol rather than a table of special cases.  A surface that
knows how to find its own elements implements ``reveal(element_key)`` and is
asked first; everything else is located by its accessible name, which every
Studio widget already sets.  Adding a surface therefore costs nothing here.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api import config, local_history, preferences
from amulet_map_editor.api.studio import copy as studio_copy
from amulet_map_editor.api.studio import tokens, widgets
from amulet_map_editor.api.studio.copy import studio_label, studio_text
from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.studio.title_bar import single_line

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# persisted palette state
# ---------------------------------------------------------------------------

#: Bounded config record holding the palette's own presentation choice.  It is
#: a separate record rather than a new field on the shared preferences schema,
#: which is deliberately small and versioned.
PALETTE_CONFIG_ID = "amulet_studio_palette"

#: The two presentations the palette offers.  ``card`` is the design's 660px
#: card and the shipped default; ``full`` fills the window for anyone who wants
#: to read many results at once.
LAYOUTS: Tuple[str, ...] = ("card", "full")
DEFAULT_LAYOUT = "card"

#: Bounded config record for settings that belong to a declarative surface.
#: Real application preferences never come through here -- they are written to
#: :mod:`amulet_map_editor.api.preferences` -- so this record only holds the
#: values declared by a :class:`~amulet_map_editor.api.studio.spec.Spec`, and
#: any surface rendering the same element reads its live value back through
#: :func:`setting_value` so the two can never disagree.
SETTING_STORE_ID = "amulet_studio_settings"
MAX_STORED_SETTINGS = 4096
MAX_SETTING_KEY_LENGTH = 200
MAX_SETTING_TEXT_LENGTH = 4096

#: Element keys are ``surface/section index/kind/item index``.  The surface part
#: is what :func:`teleport` opens; the rest is what :func:`reveal` looks for.
ELEMENT_KEY_SEPARATOR = "/"

#: The control kinds a setting result can render inline.
CONTROL_KINDS: Tuple[str, ...] = (
    "switch",
    "stepper",
    "slider",
    "select",
    "colour",
    "text",
)

#: An integer range no wider than this, stepping by one, reads better as a
#: stepper than as a slider in a single palette row.
STEPPER_MAX_SPAN = 24

#: How long the reveal ring stays around a teleported element, and how long the
#: palette waits for the surface to lay itself out before looking for it.
HIGHLIGHT_MS = 1200
REVEAL_DELAY_MS = 80

#: Result kinds, in the order they are offered when nothing has been typed.
RESULT_KINDS: Tuple[str, ...] = ("command", "surface", "setting")
_KIND_ORDER = {kind: index for index, kind in enumerate(RESULT_KINDS)}

#: Surfaces and preferences that School mode makes behave as if they were never
#: installed.  The mode's contract is omission, not disabling, so these never
#: reach the palette index at all while it is on.
SCHOOL_MODE_SURFACES: Tuple[str, ...] = ("dimsum", "languageSelect", "narrator")
SCHOOL_MODE_PREFERENCES: Tuple[str, ...] = (
    "language_mode",
    "funny_level_english",
    "funny_level_cantonese",
)
SCHOOL_MODE_TERMS: Tuple[str, ...] = (
    "cantonese",
    "bilingual",
    "funny",
    "dim sum",
    "dim-sum",
)

#: The accent the appearance surfaces accept: six or eight hexadecimal digits.
_ACCENT_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")

#: wxPython 4.1 added a medium weight; older builds fall back to normal.
_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL)


def palette_layout() -> str:
    """Return the persisted presentation: ``card`` or ``full``."""
    raw = config.get(PALETTE_CONFIG_ID, {})
    if not isinstance(raw, dict):
        return DEFAULT_LAYOUT
    value = str(raw.get("layout", DEFAULT_LAYOUT))
    return value if value in LAYOUTS else DEFAULT_LAYOUT


def set_palette_layout(layout: str) -> str:
    """Persist the palette's presentation and return what was stored."""
    value = str(layout) if str(layout) in LAYOUTS else DEFAULT_LAYOUT
    try:
        config.put(PALETTE_CONFIG_ID, {"layout": value})
    except OSError:
        log.exception("Could not persist the command palette layout")
    return value


#: The last read of the settings record.  Reading it means decompressing and
#: unpickling a file, and the palette asks for it once per rendered row on every
#: keystroke, so the answer is held until something writes it.
_settings_cache: Optional[Dict[str, Any]] = None


def _read_settings() -> Dict[str, Any]:
    """Read and bound the settings record from the profile."""
    raw = config.get(SETTING_STORE_ID, {})
    if not isinstance(raw, dict):
        return {}
    result: Dict[str, Any] = {}
    for key, value in list(raw.items())[:MAX_STORED_SETTINGS]:
        if not isinstance(key, str):
            continue
        if isinstance(value, bool) or isinstance(value, (int, float)):
            result[key[:MAX_SETTING_KEY_LENGTH]] = value
        elif isinstance(value, str):
            result[key[:MAX_SETTING_KEY_LENGTH]] = value[:MAX_SETTING_TEXT_LENGTH]
    return result


def invalidate_setting_cache() -> None:
    """Forget the cached settings record.

    Call this after writing the record by any route other than
    :func:`store_setting`, so the next read comes from disk rather than from a
    snapshot that is now behind the file.
    """
    global _settings_cache
    _settings_cache = None


def stored_settings() -> Dict[str, Any]:
    """Return every value the palette holds for a declarative surface."""
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = _read_settings()
    return dict(_settings_cache)


def setting_value(key: str, default: Any = None) -> Any:
    """Return the live value of one declarative setting, or its declared default.

    Surfaces read through this so the palette and the window that owns the
    setting cannot disagree about what the value currently is.
    """
    return stored_settings().get(str(key)[:MAX_SETTING_KEY_LENGTH], default)


def store_setting(key: str, value: Any) -> None:
    """Persist one declarative setting, refusing anything unbounded.

    Only booleans, numbers, and bounded strings are stored; a surface that needs
    richer state keeps it in its own record rather than growing this one into an
    untyped bag that nothing can validate.
    """
    element = str(key)[:MAX_SETTING_KEY_LENGTH]
    if not element:
        return
    if isinstance(value, bool) or isinstance(value, (int, float)):
        bounded: Any = value
    else:
        bounded = str(value)[:MAX_SETTING_TEXT_LENGTH]
    global _settings_cache
    values = stored_settings()
    values[element] = bounded
    if len(values) > MAX_STORED_SETTINGS:
        # Dictionaries keep insertion order, so the bound drops whatever was
        # written longest ago rather than an arbitrary member.
        values = dict(list(values.items())[-MAX_STORED_SETTINGS:])
    _settings_cache = values
    try:
        config.put(SETTING_STORE_ID, values)
    except OSError:
        # The value stays live for this session so the control the reader just
        # moved does not snap back, and the failure to persist is recorded
        # rather than presented as a successful write.
        log.exception("Could not persist the Studio setting %r", element)


# ---------------------------------------------------------------------------
# the result index
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PaletteResult:
    """One row of the palette: a command, a surface, or a single setting.

    ``label`` stays exactly as the owning surface spells it, because that is
    what :func:`reveal` matches against when it looks for the element by its
    accessible name.  ``cantonese`` carries the second language for the rows the
    Studio itself authors; a row transcribed from a surface description has none
    and simply renders the one it has.
    """

    kind: str
    key: str
    label: str
    group: str
    cantonese: str = ""
    accel: str = ""
    surface: str = ""
    control: str = ""
    options: Tuple[str, ...] = ()
    default: Any = None
    minimum: float = 0.0
    maximum: float = 100.0
    step: float = 1.0
    hint: str = ""
    preference: str = ""

    def search_text(self) -> str:
        """Return every word this row should be findable by."""
        parts = [
            self.label,
            self.cantonese,
            self.group,
            self.accel,
            self.hint,
            self.key,
        ]
        parts.extend(self.options)
        return " ".join(part for part in parts if part)

    def display_label(self) -> str:
        """Return the row's label in the reader's language, on one line.

        A row names a command, a surface, or a setting, so it takes the language
        mode and never the funny level.  Two things break when tone reaches it.
        The row is a control, and a label that grows a clause at level five
        elides to nothing useful in a 660-pixel card -- "Tell me what to do (the
        code is dan..." names nothing.  Worse, :func:`reveal` finds the element
        a row points at by matching this text against the accessible name the
        owning surface set, and a styled label matches no surface at all, so
        teleporting would quietly stop working at exactly the tone settings a
        reader chose for fun.
        """
        return single_line(studio_label(self.label, self.cantonese))

    def accessible_name(self) -> str:
        """Return the screen-reader name for the row itself."""
        pieces = [self.display_label(), self.group]
        if self.accel:
            pieces.append(self.accel)
        return " — ".join(piece for piece in pieces if piece)


def _school_mode_hides(*text: str) -> bool:
    """Return whether School mode must omit a row carrying this wording."""
    haystack = " ".join(text).casefold()
    return any(term in haystack for term in SCHOOL_MODE_TERMS)


def _command_results() -> List[PaletteResult]:
    """Index every command the shell can run.

    The registry is imported here rather than at module scope because the shell
    imports this module to open the palette; importing it back at the top would
    be a cycle, and the lazy import also keeps a headless import cheap.
    """
    try:
        from amulet_map_editor.api.studio import commands
    except ImportError:
        log.exception("The Studio command registry is unavailable")
        return []
    results: List[PaletteResult] = []
    for command in getattr(commands, "COMMANDS", ()):
        results.append(
            PaletteResult(
                kind="command",
                key=command.key,
                label=command.label,
                group=command.group,
                accel=getattr(command, "accel", ""),
            )
        )
    return results


def _surface_results() -> List[PaletteResult]:
    """Index every window, dialog, tool, and pane the shell can open."""
    try:
        from amulet_map_editor.api.studio import surfaces
    except ImportError:
        log.exception("The Studio surface registry is unavailable")
        return []
    results: List[PaletteResult] = []
    for surface in getattr(surfaces, "SURFACES", ()):
        results.append(
            PaletteResult(
                kind="surface",
                key=surface.key,
                label=surface.label,
                group=surface.group,
                accel=getattr(surface, "accel", ""),
                hint=getattr(surface, "hint", ""),
                surface=surface.key,
            )
        )
    return results


@dataclass(frozen=True)
class _PreferenceSetting:
    """One real, persisted application setting and how the palette renders it."""

    field: str
    label: str
    cantonese: str
    group: str
    control: str
    options: Tuple[str, ...] = ()
    minimum: float = 0.0
    maximum: float = 0.0
    step: float = 1.0
    hint: str = ""


#: The application's own settings, named by the
#: :class:`~amulet_map_editor.api.preferences.Preferences` field each one
#: writes.  These are the rows whose inline control changes something durable,
#: so they are described as data rather than assembled at render time.
PREFERENCE_SETTINGS: Tuple[_PreferenceSetting, ...] = (
    _PreferenceSetting(
        field="display_name",
        label="App display name",
        cantonese="應用程式顯示名",
        group="Options · Appearance",
        control="text",
        hint=(
            "The name the application shows you. It never changes the package, "
            "data directory, or update identity."
        ),
    ),
    _PreferenceSetting(
        field="language_mode",
        label="Language mode",
        cantonese="語言模式",
        group="Options · Language and voice",
        control="select",
        options=("English", "Cantonese", "Bilingual"),
        hint="English, playful Hong Kong Cantonese, or both together.",
    ),
    _PreferenceSetting(
        field="funny_level_english",
        label="Funny level (English)",
        cantonese="英文搞笑程度",
        group="Options · Language and voice",
        control="stepper",
        minimum=1,
        maximum=5,
        step=1,
        hint=(
            "1 reads fully professional and 5 is maximum playfulness. It styles "
            "every message including errors, and never changes a fact in one."
        ),
    ),
    _PreferenceSetting(
        field="funny_level_cantonese",
        label="Funny level (Cantonese)",
        cantonese="廣東話搞笑程度",
        group="Options · Language and voice",
        control="stepper",
        minimum=1,
        maximum=5,
        step=1,
        hint=(
            "1 reads fully professional and 5 is maximum playfulness. It styles "
            "every message including errors, and never changes a fact in one."
        ),
    ),
    _PreferenceSetting(
        field="show_dialog_emojis",
        label="Show emojis in dialogs and message boxes",
        cantonese="喺對話框同訊息框顯示表情符號",
        group="Options · Appearance",
        control="switch",
        hint="Decoration only. Buttons and control labels never carry an emoji.",
    ),
    _PreferenceSetting(
        field="theme",
        label="Theme",
        cantonese="主題",
        group="Options · Appearance",
        control="select",
        options=("Light", "Dark", "Follow the system"),
        hint="Light, dark, or whatever the operating system is currently using.",
    ),
    _PreferenceSetting(
        field="density",
        label="Density",
        cantonese="密度",
        group="Options · Appearance",
        control="select",
        options=("Compact", "Comfortable", "Spacious"),
        hint="Sets the height every control reaches: 32, 36, or 44 pixels.",
    ),
    _PreferenceSetting(
        field="accent",
        label="Accent colour",
        cantonese="主色",
        group="Options · Appearance",
        control="colour",
        hint="Reseeds the whole primary family, not one button colour.",
    ),
    _PreferenceSetting(
        field="ui_font",
        label="Interface font",
        cantonese="介面字體",
        group="Options · Appearance",
        control="text",
        hint=(
            "The face name of an installed font. Leave it empty to use the "
            "shipped family. Coordinates and identifiers stay monospaced."
        ),
    ),
    _PreferenceSetting(
        field="ui_scale",
        label="Interface scale",
        cantonese="介面比例",
        group="Options · Appearance",
        control="slider",
        minimum=80,
        maximum=200,
        step=5,
        hint="A percentage between 80 and 200.",
    ),
    _PreferenceSetting(
        field="external_editor_path",
        label="External editor",
        cantonese="外部編輯器",
        group="Options · Appearance",
        control="text",
        hint="The program that opens an exported file or project folder.",
    ),
)

#: Display labels for the preferences whose stored value is a token rather than
#: a sentence, so the palette can read and write either spelling.
_LANGUAGE_LABELS: Dict[str, str] = {
    "english": "English",
    "cantonese": "Cantonese",
    "bilingual": "Bilingual",
}
_THEME_LABELS: Dict[str, str] = {
    "light": "Light",
    "dark": "Dark",
    "system": "Follow the system",
}
_DENSITY_LABELS: Dict[str, str] = {
    "compact": "Compact",
    "comfortable": "Comfortable",
    "spacious": "Spacious",
}
_TOKEN_LABELS: Dict[str, Dict[str, str]] = {
    "language_mode": _LANGUAGE_LABELS,
    "theme": _THEME_LABELS,
    "density": _DENSITY_LABELS,
}


def preference_display(field: str, value: Any) -> Any:
    """Convert a stored preference into what the palette's control shows."""
    labels = _TOKEN_LABELS.get(field)
    if labels is not None:
        return labels.get(str(value), str(value))
    if field == "ui_scale":
        try:
            return round(float(value) * 100)
        except (TypeError, ValueError):
            return 100
    return value


def preference_store(field: str, value: Any) -> Any:
    """Convert what the palette's control produced into a stored preference."""
    labels = _TOKEN_LABELS.get(field)
    if labels is not None:
        text = str(value)
        for token, label in labels.items():
            if text in (token, label):
                return token
        return text
    if field == "ui_scale":
        try:
            return round(float(value)) / 100.0
        except (TypeError, ValueError):
            return 1.0
    if field in ("funny_level_english", "funny_level_cantonese"):
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return 1
    if field == "show_dialog_emojis":
        return bool(value)
    return str(value)


def _preference_results() -> List[PaletteResult]:
    """Index the application's own settings as live, writable rows."""
    school = studio_copy.is_school_mode()
    results: List[PaletteResult] = []
    for setting in PREFERENCE_SETTINGS:
        if school and (
            setting.field in SCHOOL_MODE_PREFERENCES
            or _school_mode_hides(setting.label, setting.group)
        ):
            continue
        results.append(
            PaletteResult(
                kind="setting",
                key=(
                    f"prefs{ELEMENT_KEY_SEPARATOR}preference"
                    f"{ELEMENT_KEY_SEPARATOR}{setting.field}"
                ),
                label=setting.label,
                cantonese=setting.cantonese,
                group=setting.group,
                surface="prefs",
                control=setting.control,
                options=setting.options,
                minimum=setting.minimum,
                maximum=setting.maximum,
                step=setting.step,
                hint=setting.hint,
                preference=setting.field,
            )
        )
    return results


def _numeric_control(minimum: float, maximum: float, step: float) -> str:
    """Choose between a stepper and a slider for one bounded number.

    A short integer range fits a palette row as ``[-] 3 [+]`` and reads exactly;
    anything wider or fractional gets the slider, which is also the control its
    own surface renders.
    """
    whole = float(minimum).is_integer() and float(maximum).is_integer()
    if whole and float(step) == 1.0 and (maximum - minimum) <= STEPPER_MAX_SPAN:
        return "stepper"
    return "slider"


def _spec_setting_results() -> List[PaletteResult]:
    """Index every individual setting declared by every surface description.

    A setting is anything a reader can change: a check, a bounded range, a
    dropdown, a text field, or a named colour.  Records, key bindings, tree
    lines, and revisions are content rather than settings, and are reached by
    opening the surface that holds them.
    """
    try:
        from amulet_map_editor.api.studio import specs
    except ImportError:
        log.exception("The Studio surface descriptions are unavailable")
        return []
    school = studio_copy.is_school_mode()
    results: List[PaletteResult] = []
    for key in sorted(getattr(specs, "SPECS", {})):
        # Through ``get``, never the snapshot: a surface built from live state
        # -- the Key Select window's key groups -- registers a rebuilder, and
        # reading ``SPECS`` straight indexes whatever it happened to hold when
        # this process imported it.  The palette would then offer the reader a
        # dropdown of key groups read before their configuration was.
        spec = specs.get(key)
        if spec is None:  # pragma: no cover - the key came from the same map
            continue
        if school and (
            key in SCHOOL_MODE_SURFACES or _school_mode_hides(spec.title, spec.eyebrow)
        ):
            continue
        for index, section in enumerate(spec.sections):
            group = f"{spec.title} · {section.title}" if section.title else spec.title
            base = f"{key}{ELEMENT_KEY_SEPARATOR}{index}"
            for position, check in enumerate(section.checks):
                if school and _school_mode_hides(check.label, group):
                    continue
                results.append(
                    PaletteResult(
                        kind="setting",
                        key=(
                            f"{base}{ELEMENT_KEY_SEPARATOR}checks"
                            f"{ELEMENT_KEY_SEPARATOR}{position}"
                        ),
                        label=check.label,
                        group=group,
                        surface=key,
                        control="switch",
                        default=bool(check.value),
                        hint=check.hint,
                    )
                )
            for position, item in enumerate(section.ranges):
                if school and _school_mode_hides(item.label, group):
                    continue
                results.append(
                    PaletteResult(
                        kind="setting",
                        key=(
                            f"{base}{ELEMENT_KEY_SEPARATOR}ranges"
                            f"{ELEMENT_KEY_SEPARATOR}{position}"
                        ),
                        label=item.label,
                        group=group,
                        surface=key,
                        control=_numeric_control(item.min, item.max, item.step),
                        default=float(item.value),
                        minimum=float(item.min),
                        maximum=float(item.max),
                        step=float(item.step) if float(item.step) > 0 else 1.0,
                        hint=section.hint,
                    )
                )
            for position, select in enumerate(section.selects):
                if school and _school_mode_hides(select.label, group):
                    continue
                results.append(
                    PaletteResult(
                        kind="setting",
                        key=(
                            f"{base}{ELEMENT_KEY_SEPARATOR}selects"
                            f"{ELEMENT_KEY_SEPARATOR}{position}"
                        ),
                        label=select.label,
                        group=group,
                        surface=key,
                        control="select",
                        options=tuple(select.options),
                        default=select.current(),
                        hint=section.hint,
                    )
                )
            for position, entry in enumerate(section.fields):
                if school and _school_mode_hides(entry.label, group):
                    continue
                results.append(
                    PaletteResult(
                        kind="setting",
                        key=(
                            f"{base}{ELEMENT_KEY_SEPARATOR}fields"
                            f"{ELEMENT_KEY_SEPARATOR}{position}"
                        ),
                        label=entry.label,
                        group=group,
                        surface=key,
                        control="text",
                        default=entry.value,
                        hint=entry.placeholder or section.hint,
                    )
                )
            for position, swatch in enumerate(section.swatches):
                if school and _school_mode_hides(swatch.name, group):
                    continue
                results.append(
                    PaletteResult(
                        kind="setting",
                        key=(
                            f"{base}{ELEMENT_KEY_SEPARATOR}swatches"
                            f"{ELEMENT_KEY_SEPARATOR}{position}"
                        ),
                        label=swatch.name,
                        group=group,
                        surface=key,
                        control="colour",
                        default=swatch.colour,
                        hint=section.hint,
                    )
                )
    return results


_index_cache: Optional[Tuple[PaletteResult, ...]] = None
_index_school_mode: Optional[bool] = None


def build_index(*, refresh: bool = False) -> Tuple[PaletteResult, ...]:
    """Return every palette row, building and caching it on first use.

    The index is structure, never live values: what a setting currently reads is
    resolved per row by :func:`current_value`, so a value changed anywhere in the
    application shows correctly the next time the palette paints without the
    whole index being rebuilt.  School mode is part of the cache key because it
    removes rows rather than disabling them.
    """
    global _index_cache, _index_school_mode
    school = studio_copy.is_school_mode()
    if refresh or _index_cache is None or _index_school_mode != school:
        _index_cache = tuple(
            _command_results()
            + _surface_results()
            + _preference_results()
            + _spec_setting_results()
        )
        _index_school_mode = school
    return _index_cache


def current_value(
    result: PaletteResult,
    *,
    profile: Optional[preferences.Preferences] = None,
) -> Any:
    """Return what a setting row's control should currently show.

    ``profile`` lets a caller building many rows at once read the persisted
    preferences a single time; loading them is a file read, and doing it per row
    on every keystroke is the difference between a palette that keeps up with
    typing and one that does not.
    """
    if result.preference:
        try:
            record = preferences.load() if profile is None else profile
            stored = getattr(record, result.preference)
        except (OSError, AttributeError):
            log.exception("Could not read the preference %r", result.preference)
            return result.default
        return preference_display(result.preference, stored)
    return setting_value(result.key, result.default)


def _score(result: PaletteResult, needle: str) -> int:
    """Rank one row against the query: an exact label first, the rest after."""
    label = result.label.casefold()
    if label == needle:
        return 0
    if label.startswith(needle):
        return 1
    if needle in label:
        return 2
    return 3


def search_index(
    state: SearchState, *, index: Optional[Sequence[PaletteResult]] = None
) -> Tuple[PaletteResult, ...]:
    """Return the rows matching ``state``, best match first.

    An invalid regular expression matches nothing here exactly as it does in
    every other Studio search field; the field's own feedback line says why,
    rather than the list quietly looking empty.
    """
    rows = list(build_index() if index is None else index)
    matched = [row for row in rows if state.matches(row.search_text())]
    needle = (state.query or "").strip().casefold()
    if not needle or state.regex:
        matched.sort(key=lambda row: (_KIND_ORDER[row.kind], row.group, row.label))
        return tuple(matched)
    matched.sort(
        key=lambda row: (
            _score(row, needle),
            _KIND_ORDER[row.kind],
            row.group,
            row.label,
        )
    )
    return tuple(matched)


# ---------------------------------------------------------------------------
# applying a setting
# ---------------------------------------------------------------------------


def apply_setting(result: PaletteResult, value: Any) -> Tuple[bool, str]:
    """Write one setting and report honestly whether it landed.

    A real preference goes through
    :func:`amulet_map_editor.api.preferences.update`, which is the same
    normalising, bounded write the Options window performs, so a value that
    window would refuse is refused here too and the reason comes back as the
    second element rather than being swallowed.  A declarative setting is stored
    under its element key, where the surface that declared it reads it back.
    """
    if result.preference:
        try:
            stored = preference_store(result.preference, value)
            if result.preference == "display_name":
                stored = preferences.validate_display_name(stored)
            if result.preference == "accent" and not _ACCENT_PATTERN.match(str(stored)):
                # ``normalised`` would quietly substitute the shipped accent for
                # an unusable value, and a customization surface that silently
                # discards what the user chose is worse than one that refuses it.
                return False, "An accent must be written as #RRGGBB or #RRGGBBAA."
            preferences.update(**{result.preference: stored})
        except (ValueError, KeyError, TypeError) as error:
            return False, str(error)
        except OSError as error:
            log.exception("Could not persist the preference %r", result.preference)
            return False, str(error)
        _record_change(result, stored)
        if result.preference == "language_mode":
            _apply_language(str(stored))
        tokens.notify_theme_changed()
        return True, ""
    store_setting(result.key, value)
    _record_change(result, value)
    return True, ""


def _apply_language(mode: str) -> None:
    """Switch the running translation catalogue, as the Options window does."""
    try:
        from amulet_map_editor.api import lang

        lang.set_language(
            {"english": "en", "cantonese": "zh_TW", "bilingual": "en"}.get(mode, "en")
        )
    except Exception:
        log.exception("Could not switch the active language catalogue")


def _record_change(result: PaletteResult, value: Any) -> None:
    """Record the change in the local append-only history.

    The history is what makes the change undoable, so a setting altered from the
    palette is as recoverable as one altered on its own surface.  A failure to
    record never fails the change the user actually asked for.
    """
    try:
        local_history.safe_record(
            f"studio-setting-{result.key}",
            {
                "element": result.key,
                "surface": result.surface,
                "label": result.label,
                "value": value,
                "source": "command palette",
            },
            record_type="setting changed",
        )
    except Exception:
        log.exception("Could not record the setting change for %r", result.key)


# ---------------------------------------------------------------------------
# the reveal protocol
# ---------------------------------------------------------------------------


class _RingSegment(wx.Window):
    """One edge of the ring drawn around a revealed element."""

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False


class HighlightRing:
    """A brief ring drawn in the gap around a control the palette revealed.

    The ring is four thin sibling windows placed *outside* the target rather
    than one translucent window on top of it.  A covering window would swallow
    the first click on the very control the user was just sent to, which is the
    opposite of helpful; sitting in the gap it is unmistakable and harmless.
    """

    THICKNESS = 2
    GAP = 3

    def __init__(self, target: wx.Window, *, duration_ms: int = HIGHLIGHT_MS) -> None:
        self.segments: List[_RingSegment] = []
        parent = target.GetParent()
        if parent is None:
            return
        colour = tokens.palette().primary
        rect = wx.Rect(target.GetRect())
        rect.Inflate(tokens.scaled(self.GAP), tokens.scaled(self.GAP))
        thickness = max(1, tokens.scaled(self.THICKNESS))
        edges = (
            wx.Rect(rect.x, rect.y, rect.width, thickness),
            wx.Rect(rect.x, rect.GetBottom() - thickness, rect.width, thickness),
            wx.Rect(rect.x, rect.y, thickness, rect.height),
            wx.Rect(rect.GetRight() - thickness, rect.y, thickness, rect.height),
        )
        for edge in edges:
            if edge.width <= 0 or edge.height <= 0:
                continue
            segment = _RingSegment(
                parent,
                pos=edge.GetPosition(),
                size=edge.GetSize(),
                style=wx.BORDER_NONE,
            )
            segment.SetName("Revealed element highlight")
            segment.SetBackgroundColour(colour)
            segment.Raise()
            segment.Show()
            self.segments.append(segment)
        if not self.segments:
            return
        if not widgets.reduced_motion():
            faded = tokens.blend(colour, tokens.palette().surface, 0.45)
            wx.CallLater(max(1, duration_ms * 2 // 3), self._fade, faded)
        wx.CallLater(max(1, duration_ms), self.dispose)

    def _fade(self, colour: wx.Colour) -> None:
        """Soften the ring before it goes, so it reads as fading, not blinking."""
        for segment in self.segments:
            try:
                segment.SetBackgroundColour(colour)
                segment.Refresh()
            except RuntimeError:  # pragma: no cover - window already destroyed
                continue

    def dispose(self) -> None:
        """Remove the ring; already-destroyed segments are ignored."""
        for segment in self.segments:
            try:
                segment.Destroy()
            except RuntimeError:  # pragma: no cover - window already destroyed
                continue
        self.segments = []


def find_named(root: wx.Window, name: str) -> Optional[wx.Window]:
    """Find the descendant of ``root`` whose accessible name is ``name``.

    Every Studio widget sets ``SetName``, and several set it as
    ``"label: value"`` so a screen reader announces the current selection; an
    exact match is preferred, then a ``label:`` prefix, and a containment match
    only as a last resort because it is the one that can be wrong.

    A window hidden because its notebook page is not selected still counts: that
    is precisely the element a teleport has to reach.  A visible candidate wins
    over a hidden one at the same tier, so an unfiltered surface is never sent
    to a control behind a tab it did not need to open.
    """
    needle = str(name).strip().casefold()
    if not needle:
        return None
    best: Optional[Tuple[int, int, wx.Window]] = None
    stack: List[wx.Window] = list(root.GetChildren())
    while stack:
        window = stack.pop(0)
        try:
            stack.extend(window.GetChildren())
            candidate = str(window.GetName() or "").strip().casefold()
            visible = 0 if window.IsShownOnScreen() else 1
        except RuntimeError:  # pragma: no cover - window destroyed mid-walk
            continue
        if not candidate:
            continue
        if candidate == needle:
            tier = 0
        elif candidate.startswith(f"{needle}:"):
            tier = 1
        elif needle in candidate:
            tier = 2
        else:
            continue
        if best is None or (tier, visible) < (best[0], best[1]):
            best = (tier, visible, window)
    return best[2] if best is not None else None


def scroll_into_view(target: wx.Window) -> None:
    """Scroll the nearest scrolling ancestor so ``target`` is visible."""
    parent = target.GetParent()
    while parent is not None:
        if isinstance(parent, wx.ScrolledWindow):
            scroller = getattr(parent, "ScrollChildIntoView", None)
            if callable(scroller):
                try:
                    scroller(target)
                except Exception:  # pragma: no cover - platform boundary
                    log.debug("Could not scroll %r into view", target.GetName())
            return
        parent = parent.GetParent()


def select_owning_page(target: wx.Window) -> None:
    """Select whichever notebook page ``target`` lives on, if any.

    A palette result that lands on a hidden tab has not teleported anywhere, so
    every book control between the target and its window is asked to show the
    page that contains it.
    """
    child: wx.Window = target
    parent = child.GetParent()
    while parent is not None:
        if isinstance(parent, wx.BookCtrlBase):
            for index in range(parent.GetPageCount()):
                if parent.GetPage(index) is child:
                    if parent.GetSelection() != index:
                        parent.SetSelection(index)
                    break
        child = parent
        parent = parent.GetParent()


def reveal(window: wx.Window, key: str, *, label: str = "") -> bool:
    """Show, focus, and ring the element ``key`` inside ``window``.

    A surface that can find its own elements implements ``reveal(element_key)``
    and is asked first -- that is the whole extension point, and it is why no
    surface needs a branch in this module.  Everything else is located by the
    accessible name every Studio widget already sets.
    """
    handler = getattr(window, "reveal", None)
    if callable(handler):
        try:
            if handler(key):
                return True
        except Exception:
            log.exception("The surface's own reveal handler failed for %r", key)
    target = find_named(window, label or key)
    if target is None:
        target = _reveal_after_clearing_search(window, label or key)
    if target is None:
        return False
    select_owning_page(target)
    scroll_into_view(target)
    try:
        target.SetFocus()
    except RuntimeError:  # pragma: no cover - window destroyed between calls
        return False
    HighlightRing(target)
    return True


def _reveal_after_clearing_search(window: wx.Window, name: str) -> Optional[wx.Window]:
    """Retry the lookup with the surface's own window search cleared.

    A surface filtered by its own search box genuinely does not contain the
    element yet, so the filter is lifted for the retry.  It happens only after
    the first lookup failed, so a teleport into an unfiltered window never
    disturbs a query the reader is in the middle of.
    """
    state = getattr(window, "window_search", None)
    rebuild = getattr(window, "rebuild", None)
    if not isinstance(state, SearchState) or not callable(rebuild):
        return None
    if not state.is_active():
        return None
    state.reset()
    try:
        rebuild()
    except Exception:
        log.exception("Could not rebuild %r after clearing its window search", name)
        return None
    return find_named(window, name)


def open_owning_surface(parent: wx.Window, key: str) -> Optional[wx.Window]:
    """Open the surface registered under ``key`` and return its window."""
    if not key:
        return None
    try:
        from amulet_map_editor.api.studio import surfaces
    except ImportError:
        log.exception("The Studio surface registry is unavailable")
        return None
    return surfaces.open_surface(parent, key)


def teleport(parent: wx.Window, result: PaletteResult) -> Optional[wx.Window]:
    """Open a result's surface and reveal the exact element inside it.

    The reveal is deferred by a few milliseconds because a window that has only
    just been shown has not laid its children out yet, and looking for a control
    that has no position produces a scroll to nowhere.
    """
    surface_key = result.surface or (result.key if result.kind == "surface" else "")
    window = open_owning_surface(parent, surface_key)
    if window is None:
        return None
    if result.kind == "setting":
        wx.CallLater(REVEAL_DELAY_MS, _reveal_or_report, window, result)
    return window


def _reveal_or_report(window: wx.Window, result: PaletteResult) -> None:
    """Reveal the element, and say plainly when it could not be found."""
    try:
        if reveal(window, result.key, label=result.label):
            return
    except RuntimeError:  # pragma: no cover - surface closed before the reveal
        return
    from amulet_map_editor.api.wx import nonblocking

    nonblocking.notify(
        window,
        # The title names the event and is the notification's own label; only
        # the body below is the application speaking, so only it takes tone.
        studio_label("Surface opened", "打開咗個介面"),
        studio_text(
            f"Could not find “{result.label}” to highlight it.",
            f"搵唔到「{result.label}」嚟標示。",
        ),
        details=f"Element key: {result.key}",
    )


# ---------------------------------------------------------------------------
# palette widgets
# ---------------------------------------------------------------------------


class _Eyebrow(wx.Control):
    """The uppercase, letter-spaced primary line above the palette's field."""

    SIZE_PX = 11
    TRACKING = 1

    def __init__(self, parent: wx.Window, text: str) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self.text = str(text).upper()
        self.SetName(self.text)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def _font(self) -> wx.Font:
        return tokens.font_px(self, widgets.point_size(self.SIZE_PX), _MEDIUM)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        """Return the width this eyebrow needs, measured the way it is drawn.

        Letter-spaced text is measured and drawn one character at a time, so a
        sub-pixel disagreement between the plain device context this used to
        measure with and the ``wx.GCDC`` :meth:`_on_paint` draws with compounds
        across every character.  Over eighteen of them it came to a whole
        letter: the palette's own eyebrow read "TELL ME WHAT TO DC", with the
        final O painted past the edge of the control.  Measure with the context
        that draws and the last character has somewhere to go.
        """
        client = wx.ClientDC(self)
        try:
            dc: wx.DC = wx.GCDC(client)
        except TypeError:  # pragma: no cover - platform without a graphics context
            dc = client
        dc.SetFont(self._font())
        tracking = tokens.scaled(self.TRACKING)
        size = wx.Size(
            widgets.tracked_width(dc, self.text, tracking) + tracking,
            dc.GetCharHeight() + tokens.scaled(2),
        )
        if dc is not client:
            del dc
        return size

    def refresh_theme(self) -> None:
        """Repaint after the palette or interface scale changed."""
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface)
        gcdc.SetFont(self._font())
        gcdc.SetTextForeground(palette.primary)
        widgets.draw_tracked_text(gcdc, self.text, 0, 0, tokens.scaled(self.TRACKING))
        del gcdc
        del dc


def _as_float(value: Any, fallback: float) -> float:
    """Coerce a stored value to a number without letting a bad record raise."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


class PaletteRow(wx.Control):
    """One palette result: its label, its group, and either an accelerator or
    the setting's own live control.

    The row is a control rather than a panel so it can take the keyboard itself:
    Up and Down move between rows, Enter activates, and an inline control is
    still reachable with Tab without stealing the arrow keys the list needs.
    """

    RADIUS = 10
    PADDING_X = 13
    PADDING_Y = 11
    GAP = 14
    LABEL_PX = 14
    GROUP_PX = 12
    ACCEL_PX = 11

    def __init__(
        self,
        parent: wx.Window,
        result: PaletteResult,
        *,
        on_activate: Optional[Callable[[PaletteResult], None]] = None,
        on_change: Optional[Callable[[PaletteResult, Any], None]] = None,
        profile: Optional[preferences.Preferences] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.result = result
        self.on_activate = on_activate
        self.on_change = on_change
        self.profile = profile
        self.control: Optional[wx.Window] = None
        self.selected = False
        self._hovered = False
        self._readout = ""
        self._slider_scale = 1
        # The rendered label is resolved once rather than per paint: styling it
        # reads the persisted language and tone, and a paint handler that reads
        # a file is a paint handler that stutters.
        self._display = result.display_label()
        self._name = self._accessible_name()
        self.SetName(self._name)
        self.SetToolTip(result.hint or self._name)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.AddStretchSpacer(1)
        if result.kind == "setting" and result.control:
            self.control = self._build_control()
        if self.control is not None:
            sizer.Add(
                self.control,
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                tokens.scaled(self.PADDING_X),
            )
        self.SetSizer(sizer)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_hover)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_hover)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_focus)
        self.SetInitialSize(self.DoGetBestSize())

    # -- construction --------------------------------------------------------
    def _accessible_name(self) -> str:
        """Return the screen-reader name for the row, from its rendered label."""
        pieces = [self._display, self.result.group]
        if self.result.accel:
            pieces.append(self.result.accel)
        return " — ".join(piece for piece in pieces if piece)

    def _build_control(self) -> Optional[wx.Window]:
        """Build the live control this setting is edited with."""
        result = self.result
        value = current_value(result, profile=self.profile)
        name = f"{self._display} ({result.group})"
        if result.control == "switch":
            control: wx.Window = widgets.ToggleSwitch(
                self, bool(value), on_change=self._changed
            )
        elif result.control == "stepper":
            control = widgets.Stepper(
                self,
                _as_float(value, result.minimum),
                result.minimum,
                result.maximum,
                on_change=self._changed,
            )
        elif result.control == "slider":
            control = self._build_slider(_as_float(value, result.minimum))
        elif result.control == "select":
            control = widgets.SearchableChoice(
                self,
                result.label,
                result.options,
                str(value or ""),
                on_change=self._changed,
            )
        elif result.control == "colour":
            control = self._build_colour(str(value or "#000000"))
        elif result.control == "text":
            control = self._build_text("" if value is None else str(value))
        else:
            return None
        control.SetName(name)
        if result.hint:
            control.SetToolTip(result.hint)
        return control

    def _build_slider(self, value: float) -> wx.Slider:
        """Build the native slider a bounded numeric setting is moved with.

        It is the platform's own control on purpose: arrow, page, home, and end
        handling and the value a screen reader announces all come for free, and
        the current number is painted into the row beside it.
        """
        result = self.result
        self._slider_scale = max(1, round(1 / result.step)) if result.step < 1 else 1
        scale = self._slider_scale
        slider = wx.Slider(
            self,
            value=int(round(value * scale)),
            minValue=int(round(result.minimum * scale)),
            maxValue=int(round(result.maximum * scale)),
            style=wx.SL_HORIZONTAL,
        )
        slider.SetMinSize(wx.Size(tokens.scaled(180), tokens.control_height()))
        self._readout = widgets.format_number(value)
        slider.Bind(
            wx.EVT_SLIDER,
            lambda _event: self._changed(slider.GetValue() / self._slider_scale),
        )
        return slider

    def _build_colour(self, value: str) -> wx.Window:
        """Build the colour control, which is the same picker Options uses."""
        picker = wx.ColourPickerCtrl(self, colour=widgets.colour_of(value))
        picker.SetMinSize(wx.Size(tokens.scaled(120), tokens.control_height()))
        picker.Bind(
            wx.EVT_COLOURPICKER_CHANGED,
            lambda event: self._changed(
                event.GetColour().GetAsString(wx.C2S_HTML_SYNTAX)
            ),
        )
        return picker

    def _build_text(self, value: str) -> wx.TextCtrl:
        """Build the text entry, committing on Enter and on leaving the field.

        Writing on every keystroke would persist half-typed values and, for a
        validated preference, report a refusal for every intermediate character.
        """
        entry = wx.TextCtrl(self, value=value, style=wx.TE_PROCESS_ENTER)
        entry.SetMinSize(wx.Size(tokens.scaled(200), tokens.control_height()))
        entry.Bind(wx.EVT_TEXT_ENTER, lambda _event: self._changed(entry.GetValue()))
        entry.Bind(wx.EVT_KILL_FOCUS, self._commit_text)
        return entry

    def _commit_text(self, event: wx.FocusEvent) -> None:
        entry = event.GetEventObject()
        if isinstance(entry, wx.TextCtrl):
            self._changed(entry.GetValue())
        event.Skip()

    # -- behaviour -----------------------------------------------------------
    def _changed(self, value: Any) -> None:
        if self.result.control == "slider":
            self._readout = widgets.format_number(_as_float(value, 0.0))
            self.Refresh()
        widgets.invoke(self.on_change, self.result, value)

    def refresh_value(self) -> None:
        """Re-read the live value into the row's control after a change elsewhere.

        Every setter is called without notification: pushing a value back into a
        control that then reports it as a fresh edit is how a settings row ends
        up writing itself in a loop.
        """
        if self.control is None:
            return
        value = current_value(self.result)
        try:
            if isinstance(self.control, wx.Slider):
                self.control.SetValue(
                    int(round(_as_float(value, 0.0) * self._slider_scale))
                )
                self._readout = widgets.format_number(_as_float(value, 0.0))
            elif isinstance(self.control, wx.ColourPickerCtrl):
                self.control.SetColour(widgets.colour_of(value))
            elif isinstance(self.control, wx.TextCtrl):
                self.control.ChangeValue("" if value is None else str(value))
            else:
                setter = getattr(self.control, "set_value", None)
                if callable(setter):
                    try:
                        setter(value, notify=False)
                    except TypeError:
                        setter(value)
        except (TypeError, ValueError):
            log.exception("Could not show the live value of %r", self.result.key)
        self.Refresh()

    def set_selected(self, selected: bool) -> None:
        """Mark the row as the palette's current keyboard target."""
        self.selected = bool(selected)
        self.Refresh()

    def activate(self) -> None:
        """Run the row: run a command, open a surface, or teleport to a setting."""
        widgets.invoke(self.on_activate, self.result)

    def _on_hover(self, event: wx.MouseEvent) -> None:
        self._hovered = event.GetEventType() == wx.EVT_ENTER_WINDOW.typeId
        self.Refresh()
        event.Skip()

    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        event.Skip()

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        if self.GetClientRect().Contains(event.GetPosition()):
            self.activate()
        event.Skip()

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.activate()
            return
        event.Skip()

    def _on_focus(self, event: wx.FocusEvent) -> None:
        self.Refresh()
        event.Skip()

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    # -- geometry ------------------------------------------------------------
    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        text_height = (
            tokens.scaled(self.LABEL_PX)
            + tokens.scaled(self.GROUP_PX)
            + tokens.scaled(self.PADDING_Y) * 2
        )
        control_height = 0
        if self.control is not None:
            control_height = self.control.GetBestSize().height + tokens.scaled(
                self.PADDING_Y
            )
        return wx.Size(
            tokens.scaled(320),
            max(
                text_height,
                control_height,
                tokens.control_height() + tokens.scaled(8),
            ),
        )

    def refresh_theme(self) -> None:
        """Repaint the row and everything it hosts after an appearance change."""
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:  # pragma: no cover - window already destroyed
            return
        for child in self.GetChildren():
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        # The language mode and both funny levels can move with the appearance,
        # so the cached label is re-styled here rather than left as it was.
        self._display = self.result.display_label()
        self._name = self._accessible_name()
        self.SetName(self._name)
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    # -- painting ------------------------------------------------------------
    def _text_limit(self) -> int:
        """Return where the row's text stops so a control is never overdrawn."""
        width = self.GetClientSize().width
        if self.control is None:
            return width - tokens.scaled(self.PADDING_X) * 2 - tokens.scaled(70)
        boundary = self.control.GetPosition().x
        if boundary <= 0:
            boundary = width - self.control.GetSize().width
        return boundary - tokens.scaled(self.GAP) - tokens.scaled(self.PADDING_X)

    def _trailing_text(self) -> str:
        """Return the monospaced text on the row's right: an accelerator or a value."""
        if self.result.kind == "setting":
            return self._readout
        return self.result.accel

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        if not backdrop.IsOk():
            backdrop = palette.surface
        dc, gcdc = widgets.paint_context(self, backdrop)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(self.RADIUS)
        fill = palette.surface_container
        if self.selected or self._hovered or self.HasFocus():
            fill = palette.surface_container_high
        border = palette.primary if self.selected else None
        tokens.draw_round_rect(gcdc, rect, radius, fill, border)

        left = tokens.scaled(self.PADDING_X)
        trailing = self._trailing_text()
        trailing_width = 0
        if trailing:
            gcdc.SetFont(tokens.mono_font_px(self, widgets.point_size(self.ACCEL_PX)))
            trailing_width = gcdc.GetTextExtent(trailing)[0] + tokens.scaled(10)
        limit = max(tokens.scaled(40), self._text_limit() - trailing_width)

        label_font = tokens.font_px(self, widgets.point_size(self.LABEL_PX), _MEDIUM)
        group_font = tokens.font_px(self, widgets.point_size(self.GROUP_PX))
        gcdc.SetFont(label_font)
        label = widgets.elide(gcdc, self._display, limit)
        label_height = gcdc.GetCharHeight()
        gcdc.SetFont(group_font)
        group = widgets.elide(gcdc, self.result.group, limit)
        group_height = gcdc.GetCharHeight()
        top = rect.y + max(
            tokens.scaled(4), (height - label_height - group_height) // 2
        )
        gcdc.SetFont(label_font)
        gcdc.SetTextForeground(palette.on_surface)
        gcdc.DrawText(label, left, top)
        gcdc.SetFont(group_font)
        gcdc.SetTextForeground(palette.on_surface_variant)
        gcdc.DrawText(group, left, top + label_height)

        if trailing:
            gcdc.SetFont(tokens.mono_font_px(self, widgets.point_size(self.ACCEL_PX)))
            gcdc.SetTextForeground(palette.primary)
            text_width, text_height = gcdc.GetTextExtent(trailing)
            if self.control is None:
                trailing_x = (
                    rect.GetRight() - tokens.scaled(self.PADDING_X) - text_width
                )
            else:
                trailing_x = max(
                    left + limit + tokens.scaled(6),
                    self.control.GetPosition().x - tokens.scaled(8) - text_width,
                )
            gcdc.DrawText(trailing, trailing_x, rect.y + (height - text_height) // 2)
        if self.HasFocus():
            widgets.draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


# ---------------------------------------------------------------------------
# the palette itself
# ---------------------------------------------------------------------------


def _focus_within(window: Optional[wx.Window]) -> bool:
    """Return whether the keyboard focus is ``window`` or something inside it."""
    if window is None:
        return False
    focused = wx.Window.FindFocus()
    while focused is not None:
        if focused is window:
            return True
        focused = focused.GetParent()
    return False


class CommandPalette(wx.Dialog):
    """The Ctrl+Shift+F palette over every command, surface, and setting.

    It is deliberately not modal: the palette exists to reach the rest of the
    application, and a window that blocks the application it is meant to
    navigate would be a strange way to do that.  Escape closes it and focus goes
    back to whatever had it when the palette opened.
    """

    CARD_WIDTH = 660
    CARD_HEIGHT = 620
    CARD_RESULT_LIMIT = 40
    FULL_RESULT_LIMIT = 140
    FIELD_HEIGHT = 40
    PADDING = 18
    ROW_GAP = 4
    PAGE_STEP = 8

    def __init__(
        self,
        parent: wx.Window,
        *,
        shell: Any = None,
        layout: Optional[str] = None,
    ) -> None:
        super().__init__(parent, title="Tell me what to do", style=wx.BORDER_NONE)
        self.shell = shell
        self.layout_mode = layout if layout in LAYOUTS else palette_layout()
        self.state = SearchState(label="Command palette")
        self.rows: List[PaletteRow] = []
        self.results: Tuple[PaletteResult, ...] = ()
        self.selection = -1
        self._opener: Optional[wx.Window] = wx.Window.FindFocus()
        self._closing = False
        self._theme_unsubscribe: Optional[Callable[[], None]] = None
        self.SetName("Command palette")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface)

        inset = tokens.scaled(self.PADDING)
        header = wx.BoxSizer(wx.HORIZONTAL)
        self.eyebrow = _Eyebrow(self, "Tell me what to do")
        header.Add(self.eyebrow, 0, wx.ALIGN_CENTER_VERTICAL)
        header.AddStretchSpacer(1)
        self.layout_button = widgets.StudioButton(
            self,
            self._layout_button_label(),
            variant="pill",
            hint=single_line(
                studio_text(
                    "Switch between the palette card and the full window. "
                    "The choice is remembered.",
                    "喺卡片同全視窗之間切換，你揀嘅會記住。",
                )
            ),
            on_click=self.toggle_layout,
            name="Palette size",
        )
        header.Add(
            self.layout_button,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            tokens.scaled(tokens.SPACE_SM),
        )
        self.close_button = widgets.StudioButton(
            self,
            "×",
            variant="icon",
            hint=single_line(studio_label("Close the palette", "閂咗個指令面板")),
            on_click=self.close,
            name="Close the command palette",
        )
        header.Add(self.close_button, 0, wx.ALIGN_CENTER_VERTICAL)

        self.search = widgets.SearchBar(
            self,
            "Search every command, setting, and pane",
            self.state,
            on_change=self._on_search,
        )
        self.search.field.SetMinSize(
            wx.Size(-1, max(tokens.scaled(self.FIELD_HEIGHT), tokens.control_height()))
        )

        self.count_label = widgets.StudioText(
            self, "", size_px=12, name="Command palette result count"
        )

        self.results_panel = wx.ScrolledWindow(
            self, style=wx.VSCROLL | wx.TAB_TRAVERSAL
        )
        self.results_panel.SetName("Command palette results")
        self.results_panel.SetScrollRate(0, tokens.scaled(12))
        self.results_panel.SetBackgroundColour(palette.surface)
        self.results_sizer = wx.BoxSizer(wx.VERTICAL)
        self.results_panel.SetSizer(self.results_sizer)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(header, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, inset)
        root.Add(self.search, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, inset)
        root.Add(
            self.count_label,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            tokens.scaled(tokens.SPACE_SM),
        )
        root.Add(self.results_panel, 1, wx.EXPAND | wx.ALL, inset)
        self.SetSizer(root)

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self._theme_unsubscribe = tokens.register_theme_listener(self.refresh_theme)

        self.apply_layout()
        self.apply_theme()
        self.rebuild()

    # -- layout --------------------------------------------------------------
    def _layout_button_label(self) -> str:
        """Return the label naming what pressing the size control will do."""
        return single_line(
            studio_label("Full window", "全視窗")
            if self.layout_mode == "card"
            else studio_label("Card", "卡片")
        )

    def result_limit(self) -> int:
        """Return how many rows this presentation renders at once.

        Every result is searchable; only the rendered slice is bounded, because
        each setting row builds a real control and several hundred of them would
        make the palette slower than opening the window it is meant to save you
        from opening.  The count line always states the full number.
        """
        return (
            self.CARD_RESULT_LIMIT
            if self.layout_mode == "card"
            else self.FULL_RESULT_LIMIT
        )

    def toggle_layout(self) -> None:
        """Swap between the card and the full window, and remember the choice."""
        self.layout_mode = "full" if self.layout_mode == "card" else "card"
        set_palette_layout(self.layout_mode)
        self.layout_button.set_label(self._layout_button_label())
        self.apply_layout()
        self.rebuild()

    def _work_area(self) -> wx.Rect:
        try:
            index = wx.Display.GetFromWindow(self)
            display = wx.Display(index if index != wx.NOT_FOUND else 0)
            return display.GetClientArea()
        except Exception:  # pragma: no cover - platform boundary
            return wx.Rect(0, 0, 1280, 800)

    def apply_layout(self) -> None:
        """Size and place the palette for the presentation the user chose."""
        area = self._work_area()
        parent = self.GetParent()
        if self.layout_mode == "full" and parent is not None:
            frame = parent.GetTopLevelParent()
            margin = tokens.scaled(tokens.SPACE_XL)
            rect = frame.GetScreenRect()
            self.SetSize(
                wx.Size(
                    max(tokens.scaled(360), rect.width - margin * 2),
                    max(tokens.scaled(280), rect.height - margin * 2),
                )
            )
            self.SetPosition(wx.Point(rect.x + margin, rect.y + margin))
        else:
            self.SetSize(
                wx.Size(
                    min(tokens.scaled(self.CARD_WIDTH), area.width - tokens.scaled(32)),
                    min(
                        tokens.scaled(self.CARD_HEIGHT), area.height - tokens.scaled(64)
                    ),
                )
            )
            if parent is not None:
                self.CentreOnParent()
            else:
                self.Centre()
        self._apply_rounded_shape()
        self.Layout()

    def _apply_rounded_shape(self) -> None:
        """Round the palette's own corners where the platform supports a shape.

        A top-level window is a rectangle unless it is given a region, and a
        platform that refuses one keeps square corners rather than failing to
        open the palette at all.
        """
        width, height = self.GetSize()
        if width <= 0 or height <= 0:
            return
        try:
            bitmap = wx.Bitmap(width, height)
            memory = wx.MemoryDC(bitmap)
            memory.SetBackground(wx.Brush(wx.Colour(0, 0, 0)))
            memory.Clear()
            memory.SetBrush(wx.Brush(wx.Colour(255, 255, 255)))
            memory.SetPen(wx.Pen(wx.Colour(255, 255, 255)))
            memory.DrawRoundedRectangle(
                0, 0, width, height, tokens.scaled(tokens.RADIUS_LG)
            )
            memory.SelectObject(wx.NullBitmap)
            self.SetShape(wx.Region(bitmap, wx.Colour(0, 0, 0)))
        except Exception:  # pragma: no cover - platform boundary
            log.debug(
                "This platform will not shape the palette; keeping square corners"
            )

    def _on_size(self, event: wx.SizeEvent) -> None:
        self._apply_rounded_shape()
        self.count_label.Wrap(
            max(
                tokens.scaled(120),
                event.GetSize().width - tokens.scaled(self.PADDING) * 2,
            )
        )
        event.Skip()

    # -- results -------------------------------------------------------------
    def _on_search(self, _state: SearchState) -> None:
        self.rebuild()

    def rebuild(self) -> None:
        """Rebuild the visible rows for the current query and presentation."""
        self.results = search_index(self.state)
        visible = self.results[: self.result_limit()]
        # One read of the persisted profile serves every row in this pass; each
        # row loading it for itself would read the same file forty times per
        # keystroke.
        try:
            profile = preferences.load()
        except OSError:
            log.exception("Could not read preferences while building the palette")
            profile = preferences.Preferences().normalised()
        self.results_panel.Freeze()
        try:
            self.results_sizer.Clear(delete_windows=True)
            self.rows = []
            for result in visible:
                row = PaletteRow(
                    self.results_panel,
                    result,
                    on_activate=self.activate,
                    on_change=self.change_setting,
                    profile=profile,
                )
                self.rows.append(row)
                self.results_sizer.Add(
                    row, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(self.ROW_GAP)
                )
            self.results_panel.FitInside()
            self.results_panel.Layout()
        finally:
            self.results_panel.Thaw()
        self.selection = 0 if self.rows else -1
        self._paint_selection()
        self.count_label.SetLabel(self._count_text(len(self.results), len(visible)))
        self.Layout()

    def _count_text(self, total: int, shown: int) -> str:
        """Return the honest line under the field: what matched and what is drawn."""
        summary = self.state.describe_matches(total, "result")
        if shown < total:
            return (
                f"{summary} Showing the first {shown}; "
                "narrow the search to reach the rest."
            )
        return summary

    def _paint_selection(self) -> None:
        for index, row in enumerate(self.rows):
            row.set_selected(index == self.selection)

    def move_selection(self, delta: int) -> None:
        """Move the keyboard selection by ``delta`` rows and focus the result."""
        if not self.rows:
            return
        current = self.selection if self.selection >= 0 else 0
        self.select_row(current + delta)

    def select_row(self, index: int) -> None:
        """Select one row by position, focusing it so it is announced."""
        if not self.rows:
            return
        self.selection = max(0, min(len(self.rows) - 1, int(index)))
        self._paint_selection()
        row = self.rows[self.selection]
        scroller = getattr(self.results_panel, "ScrollChildIntoView", None)
        if callable(scroller):
            scroller(row)
        row.SetFocus()

    # -- actions -------------------------------------------------------------
    def _shell_method(self, name: str) -> Optional[Callable[..., Any]]:
        """Return the shell's ``name`` method, searching the parents if needed."""
        candidate = getattr(self.shell, name, None)
        if callable(candidate):
            return candidate
        window: Optional[wx.Window] = self.GetParent()
        while window is not None:
            candidate = getattr(window, name, None)
            if callable(candidate):
                return candidate
            window = window.GetParent()
        return None

    def activate(self, result: PaletteResult) -> None:
        """Run, open, or teleport to whatever the activated row points at."""
        target = self.GetParent() or self
        self.close()
        if result.kind == "command":
            runner = self._shell_method("run_command")
            if runner is None:
                log.error("No shell is connected to run the command %r", result.key)
                return
            widgets.invoke(runner, result.key)
            return
        if result.kind == "surface":
            opener = self._shell_method("open_surface")
            if opener is not None:
                widgets.invoke(opener, result.key)
                return
            open_owning_surface(target, result.key)
            return
        teleport(target, result)

    def change_setting(self, result: PaletteResult, value: Any) -> None:
        """Write a setting edited inline, reporting a refusal rather than hiding it."""
        applied, message = apply_setting(result, value)
        if applied:
            # An appearance or language change moves what every other row reads,
            # so the visible rows are re-read rather than left showing the values
            # they were built with.
            for row in self.rows:
                if row.result.preference and row.result.key != result.key:
                    row.refresh_value()
            return
        from amulet_map_editor.api.wx import nonblocking

        nonblocking.notify(
            self,
            studio_label("That value was not accepted", "呢個值收唔到"),
            message or studio_text("The setting was left unchanged.", "個設定冇改到。"),
            severity="warning",
            details=f"Element key: {result.key}",
        )
        for row in self.rows:
            if row.result.key == result.key:
                row.refresh_value()

    # -- keyboard ------------------------------------------------------------
    def _focus_is_in_control(self) -> bool:
        """Return whether the keyboard is inside a row's own inline control.

        A slider, stepper, and dropdown all want the arrow keys for themselves,
        so the list only claims them when focus is on the field or on a row.
        """
        for row in self.rows:
            if row.control is not None and _focus_within(row.control):
                return True
        return False

    def _focused_row(self) -> Optional[PaletteRow]:
        for row in self.rows:
            if wx.Window.FindFocus() is row:
                return row
        return None

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == wx.WXK_ESCAPE:
            self.close()
            return
        if event.ControlDown() and event.ShiftDown() and code in (ord("F"), ord("f")):
            self.search.SetFocus()
            return
        if self._focus_is_in_control():
            event.Skip()
            return
        if code == wx.WXK_DOWN:
            self.move_selection(1)
            return
        if code == wx.WXK_UP:
            self.move_selection(-1)
            return
        if code == wx.WXK_PAGEDOWN:
            self.move_selection(self.PAGE_STEP)
            return
        if code == wx.WXK_PAGEUP:
            self.move_selection(-self.PAGE_STEP)
            return
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if 0 <= self.selection < len(self.rows):
                self.rows[self.selection].activate()
                return
        row = self._focused_row()
        if row is not None:
            if code in (wx.WXK_HOME, wx.WXK_END):
                self.select_row(0 if code == wx.WXK_HOME else len(self.rows) - 1)
                return
            # Typing while a result has focus belongs to the search field: the
            # list is navigated with the arrows, and every other key is the
            # reader carrying on with their query.
            if code == wx.WXK_BACK or (
                32 <= code < 127 and not event.ControlDown() and not event.AltDown()
            ):
                self.search.SetFocus()
        event.Skip()

    # -- lifetime ------------------------------------------------------------
    def close(self) -> None:
        """Hide the palette and give the keyboard back to whoever had it."""
        if self._closing:
            return
        self._closing = True
        _forget_palette(self)
        self.Hide()
        opener = self._opener
        self._opener = None
        if opener is not None:
            try:
                if not opener.IsBeingDeleted():
                    opener.SetFocus()
            except RuntimeError:  # pragma: no cover - opener already destroyed
                pass
        wx.CallAfter(self.Destroy)

    def _on_close(self, event: wx.CloseEvent) -> None:
        event.Skip(False)
        self.close()

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            _forget_palette(self)
            if self._theme_unsubscribe is not None:
                self._theme_unsubscribe()
                self._theme_unsubscribe = None
        event.Skip()

    # -- appearance ----------------------------------------------------------
    def apply_theme(self) -> None:
        """Push the live palette into the window's own native pieces."""
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface)
        self.results_panel.SetBackgroundColour(palette.surface)
        # The result count resolves its own ink and font from the palette and
        # the live interface scale, so nothing is pushed into it here.

    def refresh_theme(self) -> None:
        """Re-read the tokens and repaint the palette and every row on it."""
        try:
            if self.IsBeingDeleted():
                return
            self.apply_theme()
            for child in self.GetChildren():
                refresh = getattr(child, "refresh_theme", None)
                if callable(refresh):
                    refresh()
            self.Layout()
            self.Refresh()
        except RuntimeError:
            # The window has already gone; the listener drops itself.
            self._theme_unsubscribe = None

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface)
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(tokens.RADIUS_LG),
            palette.surface,
            palette.outline_variant,
        )
        del gcdc
        del dc


# ---------------------------------------------------------------------------
# opening it
# ---------------------------------------------------------------------------

#: One palette per top-level window.  Pressing the chord twice brings the open
#: palette forward rather than stacking a second copy behind the first.
_open_palettes: Dict[int, CommandPalette] = {}


def _forget_palette(palette: CommandPalette) -> None:
    """Drop a palette from the open register as it closes or is destroyed."""
    for key, value in list(_open_palettes.items()):
        if value is palette:
            del _open_palettes[key]


def _parent_window(shell: Any) -> Optional[wx.Window]:
    """Resolve the window a palette opened for ``shell`` should belong to."""
    if isinstance(shell, wx.Window):
        return shell.GetTopLevelParent() or shell
    frame = getattr(shell, "frame", None)
    if isinstance(frame, wx.Window):
        return frame.GetTopLevelParent() or frame
    active = wx.GetActiveWindow()
    if isinstance(active, wx.Window):
        return active
    application = wx.GetApp()
    return application.GetTopWindow() if application is not None else None


def open_palette(shell: Any = None) -> Optional[CommandPalette]:
    """Open the command palette for ``shell``, or raise the one already open.

    ``shell`` is normally the
    :class:`~amulet_map_editor.api.studio.shell.StudioShell`, which supplies
    ``run_command`` and ``open_surface``; any window works too, and the palette
    then looks up the parent chain for those methods, so it stays usable from a
    surface opened outside the shell.
    """
    parent = _parent_window(shell)
    if parent is None:
        log.error("There is no window to open the command palette against")
        return None
    existing = _open_palettes.get(id(parent))
    if existing is not None:
        try:
            if not existing.IsBeingDeleted():
                existing.Show()
                existing.Raise()
                existing.search.SetFocus()
                return existing
        except RuntimeError:  # pragma: no cover - palette destroyed already
            pass
        _open_palettes.pop(id(parent), None)
    palette = CommandPalette(parent, shell=shell)
    _open_palettes[id(parent)] = palette
    palette.Show()
    palette.Raise()
    palette.search.SetFocus()
    return palette


__all__ = [
    "CONTROL_KINDS",
    "DEFAULT_LAYOUT",
    "ELEMENT_KEY_SEPARATOR",
    "HIGHLIGHT_MS",
    "HighlightRing",
    "LAYOUTS",
    "PALETTE_CONFIG_ID",
    "PREFERENCE_SETTINGS",
    "SETTING_STORE_ID",
    "STEPPER_MAX_SPAN",
    "CommandPalette",
    "PaletteResult",
    "PaletteRow",
    "apply_setting",
    "build_index",
    "current_value",
    "find_named",
    "invalidate_setting_cache",
    "open_owning_surface",
    "open_palette",
    "palette_layout",
    "preference_display",
    "preference_store",
    "reveal",
    "scroll_into_view",
    "search_index",
    "select_owning_page",
    "set_palette_layout",
    "setting_value",
    "stored_settings",
    "store_setting",
    "teleport",
]
