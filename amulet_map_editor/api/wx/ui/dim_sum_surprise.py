"""Native, focus-safe projection for the optional startup dim-sum payload.

The panel deliberately does not download an image.  It exposes the
authoritative alt text and public catalog asset path until a verified
application-data/public-release resolver is available.  It is embedded in the
main frame rather than shown as a modal dialog, never requests focus, and
auto-dismisses on the payload's bounded timeout.
"""

from __future__ import annotations

from typing import Callable, Optional

import wx

from amulet_map_editor.api.dim_sum_surprise import (
    DimSumSurprisePayload,
    notification_copy,
)
from amulet_map_editor.api.wx.material3 import apply_material3


class DimSumSurpriseToast(wx.Panel):
    """A small, non-modal startup surface that dismisses itself once."""

    def __init__(
        self,
        parent: wx.Window,
        payload: DimSumSurprisePayload,
        *,
        on_dismiss: Optional[Callable[["DimSumSurpriseToast"], None]] = None,
    ) -> None:
        super().__init__(parent, name="Dim-sum surprise")
        self.payload = payload
        self._on_dismiss = on_dismiss
        title, body = notification_copy(payload)

        root = wx.BoxSizer(wx.HORIZONTAL)
        copy = wx.BoxSizer(wx.VERTICAL)
        heading = wx.StaticText(self, label=title, name="Dim-sum surprise title")
        description = wx.StaticText(
            self,
            label=body,
            name="Dim-sum surprise image description",
        )
        description.Wrap(760)
        # Keep the same meaningful alt text available to accessibility tools;
        # the public asset path is shown without silently pretending it was
        # fetched or bundled locally.
        description.SetToolTip(payload.alt_text)
        copy.Add(heading, 0, wx.BOTTOM, 4)
        copy.Add(description, 0, wx.EXPAND)
        root.Add(copy, 1, wx.EXPAND | wx.ALL, 12)

        close = wx.Button(self, label="Dismiss", name="Dismiss dim-sum surprise")
        close.SetToolTip("Dismiss this non-blocking surprise")
        root.Add(close, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        self.SetSizer(root)
        close.Bind(wx.EVT_BUTTON, lambda _event: self.dismiss())
        apply_material3(self)

        timeout_ms = max(1, int(payload.auto_dismiss_seconds)) * 1000
        self._timer = wx.CallLater(timeout_ms, self.dismiss)

    def dismiss(self) -> None:
        """Hide and destroy exactly once, returning focus to the prior surface."""

        if getattr(self, "_dismissed", False):
            return
        self._dismissed = True
        timer = getattr(self, "_timer", None)
        if timer is not None and timer.IsRunning():
            timer.Stop()
        callback = self._on_dismiss
        if callback is not None:
            callback(self)
        else:
            self.Hide()
            self.Destroy()
