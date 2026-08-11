"""Material 3 path picker used as the app-owned file-dialog surface."""

from __future__ import annotations

from pathlib import Path

import wx

from amulet_map_editor.api import lang, preferences
from amulet_map_editor.api.wx.material3 import apply_material3


def _copy(key: str, mode: str) -> str:
    english = lang.get(f"path.en.{key}")
    cantonese = lang.get(f"path.zh.{key}")
    if mode == "cantonese":
        return cantonese
    if mode == "bilingual":
        return f"{english} · {cantonese}"
    return english


def tokens_scaled(value: int) -> int:
    """Scale a dimension by the persisted UI scale, with a safe fallback."""
    try:
        return max(1, round(value * float(preferences.load().ui_scale)))
    except Exception:
        return value


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
        self._language_mode = preferences.load().language_mode
        # No fixed height. The shared Material chrome prepends a title bar after
        # construction, and a hard-coded height pushed the OK and Cancel buttons
        # below the visible area -- a dialog with no way to confirm it. The
        # sizer decides the height, so the buttons cannot be clipped off by a
        # taller title bar, a larger UI scale, or a longer translated label.
        super().__init__(parent, title=title)
        self._wildcard = wildcard
        self._save = save
        self._directory = directory
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(
            wx.StaticText(
                self,
                label=_copy("label", self._language_mode),
                name="Path picker label",
            ),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            16,
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.path = wx.TextCtrl(
            self,
            value=default_path,
            name="Path picker value",
            style=wx.TE_PROCESS_ENTER,
        )
        self.path.SetHint(_copy("hint", self._language_mode))
        row.Add(self.path, 1, wx.EXPAND | wx.RIGHT, 8)
        self.browse = wx.Button(
            self,
            label=_copy("browse", self._language_mode),
            name="Browse path",
        )
        row.Add(self.browse, 0)
        root.Add(row, 0, wx.EXPAND | wx.ALL, 16)
        actions = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        root.Add(actions, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        self.SetSizer(root)
        self.browse.Bind(wx.EVT_BUTTON, self._browse)

        # Typing a path and pressing Enter is the fastest route through this
        # dialog and the one people reach for first, so it confirms rather than
        # doing nothing.
        self.path.Bind(wx.EVT_TEXT_ENTER, self._confirm)
        confirm = self.FindWindow(wx.ID_OK)
        if confirm is not None:
            confirm.SetDefault()
            confirm.SetName("Confirm path")

        apply_material3(self)

        # Size to the content only after the Material chrome has been added, so
        # the height accounts for the title bar it prepends.
        self.SetSizerAndFit(self.GetSizer())
        width, height = self.GetSize()
        self.SetSize(wx.Size(max(width, tokens_scaled(680)), height))
        self.SetMinSize(self.GetSize())
        self.CentreOnParent()
        self.path.SetFocus()
        self.path.SetInsertionPointEnd()

    def _confirm(self, _event: wx.Event) -> None:
        """Accept the typed path, the way the OK button would."""
        if self.IsModal():
            self.EndModal(wx.ID_OK)
        else:
            self.SetReturnCode(wx.ID_OK)
            self.Show(False)

    def _browse(self, _event: wx.Event) -> None:
        if self._directory:
            with wx.DirDialog(
                self, _copy("choose_folder", self._language_mode)
            ) as dialog:
                if dialog.ShowModal() == wx.ID_OK:
                    self.path.SetValue(dialog.GetPath())
                    self.path.SetFocus()
            return
        style = wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT if self._save else wx.FD_OPEN
        if not self._save:
            style |= wx.FD_FILE_MUST_EXIST
        with wx.FileDialog(
            self,
            _copy("choose_path", self._language_mode),
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
