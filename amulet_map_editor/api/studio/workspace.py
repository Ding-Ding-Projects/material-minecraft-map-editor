"""The Amulet Studio workspace: ribbon, breadcrumb, navigator, view, and panes.

This is the surface a project is actually edited on.  It owns the state the
five panels each show a slice of -- which dimension, which selection boxes,
which revision is at the head -- so the breadcrumb bar, the navigator, the
viewport, the status bar, and the properties pane can never disagree with each
other about the same fact.

The panes are resizable from both the mouse and the keyboard, and each width is
remembered per surface, because a person who widened the navigator once should
not have to widen it again every session.  A reset path is always one key or
one double-click away, so a pane dragged somewhere unhelpful is never stuck
there.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api import config, local_history
from amulet_map_editor.api.studio import navigator as navigator_module
from amulet_map_editor.api.studio import properties_pane as properties_module
from amulet_map_editor.api.studio import status_bar as status_module
from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.copy import studio_label, studio_text
from amulet_map_editor.api.studio.navigator import (
    DEFAULT_BOXES,
    DEFAULT_DIMENSIONS,
    NavigatorPanel,
    SelectionBox,
)
from amulet_map_editor.api.studio.properties_pane import (
    DEFAULT_REVISIONS,
    ProjectRevision,
    PropertiesPane,
    PropertySection,
)
from amulet_map_editor.api.studio.ribbon import RibbonBar
from amulet_map_editor.api.studio.status_bar import (
    RevisionPill,
    StatusBar,
    clear_container,
    open_studio_menu,
    single_line,
)
from amulet_map_editor.api.studio.viewport import ViewportHost
from amulet_map_editor.api.studio.widgets import (
    StudioButton,
    elide,
    invoke,
    paint_context,
    point_size,
)

log = logging.getLogger(__name__)

#: Config record holding one width per resizable pane, keyed by surface.  Pane
#: geometry is per-surface furniture rather than a shipped preference, so it
#: lives in its own bounded record instead of growing the preferences schema.
PANE_WIDTHS_ID = "amulet_studio_pane_widths"

#: The design's breadcrumb bar height, in design pixels.
BREADCRUMB_HEIGHT = 34

#: The narrowest the world view may become while a pane is being dragged.  Past
#: this the viewport stops being a view of anything.
MIN_VIEWPORT_WIDTH = 320

#: How far one arrow key press moves a pane divider, and how far it moves while
#: Shift is held.
SASH_STEP = 8
SASH_LARGE_STEP = 32

#: How wide a pane is allowed to become, whatever the window can spare.
MAX_PANE_WIDTH = 640


def load_pane_widths() -> Dict[str, int]:
    """Return every remembered pane width, keyed ``<surface>.<pane>``."""
    raw = config.get(PANE_WIDTHS_ID, {})
    if not isinstance(raw, dict):
        return {}
    widths: Dict[str, int] = {}
    for key, value in raw.items():
        try:
            widths[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return widths


def store_pane_width(surface: str, pane: str, width: int) -> None:
    """Remember one pane's width, ignoring a profile that cannot be written."""
    try:
        widths = load_pane_widths()
        widths[f"{surface}.{pane}"] = int(width)
        config.put(PANE_WIDTHS_ID, widths)
    except OSError:
        log.exception("Could not store the %s pane width", pane)


def clear_pane_widths(surface: str) -> None:
    """Forget every remembered width for one surface."""
    try:
        widths = load_pane_widths()
        prefix = f"{surface}."
        remaining = {
            key: value for key, value in widths.items() if not key.startswith(prefix)
        }
        config.put(PANE_WIDTHS_ID, remaining)
    except OSError:
        log.exception("Could not reset the pane widths for %r", surface)


