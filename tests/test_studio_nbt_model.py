"""The wx-free half of the NBT editor: parsing, validation, retyping, history.

Almost nothing that makes the NBT editor careful is drawing.  Deciding that a
byte named ``keepPacked`` is a boolean and deserves a switch, that a Long
retyped to an Int has to be clamped and the user told so, that restoring an old
revision must leave the state it replaced still reachable -- that is arithmetic
and tables, and all of it can be exercised without a display.  This file does,
so a machine with no wxPython still proves the part of the editor that can
quietly corrupt a world.
"""

from __future__ import annotations

import pytest

from amulet_map_editor.api.studio import nbt_model as nbt

#: Every tag type the format has, in the order the type switcher draws them.
EXPECTED_TAG_TYPES = (
    "byte",
    "short",
    "int",
    "long",
    "float",
    "double",
    "string",
    "list",
    "compound",
    "byte_array",
    "int_array",
    "long_array",
)

#: The six documents the rail lists.
EXPECTED_SOURCES = (
    "blockEntity",
    "entity",
    "itemStack",
    "player",
    "levelDat",
    "chunk",
)


# ---------------------------------------------------------------------------
# the type table
# ---------------------------------------------------------------------------
def test_all_twelve_tag_types_are_present_and_described():
    assert tuple(item.value for item in nbt.TAG_TYPES) == EXPECTED_TAG_TYPES
    for tag_type in nbt.TAG_TYPES:
        info = nbt.TYPE_INFO[tag_type]
        assert info.label
        assert info.badge
        assert nbt.type_label(tag_type) == info.label
        assert nbt.type_for_label(info.label) is tag_type


def test_the_numeric_container_and_array_families_do_not_overlap():
    numeric = set(nbt.NUMERIC_TYPES)
    arrays = set(nbt.ARRAY_TYPES)
    containers = set(nbt.CONTAINER_TYPES)
    assert numeric.isdisjoint(arrays)
    assert numeric.isdisjoint(containers)
    assert arrays.isdisjoint(containers)
    assert nbt.TagType.STRING not in numeric | arrays | containers


# ---------------------------------------------------------------------------
# SNBT
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("source", EXPECTED_SOURCES)
def test_every_sample_document_round_trips_through_snbt(source):
    document = nbt.sample_document(source)
    text = document.snbt()
    reparsed = nbt.parse_snbt(text, name=document.root.name)
    assert nbt.to_snbt(reparsed) == text


def test_snbt_keeps_the_suffix_that_says_which_numeric_type_a_tag_is():
    text = nbt.to_snbt(
        nbt.parse_snbt("{a: 1b, b: 2s, c: 3, d: 4L, e: 5.0f, f: 6.0d}"),
        pretty=False,
    )
    for fragment in ("1b", "2s", "3", "4L", "5", "6"):
        assert fragment in text
    assert "1b" in text and "2s" in text and "4L" in text


def test_a_round_trip_preserves_arrays_and_nested_containers():
    original = (
        "{ints: [I; 1, 2, 3], longs: [L; 9L], bytes: [B; 1b], deep: {list: [{x: 1}]}}"
    )
    once = nbt.to_snbt(nbt.parse_snbt(original), pretty=False)
    twice = nbt.to_snbt(nbt.parse_snbt(once), pretty=False)
    assert once == twice
    assert "[I;" in once and "[L;" in once and "[B;" in once


def test_a_string_survives_the_quoting_it_needs():
    text = nbt.to_snbt(
        nbt.parse_snbt('{name: "he said \\"stop\\"", path: "a\\\\b"}'), pretty=False
    )
    reparsed = nbt.parse_snbt(text)
    assert reparsed.child("name").value == 'he said "stop"'
    assert reparsed.child("path").value == "a\\b"


def test_malformed_snbt_is_refused_with_the_place_it_gave_up():
    with pytest.raises(nbt.SnbtError) as failure:
        nbt.parse_snbt("{a: 1, b:}")
    assert failure.value.position >= 0
    with pytest.raises(nbt.SnbtError):
        nbt.parse_snbt("{unterminated: 'oops")
    with pytest.raises(nbt.SnbtError):
        nbt.parse_snbt("")


def test_the_hex_view_is_produced_from_the_documents_real_bytes():
    document = nbt.sample_document("itemStack")
    payload = nbt.to_binary(document.root)
    assert isinstance(payload, (bytes, bytearray))
    assert payload
    dump = nbt.hex_dump(payload)
    assert dump.splitlines()
    assert document.hex_view() == nbt.hex_dump(nbt.to_binary(document.root))


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def test_an_integer_outside_its_width_is_reported_rather_than_wrapped_quietly():
    document = nbt.sample_document("blockEntity")
    tag = document.root.child("x")
    result = document.set_value(tag, 2**31)
    assert result.ok is False
    assert result.severity == "error"
    assert "outside the valid range" in result.message
    assert "-2147483648" in result.message and "2147483647" in result.message


