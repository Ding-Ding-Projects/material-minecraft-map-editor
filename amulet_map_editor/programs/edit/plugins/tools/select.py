from typing import TYPE_CHECKING, Tuple, Iterable
import logging

import wx
from OpenGL.GL import (
    glClear,
    GL_DEPTH_BUFFER_BIT,
)

from amulet.api.data_types import BlockCoordinates

from amulet_map_editor import lang
from amulet_map_editor.api.studio.widgets import Divider, StudioText
from amulet_map_editor.api.opengl.camera import Projection, Camera
from amulet_map_editor.programs.edit.api.events import EVT_SELECTION_CHANGE
from amulet_map_editor.programs.edit.api.behaviour.inspect_block_behaviour import (
    InspectBlockBehaviour,
)
from amulet_map_editor.programs.edit.api.behaviour.block_selection_behaviour import (
    BlockSelectionBehaviour,
    EVT_RENDER_BOX_CHANGE,
    RenderBoxChangeEvent,
    EVT_RENDER_BOX_DISABLE_INPUTS,
    EVT_RENDER_BOX_ENABLE_INPUTS,
)
from amulet_map_editor.programs.edit.api.ui.tool import DefaultBaseToolUI
from amulet_map_editor.programs.edit.api.ui.material_tool_panel import (
    PANEL_PADDING,
    ToolPanel,
    TupleNumberField,
    section_heading,
    tool_button,
)
from amulet_map_editor.programs.edit.api.key_config import (
    KeybindGroup,
)
from amulet_map_editor.programs.edit.api.ui.nudge_button import MaterialNudgeButton

if TYPE_CHECKING:
    from amulet_map_editor.programs.edit.api.canvas import EditCanvas


log = logging.getLogger(__name__)
paint_log_count = 0


class BaseSelectionMoveButton(MaterialNudgeButton):
    def __init__(
        self,
        parent: wx.Window,
        camera: Camera,
        keybinds: KeybindGroup,
        label: str,
        tooltip: str,
        selection: BlockSelectionBehaviour,
    ):
        super().__init__(parent, camera, keybinds, label, tooltip)
        self._selection = selection


class Point1MoveButton(BaseSelectionMoveButton):
    def _move(self, offset: Tuple[int, int, int]):
        ox, oy, oz = offset
        (x, y, z), point2 = self._selection.active_block_positions
        self._selection.active_block_positions = (x + ox, y + oy, z + oz), point2


class Point2MoveButton(BaseSelectionMoveButton):
    def _move(self, offset: Tuple[int, int, int]):
        ox, oy, oz = offset
        point1, (x, y, z) = self._selection.active_block_positions
        self._selection.active_block_positions = point1, (x + ox, y + oy, z + oz)


class SelectionMoveButton(BaseSelectionMoveButton):
    def _move(self, offset: Tuple[int, int, int]):
        ox, oy, oz = offset
        (x1, y1, z1), (x2, y2, z2) = self._selection.active_block_positions
        self._selection.active_block_positions = (x1 + ox, y1 + oy, z1 + oz), (
            x2 + ox,
            y2 + oy,
            z2 + oz,
        )


