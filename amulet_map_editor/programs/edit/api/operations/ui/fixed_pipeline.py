"""The plugin-declared options panel, in Material rather than native controls.

A stock or third-party plugin never writes wx itself here: it hands
:class:`FixedFunctionUI` a dictionary describing each option -- a bool, an
int, a string choice, a path -- and this file is the one place that turns
that description into an actual control.  Converting it is therefore not one
panel's worth of Material coverage; it is every plugin's options panel at
once, because every one of them is built from the same ten option types this
file knows how to draw.

Behaviour is preserved exactly: the same option types, the same defaults, the
same bounds, the same ``_get_values()`` shape handed back to the operation.
What changes is only which control draws each type -- a Studio widget that
paints through ``render_to`` rather than a native control that photographs
blank on a desktop nobody is looking at.
"""

import wx
from typing import Callable, Dict, Any, TYPE_CHECKING, Sequence
import logging
import inspect

from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.widgets import (
    PathField,
    StudioButton,
    StudioCheckBox,
    StudioText,
)
from amulet_map_editor.api.wx.ui.material_forms import MaterialChoice, MaterialTextField
from amulet_map_editor.programs.edit.api.ui.material_tool_panel import NumberField

from amulet.api.data_types import OperationReturnType
from amulet_map_editor.programs.edit.api.operations import DefaultOperationUI

if TYPE_CHECKING:
    from amulet_map_editor.programs.edit.api.canvas import EditCanvas
    from amulet.api.level import BaseLevel

log = logging.getLogger(__name__)

FixedOperationType = Callable[
    ["BaseLevel", "Dimension", "SelectionGroup", Dict[str, Any]], OperationReturnType
]

#: Space between one option's row and the next.  An M3 field is taller and
#: airier than the native control it replaces, so the rows want more room
#: between them than the original's 5 design pixels or the column reads as one
#: solid block rather than a list of separate settings.
ROW_GAP = 10

#: The number types this panel draws with a :class:`NumberField`, and how many
#: decimal places each shows.  ``int`` shows none -- ``NumberField`` rounds to
#: a whole number whenever ``digits`` is zero -- and ``float`` shows two,
#: which is a display choice only: the value handed back is never rounded to
#: it, exactly as ``wx.SpinCtrlDouble`` never rounded what ``GetValue`` returned.
_NUMBER_DIGITS = {"int": 0, "float": 2}


