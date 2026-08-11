"""The six Coordinates boxes, and what each one means to the live selection.

Selection > Coordinates draws six text boxes -- ``x1``, ``x2``, ``y1``, ``y2``,
``z1``, ``z2`` -- and until this module existed each of them shipped a literal
number transcribed from the design mock.  Nothing wrote them from the open world
and nothing read them back, so the ribbon displayed a selection box that did not
exist, and went on displaying it while the real selection was dragged, added to,
and cleared.  That is worse than a control that does nothing: an inert control
disappoints, while this one *asserted* six facts about the user's world and
every one of them was false.

The table below is what makes the six boxes addressable.  Each entry names the
corner point and the axis its box stands for, which is exactly enough to read a
number out of ``selection_corners`` and to write one back in.

This is a module of its own rather than another table inside
:mod:`amulet_map_editor.api.studio.ribbon_defs` because that module says of
itself that it is "deliberately pure data ... no behaviour beyond lookup and
filtering", and :func:`parse_selection_box` is behaviour: it decides what a
typed string means and refuses the ones that mean nothing usable.  Keeping the
decision here also keeps it testable without importing the whole ribbon, and
without wxPython -- the same reason the ribbon's own definitions live away from
the widget that paints them.

Nothing here imports the ribbon, so the dependency runs one way: the ribbon
builds its six fields from this table, and this module never learns that a
ribbon exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

__all__ = [
    "SELECTION_COMMAND",
    "SELECTION_FIELDS",
    "SELECTION_FIELD_LABELS",
    "SELECTION_GROUP",
    "SELECTION_LIMIT",
    "SELECTION_TAB",
    "SelectionField",
    "parse_selection_box",
    "selection_box_values",
    "selection_field",
    "selection_field_problems",
]

#: The shell command a committed edit in one of the boxes raises.
SELECTION_COMMAND = "setSelectionBounds"

#: Where the six boxes are drawn, so a caller looking for them does not have to
#: guess at either spelling.
SELECTION_TAB = "selection"
SELECTION_GROUP = "Coordinates"

#: The furthest a coordinate may sit from the origin: Minecraft's own hard world
#: limit.  Not a taste judgement -- a mistyped ``999999999`` describes a box no
#: world contains, and applying it silently moves the selection somewhere the
#: user cannot see, cannot find, and cannot get back from without undoing
#: something nobody told them had happened.
SELECTION_LIMIT = 30_000_000

#: One selection box, as the editor keeps it: two corner points of three ints.
BoxType = Tuple[Tuple[int, int, int], Tuple[int, int, int]]


@dataclass(frozen=True)
class SelectionField:
    """One coordinate box, and the number inside the selection it stands for.

    ``point`` is which of the editor's two corner points the box belongs to --
    ``0`` is the green point 1 and ``1`` is the blue point 2, the same two the
    *Move point 1* and *Move point 2* tiles beside these boxes drive -- and
    ``axis`` is ``0``, ``1`` or ``2`` for X, Y or Z.  Together they address
    exactly one number in ``selection_corners``.
    """

    label: str
    point: int
    axis: int

    @property
    def axis_name(self) -> str:
        """Return ``X``, ``Y`` or ``Z``, for a message a person has to read."""
        return "XYZ"[self.axis] if self.axis in (0, 1, 2) else "?"


#: The six boxes, in the order the design's grid draws them.
#:
#: Hand-written rather than derived from the labels, for the same reason
#: ``ribbon_defs.STRUCTURE_FORMATS`` is written out beside its exporters: a rule
#: that reads ``x1`` as "the X of point 1" is one renamed label away from
#: silently addressing a different number, and writing the wrong corner of
#: somebody's selection is indistinguishable from working right up until they
#: look at what they just deleted.  A table can be read and disagreed with; a
#: derivation cannot.
SELECTION_FIELDS: Tuple[SelectionField, ...] = (
    SelectionField("x1", 0, 0),
    SelectionField("x2", 1, 0),
    SelectionField("y1", 0, 1),
    SelectionField("y2", 1, 1),
    SelectionField("z1", 0, 2),
    SelectionField("z2", 1, 2),
)

#: Every coordinate box label, in grid order.
SELECTION_FIELD_LABELS: Tuple[str, ...] = tuple(item.label for item in SELECTION_FIELDS)

_BY_LABEL: Dict[str, SelectionField] = {item.label: item for item in SELECTION_FIELDS}


def selection_field(label: str) -> Optional[SelectionField]:
    """Return the coordinate box called ``label``, or ``None``."""
    return _BY_LABEL.get(str(label))


def selection_box_values(box: Optional[Any]) -> Dict[str, str]:
    """Return what the six boxes must show for one selection box.

    ``None`` -- nothing selected -- gives six empty strings rather than six
    plausible numbers.  There is no box to describe, and a number here reads as
    a description of one; six of them read as a description of a box the user
    can act on, which is the defect this whole module exists to remove.
    """
    if box is None:
        return {item.label: "" for item in SELECTION_FIELDS}
    return {
        item.label: str(int(box[item.point][item.axis])) for item in SELECTION_FIELDS
    }


def parse_selection_box(values: Mapping[str, str]) -> Tuple[Optional[BoxType], str]:
    """Turn six typed strings into one selection box, or say what is wrong.

    Returns ``(box, "")`` or ``(None, problem)``.  The problem is a whole
    sentence naming the box it is about and what to type instead, because it is
    shown to somebody who has just typed something and is looking at the field
    they typed it into.  ``"Invalid input"`` beside a red outline tells that
    person nothing they did not already know.

    Three shapes are refused and one deliberately is not:

    * anything that is not a whole number, a blank box and ``1.5`` included;
    * anything past :data:`SELECTION_LIMIT`;
    * a pair equal on any axis, because a box with no thickness contains no
      blocks at all.  Every operation would then run on nothing and report
      success, which is the quietest failure this interface can produce;
    * a **reversed** pair is not refused.  The editor keeps a selection as two
      corner points rather than as bounds, and the *Move point 1* tile beside
      these boxes will happily drag point 1 past point 2, so refusing what the
      neighbouring control does would be this interface disagreeing with itself.
      The axis is ordered instead -- and because the boxes are re-read from the
      world after every applied edit, the ordering is shown back rather than
      done quietly.
    """
    corner: Dict[Tuple[int, int], int] = {}
    for item in SELECTION_FIELDS:
        raw = str(values.get(item.label, "")).strip()
        if not raw:
            return None, (
                f"{item.label} is empty. Type the {item.axis_name} coordinate of "
                "the box as a whole number of blocks."
            )
        try:
            number = int(raw)
        except ValueError:
            return None, (
                f"{item.label} must be a whole number of blocks, like -12. It "
                f"reads “{raw}”."
            )
        if abs(number) > SELECTION_LIMIT:
            return None, (
                f"{item.label} is {number:,}, which is further out than a "
                f"Minecraft world reaches ({SELECTION_LIMIT:,} blocks from the "
                "origin). Type a coordinate inside the world."
            )
        corner[(item.point, item.axis)] = number
    low: List[int] = []
    high: List[int] = []
    for axis in (0, 1, 2):
        first, second = corner[(0, axis)], corner[(1, axis)]
        if first == second:
            names = [item.label for item in SELECTION_FIELDS if item.axis == axis]
            return None, (
                f"{names[0]} and {names[1]} are both {first}, so the box would "
                f"be empty along {'XYZ'[axis]} and would contain no blocks. Give "
                "one of them a different value."
            )
        low.append(min(first, second))
        high.append(max(first, second))
    return ((low[0], low[1], low[2]), (high[0], high[1], high[2])), ""


def selection_field_problems(drawn: Iterable[Tuple[str, str]]) -> List[str]:
    """Return every fault in the table, and in the boxes the ribbon draws.

    ``drawn`` is ``(label, value)`` for each field the Coordinates group really
    builds, so the check is made against the grid on screen rather than against
    the table's own copy of itself.  A table that agrees with itself proves
    nothing; the interesting failure is a box drawn that nothing can fill, or a
    literal creeping back into the definition.
    """
    problems: List[str] = []
    labels = [item.label for item in SELECTION_FIELDS]
    pairs = [(item.point, item.axis) for item in SELECTION_FIELDS]
    for item in SELECTION_FIELDS:
        if not item.label:
            problems.append("A selection coordinate box has no label")
        if item.point not in (0, 1):
            problems.append(
                f"Coordinate box {item.label!r} names corner point {item.point}, "
                "and a selection box has only points 0 and 1"
            )
        if item.axis not in (0, 1, 2):
            problems.append(
                f"Coordinate box {item.label!r} names axis {item.axis}, and a "
                "coordinate has only axes 0, 1 and 2"
            )
    for label in {item for item in labels if labels.count(item) > 1}:
        problems.append(f"Coordinate box {label!r} is listed twice")
    for point, axis in {item for item in pairs if pairs.count(item) > 1}:
        problems.append(
            f"Two coordinate boxes both address point {point} on axis {axis}, so "
            "one of them writes over the other's number"
        )
    for point in (0, 1):
        for axis in (0, 1, 2):
            if (point, axis) not in pairs:
                problems.append(
                    f"No coordinate box addresses point {point} on axis {axis}, "
                    "so that corner of the selection cannot be read or typed"
                )
    rows = list(drawn)
    if [label for label, _value in rows] != labels:
        problems.append(
            "The Coordinates group does not draw the six boxes this table "
            "addresses, so a box on screen is bound to nothing"
        )
    for label, value in rows:
        if value:
            problems.append(
                f"Coordinate box {label!r} ships the literal value {value!r}, "
                "which is shown as though it described the open world's selection"
            )
    return problems
