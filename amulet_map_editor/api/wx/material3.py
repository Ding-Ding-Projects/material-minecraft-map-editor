"""Material 3 token and native-control projection for the wxPython interface.

The application shell uses owner-drawn controls.  This module gives remaining
native editor pages the same semantic colours, typography, density, focus, and
surface roles while those pages are migrated incrementally.

A theme application pass resolves preferences exactly once.  The previous
recursive implementation reloaded preferences, scheduled settings, fonts, and
layout state for every descendant, which made large editor trees needlessly
expensive to open or restyle.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import re
from threading import RLock
from types import MappingProxyType
import weakref
from typing import Callable, Iterable, Mapping, TypeVar

import wx

from amulet_map_editor.api import preferences, school_mode, scheduled_runtime


@dataclass(frozen=True)
class Material3Tokens:
    """Stable Material 3 light roles plus desktop spacing and shape tokens."""

    primary = wx.Colour(65, 95, 145)
    on_primary = wx.Colour(255, 255, 255)
    primary_container = wx.Colour(214, 227, 255)
    on_primary_container = wx.Colour(40, 71, 117)
    secondary_container = wx.Colour(220, 226, 242)
    on_secondary_container = wx.Colour(39, 45, 58)
    surface = wx.Colour(250, 251, 255)
    surface_container_low = wx.Colour(245, 247, 253)
    surface_container = wx.Colour(239, 241, 248)
    surface_container_high = wx.Colour(229, 231, 238)
    on_surface = wx.Colour(27, 28, 32)
    on_surface_variant = wx.Colour(68, 71, 78)
    outline = wx.Colour(116, 119, 127)
    outline_variant = wx.Colour(196, 199, 207)
    error = wx.Colour(186, 26, 26)
    on_error = wx.Colour(255, 255, 255)

    # M3 spacing and shape tokens, in device-independent pixels.
    space_xs = 4
    space_sm = 8
    space_md = 16
    space_lg = 24
    corner_small = 8
    corner_medium = 12
    corner_large = 20


TOKENS = Material3Tokens()
_WindowFunc = TypeVar("_WindowFunc", bound=Callable[..., None])
_CACHE_LOCK = RLock()
_CACHED_CONTEXT: "MaterialThemeContext | None" = None


@dataclass(frozen=True)
class MaterialThemeContext:
    """Immutable values shared by one complete style traversal."""

    palette: Mapping[str, wx.Colour]
    theme: str
    density: str
    ui_scale: float
    ui_font: str
    element_overrides: Mapping[str, Mapping[str, object]]


class _FallbackPreferences:
    theme = "system"
    density = "comfortable"
    accent = "#415F91"
    ui_scale = 1.0
    ui_font = ""


_WRAPPED_OBJECT_DELETED = re.compile(
    r"^wrapped C/C\+\+ object(?: of type .+)? has been deleted$"
)


def _is_deleted_wrapped_object_error(error: RuntimeError) -> bool:
    """Return whether wx reported its canonical destroyed-wrapper error."""

    return bool(_WRAPPED_OBJECT_DELETED.fullmatch(str(error)))


def _is_window_being_deleted(window: wx.Window) -> bool:
    """Check a wx wrapper without hiding unrelated runtime failures."""

    try:
        return window.IsBeingDeleted()
    except RuntimeError as error:
        if _is_deleted_wrapped_object_error(error):
            return True
        raise


def _ignore_destroyed_window(function: _WindowFunc) -> _WindowFunc:
    """Ignore wx callbacks racing with a window being destroyed."""

    @wraps(function)
    def guarded(window: wx.Window, *args, **kwargs):
        try:
            if _is_window_being_deleted(window):
                return None
            return function(window, *args, **kwargs)
        except RuntimeError as error:
            if _is_deleted_wrapped_object_error(error):
                return None
            raise

    return guarded  # type: ignore[return-value]


def apply_material3_deferred(window: wx.Window) -> None:
    """Theme a newly-created window after construction without retaining it."""

    window_ref = weakref.ref(window)

    def apply_if_live() -> None:
        target = window_ref()
        if target is None or _is_window_being_deleted(target):
            return
        apply_material3(target)

    wx.CallAfter(apply_if_live)
    wx.CallLater(100, apply_if_live)


def _blend_colour(
    first: wx.Colour, second: wx.Colour, second_weight: float
) -> wx.Colour:
    """Blend two RGB roles while keeping the result inside the RGB gamut."""

    weight = min(1.0, max(0.0, float(second_weight)))
    return wx.Colour(
        round(first.Red() * (1 - weight) + second.Red() * weight),
        round(first.Green() * (1 - weight) + second.Green() * weight),
        round(first.Blue() * (1 - weight) + second.Blue() * weight),
    )


def _relative_luminance(colour: wx.Colour) -> float:
    channels: list[float] = []
    for value in (colour.Red(), colour.Green(), colour.Blue()):
        channel = value / 255.0
        channels.append(
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _on_colour(background: wx.Colour) -> wx.Colour:
    """Choose the black/white on-role with the stronger WCAG contrast ratio."""

    luminance = _relative_luminance(background)
    white_contrast = 1.05 / (luminance + 0.05)
    black_contrast = (luminance + 0.05) / 0.05
    return (
        wx.Colour(255, 255, 255)
        if white_contrast >= black_contrast
        else wx.Colour(0, 0, 0)
    )


def _system_uses_dark_theme() -> bool:
    """Resolve the OS appearance with a safe fallback for older wx builds."""

    try:
        appearance = wx.SystemSettings.GetAppearance()
        if hasattr(appearance, "IsDark"):
            return bool(appearance.IsDark())
    except (AttributeError, RuntimeError):
        pass

    # Older wxPython builds may not expose SystemAppearance.  Comparing the
    # native window and text roles still follows the host palette instead of
    # silently forcing a light surface for the persisted ``system`` setting.
    try:
        background = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        foreground = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        if background.IsOk() and foreground.IsOk():
            return _relative_luminance(background) < _relative_luminance(foreground)
    except (AttributeError, RuntimeError):
        pass
    return False


def _resolve_theme(value: object) -> str:
    requested = str(value or "system").strip().casefold()
    if requested == "system":
        return "dark" if _system_uses_dark_theme() else "light"
    return requested if requested in {"light", "dark"} else "light"


def invalidate_material3_cache() -> None:
    """Discard cached appearance values after preferences are saved."""

    global _CACHED_CONTEXT
    with _CACHE_LOCK:
        _CACHED_CONTEXT = None


def _coerce_scale(value: object) -> float:
    try:
        return min(2.0, max(0.75, float(value)))
    except (TypeError, ValueError):
        return 1.0


def _load_element_overrides() -> Mapping[str, Mapping[str, object]]:
    """Load and freeze bounded overrides once for the complete style pass."""

    try:
        module = __import__(
            "amulet_map_editor.api.wx.ui.element_appearance",
            fromlist=["load_overrides"],
        )
        overrides = module.load_overrides()
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return MappingProxyType({})
    if not isinstance(overrides, Mapping):
        return MappingProxyType({})
    frozen: dict[str, Mapping[str, object]] = {}
    for key, value in overrides.items():
        if isinstance(value, Mapping):
            frozen[str(key)] = MappingProxyType(dict(value))
    return MappingProxyType(frozen)


def _build_context() -> MaterialThemeContext:
    try:
        prefs = school_mode.presentation_preferences(preferences.load())
    except (OSError, TypeError, ValueError, AttributeError):
        prefs = _FallbackPreferences()
    try:
        runtime = scheduled_runtime.current_values()
    except (OSError, RuntimeError, TypeError, ValueError):
        runtime = {}
    if not isinstance(runtime, Mapping):
        runtime = {}

    theme = _resolve_theme(runtime.get("theme", prefs.theme))
    density = str(runtime.get("density", prefs.density)).casefold()
    if density not in {"compact", "comfortable", "spacious"}:
        density = "comfortable"
    accent_value = runtime.get("accent", prefs.accent)

    if theme == "dark":
        palette: dict[str, wx.Colour] = {
            "surface": wx.Colour(20, 18, 24),
            "surface_container_low": wx.Colour(29, 27, 33),
            "surface_container": wx.Colour(33, 31, 38),
            "surface_container_high": wx.Colour(43, 41, 48),
            "on_surface": wx.Colour(230, 225, 229),
            "on_surface_variant": wx.Colour(202, 196, 208),
            "primary_container": wx.Colour(74, 63, 99),
            "on_primary_container": wx.Colour(234, 221, 255),
            "secondary_container": wx.Colour(71, 67, 79),
            "on_secondary_container": wx.Colour(232, 222, 241),
            "outline": wx.Colour(147, 143, 153),
            "outline_variant": wx.Colour(73, 69, 79),
            "error": wx.Colour(255, 180, 171),
            "on_error": wx.Colour(105, 0, 5),
        }
    else:
        palette = {
            "surface": wx.Colour(250, 251, 255),
            "surface_container_low": wx.Colour(245, 247, 253),
            "surface_container": wx.Colour(239, 241, 248),
            "surface_container_high": wx.Colour(229, 231, 238),
            "on_surface": wx.Colour(27, 28, 32),
            "on_surface_variant": wx.Colour(68, 71, 78),
            "primary_container": wx.Colour(214, 227, 255),
            "on_primary_container": wx.Colour(40, 71, 117),
            "secondary_container": wx.Colour(220, 226, 242),
            "on_secondary_container": wx.Colour(39, 45, 58),
            "outline": wx.Colour(116, 119, 127),
            "outline_variant": wx.Colour(196, 199, 207),
            "error": wx.Colour(186, 26, 26),
            "on_error": wx.Colour(255, 255, 255),
        }

    palette["primary"] = TOKENS.primary
    try:
        accent = wx.Colour(accent_value)
        if accent.IsOk():
            palette["primary"] = accent
    except (OverflowError, RuntimeError, TypeError, ValueError):
        pass
    palette["on_primary"] = _on_colour(palette["primary"])
    palette["primary_container"] = _blend_colour(
        palette["primary"],
        palette["surface_container"],
        0.65 if theme == "dark" else 0.82,
    )
    palette["on_primary_container"] = _on_colour(palette["primary_container"])
    palette["secondary_container"] = _blend_colour(
        palette["primary"],
        palette["surface_container_high"],
        0.78 if theme == "dark" else 0.90,
    )
    palette["on_secondary_container"] = _on_colour(palette["secondary_container"])
    palette["disabled_container"] = _blend_colour(
        palette["surface_container"], palette["on_surface"], 0.08
    )
    palette["on_disabled"] = _blend_colour(
        palette["surface_container"], palette["on_surface"], 0.38
    )

    # Keep these accesses explicit: appearance preferences are live design
    # tokens, not decorative values stored only by the preferences dialog.
    ui_scale = _coerce_scale(prefs.ui_scale)
    ui_font = str(prefs.ui_font or "").strip()
    element_overrides = _load_element_overrides()
    return MaterialThemeContext(
        MappingProxyType(palette),
        theme,
        density,
        ui_scale,
        ui_font,
        element_overrides,
    )


def _theme_context(*, force: bool = False) -> MaterialThemeContext:
    global _CACHED_CONTEXT
    with _CACHE_LOCK:
        if not force and _CACHED_CONTEXT is not None:
            return _CACHED_CONTEXT
        context = _build_context()
        _CACHED_CONTEXT = context
        return context


def _active_palette() -> dict[str, wx.Colour]:
    """Resolve persisted appearance values into a cached native palette."""

    return dict(_theme_context().palette)


def _font_for(
    window: wx.Window,
    point_size: int,
    weight=wx.FONTWEIGHT_NORMAL,
    *,
    context: MaterialThemeContext | None = None,
) -> wx.Font:
    """Return a platform-safe UI font while retaining the system family."""

    active = context or _theme_context()
    base = (
        window.GetFont()
        if window and window.GetFont().IsOk()
        else wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
    )
    font = wx.Font(base)
    font.SetPointSize(max(8, round(point_size * active.ui_scale)))
    if active.ui_font:
        font.SetFaceName(active.ui_font)
    font.SetWeight(weight)
    return font


def _control_min_height(
    window: wx.Window | None = None,
    *,
    natural_height: int = 0,
    context: MaterialThemeContext | None = None,
) -> int:
    """Resolve the M3 target without recursing through custom best-size hooks.

    ``natural_height`` preserves the repository's public helper contract.  A
    native control may also be supplied for convenience; owner-drawn controls
    must pass their already-measured height instead of asking themselves for a
    best size from inside ``DoGetBestSize``.
    """

    active = context or _theme_context()
    target = {"compact": 36, "comfortable": 40, "spacious": 48}.get(
        active.density, 40
    )
    scaled_target = round(target * active.ui_scale)
    measured_height = max(0, int(natural_height))
    if window is not None:
        measured_height = max(measured_height, window.GetBestSize().height)
    return max(scaled_target, measured_height)


def _children(window: wx.Window) -> Iterable[wx.Window]:
    # GetChildren returns a stable Python list and avoids platform-specific
    # sibling traversal APIs exposed by some wx wrappers.
    yield from window.GetChildren()


def _open_element_appearance(control: wx.Window) -> None:
    module = __import__(
        "amulet_map_editor.api.wx.ui.element_appearance",
        fromlist=["open_element_appearance"],
    )
    module.open_element_appearance(control)


def _reset_element_appearance(control: wx.Window) -> None:
    module = __import__(
        "amulet_map_editor.api.wx.ui.element_appearance",
        fromlist=["reset_override", "element_key"],
    )
    module.reset_override(module.element_key(control))
    invalidate_material3_cache()
    apply_material3(control.GetTopLevelParent())


def _bind_element_appearance_menu(window: wx.Window) -> None:
    """Give native controls an accessible, owner-drawn M3 appearance menu."""

    if getattr(window, "_material3_appearance_menu_bound", False):
        return
    if isinstance(window, wx.TopLevelWindow) or getattr(
        window, "_material3_appearance_menu_disabled", False
    ):
        return

    def show_menu(event: wx.ContextMenuEvent, control: wx.Window = window) -> None:
        from amulet_map_editor.api.material_menu import MaterialMenuItem
        from amulet_map_editor.api.wx.components import MaterialMenu

        old_menu = getattr(control, "_material3_appearance_popup", None)
        if old_menu is not None:
            try:
                old_menu.Destroy()
            except RuntimeError:
                pass
        menu = MaterialMenu(
            control.GetTopLevelParent(),
            title="Appearance",
            items=(
                MaterialMenuItem(
                    "Edit appearance…",
                    lambda _event=None: _open_element_appearance(control),
                    section="Element",
                ),
                MaterialMenuItem(
                    "Reset element appearance",
                    lambda _event=None: _reset_element_appearance(control),
                    section="Element",
                ),
            ),
        )
        control._material3_appearance_popup = menu
        position = event.GetPosition()
        if position == wx.DefaultPosition:
            client = control.GetClientRect()
            position = control.ClientToScreen(wx.Point(0, client.height))
        menu.show_at(control, position)

    window.Bind(wx.EVT_CONTEXT_MENU, show_menu)
    window._material3_appearance_menu_bound = True


def _ensure_material_dialog_chrome(window: wx.Window) -> None:
    """Replace wx's caption with the shared M3 title bar once content exists."""

    if not isinstance(window, wx.Dialog) or getattr(
        window, "_material3_dialog_chrome", False
    ):
        return
    content = window.GetSizer()
    if content is None:
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
    # ``content`` was installed on the dialog before this conversion.  It is
    # now owned by ``outer``; deleting the dialog's old sizer here would destroy
    # that adopted child and leave ``outer`` holding a dangling pointer.
    wx.Dialog.SetSizer(window, outer, deleteOld=False)
    window._material3_dialog_chrome = True


