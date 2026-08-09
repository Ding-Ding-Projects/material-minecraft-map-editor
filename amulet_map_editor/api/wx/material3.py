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
from amulet_map_editor.api import preferences, school_mode


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


def _active_palette() -> dict[str, wx.Colour]:
    """Resolve persisted appearance values into the live native palette."""
    prefs = school_mode.presentation_preferences(preferences.load())
    if prefs.theme == "dark":
        palette = {
            "surface": wx.Colour(20, 18, 24),
            "surface_container": wx.Colour(33, 31, 38),
            "on_surface": wx.Colour(230, 225, 229),
            "primary_container": wx.Colour(74, 63, 99),
            "on_primary_container": wx.Colour(234, 221, 255),
        }
    else:
        palette = {
            "surface": wx.Colour(250, 251, 255),
            "surface_container": wx.Colour(239, 241, 248),
            "on_surface": wx.Colour(27, 28, 32),
            "primary_container": wx.Colour(214, 227, 255),
            "on_primary_container": wx.Colour(40, 71, 117),
        }
    palette["primary"] = TOKENS.primary
    try:
        accent = wx.Colour(prefs.accent)
        if accent.IsOk():
            palette["primary"] = accent
    except (TypeError, ValueError):
        pass
    return palette


def _font_for(
    window: wx.Window, point_size: int, weight=wx.FONTWEIGHT_NORMAL
) -> wx.Font:
    """Return a platform-safe UI font while retaining the system family."""

    base = (
        window.GetFont()
        if window and window.GetFont().IsOk()
        else wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
    )
    prefs = school_mode.presentation_preferences(preferences.load())
    font = wx.Font(base)
    # Appearance values are live tokens, not decorative storage: every
    # native control receives the persisted scale and optional family.
    font.SetPointSize(max(8, round(point_size * prefs.ui_scale)))
    if prefs.ui_font:
        font.SetFaceName(prefs.ui_font)
    font.SetWeight(weight)
    return font


def _control_min_height(window: wx.Window) -> int:
    """Resolve the touch target from the persisted M3 density choice."""

    prefs = school_mode.presentation_preferences(preferences.load())
    density = prefs.density
    target = {"compact": 36, "comfortable": 40, "spacious": 48}.get(
        density, 40
    )
    return max(target, window.GetBestSize().height)


def _children(window: wx.Window) -> Iterable[wx.Window]:
    # ``GetChildren`` returns a stable Python list; using it avoids relying on
    # the platform-specific sibling traversal methods exposed by wx wrappers.
    yield from window.GetChildren()


def _ensure_material_dialog_chrome(window: wx.Window) -> None:
    """Replace wx's caption with the shared M3 title bar once content exists."""

    if not isinstance(window, wx.Dialog) or getattr(
        window, "_material3_dialog_chrome", False
    ):
        return
    content = window.GetSizer()
    if content is None:
        # Dialog constructors often install their sizer after EVT_WINDOW_CREATE;
        # the next apply_material3 pass will retry without changing state.
        return
    from amulet_map_editor.api.wx.title_bar import MaterialTitleBar

    style = window.GetWindowStyleFlag()
    window.SetWindowStyleFlag(
        (style & ~wx.CAPTION & ~wx.SYSTEM_MENU & ~wx.MINIMIZE_BOX & ~wx.MAXIMIZE_BOX)
        | wx.NO_BORDER
        | wx.RESIZE_BORDER
    )
    title_bar = MaterialTitleBar(window, window.GetTitle() or "Amulet")
    outer = wx.BoxSizer(wx.VERTICAL)
    outer.Add(title_bar, 0, wx.EXPAND)
    outer.Add(content, 1, wx.EXPAND)
    wx.Dialog.SetSizer(window, outer)
    window._material3_dialog_chrome = True
    window.Layout()


def apply_material3(window: wx.Window) -> None:
    """Apply M3 roles to a window tree.

    The helper is intentionally idempotent and uses native wx controls.  A
    control can opt out by setting ``_material3_opt_out = True`` before this
    function is called (useful for OpenGL surfaces whose clear colour is
    managed by the renderer).
    """

    if getattr(window, "_material3_opt_out", False):
        return

    _ensure_material_dialog_chrome(window)

    palette = _active_palette()

    # wx.lib.agw.flatnotebook is a custom control rather than wx.Notebook;
    # apply its public tab-role setters explicitly so the world strip does not
    # retain the platform's legacy blue/grey palette.
    if hasattr(window, "SetTabAreaColour"):
        window.SetTabAreaColour(palette["surface_container"])
    if hasattr(window, "SetActiveTabColour"):
        window.SetActiveTabColour(palette["primary_container"])
    if hasattr(window, "SetNonActiveTabColour"):
        window.SetNonActiveTabColour(palette["surface"])
    if hasattr(window, "SetActiveTabTextColour"):
        window.SetActiveTabTextColour(palette["on_primary_container"])
    if hasattr(window, "SetNonActiveTabTextColour"):
        window.SetNonActiveTabTextColour(palette["on_surface_variant"])

    window.SetBackgroundColour(palette["surface"])
    window.SetForegroundColour(palette["on_surface"])
    if isinstance(window, wx.TopLevelWindow):
        window.SetFont(_font_for(window, 10))

    for child in _children(window):
        if getattr(child, "_material3_opt_out", False):
            continue
        child.SetForegroundColour(palette["on_surface"])
        # Keep canvases renderer-owned while styling ordinary surfaces.
        if isinstance(
            child,
            (
                wx.Panel,
                wx.ScrolledWindow,
                wx.Notebook,
                wx.ListBox,
                wx.ListCtrl,
                wx.TreeCtrl,
            ),
        ):
            child.SetBackgroundColour(palette["surface"])
        if isinstance(
            child,
            (
                wx.StaticText,
                wx.CheckBox,
                wx.RadioButton,
                wx.StaticBox,
                wx.Slider,
                wx.Gauge,
            ),
        ):
            child.SetFont(_font_for(child, 10))
            if isinstance(child, (wx.CheckBox, wx.RadioButton, wx.Slider)):
                child.SetMinSize(wx.Size(-1, _control_min_height(child)))
        elif isinstance(child, (wx.ListBox, wx.ListCtrl, wx.TreeCtrl)):
            child.SetFont(_font_for(child, 10))
            child.SetMinSize(wx.Size(-1, max(child.GetBestSize().height, 120)))
        elif isinstance(child, wx.Notebook):
            child.SetFont(_font_for(child, 10, wx.FONTWEIGHT_MEDIUM))
        elif isinstance(child, (wx.Button, wx.ToggleButton)):
            child.SetFont(_font_for(child, 10, wx.FONTWEIGHT_MEDIUM))
            child.SetBackgroundColour(palette["primary_container"])
            child.SetForegroundColour(palette["on_primary_container"])
            child.SetMinSize(wx.Size(max(child.GetBestSize().width, 88), _control_min_height(child)))
        elif isinstance(
            child, (wx.TextCtrl, wx.ComboBox, wx.Choice, wx.SpinCtrl, wx.SpinCtrlDouble)
        ):
            child.SetFont(_font_for(child, 10))
            child.SetBackgroundColour(palette["surface_container"])
            child.SetForegroundColour(palette["on_surface"])
            child.SetMinSize(wx.Size(-1, _control_min_height(child)))
        apply_material3(child)

    window.Layout()
