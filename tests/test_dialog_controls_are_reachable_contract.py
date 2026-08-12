"""No dialog may render a control the user cannot reach.

A dialog that clips its own confirm button is not a cosmetic defect: it is a
dialog that cannot be completed.  The path picker shipped exactly that -- a
fixed 190-pixel height, a 44-pixel Material title bar prepended after
construction, and an OK button laid out from y=150 to y=190 against a client
area only 146 pixels tall.  Every automated check passed, because every one of
them asserted source text.

This constructs the real dialogs and measures where their children actually
land, which is the only way that failure is visible.
"""

from __future__ import annotations

import pytest

wx = pytest.importorskip("wx")


@pytest.fixture(scope="module")
def app():
    # Reuse a live ``wx.App`` when the session already has one, and only
    # create -- and later destroy -- a fresh instance when it does not.
    # Unconditionally creating a second ``wx.App`` while one is already
    # current silently orphans it, and destroying that second instance then
    # clears wx's notion of "the current app" out from under every other
    # test module -- the exact sequence that corrupts wxPython's SIP class
    # table for platform-native widgets such as ``wx.PopupTransientWindow``.
    existing = wx.App.Get()
    created = existing is None and wx.App()
    yield existing or created
    if created:
        created.Destroy()


def _clipped(window) -> list[str]:
    """Return a description of every visible child outside its parent."""
    offenders: list[str] = []
    client = window.GetClientSize()
    for child in window.GetChildren():
        if not child.IsShown():
            continue
        rect = child.GetRect()
        if rect.GetBottom() > client.height or rect.GetRight() > client.width:
            offenders.append(
                f"{type(child).__name__} {child.GetName()!r} at {tuple(rect)} "
                f"outside client {tuple(client)}"
            )
    return offenders


def test_the_path_dialog_confirm_button_is_reachable(app):
    """The dialog must be completable: its confirm button must be on screen."""
    from amulet_map_editor.api.wx.ui.path_dialog import MaterialPathDialog

    frame = wx.Frame(None)
    try:
        dialog = MaterialPathDialog(
            frame, "Choose a world folder", directory=True, default_path="C:\tmp"
        )
        try:
            dialog.Layout()
            confirm = dialog.FindWindow(wx.ID_OK)
            assert confirm is not None, "the dialog has no confirm button at all"
            assert confirm.IsShown(), "the confirm button exists but is hidden"
            client = dialog.GetClientSize()
            rect = confirm.GetRect()
            assert rect.GetBottom() <= client.height, (
                f"the confirm button ends at y={rect.GetBottom()} in a client area "
                f"only {client.height} tall, so the dialog cannot be completed"
            )
            assert not _clipped(dialog), _clipped(dialog)
        finally:
            dialog.Destroy()
    finally:
        frame.Destroy()


def test_the_path_dialog_accepts_the_typed_path_on_enter(app):
    """Typing a path and pressing Enter is the route people reach for first."""
    from amulet_map_editor.api.wx.ui.path_dialog import MaterialPathDialog

    frame = wx.Frame(None)
    try:
        dialog = MaterialPathDialog(frame, "Choose a world folder", directory=True)
        try:
            assert (
                dialog.path.GetWindowStyleFlag() & wx.TE_PROCESS_ENTER
            ), "the path field cannot report Enter, so pressing it does nothing"
        finally:
            dialog.Destroy()
    finally:
        frame.Destroy()


def test_the_path_dialog_height_follows_its_content(app):
    """A fixed height cannot survive a title bar, a scale, or a translation."""
    from amulet_map_editor.api.wx.ui.path_dialog import MaterialPathDialog

    frame = wx.Frame(None)
    try:
        dialog = MaterialPathDialog(frame, "Choose a world folder", directory=True)
        try:
            best = dialog.GetSizer().GetMinSize()
            assert dialog.GetSize().height >= best.height, (
                f"the dialog is {dialog.GetSize().height} tall but its content "
                f"needs {best.height}"
            )
        finally:
            dialog.Destroy()
    finally:
        frame.Destroy()