def _ensure_material_frame_chrome(window: wx.Window) -> None:
    """Give secondary wx frames the same M3 title bar as the main shell."""

    if (
        not isinstance(window, wx.Frame)
        or hasattr(window, "_title_bar")
        or getattr(window, "_material3_frame_chrome", False)
    ):
        return
    content = window.GetSizer()
    if content is None:
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
    # ``content`` was installed on the frame before this conversion.  It is
    # now owned by ``outer``; deleting the frame's old sizer here would destroy
    # that adopted child and leave ``outer`` holding a dangling pointer.
    wx.Frame.SetSizer(window, outer, deleteOld=False)
    window._material3_frame_chrome = True


def _apply_flat_notebook_roles(
    child: wx.Window, palette: Mapping[str, wx.Colour]
) -> None:
    if hasattr(child, "SetTabAreaColour"):
        child.SetTabAreaColour(palette["surface_container"])
    if hasattr(child, "SetActiveTabColour"):
        child.SetActiveTabColour(palette["primary_container"])
    if hasattr(child, "SetNonActiveTabColour"):
        child.SetNonActiveTabColour(palette["surface"])
    if hasattr(child, "SetActiveTabTextColour"):
        child.SetActiveTabTextColour(palette["on_primary_container"])
    if hasattr(child, "SetNonActiveTabTextColour"):
        child.SetNonActiveTabTextColour(palette["on_surface_variant"])