class FixedFunctionUI(wx.Panel, DefaultOperationUI):
    def __init__(
        self,
        parent: wx.Window,
        canvas: "EditCanvas",
        world: "BaseLevel",
        options_path: str,
        operation: FixedOperationType,
        options: Dict[str, Any],
    ):
        wx.Panel.__init__(self, parent)
        DefaultOperationUI.__init__(self, parent, canvas, world, options_path)
        self._operation = operation

        self.Hide()
        # Match the host's own surface rather than the system button face a
        # bare wx.Panel defaults to, so this panel of Material controls does
        # not sit inside a stray grey rectangle inside an already-Material host.
        backdrop = parent.GetBackgroundColour()
        if backdrop.IsOk():
            self.SetBackgroundColour(backdrop)
        self._sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self._sizer)
        self._options_sizer = wx.BoxSizer(wx.VERTICAL)
        self._sizer.Add(self._options_sizer, 0, wx.EXPAND)
        self._run_button = StudioButton(
            self, "Run Operation", variant="filled", name="Run Operation"
        )
        self._run_button.Bind(wx.EVT_BUTTON, self._run_operation)
        self._sizer.Add(
            self._run_button,
            0,
            wx.ALL | wx.ALIGN_CENTRE_HORIZONTAL,
            tokens.scaled(ROW_GAP),
        )

        self._options: Dict[str, wx.Window] = {}
        self._create_options(options)

        self.Layout()
        self.Show()

    def _create_options(self, options: Dict[str, Sequence]):
        create_functions: Dict[str, Callable[[str, Sequence], None]] = {
            "label": self._create_label,
            "bool": self._create_bool,
            "int": self._create_int,
            "float": self._create_float,
            "str": self._create_string,
            "str_choice": self._create_str_choice,
            "file_open": self._create_file_open_picker,
            "file_save": self._create_file_save_picker,
            "directory": self._create_directory_picker,
            "button": self._create_button,
        }
        for option_name, args in options.items():
            try:
                option_type, *args = args
                if option_type not in create_functions:
                    raise ValueError(f"Invalid option type {option_type}")
                create_functions[option_type](option_name, *args)
            except Exception as e:
                log.exception(e)

    def _add_row(self, window: wx.Window) -> None:
        """Add one option's own control as a row, spaced from its neighbours.

        Every Material control drawn here already carries its own label --
        the checkbox's label beside its box, the floating label notched into
        a field's outline, the caption above a number field -- so unlike the
        native controls this replaces, a row needs no separate caption of its
        own next to it.
        """
        self._options_sizer.Add(
            window,
            0,
            wx.ALL | wx.ALIGN_CENTRE_HORIZONTAL,
            tokens.scaled(ROW_GAP),
        )

    def _create_label(self, option_name: str):
        self._add_row(
            StudioText(
                self, option_name, size_px=13, role="on_surface", name=option_name
            )
        )

    def _create_bool(self, option_name: str, value: bool = False):
        if not isinstance(value, bool):
            raise TypeError("value must be a bool")
        option = StudioCheckBox(self, label=option_name, value=value, name=option_name)
        self._add_row(option)
        self._options[option_name] = option

    def _create_number(
        self, option_name: str, kind: str, initial, min_val, max_val
    ) -> None:
        option = NumberField(
            self,
            option_name,
            initial,
            min_val,
            max_val,
            digits=_NUMBER_DIGITS[kind],
            on_layout=self._relayout,
        )
        self._add_row(option)
        self._options[option_name] = option

    def _create_int(
        self, option_name: str, initial=0, min_val=-30_000_000, max_val=30_000_000
    ):
        if not (
            isinstance(initial, int)
            and isinstance(min_val, int)
            and isinstance(max_val, int)
        ):
            raise TypeError("Input value must be int")
        self._create_number(option_name, "int", initial, min_val, max_val)

    def _create_float(
        self, option_name: str, initial=0, min_val=-30_000_000, max_val=30_000_000
    ):
        if not (
            isinstance(initial, (int, float))
            and isinstance(min_val, (int, float))
            and isinstance(max_val, (int, float))
        ):
            raise TypeError("Input value must be int or float")
        self._create_number(option_name, "float", initial, min_val, max_val)

    def _create_string(self, option_name: str, value: str = ""):
        if not isinstance(value, str):
            raise TypeError("value must be a string")
        option = MaterialTextField(self, option_name, value, name=option_name)
        self._add_row(option)
        self._options[option_name] = option

    def _create_str_choice(self, option_name: str, *choices: str):
        if not (choices and all(isinstance(o, str) for o in choices)):
            return
        option = MaterialChoice(
            self, choices, label=option_name, name=option_name, value=choices[0]
        )
        self._add_row(option)
        self._options[option_name] = option

    def _create_path_picker(self, option_name: str, path: str, mode: str) -> None:
        if not isinstance(path, str):
            raise TypeError("path must be a string")
        option = PathField(self, option_name, path, mode=mode)
        self._add_row(option)
        self._options[option_name] = option

    def _create_file_save_picker(self, option_name: str, path: str = ""):
        self._create_path_picker(option_name, path, "save_file")

    def _create_file_open_picker(self, option_name: str, path: str = ""):
        self._create_path_picker(option_name, path, "file")

    def _create_directory_picker(self, option_name: str, path: str = ""):
        self._create_path_picker(option_name, path, "folder")

    def _create_button(
        self,
        option_name: str,
        button_name: str = "",
        callback: Callable[[], Any] = lambda: None,
    ):
        if not isinstance(button_name, str):
            raise TypeError("button_name must be a string")
        if inspect.signature(callback).parameters:
            raise TypeError("callback does not take any arguments")
        button = StudioButton(
            self,
            button_name,
            variant="tonal",
            on_click=callback,
            name=button_name or option_name,
        )
        self._add_row(button)

    def _relayout(self) -> None:
        """Re-run this panel's own layout after a control's size has changed.

        A :class:`NumberField` grows by one line when it shows a refused-value
        message underneath itself; without this the panel keeps the row
        height it had before that message appeared, and the message it just
        asked to show would be clipped rather than read.  The host that
        floats this panel over the canvas re-measures it independently once
        the operation is set up, and the Material tool column it sits inside
        scrolls rather than clips when its content outgrows it, so a message
        that arrives after that point stays reachable even if the floating
        window itself does not immediately grow to meet it.
        """
        self.Layout()
        self.InvalidateBestSize()
        parent = self.GetParent()
        if parent is not None:
            parent.Layout()

    def _get_values(self) -> Dict[str, Any]:
        options = {}
        for key, window in self._options.items():
            if isinstance(
                window,
                (
                    StudioCheckBox,
                    NumberField,
                    MaterialTextField,
                ),
            ):
                options[key] = window.GetValue()
            elif isinstance(window, MaterialChoice):
                options[key] = window.GetString(window.GetSelection())
            elif isinstance(window, PathField):
                options[key] = window.value()
        return options

    def _run_operation(self, evt):
        """Run the operation and return its outcome; see ``SimpleOperationPanel``."""
        return self.canvas.run_operation(
            lambda: self._operation(
                self.world,
                self.canvas.dimension,
                self.canvas.selection.selection_group,
                self._get_values(),
            )
        )
