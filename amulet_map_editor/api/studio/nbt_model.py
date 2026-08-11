"""A wx-free model of one NBT document: its tags, edits, history, and views.

The NBT editor is the most detailed window in the Studio, and almost none of
what makes it detailed is drawing.  Deciding that a byte holding ``0`` is a
boolean and deserves a switch, that an int named ``Count`` belongs between 1
and 64, that a list of compounds named ``Items`` is an inventory rather than an
ordinary list, that retyping a double to a byte will throw away both the
fraction and the magnitude -- all of that is arithmetic and tables, and none of
it needs a display.  Keeping it here means it can be exercised without a
window, and means the dialog is left with the one job of putting the right
control in the right row.

Nothing in this module imports ``wx``, reaches the network, or touches the
filesystem.  The six sample documents are built in memory so the editor has
real content to open before a world has been loaded, and they are rebuilt on
every request so two open windows can never edit each other's tags by accident.
"""

from __future__ import annotations

import itertools
import math
import struct
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence
from typing import Tuple


class SnbtError(ValueError):
    """A refusal to guess at malformed SNBT, carrying where it gave up."""

    def __init__(self, message: str, position: int = -1, excerpt: str = "") -> None:
        self.position = int(position)
        self.excerpt = str(excerpt)
        if position >= 0:
            message = f"{message} (at character {position + 1}: {excerpt!r})"
        super().__init__(message)


class TagType(str, Enum):
    """The twelve NBT tag types, in the order the design lists them."""

    BYTE = "byte"
    SHORT = "short"
    INT = "int"
    LONG = "long"
    FLOAT = "float"
    DOUBLE = "double"
    STRING = "string"
    LIST = "list"
    COMPOUND = "compound"
    BYTE_ARRAY = "byte_array"
    INT_ARRAY = "int_array"
    LONG_ARRAY = "long_array"


#: Every type, in the order the "Change tag type" grid draws them.
TAG_TYPES: Tuple[TagType, ...] = tuple(TagType)


@dataclass(frozen=True)
class TagTypeInfo:
    """Everything the editor needs to know about one tag type.

    ``binary_id`` is the value the type carries in a real NBT stream, which is
    what makes the hex view a hex view of something rather than a decoration.
    """

    tag_type: TagType
    label: str
    badge: str
    binary_id: int
    suffix: str
    kind: str
    minimum: Optional[int]
    maximum: Optional[int]
    element: Optional[TagType]
    hint: str


_INT8 = (-128, 127)
_INT16 = (-32768, 32767)
_INT32 = (-2147483648, 2147483647)
_INT64 = (-9223372036854775808, 9223372036854775807)

#: The static facts about each type.  Ranges are the real storage widths, so a
#: value that will not survive a round trip is reported before it is written
#: rather than after it has silently wrapped.
#:
#: ``label`` and ``hint`` are the design's twelve type definitions word for
#: word, because they are what the "Change tag type" grid draws on its chips and
#: shows in their tooltips.  ``badge`` is the abbreviation the tree line and the
#: form row put in front of a tag's name, again as the design writes it.
TYPE_INFO: Dict[TagType, TagTypeInfo] = {
    TagType.BYTE: TagTypeInfo(
        TagType.BYTE,
        "byte",
        "byte",
        1,
        "b",
        "integer",
        _INT8[0],
        _INT8[1],
        None,
        "8-bit signed integer, often used as a boolean",
    ),
    TagType.SHORT: TagTypeInfo(
        TagType.SHORT,
        "short",
        "short",
        2,
        "s",
        "integer",
        _INT16[0],
        _INT16[1],
        None,
        "16-bit signed integer",
    ),
    TagType.INT: TagTypeInfo(
        TagType.INT,
        "int",
        "int",
        3,
        "",
        "integer",
        _INT32[0],
        _INT32[1],
        None,
        "32-bit signed integer",
    ),
    TagType.LONG: TagTypeInfo(
        TagType.LONG,
        "long",
        "long",
        4,
        "L",
        "integer",
        _INT64[0],
        _INT64[1],
        None,
        "64-bit signed integer",
    ),
    TagType.FLOAT: TagTypeInfo(
        TagType.FLOAT,
        "float",
        "float",
        5,
        "f",
        "float",
        None,
        None,
        None,
        "32-bit floating point",
    ),
    TagType.DOUBLE: TagTypeInfo(
        TagType.DOUBLE,
        "double",
        "double",
        6,
        "d",
        "float",
        None,
        None,
        None,
        "64-bit floating point",
    ),
    TagType.STRING: TagTypeInfo(
        TagType.STRING,
        "string",
        "str",
        8,
        "",
        "string",
        None,
        None,
        None,
        "UTF-8 text",
    ),
    TagType.LIST: TagTypeInfo(
        TagType.LIST,
        "list",
        "list",
        9,
        "",
        "list",
        None,
        None,
        None,
        "Ordered list of one tag type",
    ),
    TagType.COMPOUND: TagTypeInfo(
        TagType.COMPOUND,
        "compound",
        "cmpd",
        10,
        "",
        "compound",
        None,
        None,
        None,
        "Named tag map",
    ),
    TagType.BYTE_ARRAY: TagTypeInfo(
        TagType.BYTE_ARRAY,
        "byte[]",
        "barr",
        7,
        "",
        "array",
        _INT8[0],
        _INT8[1],
        TagType.BYTE,
        "Byte array",
    ),
    TagType.INT_ARRAY: TagTypeInfo(
        TagType.INT_ARRAY,
        "int[]",
        "iarr",
        11,
        "",
        "array",
        _INT32[0],
        _INT32[1],
        TagType.INT,
        "Int array",
    ),
    TagType.LONG_ARRAY: TagTypeInfo(
        TagType.LONG_ARRAY,
        "long[]",
        "larr",
        12,
        "",
        "array",
        _INT64[0],
        _INT64[1],
        TagType.LONG,
        "Long array",
    ),
}

#: The twelve type chips the switcher draws, in order, exactly as the design
#: lists them: the visible label and the one-line tooltip beside it.
TYPE_DEFS: Tuple[Tuple[str, str], ...] = tuple(
    (TYPE_INFO[tag_type].label, TYPE_INFO[tag_type].hint) for tag_type in TAG_TYPES
)

#: Types whose payload is a single number.
NUMERIC_TYPES: Tuple[TagType, ...] = (
    TagType.BYTE,
    TagType.SHORT,
    TagType.INT,
    TagType.LONG,
    TagType.FLOAT,
    TagType.DOUBLE,
)

#: Types whose payload is a run of numbers.
ARRAY_TYPES: Tuple[TagType, ...] = (
    TagType.BYTE_ARRAY,
    TagType.INT_ARRAY,
    TagType.LONG_ARRAY,
)

#: Types whose payload is other tags.
CONTAINER_TYPES: Tuple[TagType, ...] = (TagType.LIST, TagType.COMPOUND)

#: The control kinds :func:`control_for` can ask for.
CONTROL_KINDS: Tuple[str, ...] = (
    "toggle",
    "stepper",
    "slider",
    "select",
    "vector",
    "chips",
    "slots",
    "color",
    "container",
    "longtext",
    "text",
)


def type_label(tag_type: TagType) -> str:
    """Return the human label for a type, as the type grid shows it."""
    return TYPE_INFO[tag_type].label


def type_badge(tag_type: TagType) -> str:
    """Return the three-character badge the tree and form rows draw."""
    return TYPE_INFO[tag_type].badge


def type_for_label(label: str) -> Optional[TagType]:
    """Return the type a visible label names, or ``None`` when it names none."""
    wanted = str(label).strip().casefold()
    for tag_type, info in TYPE_INFO.items():
        if info.label.casefold() == wanted:
            return tag_type
    return None


# ---------------------------------------------------------------------------
# value formatting
# ---------------------------------------------------------------------------


def to_float32(value: float) -> float:
    """Return the value a 32-bit float tag would actually store.

    A Float tag holds four bytes, so the double a caller hands in is not
    generally the number that comes back out.  Snapping on the way in means
    the editor shows what the file will hold rather than what was typed at it.
    """
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return number
    try:
        return struct.unpack(">f", struct.pack(">f", number))[0]
    except (OverflowError, struct.error):
        return math.inf if number > 0 else -math.inf


def format_float(value: float, *, double: bool = True) -> str:
    """Format a real number as the shortest text that reads back as itself.

    A double uses Python's own shortest round-tripping repr; a float uses the
    fewest digits that still land on the same four bytes, so ``0.1`` is shown
    as ``0.1`` rather than as the seventeen digits of the double beside it.  A
    result with no decimal point gains one, because ``3`` and ``3.0`` are
    different tags and the reader should be able to tell which they have.
    """
    number = float(value)
    if math.isnan(number):
        return "NaN"
    if math.isinf(number):
        return "Infinity" if number > 0 else "-Infinity"
    if double:
        text = repr(number)
    else:
        target = to_float32(number)
        text = repr(number)
        for digits in range(1, 10):
            candidate = f"{number:.{digits}g}"
            if to_float32(float(candidate)) == target:
                text = candidate
                break
    if "." not in text and "e" not in text and "E" not in text:
        text += ".0"
    return text


def format_scalar(tag_type: TagType, value: Any) -> str:
    """Format one payload the way SNBT writes it, suffix and all."""
    info = TYPE_INFO[tag_type]
    if info.kind == "integer":
        return f"{int(value)}{info.suffix}"
    if info.kind == "float":
        return f"{format_float(value, double=tag_type is TagType.DOUBLE)}{info.suffix}"
    if info.kind == "string":
        return quote_string(str(value))
    return str(value)


def quote_string(value: str) -> str:
    """Return ``value`` as a double-quoted SNBT string."""
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{escaped}"'


_UNQUOTED_KEY = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.+"
)


def format_key(name: str) -> str:
    """Return a compound key, quoted only when it could not be read back."""
    text = str(name)
    if text and all(character in _UNQUOTED_KEY for character in text):
        return text
    return quote_string(text)


# ---------------------------------------------------------------------------
# the tag tree
# ---------------------------------------------------------------------------

_uid_counter = itertools.count(1)


