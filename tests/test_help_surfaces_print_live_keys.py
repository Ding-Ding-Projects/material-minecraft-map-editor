"""A key printed in help must be a key that works.

The Key Select window is the surface a user opens *to learn the keys*, and it
was printing six the editor is not bound to.  Measured against the shipped key
group before this was written:

===========================  =================  ================
Row                          Window said        Editor listens for
===========================  =================  ================
Rotate Camera                ``MMB``            ``RMB``
Increase Selection Distance  ``Ctrl+Scroll ↑``  ``R``
Decrease Selection Distance  ``Ctrl+Scroll ↓``  ``F``
Deselect Active Box          ``Esc``            ``Ctrl+D``
Inspect Block                ``RMB``            ``Alt``
Toggle Projection            ``P``              ``Tab``
===========================  =================  ================

The rows had been transcribed from the design, which is a written-down copy of
a binding and therefore a copy that can stop matching it.  A user who had
rebound any of the nineteen was being taught the shipped default on top of that.

**The first test alone would not have caught it, and would not catch its
return.**  Comparing what the surface prints against the same lookup the
surface builds it from passes on any two things that agree, including two
blanks and two stale copies.  So it is guarded twice over:

* :func:`test_the_live_key_lookup_is_actually_answering` proves the lookup
  answers with a real key for every row, so the comparison is never vacuous.
* :func:`test_the_key_select_surface_follows_a_change_of_key_group` changes the
  user's key group underneath the surface and asserts the printed keys move
  with it.  A written-down string cannot pass that one by construction, which
  is the property the fix is actually claiming.

Every assertion here was watched failing against a deliberately wrong binding
before it was kept.
"""

from __future__ import annotations

from typing import Dict, Mapping, Tuple

import pytest

from amulet_map_editor.api.studio import context_menu, keys as studio_keys
from amulet_map_editor.api.studio import specs as spec_registry
from amulet_map_editor.api.studio.spec import Section, Spec

#: Each row the Key Select window lists, and the 3D editor action it reports.
#: Written out here rather than imported from the module under test: a table
#: that is read back out of the implementation agrees with the implementation
#: whatever the implementation says.
_ROW_ACTIONS: Mapping[str, str] = {
    "Move Up": "ACT_MOVE_UP",
    "Move Down": "ACT_MOVE_DOWN",
    "Move Forwards": "ACT_MOVE_FORWARDS",
    "Move Backwards": "ACT_MOVE_BACKWARDS",
    "Move Left": "ACT_MOVE_LEFT",
    "Move Right": "ACT_MOVE_RIGHT",
    "Select Box": "ACT_BOX_CLICK",
    "Add Box": "ACT_BOX_CLICK_ADD",
    "Rotate Camera": "ACT_CHANGE_MOUSE_MODE",
    "Increase Speed (3D)": "ACT_INCR_SPEED",
    "Decrease Speed (3D)": "ACT_DECR_SPEED",
    "Zoom In (2D)": "ACT_ZOOM_IN",
    "Zoom Out (2D)": "ACT_ZOOM_OUT",
    "Increase Selection Distance": "ACT_INCR_SELECT_DISTANCE",
    "Decrease Selection Distance": "ACT_DECR_SELECT_DISTANCE",
    "Deselect All Boxes": "ACT_DESELECT_ALL_BOXES",
    "Deselect Active Box": "ACT_DESELECT_BOX",
    "Inspect Block": "ACT_INSPECT_BLOCK",
    "Toggle Projection": "ACT_CHANGE_PROJECTION",
}

#: Two preset groups that bind the same actions to different keys, and one row
#: each that must move between them.  Read from the editor's own presets in the
#: test body; named here so a preset that stops existing fails loudly.
_ALTERNATE_GROUP = "left"
_MOVED_ROWS: Tuple[str, ...] = (
    "Move Forwards",
    "Increase Selection Distance",
)


def _controls() -> Spec:
    """Return the Key Select surface as the shell would open it."""
    spec = spec_registry.get("controls")
    assert spec is not None, "the Key Select surface is no longer registered"
    return spec


def _key_section(spec: Spec) -> Section:
    """Return the surface's bindings section, failing when it has none."""
    sections = [section for section in spec.sections if section.kind == "keys"]
    assert sections, (
        "the Key Select surface lists no key bindings at all, so the rule below "
        f"has nothing to check: {[section.kind for section in spec.sections]}"
    )
    assert len(sections) == 1, "the Key Select surface grew a second keys section"
    return sections[0]


