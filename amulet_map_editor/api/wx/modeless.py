"""Lifecycle helpers for user-invoked, non-decision reference surfaces."""

from __future__ import annotations

from typing import Callable

import wx


def show_modeless_dialog(
    owner: wx.Window,
    key: str,
    factory: Callable[[wx.Window], wx.Dialog],
) -> wx.Dialog:
    """Show one reusable modeless dialog without blocking the owning surface."""

    top = owner.GetTopLevelParent() or owner
    registry = getattr(top, "_modeless_reference_dialogs", None)
    if registry is None:
        registry = {}
        setattr(top, "_modeless_reference_dialogs", registry)
    existing = registry.get(key)
    if existing is not None and not existing.IsBeingDeleted():
        existing.Raise()
        existing.SetFocus()
        return existing

    dialog = factory(top)
    registry[key] = dialog

    def close_dialog(_event: wx.CloseEvent) -> None:
        registry.pop(key, None)
        dialog.Destroy()

    dialog.Bind(wx.EVT_CLOSE, close_dialog)
    # Reference dialogs created for modal use commonly bind their close button
    # to EndModal. Replace that binding when this helper owns the modeless
    # lifecycle so the same control remains safe in both presentations.
    close = dialog.FindWindow(wx.ID_CLOSE)
    if close is not None:
        close.Unbind(wx.EVT_BUTTON)
        close.Bind(wx.EVT_BUTTON, lambda _event: dialog.Close())
    dialog.CentreOnParent()
    dialog.Show()
    return dialog


def finish_dialog(dialog: wx.Dialog, return_code: int = wx.ID_CLOSE) -> None:
    """Close either a modal decision or a modeless reference safely."""

    if dialog.IsModal():
        dialog.EndModal(return_code)
    else:
        dialog.Close()


__all__ = ["finish_dialog", "show_modeless_dialog"]