class Tag:
    """One NBT tag: a name, a type, a payload, and its place in a tree.

    A tag knows its parent so a path, a breadcrumb trail, and a sibling
    uniqueness check are all answerable from the tag itself rather than from a
    separate index that can drift out of step with the tree.  ``uid`` is stable
    for the lifetime of the object and is what the document's history is keyed
    by: a name changes, a position changes, but the tag the user is editing
    does not.
    """

    __slots__ = ("uid", "name", "tag_type", "value", "children", "parent")

    def __init__(
        self,
        name: str,
        tag_type: TagType,
        value: Any = None,
        children: Sequence["Tag"] = (),
    ) -> None:
        self.uid: int = next(_uid_counter)
        self.name: str = str(name)
        self.tag_type: TagType = TagType(tag_type)
        self.parent: Optional["Tag"] = None
        self.children: List["Tag"] = []
        self.value: Any = None
        self.set_payload(value)
        for child in children:
            self.append(child)

    # -- payload -------------------------------------------------------------
    def set_payload(self, value: Any) -> None:
        """Coerce and store a payload appropriate to this tag's type."""
        kind = TYPE_INFO[self.tag_type].kind
        if kind == "integer":
            self.value = coerce_integer(value)
        elif kind == "float":
            self.value = coerce_float(value, single=self.tag_type is TagType.FLOAT)
        elif kind == "string":
            self.value = "" if value is None else str(value)
        elif kind == "array":
            self.value = [coerce_integer(item) for item in (value or ())]
        else:
            self.value = None

    # -- structure -----------------------------------------------------------
    @property
    def is_container(self) -> bool:
        """Return whether this tag holds other tags."""
        return self.tag_type in CONTAINER_TYPES

    @property
    def is_array(self) -> bool:
        """Return whether this tag holds a packed run of numbers."""
        return self.tag_type in ARRAY_TYPES

    @property
    def is_numeric(self) -> bool:
        """Return whether this tag holds a single number."""
        return self.tag_type in NUMERIC_TYPES

    def append(self, child: "Tag", index: Optional[int] = None) -> "Tag":
        """Add ``child`` to this container and return it."""
        if not self.is_container:
            raise TypeError(f"A {type_label(self.tag_type)} tag holds no children.")
        child.detach()
        child.parent = self
        if self.tag_type is TagType.LIST:
            child.name = ""
        if index is None or index >= len(self.children):
            self.children.append(child)
        else:
            self.children.insert(max(0, int(index)), child)
        return child

    def remove(self, child: "Tag") -> bool:
        """Remove ``child`` from this container, reporting whether it was there."""
        try:
            self.children.remove(child)
        except ValueError:
            return False
        child.parent = None
        return True

    def detach(self) -> None:
        """Unhook this tag from whatever currently holds it."""
        if self.parent is not None:
            self.parent.remove(self)

    def index(self) -> int:
        """Return this tag's position in its parent, or ``-1`` at the root."""
        if self.parent is None:
            return -1
        try:
            return self.parent.children.index(self)
        except ValueError:  # pragma: no cover - detached mid-edit
            return -1

    def child(self, name: str) -> Optional["Tag"]:
        """Return the named child of a compound, or ``None``."""
        for item in self.children:
            if item.name == name:
                return item
        return None

    def descendants(self) -> Iterator["Tag"]:
        """Yield every tag beneath this one, depth first."""
        for item in self.children:
            yield item
            yield from item.descendants()

    def count(self) -> int:
        """Return how many tags this subtree contains, including itself."""
        return 1 + sum(1 for _ in self.descendants())

    def ancestors(self) -> List["Tag"]:
        """Return this tag's ancestors, root first."""
        chain: List["Tag"] = []
        node = self.parent
        while node is not None:
            chain.append(node)
            node = node.parent
        chain.reverse()
        return chain

    def clone(self) -> "Tag":
        """Return a detached deep copy carrying fresh identities."""
        copy = Tag(self.name, self.tag_type)
        copy.value = list(self.value) if isinstance(self.value, list) else self.value
        for item in self.children:
            copy.append(item.clone())
        return copy

    # -- naming --------------------------------------------------------------
    def display_name(self) -> str:
        """Return the label this tag shows in a tree or a form row."""
        if self.parent is None:
            return self.name or "root"
        if self.parent.tag_type is TagType.LIST:
            return f"[{self.index()}]"
        return self.name or "(unnamed)"

    def path(self) -> str:
        """Return the dotted path from the root to this tag."""
        return ".".join(self.path_parts()).replace(".[", "[")

    def path_parts(self) -> Tuple[str, ...]:
        """Return the breadcrumb segments from the root down to this tag."""
        return tuple(node.display_name() for node in ([*self.ancestors(), self]))

    # -- summaries -----------------------------------------------------------
    def value_text(self) -> str:
        """Return the payload as text, or the child count for a container."""
        if self.tag_type is TagType.COMPOUND:
            return f"{len(self.children)} entries"
        if self.tag_type is TagType.LIST:
            return f"{len(self.children)} elements"
        if self.is_array:
            return f"{len(self.value)} values"
        return format_scalar(self.tag_type, self.value)

    def tree_label(self) -> str:
        """Return the monospaced line the tag tree draws for this tag."""
        name = self.display_name()
        if self.tag_type is TagType.COMPOUND:
            return f"{name} ({len(self.children)})"
        if self.tag_type is TagType.LIST:
            element = (
                type_label(self.children[0].tag_type) if self.children else "empty"
            )
            return f"{name} [{len(self.children)} {element}]"
        if self.is_array:
            return f"{name} [{len(self.value)}]"
        return f"{name} = {self.value_text()}"

    def search_text(self) -> str:
        """Return everything a tag search should look through for this tag."""
        return " ".join(
            (
                self.display_name(),
                type_label(self.tag_type),
                self.value_text(),
                self.path(),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Tag {self.path()} {type_label(self.tag_type)}>"


def coerce_integer(value: Any) -> int:
    """Return ``value`` as an integer, treating unreadable input as zero."""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return int(value)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def coerce_float(value: Any, *, single: bool = False) -> float:
    """Return ``value`` as a real number, treating unreadable input as zero.

    ``single`` snaps the result to what a 32-bit Float tag can hold, so the
    stored value and the written value are the same number.
    """
    if isinstance(value, bool):
        number = 1.0 if value else 0.0
    else:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.0
    return to_float32(number) if single else number


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationResult:
    """One tag's validity, in a sentence the inspector can show as it stands."""

    ok: bool
    severity: str
    message: str

    def __bool__(self) -> bool:
        return self.ok


def _range_text(minimum: int, maximum: int) -> str:
    return f"{minimum} to {maximum}"


def validate(tag: Tag) -> ValidationResult:
    """Return whether ``tag`` could be written back out, and why not if it could not.

    The checks are the three that actually bite when editing raw data by hand:
    a number too wide for the type holding it, a list whose elements stopped
    agreeing on a type, and two children of one compound sharing a name.  Each
    failure names the offending value or index, because "invalid" on its own
    leaves the reader hunting through a hundred tags.
    """
    info = TYPE_INFO[tag.tag_type]
    name = tag.display_name()

    duplicate = _duplicate_name(tag)
    if duplicate:
        return ValidationResult(
            False,
            "error",
            f'The compound "{duplicate}" already holds another tag named '
            f'"{tag.name}". Names must be unique inside one compound.',
        )

    if info.kind == "integer":
        value = int(tag.value)
        if info.minimum is not None and not info.minimum <= value <= info.maximum:
            return ValidationResult(
                False,
                "error",
                f"{info.label} {name} holds {value}, outside the valid range "
                f"{_range_text(info.minimum, info.maximum)}. Writing it would "
                "wrap the value round.",
            )
        return ValidationResult(
            True,
            "ok",
            f"{info.label} {name} holds {value}, inside the valid range "
            f"{_range_text(info.minimum, info.maximum)}.",
        )

    if info.kind == "float":
        single = tag.tag_type is TagType.FLOAT
        value = float(tag.value)
        if math.isnan(value):
            return ValidationResult(
                False,
                "error",
                f"{info.label} {name} is not a number. Most readers refuse the "
                "whole file rather than the one tag.",
            )
        if math.isinf(value):
            limit = "3.4028235e38" if single else "1.7976931e308"
            return ValidationResult(
                False,
                "error",
                f"{info.label} {name} is infinite. A {info.label} carries at most "
                f"about {limit}, so this value overflowed on the way in.",
            )
        width = (
            "stored in four bytes, to about seven significant digits"
            if single
            else "stored in eight bytes, to about fifteen significant digits"
        )
        return ValidationResult(
            True,
            "ok",
            f"{info.label} {name} holds "
            f"{format_float(value, double=not single)}, {width}.",
        )

    if info.kind == "string":
        encoded = len(str(tag.value).encode("utf-8"))
        if encoded > 65535:
            return ValidationResult(
                False,
                "error",
                f"String {name} encodes to {encoded} bytes; an NBT string holds "
                "at most 65535.",
            )
        return ValidationResult(
            True,
            "ok",
            f"String {name} holds {len(str(tag.value))} characters "
            f"({encoded} bytes once encoded).",
        )

    if info.kind == "array":
        for index, element in enumerate(tag.value):
            if not info.minimum <= int(element) <= info.maximum:
                return ValidationResult(
                    False,
                    "error",
                    f"{info.label} {name} element [{index}] is {element}, outside "
                    f"{_range_text(info.minimum, info.maximum)}.",
                )
        return ValidationResult(
            True,
            "ok",
            f"{info.label} {name} holds {len(tag.value)} values, all inside "
            f"{_range_text(info.minimum, info.maximum)}.",
        )

    if tag.tag_type is TagType.LIST:
        if not tag.children:
            return ValidationResult(
                True, "ok", f"List {name} is empty, which is valid."
            )
        first = tag.children[0].tag_type
        for index, child in enumerate(tag.children):
            if child.tag_type is not first:
                return ValidationResult(
                    False,
                    "error",
                    f"List {name} mixes types: element [0] holds "
                    f"{type_label(first)} and element [{index}] holds "
                    f"{type_label(child.tag_type)}. Every element of a list "
                    "must share one type.",
                )
        return ValidationResult(
            True,
            "ok",
            f"List {name} holds {len(tag.children)} {type_label(first)} elements, "
            "all of one type.",
        )

    seen: Dict[str, int] = {}
    for child in tag.children:
        seen[child.name] = seen.get(child.name, 0) + 1
    repeated = [key for key, total in seen.items() if total > 1]
    if repeated:
        return ValidationResult(
            False,
            "error",
            f'Compound {name} holds more than one tag named "{repeated[0]}". '
            "Names must be unique inside one compound.",
        )
    if "" in seen:
        return ValidationResult(
            False,
            "error",
            f"Compound {name} holds an unnamed tag. Every child of a compound "
            "needs a name.",
        )
    return ValidationResult(
        True,
        "ok",
        f"Compound {name} holds {len(tag.children)} uniquely named tags.",
    )


def _duplicate_name(tag: Tag) -> str:
    """Return the parent's label when a sibling already claims this name."""
    parent = tag.parent
    if parent is None or parent.tag_type is not TagType.COMPOUND:
        return ""
    for sibling in parent.children:
        if sibling is not tag and sibling.name == tag.name:
            return parent.display_name()
    return ""


def validate_tree(tag: Tag) -> ValidationResult:
    """Validate a whole subtree, returning the first real failure it finds."""
    first_warning: Optional[ValidationResult] = None
    for node in [tag, *tag.descendants()]:
        result = validate(node)
        if not result.ok:
            return ValidationResult(
                False, result.severity, f"{node.path()}: {result.message}"
            )
        if result.severity == "warning" and first_warning is None:
            first_warning = ValidationResult(
                True, "warning", f"{node.path()}: {result.message}"
            )
    if first_warning is not None:
        return first_warning
    return ValidationResult(
        True, "ok", f"{tag.count()} tags checked; every one of them is valid."
    )


# ---------------------------------------------------------------------------
# retyping
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetypeReport:
    """What converting a tag to another type would cost, said before it costs it."""

    ok: bool
    lossy: bool
    message: str
    value: Any = None
    children: Tuple[Tag, ...] = ()
    notes: Tuple[str, ...] = ()


def retype_preview(tag: Tag, target: TagType) -> RetypeReport:
    """Describe converting ``tag`` to ``target`` without changing anything.

    Every conversion in NBT is possible in the sense that some value comes out
    of it; the question the editor has to answer is what the user loses on the
    way, so the report names the truncation, the lost precision, or the
    discarded children explicitly instead of leaving them to be discovered.
    """
    target = TagType(target)
    source = tag.tag_type
    if source is target:
        return RetypeReport(
            True,
            False,
            f"{type_label(target)} is already this tag's type; nothing would change.",
            tag.value,
            tuple(tag.children),
        )

    source_info = TYPE_INFO[source]
    target_info = TYPE_INFO[target]
    notes: List[str] = []

    # -- into a container ----------------------------------------------------
    if target in CONTAINER_TYPES:
        children: List[Tag] = []
        if source in CONTAINER_TYPES:
            children = [child.clone() for child in tag.children]
            if target is TagType.LIST and source is TagType.COMPOUND:
                types = {child.tag_type for child in children}
                if len(types) > 1:
                    return RetypeReport(
                        False,
                        True,
                        "This compound holds "
                        + ", ".join(sorted(type_label(item) for item in types))
                        + " tags. A list can only hold one type, so the "
                        "conversion is refused rather than silently dropping "
                        "the tags that do not fit.",
                    )
                if any(child.name for child in children):
                    notes.append("every child tag loses its name")
            if target is TagType.COMPOUND and source is TagType.LIST:
                for index, child in enumerate(children):
                    child.name = str(index)
                notes.append("each element is named by its index")
        elif source in ARRAY_TYPES:
            element = source_info.element or TagType.INT
            children = [
                Tag("" if target is TagType.LIST else str(index), element, item)
                for index, item in enumerate(tag.value)
            ]
            notes.append(
                f"each of the {len(children)} packed values becomes its own "
                f"{type_label(element)} tag"
            )
        else:
            notes.append(f"the value {tag.value_text()} is discarded")
        message = _retype_message(source, target, notes)
        return RetypeReport(
            True, bool(notes), message, None, tuple(children), tuple(notes)
        )

    # -- out of a container --------------------------------------------------
    if source in CONTAINER_TYPES:
        if target in ARRAY_TYPES:
            if not all(child.is_numeric for child in tag.children):
                return RetypeReport(
                    False,
                    True,
                    f"{type_label(source)} {tag.display_name()} holds tags that "
                    f"are not numbers, so it cannot become a "
                    f"{target_info.label}.",
                )
            values = [
                _clamp_integer(int(child.value), target_info, notes, index)
                for index, child in enumerate(tag.children)
            ]
            notes.insert(0, f"{len(values)} child tags become packed values")
            return RetypeReport(
                True,
                True,
                _retype_message(source, target, notes),
                values,
                (),
                tuple(notes),
            )
        notes.append(
            f"the {len(tag.children)} child tags are discarded, because a "
            f"{target_info.label} holds a single value"
        )
        return RetypeReport(
            True,
            True,
            _retype_message(source, target, notes),
            _default_value(target),
            (),
            tuple(notes),
        )

    # -- array to array or scalar -------------------------------------------
    if source in ARRAY_TYPES and target in ARRAY_TYPES:
        values = [
            _clamp_integer(int(item), target_info, notes, index)
            for index, item in enumerate(tag.value)
        ]
        return RetypeReport(
            True,
            bool(notes),
            _retype_message(source, target, notes),
            values,
            (),
            tuple(notes),
        )
    if source in ARRAY_TYPES:
        if target is TagType.STRING:
            text = ", ".join(str(item) for item in tag.value)
            return RetypeReport(
                True,
                True,
                _retype_message(source, target, ["the values become one text line"]),
                text,
                (),
                ("the values become one text line",),
            )
        first = int(tag.value[0]) if tag.value else 0
        notes.append(
            f"only the first of {len(tag.value)} values is kept"
            if len(tag.value) > 1
            else "the packed run becomes a single value"
        )
        value = _convert_number(first, TagType.INT, target, notes)
        return RetypeReport(
            True, True, _retype_message(source, target, notes), value, (), tuple(notes)
        )

    # -- scalar to array -----------------------------------------------------
    if target in ARRAY_TYPES:
        if source is TagType.STRING:
            return RetypeReport(
                False,
                True,
                f"String {tag.display_name()} holds text, so it cannot become a "
                f"{target_info.label}. Retype it to a number first.",
            )
        value = _clamp_integer(int(tag.value), target_info, notes)
        notes.insert(0, "the single value becomes a one-element run")
        return RetypeReport(
            True,
            True,
            _retype_message(source, target, notes),
            [value],
            (),
            tuple(notes),
        )

    # -- scalar to scalar ----------------------------------------------------
    if target is TagType.STRING:
        return RetypeReport(
            True,
            False,
            _retype_message(source, target, ["the number is written out as text"]),
            format_scalar(source, tag.value).strip('"'),
            (),
            ("the number is written out as text",),
        )
    if source is TagType.STRING:
        text = str(tag.value).strip()
        try:
            number = float(text)
        except ValueError:
            notes.append(f'"{text}" is not a number, so the value becomes 0')
            number = 0.0
        value = _convert_number(number, TagType.DOUBLE, target, notes)
        return RetypeReport(
            True,
            bool(notes),
            _retype_message(source, target, notes),
            value,
            (),
            tuple(notes),
        )
    value = _convert_number(tag.value, source, target, notes)
    return RetypeReport(
        True,
        bool(notes),
        _retype_message(source, target, notes),
        value,
        (),
        tuple(notes),
    )


def _retype_message(source: TagType, target: TagType, notes: Sequence[str]) -> str:
    """Compose the sentence the type grid shows before a conversion runs."""
    head = f"{type_label(source)} becomes {type_label(target)}"
    if not notes:
        return f"{head}. Nothing is lost."
    return f"{head}, but " + "; ".join(notes) + "."


def _default_value(tag_type: TagType) -> Any:
    kind = TYPE_INFO[tag_type].kind
    if kind == "integer":
        return 0
    if kind == "float":
        return 0.0
    if kind == "string":
        return ""
    if kind == "array":
        return []
    return None


def _clamp_integer(
    value: int, info: TagTypeInfo, notes: List[str], index: Optional[int] = None
) -> int:
    """Clamp one integer into a type's width, recording the loss when it bites.

    ``index`` names the array position for a packed run; a single value passes
    ``None``, because "at [0]" on a scalar reads as though there were others.
    """
    if info.minimum is None or info.maximum is None:
        return int(value)
    if info.minimum <= value <= info.maximum:
        return int(value)
    where = f" at [{index}]" if index is not None else ""
    limit = info.minimum if value < info.minimum else info.maximum
    notes.append(
        f"{value}{where} does not fit in a {info.label} and is clamped to {limit}"
    )
    return limit


def _convert_number(
    value: Any, source: TagType, target: TagType, notes: List[str]
) -> Any:
    """Convert one number between two scalar types, recording what it costs."""
    target_info = TYPE_INFO[target]
    number = float(value)
    if target_info.kind == "float":
        if target is TagType.FLOAT:
            stored = struct.unpack(">f", struct.pack(">f", number))[0]
            if stored != number:
                notes.append(
                    f"a 32-bit float stores {format_float(number)} as "
                    f"{format_float(stored)}"
                )
            return stored
        return number
    truncated = int(number)
    if truncated != number:
        notes.append(
            f"the fractional part of {format_float(number)} is discarded, "
            f"leaving {truncated}"
        )
    return _clamp_integer(truncated, target_info, notes)


# ---------------------------------------------------------------------------
# control selection
# ---------------------------------------------------------------------------

#: Byte tags whose name says plainly that the byte is a boolean.  Values other
#: than 0 and 1 disqualify a tag regardless of its name, because a switch that
#: cannot show 2 would silently rewrite it.
BOOLEAN_NAMES: frozenset = frozenset(
    {
        "allowcommands",
        "bonus_chest",
        "custonnametvisible",
        "customnamevisible",
        "difficultylocked",
        "enabled",
        "findable",
        "flying",
        "generate_features",
        "glowing",
        "hardcore",
        "initialized",
        "instabuild",
        "invisible",
        "invulnerable",
        "islighton",
        "keeppacked",
        "mayfly",
        "maybuild",
        "nogravity",
        "onground",
        "persistencerequired",
        "powered",
        "raining",
        "seencredits",
        "silent",
        "snapshot",
        "thundering",
        "unbreakable",
    }
)

#: Prefixes that mark a byte as a boolean when its value is 0 or 1.
_BOOLEAN_PREFIXES: Tuple[str, ...] = ("is", "has", "can", "should", "allow")

#: Tags whose text is prose rather than an identifier.
LONGTEXT_NAMES: frozenset = frozenset(
    {
        "command",
        "customname",
        "lastoutput",
        "lore",
        "motd",
        "text1",
        "text2",
        "text3",
        "text4",
        "front_text",
        "back_text",
    }
)

#: Tags carrying a packed RGB colour.
COLOUR_NAMES: frozenset = frozenset(
    {"color", "colour", "customcolor", "displaycolor", "mapcolor", "beamcolor"}
)

#: Lists whose compound elements are inventory stacks.
INVENTORY_NAMES: frozenset = frozenset(
    {"items", "inventory", "enderitems", "armoritems", "handitems", "itemstacks"}
)

#: Lists and compounds that describe a point or a direction in the world.
VECTOR_NAMES: frozenset = frozenset(
    {"pos", "motion", "rotation", "spawnpos", "wanderingtraderoriginpos", "tilepos"}
)

#: Axis captions per component count, so a two-component rotation is not
#: mislabelled as an x/y pair.
_AXES: Dict[int, Tuple[str, ...]] = {
    2: ("yaw", "pitch"),
    3: ("x", "y", "z"),
    4: ("x", "y", "z", "w"),
}

#: The colour each axis caption is drawn in, as the design paints them: red
#: east-west, green up-down, blue north-south.  An axis with no entry -- a yaw
#: or a pitch -- takes the theme's primary colour, which is what the empty
#: string means everywhere a colour is asked for here.
AXIS_COLOURS: Dict[str, str] = {
    "x": "#C0392B",
    "y": "#1E8449",
    "z": "#2471A3",
}


def axis_colour(axis: str) -> str:
    """Return the colour an axis caption is drawn in, or "" for the theme's own."""
    return AXIS_COLOURS.get(str(axis).casefold(), "")


#: Strings with a small, known set of legal values.  Every list the design
#: writes out is here verbatim, in the design's order, because the order is what
#: the select offers and -- for the numeric ones below -- what each value means.
ENUM_OPTIONS: Dict[str, Tuple[str, ...]] = {
    "difficulty": ("peaceful", "easy", "normal", "hard"),
    "dimension": (
        "minecraft:overworld",
        "minecraft:the_nether",
        "minecraft:the_end",
    ),
    "facing": ("north", "east", "south", "west"),
    "gametype": ("survival", "creative", "adventure", "spectator"),
    "generatorname": ("default", "flat", "largeBiomes", "amplified", "buffet"),
    "loottable": (
        "(none)",
        "minecraft:chests/simple_dungeon",
        "minecraft:chests/village/village_armorer",
    ),
    "mode": ("save", "load", "corner", "data"),
    "mirror": ("NONE", "LEFT_RIGHT", "FRONT_BACK"),
    "playergametype": ("survival", "creative", "adventure", "spectator"),
    "profession": ("librarian", "farmer", "armorer", "cleric", "nitwit", "none"),
    "rotationmode": ("NONE", "CLOCKWISE_90", "CLOCKWISE_180", "COUNTERCLOCKWISE_90"),
    "status": ("full", "features", "liquid_carvers", "structure_starts", "empty"),
    "type": (
        "minecraft:desert",
        "minecraft:jungle",
        "minecraft:plains",
        "minecraft:savanna",
        "minecraft:snow",
        "minecraft:swamp",
        "minecraft:taiga",
    ),
}

#: The enumerations whose tag holds an ordinal rather than the word.  The word
#: is what the design's select shows; the number is what the file holds, and the
#: two are the same list read from either end.
NUMERIC_ENUMS: Dict[str, Tuple[str, ...]] = {
    "difficulty": ENUM_OPTIONS["difficulty"],
    "gametype": ENUM_OPTIONS["gametype"],
    "playergametype": ENUM_OPTIONS["playergametype"],
}


def enum_label(name: str, value: int) -> str:
    """Return the word an ordinal enumeration stands for, or the bare number."""
    options = NUMERIC_ENUMS.get(str(name).casefold())
    index = int(value)
    if options is None or not 0 <= index < len(options):
        return str(index)
    return options[index]


def enum_index(name: str, text: str) -> Optional[int]:
    """Return the number a word stands for, or ``None`` when it stands for none."""
    options = NUMERIC_ENUMS.get(str(name).casefold())
    if options is None:
        return None
    wanted = str(text).strip().casefold()
    for index, option in enumerate(options):
        if option.casefold() == wanted:
            return index
    return None


#: Semantic ranges that are tighter than the storage type allows.  A stepper or
#: a slider offering the whole width of an int for a value the game only reads
#: from 0 to 15 is technically correct and practically useless.
#: Every range the design states outright -- Air 0 … 300 stepping by 20, Fire
#: -1 … 800, DayTime 0 … 24000 stepping by 100, and the rest -- is that range
#: here, step included, because the step is how far one press of a stepper or
#: one notch of a slider actually moves the value.
TAG_RANGES: Dict[str, Tuple[float, float, float]] = {
    "absorptionamount": (0.0, 20.0, 0.5),
    "air": (0.0, 300.0, 20.0),
    "burntime": (0.0, 1600.0, 1.0),
    "cooktime": (0.0, 200.0, 1.0),
    "cooktimetotal": (0.0, 200.0, 1.0),
    "count": (1.0, 64.0, 1.0),
    "damage": (0.0, 1561.0, 1.0),
    "daytime": (0.0, 24000.0, 100.0),
    "delay": (0.0, 800.0, 1.0),
    "difficulty": (0.0, 3.0, 1.0),
    "fire": (-1.0, 800.0, 20.0),
    "flyspeed": (0.0, 1.0, 0.01),
    "foodexhaustionlevel": (0.0, 4.0, 0.1),
    "foodlevel": (0.0, 20.0, 1.0),
    "foodsaturationlevel": (0.0, 20.0, 0.5),
    "health": (0.0, 20.0, 0.5),
    "inhabitedtime": (0.0, 72000.0, 100.0),
    "level": (1.0, 5.0, 1.0),
    "lvl": (0.0, 255.0, 1.0),
    "maxnearbyentities": (0.0, 64.0, 1.0),
    "maxspawndelay": (0.0, 800.0, 1.0),
    "minspawndelay": (0.0, 200.0, 1.0),
    "playergametype": (0.0, 3.0, 1.0),
    "raintime": (0.0, 180000.0, 1000.0),
    "requiredplayerrange": (0.0, 64.0, 1.0),
    "selecteditemslot": (0.0, 8.0, 1.0),
    "slot": (0.0, 40.0, 1.0),
    "spawncount": (1.0, 64.0, 1.0),
    "spawnrange": (1.0, 16.0, 1.0),
    "walkspeed": (0.0, 1.0, 0.01),
    "xplevel": (0.0, 24791.0, 1.0),
    "xpp": (0.0, 1.0, 0.01),
    "y": (-64.0, 320.0, 1.0),
    "ypos": (-4.0, 20.0, 1.0),
}

#: The bounded whole numbers the design draws as a slider rather than a
#: stepper.  There is no rule to derive this from: the design gives rainTime a
#: stepper over 180,000 values and InhabitedTime a slider over 72,000, so which
#: control a tag gets is a decision about the tag rather than about its width.
#: Bounded real numbers are always sliders, so they are not listed here.
SLIDER_NAMES: frozenset = frozenset(
    {"damage", "daytime", "foodlevel", "health", "inhabitedtime"}
)

#: One line of plain explanation per well-known tag, shown under its name.
#: Wherever the design writes a hint for a tag, that hint is this hint, word for
#: word.  Six names -- ``id``, ``CustomName``, ``Pos``, ``Health``, ``UUID`` and
#: ``SpawnPos`` -- carry a different sentence in each source the design shows
#: them in ("Entity type identifier" against "Item identifier"), so what sits
#: here is the sentence that is true wherever the tag turns up, and the exact
#: per-source wording lives in :data:`SOURCE_FIELDS`.
TAG_HINTS: Dict[str, str] = {
    "abilities": "What this player may do: flight, building, and invulnerability.",
    "air": "Remaining breath in ticks.",
    "allowcommands": "Enables cheats in single player.",
    "armoritems": "Feet, legs, chest, head — in that order.",
    "block_entities": "Block entities stored in this chunk.",
    "bordersize": "World border diameter in blocks.",
    "brain": "Memory module compound. Opens as its own subtree.",
    "color": "Leather and firework colour as a packed integer.",
    "count": "Stack size. Vanilla clamps to the item's maximum.",
    "customname": "The display name shown in the world, as raw JSON text.",
    "damage": "Durability used. 0 is undamaged.",
    "dataversion": "The world format revision this data was written by.",
    "daytime": "Time of day in ticks. 0 is dawn, 18000 is midnight.",
    "difficulty": "World difficulty.",
    "dimension": "Dimension the player is in.",
    "fire": "Burn ticks. -1 means not burning.",
    "foodlevel": "Hunger, 0 to 20.",
    "gametype": "Default game mode for new players.",
    "glowing": "Draws the outline through blocks.",
    "hardcore": "Death locks the world to spectator.",
    "health": "Current hit points. A player caps at 20.",
    "hideflags": "Bit field hiding tooltip sections.",
    "enchantments": "Each entry pairs an id with a level.",
    "enderitems": "Ender chest contents.",
    "gamerules": "Every game rule as a named tag.",
    "heightmaps": "Packed surface heights, used for lighting and spawning.",
    "id": "The namespaced identifier of the block, entity, or item.",
    "inhabitedtime": "Ticks players have spent in this chunk. Affects local difficulty.",
    "inventory": "Hotbar first, then main inventory.",
    "invulnerable": "Ignores all damage sources.",
    "items": "Inventory contents. Click a slot to edit its stack.",
    "islighton": "Whether the stored light data is trusted rather than recomputed.",
    "keeppacked": "Kept packed means the block entity is not ticked yet.",
    "lastupdate": "Game tick when the chunk was last saved.",
    "level": "Trading level, 1 to 5.",
    "levelname": "World name shown in the game's world list.",
    "lock": "Item name required to open the container.",
    "lore": "One JSON text component per line.",
    "loottable": "Unrolled table. Editing Items clears this reference.",
    "lvl": "Enchantment level.",
    "motion": "Velocity in blocks per tick, one component per axis.",
    "noai": "Freezes behaviour and pathfinding.",
    "persistencerequired": "When on, the entity never despawns.",
    "playergametype": "Game mode for this player.",
    "pos": "Position in the world, in blocks.",
    "position": "Block coordinates of this block entity.",
    "profession": "Profession identifier.",
    "raining": "Current weather state.",
    "randomseed": "Generation seed. Existing chunks keep their terrain.",
    "raintime": "Ticks until the weather changes.",
    "references": "Structure bounding-box references.",
    "rotation": "Yaw then pitch, in degrees.",
    "sections": "One compound per 16-block vertical section.",
    "selecteditemslot": "Which hot-bar slot is held, 0 to 8.",
    "silent": "Suppresses the entity's sounds.",
    "slot": "Inventory slot index.",
    "spawncount": "How many mobs one successful spawner attempt makes.",
    "status": "Generation stage of this chunk.",
    "time": "Total world age in ticks, unaffected by sleeping.",
    "unbreakable": "Durability never decreases.",
    "uuid": "A 128-bit identity stored as four signed integers.",
    "world_surface": "Packed height values, 256 entries.",
    "worldgensettings": "Generator type and dimension settings.",
    "x": "Block position on the east-west axis.",
    "xplevel": "Experience level.",
    "xpos": "Chunk coordinates.",
    "xpp": "Progress towards the next level, from 0 to 1.",
    "y": "Block position on the vertical axis.",
    "z": "Block position on the north-south axis.",
    "zpos": "Chunk coordinates.",
}

#: The swatch row the design puts beside a colour tag: six named colours, in
#: this order, each one a real hex value rather than a theme token.
COLOUR_SWATCHES: Tuple[Tuple[str, str], ...] = (
    ("Teal", "#82D5CC"),
    ("Red", "#C0392B"),
    ("Green", "#1E8449"),
    ("Blue", "#2471A3"),
    ("Gold", "#D4A017"),
    ("Purple", "#6750A4"),
)

#: The sixteen dye colours.  The design's colour control offers the six above
#: rather than these, but a picker that means to name a Minecraft colour still
#: needs the sixteen the game itself has, so they stay.
DYE_COLOURS: Tuple[Tuple[str, str], ...] = (
    ("White", "#F9FFFE"),
    ("Orange", "#F9801D"),
    ("Magenta", "#C74EBD"),
    ("Light blue", "#3AB3DA"),
    ("Yellow", "#FED83D"),
    ("Lime", "#80C71F"),
    ("Pink", "#F38BAA"),
    ("Gray", "#474F52"),
    ("Light gray", "#9D9D97"),
    ("Cyan", "#169C9C"),
    ("Purple", "#8932B8"),
    ("Blue", "#3C44AA"),
    ("Brown", "#835432"),
    ("Green", "#5E7C16"),
    ("Red", "#B02E26"),
    ("Black", "#1D1D21"),
)


@dataclass(frozen=True)
class ControlSpec:
    """Which editor control a tag deserves, and everything it needs to draw.

    The dialog reads this and builds one control; it never re-decides the kind
    itself, so the same tag gets the same control wherever it is shown.
    """

    kind: str
    label: str = ""
    hint: str = ""
    value: str = ""
    number: float = 0.0
    minimum: float = 0.0
    maximum: float = 0.0
    step: float = 1.0
    integral: bool = True
    options: Tuple[str, ...] = ()
    parts: Tuple[Tuple[str, str], ...] = ()
    chips: Tuple[str, ...] = ()
    slots: Tuple[Mapping[str, Any], ...] = ()
    swatches: Tuple[Tuple[str, str], ...] = ()
    colour: str = ""
    placeholder: str = ""
    boolean: bool = False
    #: One colour per entry in :attr:`parts`, in the same order.  An empty
    #: string asks for the theme's primary colour rather than a fixed one.
    axis_colours: Tuple[str, ...] = ()
    #: The bounds caption a stepper draws beside its entry, as the design
    #: writes it: "0 … 300", "-1 … 800", "1 … 5".
    range_text: str = ""


def range_caption(minimum: float, maximum: float) -> str:
    """Return the "low … high" caption a stepper shows beside its entry."""

    def figure(number: float) -> str:
        return str(int(number)) if float(number).is_integer() else format_float(number)

    return f"{figure(minimum)} … {figure(maximum)}"


def tag_hint(tag: Tag) -> str:
    """Return the explanatory line shown under a field's name."""
    known = TAG_HINTS.get(tag.name.casefold())
    if known:
        return known
    return TYPE_INFO[tag.tag_type].hint


def _slot_short(item_id: str) -> str:
    """Abbreviate an item identifier to the short word a slot cell shows.

    The design labels its own cells by hand -- ``carved_pumpkin`` is captioned
    "hat" -- so no rule reproduces them and the drawn samples carry their
    captions as data.  What is left for a stack nobody has captioned is the
    plainest thing that still reads: the last word of the identifier, cut to
    the width one cell has.
    """
    base = str(item_id).split(":")[-1]
    parts = [part for part in base.split("_") if part]
    if not parts:
        return "?"
    return parts[-1][:6].casefold()


def _slot_dicts(tag: Tag) -> Tuple[Mapping[str, Any], ...]:
    """Describe each compound element of an inventory list as one slot.

    Every element becomes one cell, in list order.  The design's own grids
    leave gaps where a slot index is unused, which is a statement about those
    particular chests rather than a rule -- a player inventory numbers its
    helmet 103 -- so the drawn gaps are transcribed in :data:`SOURCE_FIELDS`
    and an arbitrary list is packed rather than spread over a hundred cells.
    """
    slots: List[Mapping[str, Any]] = []
    for index, child in enumerate(tag.children):
        item = child.child("id")
        count = child.child("Count")
        slot_index = child.child("Slot")
        item_id = str(item.value) if item is not None else ""
        number = int(count.value) if count is not None else 1
        position = int(slot_index.value) if slot_index is not None else index
        stack = f" ×{number}" if number > 1 else ""
        slots.append(
            {
                "short": _slot_short(item_id) if item_id else str(position),
                "count": str(number),
                "title": f"Slot {position} · {item_id or 'no identifier'}{stack}",
                "block_id": item_id,
                "index": index,
            }
        )
    return tuple(slots)


def _vector_parts(tag: Tag) -> Tuple[Tuple[str, str], ...]:
    """Return the axis captions and values a vector row shows."""
    if tag.tag_type is TagType.COMPOUND:
        parts = []
        for axis in ("x", "y", "z"):
            child = next(
                (item for item in tag.children if item.name.casefold() == axis),
                None,
            )
            if child is not None:
                parts.append((axis, _plain_number(child)))
        return tuple(parts)
    axes = _AXES.get(len(tag.children), tuple(str(i) for i in range(len(tag.children))))
    return tuple(
        (axes[index], _plain_number(child)) for index, child in enumerate(tag.children)
    )


def _plain_number(tag: Tag) -> str:
    """Return a numeric payload without its type suffix, for entry fields."""
    if tag.tag_type in (TagType.FLOAT, TagType.DOUBLE):
        return format_float(tag.value, double=tag.tag_type is TagType.DOUBLE)
    return str(int(tag.value))


def _is_vector(tag: Tag) -> bool:
    """Return whether this tag is an x/y/z-style group rather than a plain container."""
    name = tag.name.casefold()
    if tag.tag_type is TagType.LIST:
        return (
            name in VECTOR_NAMES
            and 2 <= len(tag.children) <= 4
            and all(child.is_numeric for child in tag.children)
        )
    if tag.tag_type is TagType.COMPOUND:
        axes = {child.name.casefold() for child in tag.children if child.is_numeric}
        return {"x", "y", "z"}.issubset(axes) and len(tag.children) <= 4
    return False


def _is_boolean_byte(tag: Tag) -> bool:
    """Return whether a byte is standing in for a boolean."""
    if tag.tag_type is not TagType.BYTE or int(tag.value) not in (0, 1):
        return False
    name = tag.name.casefold()
    if name in BOOLEAN_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in _BOOLEAN_PREFIXES)


def _range_for(tag: Tag) -> Optional[Tuple[float, float, float]]:
    """Return the range a bounded control should offer, or ``None`` for none.

    A semantic range is the usual range, not a law: a player's helmet sits in
    slot 103 while a chest's slots stop at 26, and a boss carries more than
    twenty hit points.  A control built from the narrow range would clamp the
    value it was opened to show, which destroys data at a glance, so a value
    already outside the declared range widens the control to the storage type's
    own width -- or drops the bounded control entirely when the type has no
    integer width to fall back on.
    """
    if not tag.is_numeric:
        # A name is not a type: an item's ``Slot`` is a number, an attribute
        # modifier's ``Slot`` is the text "mainhand".
        return None
    bounds = TAG_RANGES.get(tag.name.casefold())
    if bounds is None:
        return None
    minimum, maximum, step = bounds
    value = float(tag.value)
    if minimum <= value <= maximum:
        return bounds
    info = TYPE_INFO[tag.tag_type]
    if info.minimum is None or info.maximum is None:
        return None
    return (float(info.minimum), float(info.maximum), step)


def colour_hex(value: int) -> str:
    """Return a packed integer colour as ``#RRGGBB``."""
    packed = int(value) & 0xFFFFFF
    return f"#{packed:06X}"


def colour_value(text: str) -> int:
    """Return a ``#RRGGBB`` string as the packed integer NBT stores."""
    cleaned = str(text).strip().lstrip("#")
    try:
        return int(cleaned[:6], 16)
    except ValueError:
        return 0


def control_for(tag: Tag) -> ControlSpec:
    """Return the control this tag deserves, and the numbers it needs.

    The order of the checks is the order of specificity: a meaning the tag
    carries -- a boolean, a colour, a position, an inventory -- beats the
    generic control its storage type would otherwise get, because the storage
    type is what NBT had available rather than what the value is.
    """
    label = tag.display_name()
    hint = tag_hint(tag)

    if _is_vector(tag):
        parts = _vector_parts(tag)
        return ControlSpec(
            "vector",
            label,
            hint,
            value=" ".join(value for _axis, value in parts),
            parts=parts,
            axis_colours=tuple(axis_colour(axis) for axis, _value in parts),
        )

    if tag.tag_type is TagType.LIST and tag.name.casefold() in INVENTORY_NAMES:
        if tag.children and all(
            child.tag_type is TagType.COMPOUND for child in tag.children
        ):
            return ControlSpec(
                "slots",
                label,
                hint,
                value=f"{len(tag.children)} stacks",
                slots=_slot_dicts(tag),
            )

    if tag.is_container:
        return ControlSpec("container", label, hint, value=tag.value_text())

    if tag.is_array:
        return ControlSpec(
            "chips",
            label,
            hint,
            value=tag.value_text(),
            chips=tuple(str(item) for item in tag.value),
        )

    if _is_boolean_byte(tag):
        return ControlSpec(
            "toggle",
            label,
            hint,
            value=format_scalar(tag.tag_type, tag.value),
            boolean=bool(int(tag.value)),
            number=float(tag.value),
        )

    if tag.tag_type in (TagType.INT, TagType.LONG) and (
        tag.name.casefold() in COLOUR_NAMES
    ):
        return ControlSpec(
            "color",
            label,
            hint,
            value=colour_hex(int(tag.value)),
            number=float(tag.value),
            colour=colour_hex(int(tag.value)),
            swatches=COLOUR_SWATCHES,
        )

    bounds = _range_for(tag)
    if tag.tag_type in (TagType.FLOAT, TagType.DOUBLE):
        if bounds is not None:
            minimum, maximum, step = bounds
            return ControlSpec(
                "slider",
                label,
                hint,
                value=format_scalar(tag.tag_type, tag.value),
                number=float(tag.value),
                minimum=minimum,
                maximum=maximum,
                step=step,
                integral=False,
                range_text=range_caption(minimum, maximum),
            )
        return ControlSpec(
            "text",
            label,
            hint,
            value=_plain_number(tag),
            number=float(tag.value),
            integral=False,
            placeholder="A real number",
        )

    if tag.is_numeric:
        info = TYPE_INFO[tag.tag_type]
        if bounds is None and tag.tag_type is TagType.LONG:
            # A stepper reports its own bounds, and no float can hold a Long's
            # bounds exactly -- the readout would be off by one at each end.
            # Seeds and timestamps are typed rather than stepped anyway.
            return ControlSpec(
                "text",
                label,
                hint,
                value=str(int(tag.value)),
                number=float(tag.value),
                placeholder=f"A whole number, {info.minimum} to {info.maximum}",
            )
        if bounds is not None:
            minimum, maximum, step = bounds
        else:
            minimum, maximum, step = float(info.minimum), float(info.maximum), 1.0
        # Which of the two bounded controls a whole number gets is a decision
        # the design makes tag by tag rather than by width: rainTime steps
        # through 180,000 values while InhabitedTime slides through 72,000.
        kind = "slider" if tag.name.casefold() in SLIDER_NAMES else "stepper"
        return ControlSpec(
            kind,
            label,
            hint,
            value=str(int(tag.value)),
            number=float(tag.value),
            minimum=minimum,
            maximum=maximum,
            step=step,
            range_text=range_caption(minimum, maximum),
        )

    text = str(tag.value)
    options = ENUM_OPTIONS.get(tag.name.casefold())
    if options is None and text.casefold() in ("true", "false"):
        options = ("true", "false")
    if options is not None:
        choices = tuple(options)
        if text and text not in choices:
            choices = choices + (text,)
        return ControlSpec("select", label, hint, value=text, options=choices)

    if tag.name.casefold() in LONGTEXT_NAMES or "\n" in text or len(text) > 48:
        return ControlSpec(
            "longtext", label, hint, value=text, placeholder="Text, JSON, or a command"
        )

    return ControlSpec("text", label, hint, value=text, placeholder="Text")


# ---------------------------------------------------------------------------
# SNBT
# ---------------------------------------------------------------------------


def to_snbt(tag: Tag, *, indent: int = 2, pretty: bool = True) -> str:
    """Serialise a tag's payload as SNBT.

    The root's own name is deliberately absent: SNBT describes a value, and a
    named root is a property of the file it came from rather than of the value
    itself, so writing one out would produce text no reader accepts back.
    """
    return _write_value(tag, 0, max(0, int(indent)), bool(pretty))


def _write_value(tag: Tag, depth: int, indent: int, pretty: bool) -> str:
    if tag.tag_type is TagType.COMPOUND:
        if not tag.children:
            return "{}"
        pad = " " * (indent * (depth + 1)) if pretty else ""
        close = " " * (indent * depth) if pretty else ""
        separator = ",\n" if pretty else ","
        body = separator.join(
            f"{pad}{format_key(child.name)}: "
            f"{_write_value(child, depth + 1, indent, pretty)}"
            for child in tag.children
        )
        return "{\n" + body + "\n" + close + "}" if pretty else "{" + body + "}"
    if tag.tag_type is TagType.LIST:
        if not tag.children:
            return "[]"
        simple = all(
            not child.is_container and not child.is_array for child in tag.children
        )
        if simple or not pretty:
            body = ", ".join(
                _write_value(child, depth, indent, False) for child in tag.children
            )
            return f"[{body}]"
        pad = " " * (indent * (depth + 1))
        close = " " * (indent * depth)
        body = ",\n".join(
            f"{pad}{_write_value(child, depth + 1, indent, pretty)}"
            for child in tag.children
        )
        return "[\n" + body + "\n" + close + "]"
    if tag.is_array:
        prefix = {
            TagType.BYTE_ARRAY: "B;",
            TagType.INT_ARRAY: "I;",
            TagType.LONG_ARRAY: "L;",
        }[tag.tag_type]
        element = TYPE_INFO[tag.tag_type].element or TagType.INT
        suffix = TYPE_INFO[element].suffix
        body = ", ".join(f"{int(item)}{suffix}" for item in tag.value)
        return f"[{prefix}{body}]"
    return format_scalar(tag.tag_type, tag.value)


_NUMBER_SUFFIXES: Dict[str, TagType] = {
    "b": TagType.BYTE,
    "s": TagType.SHORT,
    "l": TagType.LONG,
    "f": TagType.FLOAT,
    "d": TagType.DOUBLE,
}

_UNQUOTED = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.+"
)