def test_a_value_inside_its_width_validates_cleanly():
    document = nbt.sample_document("blockEntity")
    tag = document.root.child("x")
    result = document.set_value(tag, 12)
    assert result.ok is True
    assert result.severity == "ok"
    assert tag.value_text() == "12"


@pytest.mark.parametrize(
    "tag_type,bound",
    (
        (nbt.TagType.BYTE, 127),
        (nbt.TagType.SHORT, 32767),
        (nbt.TagType.INT, 2**31 - 1),
        (nbt.TagType.LONG, 2**63 - 1),
    ),
)
def test_each_integer_width_accepts_its_own_maximum_and_refuses_one_more(
    tag_type, bound
):
    tag = nbt.Tag("value", tag_type, bound)
    assert nbt.validate(tag).ok is True
    tag.value = bound + 1
    assert nbt.validate(tag).ok is False


def test_a_float_that_cannot_be_held_exactly_says_so_instead_of_lying():
    document = nbt.sample_document("entity")
    tag = nbt.Tag("speed", nbt.TagType.FLOAT, 0.0)
    document.root.append(tag)
    document.apply_value(tag, 0.1)
    assert tag.value == nbt.to_float32(0.1)
    assert nbt.format_float(tag.value, double=False)


def test_validating_the_whole_tree_finds_a_problem_anywhere_in_it():
    document = nbt.sample_document("blockEntity")
    assert document.validate_all().ok is True
    document.root.child("x").value = 2**40
    assert document.validate_all().ok is False


def test_two_children_of_one_compound_cannot_share_a_name():
    document = nbt.sample_document("blockEntity")
    tag = document.root.child("x")
    result = document.rename(tag, "y")
    assert result.ok is False
    assert tag.name == "x"


# ---------------------------------------------------------------------------
# retyping
# ---------------------------------------------------------------------------
def test_a_widening_retype_loses_nothing_and_says_so():
    document = nbt.sample_document("blockEntity")
    report = nbt.retype_preview(document.root.child("y"), nbt.TagType.LONG)
    assert report.ok is True
    assert report.lossy is False
    assert "Nothing is lost" in report.message


def test_a_narrowing_retype_reports_the_exact_value_it_would_clamp():
    document = nbt.sample_document("blockEntity")
    report = nbt.retype_preview(document.root.child("LootTableSeed"), nbt.TagType.INT)
    assert report.ok is True
    assert report.lossy is True
    assert "clamped" in report.message
    assert report.value == -(2**31)
    assert report.notes


def test_retyping_a_value_to_a_container_says_the_value_is_discarded():
    document = nbt.sample_document("blockEntity")
    report = nbt.retype_preview(document.root.child("id"), nbt.TagType.COMPOUND)
    assert report.lossy is True
    assert "discarded" in report.message


def test_retyping_a_double_to_a_byte_warns_about_both_losses():
    tag = nbt.Tag("value", nbt.TagType.DOUBLE, 1234.5)
    report = nbt.retype_preview(tag, nbt.TagType.BYTE)
    assert report.lossy is True
    assert len(report.notes) >= 1
    assert -128 <= report.value <= 127


def test_applying_a_retype_changes_the_tag_and_records_it():
    document = nbt.sample_document("blockEntity")
    tag = document.root.child("y")
    report = document.retype(tag, nbt.TagType.BYTE)
    assert report.ok is True
    assert tag.tag_type is nbt.TagType.BYTE
    actions = [revision.action for revision in document.history(tag)]
    assert "retype" in actions


# ---------------------------------------------------------------------------
# per-tag controls
# ---------------------------------------------------------------------------
def test_a_byte_that_is_really_a_boolean_gets_a_switch():
    document = nbt.sample_document("blockEntity")
    control = nbt.control_for(document.root.child("keepPacked"))
    assert control.kind == "toggle"
    assert control.hint


def test_a_bounded_number_gets_the_range_it_is_actually_bounded_by():
    document = nbt.sample_document("itemStack")
    count = document.find("root.Count") or document.root.child("Count")
    if count is None:  # pragma: no cover - the sample always carries one
        pytest.skip("the item-stack sample no longer carries a Count tag")
    control = nbt.control_for(count)
    assert control.minimum < control.maximum
    assert control.minimum <= control.number <= control.maximum


def test_every_control_kind_a_tag_can_ask_for_is_one_the_editor_draws():
    for source in EXPECTED_SOURCES:
        document = nbt.sample_document(source)
        for tag in [document.root, *document.root.descendants()]:
            control = nbt.control_for(tag)
            assert control.kind in nbt.CONTROL_KINDS, f"{source}: {tag.name}"
            assert control.label