def _printed() -> Dict[str, str]:
    """Return what the surface prints, as ``row label -> key``."""
    return {row.action: row.binding for row in _key_section(_controls()).keys}


def test_the_key_select_surface_prints_the_keys_the_editor_listens_for() -> None:
    """The window a user opens to learn the keys must not teach a wrong one."""
    printed = _printed()
    missing = sorted(set(_ROW_ACTIONS) - set(printed))
    assert not missing, (
        "these rows are named by this test but are no longer on the Key Select "
        f"surface, so the rule silently stopped covering them: {missing}"
    )
    unnamed = sorted(set(printed) - set(_ROW_ACTIONS))
    assert not unnamed, (
        "these rows appeared on the Key Select surface without this test "
        "knowing which action they report, so nothing checks the key they "
        f"print: {unnamed}"
    )
    wrong = {}
    for label, action in _ROW_ACTIONS.items():
        live = studio_keys.viewport_accelerator(action)
        if printed[label] != live:
            wrong[label] = (printed[label], live)
    assert not wrong, (
        "these Key Select rows print a key the 3D editor is not bound to "
        f"(row: printed, really bound): {wrong}"
    )


def test_the_live_key_lookup_is_actually_answering() -> None:
    """Without this, the rule above passes on a lookup that returns nothing.

    ``viewport_accelerator`` answers with an empty string for anything it
    cannot read, and the surface would then print empty keys -- which match an
    empty lookup on every row and prove nothing whatsoever.
    """
    answered = {
        action: studio_keys.viewport_accelerator(action)
        for action in _ROW_ACTIONS.values()
    }
    blank = sorted(action for action, key in answered.items() if not key)
    assert not blank, (
        "the live keybind lookup answered nothing for these actions, so the "
        f"comparison above is vacuous: {blank}"
    )
    printed = _printed()
    unbound = sorted(
        label for label, key in printed.items() if key == studio_keys.NOT_BOUND
    )
    assert not unbound, (
        "the surface reported these rows as unbound, which would also match a "
        f"lookup that answered nothing: {unbound}"
    )


def test_the_key_select_surface_follows_a_change_of_key_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Change the user's key group and the printed keys must change with it.

    This is the assertion a written-down string cannot pass.  The surface is
    rebuilt against a different preset and its rows are compared against that
    preset's own bindings, read straight out of the editor rather than through
    the code being tested.
    """
    from amulet_map_editor.api import config
    from amulet_map_editor.programs.edit.api.key_config import PresetKeybinds

    assert _ALTERNATE_GROUP in PresetKeybinds, (
        f"the preset key group {_ALTERNATE_GROUP!r} this test switches to no "
        f"longer exists: {sorted(PresetKeybinds)}"
    )

    before = _printed()

    real_get = config.get

    def _switched(identifier: str, default=None):
        if identifier == "amulet_edit":
            stored = dict(real_get(identifier, default) or {})
            stored["keybind_group"] = _ALTERNATE_GROUP
            return stored
        return real_get(identifier, default)

    monkeypatch.setattr(config, "get", _switched)
    after = _printed()

    moved = {label: (before[label], after[label]) for label in _MOVED_ROWS}
    unchanged = sorted(label for label, pair in moved.items() if pair[0] == pair[1])
    assert not unchanged, (
        "these rows print the same key for two key groups that bind them "
        "differently, so the surface is not reading the live group at all: "
        f"{ {label: moved[label] for label in unchanged} }"
    )

    group = PresetKeybinds[_ALTERNATE_GROUP]
    wrong = {}
    for label, action in _ROW_ACTIONS.items():
        expected = studio_keys.format_binding(group.get(action))
        if after[label] != expected:
            wrong[label] = (after[label], expected)
    assert not wrong, (
        f"with the {_ALTERNATE_GROUP!r} key group active these rows print "
        f"something that group does not bind (row: printed, bound): {wrong}"
    )


def test_no_menu_row_writes_down_a_key_the_shared_table_already_binds() -> None:
    """A row that restates a bound key is a second copy that can drift.

    The ribbon's "Command palette" row carried ``Ctrl+Shift+F`` as literal text
    beside a table entry binding the same key -- the same two-places-to-edit
    shape the Key Select rows were in, and invisible from the built menu, since
    a restated accelerator and a resolved one are the same string.  So this
    reads the source: a ``_item(...)`` call that passes *both* a literal
    ``accel=`` and a ``command=``/``surface=`` the table answers for.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(context_menu))
    restated = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        if name != "_item":
            continue
        stated: Dict[str, str] = {}
        for keyword in node.keywords:
            if keyword.arg in ("accel", "command", "surface") and isinstance(
                keyword.value, ast.Constant
            ):
                stated[str(keyword.arg)] = str(keyword.value.value)
        accel = stated.get("accel", "")
        if not accel:
            continue
        bound = context_menu.accelerator(
            command=stated.get("command", ""), surface=stated.get("surface", "")
        )
        if bound:
            label = node.args[0].value if node.args else "?"
            restated.append((label, accel, bound))
    assert not restated, (
        "these menu rows write down an accelerator the shared table already "
        "binds; drop the literal so the row resolves it (row, written, bound): "
        f"{restated}"
    )