class _SnbtParser:
    """A recursive-descent SNBT reader that refuses rather than guesses."""

    def __init__(self, text: str) -> None:
        self.text = str(text)
        self.position = 0

    # -- primitives ----------------------------------------------------------
    def error(self, message: str) -> SnbtError:
        excerpt = self.text[self.position : self.position + 24]
        return SnbtError(message, self.position, excerpt)

    def skip_space(self) -> None:
        while self.position < len(self.text) and self.text[self.position].isspace():
            self.position += 1

    def peek(self) -> str:
        return self.text[self.position] if self.position < len(self.text) else ""

    def expect(self, character: str) -> None:
        self.skip_space()
        if self.peek() != character:
            raise self.error(f"Expected {character!r}")
        self.position += 1

    # -- values --------------------------------------------------------------
    def parse(self, name: str) -> Tag:
        self.skip_space()
        tag = self.parse_value(name)
        self.skip_space()
        if self.position < len(self.text):
            raise self.error("Unexpected text after the value ended")
        return tag

    def parse_value(self, name: str) -> Tag:
        self.skip_space()
        character = self.peek()
        if not character:
            raise self.error("The text ended where a value was expected")
        if character == "{":
            return self.parse_compound(name)
        if character == "[":
            return self.parse_list(name)
        if character in "\"'":
            return Tag(name, TagType.STRING, self.parse_quoted())
        return self.parse_bare(name)

    def parse_compound(self, name: str) -> Tag:
        self.expect("{")
        tag = Tag(name, TagType.COMPOUND)
        self.skip_space()
        if self.peek() == "}":
            self.position += 1
            return tag
        while True:
            self.skip_space()
            key = self.parse_key()
            self.expect(":")
            tag.append(self.parse_value(key))
            self.skip_space()
            if self.peek() == ",":
                self.position += 1
                continue
            self.expect("}")
            return tag

    def parse_key(self) -> str:
        self.skip_space()
        if self.peek() in "\"'":
            return self.parse_quoted()
        start = self.position
        while self.position < len(self.text) and self.text[self.position] in _UNQUOTED:
            self.position += 1
        if start == self.position:
            raise self.error("Expected a tag name")
        return self.text[start : self.position]

    def parse_list(self, name: str) -> Tag:
        self.expect("[")
        self.skip_space()
        array_type = self._array_prefix()
        if array_type is not None:
            return self._parse_array(name, array_type)
        tag = Tag(name, TagType.LIST)
        self.skip_space()
        if self.peek() == "]":
            self.position += 1
            return tag
        while True:
            tag.append(self.parse_value(""))
            self.skip_space()
            if self.peek() == ",":
                self.position += 1
                continue
            self.expect("]")
            break
        types = {child.tag_type for child in tag.children}
        if len(types) > 1:
            raise self.error(
                "A list must hold one type, but this one mixes "
                + ", ".join(sorted(type_label(item) for item in types))
            )
        return tag

    def _array_prefix(self) -> Optional[TagType]:
        if self.position + 1 < len(self.text) and self.text[self.position + 1] == ";":
            marker = self.text[self.position].upper()
            mapping = {
                "B": TagType.BYTE_ARRAY,
                "I": TagType.INT_ARRAY,
                "L": TagType.LONG_ARRAY,
            }
            if marker in mapping:
                self.position += 2
                return mapping[marker]
        return None

    def _parse_array(self, name: str, array_type: TagType) -> Tag:
        values: List[int] = []
        self.skip_space()
        if self.peek() == "]":
            self.position += 1
            return Tag(name, array_type, values)
        while True:
            element = self.parse_bare("")
            if not element.is_numeric:
                raise self.error(
                    f"{type_label(array_type)} elements must be numbers; this "
                    f"one is a {type_label(element.tag_type)}"
                )
            values.append(int(element.value))
            self.skip_space()
            if self.peek() == ",":
                self.position += 1
                continue
            self.expect("]")
            return Tag(name, array_type, values)

    def parse_quoted(self) -> str:
        quote = self.peek()
        self.position += 1
        out: List[str] = []
        escapes = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "'": "'"}
        while True:
            if self.position >= len(self.text):
                raise self.error("A quoted string was never closed")
            character = self.text[self.position]
            self.position += 1
            if character == "\\":
                if self.position >= len(self.text):
                    raise self.error("A string ended in an unfinished escape")
                following = self.text[self.position]
                self.position += 1
                out.append(escapes.get(following, following))
                continue
            if character == quote:
                return "".join(out)
            out.append(character)

    def parse_bare(self, name: str) -> Tag:
        self.skip_space()
        start = self.position
        while self.position < len(self.text) and self.text[self.position] in _UNQUOTED:
            self.position += 1
        raw = self.text[start : self.position]
        if not raw:
            raise self.error("Expected a value")
        lowered = raw.casefold()
        if lowered == "true":
            return Tag(name, TagType.BYTE, 1)
        if lowered == "false":
            return Tag(name, TagType.BYTE, 0)
        suffix = raw[-1].casefold()
        body = raw[:-1]
        if suffix in _NUMBER_SUFFIXES and body not in ("", "-", "+"):
            tag_type = _NUMBER_SUFFIXES[suffix]
            try:
                if TYPE_INFO[tag_type].kind == "integer":
                    return Tag(name, tag_type, int(body))
                return Tag(name, tag_type, float(body))
            except ValueError:
                return Tag(name, TagType.STRING, raw)
        try:
            return Tag(name, TagType.INT, int(raw))
        except ValueError:
            pass
        try:
            return Tag(name, TagType.DOUBLE, float(raw))
        except ValueError:
            return Tag(name, TagType.STRING, raw)


