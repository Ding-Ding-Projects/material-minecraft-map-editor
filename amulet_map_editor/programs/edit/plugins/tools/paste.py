import wx
from typing import TYPE_CHECKING, Tuple, Iterable
import logging
import math
import numpy
import weakref

from OpenGL.GL import (
    glClear,
    GL_DEPTH_BUFFER_BIT,
)

from amulet.api.data_types import PointCoordinates
from amulet.api.level import BaseLevel
from amulet.api.level.base_level.clone import PasteRule
from amulet.api.structure import structure_cache
from amulet.operations.paste import paste_iter
from amulet.utils.matrix import (
    rotation_matrix_xyz,
    decompose_transformation_matrix,
    scale_matrix,
    transform_matrix,
)

from amulet_map_editor import lang
from amulet_map_editor.api import image
from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.widgets import (
    Divider,
    SearchableChoice,
    StudioCheckBox,
)
from amulet_map_editor.api.wx.nonblocking import notify
from amulet_map_editor.api.opengl.camera import Projection, Camera
from amulet_map_editor.api.opengl.mesh.level import RenderLevel
from amulet_map_editor.programs.edit.api.key_config import (
    KeybindGroup,
)
from amulet_map_editor.programs.edit.api.operations import OperationSuccessful
from amulet_map_editor.programs.edit.api.ui.material_tool_panel import (
    IconButton,
    PANEL_PADDING,
    ToolPanel,
    TupleNumberField,
    panel_note,
    section_heading,
    tool_button,
)
from amulet_map_editor.programs.edit.api.ui.nudge_button import MaterialNudgeButton
from amulet_map_editor.programs.edit.api.ui.tool import DefaultBaseToolUI
from amulet_map_editor.programs.edit.api.behaviour import StaticSelectionBehaviour
from amulet_map_editor.programs.edit.api.behaviour.pointer_behaviour import (
    PointerBehaviour,
    EVT_POINT_CHANGE,
    PointChangeEvent,
)
from amulet_map_editor.programs.edit.api.events import (
    InputPressEvent,
    EVT_INPUT_PRESS,
)
from amulet_map_editor.programs.edit.api.key_config import ACT_BOX_CLICK

if TYPE_CHECKING:
    from amulet_map_editor.programs.edit.api.canvas import EditCanvas
    from amulet_map_editor.programs.edit.api.canvas.edit_canvas import OperationOutcome

log = logging.getLogger(__name__)

#: The narrowest a wrapped caption on the paste panel may be told to wrap at.
#:
#: A wrap width of zero or less means "do not wrap", so a measurement that came
#: back empty would silently produce the one thing the wrapping exists to
#: prevent -- a single long line that makes the whole panel as wide as the
#: sentence and pushes the viewport's controls off the canvas.
MIN_NOTE_WRAP = 160


def _control_width(control) -> int:
    """Return a sensible wrap width from a control, whether window or sizer.

    The coordinate inputs on this panel are windows now and answer
    ``GetBestSize``; they were ``wx.FlexGridSizer`` subclasses, and a sizer has
    no ``GetBestSize`` -- asking one for it raises ``AttributeError`` and takes
    the whole panel down with it, so the paste tool would not build at all.
    Both spellings are still tried because this helper is the panel's one
    measuring point and the next control added here may be either, and the
    floor still catches a control that cannot measure itself before layout has
    run.
    """
    for name in ("GetBestSize", "CalcMin"):
        method = getattr(control, name, None)
        if method is None:
            continue
        try:
            return max(MIN_NOTE_WRAP, int(method().GetWidth()))
        except Exception:  # noqa: BLE001 - a control that cannot measure itself
            continue
    return MIN_NOTE_WRAP