class SelectTool(wx.BoxSizer, DefaultBaseToolUI):
    def __init__(self, canvas: "EditCanvas"):
        wx.BoxSizer.__init__(self, wx.HORIZONTAL)
        DefaultBaseToolUI.__init__(self, canvas)

        self._selection = BlockSelectionBehaviour(self.canvas)
        self._inspect_block = InspectBlockBehaviour(self.canvas, self._selection)

        self._button_panel = ToolPanel(canvas.GetParent(), "Select tool options")
        button_sizer = self._button_panel.sizer
        pad = wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND

        def add_line():
            button_sizer.Add(Divider(self._button_panel), 0, pad, PANEL_PADDING)

        button_sizer.AddSpacer(PANEL_PADDING)

        self._delete_button = tool_button(
            self._button_panel,
            lang.get("program_3d_edit.select_tool.delete_button"),
            tooltip=lang.get("program_3d_edit.select_tool.delete_button_tooltip"),
            variant="danger",
            on_click=lambda: self.canvas.delete(),
        )
        button_sizer.Add(self._delete_button, 0, pad, PANEL_PADDING)

        self._copy_button = tool_button(
            self._button_panel,
            lang.get("program_3d_edit.select_tool.copy_button"),
            tooltip=lang.get("program_3d_edit.select_tool.copy_button_tooltip"),
            variant="tonal",
            on_click=lambda: self.canvas.copy(),
        )
        button_sizer.Add(self._copy_button, 0, pad, PANEL_PADDING)

        self._cut_button = tool_button(
            self._button_panel,
            lang.get("program_3d_edit.select_tool.cut_button"),
            tooltip=lang.get("program_3d_edit.select_tool.cut_button_tooltip"),
            variant="tonal",
            on_click=lambda: self.canvas.cut(),
        )
        button_sizer.Add(self._cut_button, 0, pad, PANEL_PADDING)

        self._paste_button = tool_button(
            self._button_panel,
            lang.get("program_3d_edit.select_tool.paste_button"),
            tooltip=lang.get("program_3d_edit.select_tool.paste_button_tooltip"),
            variant="tonal",
            on_click=lambda: self.canvas.paste_from_cache(),
        )
        button_sizer.Add(self._paste_button, 0, pad, PANEL_PADDING)

        add_line()

        # Point 1 -- the box's green corner.  Colour alone never carries the
        # meaning: the heading names it, the per-axis letter is coloured the
        # way the viewport's own axis legend is, and the move button beneath
        # repeats the words "Point 1" so a reader who cannot see colour still
        # knows which corner each control touches.
        button_sizer.Add(
            section_heading(
                self._button_panel,
                lang.get("program_3d_edit.select_tool.point1_heading"),
            ),
            0,
            pad,
            PANEL_PADDING,
        )
        self._point1 = TupleNumberField(
            self._button_panel,
            ("X", "Y", "Z"),
            group="Point 1",
            tooltips=(
                lang.get("program_3d_edit.select_tool.scroll_point_x1_tooltip"),
                lang.get("program_3d_edit.select_tool.scroll_point_y1_tooltip"),
                lang.get("program_3d_edit.select_tool.scroll_point_z1_tooltip"),
            ),
            on_change=lambda _value: self._box_input_change(),
            on_layout=self._resize,
        )
        button_sizer.Add(self._point1, 0, pad, PANEL_PADDING)
        self._point1_move = Point1MoveButton(
            self._button_panel,
            self.canvas.camera,
            self.canvas.key_binds,
            lang.get("program_3d_edit.select_tool.button_point1"),
            lang.get("program_3d_edit.select_tool.button_point1_tooltip"),
            self._selection,
        )
        self._point1_move.Disable()
        button_sizer.Add(self._point1_move, 0, pad, PANEL_PADDING)

        add_line()

        button_sizer.Add(
            section_heading(
                self._button_panel,
                lang.get("program_3d_edit.select_tool.point2_heading"),
            ),
            0,
            pad,
            PANEL_PADDING,
        )
        self._point2 = TupleNumberField(
            self._button_panel,
            ("X", "Y", "Z"),
            group="Point 2",
            tooltips=(
                lang.get("program_3d_edit.select_tool.scroll_point_x2_tooltip"),
                lang.get("program_3d_edit.select_tool.scroll_point_y2_tooltip"),
                lang.get("program_3d_edit.select_tool.scroll_point_z2_tooltip"),
            ),
            on_change=lambda _value: self._box_input_change(),
            on_layout=self._resize,
        )
        button_sizer.Add(self._point2, 0, pad, PANEL_PADDING)
        self._point2_move = Point2MoveButton(
            self._button_panel,
            self.canvas.camera,
            self.canvas.key_binds,
            lang.get("program_3d_edit.select_tool.button_point2"),
            lang.get("program_3d_edit.select_tool.button_point2_tooltip"),
            self._selection,
        )
        self._point2_move.Disable()
        button_sizer.Add(self._point2_move, 0, pad, PANEL_PADDING)

        add_line()

        self._box_size_selector_fstring = lang.get(
            "program_3d_edit.select_tool.box_size_selector_fstring"
        )
        try:
            box_size_fstring = self._box_size_selector_fstring.format(x=0, y=0, z=0)
        except Exception:
            self._box_size_selector_fstring = "dx={x},dy={y},dz={z}"
            box_size_fstring = self._box_size_selector_fstring.format(x=0, y=0, z=0)
        self._box_size_selector_text = StudioText(
            self._button_panel,
            box_size_fstring,
            size_px=12,
            role="on_surface_variant",
            name="Selection size",
        )
        self._box_size_selector_text.SetToolTip(
            lang.get("program_3d_edit.select_tool.box_size_selector_tooltip")
        )
        button_sizer.Add(self._box_size_selector_text, 0, pad, PANEL_PADDING)

        self._box_volume_text = StudioText(
            self._button_panel,
            "0x0x0=0",
            size_px=12,
            role="on_surface_variant",
            name="Selection volume",
        )
        self._box_volume_text.SetToolTip(
            lang.get("program_3d_edit.select_tool.box_size_tooltip")
        )
        button_sizer.Add(self._box_volume_text, 0, pad, PANEL_PADDING)

        self._selection_move = SelectionMoveButton(
            self._button_panel,
            self.canvas.camera,
            self.canvas.key_binds,
            lang.get("program_3d_edit.select_tool.button_selection_box"),
            lang.get("program_3d_edit.select_tool.button_selection_box_tooltip"),
            self._selection,
        )
        self._selection_move.Disable()
        button_sizer.Add(self._selection_move, 0, pad, PANEL_PADDING)

        self._resize()

    @property
    def name(self) -> str:
        return "Select"

    def bind_events(self):
        super().bind_events()
        self.canvas.Bind(EVT_RENDER_BOX_CHANGE, self._box_renderer_change)
        self.canvas.Bind(EVT_RENDER_BOX_DISABLE_INPUTS, self._disable_inputs)
        self.canvas.Bind(EVT_RENDER_BOX_ENABLE_INPUTS, self._enable_inputs)
        self.canvas.Bind(EVT_SELECTION_CHANGE, self._on_selection_change)
        self.canvas.Bind(wx.EVT_SIZE, self._on_resize)
        self._selection.bind_events()
        self._inspect_block.bind_events()

    def enable(self):
        super().enable()
        self._selection.enable()
        self._pull_selection()
        self._point1_move.enable()
        self._point2_move.enable()
        self._selection_move.enable()
        self._button_panel.Show()
        self._resize()

    def disable(self):
        super().disable()
        self._point1_move.disable()
        self._point2_move.disable()
        self._selection_move.disable()
        self._button_panel.Hide()

    def _box_input_change(self):
        self._selection.active_block_positions = (
            tuple(self._point1.value),
            tuple(self._point2.value),
        )

    def _box_renderer_change(self, evt: RenderBoxChangeEvent):
        self._update_selection_inputs(*evt.points)
        evt.Skip()

    def _on_selection_change(self, evt):
        self._pull_selection()
        evt.Skip()

    def _pull_selection(self):
        self._update_selection_inputs(*self._selection.active_block_positions)

    def _update_selection_inputs(
        self, point1: BlockCoordinates, point2: BlockCoordinates
    ):
        x1, y1, z1, x2, y2, z2 = map(int, (*point1, *point2))
        self._point1.value = (x1, y1, z1)
        self._point2.value = (x2, y2, z2)
        xdim = int(abs(x2 - x1))
        ydim = int(abs(y2 - y1))
        zdim = int(abs(z2 - z1))
        self._box_size_selector_text.SetLabel(
            self._box_size_selector_fstring.format(
                x=xdim,
                y=ydim,
                z=zdim,
            )
        )
        self._box_volume_text.SetLabel(
            f"{xdim + 1}x{ydim + 1}x{zdim + 1}={(xdim + 1)*(ydim + 1)*(zdim + 1):,}"
        )
        self._resize()

    def _enable_inputs(self, evt):
        self._set_scroll_state(True)
        self._point1_move.Enable()
        self._point2_move.Enable()
        self._selection_move.Enable()
        evt.Skip()

    def _disable_inputs(self, evt):
        self._set_scroll_state(False)
        self._point1_move.Disable()
        self._point2_move.Disable()
        self._selection_move.Disable()
        evt.Skip()

    def _set_scroll_state(self, state: bool):
        self._point1.Enable(state)
        self._point2.Enable(state)

    def _on_resize(self, evt):
        self._resize()
        evt.Skip()

    def _resize(self):
        # Docked flush against the right edge of the viewport, full height,
        # rather than centred over the middle of the world -- the raw wx
        # panel this replaces sat a third of the way down the left edge and
        # hid whatever the reader was trying to look at underneath it.
        panel_size = self._button_panel.GetBestSize()
        canvas_size = self.canvas.GetSize()
        canvas_width = canvas_size.GetWidth()
        canvas_height = canvas_size.GetHeight()
        panel_width = panel_size.GetWidth()
        panel_height = min(panel_size.GetHeight(), canvas_height)
        if panel_height < panel_size.GetHeight():
            panel_width += wx.SystemSettings.GetMetric(wx.SYS_VSCROLL_X)
        self._button_panel.SetSize(
            wx.Rect(
                max(0, canvas_width - panel_width),
                0,
                panel_width,
                panel_height,
            )
        )
        self._button_panel.Layout()
        self._button_panel.Raise()

    def _draw(self):
        global paint_log_count
        self.canvas.renderer.start_draw()
        if self.canvas.camera.projection_mode == Projection.PERSPECTIVE:
            self.canvas.renderer.draw_sky_box()
            glClear(GL_DEPTH_BUFFER_BIT)
        self.canvas.renderer.draw_level()
        self._selection.draw()
        self.canvas.mask_gl()
        self.canvas.renderer.end_draw()
        if paint_log_count < 10:
            paint_log_count += 1
            log.debug(f"Painted frame. {paint_log_count}/10")

    def windows(self) -> Iterable[wx.Window]:
        return [self._button_panel]