def parse_snbt(text: str, *, name: str = "") -> Tag:
    """Parse SNBT into a tag tree, raising :class:`SnbtError` on malformed input."""
    if not str(text).strip():
        raise SnbtError("There is nothing to read: the text is empty.")
    return _SnbtParser(text).parse(name)


# ---------------------------------------------------------------------------
# binary form and the hex view
# ---------------------------------------------------------------------------


def to_binary(tag: Tag) -> bytes:
    """Encode a tag as an uncompressed big-endian NBT stream.

    This is what the hex view shows.  Encoding it properly rather than hexing
    the SNBT means the offsets, the lengths, and the type markers in the dump
    are the ones the file on disk would carry.
    """
    out = bytearray()
    out.append(TYPE_INFO[tag.tag_type].binary_id)
    _write_string(out, tag.name)
    _write_payload(out, tag)
    return bytes(out)


def _write_string(out: bytearray, text: str) -> None:
    encoded = str(text).encode("utf-8")[:65535]
    out.extend(struct.pack(">H", len(encoded)))
    out.extend(encoded)


def _clamp(value: int, tag_type: TagType) -> int:
    info = TYPE_INFO[tag_type]
    if info.minimum is None or info.maximum is None:
        return int(value)
    return max(info.minimum, min(info.maximum, int(value)))


