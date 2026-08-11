"""Borderless Material 3 confirmation surface for blocking decisions."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import wx

from amulet_map_editor.api import preferences
from amulet_map_editor.api.studio import widgets as studio
from amulet_map_editor.api.wx.material3 import apply_material3


class MaterialConfirmDialog(wx.Dialog):
    """Small app-owned confirmation dialog with wx-compatible result IDs."""

    def __init__(
        self, parent: wx.Window, message: str, style: int, title: str | None = None
    ):
        super().__init__(
            parent,
            title=preferences.load().display_name if title is None else title,
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        root = wx.BoxSizer(wx.VERTICAL)
        body = studio.StudioText(
            self, message, size_px=13, role="on_surface", wrap_width=640
        )
        root.Add(body, 1, wx.ALL | wx.EXPAND, 20)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.AddStretchSpacer()
        if style & wx.YES:
            yes = studio.StudioButton(self, "Yes", variant="filled", name="Yes")
            yes.SetId(wx.ID_YES)
            yes.Bind(wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_YES))
            buttons.Add(yes, 0, wx.LEFT, 8)
        if style & wx.NO:
            no = studio.StudioButton(self, "No", variant="outlined", name="No")
            no.SetId(wx.ID_NO)
            no.Bind(wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_NO))
            buttons.Add(no, 0, wx.LEFT, 8)
        if style & wx.CANCEL:
            cancel = studio.StudioButton(
                self, "Cancel", variant="outlined", name="Cancel"
            )
            cancel.SetId(wx.ID_CANCEL)
            cancel.Bind(wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_CANCEL))
            buttons.Add(cancel, 0, wx.LEFT, 8)
            self.SetEscapeId(wx.ID_CANCEL)
        root.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 12)
        self.SetSizerAndFit(root)
        apply_material3(self)


@contextmanager
def material_confirmation(
    parent: wx.Window, message: str, style: int, title: str | None = None
) -> Iterator[MaterialConfirmDialog]:
    """Yield an M3 confirmation dialog while preserving normal wx cleanup."""

    with MaterialConfirmDialog(parent, message, style, title) as dialog:
        yield dialog


def show_material_confirmation(
    parent: wx.Window, message: str, style: int, title: str | None = None
) -> int:
    """Show a blocking decision and return wx.ID_YES/NO/CANCEL."""

    with material_confirmation(parent, message, style, title) as dialog:
        return dialog.ShowModal()
