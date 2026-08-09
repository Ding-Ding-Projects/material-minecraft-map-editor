"""Material 3 path picker used as the app-owned file-dialog surface."""

from __future__ import annotations

from pathlib import Path

import wx

from amulet_map_editor.api.wx.material3 import apply_material3


class MaterialPathDialog(wx.Dialog):
    """A bounded, keyboard-accessible path editor with an explicit Browse action."""

    def __init__(
        self,
        parent: wx.Window,
        title: str,
        *,
        wildcard: str = "All files (*.*)|*.*",
        save: bool = False,
        directory: bool = False,
        default_path: str = "",
    ):
        super().__init__(parent, title=title, size=wx.Size(680, 190))
        self._wildcard = wildcard
        self._save = save
        self._directory = directory
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(
            wx.StaticText(self, label="Path", name="Path picker label"),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            16,
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.path = wx.TextCtrl(self, value=default_path, name="Path picker value")
        self.path.SetHint("Type a path or choose Browse")
        row.Add(self.path, 1, wx.EXPAND | wx.RIGHT, 8)
        self.browse = wx.Button(self, label="Browse…", name="Browse path")
        row.Add(self.browse, 0)
        root.Add(row, 0, wx.EXPAND | wx.ALL, 16)
        actions = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        root.Add(actions, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        self.SetSizer(root)
        self.browse.Bind(wx.EVT_BUTTON, self._browse)
        apply_material3(self)

    def _browse(self, _event: wx.Event) -> None:
        if self._directory:
            with wx.DirDialog(self, "Choose a folder") as dialog:
                if dialog.ShowModal() == wx.ID_OK:
                    self.path.SetValue(dialog.GetPath())
                    self.path.SetFocus()
            return
        style = wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT if self._save else wx.FD_OPEN
        if not self._save:
            style |= wx.FD_FILE_MUST_EXIST
        with wx.FileDialog(
            self,
            "Choose a path",
            defaultFile=Path(self.path.GetValue()).name,
            wildcard=self._wildcard,
            style=style,
        ) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.path.SetValue(dialog.GetPath())
                self.path.SetFocus()

    def value(self) -> str:
        return self.path.GetValue().strip()


def choose_path(parent: wx.Window, title: str, **kwargs) -> str | None:
    dialog = MaterialPathDialog(parent, title, **kwargs)
    try:
        if dialog.ShowModal() == wx.ID_OK and dialog.value():
            return dialog.value()
        return None
    finally:
        dialog.Destroy()