class _PasteRuleChoice(SearchableChoice):
    """The paste rule dropdown, answering the index its caller already asked for.

    ``SearchableChoice`` holds the chosen *option* rather than its position,
    which is the right shape for a searchable list and the wrong one for the
    mapping this tool has always used to pick a :class:`PasteRule`.  Answering
    ``GetSelection`` here keeps that mapping written against a position, so the
    rule the paste actually runs under did not have to be rewritten to change
    the control that chooses it.

    It is also narrower than the shell's default combo.  This panel floats over
    the world in a column beside it, and the design's 220 pixel field is most
    of what a reader can spare -- but not at the price of hiding which rule is
    chosen, so the ceiling is high enough for the longest of the three.
    """

    WIDTH = 200
    MAX_WIDTH = 280

    def GetSelection(self) -> int:  # noqa: N802 - wx API spelling
        """Return the position of the chosen option, or ``0`` for none."""
        try:
            return self.options.index(self.value)
        except ValueError:
            return 0


class MoveButton(MaterialNudgeButton):
    def __init__(
        self,
        parent: wx.Window,
        camera: Camera,
        keybinds: KeybindGroup,
        label: str,
        tooltip: str,
        paste_tool: "PasteTool",
    ):
        super().__init__(parent, camera, keybinds, label, tooltip)
        self._paste_tool = weakref.ref(paste_tool)

    def _move(self, offset: Tuple[int, int, int]):
        ox, oy, oz = offset
        x, y, z = self._paste_tool().location
        self._paste_tool().location = x + ox, y + oy, z + oz