def test_the_two_accelerator_tables_say_the_same_thing() -> None:
    """The palette prints one table's keys and the menus print the other's.

    ``commands`` and ``context_menu`` each hold a copy, and nothing had ever
    checked that the copies agree -- so a key edited in one place would be
    advertised two different ways by two surfaces of the same shell.
    """
    from amulet_map_editor.api.studio import commands

    mismatched = commands.mismatched_accelerators()
    assert not mismatched, (
        "the command registry and the context menus advertise different keys "
        f"(key, commands, context_menu): {mismatched}"
    )


def test_the_palette_pill_advertises_the_chord_the_hook_answers_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one shortcut the shell teaches on screen must be the one it obeys.

    The pill's text, the chord the character hook compares against, and the
    accelerator table were three hand-written copies of one binding.  This
    drives a real ``EVT_CHAR_HOOK`` through the installed handler rather than
    calling it directly, so a handler that was written and never bound fails.

    The near-miss press is the control: without it, a hook that fires on
    *every* key would satisfy the positive case, and so would a hook that had
    been deleted along with the binding it guards -- both of which have shipped
    green in this repository before.
    """
    wx = pytest.importorskip("wx")

    from amulet_map_editor.api.studio import context_menu, title_bar

    advertised = context_menu.accelerator(surface="palette")
    assert advertised, "the shell no longer binds a key to the command palette"
    assert title_bar.palette_accelerator() == advertised, (
        "the palette pill advertises a key the shared table does not bind: "
        f"{title_bar.palette_accelerator()!r} against {advertised!r}"
    )

    flags, code = title_bar.PALETTE_ACCELERATOR
    parsed = context_menu.parse_accelerator(advertised)
    assert parsed == (flags, code), (
        "the chord the character hook compares against is not the chord the "
        f"table binds: {(flags, code)} against {parsed}"
    )

    app = wx.App.Get() or wx.App()
    frame = wx.Frame(None)
    opened: list = []
    remove = title_bar.install_palette_shortcut(frame, lambda: opened.append(True))
    try:

        def _press(key_code: int, *, ctrl: bool, shift: bool, alt: bool) -> None:
            event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
            event.SetEventObject(frame)
            event.SetKeyCode(key_code)
            event.SetControlDown(ctrl)
            event.SetShiftDown(shift)
            event.SetAltDown(alt)
            frame.GetEventHandler().ProcessEvent(event)

        _press(
            code,
            ctrl=bool(flags & wx.ACCEL_CTRL),
            shift=bool(flags & wx.ACCEL_SHIFT),
            alt=bool(flags & wx.ACCEL_ALT),
        )
        assert opened, (
            f"pressing {advertised}, the chord the shell advertises, did not "
            "open the command palette"
        )

        opened.clear()
        _press(
            code,
            ctrl=not bool(flags & wx.ACCEL_CTRL),
            shift=bool(flags & wx.ACCEL_SHIFT),
            alt=bool(flags & wx.ACCEL_ALT),
        )
        assert not opened, (
            "the palette opened for a chord missing one of its modifiers, so "
            "the positive case above proves nothing about the modifiers"
        )
    finally:
        remove()
        frame.Destroy()
        del app
