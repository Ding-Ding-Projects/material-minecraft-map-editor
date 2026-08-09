"""Borderless Material 3 confirmation surface for blocking decisions."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import wx

from amulet_map_editor.api.wx.material3 import apply_material3


class MaterialConfirmDialog(wx.Dialog):
    """Small app-owned confirmation dialog with wx-compatible result IDs."""

    def __init__(self, parent: wx.Window, message: str, style: int, title: str = "Amulet"):
        super().__init__(
            parent,
            title=title,
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        root = wx.BoxSizer(wx.VERTICAL)
        body = wx.StaticText(self, label=message)
        body.Wrap(640)
        root.Add(body, 1, wx.ALL | wx.EXPAND, 20)

        buttons = wx.StdDialogButtonSizer()
        if style & wx.YES:
            yes = wx.Button(self, wx.ID_YES, "Yes")
            yes.Bind(wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_YES))
            buttons.AddButton(yes)
        if style & wx.NO:
            no = wx.Button(self, wx.ID_NO, "No")
            no.Bind(wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_NO))
            buttons.AddButton(no)
        if style & wx.CANCEL:
            cancel = wx.Button(self, wx.ID_CANCEL, "Cancel")
            cancel.Bind(wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_CANCEL))
            buttons.AddButton(cancel)
            self.SetEscapeId(wx.ID_CANCEL)
        buttons.Realize()
        root.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 12)
        self.SetSizerAndFit(root)
        apply_material3(self)


@contextmanager
def material_confirmation(
    parent: wx.Window, message: str, style: int, title: str = "Amulet"
) -> Iterator[MaterialConfirmDialog]:
    """Yield an M3 confirmation dialog while preserving normal wx cleanup."""

    with MaterialConfirmDialog(parent, message, style, title) as dialog:
        yield dialog


def show_material_confirmation(
    parent: wx.Window, message: str, style: int, title: str = "Amulet"
) -> int:
    """Show a blocking decision and return wx.ID_YES/NO/CANCEL."""

    with material_confirmation(parent, message, style, title) as dialog:
        return dialog.ShowModal()
