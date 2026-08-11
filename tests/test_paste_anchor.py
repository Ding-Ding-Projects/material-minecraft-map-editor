"""Where a paste lands, and which point of it a typed position names.

The paste tool's ``location`` is the **centre** of the structure, not a corner.
amulet-core's clone takes ``rotation_point = (min + max) // 2`` of the source
bounds and displaces the whole copy by ``location - rotation_point``, so a
4 by 1 by 4 slab sent to ``(8, 40, 8)`` fills ``(6, 40, 6)..(9, 40, 9)``.  That
is a real observation rather than a reading of the source: ``tests/
test_editor_clone_runtime.py`` drives the built editor against a real world and
finds the gold there.

Nothing in the interface said so, which makes it the most likely reading of
"cloning doesn't work" from somebody who typed the coordinate they wanted and
went to look for the blocks.  :mod:`amulet_map_editor.api.studio.editor_tools`
now works the box out from the extent and the transform, so the pane can show
it beside the numbers as they are typed and offer to name a corner instead.

This module is arithmetic only.  The pane that shows it is checked in
``tests/test_paste_anchor_ui_contract.py``, and the whole route -- typed corner
to blocks in a world -- in ``tests/test_editor_clone_runtime.py``.
"""

from __future__ import annotations

from typing import Sequence, Tuple

import pytest

from amulet_map_editor.api.studio import editor_tools