class PasteTool(wx.BoxSizer, DefaultBaseToolUI):
    def __init__(self, canvas: "EditCanvas"):
        wx.BoxSizer.__init__(self, wx.HORIZONTAL)
        DefaultBaseToolUI.__init__(self, canvas)

        self._selection = StaticSelectionBehaviour(self.canvas)
        self._cursor = PointerBehaviour(self.canvas)
        self._moving = False
        self._is_enabled = False

        self._paste_panel = ToolPanel(canvas.GetParent(), "Paste tool options")
        self._paste_panel.Hide()
        self._paste_sizer = self._paste_panel.sizer
        pad = wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND
        pad_centre = wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.ALIGN_CENTER_HORIZONTAL

        def add_line():
            """Separate two blocks of controls with the shell's own rule."""
            self._paste_sizer.Add(Divider(self._paste_panel), 0, pad, PANEL_PADDING)

        def add_tick_box(name: str, tooltip: str, state: bool = True):
            tick = StudioCheckBox(self._paste_panel, label=name, value=state, name=name)
            tick.SetToolTip(tooltip)
            self._paste_sizer.Add(tick, 0, pad, PANEL_PADDING)
            return tick

        def add_label(name: str):
            self._paste_sizer.Add(
                section_heading(self._paste_panel, name), 0, pad, PANEL_PADDING
            )

        def add_note(name: str, wrap_at: int):
            """Add one wrapped sentence of explanation under a control.

            Wrapped at a width taken from the control it explains rather than
            left to size itself.  ``_resize`` gives this panel its own best
            size, so an unwrapped sentence would not be a caption under the
            boxes -- it would make the whole panel as wide as the sentence, and
            push the viewport's own controls off the edge of the canvas.
            """
            note = panel_note(self._paste_panel, name, wrap_at)
            self._paste_sizer.Add(note, 0, pad, PANEL_PADDING)
            return note

        self._paste_sizer.AddSpacer(PANEL_PADDING)
        add_label(lang.get("program_3d_edit.paste_tool.location_label"))
        self._location = TupleNumberField(
            self._paste_panel,
            (
                lang.get("program_3d_edit.paste_tool.location_x_label"),
                lang.get("program_3d_edit.paste_tool.location_y_label"),
                lang.get("program_3d_edit.paste_tool.location_z_label"),
            ),
            group="Location",
            tooltips=(
                lang.get("program_3d_edit.paste_tool.location_x_tooltip"),
                lang.get("program_3d_edit.paste_tool.location_y_tooltip"),
                lang.get("program_3d_edit.paste_tool.location_z_tooltip"),
            ),
            on_change=lambda _value: self._update_transform(),
            on_layout=self._resize,
        )
        self._paste_sizer.Add(self._location, 0, pad, PANEL_PADDING)
        # What these three boxes actually mean, said on the panel rather than
        # only in each box's hover tooltip.  The location is the CENTRE of the
        # structure -- ``paste_iter`` displaces it by
        # ``location - (min + max) // 2`` -- so a 4x1x4 slab sent to 8, 40, 8
        # fills 6, 40, 6 to 9, 40, 9, half a structure away from the numbers
        # that were typed.  A tooltip discloses that only to somebody who
        # already suspects it and hovers to check; the reader who types a
        # coordinate, confirms, walks over and finds bare stone is precisely
        # the reader who never hovered.
        self._location_note = add_note(
            lang.get("program_3d_edit.paste_tool.location_note"),
            _control_width(self._location),
        )

        self._move_button = MoveButton(
            self._paste_panel,
            self.canvas.camera,
            self.canvas.key_binds,
            lang.get("program_3d_edit.paste_tool.move_selection_label"),
            lang.get("program_3d_edit.paste_tool.move_selection_tooltip"),
            self,
        )
        self._paste_sizer.Add(self._move_button, 0, pad, PANEL_PADDING)

        add_line()

        add_label(lang.get("program_3d_edit.paste_tool.rotation_label"))
        self._free_rotation = StudioCheckBox(
            self._paste_panel,
            label=lang.get("program_3d_edit.paste_tool.free_rotation_label"),
            name=lang.get("program_3d_edit.paste_tool.free_rotation_label"),
        )
        self._free_rotation.SetToolTip(
            lang.get("program_3d_edit.paste_tool.free_rotation_tooltip")
        )
        self._paste_sizer.Add(self._free_rotation, 0, pad, PANEL_PADDING)

        self._rotation = TupleNumberField(
            self._paste_panel,
            (
                lang.get("program_3d_edit.paste_tool.rotation_x_label"),
                lang.get("program_3d_edit.paste_tool.rotation_y_label"),
                lang.get("program_3d_edit.paste_tool.rotation_z_label"),
            ),
            minimum=-180,
            maximum=180,
            increment=90,
            digits=2,
            wrap=True,
            snap=True,
            group="Rotation",
            tooltips=(
                lang.get("program_3d_edit.paste_tool.rotation_x_tooltip"),
                lang.get("program_3d_edit.paste_tool.rotation_y_tooltip"),
                lang.get("program_3d_edit.paste_tool.rotation_z_tooltip"),
            ),
            on_change=lambda _value: self._update_transform(),
            on_layout=self._resize,
        )
        self._paste_sizer.Add(self._rotation, 0, pad, PANEL_PADDING)
        self._free_rotation.Bind(wx.EVT_CHECKBOX, self._on_free_rotation_change)

        rotate_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._paste_sizer.Add(rotate_sizer, 0, pad_centre, PANEL_PADDING)

        self._rotate_left_button = IconButton(
            self._paste_panel,
            image.icon.tablericons.rotate_2.bitmap(),
            hint=lang.get("program_3d_edit.paste_tool.rotate_anti_clockwise_tooltip"),
            name="Rotate anti-clockwise",
            on_click=self._on_rotate_left,
        )
        rotate_sizer.Add(self._rotate_left_button)

        self._rotate_right_button = IconButton(
            self._paste_panel,
            image.icon.tablericons.rotate_clockwise_2.bitmap(),
            hint=lang.get("program_3d_edit.paste_tool.rotate_clockwise_tooltip"),
            name="Rotate clockwise",
            on_click=self._on_rotate_right,
        )
        rotate_sizer.Add(self._rotate_right_button, 0, wx.LEFT, tokens.scaled(6))

        add_line()

        add_label(lang.get("program_3d_edit.paste_tool.scale_label"))
        self._scale = TupleNumberField(
            self._paste_panel,
            (
                lang.get("program_3d_edit.paste_tool.scale_x_label"),
                lang.get("program_3d_edit.paste_tool.scale_y_label"),
                lang.get("program_3d_edit.paste_tool.scale_z_label"),
            ),
            start_value=1,
            digits=2,
            group="Scale",
            tooltips=(
                lang.get("program_3d_edit.paste_tool.scale_x_tooltip"),
                lang.get("program_3d_edit.paste_tool.scale_y_tooltip"),
                lang.get("program_3d_edit.paste_tool.scale_z_tooltip"),
            ),
            on_change=lambda _value: self._update_transform(),
            on_layout=self._resize,
        )
        self._paste_sizer.Add(self._scale, 0, pad, PANEL_PADDING)

        mirror_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._paste_sizer.Add(mirror_sizer, 0, pad_centre, PANEL_PADDING)

        # the tablericons file names are the wrong way around
        self._mirror_horizontal_button = IconButton(
            self._paste_panel,
            image.icon.tablericons.flip_vertical.bitmap(),
            hint=lang.get("program_3d_edit.paste_tool.mirror_horizontal_tooltip"),
            name="Mirror horizontally",
            on_click=self._on_mirror_horizontal,
        )
        mirror_sizer.Add(self._mirror_horizontal_button)

        self._mirror_vertical_button = IconButton(
            self._paste_panel,
            image.icon.tablericons.flip_horizontal.bitmap(),
            hint=lang.get("program_3d_edit.paste_tool.mirror_vertical_tooltip"),
            name="Mirror vertically",
            on_click=self._on_mirror_vertical,
        )
        mirror_sizer.Add(self._mirror_vertical_button, 0, wx.LEFT, tokens.scaled(6))

        add_line()

        self._copy_air = add_tick_box(
            lang.get("program_3d_edit.paste_tool.copy_air_label"),
            lang.get("program_3d_edit.paste_tool.copy_air_tooltip"),
        )
        self._copy_water = add_tick_box(
            lang.get("program_3d_edit.paste_tool.copy_water_label"),
            lang.get("program_3d_edit.paste_tool.copy_water_tooltip"),
        )
        self._copy_lava = add_tick_box(
            lang.get("program_3d_edit.paste_tool.copy_lava_label"),
            lang.get("program_3d_edit.paste_tool.copy_lava_tooltip"),
        )

        self._paste_rule_options = [
            lang.get("program_3d_edit.paste_tool.paste_all"),
            lang.get("program_3d_edit.paste_tool.paste_existing"),
            lang.get("program_3d_edit.paste_tool.paste_not_existing"),
        ]
        self._paste_rule = _PasteRuleChoice(
            self._paste_panel,
            lang.get("program_3d_edit.paste_tool.paste_rule_label"),
            self._paste_rule_options,
            self._paste_rule_options[0],
        )
        self._paste_sizer.Add(self._paste_rule, 0, pad, PANEL_PADDING)

        add_line()

        confirm_button = tool_button(
            self._paste_panel,
            lang.get("program_3d_edit.paste_tool.confirm_label"),
            tooltip=lang.get("program_3d_edit.paste_tool.confirm_tooltip"),
            variant="filled",
            on_click=self._paste_confirm,
        )
        self._paste_sizer.Add(confirm_button, 0, pad, PANEL_PADDING)

        self._paste_panel.Disable()
        self._resize()

    @property
    def name(self) -> str:
        return "Paste"

    def bind_events(self):
        super().bind_events()
        self._selection.bind_events()
        self._cursor.bind_events()
        self.canvas.Bind(EVT_POINT_CHANGE, self._on_pointer_change)
        self.canvas.Bind(EVT_INPUT_PRESS, self._on_input_press)
        self.canvas.Bind(wx.EVT_SIZE, self._on_resize)

    def enable(self):
        super().enable()
        self._move_button.enable()
        self._selection.update_selection()
        self._moving = False
        self._paste_panel.Show()
        self._resize()

    def set_state(self, state):
        if (
            isinstance(state, dict)
            and isinstance(state.get("structure"), BaseLevel)
            and isinstance(state.get("dimension"), str)
        ):
            structure = state["structure"]
            dimension = state["dimension"]
        elif structure_cache:
            structure, dimension = structure_cache.get_structure()
        else:
            notify(
                self,
                "Paste unavailable",
                "A structure needs to be copied before one can be pasted.",
                severity="warning",
            )
            return

        self._paste_panel.Enable()
        self._is_enabled = True
        self.canvas.renderer.fake_levels.clear()
        self.canvas.renderer.fake_levels.append(
            structure, dimension, (0, 0, 0), (1, 1, 1), (0, 0, 0)
        )
        self._moving = True

    def disable(self):
        super().disable()
        self._move_button.disable()
        self._paste_panel.Disable()
        self._is_enabled = False
        self.canvas.renderer.fake_levels.clear()
        self._paste_panel.Hide()

    @property
    def location(self) -> PointCoordinates:
        """The location as specified in the UI."""
        return self._location.value

    @location.setter
    def location(self, location: PointCoordinates):
        """Set the location value.
        Will update the UI and the renderer."""
        self._location.value = location
        self._update_transform()

    def _on_free_rotation_change(self, evt):
        if self._free_rotation.GetValue():
            self._rotation.increment = 1
        else:
            self._rotation.increment = 90

    def _on_rotate_left(self, evt=None):
        self._rotate(-90)

    def _on_rotate_right(self, evt=None):
        self._rotate(90)

    def _rotate(self, angle: int):
        """Rotate the floating selection by the angle based on the camera rotation."""
        angle = math.radians(angle)
        ry, rx = self.canvas.camera.rotation
        if rx < -45:
            rotation_change = rotation_matrix_xyz(0, angle, 0)
        elif -45 <= rx < 45:
            if -135 <= ry < -45:
                # east
                rotation_change = rotation_matrix_xyz(angle, 0, 0)
            elif -45 <= ry < 45:
                # south
                rotation_change = rotation_matrix_xyz(0, 0, angle)
            elif 45 <= ry < 135:
                # west
                rotation_change = rotation_matrix_xyz(-angle, 0, 0)
            else:
                # north
                rotation_change = rotation_matrix_xyz(0, 0, -angle)
        else:
            rotation_change = rotation_matrix_xyz(0, -angle, 0)

        self._rotation.value = numpy.rad2deg(
            decompose_transformation_matrix(
                numpy.matmul(
                    rotation_change, rotation_matrix_xyz(*self._rotation_radians())
                )
            )[1]
        )
        self._update_transform()

    def _rotation_radians(self) -> Tuple[float, float, float]:
        return tuple(math.radians(v) for v in self._rotation.value)

    def _on_mirror_vertical(self, evt=None):
        ry, rx = self.canvas.camera.rotation
        if -45 <= rx < 45:
            # looking north, east, south or west vertical mirror is always in y
            self._mirror(1)
        elif -135 <= ry < -45 or 45 <= ry < 135:
            # looking down or up facing east or west
            self._mirror(0)
        else:
            # looking down or up facing north or south
            self._mirror(2)

    def _on_mirror_horizontal(self, evt=None):
        ry, rx = self.canvas.camera.rotation
        if -135 <= ry < -45 or 45 <= ry < 135:
            # facing east or west
            self._mirror(2)
        else:
            # facing north or south
            self._mirror(0)

    def _mirror(self, axis: int):
        """Mirror the selection in the given axis.

        :param axis: The axis to scale in 0=x, 1=y, 2=z
        :return:
        """
        scale = [(-1, 1, 1), (1, -1, 1), (1, 1, -1)][axis]
        self._scale.value, rotation, _ = decompose_transformation_matrix(
            numpy.matmul(
                scale_matrix(*scale),
                transform_matrix(
                    self._scale.value, self._rotation_radians(), (0, 0, 0)
                ),
            )
        )
        self._rotation.value = numpy.rad2deg(rotation)
        self._update_transform()

    def _on_pointer_change(self, evt: PointChangeEvent):
        if self._is_enabled and self._moving:
            self.canvas.renderer.fake_levels.active_transform = (
                evt.point,
                self._scale.value,
                self._rotation_radians(),
            )
            self._location.value = evt.point
        evt.Skip()

    def _update_transform(self):
        """Update the renderer with the new values."""
        self.canvas.renderer.fake_levels.active_transform = (
            self._location.value,
            self._scale.value,
            self._rotation_radians(),
        )

    def _on_input_press(self, evt: InputPressEvent):
        if evt.action_id == ACT_BOX_CLICK:
            if self._is_enabled:
                self._moving = not self._moving
                if self._moving:
                    self.canvas.renderer.fake_levels.active_transform = (
                        self._location.value,
                        self._scale.value,
                        self._rotation_radians(),
                    )
        evt.Skip()

    def _paste_operation(self):
        if all(self._scale.value):
            fake_levels = self.canvas.renderer.fake_levels
            level_index: int = fake_levels.active_level_index
            if level_index is not None:
                render_level: RenderLevel = fake_levels.render_levels[level_index]
                paste_rule = {
                    1: PasteRule.PasteExist,
                    2: PasteRule.PasteNotExist,
                }.get(self._paste_rule.GetSelection(), PasteRule.PasteAll)
                yield from paste_iter(
                    self.canvas.world,
                    self.canvas.dimension,
                    render_level.level,
                    render_level.dimension,
                    self._location.value,
                    self._scale.value,
                    self._rotation.value,
                    self._copy_air.GetValue(),
                    self._copy_water.GetValue(),
                    self._copy_lava.GetValue(),
                    paste_rule,
                )
        else:
            raise OperationSuccessful(
                lang.get("program_3d_edit.paste_tool.zero_scale_message")
            )

    def _paste_confirm(self, evt=None):
        self.confirm_paste()

    def confirm_paste(self) -> "OperationOutcome":
        """Write the held structure into the world and say what happened.

        This returned ``None`` whether the paste landed or was contained, which
        is why ``editor_tools.confirm_pending`` had to infer the answer from the
        world's undo depth.  The depth check stays -- it is the only evidence
        available from a build whose paste tool predates this -- but a caller
        that gets an outcome here now gets the real reason instead of a guess.
        """
        return self.canvas.run_operation(self._paste_operation)

    def _on_resize(self, evt):
        self._resize()
        evt.Skip()

    def _resize(self):
        panel_size = self._paste_panel.GetBestSize()
        canvas_height = self.canvas.GetSize().GetHeight()
        allowed_canvas_height = canvas_height - 60
        ideal_path_height = panel_size.GetHeight()
        panel_height = min(ideal_path_height, allowed_canvas_height)
        panel_width = panel_size.GetWidth()
        if allowed_canvas_height < ideal_path_height:
            panel_width += wx.SystemSettings.GetMetric(wx.SYS_VSCROLL_X)
        self._paste_panel.SetSize(
            wx.Rect(
                0, canvas_height // 2 - panel_height // 2, panel_width, panel_height
            )
        )
        self._paste_panel.Layout()
        self._paste_panel.Raise()
        self._paste_panel.Refresh(False)

    def _draw(self):
        self.canvas.renderer.start_draw()
        if self.canvas.camera.projection_mode == Projection.PERSPECTIVE:
            self.canvas.renderer.draw_sky_box()
            glClear(GL_DEPTH_BUFFER_BIT)
        self.canvas.renderer.draw_level()
        self.canvas.renderer.draw_fake_levels()
        self._selection.draw()
        self.canvas.mask_gl()
        self.canvas.renderer.end_draw()

    def windows(self) -> Iterable[wx.Window]:
        return [self._paste_panel]