def test_a_search_over_the_tree_opens_the_branches_a_result_is_hiding_in():
    document = nbt.sample_document("blockEntity")
    everything = 1 + len(list(document.root.descendants()))
    opened = document.rows(matches=lambda text: "oak_planks" in text)
    assert any("oak_planks" in row.label for row in opened)
    assert 0 < len(opened) < everything
    # Every branch on the way to a result is open, so nothing found is hidden.
    assert all(row.caret != "▸" for row in opened if row.expandable)


def test_a_colour_tag_translates_both_ways():
    assert nbt.colour_hex(0xFF0000).upper().endswith("FF0000")
    assert nbt.colour_value(nbt.colour_hex(0x3F51B5)) == 0x3F51B5


# ---------------------------------------------------------------------------
# history: restoring writes a new revision
# ---------------------------------------------------------------------------
def test_the_first_edit_records_the_state_the_tag_was_opened_in():
    document = nbt.sample_document("blockEntity")
    tag = document.root.child("x")
    assert document.history(tag) == ()
    document.set_value(tag, 5)
    history = document.history(tag)
    assert history[0].action == "baseline"
    assert "-2" in history[0].detail


def test_restoring_appends_a_revision_rather_than_rewinding_the_history():
    document = nbt.sample_document("blockEntity")
    tag = document.root.child("x")
    document.set_value(tag, 5)
    document.set_value(tag, 9)
    before = document.history(tag)
    assert [revision.action for revision in before] == ["baseline", "edit", "edit"]

    restored = document.restore(tag, before[0])
    after = document.history(tag)
    assert tag.value_text() == "-2"
    assert len(after) == len(before) + 1
    assert after[: len(before)] == before, "history must be append-only"
    assert after[-1] is restored
    assert restored.action == "restore"
    assert restored.label not in {revision.label for revision in before}


def test_an_undo_can_itself_be_undone_because_nothing_was_discarded():
    document = nbt.sample_document("blockEntity")
    tag = document.root.child("x")
    document.set_value(tag, 5)
    edited = document.history(tag)[-1]
    document.restore(tag, document.history(tag)[0])
    assert tag.value_text() == "-2"
    document.restore(tag, edited)
    assert tag.value_text() == "5"
    assert [revision.action for revision in document.history(tag)] == [
        "baseline",
        "edit",
        "restore",
        "restore",
    ]


def test_a_snapshot_is_detached_so_later_edits_cannot_reach_back_into_it():
    document = nbt.sample_document("blockEntity")
    tag = document.root.child("x")
    document.set_value(tag, 5)
    baseline = document.history(tag)[0]
    document.set_value(tag, 77)
    assert baseline.snapshot.value_text() == "-2"
    document.restore(tag, baseline)
    document.restore(tag, baseline)
    assert tag.value_text() == "-2"


def test_restoring_a_container_brings_its_children_back_too():
    document = nbt.sample_document("blockEntity")
    items = document.root.child("Items")
    document.record(items, "baseline", "before the deletion")
    baseline = document.history(items)[0]
    removed = list(items.children)[0]
    assert document.delete(removed) is True
    shrunken = len(items.children)
    document.restore(items, baseline)
    assert len(items.children) == shrunken + 1


def test_a_document_that_has_been_edited_says_so_and_can_be_marked_saved():
    document = nbt.sample_document("blockEntity")
    assert document.dirty is False
    document.set_value(document.root.child("x"), 3)
    assert document.dirty is True
    assert document.dirty_text()
    document.mark_committed()
    assert document.dirty is False


# ---------------------------------------------------------------------------
# the six sources
# ---------------------------------------------------------------------------
def test_the_rail_lists_the_six_documented_sources():
    assert tuple(item.key for item in nbt.SOURCES) == EXPECTED_SOURCES
    for item in nbt.SOURCES:
        assert item.label and item.glyph and item.pill and item.summary
    assert nbt.DEFAULT_SOURCE == "blockEntity"


def test_an_unknown_source_opens_the_default_one_rather_than_nothing():
    assert nbt.sample_document("no-such-source").key == nbt.DEFAULT_SOURCE
    assert nbt.source("no-such-source").key == nbt.DEFAULT_SOURCE


def test_two_open_documents_never_share_a_tag():
    first = nbt.sample_document("player")
    second = nbt.sample_document("player")
    first.set_value(first.root.child("Health"), 3)
    assert (
        second.root.child("Health").value_text()
        != first.root.child("Health").value_text()
    )


def test_every_source_reports_how_many_tags_it_holds():
    counts = nbt.sample_tag_counts()
    assert set(counts) == set(EXPECTED_SOURCES)
    assert all(value > 0 for value in counts.values())
