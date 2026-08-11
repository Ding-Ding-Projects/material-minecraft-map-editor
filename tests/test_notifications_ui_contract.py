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


def test_notification_history_dismisses_every_selected_record():
    """Select two, dismiss, and check both went.

    This replaces two source assertions -- ``"wx.LIST_STATE_SELECTED" in
    source`` and ``"_list_key_down" in source`` -- that could only ever say the
    file mentioned multi-selection, never that dismissing acted on more than
    one record. Both stayed true while the handler did nothing, and both pinned
    the rows to a native list that no capture can show.
    """
    wx = pytest.importorskip("wx")
    from amulet_map_editor.api import notifications as notification_api
    from amulet_map_editor.api.wx.ui.notifications import NotificationHistoryDialog

    # Held in a local: an unassigned ``wx.App()`` is collected immediately and
    # the next wx call raises "The wx.App object must be created first!".
    app = wx.App.Get() or wx.App()
    assert app is not None
    for index in range(3):
        notification_api.add("info", f"Bulk record {index}", "body")

    frame = wx.Frame(None)
    try:
        dialog = NotificationHistoryDialog(frame)
        try:
            table = dialog.list
            assert table.row_count() >= 3, "the centre listed nothing to dismiss"
            table.select(0)
            table.select(1)
            assert table.selected_indices() == [0, 1]
            targets = {
                dialog._items[index].notification_id
                for index in table.selected_indices()
            }
            dialog._dismiss_selected()
            dismissed = {
                item.notification_id
                for item in notification_api.list_notifications()
                if item.dismissed
            }
            assert (
                targets <= dismissed
            ), "a selected notification survived the dismissal"
        finally:
            dialog.Destroy()
    finally:
        frame.Destroy()


def test_the_close_action_works_on_the_modeless_window_the_shell_opens():
    """The shell opens this centre modeless, so ``EndModal`` would be an error.

    The helper that used to rescue that rebound whatever button carried
    ``wx.ID_CLOSE`` -- and an owner-drawn action has no dialog id to be found
    by, so the rescue silently stopped applying the moment the button stopped
    being a ``wx.Button``. Nothing in the source would show that.
    """
    wx = pytest.importorskip("wx")
    from amulet_map_editor.api.wx.modeless import show_modeless_dialog
    from amulet_map_editor.api.wx.ui.notifications import NotificationHistoryDialog

    app = wx.App.Get() or wx.App()
    assert app is not None
    frame = wx.Frame(None)
    try:
        dialog = show_modeless_dialog(
            frame, "notification-history-test", NotificationHistoryDialog
        )
        assert not dialog.IsModal()
        dialog.close_button.activate()
        for _ in range(3):
            wx.Yield()
        assert not dialog, "the close action did not destroy the modeless window"
    finally:
        frame.Destroy()


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
