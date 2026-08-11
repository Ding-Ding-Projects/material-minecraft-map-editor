from typing import TYPE_CHECKING, Dict, Tuple, Optional, Iterable
import logging

import wx
from OpenGL.GL import (
    glClear,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_TEST,
    glEnable,
    glDisable,
    glGetBoolean,
)

from amulet_map_editor import lang
from amulet_map_editor.api.opengl.camera import Projection, EVT_CAMERA_MOVED
from amulet_map_editor.programs.edit.api.ui.tool import DefaultBaseToolUI
from amulet_map_editor.programs.edit.api.behaviour import ChunkSelectionBehaviour
from amulet.operations.delete_chunk import delete_chunk
from amulet.api.data_types import Dimension
from amulet.api.data_types.operation_types import OperationReturnType
from amulet.api.level import BaseLevel
from amulet.api.selection import SelectionGroup
from amulet.api.chunk import Chunk
from amulet.api.errors import ChunkLoadError
from amulet.level.load import load_format
from amulet_map_editor.programs.edit.plugins.operations.stock_plugins.internal_operations.prune_chunks import (
    prune_chunks,
)
from amulet_map_editor.api.wx.ui.select_world import WorldSelectDialog
from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.programs.edit.api.ui.material_tool_panel import (
    NumberField,
    PANEL_PADDING,
    ToolPanel,
    section_heading,
    tool_button,
)

if TYPE_CHECKING:
    from amulet_map_editor.programs.edit.api.canvas import EditCanvas


log = logging.getLogger(__name__)


def _log_failure(action: str, outcome: object) -> None:
    """Record that a chunk operation did not complete, naming which one.

    ``run_operation`` reports the error to the user itself, so this deliberately
    does not raise a second notification for the same fault.  What it adds is the
    name of the button that was pressed: the canvas's own message says an
    operation failed, and the log then said nothing at all about *which* of the
    four chunk operations it was.  A deliberate abort -- the user cancelling the
    progress dialog -- is not a failure and is not logged as one.

    ``outcome`` is typed loosely on purpose: a build whose canvas predates
    :class:`OperationOutcome` answers ``None`` here, and an absent answer is not
    evidence of a failure.
    """
    if getattr(outcome, "failed", False):
        log.warning("%s did not complete: %s", action, getattr(outcome, "message", ""))


