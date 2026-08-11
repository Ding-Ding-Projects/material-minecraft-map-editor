from typing import TYPE_CHECKING
from math import floor, log10
import logging

import wx

from amulet_map_editor.programs.edit.api.edit_canvas_container import (
    EditCanvasContainer,
)
from amulet_map_editor.api.studio import tokens, widgets
from amulet_map_editor.programs.edit.api.events import (
    EVT_CAMERA_MOVED,
    EVT_SPEED_CHANGED,
    EVT_UNDO,
    EVT_REDO,
    EVT_CREATE_UNDO,
    EVT_SAVE,
    EVT_PROJECTION_CHANGED,
    EVT_DIMENSION_CHANGE,
    DimensionChangeEvent,
    EditCloseEvent,
)
from amulet_map_editor.api import lang
from amulet_map_editor.api.opengl.camera import Projection
from amulet_map_editor.api.wx.material3 import apply_material3

if TYPE_CHECKING:
    from amulet_map_editor.programs.edit.api.canvas import EditCanvas

log = logging.getLogger(__name__)

#: The glyphs the toolbar draws, taken from the Studio ribbon's own vocabulary
#: rather than from a bitmap set.  Two reasons, and the second is the load
#: bearing one: the ribbon already spells undo, redo and save exactly this way,
#: so a user meets one iconography instead of two; and the toolbar is drawn on a
#: dark scrim, where the dark-stroke bitmaps these buttons used to carry are
#: very nearly invisible.
UNDO_GLYPH = "↶"
REDO_GLYPH = "↷"
SAVE_GLYPH = "▣"
CLOSE_GLYPH = "✕"
GOTO_GLYPH = "⌖"

#: Gap between two controls on the bar, and the room left inside the bar's own
#: rounded surface, both in design pixels.
CONTROL_GAP = 3
BAR_PADDING = 5

#: The version readout's own padding, deliberately tighter than the toolbar's.
#: It is pinned to the top-left corner of the view, where the heads-up readout
#: chips also start, so every pixel it grows is a pixel of overlap with them.
VERSION_PADDING = 2


def _format_float(num: float) -> str:
    if num < 100:
        return f"{num:.0{max(0, 2 - floor(log10(num)))}f}".rstrip("0").rstrip(".")
    else:
        return f"{num:.0f}"


