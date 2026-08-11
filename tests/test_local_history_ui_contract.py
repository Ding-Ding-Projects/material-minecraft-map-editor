import pytest
from pathlib import Path


def test_local_history_dialog_is_reachable_and_filterable():
    source = Path("amulet_map_editor/api/wx/ui/local_history.py").read_text(
        encoding="utf-8"
    )
    frame = Path("amulet_map_editor/api/framework/amulet_ui.py").read_text(
        encoding="utf-8"
    )
    assert "class LocalHistoryDialog(wx.Dialog)" in source
    assert "wx.adv.DatePickerCtrl" in source
    assert "RegexBuilderDialog" in source
    assert "self._store.restore" in source
    # Deliberately NOT a source assertion. This line used to read
    # `assert "wx.LC_MULTIPLE_SEL" in source`, and wx has no such
    # constant -- so the dialog raised AttributeError before it could be
    # built, and this test passed anyway, pinning the defect in place.
    assert (
        "wx.LC_MULTIPLE_SEL" not in source
    ), "wx has no LC_MULTIPLE_SEL; naming it stops the dialog constructing"
    assert "Select all" in source
    assert "Invert selection" in source
    assert "Restored {restored}" in source
    assert "Local history…" in frame


def test_local_history_bulk_selection_is_reachable_without_a_pointer():
    """Press the keys. The source assertions this replaces proved nothing.

    They read ``"_list_key_down" in source`` and ``"event.ControlDown()" in
    source``: two substrings that stayed true however the handler behaved, and
    that went on being true when the method was a no-op. They also pinned the
    list to ``wx.ListCtrl``, which contributes nothing to a capture -- so the
    rows, the one part of this window worth photographing, could never be
    checked. This drives the real control instead.
    """
    wx = pytest.importorskip("wx")
    from amulet_map_editor.api.wx.ui.local_history import LocalHistoryDialog

    # Held in a local: an unassigned ``wx.App()`` is collected immediately and
    # the next wx call raises "The wx.App object must be created first!".
    app = wx.App.Get() or wx.App()
    assert app is not None
    frame = wx.Frame(None)
    try:
        dialog = LocalHistoryDialog(frame)
        try:
            table = dialog.list
            table.set_rows(
                [
                    (f"updated", f"record-{index}", "settings", "", "")
                    for index in range(4)
                ]
            )
            assert table.selected_indices() == []

            select_all = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
            select_all.SetKeyCode(ord("A"))
            select_all.SetControlDown(True)
            table._on_key_down(select_all)
            assert table.selected_indices() == [0, 1, 2, 3], "Ctrl+A did not select"

            invert = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
            invert.SetKeyCode(ord("I"))
            invert.SetControlDown(True)
            table._on_key_down(invert)
            assert table.selected_indices() == [], "Ctrl+I did not invert"

            # Shift extends from the anchor, which is what makes a range of
            # events restorable in one action rather than four.
            down = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
            down.SetKeyCode(wx.WXK_DOWN)
            down.SetShiftDown(True)
            table._on_key_down(down)
            table._on_key_down(down)
            assert table.selected_indices() == [0, 1, 2]
        finally:
            dialog.Destroy()
    finally:
        frame.Destroy()


def test_the_local_history_browser_can_actually_be_opened():
    """Construct it. A source check cannot tell whether a dialog is buildable.

    Both of this suite's checks on this file were source assertions, and the
    dialog spent that whole time raising AttributeError on a constant that does
    not exist. The only assertion that would have caught it is this one.
    """
    wx = pytest.importorskip("wx")
    from amulet_map_editor.api.wx.ui.local_history import LocalHistoryDialog

    app = wx.App.Get() or wx.App()
    frame = wx.Frame(None)
    try:
        dialog = LocalHistoryDialog(frame)
        try:
            assert dialog.GetChildren(), "the dialog built no controls"
        finally:
            dialog.Destroy()
    finally:
        frame.Destroy()
