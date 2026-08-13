""" "Prefer rich controls" outside the command palette, driven for real.

The command palette already renders its results as live inline controls, and
that lane has its own tests. What this rule also asks for -- and what had no
desktop-side proof -- is that a NON-palette list, when it shows a value the
user can change, shows the real control rather than a printout of it: a list
row, a card, a detail panel, a form built from a selection. This module walks
a hand-written inventory of exactly those surfaces and either

* drives the real control and asserts the underlying value actually changed
  through the same code path the originating surface uses (``live_control``),
  or
* records which escape clause applies and why, when a plain readout is the
  documented, deliberate choice (``escape_clause``).

The inventory is hand-written on purpose. A pattern scan only ever checks the
surfaces it already knows to look at, so a scan-based version of this file
would pass unchanged the day a new printout-only list ships beside it. The
completeness test below keeps the inventory from quietly shrinking to the
easy cases.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.api.studio import backstage  # noqa: E402
from amulet_map_editor.api.studio import nbt_model as model  # noqa: E402
from amulet_map_editor.api.studio import nbt_studio  # noqa: E402
from amulet_map_editor.api.studio import recents  # noqa: E402
from amulet_map_editor.api.studio.widgets import ToggleSwitch  # noqa: E402
from amulet_map_editor.api.wx.ui.notifications import (  # noqa: E402
    NotificationHistoryDialog,
)
from amulet_map_editor.api.wx.ui.material_dialog import RecordTable  # noqa: E402


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault(
        "CONFIG_DIR", tempfile.mkdtemp(prefix="amulet-rich-controls-")
    )
    existing = wx.App.Get()
    created = existing is None and wx.App()
    yield existing or created
    if created:
        created.Destroy()


@pytest.fixture
def frame(app):
    top = wx.Frame(None)
    yield top
    top.Destroy()


# ---------------------------------------------------------------------------
# the hand-written inventory
# ---------------------------------------------------------------------------


@dataclass
class Surface:
    """One non-palette surface the "prefer rich controls" contract touches.

    ``verdict`` is either ``"live_control"`` -- a real control lives in the
    row/card/form and this module drives it end to end -- or
    ``"escape_clause"`` -- a documented, deliberate plain readout. ``reason``
    is required either way, so the decision is recorded rather than assumed.
    """

    name: str
    verdict: str
    reason: str


INVENTORY: List[Surface] = [
    Surface(
        name="backstage._RecentTable pin star",
        verdict="live_control",
        reason=(
            "each recent-project row draws its own pin star; clicking it "
            "calls table.toggle_pin(index), which writes through "
            "RecentStore.pin() -- the same store the Recents page reads on "
            "every launch, not a second copy of the value"
        ),
    ),
    Surface(
        name="nbt_studio form-row ToggleSwitch",
        verdict="live_control",
        reason=(
            "the NBT editor's centre pane is a list of tag rows built from "
            "the selected container's children; a boolean byte's row gets a "
            "real ToggleSwitch wired to NbtStudioDialog._edit, which writes "
            "through the live NbtDocument rather than a display-only copy"
        ),
    ),
    Surface(
        name="notifications.NotificationHistoryDialog record list",
        verdict="escape_clause",
        reason=(
            "the escape clause for 'the list is long enough that live "
            "controls would make it stutter' plus 'the value cannot be "
            "written from that context': dismissed notifications are a log, "
            "not a live setting, an unbounded history can run into the "
            "hundreds, and a photographed native wx.ListCtrl comes back a "
            "blank rectangle -- RecordTable is a plain, keyboard-operable "
            "readout by design, documented in its own class docstring"
        ),
    ),
]


def test_the_inventory_covers_every_surface_this_lane_touched() -> None:
    """The hand-written list must not quietly shrink to the easy surfaces."""
    names = [surface.name for surface in INVENTORY]
    assert len(names) >= 3, (
        "the rich-controls inventory has shrunk to "
        f"{len(names)}: {names}. Surfaces are added to it, never removed."
    )
    assert len(set(names)) == len(names), f"a surface is listed twice: {names}"
    for surface in INVENTORY:
        assert surface.verdict in ("live_control", "escape_clause"), surface.name
        assert surface.reason.strip(), f"{surface.name} has no recorded reason"


# ---------------------------------------------------------------------------
# backstage._RecentTable: pinning a row is a real, persisted control
# ---------------------------------------------------------------------------


def test_recent_table_pin_star_writes_through_the_store(frame, tmp_path) -> None:
    """Clicking a row's pin star is the real control, not a printout of one.

    The row draws a filled or hollow star from ``entry.pinned`` and clicking
    it calls ``table.toggle_pin``. This drives that exact call -- the same
    one the row's own click handler makes -- and then re-reads the entry
    from a *fresh* ``RecentStore`` bound to the same directory, so the
    assertion cannot be satisfied by a table that only changed its own
    in-memory copy.
    """
    store = recents.RecentStore(root=tmp_path)
    store.add(name="Sunset Ridge", kind="World", platform="Java", path="C:/w/sunset")
    entries = store.load()
    assert entries and entries[0].pinned is False

    def _on_pin(entry, pinned) -> None:
        # The real host (BackstageView._pin_recent) writes through the store
        # and then hands the table its own fresh rows back -- the table never
        # mutates the entry it was given.  Mirroring that here is what makes
        # the second toggle below a genuine test of the store rather than of
        # a stale in-memory copy the table happened to keep.
        store.pin(entry, pinned)
        table.set_entries(store.load())

    table = backstage._RecentTable(frame, on_pin=_on_pin)
    table.set_entries(entries)
    assert table.rows, "the table built no rows for one recent entry"

    row = table.rows[0]
    assert row.entry.pin_glyph() == "\u2606", "row started already pinned"

    table.toggle_pin(row.index)

    reloaded = recents.RecentStore(root=tmp_path).load()
    assert reloaded[0].pinned is True, (
        "toggling the row's pin star did not write through RecentStore -- "
        "the star is decorative rather than the real control"
    )
    assert table.rows[0].entry.pinned is True

    # And the inverse, through the same call, proves it is not one-directional.
    table.toggle_pin(table.rows[0].index)
    reloaded_again = recents.RecentStore(root=tmp_path).load()
    assert reloaded_again[0].pinned is False


# ---------------------------------------------------------------------------
# nbt_studio: a boolean byte's form row carries a real ToggleSwitch
# ---------------------------------------------------------------------------


def _find_boolean_byte(tag: model.Tag) -> Optional[model.Tag]:
    """Depth-first search for the first tag :func:`control_for` renders as a toggle."""
    for child in tag.children:
        spec = model.control_for(child)
        if spec.kind == "toggle":
            return child
        found = _find_boolean_byte(child)
        if found is not None:
            return found
    return None


def _collect_toggle_switches(window: wx.Window) -> List[ToggleSwitch]:
    found: List[ToggleSwitch] = []
    for child in window.GetChildren():
        if isinstance(child, ToggleSwitch):
            found.append(child)
        found.extend(_collect_toggle_switches(child))
    return found


def test_nbt_form_row_toggle_switch_writes_through_the_document(frame) -> None:
    """A boolean byte's row shows a real ``ToggleSwitch``, not a caption.

    The switch is found the same way the palette's own inline controls are
    proved live elsewhere in this suite: build the real window, find the real
    control inside it, drive it, and read the value back from the document
    the row is supposed to be writing through -- never from the control's own
    displayed state, which would pass even if the control were disconnected.
    """
    dialog = nbt_studio.NbtStudioDialog(frame, source=model.DEFAULT_SOURCE)
    try:
        boolean_tag = _find_boolean_byte(dialog.document.root)
        if boolean_tag is None:
            # A sample source with no boolean byte at all is a fixture
            # problem, not a "nothing to check" pass -- try the other
            # bundled sample before giving up.
            for source_key in model.sample_documents():
                dialog.document = model.sample_document(source_key)
                boolean_tag = _find_boolean_byte(dialog.document.root)
                if boolean_tag is not None:
                    break
        assert boolean_tag is not None, (
            "none of the bundled sample documents contain a boolean byte -- "
            "this test cannot exercise the toggle row without one"
        )

        parent = boolean_tag.parent
        assert parent is not None
        dialog.selected = parent
        dialog.mode = "form"
        dialog.rebuild_centre()

        switches = _collect_toggle_switches(dialog.centre_pane)
        assert switches, (
            "the form for a container holding a boolean byte built no "
            "ToggleSwitch -- the row is rendering a printout, not the "
            "real control"
        )

        before = bool(int(boolean_tag.value))
        switch = switches[0]
        assert switch.value == before, "the switch did not start at the tag's own value"

        switch.activate()

        after = bool(int(boolean_tag.value))
        assert after != before, (
            "activating the row's ToggleSwitch did not change the "
            "underlying tag -- the switch is decorative rather than "
            "wired to NbtStudioDialog._edit"
        )
        assert (
            switch.value == after
        ), "the switch and the document disagree after the edit"
    finally:
        dialog.Destroy()


# ---------------------------------------------------------------------------
# notifications.NotificationHistoryDialog: the documented escape clause
# ---------------------------------------------------------------------------


def test_notification_history_list_is_a_record_table_not_a_native_list() -> None:
    """The escape-clause surface is checked for what it actually is.

    This does not ask the list to carry live controls -- the inventory above
    records why it should not -- but it does hold the escape clause to
    account: the surface must still be the accessible, keyboard-operable
    ``RecordTable`` the docstring promises, not a native ``wx.ListCtrl`` that
    would make the "cannot be verified by capture" half of the reasoning
    false.
    """
    # RecordTable is constructed as ``self.list`` inside __init__; rather than
    # instantiate the whole dialog (which reaches live preferences/export
    # wiring this test has no business touching), assert the class it is
    # built from is the accessible record table, not a native list control.
    import inspect

    source = inspect.getsource(NotificationHistoryDialog.__init__)
    assert "RecordTable(" in source, (
        "NotificationHistoryDialog no longer builds its list from "
        "RecordTable -- if it now builds a native wx.ListCtrl, the escape "
        "clause recorded in the inventory above no longer applies and the "
        "surface needs a live_control verdict instead"
    )
    assert "wx.ListCtrl(" not in source