def selection_volume(boxes: Sequence[SelectionBox]) -> int:
    """Return how many distinct blocks a group of selection boxes covers.

    Selection boxes are allowed to overlap, so adding their volumes together
    would count the shared blocks twice and report a selection larger than the
    one the user made.  The boxes are swept instead: the distinct coordinates
    on each axis cut the space into cells, and each cell is counted once if any
    box contains it.
    """
    if not boxes:
        return 0
    bounds = [
        (
            box.minimum,
            tuple(
                low + max(0, int(extent)) for low, extent in zip(box.minimum, box.size)
            ),
        )
        for box in boxes
    ]
    axes = [
        sorted({edge[axis] for pair in bounds for edge in pair}) for axis in range(3)
    ]
    total = 0
    for x_index in range(len(axes[0]) - 1):
        x_low, x_high = axes[0][x_index], axes[0][x_index + 1]
        for y_index in range(len(axes[1]) - 1):
            y_low, y_high = axes[1][y_index], axes[1][y_index + 1]
            for z_index in range(len(axes[2]) - 1):
                z_low, z_high = axes[2][z_index], axes[2][z_index + 1]
                covered = any(
                    low[0] <= x_low
                    and high[0] >= x_high
                    and low[1] <= y_low
                    and high[1] >= y_high
                    and low[2] <= z_low
                    and high[2] >= z_high
                    for low, high in bounds
                )
                if covered:
                    total += (x_high - x_low) * (y_high - y_low) * (z_high - z_low)
    return total


class PaneSash(wx.Window):
    """The draggable edge between a pane and the view beside it.

    It is focusable on purpose.  A divider that can only be dragged is a
    divider somebody who does not use a mouse can never move, so the arrow keys
    move it, Home puts it back, and the control says so in its own name.
    """

    THICKNESS = 6

    def __init__(
        self,
        parent: wx.Window,
        side: str,
        *,
        on_resize: Callable[[int], None],
        on_reset: Callable[[], None],
        name: str,
    ) -> None:
        super().__init__(parent, style=wx.WANTS_CHARS)
        #: ``left`` when the pane it resizes is on its left, so dragging right
        #: widens that pane; ``right`` when the pane is on its right, where the
        #: same drag narrows it.
        self.side = "right" if side == "right" else "left"
        self.on_resize = on_resize
        self.on_reset = on_reset
        self._dragging = False
        self._last_x = 0
        self._hovered = False
        self.SetName(name)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetCursor(wx.Cursor(wx.CURSOR_SIZEWE))
        self.SetToolTip(
            single_line(
                studio_text(
                    "Drag to resize this pane. The left and right arrow keys move "
                    "it, and Home puts it back where it started.",
                    "拉住就可以改呢一欄嘅闊度。左右箭嘴掣一樣得，撳 Home 就返到最初嘅闊度。",
                )
            )
        )
        self.SetMinSize(wx.Size(tokens.scaled(self.THICKNESS), -1))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_LEFT_DCLICK, self._on_double_click)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_focus)

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def _apply(self, divider_delta: int) -> None:
        """Convert a divider movement into a width change for the owned pane."""
        if not divider_delta:
            return
        invoke(self.on_resize, divider_delta if self.side == "left" else -divider_delta)

    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        self._dragging = True
        self._last_x = wx.GetMousePosition().x
        if not self.HasCapture():
            self.CaptureMouse()
        event.Skip()

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        self._release()
        event.Skip()

    def _release(self) -> None:
        self._dragging = False
        if self.HasCapture():
            self.ReleaseMouse()

    def _on_capture_lost(self, _event: wx.MouseCaptureLostEvent) -> None:
        self._dragging = False

    def _on_motion(self, event: wx.MouseEvent) -> None:
        if self._dragging and event.Dragging() and event.LeftIsDown():
            current = wx.GetMousePosition().x
            self._apply(current - self._last_x)
            self._last_x = current
        event.Skip()

    def _on_double_click(self, event: wx.MouseEvent) -> None:
        self._release()
        invoke(self.on_reset)
        event.Skip()

    def _on_enter(self, event: wx.MouseEvent) -> None:
        self._hovered = True
        self.Refresh()
        event.Skip()

    def _on_leave(self, event: wx.MouseEvent) -> None:
        self._hovered = False
        self.Refresh()
        event.Skip()

    def _on_focus(self, event: wx.FocusEvent) -> None:
        self.Refresh()
        event.Skip()

    def _on_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        step = SASH_LARGE_STEP if event.ShiftDown() else SASH_STEP
        if code == wx.WXK_LEFT:
            self._apply(-step)
        elif code == wx.WXK_RIGHT:
            self._apply(step)
        elif code in (wx.WXK_HOME, wx.WXK_NUMPAD_HOME):
            invoke(self.on_reset)
        else:
            event.Skip()

    def refresh_theme(self) -> None:
        """Repaint the divider in the live palette."""
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        centre = width // 2
        active = self._hovered or self._dragging or self.HasFocus()
        gcdc.SetPen(wx.Pen(palette.primary if active else palette.outline_variant, 1))
        gcdc.DrawLine(centre, 0, centre, height)
        if active:
            grip = tokens.scaled(18)
            top = max(0, (height - grip) // 2)
            tokens.draw_round_rect(
                gcdc,
                wx.Rect(centre - 1, top, 3, grip),
                2,
                palette.primary,
            )
        del gcdc


class CrumbButton(StudioButton):
    """One step of the breadcrumb path, filled while it is the current one."""

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        *,
        active: bool = False,
        on_click: Optional[Callable[[], None]] = None,
        hint: str = "",
    ) -> None:
        self.active = bool(active)
        super().__init__(
            parent,
            single_line(label),
            variant="text",
            on_click=on_click,
            height=24,
            hint=hint,
        )
        state = " (current)" if self.active else ""
        self.SetName(f"{single_line(label)}{state}")

    def _state_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour, Optional[wx.Colour]]:
        fill: Optional[wx.Colour] = (
            palette.surface_container_high if self.active else None
        )
        ink = palette.on_surface if self.active else palette.on_surface_variant
        if self._pressed:
            fill = tokens.blend(
                palette.surface_container_high, palette.on_surface, 0.10
            )
            ink = palette.on_surface
        elif self._hovered:
            fill = palette.surface_container_high
            ink = palette.on_surface
        return fill, ink, None