def core_box(
    source_minimum: Sequence[int], extent: Sequence[int], location: Sequence[int]
) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
    """Return the box amulet-core's own clone fills, worked out its way.

    A deliberate second implementation, transcribed from the ``else`` branch of
    ``amulet/api/level/base_level/clone.py`` -- the one a paste with no rotation
    and no scale takes::

        rotation_point = ((src_selection.max_array + src_selection.min_array) // 2)
        offset = numpy.asarray(location).astype(int) - rotation_point
        moved_min_location = src_selection.min_array + offset

    Kept in the test rather than imported so the two arrive at the answer by
    different routes.  ``paste_box`` drops the source position entirely, which
    is only sound because ``(2a + e) // 2 == a + e // 2``; this one keeps it, so
    a case where that identity failed would show up as a disagreement.
    """
    maximum = [low + size for low, size in zip(source_minimum, extent)]
    rotation_point = [(high + low) // 2 for low, high in zip(source_minimum, maximum)]
    offset = [int(value) - point for value, point in zip(location, rotation_point)]
    moved = [low + shift for low, shift in zip(source_minimum, offset)]
    return tuple(moved), tuple(low + size - 1 for low, size in zip(moved, extent))


#: ``(source minimum, extent, location)``.  The first is the case the runtime
#: module actually observed in a world; the rest move the source around to
#: prove the answer does not depend on where the copy came from.
CASES: Tuple[Tuple[Tuple[int, int, int], ...], ...] = (
    ((0, 4, 0), (4, 1, 4), (8, 40, 8)),
    ((13, 70, -22), (5, 3, 7), (0, 0, 0)),
    ((-31, 2, 100), (1, 1, 1), (7, 7, 7)),
    ((4, 4, 4), (2, 2, 2), (-9, 15, 3)),
    ((0, 0, 0), (16, 32, 16), (100, 64, -100)),
    ((7, -60, 7), (3, 9, 2), (12, 5, -40)),
)


def test_the_recorded_observation_is_what_the_box_says() -> None:
    """The one case a real world was watched producing.

    Asserted on its own, before the general agreement below, because every
    other case in this module is arithmetic checked against arithmetic.  This
    one is arithmetic checked against blocks that were seen in a world.
    """
    assert editor_tools.paste_box((8, 40, 8), (4, 1, 4)) == (
        (6, 40, 6),
        (9, 40, 9),
    ), "the 4 by 1 by 4 slab observed at (6, 40, 6)..(9, 40, 9) is reported elsewhere"


@pytest.mark.parametrize("source_minimum, extent, location", CASES)
def test_the_box_agrees_with_amulet_cores_own_arithmetic(
    source_minimum: Tuple[int, int, int],
    extent: Tuple[int, int, int],
    location: Tuple[int, int, int],
) -> None:
    """Two routes to the same box, one of which keeps the source position."""
    assert editor_tools.paste_box(location, extent) == core_box(
        source_minimum, extent, location
    )


@pytest.mark.parametrize("_source, extent, location", CASES)
def test_the_centre_anchor_is_the_editors_own_behaviour(
    _source: Tuple[int, int, int],
    extent: Tuple[int, int, int],
    location: Tuple[int, int, int],
) -> None:
    """Centre must be an exact no-op, or an existing habit silently breaks.

    Somebody who has learned to type a centre and has their own arithmetic in
    their head must get the same result they got yesterday.  That is the whole
    reason centre is the default and the reason this is asserted rather than
    assumed.
    """
    assert editor_tools.anchor_point(location, extent) == location
    assert editor_tools.location_for_anchor(location, extent) == location


@pytest.mark.parametrize("anchor, _label", editor_tools.ANCHORS)
@pytest.mark.parametrize("_source, extent, location", CASES)
def test_an_anchor_reads_back_to_the_position_it_came_from(
    anchor: str,
    _label: str,
    _source: Tuple[int, int, int],
    extent: Tuple[int, int, int],
    location: Tuple[int, int, int],
) -> None:
    """The pane shows one and writes back the other, so they must invert.

    Without this the position drifts by the anchor offset on every refresh: the
    pane reads the tool, converts to an anchor to show it, and converts back
    when the value is typed.  A round trip that is off by one block moves the
    copy every time the live timer fires.
    """
    point = editor_tools.anchor_point(location, extent, anchor=anchor)
    assert point is not None
    assert editor_tools.location_for_anchor(point, extent, anchor=anchor) == location


@pytest.mark.parametrize("_source, extent, location", CASES)
def test_each_anchor_names_the_corner_it_claims_to(
    _source: Tuple[int, int, int],
    extent: Tuple[int, int, int],
    location: Tuple[int, int, int],
) -> None:
    """A named corner is that corner of the box the paste really fills."""
    box = editor_tools.paste_box(location, extent)
    assert box is not None
    minimum, maximum = box

    assert (
        editor_tools.anchor_point(location, extent, anchor=editor_tools.ANCHOR_MINIMUM)
        == minimum
    )
    assert (
        editor_tools.anchor_point(location, extent, anchor=editor_tools.ANCHOR_MAXIMUM)
        == maximum
    )
    base = editor_tools.anchor_point(location, extent, anchor=editor_tools.ANCHOR_BASE)
    assert base is not None
    assert base[1] == minimum[1], "the base anchor sits on the copy's bottom layer"
    centre = editor_tools.anchor_point(location, extent)
    assert centre is not None
    assert (base[0], base[2]) == (
        centre[0],
        centre[2],
    ), "the base anchor is the centre in x and z, and only the height differs"


def test_typing_a_corner_puts_the_blocks_at_that_corner() -> None:
    """The promise the anchor control makes, stated as one assertion.

    Typing ``11, 50, 11`` with the lowest corner chosen must fill a box that
    starts at ``11, 50, 11``.  ``tests/test_editor_clone_runtime.py`` makes the
    same claim about blocks in a real world; this one makes it about the
    arithmetic, so a failure here says which of the two is wrong.
    """
    wanted = (11, 50, 11)
    extent = (4, 1, 4)
    location = editor_tools.location_for_anchor(
        wanted, extent, anchor=editor_tools.ANCHOR_MINIMUM
    )
    assert location is not None
    assert editor_tools.paste_box(location, extent) == (wanted, (14, 50, 14))


def test_a_quarter_turn_swaps_the_axes_of_the_box() -> None:
    """Rotation moves the box, and the readout has to follow it.

    The tool's own rotate buttons turn by ninety degrees, where the transformed
    structure is still axis aligned and this is exact rather than a bound.
    """
    box = editor_tools.paste_box((0, 0, 0), (7, 1, 3), rotation=(0, 90, 0))
    assert box is not None
    minimum, maximum = box
    size = tuple(high - low + 1 for low, high in zip(minimum, maximum))
    assert size == (3, 1, 7), f"a 7 by 1 by 3 copy turned about y is 3 by 1 by 7: {box}"


def test_doubling_the_scale_doubles_the_box() -> None:
    """Scale is part of what the paste writes, so it is part of the box."""
    box = editor_tools.paste_box((0, 0, 0), (4, 2, 4), scale=(2, 2, 2))
    assert box is not None
    minimum, maximum = box
    size = tuple(high - low + 1 for low, high in zip(minimum, maximum))
    assert size == (
        8,
        4,
        8,
    ), f"a 4 by 2 by 4 copy at double scale is 8 by 4 by 8: {box}"


@pytest.mark.parametrize(
    "extent",
    [
        (0, 0, 0),
        (4, 0, 4),
        (-1, 1, 1),
        (60_000_000, 384, 60_000_000),
    ],
)
def test_an_unreadable_size_is_said_rather_than_guessed(
    extent: Tuple[int, int, int],
) -> None:
    """No extent means no box, and no box means no claim.

    ``None`` rather than a zero-sized box at the position, because the pane
    shows whatever comes back: a box quietly reading ``8, 40, 8`` to
    ``8, 40, 8`` for an object whose size nobody could read is a confident
    wrong answer, which is the exact failure this whole surface exists to
    remove.  The last case is a whole world's bounds, which is what an object
    whose level reports the dimension instead of the structure would give.
    """
    assert editor_tools.paste_box((8, 40, 8), extent) is None
    assert editor_tools.anchor_point((8, 40, 8), extent) is None
    assert editor_tools.location_for_anchor((8, 40, 8), extent) is None


def test_an_unknown_anchor_falls_back_to_the_editors_behaviour() -> None:
    """A stored anchor from a build that offered a different set is not fatal."""
    assert editor_tools.normalise_anchor("nonsense") == editor_tools.ANCHOR_CENTRE
    assert editor_tools.normalise_anchor(None) == editor_tools.ANCHOR_CENTRE
    assert editor_tools.normalise_anchor("MINIMUM") == editor_tools.ANCHOR_MINIMUM
    assert editor_tools.anchor_label("nonsense") == "Centre of the copy"


def test_every_anchor_is_named_and_the_names_are_distinct() -> None:
    """The picker shows these, so two of them reading alike would be unusable."""
    keys = [key for key, _label in editor_tools.ANCHORS]
    labels = [label for _key, label in editor_tools.ANCHORS]
    assert len(set(keys)) == len(keys) == 4
    assert len(set(labels)) == len(labels)
    assert editor_tools.ANCHORS[0][0] == editor_tools.ANCHOR_CENTRE, (
        "the editor's own behaviour has to be the first option, because it is "
        "the default and the one an existing habit expects"
    )
