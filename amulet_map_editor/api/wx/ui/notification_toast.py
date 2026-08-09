"""Material 3 non-blocking notification toast for the desktop shell."""

from __future__ import annotations

import wx

from amulet_map_editor.api import notification_copy
from amulet_map_editor.api.wx.material3 import apply_material3


class NotificationToast(wx.Panel):
    """A bounded toast that never steals focus or blocks the active surface."""

    def __init__(
        self, parent: wx.Window, title: str, body: str, severity: str, on_dismiss
    ):
        super().__init__(parent, style=wx.NO_BORDER)
        self._on_dismiss = on_dismiss
        root = wx.BoxSizer(wx.HORIZONTAL)
        copy = wx.BoxSizer(wx.VERTICAL)
        heading = wx.StaticText(self, label=title)
        heading.SetName("Notification toast title")
        message = wx.StaticText(self, label=body)
        message.SetName("Notification toast message")
        message.Wrap(360)
        copy.Add(heading, 0, wx.BOTTOM, 2)
        copy.Add(message, 0, wx.EXPAND)
        root.Add(copy, 1, wx.EXPAND | wx.ALL, 12)
        close = wx.Button(
            self,
            label=notification_copy.notification_text("action.dismiss", styled=False),
        )
        close.SetName("Dismiss notification toast")
        close.Bind(wx.EVT_BUTTON, lambda _event: self.dismiss())
        root.Add(close, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(420, 64))
        self._timer = None
        if severity not in {"error", "warning"}:
            self._timer = wx.CallLater(6000, self.dismiss)
        apply_material3(self)

    def dismiss(self) -> None:
        if self._timer is not None and self._timer.IsRunning():
            self._timer.Stop()
        if self._on_dismiss is not None:
            callback, self._on_dismiss = self._on_dismiss, None
            callback(self)


__all__ = ["NotificationToast"]
