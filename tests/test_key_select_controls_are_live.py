"""The Key Select window's own controls must do what their labels say.

The keys it prints were fixed first: they are read from the 3D editor's live
key group rather than transcribed from a design.  That left the surface's
*controls* still describing a window that does not exist.

===================  ====================================================
Control              What it did
===================  ====================================================
"Active group"       Listed the reader's real key groups, active one
                     pre-selected, wired to nothing.  Picking another
                     left all nineteen key rows where they were.
"Action set"         Offered "3D editor", "Selection", "Camera" -- not
                     things the editor has -- and filtered nothing.
"Save group"         Saved nothing.
"New group"          Created nothing.
"Reset group"        Cleared the window's search boxes and re-read the
                     open world, which is not a key group.
===================  ====================================================

The dropdown is the one that matters, because it is the most convincing: real
options, the right one selected, beside a button that says "Save".  A reader
has every reason to believe they have just changed something.

Each test here was watched failing before it was kept, against the code as it
shipped and against a deliberately broken version of the fix.  Two of them
carry their own precondition, because the interesting assertions are all of the
form "these two readings differ" -- and two readings of nothing also differ from
nothing at all.
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from amulet_map_editor.api.studio import keys as studio_keys
from amulet_map_editor.api.studio import specs as spec_registry
from amulet_map_editor.api.studio.spec import Section, Select, Spec
from amulet_map_editor.api.studio.specs import core


@pytest.fixture(autouse=True)
def _restore_shown_group():
    """Leave the module-level "group being shown" exactly as it was found."""
    before = core._SHOWN_GROUP
    try:
        yield
    finally:
        core.show_group(before)


def _controls() -> Spec:
    spec = spec_registry.get("controls")
    assert spec is not None, "the Key Select surface is no longer registered"
    return spec


def _section(spec: Spec, kind: str) -> Section:
    found = [section for section in spec.sections if section.kind == kind]
    assert found, f"the Key Select surface has no {kind!r} section: " + str(
        [section.kind for section in spec.sections]
    )
    return found[0]


def _selects(spec: Spec) -> List[Select]:
    return [select for section in spec.sections for select in section.selects]


def _printed(spec: Spec) -> Dict[str, str]:
    return {row.action: row.binding for row in _section(spec, "keys").keys}


def _group_dropdown(spec: Spec) -> Select:
    groups = studio_keys.read_key_groups()
    if not groups.ids:
        pytest.skip("this checkout cannot read the editor's key groups")
    selects = _selects(spec)
    assert len(selects) == 1, (
        "the Key Select surface offers a dropdown this test does not know "
        f"about, so nothing checks what picking from it does: "
        f"{[select.label for select in selects]}"
    )
    return selects[0]


def test_the_key_group_dropdown_is_wired_to_something() -> None:
    """A dropdown with no handler is a picture of a dropdown."""
    select = _group_dropdown(_controls())
    assert select.on_change is not None, (
        f"the {select.label!r} dropdown on the Key Select surface has no "
        "change handler, so choosing an option cannot do anything at all"
    )


def test_choosing_a_key_group_moves_the_keys_the_window_prints() -> None:
    """The property the dropdown claims: pick a group, read that group's keys.

    Wiring a handler is not the same as the handler working, so this drives the
    surface the way the window does -- call the handler, build the surface
    again -- and compares the rows against the editor's own table for the group
    that was picked.  Reading them back out of the thing that produced them
    would agree with it whatever it said.
    """
    editor = studio_keys.key_config()
    if editor is None:
        pytest.skip("this checkout has no 3D editor key table to compare against")
    presets = editor.PresetKeybinds

    before_spec = _controls()
    select = _group_dropdown(before_spec)
    before = _printed(before_spec)

    others = [
        option
        for option in select.options
        if option != select.current() and dict(presets.get(option) or {}) != {}
    ]
    if not others:
        pytest.skip("this configuration offers no second preset group to switch to")

    #: A group binding every action exactly as the current one does would make
    #: the comparison below vacuous, so pick one that genuinely differs.
    current = dict(presets.get(select.current()) or {})
    differing = [
        option for option in others if dict(presets.get(option) or {}) != current
    ]
    assert differing, (
        "every other preset key group binds exactly what the active one does, "
        "so switching between them could not move a single row and this test "
        f"would pass on a dead dropdown: {sorted(others)}"
    )
    target = differing[0]

    select.on_change(target)
    after_spec = _controls()
    after = _printed(after_spec)

    moved = {
        action: (before[action], after[action])
        for action in before
        if action in after and before[action] != after[action]
    }
    assert moved, (
        f"the Key Select surface prints exactly the same nineteen keys for "
        f"{select.current()!r} and {target!r}, which bind different keys, so "
        "choosing a group changes nothing the reader can see"
    )

    group = presets[target]
    wrong = {}
    for row in _section(after_spec, "keys").keys:
        action = next(
            (
                name
                for name in studio_keys.declared_actions()
                if studio_keys.action_label(name) == row.action
            ),
            "",
        )
        if not action:
            continue
        expected = (
            studio_keys.format_binding(group.get(action)) or studio_keys.NOT_BOUND
        )
        if row.binding != expected:
            wrong[row.action] = (row.binding, expected)
    assert not wrong, (
        f"with {target!r} chosen the surface prints keys that group does not "
        f"bind (row: printed, bound): {wrong}"
    )


def test_the_window_says_which_group_it_shows_and_which_one_is_live() -> None:
    """Reading a group you are not using must not look like using it.

    The dropdown does not change what the editor listens to -- nothing here
    writes the reader's configuration -- so a window showing one group while
    the editor obeys another has to say so, or it is teaching wrong keys again
    by a different route.
    """
    groups = studio_keys.read_key_groups()
    if not groups.active:
        pytest.skip("this checkout cannot read the editor's key groups")

    spec = _controls()
    select = _group_dropdown(spec)
    assert groups.active in _section(spec, "note").hint, (
        "the note on the Key Select surface does not name the group the "
        f"editor is listening to ({groups.active!r}): "
        f"{_section(spec, 'note').hint!r}"
    )

    others = [option for option in select.options if option != groups.active]
    if not others:
        pytest.skip("this configuration has only one key group")
    target = others[0]

    select.on_change(target)
    note = _section(_controls(), "note").hint
    assert target in note and groups.active in note, (
        f"showing the key group {target!r} while the editor listens to "
        f"{groups.active!r}, the window names neither one or only one of "
        f"them: {note!r}"
    )
    assert "listening to" in note, (
        "the note does not say that the group being shown is not the group "
        f"the editor obeys: {note!r}"
    )


def test_no_control_on_the_surface_promises_something_it_cannot_do() -> None:
    """The three labels that described a window this one is not.

    Named literally rather than derived: a rule computed from the surface's own
    contents would be satisfied by whatever the surface happens to contain,
    which is exactly how these shipped.
    """
    spec = _controls()
    labels = {action.label for action in spec.actions} | {spec.confirm}
    invented = sorted(
        label for label in labels if label in {"Save group", "New group", "Reset group"}
    )
    assert not invented, (
        "the Key Select window offers these buttons again; it saves nothing, "
        f"creates nothing and resets nothing: {invented}"
    )
    dropdowns = sorted(select.label for select in _selects(spec))
    assert "Action set" not in dropdowns, (
        "the invented 'Action set' dropdown is back on the Key Select "
        "surface; the editor has no such concept and it filters nothing"
    )


def test_a_group_that_does_not_exist_falls_back_to_the_live_one() -> None:
    """A stale choice must not leave the window listing nothing.

    ``show_group`` deliberately validates nothing, so this is where the
    fallback is proved: a name the configuration cannot answer for reads the
    active group again rather than emptying the window.
    """
    groups = studio_keys.read_key_groups()
    if not groups.active:
        pytest.skip("this checkout cannot read the editor's key groups")

    core.show_group("a-group-nobody-has")
    spec = _controls()
    printed = _printed(spec)
    assert printed != {studio_keys.UNREADABLE[0]: studio_keys.UNREADABLE[1]}, (
        "choosing a key group that no longer exists emptied the Key Select "
        "window instead of falling back to the group the editor is using"
    )
    assert groups.active in _section(spec, "note").hint, (
        "after a stale group choice the window does not name the group it is "
        f"actually showing: {_section(spec, 'note').hint!r}"
    )
    live = {
        studio_keys.action_label(action): studio_keys.viewport_accelerator(action)
        or studio_keys.NOT_BOUND
        for action in studio_keys.declared_actions()
    }
    assert live, "the editor declares no actions, so this comparison is vacuous"
    assert printed == live, (
        "a stale group choice left the window printing something other than "
        "the live key group"
    )