def _heading_role(child: wx.Window) -> bool:
    try:
        name = child.GetName().casefold()
    except (AttributeError, RuntimeError):
        return False
    return any(marker in name for marker in ("title", "heading"))


def _style_control(child: wx.Window, context: MaterialThemeContext) -> None:
    palette = context.palette
    _apply_flat_notebook_roles(child, palette)
    child.SetForegroundColour(palette["on_surface"])

    surface_role = getattr(child, "_material3_surface_role", None)
    if surface_role is not None:
        child.SetBackgroundColour(palette.get(surface_role, palette["surface"]))
    elif isinstance(
        child,
        (
            wx.TopLevelWindow,
            wx.Panel,
            wx.ScrolledWindow,
            wx.Notebook,
            wx.ListBox,
            wx.ListCtrl,
            wx.TreeCtrl,
            wx.CollapsiblePane,
        ),
    ):
        child.SetBackgroundColour(palette["surface"])
    elif child.GetParent() is not None:
        child.SetBackgroundColour(child.GetParent().GetBackgroundColour())

    if isinstance(child, wx.StaticLine):
        child.SetForegroundColour(palette["outline"])
    if isinstance(
        child,
        (
            wx.StaticText,
            wx.CheckBox,
            wx.RadioButton,
            wx.RadioBox,
            wx.StaticBox,
            wx.Slider,
            wx.Gauge,
            wx.CollapsiblePane,
        ),
    ):
        heading = _heading_role(child)
        child.SetFont(
            _font_for(
                child,
                14 if heading else 10,
                wx.FONTWEIGHT_MEDIUM if heading else wx.FONTWEIGHT_NORMAL,
                context=context,
            )
        )
        if isinstance(
            child,
            (
                wx.CheckBox,
                wx.RadioButton,
                wx.RadioBox,
                wx.Slider,
                wx.CollapsiblePane,
            ),
        ):
            # Public compatibility form retained for third-party callers:
            # _control_min_height(child)
            child.SetMinSize(
                wx.Size(-1, _control_min_height(child, context=context))
            )
        elif isinstance(child, wx.StaticText) and child.GetParent() is not None:
            child.SetBackgroundColour(child.GetParent().GetBackgroundColour())
    elif isinstance(child, (wx.ListBox, wx.ListCtrl, wx.TreeCtrl)):
        child.SetFont(_font_for(child, 10, context=context))
        child.SetMinSize(wx.Size(-1, max(child.GetBestSize().height, 120)))
    elif isinstance(child, wx.Notebook):
        child.SetFont(_font_for(child, 10, wx.FONTWEIGHT_MEDIUM, context=context))
    elif isinstance(child, (wx.Button, wx.ToggleButton)):
        child.SetFont(_font_for(child, 10, wx.FONTWEIGHT_MEDIUM, context=context))
        child.SetBackgroundColour(palette["primary_container"])
        child.SetForegroundColour(palette["on_primary_container"])
        child.SetMinSize(
            wx.Size(
                max(child.GetBestSize().width, 88),
                _control_min_height(child, context=context),
            )
        )
    elif isinstance(
        child,
        (
            wx.TextCtrl,
            wx.SearchCtrl,
            wx.ComboBox,
            wx.Choice,
            wx.SpinCtrl,
            wx.SpinCtrlDouble,
        ),
    ):
        child.SetFont(_font_for(child, 10, context=context))
        child.SetBackgroundColour(palette["surface_container"])
        child.SetForegroundColour(palette["on_surface"])
        child.SetMinSize(
            wx.Size(-1, _control_min_height(child, context=context))
        )