class OutlinePill(wx.Control):
    """The outlined monospaced readout at the right of the breadcrumb bar."""

    HEIGHT = 24
    PADDING = 10

    def __init__(self, parent: wx.Window, text: str, *, name: str) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self._text = ""
        self._label = str(name)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.set_text(text)

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def text(self) -> str:
        """Return the readout's current text."""
        return self._text

    def set_text(self, text: str) -> None:
        """Replace the readout and re-measure the pill around it."""
        self._text = single_line(text)
        self.SetName(f"{self._label}: {self._text}")
        self.SetToolTip(self._text)
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.mono_font(self, point_size(11)))
        width = dc.GetTextExtent(self._text or " ")[0]
        return wx.Size(
            width + tokens.scaled(self.PADDING) * 2, tokens.scaled(self.HEIGHT)
        )

    def refresh_theme(self) -> None:
        """Re-measure for the live density and repaint."""
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
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
            None,
            palette.outline_variant,
        )
        gcdc.SetFont(tokens.mono_font(self, point_size(11)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        inset = tokens.scaled(self.PADDING)
        text = elide(gcdc, self._text, max(0, width - inset * 2))
        gcdc.DrawText(text, inset, (height - gcdc.GetCharHeight()) // 2)
        del gcdc


class BreadcrumbBar(wx.Panel):
    """The context strip under the ribbon: where you are, and what is selected."""

    HEIGHT = BREADCRUMB_HEIGHT

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_history: Optional[Callable[[], None]] = None,
        on_surface: Optional[Callable[[str], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_history = on_history
        self.on_surface = on_surface
        self.on_command = on_command
        self.SetName("Workspace context bar")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.crumb_panel = wx.Panel(self, style=wx.TAB_TRAVERSAL)
        self.crumb_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.crumb_panel.SetSizer(self.crumb_sizer)
        self.revision = RevisionPill(
            self,
            "a91f0c7",
            len(DEFAULT_REVISIONS),
            glyph="●",
            suffix="revisions",
            on_click=self._open_history,
        )
        self.summary = OutlinePill(
            self, "3 boxes · 576 blocks", name="Selection summary"
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.crumb_panel, 0, wx.ALIGN_CENTER_VERTICAL)
        row.AddStretchSpacer(1)
        row.Add(
            self.revision,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_SM),
        )
        row.Add(
            self.summary,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_SM),
        )
        frame = wx.BoxSizer(wx.HORIZONTAL)
        frame.Add(row, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, tokens.scaled(14))
        self.SetSizer(frame)
        self.SetMinSize(wx.Size(-1, tokens.scaled(self.HEIGHT)))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self._apply_theme()

    def _open_history(self) -> None:
        if self.on_history is not None:
            invoke(self.on_history)
        else:
            invoke(self.on_surface, "history")

    def set_crumbs(
        self, crumbs: Sequence[Tuple[str, Optional[Callable[[], None]], str]]
    ) -> None:
        """Rebuild the path from ``(label, action, hint)`` triples.

        The last crumb is the current place, so it is drawn as the active one
        even when it still runs an action -- reaching the place you are already
        in should reveal it, not do nothing.
        """
        clear_container(self.crumb_sizer, self.crumb_panel)
        total = len(crumbs)
        for index, (label, action, hint) in enumerate(crumbs):
            self.crumb_sizer.Add(
                CrumbButton(
                    self.crumb_panel,
                    label,
                    active=index == total - 1,
                    on_click=action,
                    hint=hint,
                ),
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                tokens.scaled(2),
            )
        self.crumb_panel.Layout()
        self.Layout()

    def set_revision(self, commit: str, count: int) -> None:
        """Show a new head revision on the tinted pill."""
        self.revision.set_revision(commit, count)
        self.Layout()

    def set_summary(self, text: str) -> None:
        """Show how much the current selection covers."""
        self.summary.set_text(text)
        self.Layout()

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        position = event.GetPosition()
        if position == wx.DefaultPosition:
            size = self.GetSize()
            position = self.ClientToScreen(wx.Point(size.width // 2, size.height // 2))
        open_studio_menu(self, "pane", position, self.on_surface, self.on_command)

    def _apply_theme(self) -> None:
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface)
        self.crumb_panel.SetBackgroundColour(palette.surface)

    def refresh_theme(self) -> None:
        """Re-read the palette for the bar and everything on it."""
        self._apply_theme()
        for child in list(self.GetChildren()) + list(self.crumb_panel.GetChildren()):
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        self.Layout()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = paint_context(self, palette.surface)
        width, height = self.GetClientSize()
        gcdc.SetPen(wx.Pen(palette.outline_variant))
        gcdc.DrawLine(0, height - 1, width, height - 1)
        del gcdc


class WorkspaceView(wx.Panel):
    """The whole editing surface, and the single owner of what it shows."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_surface: Optional[Callable[[str], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
        on_backstage: Optional[Callable[[str], None]] = None,
        surface_key: str = "workspace",
        title: str = "Untitled project",
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self._on_surface = on_surface
        self._on_command = on_command
        self.on_backstage = on_backstage
        self.surface_key = str(surface_key)
        self.doc_title = str(title)
        self.project_path = ""
        self.saved = True
        self.boxes: List[SelectionBox] = list(DEFAULT_BOXES)
        self.revisions: List[ProjectRevision] = list(DEFAULT_REVISIONS)
        self.camera_speed = status_module.DEFAULT_CAMERA_SPEED
        self.SetName("Workspace")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        self.ribbon = RibbonBar(
            self,
            on_surface=self.open_surface,
            on_command=self.run_command,
            on_backstage=self._show_backstage,
        )
        self.breadcrumb = BreadcrumbBar(
            self,
            on_history=self._open_history,
            on_surface=self.open_surface,
            on_command=self.run_command,
        )
        self.split = wx.Panel(self, style=wx.TAB_TRAVERSAL)
        self.navigator = NavigatorPanel(
            self.split,
            dimensions=DEFAULT_DIMENSIONS,
            boxes=self.boxes,
            on_dimension=self._on_dimension,
            on_box=self._on_box,
            on_add_box=self._add_box,
            on_surface=self.open_surface,
            on_command=self.run_command,
        )
        self.navigator_sash = PaneSash(
            self.split,
            "left",
            on_resize=lambda delta: self.nudge_pane_width("navigator", delta),
            on_reset=lambda: self.reset_pane_width("navigator"),
            name="Resize the navigator pane",
        )
        self.centre = wx.Panel(self.split, style=wx.TAB_TRAVERSAL)
        self.viewport = ViewportHost(
            self.centre,
            on_surface=self.open_surface,
            on_command=self.run_command,
            on_tool=self._on_tool,
            on_projection=self._on_projection_from_viewport,
            on_selection=self._on_selection_changed,
        )
        self.status = StatusBar(
            self.centre,
            on_history=self._open_history,
            on_speed=self._on_speed,
            on_projection=self._on_projection_from_status,
            on_surface=self.open_surface,
            on_command=self.run_command,
        )
        centre_sizer = wx.BoxSizer(wx.VERTICAL)
        centre_sizer.Add(self.viewport, 1, wx.EXPAND)
        centre_sizer.Add(self.status, 0, wx.EXPAND)
        self.centre.SetSizer(centre_sizer)
        self.properties_sash = PaneSash(
            self.split,
            "right",
            on_resize=lambda delta: self.nudge_pane_width("properties", delta),
            on_reset=lambda: self.reset_pane_width("properties"),
            name="Resize the properties pane",
        )
        self.properties = PropertiesPane(
            self.split,
            project_key=self._project_key(),
            on_close=lambda: self.show_properties(False),
            on_action=self._on_pane_action,
            on_restore=self.restore_revision,
            on_surface=self.open_surface,
            on_command=self.run_command,
        )

        split_sizer = wx.BoxSizer(wx.HORIZONTAL)
        split_sizer.Add(self.navigator, 0, wx.EXPAND)
        split_sizer.Add(self.navigator_sash, 0, wx.EXPAND)
        split_sizer.Add(self.centre, 1, wx.EXPAND)
        split_sizer.Add(self.properties_sash, 0, wx.EXPAND)
        split_sizer.Add(self.properties, 0, wx.EXPAND)
        self.split.SetSizer(split_sizer)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self.ribbon, 0, wx.EXPAND)
        root.Add(self.breadcrumb, 0, wx.EXPAND)
        root.Add(self.split, 1, wx.EXPAND)
        self.SetSizer(root)

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self._theme_unsubscribe = tokens.register_theme_listener(self.refresh_theme)
        self._apply_theme()
        self._restore_pane_widths()
        self.refresh_state()

    # ------------------------------------------------------------------
    # project state
    # ------------------------------------------------------------------
    def _project_key(self) -> str:
        """Return the key a project's own records are stored under."""
        return self.project_path or self.doc_title

    def set_project(self, title: str, path: str = "") -> None:
        """Point the workspace at another project."""
        self.doc_title = str(title)
        self.project_path = str(path)
        self.properties.set_project(self._project_key())
        self.refresh_state()

    def set_saved(self, saved: bool) -> None:
        """Record whether the project has unsaved changes and say so."""
        self.saved = bool(saved)
        self.status.set_status_text(
            (
                studio_label("Ready", "準備好")
                if self.saved
                else studio_label("Unsaved changes", "有嘢未儲存")
            ),
            "ready" if self.saved else "busy",
        )

    def selected_box(self) -> Optional[SelectionBox]:
        """Return the selection box the workspace is currently editing."""
        return self.navigator.selected_box()

    def refresh_state(self) -> None:
        """Push the workspace's state into all five panels at once."""
        box = self.selected_box()
        dimension = self.navigator.dimension()
        dimension_label = dimension.label if dimension else "minecraft:overworld"
        head = self.revisions[0] if self.revisions else None
        if box is not None:
            self.status.set_selection(box.delta_text())
            self.viewport.set_selection(box.label, box.minimum, box.maximum)
        self.status.set_dimension(dimension_label)
        self.viewport.set_status(dimension=dimension_label)
        if dimension is not None:
            self.viewport.set_status(chunks=dimension.chunks)
        boxes = len(self.boxes)
        plural = "box" if boxes == 1 else "boxes"
        self.breadcrumb.set_summary(
            f"{boxes} {plural} · {selection_volume(self.boxes)} blocks"
        )
        if head is not None:
            self.breadcrumb.set_revision(head.commit, len(self.revisions))
            self.status.set_revision(head.commit, len(self.revisions))
        self.properties.set_revisions(self.revisions)
        self.properties.set_sections(self._build_sections())
        self.properties.set_title(box.label if box is not None else self.doc_title)
        self._rebuild_breadcrumb()
        self.set_saved(self.saved)

    def _build_sections(self) -> Tuple[PropertySection, ...]:
        """Describe the current selection, dimension, and head revision."""
        box = self.selected_box()
        dimension = self.navigator.dimension()
        head = self.revisions[0] if self.revisions else None
        selection_rows: Tuple[Tuple[str, str], ...] = ()
        if box is not None:
            selection_rows = (
                ("Minimum", box.corner_text(box.minimum)),
                ("Maximum", box.corner_text(box.maximum)),
                ("Size", box.size_text()),
                ("Volume", f"{box.volume} blocks"),
            )
        dimension_rows: Tuple[Tuple[str, str], ...] = ()
        if dimension is not None:
            dimension_rows = (
                ("Dimension", dimension.label),
                ("Height range", dimension.height_range),
                ("Loaded chunks", str(dimension.chunks)),
            )
        revision_rows: Tuple[Tuple[str, str], ...] = ()
        if head is not None:
            parts = [part.strip() for part in head.meta.split("·")]
            committed = parts[1] if len(parts) > 1 else head.meta
            revision_rows = (
                ("Head", head.commit),
                ("Message", head.message),
                ("Committed", committed),
                ("Revisions", f"{len(self.revisions)} commits"),
            )
        return (
            PropertySection("Selection", selection_rows),
            PropertySection("Dimension", dimension_rows),
            PropertySection("Revision", revision_rows),
        )

    def _rebuild_breadcrumb(self) -> None:
        box = self.selected_box()
        dimension = self.navigator.dimension()
        crumbs: List[Tuple[str, Optional[Callable[[], None]], str]] = [
            (
                self.doc_title,
                lambda: self._show_backstage("info"),
                "Open the project information page",
            ),
            (
                dimension.label if dimension else "minecraft:overworld",
                self._reveal_dimension,
                "Reveal this dimension in the navigator",
            ),
        ]
        if box is not None:
            crumbs.append(
                (box.label, self._reveal_box, "Reveal this box in the navigator")
            )
        self.breadcrumb.set_crumbs(crumbs)

    def _reveal_dimension(self) -> None:
        self.navigator.SetFocus()
        for child in self.navigator.tree_panel.GetChildren():
            if isinstance(child, navigator_module.DimensionRow) and child.selected:
                child.SetFocus()
                return

    def _reveal_box(self) -> None:
        for child in self.navigator.boxes_panel.GetChildren():
            if isinstance(child, navigator_module.BoxCard) and child.selected:
                child.SetFocus()
                return
        self.navigator.SetFocus()

    # ------------------------------------------------------------------
    # revisions
    # ------------------------------------------------------------------
    def record_revision(self, message: str, detail: str) -> ProjectRevision:
        """Append a revision for an operation that changed the project.

        The project's repository is append-only, so this never rewrites an
        existing entry: the new commit becomes the head and every earlier one
        keeps its place in the list.
        """
        commit = uuid.uuid4().hex[:7]
        stamp = datetime.now().strftime("%d %b %Y, %H:%M")
        revision = ProjectRevision(
            commit, str(message), f"{commit} · {stamp} · {detail}", head=True
        )
        self.revisions = [revision] + [
            replace(item, head=False) for item in self.revisions
        ]
        local_history.safe_record(
            f"studio-project-{self._project_key()}",
            {
                "project": self._project_key(),
                "commit": commit,
                "message": str(message),
                "detail": str(detail),
            },
            record_type="studio revision",
        )
        return revision

    def restore_revision(self, commit: str) -> Optional[ProjectRevision]:
        """Restore a revision by writing a new one on top of it."""
        source = next(
            (item for item in self.revisions if item.commit == str(commit)), None
        )
        if source is None:
            log.debug("No revision %r to restore", commit)
            return None
        revision = self.record_revision(
            f"Restore {source.commit} · {source.message}",
            f"restored from {source.commit}",
        )
        self.refresh_state()
        self.notify(
            studio_label("Revision restored", "還原咗個版本"),
            studio_text(
                f"{source.commit} was restored as {revision.commit}. The revision "
                "you restored from is still in the history.",
                f"{source.commit} 已經還原做 {revision.commit}。你還原之前嗰個版本仲喺歷史度。",
            ),
        )
        return revision

    def notify(self, title: str, body: str, severity: str = "info") -> None:
        """Report a result without blocking whatever the user is doing.

        ``title`` names the event and is built with
        :func:`~amulet_map_editor.api.studio.copy.studio_label`; ``body`` is the
        application speaking and keeps its tone.  A toast title is a heading in
        a small card, so an aside appended to it clips before the sentence
        underneath -- which is exactly where it would have been readable.
        """
        try:
            from amulet_map_editor.api.wx import nonblocking
        except ImportError:
            log.debug("Non-blocking notifications are unavailable: %s", title)
            return
        nonblocking.notify(
            self, single_line(title), single_line(body), severity=severity
        )

    # ------------------------------------------------------------------
    # panel callbacks
    # ------------------------------------------------------------------
    def _on_dimension(self, _key: str) -> None:
        self.refresh_state()

    def _on_box(self, _index: int) -> None:
        self.boxes = list(self.navigator.boxes)
        self.refresh_state()

    def _add_box(self) -> None:
        box = self.navigator.add_box()
        self.boxes = list(self.navigator.boxes)
        self.record_revision(
            f"Add {box.label}", f"1 box at {box.corner_text(box.minimum)}"
        )
        self.set_saved(False)
        self.refresh_state()

    def _on_selection_changed(
        self, minimum: Tuple[int, int, int], maximum: Tuple[int, int, int]
    ) -> None:
        """Take a corner move from the viewport into the box it belongs to."""
        index = self.navigator.box_index
        if not 0 <= index < len(self.boxes):
            return
        current = self.boxes[index]
        size = tuple(high - low + 1 for low, high in zip(minimum, maximum))
        self.boxes[index] = SelectionBox(current.label, tuple(minimum), size)
        self.navigator.set_boxes(self.boxes)
        box = self.boxes[index]
        self.status.set_selection(box.delta_text())
        self.breadcrumb.set_summary(
            f"{len(self.boxes)} boxes · {selection_volume(self.boxes)} blocks"
        )
        self.properties.set_sections(self._build_sections())
        self.set_saved(False)

    def _on_tool(self, key: str) -> None:
        # These land in the status bar's readout, which sizes itself to its text
        # and lends it to the control's accessible name, so they are labels for
        # a state rather than the application talking: no tone.
        messages = {
            "frame": studio_label("Framed the selection", "已經對準咗個選取範圍"),
            "top": studio_label("Switched the view", "換咗個視角"),
            "slice": (
                studio_label("Layer slice on", "開咗層切片")
                if self.viewport.slice_visible
                else studio_label("Layer slice off", "熄咗層切片")
            ),
            "reset": studio_label("Camera reset", "鏡頭返晒去原位"),
        }
        message = messages.get(key)
        if message:
            self.status.set_status_text(message)

    def _on_projection_from_viewport(self, key: str) -> None:
        self.status.set_projection(key)

    def _on_projection_from_status(self, key: str) -> None:
        self.viewport.set_projection(key)

    def _on_speed(self, value: int) -> None:
        self.camera_speed = int(value)
        self.status.set_status_text(
            studio_label(
                f"Camera speed {value} blocks per second",
                f"鏡頭速度每秒 {value} 格",
            )
        )

    def _on_pane_action(self, key: str) -> None:
        if key == "frame":
            self.viewport.frame_selection()
            self._on_tool("frame")

    def _open_history(self) -> None:
        self.open_surface("history")

    def _show_backstage(self, tab: str = "home") -> None:
        invoke(self.on_backstage, tab)

    # ------------------------------------------------------------------
    # surfaces and commands
    # ------------------------------------------------------------------
    def open_surface(self, key: str) -> Optional[wx.Window]:
        """Open a Studio surface, through the shell when one is wired up."""
        if self._on_surface is not None:
            return invoke(self._on_surface, key)
        try:
            from amulet_map_editor.api.studio import surfaces
        except ImportError:
            log.debug("The Studio surface index is unavailable; cannot open %r", key)
            return None
        try:
            return surfaces.open_surface(self, key)
        except Exception:
            log.exception("Could not open the %r surface", key)
            return None

    def run_command(self, key: str) -> None:
        """Run a Studio command, through the shell when one is wired up."""
        if self._on_command is not None:
            invoke(self._on_command, key)
            return
        log.debug("No command handler is wired up for %r", key)

    # ------------------------------------------------------------------
    # renderer and panes
    # ------------------------------------------------------------------
    def set_canvas(self, window: Optional[wx.Window]) -> None:
        """Hand the viewport a real renderer canvas, or take it away again."""
        self.viewport.set_canvas(window)

    def properties_visible(self) -> bool:
        """Return whether the properties pane is currently shown."""
        return self.properties.IsShown()

    def show_properties(self, visible: bool) -> None:
        """Show or hide the properties pane and its divider together."""
        self.properties.Show(bool(visible))
        self.properties_sash.Show(bool(visible))
        self.split.Layout()
        self.Layout()

    def toggle_properties(self) -> None:
        """Flip the properties pane in or out of the layout."""
        self.show_properties(not self.properties_visible())

    def toggle_ribbon(self) -> None:
        """Collapse or expand the command ribbon."""
        self.ribbon.toggle_collapsed()
        self.Layout()

    def set_ribbon_tab(self, key: str) -> None:
        """Open one of the ribbon's tabs by key."""
        self.ribbon.set_tab(key)

    def _pane(self, pane: str) -> wx.Panel:
        return self.navigator if pane == "navigator" else self.properties

    def _default_width(self, pane: str) -> int:
        return (
            navigator_module.PANEL_WIDTH
            if pane == "navigator"
            else properties_module.PANEL_WIDTH
        )

    def _minimum_width(self, pane: str) -> int:
        return (
            navigator_module.MIN_PANEL_WIDTH
            if pane == "navigator"
            else properties_module.MIN_PANEL_WIDTH
        )

    def pane_width(self, pane: str) -> int:
        """Return a pane's current width in physical pixels."""
        return int(self._pane(pane).GetSize().width)

    def _clamp_width(self, pane: str, width: int) -> int:
        """Keep a pane inside its own bounds and leave the view usable."""
        lowest = tokens.scaled(self._minimum_width(pane))
        highest = tokens.scaled(MAX_PANE_WIDTH)
        available = self.split.GetClientSize().width
        if available > 0:
            other = "properties" if pane == "navigator" else "navigator"
            taken = tokens.scaled(MIN_VIEWPORT_WIDTH) + tokens.scaled(
                PaneSash.THICKNESS * 2
            )
            if self._pane(other).IsShown():
                taken += self.pane_width(other)
            highest = min(highest, max(lowest, available - taken))
        return max(lowest, min(highest, int(width)))

    def set_pane_width(self, pane: str, width: int, *, persist: bool = True) -> int:
        """Resize one pane, clamp it, and remember the result."""
        clamped = self._clamp_width(pane, width)
        target = self._pane(pane)
        target.SetMinSize(wx.Size(clamped, -1))
        target.SetSize(wx.Size(clamped, target.GetSize().height))
        self.split.Layout()
        if persist:
            store_pane_width(self.surface_key, pane, clamped)
        return clamped

    def nudge_pane_width(self, pane: str, delta: int) -> int:
        """Move one pane's edge by ``delta`` physical pixels."""
        return self.set_pane_width(pane, self.pane_width(pane) + int(delta))

    def reset_pane_width(self, pane: str) -> int:
        """Put one pane back to the width the design ships."""
        width = self.set_pane_width(
            pane, tokens.scaled(self._default_width(pane)), persist=False
        )
        store_pane_width(self.surface_key, pane, width)
        return width

    def reset_pane_widths(self) -> None:
        """Put both panes back and forget the remembered widths."""
        clear_pane_widths(self.surface_key)
        for pane in ("navigator", "properties"):
            self.set_pane_width(
                pane, tokens.scaled(self._default_width(pane)), persist=False
            )
        self.notify(
            studio_label("Pane widths reset", "欄闊度已經還原"),
            studio_text(
                "The navigator and properties panes are back at their shipped "
                "widths.",
                "導覽同屬性兩欄都返返出廠嗰個闊度。",
            ),
        )

    def _restore_pane_widths(self) -> None:
        widths = load_pane_widths()
        for pane in ("navigator", "properties"):
            stored = widths.get(f"{self.surface_key}.{pane}")
            self.set_pane_width(
                pane,
                stored if stored else tokens.scaled(self._default_width(pane)),
                persist=False,
            )

    # ------------------------------------------------------------------
    # appearance
    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface)
        self.split.SetBackgroundColour(palette.surface)
        self.centre.SetBackgroundColour(palette.surface)

    def refresh_theme(self) -> None:
        """Re-read the tokens and repaint every panel in the workspace."""
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:
            return
        self._apply_theme()
        for panel in (
            self.ribbon,
            self.breadcrumb,
            self.navigator,
            self.navigator_sash,
            self.viewport,
            self.status,
            self.properties_sash,
            self.properties,
        ):
            refresh = getattr(panel, "refresh_theme", None)
            if callable(refresh):
                try:
                    refresh()
                except RuntimeError:
                    log.debug("A workspace panel was gone before it could repaint")
        self.Layout()
        self.Refresh()

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self and self._theme_unsubscribe is not None:
            self._theme_unsubscribe()
            self._theme_unsubscribe = None
        event.Skip()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = paint_context(self, palette.surface)
        del gcdc
        del dc


__all__ = [
    "BREADCRUMB_HEIGHT",
    "BreadcrumbBar",
    "CrumbButton",
    "MAX_PANE_WIDTH",
    "MIN_VIEWPORT_WIDTH",
    "OutlinePill",
    "PANE_WIDTHS_ID",
    "PaneSash",
    "SASH_LARGE_STEP",
    "SASH_STEP",
    "WorkspaceView",
    "clear_pane_widths",
    "load_pane_widths",
    "selection_volume",
    "store_pane_width",
]
