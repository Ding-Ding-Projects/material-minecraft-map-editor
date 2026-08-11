"""The declarative surface description that drives most Amulet Studio windows.

A surface is a :class:`Spec`: an eyebrow, a title, an optional introduction, an
ordered list of :class:`Section` values, and a list of footer :class:`Action`
values.  Each section names a ``kind`` and the renderer in
:mod:`amulet_map_editor.api.studio.spec_dialog` turns it into real controls, so
adding a surface is one data entry rather than a new window class.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

from amulet_map_editor.api.studio.search import SearchState

#: Every section kind the renderer understands.
SECTION_KINDS: Tuple[str, ...] = (
    "search",
    "fields",
    "selects",
    "list",
    "keys",
    "tree",
    "chips",
    "checks",
    "ranges",
    "swatches",
    "progress",
    "keygate",
    "code",
    "note",
    "commits",
    "texture",
)

#: Footer action styles, mapped onto the button variants in ``widgets``.
ACTION_KINDS: Tuple[str, ...] = ("tonal", "outlined", "danger", "text", "filled")

#: The standard disclaimer attached to every generated texture preview.
TEXTURE_HINT = (
    "The tile above is a generated placeholder, not the game texture. "
    "Load a resource pack or drop a PNG to show the real one."
)

#: The prompt shown inside a texture section's drop target.
TEXTURE_SLOT_HINT = "Drop the real texture from your resource pack"


@dataclass(frozen=True)
class Field:
    """One labelled text entry inside a ``fields`` section."""

    label: str
    value: str = ""
    placeholder: str = ""

    def search_text(self) -> str:
        return f"{self.label} {self.value} {self.placeholder}"


@dataclass(frozen=True)
class Select:
    """One searchable dropdown inside a ``selects`` section.

    ``on_change`` is what makes a dropdown a control rather than a picture of
    one.  A select without it renders, opens, highlights and closes again
    having changed nothing, which is worse than no dropdown at all: the Key
    Select window offered a real list of the reader's own key groups, with the
    active one already selected, beside a button reading "Save group", and
    choosing a different group did nothing whatsoever.  The renderer calls this
    with the chosen option and then re-reads the surface, so a family that
    wires one gets both the effect and the redraw.

    It is excluded from equality and from the repr: two descriptions differ
    when their labels, options or values differ, never because they were built
    with two separately-created closures.
    """

    label: str
    options: Tuple[str, ...] = ()
    value: str = ""
    on_change: Optional[Callable[[str], None]] = field(
        default=None, compare=False, repr=False
    )

    def current(self) -> str:
        """Return the selected option, defaulting to the first one."""
        if self.value:
            return self.value
        return self.options[0] if self.options else ""

    def search_text(self) -> str:
        return f"{self.label} {' '.join(self.options)}"


@dataclass(frozen=True)
class Row:
    """One record inside a ``list`` section."""

    name: str
    detail: str = ""
    tag: str = ""
    swatch: str = ""

    def search_text(self) -> str:
        return f"{self.name} {self.detail} {self.tag}"


@dataclass(frozen=True)
class KeyBinding:
    """One action and its keyboard binding inside a ``keys`` section."""

    action: str
    binding: str

    def search_text(self) -> str:
        return f"{self.action} {self.binding}"


@dataclass(frozen=True)
class TreeNode:
    """One line of a monospaced tree inside a ``tree`` section."""

    glyph: str
    label: str
    selected: bool = False

    def search_text(self) -> str:
        return self.label


@dataclass(frozen=True)
class Check:
    """One checkbox with its supporting explanation."""

    label: str
    hint: str = ""
    value: bool = False

    def search_text(self) -> str:
        return f"{self.label} {self.hint}"


@dataclass(frozen=True)
class RangeDef:
    """One bounded slider with a live readout."""

    label: str
    value: float
    min: float = 0
    max: float = 100
    step: float = 1

    def search_text(self) -> str:
        return self.label


@dataclass(frozen=True)
class SwatchDef:
    """One named colour swatch."""

    name: str
    colour: str

    def search_text(self) -> str:
        return f"{self.name} {self.colour}"


@dataclass(frozen=True)
class Commit:
    """One revision inside a ``commits`` section."""

    message: str
    meta: str = ""
    head: bool = False

    def search_text(self) -> str:
        return f"{self.message} {self.meta}"


@dataclass(frozen=True)
class Section:
    """One block of a surface, rendered according to :attr:`kind`."""

    kind: str = "note"
    title: str = ""
    hint: str = ""
    fields: Tuple[Field, ...] = ()
    selects: Tuple[Select, ...] = ()
    rows: Tuple[Row, ...] = ()
    keys: Tuple[KeyBinding, ...] = ()
    tree: Tuple[TreeNode, ...] = ()
    chips: Tuple[str, ...] = ()
    checks: Tuple[Check, ...] = ()
    ranges: Tuple[RangeDef, ...] = ()
    swatches: Tuple[SwatchDef, ...] = ()
    commits: Tuple[Commit, ...] = ()
    code: str = ""
    progress_label: str = ""
    progress_fraction: float = 0.0
    block_id: str = ""
    slot_id: str = ""
    faces: Tuple[str, ...] = ("top", "side", "bottom")

    @property
    def has_title(self) -> bool:
        return bool(self.title)

    def items(self) -> Tuple[Any, ...]:
        """Return the searchable members of this section, whatever its kind."""
        return (
            tuple(self.fields)
            + tuple(self.selects)
            + tuple(self.rows)
            + tuple(self.keys)
            + tuple(self.tree)
            + tuple(self.checks)
            + tuple(self.ranges)
            + tuple(self.swatches)
            + tuple(self.commits)
        )

    def search_text(self) -> str:
        """Return every word this section contributes to a window search."""
        parts = [self.title, self.hint, self.code, self.block_id]
        parts.extend(self.chips)
        parts.extend(item.search_text() for item in self.items())
        return " ".join(part for part in parts if part)


@dataclass(frozen=True)
class Action:
    """One footer button.

    ``surface`` opens another surface; ``command`` runs a shell command.  A bare
    action with neither is a local button the dialog handles itself.
    """

    label: str
    kind: str = "outlined"
    surface: str = ""
    command: str = ""


@dataclass(frozen=True)
class Spec:
    """A complete surface description."""

    key: str
    eyebrow: str
    title: str
    width: int = 640
    confirm: str = "Close"
    intro: str = ""
    sections: Tuple[Section, ...] = ()
    actions: Tuple[Action, ...] = ()

    @property
    def has_intro(self) -> bool:
        return bool(self.intro)

    def search_text(self) -> str:
        """Return every word this surface contributes to a global search."""
        parts = [self.key, self.eyebrow, self.title, self.intro]
        parts.extend(section.search_text() for section in self.sections)
        parts.extend(action.label for action in self.actions)
        return " ".join(part for part in parts if part)


def _tuple(value: Any) -> Tuple[Any, ...]:
    """Coerce a sequence keyword into the immutable tuple the dataclass wants."""
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(value)
    return (value,)


_SEQUENCE_KEYS = (
    "fields",
    "selects",
    "rows",
    "keys",
    "tree",
    "chips",
    "checks",
    "ranges",
    "swatches",
    "commits",
    "faces",
)


def sec(title: str = "", kind: str = "note", **kwargs: Any) -> Section:
    """Build a :class:`Section`, coercing sequence keywords to tuples."""
    if kind not in SECTION_KINDS:
        raise ValueError(f"Unknown section kind: {kind!r}")
    payload: Dict[str, Any] = dict(kwargs)
    for name in _SEQUENCE_KEYS:
        if name in payload:
            payload[name] = _tuple(payload[name])
    return Section(kind=kind, title=title, **payload)


def tex_section(block_id: str, slot_id: str, hint: str = "") -> Section:
    """Build the standard texture-preview section for ``block_id``.

    The tile is a generated placeholder and says so; the real texture arrives
    from a loaded install, a resource pack, or a PNG dropped on the slot.
    """
    return Section(
        kind="texture",
        title="Texture",
        hint=hint or TEXTURE_HINT,
        block_id=block_id,
        slot_id=slot_id,
    )


def _filter_section(section: Section, state: SearchState) -> Section | None:
    """Return ``section`` narrowed to the members matching ``state``."""
    if not state.is_active():
        return section
    narrowed: Dict[str, Any] = {}
    matched_member = False
    for name in (
        "fields",
        "selects",
        "rows",
        "keys",
        "tree",
        "checks",
        "ranges",
        "swatches",
        "commits",
    ):
        members = getattr(section, name)
        if not members:
            continue
        kept = tuple(
            member for member in members if state.matches(member.search_text())
        )
        if kept:
            matched_member = True
        narrowed[name] = kept
    if section.chips:
        kept_chips = tuple(chip for chip in section.chips if state.matches(chip))
        if kept_chips:
            matched_member = True
        narrowed["chips"] = kept_chips
    header_matches = state.matches(
        " ".join(part for part in (section.title, section.hint, section.code) if part)
    )
    if header_matches:
        # A section whose own heading matches keeps all of its members, so a
        # search for a panel name does not silently empty that panel.
        return section
    if not matched_member:
        return None
    return replace(section, **narrowed)


def searchable(spec: Spec, state: SearchState) -> Spec:
    """Return ``spec`` narrowed to whatever matches the window search."""
    if not state.is_active():
        return spec
    sections = []
    for section in spec.sections:
        # Structural sections carry no records of their own; they stay so the
        # window keeps its search field, notes, and gates while filtering.
        if section.kind in ("search", "keygate", "progress", "texture", "note", "code"):
            if state.matches(section.search_text()) or section.kind == "search":
                sections.append(section)
            continue
        narrowed = _filter_section(section, state)
        if narrowed is not None:
            sections.append(narrowed)
    return replace(spec, sections=tuple(sections))