def _write_payload(out: bytearray, tag: Tag) -> None:
    tag_type = tag.tag_type
    if tag_type is TagType.BYTE:
        out.extend(struct.pack(">b", _clamp(tag.value, tag_type)))
    elif tag_type is TagType.SHORT:
        out.extend(struct.pack(">h", _clamp(tag.value, tag_type)))
    elif tag_type is TagType.INT:
        out.extend(struct.pack(">i", _clamp(tag.value, tag_type)))
    elif tag_type is TagType.LONG:
        out.extend(struct.pack(">q", _clamp(tag.value, tag_type)))
    elif tag_type is TagType.FLOAT:
        out.extend(struct.pack(">f", float(tag.value)))
    elif tag_type is TagType.DOUBLE:
        out.extend(struct.pack(">d", float(tag.value)))
    elif tag_type is TagType.STRING:
        _write_string(out, tag.value)
    elif tag_type is TagType.BYTE_ARRAY:
        out.extend(struct.pack(">i", len(tag.value)))
        for item in tag.value:
            out.extend(struct.pack(">b", _clamp(item, TagType.BYTE)))
    elif tag_type is TagType.INT_ARRAY:
        out.extend(struct.pack(">i", len(tag.value)))
        for item in tag.value:
            out.extend(struct.pack(">i", _clamp(item, TagType.INT)))
    elif tag_type is TagType.LONG_ARRAY:
        out.extend(struct.pack(">i", len(tag.value)))
        for item in tag.value:
            out.extend(struct.pack(">q", _clamp(item, TagType.LONG)))
    elif tag_type is TagType.LIST:
        element = TYPE_INFO[tag.children[0].tag_type].binary_id if tag.children else 0
        out.append(element)
        out.extend(struct.pack(">i", len(tag.children)))
        for child in tag.children:
            _write_payload(out, child)
    else:
        for child in tag.children:
            out.append(TYPE_INFO[child.tag_type].binary_id)
            _write_string(out, child.name)
            _write_payload(out, child)
        out.append(0)


#: How much of a stream the hex view renders before it says it stopped.  A
#: chunk is megabytes; a view that tried to draw all of it would stall the
#: window and tell the reader nothing the first kilobyte did not.
HEX_LIMIT = 4096