class ChunkTool(wx.BoxSizer, DefaultBaseToolUI):
    def __init__(self, canvas: "EditCanvas"):
        wx.BoxSizer.__init__(self, wx.HORIZONTAL)
        DefaultBaseToolUI.__init__(self, canvas)

        self._selection = ChunkSelectionBehaviour(self.canvas)

        self._button_panel = ToolPanel(canvas.GetParent(), "Chunk tool options")
        self._button_panel.Hide()
        button_sizer = self._button_panel.sizer
        pad = wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND

        button_sizer.AddSpacer(PANEL_PADDING)
        button_sizer.Add(
            section_heading(
                self._button_panel,
                lang.get("program_3d_edit.chunk_tool.view_range"),
            ),
            0,
            pad,
            PANEL_PADDING,
        )
        self._min_y = NumberField(
            self._button_panel,
            lang.get("program_3d_edit.chunk_tool.min_y"),
            256,
            -30_000_000,
            30_000_000,
            tooltip=lang.get("program_3d_edit.chunk_tool.min_y_tooltip"),
            name=lang.get("program_3d_edit.chunk_tool.min_y"),
            on_change=lambda _value: self._on_clipping_changed(),
            on_layout=self._resize,
        )
        button_sizer.Add(self._min_y, 0, pad, PANEL_PADDING)

        self._max_y = NumberField(
            self._button_panel,
            lang.get("program_3d_edit.chunk_tool.max_y"),
            0,
            -30_000_000,
            30_000_000,
            tooltip=lang.get("program_3d_edit.chunk_tool.max_y_tooltip"),
            name=lang.get("program_3d_edit.chunk_tool.max_y"),
            on_change=lambda _value: self._on_clipping_changed(),
            on_layout=self._resize,
        )
        button_sizer.Add(self._max_y, 0, pad, PANEL_PADDING)
        self._dimensions: Dict[Dimension, Tuple[int, int]] = {}

        button_sizer.Add(
            section_heading(
                self._button_panel,
                lang.get("program_3d_edit.chunk_tool.chunk_actions"),
            ),
            0,
            pad,
            PANEL_PADDING,
        )
        for key, handler, variant in (
            ("create_chunks", self._create_chunks, "tonal"),
            ("delete_chunks", self._delete_chunks, "danger"),
            ("prune_chunks", self._prune_chunks, "danger"),
            ("import_chunks", self._import_chunks, "tonal"),
        ):
            button_sizer.Add(
                tool_button(
                    self._button_panel,
                    lang.get(f"program_3d_edit.chunk_tool.{key}"),
                    tooltip=lang.get(f"program_3d_edit.chunk_tool.{key}_tooltip"),
                    variant=variant,
                    on_click=handler,
                ),
                0,
                pad,
                PANEL_PADDING,
            )

        self._resize()

    @property
    def name(self) -> str:
        return "Chunk"

    def bind_events(self):
        super().bind_events()
        self._selection.bind_events()
        self.canvas.Bind(EVT_CAMERA_MOVED, self._on_update_clipping)
        self.canvas.Bind(wx.EVT_SIZE, self._on_resize)

    def enable(self):
        self._button_panel.Show()
        self.canvas.camera.projection_mode = Projection.TOP_DOWN
        self._selection.enable()
        self._update_clipping()

        dimension = self.canvas.dimension
        if dimension not in self._dimensions:
            self._dimensions[dimension] = (
                min(
                    30_000_000,
                    max(-30_000_000, self.canvas.world.bounds(dimension).min[1]),
                ),
                min(
                    30_000_000,
                    max(-30_000_000, self.canvas.world.bounds(dimension).max[1]),
                ),
            )
        miny, maxy = self._dimensions[dimension]
        self._min_y.SetValue(miny)
        self._max_y.SetValue(maxy)
        self._update_clipping()
        self._resize()

    def disable(self):
        super().disable()
        self.canvas.camera.orthographic_clipping = -(10**5), 10**5
        self._button_panel.Hide()

    def _on_update_clipping(self, evt):
        self._update_clipping()
        evt.Skip()

    def _on_clipping_changed(self) -> None:
        """One of the two Y boxes moved.

        The boxes report through their own callback rather than through a spin
        event caught at the panel, which is what the native controls did.  The
        difference matters: a panel-level ``EVT_SPINCTRL`` fired for whichever
        spin control happened to be on the panel, so adding a third one later
        would silently have redrawn the clipping planes as well.
        """
        self._update_clipping()

    def _update_clipping(self):
        y = self.canvas.camera.location[1]
        self.canvas.camera.orthographic_clipping = (
            y - self._max_y.GetValue() - 1,
            y - self._min_y.GetValue() + 1,
        )

    def _ask_delete_chunks(self) -> Optional[bool]:
        class DeleteChunksDialog(wx.Dialog):
            def __init__(self, *args, **kwds):
                kwds["style"] = kwds.get("style", 0) | wx.NO_BORDER | wx.RESIZE_BORDER
                wx.Dialog.__init__(self, *args, **kwds)
                self.SetTitle("Do you want to load the original chunk state?")

                sizer_1 = wx.BoxSizer(wx.VERTICAL)

                label_1 = wx.StaticText(
                    self,
                    wx.ID_ANY,
                    "Do you want to load the original chunk state?\n\n"
                    'Clicking "Yes" will allow you to undo this operation but the operation will take a while to process.\n\n'
                    'Clicking "No" will mean this operation cannot be undone.\n\n'
                    "Changes will not be made to the world until you save so closing before saving will not actually delete the chunks.",
                    style=wx.ALIGN_CENTER_HORIZONTAL,
                )
                label_1.Wrap(500)
                sizer_1.Add(label_1, 0, wx.ALL, 5)

                sizer_2 = wx.StdDialogButtonSizer()
                sizer_1.Add(sizer_2, 0, wx.ALIGN_RIGHT | wx.ALL, 4)

                self.button_YES = wx.Button(self, wx.ID_YES, "")
                self.button_YES.SetDefault()
                sizer_2.AddButton(self.button_YES)

                self.button_NO = wx.Button(self, wx.ID_NO, "")
                self.button_NO.Bind(wx.EVT_BUTTON, self._on_no)
                sizer_2.AddButton(self.button_NO)

                self.button_CANCEL = wx.Button(self, wx.ID_CANCEL, "")
                sizer_2.AddButton(self.button_CANCEL)

                sizer_2.Realize()

                self.SetSizer(sizer_1)
                sizer_1.Fit(self)

                self.SetAffirmativeId(self.button_YES.GetId())
                self.SetEscapeId(self.button_CANCEL.GetId())

                self.Layout()
                apply_material3(self)

            def _on_no(self, evt):
                self.EndModal(wx.ID_NO)

        d = DeleteChunksDialog(self.canvas)
        d.CentreOnScreen()
        log.debug(f"Showing DeleteChunksDialog at {d.GetRect()}")
        response = d.ShowModal()
        if response == wx.ID_YES:
            return True
        elif response == wx.ID_NO:
            return False
        return None

    def _create_chunks(self, evt=None):
        def create_chunks(
            world: BaseLevel,
            dimension: Dimension,
            selection: SelectionGroup,
        ):
            for cx, cz in selection.chunk_locations():
                if not world.has_chunk(cx, cz, dimension):
                    world.put_chunk(Chunk(cx, cz), dimension)

        _log_failure(
            "Creating chunks",
            self.canvas.run_operation(
                lambda: create_chunks(
                    self.canvas.world,
                    self.canvas.dimension,
                    self.canvas.selection.selection_group,
                )
            ),
        )

    def _delete_chunks(self, evt=None):
        load_original = self._ask_delete_chunks()
        if load_original is not None:
            _log_failure(
                "Deleting chunks",
                self.canvas.run_operation(
                    lambda: delete_chunk(
                        self.canvas.world,
                        self.canvas.dimension,
                        self.canvas.selection.selection_group,
                        load_original,
                    )
                ),
            )

    def _prune_chunks(self, evt=None):
        load_original = self._ask_delete_chunks()
        if load_original is not None:
            _log_failure(
                "Pruning chunks",
                self.canvas.run_operation(
                    lambda: prune_chunks(
                        self.canvas.world,
                        self.canvas.dimension,
                        self.canvas.selection.selection_group,
                        load_original,
                    )
                ),
            )

    def _import_chunks(self, evt=None):
        def on_world_selected(path: str):
            destination_changed = False

            def operation() -> OperationReturnType:
                nonlocal destination_changed

                src_level = load_format(path)
                try:
                    src_level.open()
                    dimension = self.canvas.dimension

                    chunks = list(
                        self.canvas.selection.selection_group.chunk_locations()
                    )
                    count = len(chunks)

                    for i, (cx, cz) in enumerate(chunks):
                        try:
                            chunk = src_level.load_chunk(cx, cz, self.canvas.dimension)
                            chunk.changed = True
                            self.canvas.world.put_chunk(chunk, dimension)
                            destination_changed = True
                        except ChunkLoadError:
                            pass

                        yield (i + 1) / count
                finally:
                    src_level.close()

            _log_failure(
                "Importing chunks",
                self.canvas.run_operation(
                    operation, rollback_on_error=lambda: destination_changed
                ),
            )

        with WorldSelectDialog(self.canvas, on_world_selected) as select_world:
            select_world.CentreOnScreen()
            log.debug(f"Showing WorldSelectDialog at {select_world.GetRect()}")
            select_world.ShowModal()

    def _on_resize(self, evt):
        self._resize()
        evt.Skip()

    def _resize(self):
        panel_size = self._button_panel.GetBestSize()
        canvas_height = self.canvas.GetSize().GetHeight()
        allowed_canvas_height = canvas_height - 60
        ideal_path_height = panel_size.GetHeight()
        panel_height = min(ideal_path_height, allowed_canvas_height)
        panel_width = panel_size.GetWidth()
        if allowed_canvas_height < ideal_path_height:
            panel_width += wx.SystemSettings.GetMetric(wx.SYS_VSCROLL_X)
        self._button_panel.SetSize(
            wx.Rect(
                0, canvas_height // 2 - panel_height // 2, panel_width, panel_height
            )
        )
        self._button_panel.Layout()
        self._button_panel.Raise()
        self._button_panel.Refresh(False)

    def _draw(self):
        self.canvas.renderer.start_draw()
        if self.canvas.camera.projection_mode == Projection.PERSPECTIVE:
            self.canvas.renderer.draw_sky_box()
            glClear(GL_DEPTH_BUFFER_BIT)
        self.canvas.renderer.draw_level()
        if self.canvas.camera.projection_mode == Projection.PERSPECTIVE:
            self._selection.draw()
        else:
            depth_state = glGetBoolean(GL_DEPTH_TEST)
            if depth_state:
                glDisable(GL_DEPTH_TEST)
            clip = self.canvas.camera.orthographic_clipping
            self.canvas.camera.orthographic_clipping = -(10**5), 10**5
            self._selection.draw()
            self.canvas.camera.orthographic_clipping = clip
            if depth_state:
                glEnable(GL_DEPTH_TEST)
        self.canvas.mask_gl()
        self.canvas.renderer.end_draw()

    def windows(self) -> Iterable[wx.Window]:
        return [self._button_panel]