def _bind_system_colour_refresh(window: wx.Window) -> None:
    """Restyle live top-level surfaces when the host appearance changes."""

    if not isinstance(window, wx.TopLevelWindow) or getattr(
        window, "_material3_system_colour_bound", False
    ):
        return
    window_ref = weakref.ref(window)

    def refresh(event: wx.SysColourChangedEvent) -> None:
        invalidate_material3_cache()
        target = window_ref()
        if target is not None and not _is_window_being_deleted(target):
            wx.CallAfter(apply_material3, target)
        event.Skip()

    window.Bind(wx.EVT_SYS_COLOUR_CHANGED, refresh)
    window._material3_system_colour_bound = True


def _apply_element_override(
    window: wx.Window, overrides: Mapping[str, Mapping[str, object]]
) -> None:
    """Apply a preloaded override without rereading config for every control."""

    if not overrides:
        return
    try:
        module = __import__(
            "amulet_map_editor.api.wx.ui.element_appearance",
            fromlist=["element_key"],
        )
        override = overrides.get(module.element_key(window))
    except (ImportError, RuntimeError, TypeError, ValueError):
        return
    if not isinstance(override, Mapping):
        return

    for field, setter in (
        ("background", window.SetBackgroundColour),
        ("foreground", window.SetForegroundColour),
    ):
        value = override.get(field)
        if value:
            try:
                setter(wx.Colour(str(value)))
            except (RuntimeError, TypeError, ValueError):
                pass

    try:
        size = int(override.get("font_size", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        size = 0
    if not size:
        return
    font = wx.Font(window.GetFont())
    font.SetPointSize(max(1, min(72, size)))
    font.SetWeight(
        {
            "normal": wx.FONTWEIGHT_NORMAL,
            "medium": wx.FONTWEIGHT_MEDIUM,
            "bold": wx.FONTWEIGHT_BOLD,
        }.get(str(override.get("weight", "normal")), wx.FONTWEIGHT_NORMAL)
    )
    font.SetStyle(
        wx.FONTSTYLE_ITALIC
        if bool(override.get("italic", False))
        else wx.FONTSTYLE_NORMAL
    )
    font.SetUnderlined(bool(override.get("underline", False)))
    if hasattr(font, "SetStrikethrough"):
        font.SetStrikethrough(bool(override.get("strikethrough", False)))
    window.SetFont(font)


@_ignore_destroyed_window
def apply_material3(window: wx.Window) -> None:
    """Apply M3 roles to a window tree in one non-recursive traversal.

    A control can opt out by setting ``_material3_opt_out = True`` before this
    function is called.  Opted-out subtrees are not traversed, which keeps
    renderer-owned OpenGL surfaces untouched.
    """

    if getattr(window, "_material3_opt_out", False):
        return
    # Resolve first so any title-bar controls created below reuse this exact
    # pass context instead of causing an extra preferences/config read.
    context = _theme_context(force=True)
    _bind_system_colour_refresh(window)
    _ensure_material_dialog_chrome(window)
    _ensure_material_frame_chrome(window)

    stack: list[wx.Window] = [window]
    while stack:
        child = stack.pop()
        if getattr(child, "_material3_opt_out", False):
            continue
        _style_control(child, context)
        _bind_element_appearance_menu(child)
        _apply_element_override(child, context.element_overrides)
        descendants = list(_children(child))
        stack.extend(reversed(descendants))

    # Layout once at the traversal root.  Descendant Layout calls caused the
    # old implementation to repeatedly recalculate the same large editor tree.
    window.Layout()
    window.Refresh(False)


__all__ = [
    "Material3Tokens",
    "MaterialThemeContext",
    "TOKENS",
    "apply_material3",
    "apply_material3_deferred",
    "invalidate_material3_cache",
]
