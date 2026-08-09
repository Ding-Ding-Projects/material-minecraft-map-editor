"""Small Material 3 foundation for the wxPython interface.

The editor predates a design-token system and has many independently-created
controls.  This module keeps the first step deliberately narrow: one palette,
typography scale, spacing tokens, and an idempotent application helper.  It
does not replace native controls or alter event behaviour, so it is safe to
roll out across existing pages incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import wx


@dataclass(frozen=True)
class Material3Tokens:
    """Material 3 light colour roles used by the desktop shell."""

    primary = wx.Colour(65, 95, 145)
    on_primary = wx.Colour(255, 255, 255)
    primary_container = wx.Colour(214, 227, 255)
    on_primary_container = wx.Colour(40, 71, 117)
    surface = wx.Colour(250, 251, 255)
    surface_container = wx.Colour(239, 241, 248)
    surface_container_high = wx.Colour(229, 231, 238)
    on_surface = wx.Colour(27, 28, 32)
    on_surface_variant = wx.Colour(68, 71, 78)
    outline = wx.Colour(116, 119, 127)
    error = wx.Colour(186, 26, 26)

    # M3 spacing and shape tokens, in device-independent pixels.
    space_xs = 4
    space_sm = 8
    space_md = 16
    space_lg = 24
    corner_medium = 12


TOKENS = Material3Tokens()


def _font_for(
    window: wx.Window, point_size: int, weight=wx.FONTWEIGHT_NORMAL
) -> wx.Font:
    """Return a platform-safe UI font while retaining the system family."""

    base = (
        window.GetFont()
        if window and window.GetFont().IsOk()
        else wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
    )
    font = wx.Font(base)
    font.SetPointSize(point_size)
    font.SetWeight(weight)
    return font


def _children(window: wx.Window) -> Iterable[wx.Window]:
    # ``GetChildren`` returns a stable Python list; using it avoids relying on
    # the platform-specific sibling traversal methods exposed by wx wrappers.
    yield from window.GetChildren()


def apply_material3(window: wx.Window) -> None:
    """Apply M3 roles to a window tree.

    The helper is intentionally idempotent and uses native wx controls.  A
    control can opt out by setting ``_material3_opt_out = True`` before this
    function is called (useful for OpenGL surfaces whose clear colour is
    managed by the renderer).
    """

    if getattr(window, "_material3_opt_out", False):
        return

    window.SetBackgroundColour(TOKENS.surface)
    window.SetForegroundColour(TOKENS.on_surface)
    if isinstance(window, wx.TopLevelWindow):
        window.SetFont(_font_for(window, 10))

    for child in _children(window):
        if getattr(child, "_material3_opt_out", False):
            continue
        child.SetForegroundColour(TOKENS.on_surface)
        # Keep canvases renderer-owned while styling ordinary surfaces.
        if isinstance(child, (wx.Panel, wx.ScrolledWindow, wx.Notebook)):
            child.SetBackgroundColour(TOKENS.surface)
        if isinstance(child, wx.StaticText):
            child.SetFont(_font_for(child, 10))
        elif isinstance(child, (wx.Button, wx.ToggleButton)):
            child.SetFont(_font_for(child, 10, wx.FONTWEIGHT_MEDIUM))
            child.SetBackgroundColour(TOKENS.primary_container)
            child.SetForegroundColour(TOKENS.on_primary_container)
            child.SetMinSize(
                wx.Size(
                    max(child.GetBestSize().width, 88),
                    max(child.GetBestSize().height, 40),
                )
            )
        elif isinstance(
            child, (wx.TextCtrl, wx.ComboBox, wx.Choice, wx.SpinCtrl, wx.SpinCtrlDouble)
        ):
            child.SetFont(_font_for(child, 10))
            child.SetMinSize(wx.Size(-1, max(child.GetBestSize().height, 40)))
        apply_material3(child)

    window.Layout()
