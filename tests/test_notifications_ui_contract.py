import pytest

"""Static contract checks for localized notification-history chrome."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_notification_history_uses_persisted_language_resources():
    source = (ROOT / "amulet_map_editor/api/wx/ui/notifications.py").read_text(
        encoding="utf-8"
    )
    resources = (ROOT / "amulet_map_editor/lang/en.lang").read_text(encoding="utf-8")
    for marker in (
        "preferences.load().language_mode",
        '_copy("title", self._language_mode)',
        "notifications.en.title",
        "notifications.zh.title",
        "notifications.en.exported_to",
    ):
        assert marker in source + resources


def test_notification_history_supports_multi_select_bulk_dismissal():
    source = (ROOT / "amulet_map_editor/api/wx/ui/notifications.py").read_text(
        encoding="utf-8"
    )
    assert "wx.LC_REPORT | wx.LC_SINGLE_SEL" not in source
    assert "wx.LIST_STATE_SELECTED" in source
    assert "notifications.bulk_dismiss(selected)" in source
    # Deliberately NOT a source assertion. This line used to read
    # `assert "wx.LC_MULTIPLE_SEL" in source`, and wx has no such
    # constant -- so the dialog raised AttributeError before it could be
    # built, and this test passed anyway, pinning the defect in place.
    assert (
        "wx.LC_MULTIPLE_SEL" not in source
    ), "wx has no LC_MULTIPLE_SEL; naming it stops the dialog constructing"
    assert '_copy("select_all"' in source
    assert '_copy("invert_selection"' in source
    assert "_list_key_down" in source


def test_notification_history_exposes_complete_technical_details_and_copy():
    source = (ROOT / "amulet_map_editor/api/wx/ui/notifications.py").read_text(
        encoding="utf-8"
    )
    for marker in (
        'name="Notification technical details"',
        "item.details",
        "self.copy_details.Enable(bool(details))",
        "wx.TheClipboard.SetData(wx.TextDataObject(value))",
        '_copy("copy_details", self._language_mode)',
    ):
        assert marker in source


def test_the_notification_centre_can_actually_be_opened():
    """Construct it. A source check cannot tell whether a dialog is buildable.

    Both of this suite's checks on this file were source assertions, and the
    dialog spent that whole time raising AttributeError on a constant that does
    not exist. The only assertion that would have caught it is this one.
    """
    wx = pytest.importorskip("wx")
    from amulet_map_editor.api.wx.ui.notifications import NotificationHistoryDialog

    app = wx.App.Get() or wx.App()
    frame = wx.Frame(None)
    try:
        dialog = NotificationHistoryDialog(frame)
        try:
            assert dialog.GetChildren(), "the dialog built no controls"
        finally:
            dialog.Destroy()
    finally:
        frame.Destroy()
