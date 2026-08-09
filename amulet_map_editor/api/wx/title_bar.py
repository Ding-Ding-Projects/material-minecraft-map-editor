"""Material-style title bar for the borderless desktop frame."""

from __future__ import annotations

import wx

from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.api.wx.components import MaterialWindowButton


class MaterialTitleBar(wx.Panel):
    """A keyboard-accessible title bar with real frame window actions."""

    def __init__(self, parent: wx.Window, title: str):
        super().__init__(parent, size=wx.Size(-1, 44))
        frame = (
            parent
            if isinstance(parent, wx.TopLevelWindow)
            else parent.GetTopLevelParent()
        )
        if not isinstance(frame, wx.TopLevelWindow):
            raise TypeError("MaterialTitleBar requires a top-level window parent")
        self._frame = frame
        self._drag_origin: wx.Point | None = None
        self.SetMinSize(wx.Size(-1, 44))
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.brand = wx.StaticText(self, label=title, name="Window title")
        self.brand.SetToolTip("Application title; drag this bar to move the window.")
        row.Add(self.brand, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 16)
        self.minimise = self._button("—", "Minimize window", self._minimise)
        self.maximise = self._button("□", "Maximize window", self._toggle_maximize)
        self.close = self._button("×", "Close window", self._close)
        for button in (self.minimise, self.maximise, self.close):
            row.Add(button, 0, wx.EXPAND | wx.LEFT, 4)
        row.AddSpacer(8)
        self.SetSizer(row)
        for control in (self, self.brand):
            control.Bind(wx.EVT_LEFT_DOWN, self._drag_start)
            control.Bind(wx.EVT_LEFT_UP, self._drag_end)
            control.Bind(wx.EVT_MOTION, self._drag_move)
            control.Bind(wx.EVT_LEFT_DCLICK, lambda _event: self._toggle_maximize())
        apply_material3(self)

    def _button(self, label: str, name: str, handler) -> MaterialWindowButton:
        action = {
            "—": "minimize",
            "□": "maximize",
            "×": "close",
        }[label]
        return MaterialWindowButton(self, action, name, handler)

    def set_title(self, title: str) -> None:
        self.brand.SetLabel(title)

    def _minimise(self, _event) -> None:
        self._frame.Iconize(True)

    def _toggle_maximize(self, _event=None) -> None:
        self._frame.Maximize(not self._frame.IsMaximized())

    def _close(self, _event) -> None:
        self._frame.Close()

    def _drag_start(self, event: wx.MouseEvent) -> None:
        self._drag_origin = event.GetPosition()
        self.CaptureMouse()
        event.Skip()

    def _drag_end(self, event: wx.MouseEvent) -> None:
        if self.HasCapture():
            self.ReleaseMouse()
        self._drag_origin = None
        event.Skip()

    def _drag_move(self, event: wx.MouseEvent) -> None:
        if self._drag_origin is None or not event.Dragging() or not event.LeftIsDown():
            event.Skip()
            return
        screen_point = self.ClientToScreen(event.GetPosition())
        origin_screen = self.ClientToScreen(self._drag_origin)
        frame_position = self._frame.GetPosition()
        self._frame.Move(
            frame_position.x + screen_point.x - origin_screen.x,
            frame_position.y + screen_point.y - origin_screen.y,
        )
        event.Skip()