def hex_dump(data: bytes, *, limit: int = HEX_LIMIT) -> str:
    """Render bytes as offset, hex columns, and a printable panel.

    Truncation is stated in the output rather than implied by the dump simply
    ending, because a reader cannot tell a short file from a cut-off view.
    """
    payload = bytes(data)
    shown = payload[: max(0, int(limit))]
    lines: List[str] = []
    for offset in range(0, len(shown), 16):
        row = shown[offset : offset + 16]
        left = " ".join(f"{byte:02x}" for byte in row[:8])
        right = " ".join(f"{byte:02x}" for byte in row[8:])
        columns = f"{left:<23}  {right:<23}"
        printable = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in row)
        lines.append(f"{offset:08x}  {columns}  |{printable}|")
    if not lines:
        lines.append("00000000  (no bytes)")
    if len(payload) > len(shown):
        remaining = len(payload) - len(shown)
        lines.append("")
        lines.append(
            f"{len(shown)} of {len(payload)} bytes shown; {remaining} more are "
            "not rendered."
        )
    else:
        lines.append("")
        lines.append(f"{len(payload)} bytes in total.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# revisions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Revision:
    """One recorded state of one tag, and what the change to it was.

    ``snapshot`` is a detached clone, so restoring cannot be affected by later
    edits to the live tree, and restoring the same revision twice gives the
    same result both times.
    """

    label: str
    action: str
    detail: str
    timestamp: str
    snapshot: Tag


@dataclass(frozen=True)
class SourceInfo:
    """One of the six data sources the left rail lists.

    ``glyph``, ``label``, ``count`` and ``crumb`` are the design's four facts
    about a source: the mark in front of it, its name, how many of that thing
    are in scope, and the path that names the one being edited.  ``pill`` is the
    caption beside the window title, which the design composes from the label
    and the count, and ``summary`` is the same trail spelled out for a reader
    who has the pointer on the rail rather than eyes on the breadcrumb.
    """

    key: str
    label: str
    glyph: str
    pill: str
    summary: str
    count: str = ""
    crumb: str = ""

    @property
    def crumbs(self) -> Tuple[str, ...]:
        """Return the breadcrumb trail split into the parts the header draws."""
        return tuple(part for part in self.crumb.split(" › ") if part)


def _source(key: str, label: str, glyph: str, count: str, crumb: str) -> SourceInfo:
    """Build a source record from the five facts the design gives about it."""
    return SourceInfo(
        key,
        label,
        glyph,
        f"{label} · {count} in scope",
        crumb,
        count,
        crumb,
    )


#: The sources, in the order the design's rail draws them, with the design's
#: own glyphs, labels, in-scope counts and breadcrumb trails.
SOURCES: Tuple[SourceInfo, ...] = (
    _source(
        "blockEntity",
        "Block entity",
        "▤",
        "26",
        "chunk 4,-13 › block_entities[3] › chest",
    ),
    _source("entity", "Entity", "☰", "12", "chunk 4,-13 › entities[1] › villager"),
    _source(
        "itemStack",
        "Item stack",
        "◈",
        "14",
        "player › Inventory[0] › diamond_pickaxe",
    ),
    _source("player", "Player", "☺", "2", "playerdata › 6f1c…a904"),
    _source("levelDat", "level.dat", "▣", "1", "level.dat › Data"),
    _source("chunk", "Chunk", "▦", "812", "region r.0.-1 › chunk 4,-13"),
)

#: The design's own key for each source, for a caller holding one of those
#: rather than the model's.  ``item`` and ``level`` are what the design writes;
#: ``itemStack`` and ``levelDat`` are what this module has always called them,
#: and both open the same document.
SOURCE_ALIASES: Dict[str, str] = {
    "item": "itemStack",
    "level": "levelDat",
}

#: The source opened when a caller names none.
DEFAULT_SOURCE = "blockEntity"

#: The source the design opens on, and the one it falls back to when a key
#: names none of the six.  Every surface that raises the editor -- the ribbon,
#: the palette, a block or chunk inspector -- names its source outright, so this
#: is what a caller who names nothing is asking to see.
DESIGN_DEFAULT_SOURCE = "entity"


# ---------------------------------------------------------------------------
# what each source shows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    """One row of the form, exactly as the design specifies that row.

    A :class:`ControlSpec` is worked out from a live tag; a :class:`FieldSpec`
    is the row the design draws, which is not always the same thing.  The
    design flattens a path into one row -- ``VillagerData.profession``,
    ``tag.display.color``, ``xPos / zPos`` -- and it chooses per source rather
    than per name: a block entity's ``id`` is a text box because the placed
    block decides it, an entity's ``id`` is a picker because it does not.  No
    rule derives that from a tag, so it is written down instead.
    """

    #: The abbreviation drawn in front of the name, e.g. ``str`` or ``cmpd``.
    badge: str
    label: str
    hint: str
    #: One of :data:`CONTROL_KINDS`.
    kind: str
    value: str = ""
    range_text: str = ""
    minimum: float = 0.0
    maximum: float = 0.0
    step: float = 1.0
    number: float = 0.0
    integral: bool = True
    options: Tuple[str, ...] = ()
    parts: Tuple[Tuple[str, str], ...] = ()
    axis_colours: Tuple[str, ...] = ()
    chips: Tuple[str, ...] = ()
    slots: Tuple[Mapping[str, Any], ...] = ()
    swatches: Tuple[Tuple[str, str], ...] = ()
    colour: str = ""
    placeholder: str = ""
    boolean: bool = False
    #: The source an "Open" button moves to, when it moves to one.
    opens_source: str = ""
    #: The dialog an "Open" button raises, when it raises one.
    opens_dialog: str = ""

    @property
    def caret(self) -> str:
        """Return the mark the tree line draws: a branch opens, a leaf does not."""
        return "▾" if self.kind in ("container", "slots", "chips") else "·"

    def matches(self, query: str) -> bool:
        """Return whether the tag search's plain-text query keeps this row.

        Name, explanation, and type are all searched together, so typing
        ``byte`` finds every byte and typing ``despawn`` finds the switch whose
        explanation mentions it without the reader knowing its name.
        """
        needle = str(query).strip().casefold()
        if not needle:
            return True
        return needle in (self.label + self.hint + self.badge).casefold()

    def control(self) -> ControlSpec:
        """Return this row as the control record the form builder consumes."""
        return ControlSpec(
            self.kind,
            self.label,
            self.hint,
            value=self.value,
            number=self.number,
            minimum=self.minimum,
            maximum=self.maximum,
            step=self.step,
            integral=self.integral,
            options=self.options,
            parts=self.parts,
            chips=self.chips,
            slots=self.slots,
            swatches=self.swatches,
            colour=self.colour,
            placeholder=self.placeholder,
            boolean=self.boolean,
            axis_colours=self.axis_colours,
            range_text=self.range_text,
        )


def _xyz(*values: str) -> Tuple[Tuple[Tuple[str, str], ...], Tuple[str, ...]]:
    """Return the parts and colours of an x, y, z row."""
    axes = ("x", "y", "z")[: len(values)]
    parts = tuple(zip(axes, values))
    return parts, tuple(axis_colour(axis) for axis in axes)


#: The chest's block position, which is also the player's personal respawn.
_POSITION_PARTS, _POSITION_COLOURS = _xyz("412", "71", "188")
_ENTITY_POS_PARTS, _ENTITY_POS_COLOURS = _xyz("412.5", "71.0", "188.5")
_WORLD_SPAWN_PARTS, _WORLD_SPAWN_COLOURS = _xyz("66", "118", "-43")
_PLAYER_POS_PARTS, _PLAYER_POS_COLOURS = _xyz("66.40", "118.13", "-43.12")


def _cell(
    short: str,
    count: str,
    title: str,
    *,
    block_id: str = "",
    selected: bool = False,
    index: int = -1,
) -> Mapping[str, Any]:
    """Return one cell of an inventory grid, filled or empty."""
    return {
        "short": short,
        "count": count,
        "title": title,
        "block_id": block_id,
        "selected": selected,
        "index": index,
    }


def _empty_cell(title: str) -> Mapping[str, Any]:
    """Return an unoccupied cell, which is still a cell and still reachable."""
    return _cell("", "", title)


#: Every row of every source's form, in the design's order, with the design's
#: own captions, explanations, values, bounds, options, chips, swatches and
#: slot grids.  This is the whole of what the editor shows for each of its six
#: data sources.
SOURCE_FIELDS: Dict[str, Tuple[FieldSpec, ...]] = {
    "blockEntity": (
        FieldSpec(
            "str",
            "id",
            "Block entity identifier. Read-only for the placed block.",
            "text",
            value="minecraft:chest",
        ),
        FieldSpec(
            "int",
            "Position",
            "Block coordinates of this block entity.",
            "vector",
            parts=_POSITION_PARTS,
            axis_colours=_POSITION_COLOURS,
        ),
        FieldSpec(
            "str",
            "CustomName",
            "JSON text component shown in the container title.",
            "longtext",
            value='{"text":"Storage","color":"aqua"}',
        ),
        FieldSpec(
            "list",
            "Items",
            "Inventory contents. Click a slot to edit its stack.",
            "slots",
            slots=(
                _cell(
                    "planks",
                    "32",
                    "Slot 0 · minecraft:oak_planks ×32",
                    block_id="minecraft:oak_planks",
                    selected=True,
                    index=0,
                ),
                _cell(
                    "torch",
                    "8",
                    "Slot 1 · minecraft:torch ×8",
                    block_id="minecraft:torch",
                    index=1,
                ),
                _cell(
                    "iron",
                    "12",
                    "Slot 2 · minecraft:iron_ingot ×12",
                    block_id="minecraft:iron_ingot",
                    index=2,
                ),
                _empty_cell("Slot 3 · empty"),
                _empty_cell("Slot 4 · empty"),
                _cell(
                    "coal",
                    "64",
                    "Slot 5 · minecraft:coal ×64",
                    block_id="minecraft:coal",
                    index=3,
                ),
                _empty_cell("Slot 6 · empty"),
                _empty_cell("Slot 7 · empty"),
                _empty_cell("Slot 8 · empty"),
            ),
        ),
        FieldSpec(
            "str",
            "LootTable",
            "Unrolled table. Editing Items clears this reference.",
            "select",
            value="(none)",
            options=ENUM_OPTIONS["loottable"],
        ),
        FieldSpec(
            "str",
            "Lock",
            "Item name required to open the container.",
            "text",
            value="",
            placeholder="No lock",
        ),
    ),
    "entity": (
        FieldSpec(
            "str",
            "id",
            "Entity type identifier.",
            "select",
            value="minecraft:villager",
            options=(
                "minecraft:villager",
                "minecraft:zombie",
                "minecraft:cow",
                "minecraft:armor_stand",
            ),
        ),
        FieldSpec(
            "str",
            "CustomName",
            "Display name shown above the entity.",
            "text",
            value="Ana",
        ),
        FieldSpec(
            "list",
            "Pos",
            "Exact double position inside the chunk.",
            "vector",
            parts=_ENTITY_POS_PARTS,
            axis_colours=_ENTITY_POS_COLOURS,
        ),
        FieldSpec(
            "list",
            "Rotation",
            "Yaw then pitch, in degrees.",
            "vector",
            parts=(("yaw", "142.0"), ("pitch", "0.0")),
            axis_colours=("", ""),
        ),
        FieldSpec(
            "float",
            "Health",
            "Current health. The slider clamps to the type's maximum.",
            "slider",
            value="20.0 / 20.0",
            number=20.0,
            minimum=0.0,
            maximum=20.0,
            step=0.5,
            integral=False,
        ),
        FieldSpec(
            "short",
            "Air",
            "Remaining breath in ticks.",
            "stepper",
            value="300",
            range_text="0 … 300",
            number=300.0,
            minimum=0.0,
            maximum=300.0,
            step=20.0,
        ),
        FieldSpec(
            "short",
            "Fire",
            "Burn ticks. -1 means not burning.",
            "stepper",
            value="-1",
            range_text="-1 … 800",
            number=-1.0,
            minimum=-1.0,
            maximum=800.0,
            step=20.0,
        ),
        FieldSpec(
            "byte",
            "PersistenceRequired",
            "When on, the entity never despawns.",
            "toggle",
            value="1b (true)",
            number=1.0,
            boolean=True,
        ),
        FieldSpec(
            "byte",
            "Invulnerable",
            "Ignores all damage sources.",
            "toggle",
            value="0b (false)",
        ),
        FieldSpec(
            "byte",
            "NoAI",
            "Freezes behaviour and pathfinding.",
            "toggle",
            value="0b (false)",
        ),
        FieldSpec(
            "byte",
            "Silent",
            "Suppresses the entity's sounds.",
            "toggle",
            value="0b (false)",
        ),
        FieldSpec(
            "byte",
            "Glowing",
            "Draws the outline through blocks.",
            "toggle",
            value="0b (false)",
        ),
        FieldSpec(
            "int",
            "VillagerData.level",
            "Trading level, 1 to 5.",
            "stepper",
            value="3",
            range_text="1 … 5",
            number=3.0,
            minimum=1.0,
            maximum=5.0,
            step=1.0,
        ),
        FieldSpec(
            "str",
            "VillagerData.profession",
            "Profession identifier.",
            "select",
            value="librarian",
            options=ENUM_OPTIONS["profession"],
        ),
        FieldSpec(
            "cmpd",
            "Brain",
            "Memory module compound. Opens as its own subtree.",
            "container",
            value="1 child · memories",
            opens_source="entity",
        ),
        FieldSpec(
            "iarr",
            "UUID",
            "Four signed integers forming the entity UUID.",
            "chips",
            chips=("1868372892", "-1140296441", "-1354192113", "1029385712"),
        ),
        FieldSpec(
            "list",
            "Offers.Recipes",
            "Trade list. Each entry has buy, buyB, and sell stacks.",
            "container",
            value="4 entries",
        ),
        FieldSpec(
            "list",
            "ArmorItems",
            "Feet, legs, chest, head — in that order.",
            "slots",
            slots=(
                _cell(
                    "boots",
                    "1",
                    "Feet · minecraft:leather_boots",
                    block_id="minecraft:leather_boots",
                    index=0,
                ),
                _empty_cell("Legs · empty"),
                _empty_cell("Chest · empty"),
                _cell(
                    "hat",
                    "1",
                    "Head · minecraft:carved_pumpkin",
                    block_id="minecraft:carved_pumpkin",
                    index=1,
                ),
            ),
        ),
    ),
    "levelDat": (
        FieldSpec(
            "str",
            "LevelName",
            "World name shown in the game's world list.",
            "text",
            value="1.17 Height",
        ),
        FieldSpec(
            "long",
            "RandomSeed",
            "Generation seed. Existing chunks keep their terrain.",
            "text",
            value="1471929",
        ),
        FieldSpec(
            "int",
            "SpawnPos",
            "World spawn block position.",
            "vector",
            parts=_WORLD_SPAWN_PARTS,
            axis_colours=_WORLD_SPAWN_COLOURS,
        ),
        FieldSpec(
            "long",
            "DayTime",
            "Time of day in ticks. 0 is dawn, 18000 is midnight.",
            "slider",
            value="6000 ticks",
            number=6000.0,
            minimum=0.0,
            maximum=24000.0,
            step=100.0,
        ),
        FieldSpec(
            "int",
            "GameType",
            "Default game mode for new players.",
            "select",
            value="survival",
            options=ENUM_OPTIONS["gametype"],
        ),
        FieldSpec(
            "byte",
            "Difficulty",
            "World difficulty.",
            "select",
            value="peaceful",
            options=ENUM_OPTIONS["difficulty"],
        ),
        FieldSpec(
            "byte",
            "allowCommands",
            "Enables cheats in single player.",
            "toggle",
            value="1b (true)",
            number=1.0,
            boolean=True,
        ),
        FieldSpec(
            "byte",
            "hardcore",
            "Death locks the world to spectator.",
            "toggle",
            value="0b (false)",
        ),
        FieldSpec(
            "byte",
            "raining",
            "Current weather state.",
            "toggle",
            value="0b (false)",
        ),
        FieldSpec(
            "int",
            "rainTime",
            "Ticks until the weather changes.",
            "stepper",
            value="12000",
            range_text="0 … 180000",
            number=12000.0,
            minimum=0.0,
            maximum=180000.0,
            step=1000.0,
        ),
        FieldSpec(
            "cmpd",
            "GameRules",
            "Every game rule as a named tag.",
            "container",
            value="38 children",
            opens_dialog="gamerules",
        ),
        FieldSpec(
            "cmpd",
            "WorldGenSettings",
            "Generator type and dimension settings.",
            "container",
            value="3 children",
        ),
        FieldSpec(
            "double",
            "BorderSize",
            "World border diameter in blocks.",
            "text",
            value="59999968",
            integral=False,
        ),
    ),
    "player": (
        FieldSpec(
            "iarr",
            "UUID",
            "Player UUID as four signed integers.",
            "chips",
            chips=("1868372892", "-1140296441", "-1354192113", "1029385712"),
        ),
        FieldSpec(
            "list",
            "Pos",
            "Player position.",
            "vector",
            parts=_PLAYER_POS_PARTS,
            axis_colours=_PLAYER_POS_COLOURS,
        ),
        FieldSpec(
            "str",
            "Dimension",
            "Dimension the player is in.",
            "select",
            value="minecraft:overworld",
            options=ENUM_OPTIONS["dimension"],
        ),
        FieldSpec(
            "float",
            "Health",
            "Current health.",
            "slider",
            value="20.0 / 20.0",
            number=20.0,
            minimum=0.0,
            maximum=20.0,
            step=0.5,
            integral=False,
        ),
        FieldSpec(
            "int",
            "foodLevel",
            "Hunger, 0 to 20.",
            "slider",
            value="18 / 20",
            number=18.0,
            minimum=0.0,
            maximum=20.0,
            step=1.0,
        ),
        FieldSpec(
            "int",
            "XpLevel",
            "Experience level.",
            "stepper",
            value="34",
            range_text="0 … 24791",
            number=34.0,
            minimum=0.0,
            maximum=24791.0,
            step=1.0,
        ),
        FieldSpec(
            "int",
            "playerGameType",
            "Game mode for this player.",
            "select",
            value="survival",
            options=ENUM_OPTIONS["playergametype"],
        ),
        FieldSpec(
            "list",
            "Inventory",
            "Hotbar first, then main inventory.",
            "slots",
            slots=(
                _cell(
                    "pick",
                    "1",
                    "Slot 0 · minecraft:diamond_pickaxe",
                    block_id="minecraft:diamond_pickaxe",
                    selected=True,
                    index=0,
                ),
                _cell(
                    "shovel",
                    "1",
                    "Slot 1 · minecraft:diamond_shovel",
                    block_id="minecraft:diamond_shovel",
                    index=1,
                ),
                _cell(
                    "stone",
                    "64",
                    "Slot 2 · minecraft:stone ×64",
                    block_id="minecraft:stone",
                    index=2,
                ),
                _cell(
                    "torch",
                    "48",
                    "Slot 3 · minecraft:torch ×48",
                    block_id="minecraft:torch",
                    index=3,
                ),
                _empty_cell("Slot 4 · empty"),
                _cell(
                    "bread",
                    "16",
                    "Slot 5 · minecraft:bread ×16",
                    block_id="minecraft:bread",
                    index=4,
                ),
                _empty_cell("Slot 6 · empty"),
                _cell(
                    "map",
                    "1",
                    "Slot 7 · minecraft:filled_map",
                    block_id="minecraft:filled_map",
                    index=5,
                ),
                _cell(
                    "boat",
                    "1",
                    "Slot 8 · minecraft:oak_boat",
                    block_id="minecraft:oak_boat",
                    index=6,
                ),
            ),
        ),
        FieldSpec(
            "list",
            "EnderItems",
            "Ender chest contents.",
            "slots",
            slots=(
                _cell(
                    "gold",
                    "12",
                    "Slot 0 · minecraft:gold_ingot ×12",
                    block_id="minecraft:gold_ingot",
                    index=0,
                ),
                _empty_cell("Slot 1 · empty"),
                _empty_cell("Slot 2 · empty"),
            ),
        ),
        FieldSpec(
            "int",
            "SpawnPos",
            "Personal respawn position.",
            "vector",
            parts=_POSITION_PARTS,
            axis_colours=_POSITION_COLOURS,
        ),
    ),
    "itemStack": (
        FieldSpec(
            "str",
            "id",
            "Item identifier.",
            "text",
            value="minecraft:diamond_pickaxe",
        ),
        FieldSpec(
            "byte",
            "Count",
            "Stack size. Vanilla clamps to the item's maximum.",
            "stepper",
            value="1",
            range_text="1 … 64",
            number=1.0,
            minimum=1.0,
            maximum=64.0,
            step=1.0,
        ),
        FieldSpec(
            "byte",
            "Slot",
            "Inventory slot index.",
            "stepper",
            value="0",
            range_text="0 … 40",
            number=0.0,
            minimum=0.0,
            maximum=40.0,
            step=1.0,
        ),
        FieldSpec(
            "int",
            "tag.Damage",
            "Durability used. 0 is undamaged.",
            "slider",
            value="240 / 1561",
            number=240.0,
            minimum=0.0,
            maximum=1561.0,
            step=1.0,
        ),
        FieldSpec(
            "list",
            "tag.Enchantments",
            "Each entry pairs an id with a level.",
            "chips",
            chips=("efficiency V", "unbreaking III", "fortune III", "mending I"),
        ),
        FieldSpec(
            "str",
            "tag.display.Name",
            "JSON text component for the item name.",
            "longtext",
            value='{"text":"Ana\'s Pick","italic":false,"color":"gold"}',
        ),
        FieldSpec(
            "list",
            "tag.display.Lore",
            "One JSON text component per line.",
            "chips",
            chips=('"Forged at spawn"', '"Do not lend"'),
        ),
        FieldSpec(
            "int",
            "tag.display.color",
            "Leather and firework colour as a packed integer.",
            "color",
            value="#82D5CC",
            colour="#82D5CC",
            number=float(0x82D5CC),
            swatches=COLOUR_SWATCHES,
        ),
        FieldSpec(
            "byte",
            "tag.Unbreakable",
            "Durability never decreases.",
            "toggle",
            value="0b (false)",
        ),
        FieldSpec(
            "int",
            "tag.HideFlags",
            "Bit field hiding tooltip sections.",
            "chips",
            chips=("enchantments", "attributes", "unbreakable"),
        ),
    ),
    "chunk": (
        FieldSpec(
            "int",
            "xPos / zPos",
            "Chunk coordinates.",
            "vector",
            parts=(("x", "4"), ("z", "-13")),
            axis_colours=(axis_colour("x"), axis_colour("z")),
        ),
        FieldSpec(
            "str",
            "Status",
            "Generation stage of this chunk.",
            "select",
            value="full",
            options=ENUM_OPTIONS["status"],
        ),
        FieldSpec(
            "long",
            "LastUpdate",
            "Game tick when the chunk was last saved.",
            "text",
            value="148291",
        ),
        FieldSpec(
            "long",
            "InhabitedTime",
            "Ticks players have spent in this chunk. Affects local difficulty.",
            "slider",
            value="3600 ticks",
            number=3600.0,
            minimum=0.0,
            maximum=72000.0,
            step=100.0,
        ),
        FieldSpec(
            "larr",
            "Heightmaps.WORLD_SURFACE",
            "Packed height values, 256 entries.",
            "chips",
            chips=("packed ×37", "min 62", "max 134"),
        ),
        FieldSpec(
            "list",
            "sections",
            "One compound per 16-block vertical section.",
            "container",
            value="24 sections",
        ),
        FieldSpec(
            "list",
            "block_entities",
            "Block entities stored in this chunk.",
            "container",
            value="26 entries",
            opens_source="blockEntity",
        ),
        FieldSpec(
            "cmpd",
            "structures.References",
            "Structure bounding-box references.",
            "container",
            value="3 children",
            opens_dialog="structureLocator",
        ),
    ),
}


def fields_for(key: str = DEFAULT_SOURCE) -> Tuple[FieldSpec, ...]:
    """Return every row the form draws for one source, in the design's order."""
    return SOURCE_FIELDS.get(source(key).key, ())


def matching_fields(
    key: str = DEFAULT_SOURCE, query: str = ""
) -> Tuple[FieldSpec, ...]:
    """Return the rows a tag search keeps, or every row for an empty query."""
    return tuple(field for field in fields_for(key) if field.matches(query))


def tree_lines_for(key: str = DEFAULT_SOURCE) -> Tuple[Tuple[str, str, str], ...]:
    """Return the left tree as ``(caret, badge, label)`` per line.

    The tree lists what the form shows rather than a second, differently
    ordered index of the same tags: a line and a row are the same thing seen
    twice, so a reader scanning the tree and a reader scrolling the form are
    never looking at two different documents.
    """
    return tuple((field.caret, field.badge, field.label) for field in fields_for(key))


@dataclass
class TreeRow:
    """One drawn line of the tag tree."""

    tag: Tag
    depth: int
    caret: str
    badge: str
    label: str
    expandable: bool


class NbtDocument:
    """One editable NBT document, its unsaved state, and its history.

    History is append-only and per tag.  A restore does not rewind: it applies
    an old snapshot and records that as a new revision, so the state restored
    from is still there to go back to.  That is the same contract the project
    history keeps, and it is what makes experimenting with raw tags safe.
    """

    def __init__(self, source: SourceInfo, root: Tag) -> None:
        self.source = source
        self.root = root
        self.dirty = False
        self.edit_count = 0
        self._history: Dict[int, List[Revision]] = {}
        self._revision_number = itertools.count(1)

    # -- identity ------------------------------------------------------------
    @property
    def key(self) -> str:
        """Return the source key this document was built from."""
        return self.source.key

    def tag_count(self) -> int:
        """Return how many tags the document holds."""
        return self.root.count()

    def dirty_text(self) -> str:
        """Return the honest footer line about unsaved work.

        A value that is being typed has changed the document without yet
        recording a revision, and saying "0 edits" for that state would be
        both wrong and alarming; it gets its own line instead.
        """
        if not self.dirty:
            return "No unsaved changes."
        if not self.edit_count:
            return "Editing. Nothing recorded yet."
        edits = "1 edit" if self.edit_count == 1 else f"{self.edit_count} edits"
        return f"{edits} not committed yet."

    # -- navigation ----------------------------------------------------------
    def find(self, path: str) -> Optional[Tag]:
        """Return the tag at a dotted path, or ``None`` when there is none."""
        wanted = str(path)
        for node in [self.root, *self.root.descendants()]:
            if node.path() == wanted:
                return node
        return None

    def breadcrumbs(self, tag: Tag) -> Tuple[str, ...]:
        """Return the breadcrumb segments for the selected tag."""
        return tag.path_parts()

    def rows(
        self,
        *,
        expanded: Sequence[int] = (),
        matches: Optional[Callable[[str], bool]] = None,
    ) -> Tuple[TreeRow, ...]:
        """Return the visible tree lines for the current expansion and search.

        A search shows every matching tag with the ancestors needed to reach
        it, expanded whether or not the reader had opened them, because a
        result hidden inside a collapsed branch is a result nobody finds.
        """
        opened = set(int(uid) for uid in expanded)
        keep: Optional[set] = None
        if matches is not None:
            keep = set()
            for node in [self.root, *self.root.descendants()]:
                if matches(node.search_text()):
                    keep.add(node.uid)
                    for ancestor in node.ancestors():
                        keep.add(ancestor.uid)
        out: List[TreeRow] = []

        def walk(node: Tag, depth: int) -> None:
            if keep is not None and node.uid not in keep:
                return
            expandable = bool(node.children)
            is_open = expandable and (node.uid in opened or keep is not None)
            caret = ("▾" if is_open else "▸") if expandable else "·"
            out.append(
                TreeRow(
                    node,
                    depth,
                    caret,
                    type_badge(node.tag_type),
                    node.tree_label(),
                    expandable,
                )
            )
            if is_open:
                for child in node.children:
                    walk(child, depth + 1)

        walk(self.root, 0)
        return tuple(out)

    def default_expansion(self) -> List[int]:
        """Return the uids opened when the document is first shown."""
        opened = [self.root.uid]
        for child in self.root.children:
            if child.is_container:
                opened.append(child.uid)
        return opened

    # -- history -------------------------------------------------------------
    def history(self, tag: Tag) -> Tuple[Revision, ...]:
        """Return every revision recorded for one tag, oldest first."""
        return tuple(self._history.get(tag.uid, ()))

    def record(self, tag: Tag, action: str, detail: str) -> Revision:
        """Append a revision holding the tag's state as it stands now."""
        revision = Revision(
            label=f"r{next(self._revision_number)}",
            action=str(action),
            detail=str(detail),
            timestamp=datetime.now().strftime("%H:%M:%S"),
            snapshot=tag.clone(),
        )
        self._history.setdefault(tag.uid, []).append(revision)
        return revision

    def _ensure_baseline(self, tag: Tag) -> None:
        """Record the state a tag was opened in, before its first change.

        Without this the first edit would have nothing to go back to, and a
        history whose oldest entry is already a change is a history that
        cannot restore the value the file actually held.
        """
        if self._history.get(tag.uid):
            return
        self.record(tag, "baseline", f"Opened holding {tag.value_text()}")

    def restore(self, tag: Tag, revision: Revision) -> Revision:
        """Apply an old revision and record the restore as a new one."""
        previous = tag.value_text()
        snapshot = revision.snapshot
        if tag.parent is not None and tag.parent.tag_type is TagType.COMPOUND:
            tag.name = snapshot.name
        tag.tag_type = snapshot.tag_type
        tag.value = (
            list(snapshot.value) if isinstance(snapshot.value, list) else snapshot.value
        )
        for child in list(tag.children):
            tag.remove(child)
        for child in snapshot.children:
            tag.append(child.clone())
        self._touch()
        return self.record(
            tag,
            "restore",
            f"Restored {revision.label}: {previous} back to {tag.value_text()}",
        )

    def _touch(self) -> None:
        self.dirty = True
        self.edit_count += 1

    # -- editing -------------------------------------------------------------
    def apply_value(self, tag: Tag, value: Any) -> ValidationResult:
        """Apply a payload without recording a revision, and report its validity.

        Typing into a field and dragging a slider both produce a stream of
        values, and one revision per keystroke would bury the edit that
        actually happened under fifty that did not.  The caller applies live
        through here and calls :meth:`record_edit` once the burst is over.

        A Float tag holds four bytes, so a value it cannot represent exactly is
        stored rounded.  That is reported here rather than left for the reader
        to notice later, because a field that quietly shows something other
        than what was typed reads as a defect in the editor.
        """
        before = tag.value_text()
        self._ensure_baseline(tag)
        tag.set_payload(value)
        if tag.value_text() != before:
            self.dirty = True
        result = validate(tag)
        if result.ok and tag.tag_type is TagType.FLOAT:
            requested = coerce_float(value)
            stored = format_float(tag.value, double=False)
            # The comparison is between the two pieces of *text*: a request of
            # "12.34" lands on a float32 whose shortest form is also "12.34",
            # and warning about that would be a warning about nothing.
            if math.isfinite(requested) and format_float(requested) != stored:
                return ValidationResult(
                    True,
                    "warning",
                    f"Float {tag.display_name()} cannot hold "
                    f"{format_float(requested)} in four bytes, so it stores "
                    f"{stored}.",
                )
        return result

    def record_edit(self, tag: Tag, before: str) -> Optional[Revision]:
        """Record one revision for an edit already applied, if it changed anything.

        ``before`` is the value text the tag held when the burst of edits
        started, so a field typed through six characters and back to where it
        began records nothing at all.
        """
        after = tag.value_text()
        if str(before) == after:
            return None
        self._touch()
        return self.record(tag, "edit", f"{tag.display_name()}: {before} to {after}")

    def set_value(self, tag: Tag, value: Any) -> ValidationResult:
        """Apply a payload and record it as one revision.

        This is the route a discrete control takes -- a switch, a stepper
        press, a chosen option -- where one interaction is one edit.
        """
        before = tag.value_text()
        result = self.apply_value(tag, value)
        self.record_edit(tag, before)
        return result

    def rename(self, tag: Tag, name: str) -> ValidationResult:
        """Rename a tag inside its compound, refusing a name already taken."""
        if tag.parent is None:
            return ValidationResult(
                False, "error", "The root tag's name belongs to the file, not the tree."
            )
        if tag.parent.tag_type is TagType.LIST:
            return ValidationResult(
                False,
                "error",
                "Elements of a list are unnamed; their position is their name.",
            )
        wanted = str(name).strip()
        if not wanted:
            return ValidationResult(
                False, "error", "A tag inside a compound needs a name."
            )
        if any(
            sibling is not tag and sibling.name == wanted
            for sibling in tag.parent.children
        ):
            return ValidationResult(
                False,
                "error",
                f'"{tag.parent.display_name()}" already holds a tag named '
                f'"{wanted}".',
            )
        before = tag.name
        if before == wanted:
            return ValidationResult(True, "ok", "The name is unchanged.")
        self._ensure_baseline(tag)
        tag.name = wanted
        self._touch()
        self.record(tag, "rename", f'Renamed "{before}" to "{wanted}"')
        return ValidationResult(True, "ok", f'Renamed to "{wanted}".')

    def retype(self, tag: Tag, target: TagType) -> RetypeReport:
        """Convert a tag to another type, recording what the conversion cost."""
        report = retype_preview(tag, target)
        if not report.ok:
            return report
        if TagType(target) is tag.tag_type:
            return report
        before = f"{type_label(tag.tag_type)} {tag.value_text()}"
        self._ensure_baseline(tag)
        tag.tag_type = TagType(target)
        for child in list(tag.children):
            tag.remove(child)
        tag.set_payload(report.value)
        for child in report.children:
            tag.append(child)
        self._touch()
        self.record(
            tag,
            "retype",
            f"{before} became {type_label(tag.tag_type)} {tag.value_text()}",
        )
        return report

    def add_child(
        self,
        parent: Tag,
        name: str,
        tag_type: TagType,
        value: Any = None,
    ) -> Tag:
        """Add a child to a container and record it on the parent."""
        if not parent.is_container:
            raise TypeError(
                f"{type_label(parent.tag_type)} {parent.display_name()} holds no "
                "child tags."
            )
        self._ensure_baseline(parent)
        child = Tag(name, tag_type, value)
        parent.append(child)
        self._touch()
        self.record(
            parent,
            "add",
            f"Added {type_label(child.tag_type)} {child.display_name()}",
        )
        return child

    def duplicate(self, tag: Tag) -> Optional[Tag]:
        """Copy a tag beside itself, giving the copy an unused name."""
        parent = tag.parent
        if parent is None:
            return None
        copy = tag.clone()
        if parent.tag_type is TagType.COMPOUND:
            copy.name = self._unused_name(parent, tag.name)
        self._ensure_baseline(parent)
        parent.append(copy, tag.index() + 1)
        self._touch()
        self.record(
            parent, "duplicate", f"Duplicated {tag.display_name()} as {copy.name or ''}"
        )
        return copy

    @staticmethod
    def _unused_name(parent: Tag, base: str) -> str:
        """Return ``base`` with the smallest suffix its compound does not hold."""
        taken = {child.name for child in parent.children}
        if base not in taken:
            return base
        for index in itertools.count(2):
            candidate = f"{base} ({index})"
            if candidate not in taken:
                return candidate
        raise AssertionError("unreachable")  # pragma: no cover

    def delete(self, tag: Tag) -> bool:
        """Remove a tag from its parent, recording the removal on the parent."""
        parent = tag.parent
        if parent is None:
            return False
        label = f"{type_label(tag.tag_type)} {tag.display_name()}"
        self._ensure_baseline(parent)
        removed = parent.remove(tag)
        if not removed:
            return False
        self._history.pop(tag.uid, None)
        self._touch()
        self.record(parent, "delete", f"Deleted {label}")
        return True

    def replace(self, tag: Tag, replacement: Tag) -> Tag:
        """Replace a tag's type, payload, and children from another tree."""
        before = f"{type_label(tag.tag_type)} {tag.value_text()}"
        self._ensure_baseline(tag)
        tag.tag_type = replacement.tag_type
        tag.value = (
            list(replacement.value)
            if isinstance(replacement.value, list)
            else replacement.value
        )
        for child in list(tag.children):
            tag.remove(child)
        for child in list(replacement.children):
            tag.append(child.clone())
        self._touch()
        self.record(
            tag,
            "import",
            f"{before} replaced by {type_label(tag.tag_type)} {tag.value_text()}",
        )
        return tag

    # -- views ---------------------------------------------------------------
    def snbt(self, tag: Optional[Tag] = None) -> str:
        """Return the live SNBT for a tag, or for the whole document."""
        return to_snbt(tag if tag is not None else self.root)

    def hex_view(self, tag: Optional[Tag] = None) -> str:
        """Return the live hex dump for a tag, or for the whole document."""
        return hex_dump(to_binary(tag if tag is not None else self.root))

    def validate(self, tag: Tag) -> ValidationResult:
        """Validate one tag."""
        return validate(tag)

    def validate_all(self) -> ValidationResult:
        """Validate every tag in the document."""
        return validate_tree(self.root)

    def mark_committed(self) -> None:
        """Record that the edits have been handed on and are no longer pending."""
        self.dirty = False
        self.edit_count = 0


# ---------------------------------------------------------------------------
# sample documents
# ---------------------------------------------------------------------------


def _byte(name: str, value: int) -> Tag:
    return Tag(name, TagType.BYTE, value)


def _short(name: str, value: int) -> Tag:
    return Tag(name, TagType.SHORT, value)


def _int(name: str, value: int) -> Tag:
    return Tag(name, TagType.INT, value)


def _long(name: str, value: int) -> Tag:
    return Tag(name, TagType.LONG, value)


def _float(name: str, value: float) -> Tag:
    return Tag(name, TagType.FLOAT, value)


def _double(name: str, value: float) -> Tag:
    return Tag(name, TagType.DOUBLE, value)


def _string(name: str, value: str) -> Tag:
    return Tag(name, TagType.STRING, value)


def _compound(name: str, children: Sequence[Tag]) -> Tag:
    return Tag(name, TagType.COMPOUND, None, children)


def _list(name: str, children: Sequence[Tag]) -> Tag:
    return Tag(name, TagType.LIST, None, children)


def _int_array(name: str, values: Sequence[int]) -> Tag:
    return Tag(name, TagType.INT_ARRAY, list(values))


def _long_array(name: str, values: Sequence[int]) -> Tag:
    return Tag(name, TagType.LONG_ARRAY, list(values))


def _byte_array(name: str, values: Sequence[int]) -> Tag:
    return Tag(name, TagType.BYTE_ARRAY, list(values))


def _stack(slot: int, item_id: str, count: int, extra: Sequence[Tag] = ()) -> Tag:
    """Build one inventory stack compound."""
    return _compound(
        "",
        [_byte("Slot", slot), _string("id", item_id), _byte("Count", count), *extra],
    )


def _block_entity_root() -> Tag:
    return _compound(
        "",
        [
            _string("id", "minecraft:chest"),
            _int("x", -2),
            _int("y", 98),
            _int("z", -49),
            _byte("keepPacked", 0),
            _string("CustomName", '{"text":"Supply chest","italic":false}'),
            _string("Lock", ""),
            _string("LootTable", "minecraft:chests/simple_dungeon"),
            _long("LootTableSeed", -4820391746620183940),
            _list(
                "Items",
                [
                    _stack(0, "minecraft:oak_planks", 32),
                    _stack(1, "minecraft:torch", 8),
                    _stack(
                        2,
                        "minecraft:iron_pickaxe",
                        1,
                        [_compound("tag", [_int("Damage", 43), _int("RepairCost", 1)])],
                    ),
                    _stack(4, "minecraft:bread", 12),
                    _stack(7, "minecraft:redstone", 24),
                ],
            ),
        ],
    )


def _entity_root() -> Tag:
    return _compound(
        "",
        [
            _string("id", "minecraft:villager"),
            _int_array("UUID", [-1177451, 1877343992, -1259875223, 1017391712]),
            _list(
                "Pos",
                [
                    _double("", 66.4),
                    _double("", 118.0),
                    _double("", -43.12),
                ],
            ),
            _list(
                "Motion",
                [_double("", 0.0), _double("", -0.0784), _double("", 0.0)],
            ),
            _list("Rotation", [_float("", 178.5), _float("", 0.0)]),
            _float("Health", 20.0),
            _float("FallDistance", 0.0),
            _short("Air", 300),
            _short("Fire", -1),
            _byte("OnGround", 1),
            _byte("Invulnerable", 0),
            _byte("NoGravity", 0),
            _byte("PersistenceRequired", 1),
            _byte("CustomNameVisible", 1),
            _string("CustomName", '{"text":"Marta"}'),
            _compound(
                "VillagerData",
                [
                    _int("level", 3),
                    _string("profession", "minecraft:librarian"),
                    _string("type", "minecraft:plains"),
                ],
            ),
            _int("Xp", 128),
            _list(
                "Inventory",
                [_stack(0, "minecraft:bread", 6), _stack(1, "minecraft:paper", 18)],
            ),
            _list("Tags", [_string("", "town_guard"), _string("", "no_wander")]),
        ],
    )


def _item_stack_root() -> Tag:
    return _compound(
        "",
        [
            _string("id", "minecraft:diamond_sword"),
            _byte("Count", 1),
            _byte("Slot", 0),
            _compound(
                "tag",
                [
                    _int("Damage", 43),
                    _int("RepairCost", 3),
                    _byte("Unbreakable", 0),
                    _int("HideFlags", 4),
                    _list(
                        "Enchantments",
                        [
                            _compound(
                                "",
                                [
                                    _string("id", "minecraft:sharpness"),
                                    _short("lvl", 4),
                                ],
                            ),
                            _compound(
                                "",
                                [
                                    _string("id", "minecraft:unbreaking"),
                                    _short("lvl", 3),
                                ],
                            ),
                            _compound(
                                "",
                                [_string("id", "minecraft:mending"), _short("lvl", 1)],
                            ),
                        ],
                    ),
                    _compound(
                        "display",
                        [
                            _string("Name", '{"text":"Dawnbreaker","color":"gold"}'),
                            _int("color", 16766720),
                            _list(
                                "Lore",
                                [
                                    _string("", '{"text":"Forged in the deep dark."}'),
                                    _string("", '{"text":"It hums near sculk."}'),
                                ],
                            ),
                        ],
                    ),
                    _list(
                        "AttributeModifiers",
                        [
                            _compound(
                                "",
                                [
                                    _string("AttributeName", "generic.attack_damage"),
                                    _string("Name", "sharpened edge"),
                                    _double("Amount", 3.5),
                                    _int("Operation", 0),
                                    _string("Slot", "mainhand"),
                                ],
                            )
                        ],
                    ),
                ],
            ),
        ],
    )


def _player_root() -> Tag:
    return _compound(
        "",
        [
            _int("DataVersion", 3700),
            _string("Dimension", "minecraft:overworld"),
            _list(
                "Pos",
                [
                    _double("", 66.4),
                    _double("", 118.13),
                    _double("", -43.12),
                ],
            ),
            _list("Motion", [_double("", 0.0), _double("", 0.0), _double("", 0.0)]),
            _list(
                "Rotation",
                [_float("", -134.1), _float("", 21.9)],
            ),
            _int("playerGameType", 1),
            _float("Health", 20.0),
            _int("foodLevel", 20),
            _float("foodSaturationLevel", 5.0),
            _float("foodExhaustionLevel", 0.8),
            _int("XpLevel", 30),
            _float("XpP", 0.425),
            _int("XpTotal", 1395),
            _int("Score", 1395),
            _int("SelectedItemSlot", 0),
            _short("Air", 300),
            _byte("OnGround", 1),
            _byte("seenCredits", 0),
            _int("SpawnX", 64),
            _int("SpawnY", 96),
            _int("SpawnZ", -32),
            _int_array("UUID", [1584379284, -1119481456, -1978310912, 1749390211]),
            _compound(
                "abilities",
                [
                    _byte("flying", 1),
                    _byte("mayfly", 1),
                    _byte("instabuild", 1),
                    _byte("invulnerable", 1),
                    _byte("mayBuild", 1),
                    _float("walkSpeed", 0.1),
                    _float("flySpeed", 0.05),
                ],
            ),
            _list(
                "Inventory",
                [
                    _stack(0, "minecraft:diamond_pickaxe", 1),
                    _stack(1, "minecraft:torch", 64),
                    _stack(2, "minecraft:oak_planks", 64),
                    _stack(3, "minecraft:cooked_beef", 32),
                    _stack(4, "minecraft:water_bucket", 1),
                    _stack(8, "minecraft:ender_pearl", 6),
                    _stack(100, "minecraft:diamond_boots", 1),
                    _stack(103, "minecraft:diamond_helmet", 1),
                ],
            ),
            _list("EnderItems", [_stack(0, "minecraft:ancient_debris", 4)]),
            _compound(
                "recipeBook",
                [
                    _byte("isGuiOpen", 0),
                    _byte("isFilteringCraftable", 0),
                    _list(
                        "recipes",
                        [
                            _string("", "minecraft:oak_planks"),
                            _string("", "minecraft:torch"),
                            _string("", "minecraft:stone_pickaxe"),
                        ],
                    ),
                ],
            ),
        ],
    )


def _level_dat_root() -> Tag:
    return _compound(
        "",
        [
            _compound(
                "Data",
                [
                    _string("LevelName", "Amulet demo world"),
                    _int("version", 19133),
                    _int("DataVersion", 3700),
                    _int("GameType", 1),
                    _byte("Difficulty", 2),
                    _byte("DifficultyLocked", 0),
                    _byte("hardcore", 0),
                    _byte("allowCommands", 1),
                    _byte("initialized", 1),
                    _long("RandomSeed", -4172144997902289642),
                    _long("Time", 148263041),
                    _long("DayTime", 6000),
                    _long("LastPlayed", 1770000000000),
                    _int("SpawnX", 64),
                    _int("SpawnY", 96),
                    _int("SpawnZ", -32),
                    _float("SpawnAngle", 0.0),
                    _byte("raining", 0),
                    _int("rainTime", 41892),
                    _byte("thundering", 0),
                    _int("thunderTime", 92374),
                    _int("clearWeatherTime", 0),
                    _string("generatorName", "default"),
                    _double("BorderCenterX", 0.0),
                    _double("BorderCenterZ", 0.0),
                    _double("BorderSize", 59999968.0),
                    _double("BorderWarningBlocks", 5.0),
                    _compound(
                        "GameRules",
                        [
                            _string("doDaylightCycle", "true"),
                            _string("doMobSpawning", "true"),
                            _string("doFireTick", "false"),
                            _string("keepInventory", "true"),
                            _string("mobGriefing", "false"),
                            _string("randomTickSpeed", "3"),
                            _string("showDeathMessages", "true"),
                            _string("spawnRadius", "10"),
                        ],
                    ),
                    _compound(
                        "Version",
                        [
                            _int("Id", 3700),
                            _string("Name", "1.20.4"),
                            _string("Series", "main"),
                            _byte("Snapshot", 0),
                        ],
                    ),
                    _compound(
                        "DataPacks",
                        [
                            _list("Enabled", [_string("", "vanilla")]),
                            _list(
                                "Disabled",
                                [_string("", "bundle"), _string("", "trade_rebalance")],
                            ),
                        ],
                    ),
                    _compound(
                        "WorldGenSettings",
                        [
                            _long("seed", -4172144997902289642),
                            _byte("generate_features", 1),
                            _byte("bonus_chest", 0),
                        ],
                    ),
                    _compound(
                        "CustomBossEvents",
                        [
                            _compound(
                                "amulet:demo_bar",
                                [
                                    _string("Name", '{"text":"Conversion progress"}'),
                                    _string("Color", "green"),
                                    _int("Max", 100),
                                    _int("Value", 64),
                                    _byte("Visible", 1),
                                ],
                            )
                        ],
                    ),
                ],
            )
        ],
    )


def _chunk_root() -> Tag:
    return _compound(
        "",
        [
            _int("DataVersion", 3700),
            _int("xPos", -1),
            _int("zPos", -4),
            _int("yPos", -4),
            _string("Status", "minecraft:full"),
            _long("LastUpdate", 148262880),
            _long("InhabitedTime", 91240),
            _byte("isLightOn", 1),
            _list(
                "sections",
                [
                    _compound(
                        "",
                        [
                            _byte("Y", 5),
                            _compound(
                                "block_states",
                                [
                                    _list(
                                        "palette",
                                        [
                                            _compound(
                                                "", [_string("Name", "minecraft:air")]
                                            ),
                                            _compound(
                                                "", [_string("Name", "minecraft:stone")]
                                            ),
                                            _compound(
                                                "",
                                                [
                                                    _string(
                                                        "Name", "minecraft:deepslate"
                                                    ),
                                                    _compound(
                                                        "Properties",
                                                        [_string("axis", "y")],
                                                    ),
                                                ],
                                            ),
                                        ],
                                    ),
                                    _long_array(
                                        "data",
                                        [
                                            1229782938247303441,
                                            -8608480567731124088,
                                            2459565876494606882,
                                            0,
                                        ],
                                    ),
                                ],
                            ),
                            _compound(
                                "biomes",
                                [
                                    _list(
                                        "palette",
                                        [_string("", "minecraft:plains")],
                                    )
                                ],
                            ),
                            _byte_array("SkyLight", [15, 15, 15, 14, 12, 9, 4, 0]),
                            _byte_array("BlockLight", [0, 0, 3, 7, 11, 14, 15, 15]),
                        ],
                    )
                ],
            ),
            _compound(
                "Heightmaps",
                [
                    _long_array(
                        "MOTION_BLOCKING",
                        [
                            2310355422147575808,
                            2310355422147575808,
                            2310355422147575809,
                        ],
                    ),
                    _long_array(
                        "WORLD_SURFACE",
                        [
                            2310355422147575808,
                            2310355422147575810,
                            2310355422147575808,
                        ],
                    ),
                ],
            ),
            _list(
                "block_entities",
                [
                    _compound(
                        "",
                        [
                            _string("id", "minecraft:chest"),
                            _int("x", -2),
                            _int("y", 98),
                            _int("z", -49),
                            _byte("keepPacked", 0),
                        ],
                    ),
                    _compound(
                        "",
                        [
                            _string("id", "minecraft:sign"),
                            _int("x", -6),
                            _int("y", 99),
                            _int("z", -52),
                            _string("Text1", '{"text":"Mine entrance"}'),
                        ],
                    ),
                ],
            ),
            _list("block_ticks", []),
            _list("fluid_ticks", []),
            _compound(
                "structures",
                [
                    _compound("starts", []),
                    _compound(
                        "References",
                        [
                            _long_array(
                                "minecraft:mineshaft", [-4294967295, 12884901889]
                            )
                        ],
                    ),
                ],
            ),
        ],
    )


#: One builder per source key.  Each returns a fresh tree so two open editors
#: never share mutable tags.
SAMPLE_BUILDERS: Dict[str, Callable[[], Tag]] = {
    "blockEntity": _block_entity_root,
    "entity": _entity_root,
    "itemStack": _item_stack_root,
    "player": _player_root,
    "levelDat": _level_dat_root,
    "chunk": _chunk_root,
}


def source(key: str) -> SourceInfo:
    """Return the source record for a key, falling back to the default one.

    A design key -- ``item``, ``level`` -- names the same source as the model's
    own ``itemStack`` and ``levelDat``, so either opens the right document.
    """
    wanted = SOURCE_ALIASES.get(str(key), str(key))
    for item in SOURCES:
        if item.key == wanted:
            return item
    return SOURCES[0]


def sample_document(key: str = DEFAULT_SOURCE) -> NbtDocument:
    """Build one of the six built-in documents.

    An unknown key opens the default source rather than raising: the editor is
    opened from ribbon buttons, palettes, and other surfaces, and a mistyped
    key should show a usable window with the wrong data selected rather than
    no window at all.
    """
    info = source(key)
    builder = SAMPLE_BUILDERS.get(info.key, _block_entity_root)
    return NbtDocument(info, builder())


def sample_documents() -> Dict[str, NbtDocument]:
    """Build all six documents, keyed by source."""
    return {info.key: sample_document(info.key) for info in SOURCES}


def sample_tag_counts() -> Dict[str, int]:
    """Return how many tags each source holds, for the rail's count column."""
    return {info.key: sample_document(info.key).tag_count() for info in SOURCES}


def scope_counts() -> Dict[str, int]:
    """Return how many of each thing are in scope, as the design's rail counts.

    This is not the tag count above: the rail says there are 812 chunks and 26
    block entities to choose between, while the tag count says how many tags
    are inside the one being edited.  Both are useful and they are not the same
    number, so they are not the same function either.
    """
    return {info.key: int(info.count) for info in SOURCES if info.count}


__all__ = [
    "ARRAY_TYPES",
    "AXIS_COLOURS",
    "BOOLEAN_NAMES",
    "COLOUR_NAMES",
    "COLOUR_SWATCHES",
    "CONTAINER_TYPES",
    "CONTROL_KINDS",
    "ControlSpec",
    "DEFAULT_SOURCE",
    "DESIGN_DEFAULT_SOURCE",
    "DYE_COLOURS",
    "ENUM_OPTIONS",
    "FieldSpec",
    "HEX_LIMIT",
    "INVENTORY_NAMES",
    "LONGTEXT_NAMES",
    "NUMERIC_ENUMS",
    "NUMERIC_TYPES",
    "NbtDocument",
    "Revision",
    "RetypeReport",
    "SAMPLE_BUILDERS",
    "SLIDER_NAMES",
    "SOURCES",
    "SOURCE_ALIASES",
    "SOURCE_FIELDS",
    "SnbtError",
    "SourceInfo",
    "TAG_HINTS",
    "TAG_RANGES",
    "TAG_TYPES",
    "TYPE_DEFS",
    "TYPE_INFO",
    "Tag",
    "TagType",
    "TagTypeInfo",
    "TreeRow",
    "VECTOR_NAMES",
    "ValidationResult",
    "axis_colour",
    "coerce_float",
    "coerce_integer",
    "colour_hex",
    "colour_value",
    "control_for",
    "enum_index",
    "enum_label",
    "fields_for",
    "format_float",
    "format_key",
    "format_scalar",
    "hex_dump",
    "matching_fields",
    "parse_snbt",
    "quote_string",
    "range_caption",
    "retype_preview",
    "sample_document",
    "sample_documents",
    "sample_tag_counts",
    "scope_counts",
    "source",
    "tag_hint",
    "to_binary",
    "to_snbt",
    "tree_lines_for",
    "type_badge",
    "type_for_label",
    "type_label",
    "validate",
    "validate_tree",
]
