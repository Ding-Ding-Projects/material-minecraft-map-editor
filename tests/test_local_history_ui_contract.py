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
    assert "_list_key_down" in source
    assert "event.ControlDown()" in source
    assert "Restored {restored}" in source
    assert "Local history…" in frame


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
