"""The workspace status bar: live state, revision, selection, camera, and view.

The design draws this strip as a row of small readouts, but every one of them
reports something the workspace actually knows and two of them change it: the
revision pill opens the project history, the speed slider moves the camera, and
the segmented control switches the projection.  Nothing here is painted
decoration -- a control that looks operable and is not is the defect this shell
exists to remove, and a status bar is exactly where that defect hides best.

The bar keeps a fixed height, so every string it shows is collapsed onto one
line: bilingual copy arrives as two lines and would otherwise be cut in half.
The full text stays reachable through each control's tooltip and accessible
name.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.copy import studio_text
from amulet_map_editor.api.studio.widgets import (
    Divider,
    StudioButton,
    elide,
    invoke,
    paint_context,
    point_size,
)

log = logging.getLogger(__name__)

#: The design's status bar height, in design pixels.
BAR_HEIGHT = 34

#: The camera speed slider's bounds and shipped value, in blocks per second.
MIN_CAMERA_SPEED = 1
MAX_CAMERA_SPEED = 60
DEFAULT_CAMERA_SPEED = 12

#: The two projections the segmented control switches between.
PROJECTIONS: Tuple[Tuple[str, str], ...] = (("3d", "3D"), ("top", "Top"))

#: The status dot's ink per tone.  A tone never rewrites the message: it only
#: says how loudly to draw the dot beside it.
_TONES: Tuple[str, ...] = ("ready", "busy", "warning", "error")

_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL)


def single_line(text: str) -> str:
    """Collapse a possibly bilingual string onto one line for a fixed-height bar.

    Bilingual mode returns an English line above a Cantonese one.  A 34px bar
    cannot show two lines, and silently painting only the first would hide half
    the copy from a bilingual reader, so both are joined with the separator the
    design already uses between facts.
    """
    parts = [part.strip() for part in str(text).splitlines() if part.strip()]
    return " · ".join(parts)


def open_studio_menu(
    window: wx.Window,
    key: str,
    position: wx.Point,
    on_surface: Optional[Callable[[str], None]],
    on_command: Optional[Callable[[str], None]],
) -> None:
    """Open one of the shared searchable context menus over ``window``.

    The menus live in a module another part of the shell owns and construct a
    popup window, so the import is deferred: importing it here would make this
    module need a display before it could even be read.
    """
    try:
        from amulet_map_editor.api.studio import context_menu
    except ImportError:
        log.debug("The shared Studio context menus are not available")
        return
    try:
        context_menu.open_context_menu(
            window, key, position, on_surface=on_surface, on_command=on_command
        )
    except Exception:
        log.exception("Could not open the %r context menu", key)


def clear_container(
    sizer: wx.Sizer, panel: wx.Window, keep: Sequence[wx.Window] = ()
) -> None:
    """Empty a rebuilt list without destroying a window in mid-event.

    Every list in the workspace is rebuilt from inside the click of one of its
    own rows, and destroying a window while it is still handling an event is
    how wx tears the ground out from under itself.  The old rows are detached
    from the layout now and destroyed once the handler has returned, so the
    rebuilt list is correct immediately and nothing is deleted too early.
    """
    sizer.Clear(delete_windows=False)
    for child in list(panel.GetChildren()):
        if any(child is protected for protected in keep):
            continue
        try:
            if child.IsBeingDeleted():
                continue
            child.Hide()
            destroy_later = getattr(child, "DestroyLater", None)
            if callable(destroy_later):
                destroy_later()
            else:  # pragma: no cover - wxPython older than 4.0.4
                wx.CallAfter(child.Destroy)
        except RuntimeError:
            # The window has already gone; there is nothing left to tidy.
            continue


class BarLabel(wx.Control):
    """One read-only line of bar text, in the interface or monospaced face.

    It is a control rather than a ``wx.StaticText`` because the bar's ink comes
    from the live palette and the text has to elide rather than clip when the
    window narrows; both are painted here so a theme change or a resize leaves
    the row readable instead of truncated mid-character.
    """

    def __init__(
        self,
        parent: wx.Window,
        text: str = "",
        *,
        mono: bool = False,
        name: str = "",
        size_px: int = 12,
        emphasis: bool = False,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self._text = ""
        self._mono = bool(mono)
        self._size_px = int(size_px)
        self._label = str(name)
        self._emphasis = bool(emphasis)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.set_text(text)

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def _font(self) -> wx.Font:
        weight = _MEDIUM if self._emphasis else wx.FONTWEIGHT_NORMAL
        if self._mono:
            return tokens.mono_font(self, point_size(self._size_px), weight)
        return tokens.font(self, point_size(self._size_px), weight)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(self._font())
        width, height = dc.GetTextExtent(self._text or " ")
        return wx.Size(width + tokens.scaled(2), max(height, tokens.scaled(16)))

    def text(self) -> str:
        """Return the string currently shown."""
        return self._text

    def set_text(self, text: str) -> None:
        """Replace the text, its accessible name, and the space it asks for."""
        self._text = single_line(text)
        self.SetName(self._label or self._text or "Status")
        if self._text:
            self.SetToolTip(self._text)
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def refresh_theme(self) -> None:
        """Re-measure for the current density and repaint in the live palette."""
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        gcdc.SetFont(self._font())
        gcdc.SetTextForeground(
            palette.on_surface if self._emphasis else palette.on_surface_variant
        )
        gcdc.DrawText(
            elide(gcdc, self._text, width), 0, (height - gcdc.GetCharHeight()) // 2
        )
        del gcdc


class StatusReadout(wx.Control):
    """The tone dot and the status message it belongs to, drawn as one line."""

    DOT = 7

    def __init__(self, parent: wx.Window, text: str, *, tone: str = "ready") -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self._text = single_line(text)
        self._tone = tone if tone in _TONES else "ready"
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self._announce()
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def _announce(self) -> None:
        self.SetName(f"Status, {self._tone}: {self._text}")
        self.SetToolTip(self._text)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, point_size(12)))
        width, height = dc.GetTextExtent(self._text or " ")
        return wx.Size(
            width + tokens.scaled(self.DOT) + tokens.scaled(8),
            max(height, tokens.scaled(16)),
        )

    def set_status(self, text: str, tone: str = "ready") -> None:
        """Replace the message and the tone of the dot beside it."""
        self._text = single_line(text)
        self._tone = tone if tone in _TONES else "ready"
        self._announce()
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def text(self) -> str:
        """Return the message currently shown."""
        return self._text

    def tone(self) -> str:
        """Return the current tone name."""
        return self._tone

    def refresh_theme(self) -> None:
        """Re-measure and repaint against the live palette."""
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _dot_colour(self, palette: tokens.StudioPalette) -> wx.Colour:
        if self._tone == "error":
            return palette.error
        if self._tone == "warning":
            return tokens.blend(palette.error, palette.primary, 0.35)
        if self._tone == "busy":
            return tokens.blend(palette.primary, palette.on_surface, 0.20)
        return palette.primary

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        dot = tokens.scaled(self.DOT)
        gcdc.SetBrush(wx.Brush(self._dot_colour(palette)))
        gcdc.SetPen(wx.TRANSPARENT_PEN)
        gcdc.DrawEllipse(0, (height - dot) // 2, dot, dot)
        left = dot + tokens.scaled(8)
        gcdc.SetFont(tokens.font(self, point_size(12)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        gcdc.DrawText(
            elide(gcdc, self._text, max(0, width - left)),
            left,
            (height - gcdc.GetCharHeight()) // 2,
        )
        del gcdc


class RevisionPill(StudioButton):
    """The tinted monospaced button that names the head revision.

    Both the breadcrumb bar and the status bar show the same fact, so they show
    it through the same control: one place decides how a revision reads, and
    clicking either one lands on the same project history.
    """

    def __init__(
        self,
        parent: wx.Window,
        commit: str,
        count: int,
        *,
        glyph: str = "⟲",
        suffix: str = "",
        on_click: Optional[Callable[[], None]] = None,
        height: int = 24,
    ) -> None:
        self.commit = str(commit)
        self.count = int(count)
        self.suffix = str(suffix)
        super().__init__(
            parent,
            self._compose(),
            variant="pill",
            glyph=glyph,
            hint="Project history · unlimited undo",
            on_click=on_click,
            height=height,
        )
        # The identifier is a hash, and a hash is unreadable in a proportional
        # face; the shared button paints its label monospaced when asked.  The
        # label is set again afterwards so the button is measured in the face
        # it will actually be drawn in.
        self._mono = True
        self.SetLabel(self._compose())
        self._rename()

    def _compose(self) -> str:
        label = f"{self.commit} · {self.count}"
        return f"{label} {self.suffix}".rstrip() if self.suffix else label

    def _rename(self) -> None:
        plural = "revision" if self.count == 1 else "revisions"
        self.SetName(
            f"Head revision {self.commit}, {self.count} {plural}. "
            "Opens the project history."
        )

    def set_revision(self, commit: str, count: int) -> None:
        """Show a new head revision and revision count."""
        self.commit = str(commit)
        self.count = int(count)
        self.SetLabel(self._compose())
        self._rename()

    def _state_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour, Optional[wx.Colour]]:
        if not self.IsEnabled():
            return (
                palette.surface_container,
                tokens.blend(palette.on_surface_variant, palette.surface, 0.45),
                None,
            )
        fill = palette.tint
        if self._pressed:
            fill = tokens.blend(palette.surface_container_high, palette.primary, 0.16)
        elif self._hovered:
            fill = palette.surface_container_high
        return fill, palette.on_primary_container, None


class _Segment(StudioButton):
    """One half of a segmented control, filled while it is the chosen one."""

    def __init__(
        self,
        parent: wx.Window,
        key: str,
        label: str,
        *,
        selected: bool,
        on_click: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.key = str(key)
        self.selected = bool(selected)
        self._on_select = on_click
        super().__init__(
            parent,
            label,
            variant="pill",
            on_click=self._choose,
            height=20,
            hint=f"Show the {label} view",
        )
        self._sync_name()

    def _choose(self) -> None:
        invoke(self._on_select, self.key)

    def _sync_name(self) -> None:
        state = "selected" if self.selected else "not selected"
        self.SetName(f"{self.GetLabel()} view, {state}")

    def set_selected(self, selected: bool) -> None:
        """Set the chosen state without running the callback."""
        self.selected = bool(selected)
        self._sync_name()
        self.Refresh()

    def _state_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour, Optional[wx.Colour]]:
        if self.selected:
            fill = palette.primary
            if self._pressed:
                fill = tokens.blend(fill, palette.on_primary, 0.18)
            elif self._hovered:
                fill = tokens.blend(fill, palette.on_primary, 0.10)
            return fill, palette.on_primary, None
        fill: Optional[wx.Colour] = None
        if self._pressed:
            fill = tokens.blend(
                palette.surface_container_high, palette.on_surface, 0.12
            )
        elif self._hovered:
            fill = tokens.blend(
                palette.surface_container_high, palette.on_surface, 0.06
            )
        return fill, palette.on_surface_variant, None


class SegmentedToggle(wx.Panel):
    """A rounded track holding one button per option, one of them chosen."""

    def __init__(
        self,
        parent: wx.Window,
        options: Sequence[Tuple[str, str]],
        value: str,
        *,
        on_change: Optional[Callable[[str], None]] = None,
        name: str = "View",
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_change = on_change
        self.value = str(value)
        self.SetName(name)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.segments: Dict[str, _Segment] = {}
        row = wx.BoxSizer(wx.HORIZONTAL)
        pad = tokens.scaled(2)
        for key, label in options:
            segment = _Segment(
                self, key, label, selected=key == self.value, on_click=self._choose
            )
            self.segments[key] = segment
            row.Add(segment, 0, wx.ALL, pad)
        self.SetSizer(row)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Fit()

    def _choose(self, key: str) -> None:
        self.set_value(key, notify=True)

    def set_value(self, key: str, *, notify: bool = False) -> None:
        """Choose an option, optionally reporting the change to the owner."""
        if key not in self.segments:
            return
        self.value = key
        for name, segment in self.segments.items():
            segment.set_selected(name == key)
        if notify:
            invoke(self.on_change, key)

    def refresh_theme(self) -> None:
        """Repaint the track and every segment on it."""
        for segment in self.segments.values():
            segment.refresh_theme()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.RADIUS_PILL,
            palette.surface_container_high,
        )
        del gcdc


class StatusBar(wx.Panel):
    """The 34px strip under the viewport, wired to the workspace it describes.

    Every readout is fed by the owner through a setter and every control
    reports back through a callback, so the bar never holds a second copy of
    the truth: it shows what the workspace told it and asks the workspace to
    change what the user changed.
    """

    HEIGHT = BAR_HEIGHT

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_history: Optional[Callable[[], None]] = None,
        on_speed: Optional[Callable[[int], None]] = None,
        on_projection: Optional[Callable[[str], None]] = None,
        on_surface: Optional[Callable[[str], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
        status: str = "",
        commit: str = "a91f0c7",
        revisions: int = 6,
        selection: str = "dx=15, dy=1, dz=17 · 16x2x18",
        dimension: str = "minecraft:overworld",
        speed: int = DEFAULT_CAMERA_SPEED,
        projection: str = "3d",
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_history = on_history
        self.on_speed = on_speed
        self.on_projection = on_projection
        self.on_surface = on_surface
        self.on_command = on_command
        self.SetName("Workspace status bar")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        self.readout = StatusReadout(
            self, status or studio_text("Ready", "準備好"), tone="ready"
        )
        self.revision = RevisionPill(
            self, commit, revisions, on_click=self._open_history
        )
        self.selection = BarLabel(
            self,
            selection,
            mono=True,
            name="Selection size",
        )
        self.dimension = BarLabel(self, dimension, name="Active dimension")
        self.speed_caption = BarLabel(self, studio_text("Speed"), name="Camera speed")
        self.speed_slider = wx.Slider(
            self,
            value=self._clamp_speed(speed),
            minValue=MIN_CAMERA_SPEED,
            maxValue=MAX_CAMERA_SPEED,
            style=wx.SL_HORIZONTAL,
        )
        self.speed_slider.SetName("Camera speed in blocks per second")
        self.speed_slider.SetToolTip(
            single_line(
                studio_text(
                    "How fast the camera flies, in blocks per second.",
                    "鏡頭飛得幾快，每秒幾多格。",
                )
            )
        )
        self.speed_slider.SetMinSize(wx.Size(tokens.scaled(96), -1))
        self.speed_slider.Bind(wx.EVT_SLIDER, self._on_speed)
        self.speed_value = BarLabel(
            self,
            f"{self._clamp_speed(speed)} b/s",
            mono=True,
            name="Camera speed readout",
        )
        self.projection_toggle = SegmentedToggle(
            self,
            PROJECTIONS,
            projection if projection in dict(PROJECTIONS) else "3d",
            on_change=self._on_projection,
            name="Viewport projection",
        )
        self._rules = [Divider(self, vertical=True) for _ in range(3)]

        gap = tokens.scaled(tokens.SPACE_SM + 4)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.readout, 0, wx.ALIGN_CENTER_VERTICAL)
        row.Add(self.revision, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        row.AddStretchSpacer(1)
        row.Add(self.selection, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        row.Add(self._rules[0], 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        row.Add(self.dimension, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        row.Add(self._rules[1], 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        row.Add(self.speed_caption, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        row.Add(
            self.speed_slider,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_SM),
        )
        row.Add(
            self.speed_value,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_SM),
        )
        row.Add(self._rules[2], 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        row.Add(self.projection_toggle, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        frame = wx.BoxSizer(wx.HORIZONTAL)
        frame.Add(row, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, tokens.scaled(12))
        self.SetSizer(frame)
        self.SetMinSize(wx.Size(-1, tokens.scaled(self.HEIGHT)))

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self._apply_theme()

    # -- state ---------------------------------------------------------------
    @staticmethod
    def _clamp_speed(value: int) -> int:
        try:
            number = int(round(float(value)))
        except (TypeError, ValueError):
            return DEFAULT_CAMERA_SPEED
        return max(MIN_CAMERA_SPEED, min(MAX_CAMERA_SPEED, number))

    def set_status_text(self, text: str, tone: str = "ready") -> None:
        """Replace the message and dot beside it, then re-lay the row out."""
        self.readout.set_status(text, tone)
        self.Layout()

    def status_text(self) -> str:
        """Return the message currently shown."""
        return self.readout.text()

    def set_revision(self, commit: str, count: int) -> None:
        """Show a new head revision on the pill."""
        self.revision.set_revision(commit, count)
        self.Layout()

    def set_selection(self, text: str) -> None:
        """Show the selection delta and size, monospaced."""
        self.selection.set_text(text)
        self.Layout()

    def set_dimension(self, text: str) -> None:
        """Show which dimension the workspace is editing."""
        self.dimension.set_text(text)
        self.Layout()

    def speed(self) -> int:
        """Return the camera speed in blocks per second."""
        return int(self.speed_slider.GetValue())

    def set_speed(self, value: int, *, notify: bool = False) -> None:
        """Move the speed slider and its readout together."""
        clamped = self._clamp_speed(value)
        self.speed_slider.SetValue(clamped)
        self.speed_value.set_text(f"{clamped} b/s")
        self.Layout()
        if notify:
            invoke(self.on_speed, clamped)

    def projection(self) -> str:
        """Return the chosen projection key: ``3d`` or ``top``."""
        return self.projection_toggle.value

    def set_projection(self, key: str, *, notify: bool = False) -> None:
        """Choose a projection, optionally reporting it to the owner."""
        self.projection_toggle.set_value(key, notify=notify)

    # -- events --------------------------------------------------------------
    def _open_history(self) -> None:
        if self.on_history is not None:
            invoke(self.on_history)
        else:
            invoke(self.on_surface, "history")

    def _on_speed(self, _event: wx.CommandEvent) -> None:
        value = self.speed()
        self.speed_value.set_text(f"{value} b/s")
        self.Layout()
        invoke(self.on_speed, value)

    def _on_projection(self, key: str) -> None:
        invoke(self.on_projection, key)

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        position = event.GetPosition()
        if position == wx.DefaultPosition:
            size = self.GetSize()
            position = self.ClientToScreen(wx.Point(size.width // 2, size.height // 2))
        open_studio_menu(self, "statusbar", position, self.on_surface, self.on_command)

    # -- appearance ----------------------------------------------------------
    def _apply_theme(self) -> None:
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface_container)
        self.speed_slider.SetBackgroundColour(palette.surface_container)
        self.speed_slider.SetForegroundColour(palette.primary)

    def refresh_theme(self) -> None:
        """Re-read the palette for the bar and everything sitting on it."""
        self._apply_theme()
        for child in self.GetChildren():
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        self.Layout()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = paint_context(self, palette.surface_container)
        width, _height = self.GetClientSize()
        gcdc.SetPen(wx.Pen(palette.outline_variant))
        gcdc.DrawLine(0, 0, width, 0)
        del gcdc


__all__ = [
    "BAR_HEIGHT",
    "BarLabel",
    "DEFAULT_CAMERA_SPEED",
    "MAX_CAMERA_SPEED",
    "MIN_CAMERA_SPEED",
    "PROJECTIONS",
    "RevisionPill",
    "SegmentedToggle",
    "StatusBar",
    "StatusReadout",
    "clear_container",
    "open_studio_menu",
    "single_line",
]