class FilePanel(EditCanvasContainer):
    """The world toolbar floating at the top of the 3D view.

    Every control here is a Studio widget drawn on a scrim
    :class:`~amulet_map_editor.api.studio.widgets.OverlayBar`, so the row
    belongs with the heads-up chips beneath it rather than sitting above them
    as a strip of the platform's own chrome.  What each control *does* is
    unchanged from the native row it replaces, down to the tooltips: this is a
    change of appearance, keyboard reach and accessible naming, not of
    behaviour.
    """

    def __init__(self, canvas: "EditCanvas"):
        super().__init__(canvas)

        level = self.canvas.world
        gap = tokens.scaled(CONTROL_GAP)
        padding = tokens.scaled(widgets.OverlayBar.MARGIN + BAR_PADDING)
        version_padding = tokens.scaled(widgets.OverlayBar.MARGIN + VERSION_PADDING)

        version = f"{level.level_wrapper.platform}, {level.level_wrapper.version}"
        self._version_panel = widgets.OverlayBar(
            canvas.GetParent(),
            name=lang.get("program_3d_edit.file_ui.version_name"),
        )
        self._version_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._version_panel.SetSizer(self._version_sizer)
        self._version_text = widgets.OverlayText(
            self._version_panel,
            version,
            size_px=11,
            line_height=1.0,
            mono=True,
            name=f"{lang.get('program_3d_edit.file_ui.version_name')}: {version}",
            hint=lang.get("program_3d_edit.file_ui.version_tooltip"),
        )
        self._version_sizer.Add(
            self._version_text, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, version_padding
        )
        # The bar carries it too: the text does not fill the surface, and a
        # tooltip that only answers over the glyphs is one most people never
        # find.
        self._version_panel.SetToolTip(
            lang.get("program_3d_edit.file_ui.version_tooltip")
        )

        self._button_window = widgets.OverlayBar(
            canvas.GetParent(),
            name=lang.get("program_3d_edit.file_ui.toolbar_name"),
        )
        self._button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        outer = wx.BoxSizer(wx.HORIZONTAL)
        outer.Add(self._button_sizer, 1, wx.EXPAND | wx.ALL, padding)
        self._button_window.SetSizer(outer)

        def add(control: wx.Window) -> None:
            self._button_sizer.Add(
                control,
                0,
                wx.ALIGN_CENTER_VERTICAL
                | (wx.LEFT if self._button_sizer.GetChildren() else 0),
                gap,
            )

        projection_hint = lang.get("program_3d_edit.file_ui.projection_tooltip")
        self._projection_button = widgets.OverlayButton(
            self._button_window,
            "3D",
            hint=projection_hint,
            name=f"{projection_hint}: 3D",
            on_click=self._toggle_projection,
        )
        add(self._projection_button)

        location = ", ".join(f"{s:.2f}" for s in self.canvas.camera.location)
        self._location_hint = lang.get("program_3d_edit.file_ui.location_tooltip")
        self._location_button = widgets.OverlayButton(
            self._button_window,
            location,
            glyph=GOTO_GLYPH,
            hint=self._location_hint,
            name=f"{self._location_hint}: {location}",
            on_click=lambda: self.canvas.goto(),
        )
        add(self._location_button)

        def set_speed() -> None:
            dialog = SpeedSelectDialog(
                canvas, self.canvas.camera.move_speed * 1000 / 33
            )
            dialog.CentreOnScreen()
            log.debug(f"Showing SpeedSelectDialog at {dialog.GetRect()}")
            if dialog.ShowModal() == wx.ID_OK:
                self.canvas.camera.move_speed = dialog.speed * 33 / 1000

        speed = self._speed_label()
        self._speed_hint = lang.get("program_3d_edit.file_ui.speed_tooltip")
        self._speed_button = widgets.OverlayButton(
            self._button_window,
            speed,
            hint=self._speed_hint,
            name=f"{self._speed_hint}: {speed}",
            on_click=set_speed,
        )
        add(self._speed_button)

        self._dim_options = widgets.OverlayChoice(
            self._button_window,
            lang.get("program_3d_edit.file_ui.dim_label"),
            self._dimension_names(level),
            on_change=self._on_dimension_chosen,
            hint=lang.get("program_3d_edit.file_ui.dim_tooltip"),
        )
        self._set_dimension(canvas.dimension)
        add(self._dim_options)

        def create_button(glyph: str, key: str, operation) -> widgets.OverlayButton:
            hint = lang.get(f"program_3d_edit.file_ui.{key}_tooltip")
            button = widgets.OverlayButton(
                self._button_window,
                "",
                glyph=glyph,
                hint=hint,
                name=hint,
                on_click=operation,
            )
            add(button)
            return button

        self._undo_button = create_button(UNDO_GLYPH, "undo", self.canvas.undo)
        self._redo_button = create_button(REDO_GLYPH, "redo", self.canvas.redo)
        self._save_button = create_button(SAVE_GLYPH, "save", self.canvas.save)
        self._close_button = create_button(
            CLOSE_GLYPH,
            "close",
            lambda: wx.PostEvent(self.canvas, EditCloseEvent()),
        )

        self._update_buttons()

        self._resize()

    # -- readings ------------------------------------------------------------
    @staticmethod
    def _dimension_names(level) -> list[str]:
        """Return the world's dimensions, named and ordered as the row shows them.

        Sorted and stripped because the control this replaces sorted and
        stripped them, and a dimension list that reorders itself under a user
        who has learned where "the nether" sits is a change of behaviour even
        though every entry is still present.
        """
        return sorted(
            str(dimension).strip() for dimension in level.level_wrapper.dimensions
        )

    def _speed_label(self) -> str:
        return (
            f"{_format_float(self.canvas.camera.move_speed * 1000 / 33)} "
            f"{lang.get('program_3d_edit.file_ui.speed_blocks_per_second')}"
        )

    def bind_events(self):
        self.canvas.Bind(EVT_CAMERA_MOVED, self._on_camera_move)
        self.canvas.Bind(EVT_SPEED_CHANGED, self._on_speed_change)
        self.canvas.Bind(EVT_UNDO, self._on_update_buttons)
        self.canvas.Bind(EVT_REDO, self._on_update_buttons)
        self.canvas.Bind(EVT_SAVE, self._on_update_buttons)
        self.canvas.Bind(EVT_CREATE_UNDO, self._on_update_buttons)
        self.canvas.Bind(EVT_PROJECTION_CHANGED, self._on_projection_change)
        self.canvas.Bind(EVT_DIMENSION_CHANGE, self._change_dimension)
        self.canvas.Bind(wx.EVT_SIZE, self._on_resize)

    def _on_update_buttons(self, evt):
        self._update_buttons()
        evt.Skip()

    def _relabel(self, button, label: str, hint: str) -> bool:
        """Give ``button`` a new reading, and say so in its accessible name.

        The label on these buttons is a *number* -- how many undos are left,
        how many changes are unsaved -- so letting the accessible name follow
        it would introduce the control to a screen reader as "0", and then as
        "1", and make it a different control every time the count moved.  The
        name is the action plus the reading; the tooltip stays the action.

        Returns whether anything changed, so a caller can lay the row out again
        only when it has to: this runs on every camera movement.
        """
        if button.GetLabel() == label:
            return False
        button.SetLabel(label)
        button.SetName(f"{hint}: {label}")
        return True

    def _update_buttons(self):
        history = self.canvas.world.history_manager
        changed = self._relabel(
            self._undo_button,
            f"{history.undo_count}",
            lang.get("program_3d_edit.file_ui.undo_tooltip"),
        )
        changed |= self._relabel(
            self._redo_button,
            f"{history.redo_count}",
            lang.get("program_3d_edit.file_ui.redo_tooltip"),
        )
        changed |= self._relabel(
            self._save_button,
            f"{history.unsaved_changes}",
            lang.get("program_3d_edit.file_ui.save_tooltip"),
        )
        if changed:
            # A count that grows from 9 to 10 needs a wider button, and the row
            # is only as wide as its last layout made it.
            self._resize()

    def _on_dimension_chosen(self, dimension: str) -> None:
        """Run when the dimension is chosen by the user in the toolbar."""
        if dimension:
            self.canvas.dimension = dimension
        self._resize()

    def _on_projection_change(self, evt):
        if self.canvas.camera.projection_mode == Projection.PERSPECTIVE:
            self._set_projection_label("3D")
        elif self.canvas.camera.projection_mode == Projection.TOP_DOWN:
            self._set_projection_label("2D")
        evt.Skip()

    def _set_projection_label(self, label: str) -> None:
        hint = lang.get("program_3d_edit.file_ui.projection_tooltip")
        self._projection_button.SetLabel(label)
        self._projection_button.SetName(f"{hint}: {label}")

    def _toggle_projection(self) -> None:
        if self.canvas.camera.projection_mode == Projection.PERSPECTIVE:
            self.canvas.camera.projection_mode = Projection.TOP_DOWN
        else:
            self.canvas.camera.projection_mode = Projection.PERSPECTIVE

    def _change_dimension(self, evt: DimensionChangeEvent):
        """Run when the dimension attribute in the canvas is changed.
        This is run when the user changes the attribute and when it is changed manually in code.
        """
        self._set_dimension(evt.dimension)

    def _set_dimension(self, dimension: str) -> None:
        """Show ``dimension`` without running the change callback.

        The guard is the one the native choice had: a dimension the world does
        not offer is ignored rather than shown, and setting the one already
        shown does nothing at all -- which is what keeps the canvas telling the
        toolbar and the toolbar telling the canvas from becoming a loop.
        """
        name = str(dimension)
        if name in self._dim_options.options and name != self._dim_options.value:
            self._dim_options.set_value(name)
            self._resize()

    def _on_camera_move(self, evt):
        x, y, z = evt.camera_location
        label = f"{x:.2f}, {y:.2f}, {z:.2f}"
        old_label = self._location_button.GetLabel()
        if self._relabel(self._location_button, label, self._location_hint):
            if len(label) != len(old_label):
                self._resize()
        evt.Skip()

    def _on_speed_change(self, evt):
        label = self._speed_label()
        old_label = self._speed_button.GetLabel()
        if self._relabel(self._speed_button, label, self._speed_hint):
            if len(label) != len(old_label):
                self._resize()
        evt.Skip()

    def _on_resize(self, evt) -> None:
        self._resize()
        evt.Skip()

    def _resize(self) -> None:
        version_text_size = self._version_panel.GetBestSize()
        self._version_panel.SetSize(
            wx.Rect(0, 0, version_text_size.GetWidth(), version_text_size.GetHeight())
        )
        self._version_panel.Raise()

        self._button_window.Layout()
        window_size = self._button_window.GetBestSize()
        canvas_size = self.canvas.GetSize()
        self._button_window.SetSize(
            wx.Rect(
                max(0, canvas_size.GetWidth() - window_size.GetWidth()),
                0,
                window_size.GetWidth(),
                window_size.GetHeight(),
            )
        )
        self._button_window.Raise()
        self._button_window.Refresh(False)

    def windows(self) -> list[wx.Window]:
        return [self._version_panel, self._button_window]


class SpeedSelectDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, speed: float):
        wx.Dialog.__init__(self, parent, style=wx.NO_BORDER | wx.RESIZE_BORDER)
        self.SetTitle(lang.get("program_3d_edit.file_ui.speed_dialog_name"))

        sizer = wx.BoxSizer(wx.VERTICAL)

        self._speed_spin_ctrl_double = wx.SpinCtrlDouble(
            self, wx.ID_ANY, initial=speed, min=0.0, max=1_000_000_000.0
        )
        self._speed_spin_ctrl_double.SetToolTip(
            lang.get("program_3d_edit.file_ui.speed_tooltip")
        )

        def on_mouse_wheel(evt: wx.MouseEvent):
            if evt.GetWheelRotation() > 0:
                self._speed_spin_ctrl_double.SetValue(
                    self._speed_spin_ctrl_double.GetValue()
                    + self._speed_spin_ctrl_double.GetIncrement()
                )
            else:
                self._speed_spin_ctrl_double.SetValue(
                    self._speed_spin_ctrl_double.GetValue()
                    - self._speed_spin_ctrl_double.GetIncrement()
                )

        self._speed_spin_ctrl_double.Bind(wx.EVT_MOUSEWHEEL, on_mouse_wheel)
        self._speed_spin_ctrl_double.SetIncrement(1.0)
        self._speed_spin_ctrl_double.SetDigits(4)
        sizer.Add(self._speed_spin_ctrl_double)

        button_sizer = wx.StdDialogButtonSizer()
        sizer.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 4)

        self._button_ok = wx.Button(self, wx.ID_OK, "")
        self._button_ok.SetDefault()
        button_sizer.AddButton(self._button_ok)

        self._button_cancel = wx.Button(self, wx.ID_CANCEL, "")
        button_sizer.AddButton(self._button_cancel)

        button_sizer.Realize()

        self.SetSizer(sizer)
        sizer.Fit(self)

        self.SetAffirmativeId(self._button_ok.GetId())
        self.SetEscapeId(self._button_cancel.GetId())

        self.Layout()
        apply_material3(self)

    @property
    def speed(self) -> float:
        return self._speed_spin_ctrl_double.GetValue()
