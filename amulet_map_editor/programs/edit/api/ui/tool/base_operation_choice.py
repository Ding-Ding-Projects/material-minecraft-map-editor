import wx
from collections.abc import Mapping
from typing import TYPE_CHECKING, Optional, Iterable, Tuple
import traceback
import logging

import os
import sys
import subprocess
from amulet_map_editor.api import process

from amulet_map_editor.api import image
from amulet_map_editor.api.wx.ui.simple import SimpleChoiceAny
from amulet_map_editor.api.wx.nonblocking import notify, notify_exception

from amulet_map_editor.programs.edit.api.operations import OperationUIType
from amulet_map_editor.programs.edit.api.operations.manager import UIOperationManager
from .base_tool_ui import BaseToolUI

if TYPE_CHECKING:
    from amulet_map_editor.programs.edit.api.canvas import EditCanvas

log = logging.getLogger(__name__)


class BaseOperationChoiceToolUI(wx.BoxSizer, BaseToolUI):
    OperationGroupName = None
    _active_operation: Optional[OperationUIType]

    ShowOpenFolder = True

    def __init__(self, canvas: "EditCanvas"):
        wx.BoxSizer.__init__(self, wx.VERTICAL)
        BaseToolUI.__init__(self, canvas)

        self._active_operation: Optional[OperationUIType] = None
        self._last_active_operation_id: Optional[str] = None

        self._settings_panel = wx.Panel(canvas.GetParent())
        self._settings_panel.SetBackgroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE)
        )
        self._settings_panel.Hide()
        self._settings_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._settings_panel.SetSizer(self._settings_sizer)

        self._operation_panel = wx.Panel(canvas.GetParent())
        self._operation_panel.SetBackgroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE)
        )
        self._operation_panel.Hide()
        self._operation_sizer = wx.BoxSizer(wx.VERTICAL)
        self._operation_panel.SetSizer(self._operation_sizer)

        assert isinstance(
            self.OperationGroupName, str
        ), "OperationGroupName has not been set or is not a string."
        # The operation selection
        self._operation_choice = SimpleChoiceAny(self._settings_panel)
        self._settings_sizer.Add(self._operation_choice)
        self._operations = UIOperationManager(self.OperationGroupName)
        self._operation_choice.SetItems(
            {op.identifier: op.name for op in self._operations.operations}
        )
        self._operation_choice.Bind(wx.EVT_CHOICE, self._on_operation_change)

        # The reload button
        self._reload_operation = wx.BitmapButton(
            self._settings_panel, bitmap=image.REFRESH_ICON.bitmap(16, 16)
        )
        self._reload_operation.SetToolTip("Reload Operations")
        self._settings_sizer.Add(self._reload_operation)
        self._reload_operation.Bind(wx.EVT_BUTTON, self._on_reload_operations)

        # The open folder button
        if self.ShowOpenFolder:
            self._open_folder = wx.BitmapButton(
                self._settings_panel, bitmap=image.TABLERICONS.folder.bitmap(16, 16)
            )
            self._open_folder.SetToolTip("Open Plugin Folder")
            self._settings_sizer.Add(self._open_folder)
            self._open_folder.Bind(wx.EVT_BUTTON, self._on_open_folder)

        self._resize()

    def windows(self) -> Iterable[wx.Window]:
        return [self._settings_panel, self._operation_panel]

    @property
    def name(self) -> str:
        """The name of the group of operations."""
        raise NotImplementedError

    @property
    def active_operation_id(self) -> str:
        """The identifier of the operation selected by the choice input.
        Note if in the process of changing this may be different to self._active_operation.
        """
        return self._operation_choice.GetCurrentObject()

    @property
    def active_operation_name(self) -> str:
        """The name of the operation the chooser is showing, or ``""``.

        The name rather than the identifier, because the identifier is a module
        path: it is what the code keys on and it is not what the user picked
        from the list.
        """
        return str(self._operation_choice.GetStringSelection() or "")

    @property
    def operation_names(self) -> Tuple[str, ...]:
        """Every operation the chooser is currently offering, in its own order.

        Read from the chooser rather than from the loader behind it, because
        this is what a caller reporting on a reload needs to say: an operation
        that loaded but never reached the list is one the user cannot pick.
        """
        return tuple(str(name) for name in self._operation_choice.GetStrings())

    @staticmethod
    def _match_key(value: str) -> str:
        """Return the form two operation names are compared in.

        ``Set Biome`` is the plugin's own spelling and ``Set biome`` is the one
        on the tile that asks for it.  Comparing them exactly would make the
        request silently miss, so case and surrounding space are dropped before
        the comparison rather than either spelling being declared the right one.
        """
        return " ".join(str(value or "").split()).casefold()

    def operation_id_for(self, wanted: str) -> Optional[str]:
        """Return the identifier of the operation named ``wanted``, or ``None``.

        Both the identifier and the visible name are accepted: a caller inside
        this package already holds the identifier, and a caller outside it knows
        only the name the user sees.
        """
        text = str(wanted or "").strip()
        if not text:
            return None
        if text in self._operation_choice.values:
            return text
        target = self._match_key(text)
        for name, identifier in self._operation_choice.items:
            if self._match_key(name) == target:
                return identifier
        return None

    def set_state(self, state):
        """Select the operation this tool was asked to start on.

        The tool manager hands this whatever posted the tool change, which is
        how one tool bounces to another with more than a bare start.  A tile
        that names an operation therefore arrives on that operation instead of
        on whichever one the list happened to sort first -- which for this
        chooser is alphabetical, so the first entry was never a decision
        anybody made.

        ``state`` may be the operation's name, its identifier, or a mapping
        carrying either under ``operation``.  Anything else is left alone: the
        tool has already started, and a state it does not understand is not a
        reason to unselect what the user was working on.
        """
        wanted = ""
        if isinstance(state, str):
            wanted = state
        elif isinstance(state, Mapping):
            value = state.get("operation")
            if isinstance(value, str):
                wanted = value
        if not wanted.strip():
            return

        identifier = self.operation_id_for(wanted)
        if identifier is None:
            log.warning(
                "No operation named %r is installed in the %r group",
                wanted,
                self.OperationGroupName,
            )
            notify(
                self.canvas,
                f"{wanted} is not installed",
                f"No operation named “{wanted}” was found in this build, so the "
                f"{self.name} tool is showing "
                f"{self.active_operation_name or 'nothing'} instead.",
                severity="warning",
            )
            return

        identifiers = self._operation_choice.values
        self._operation_choice.SetSelection(identifiers.index(identifier))
        if identifier != self._last_active_operation_id:
            self._setup_operation()
            self.canvas.reset_bound_events()
        self._resize()

    def _on_operation_change(self, evt):
        """Run when the operation selection changes."""
        if (
            self.active_operation_id
            and self._last_active_operation_id != self.active_operation_id
        ):
            self._setup_operation()
            self.canvas.reset_bound_events()
            self._resize()
        evt.Skip()

    def _setup_operation(self):
        """Remove the old operation and create the UI for the new operation."""
        operation_path = self.active_operation_id
        if operation_path:
            # only reload the operation if the
            operation = self._operations[operation_path]
            self._operation_panel.Freeze()
            try:
                if self._active_operation is not None:
                    self._active_operation.disable()
                self._operation_sizer.Clear(delete_windows=True)
                try:
                    self._active_operation = operation(
                        self._operation_panel, self.canvas, self.canvas.world
                    )
                    self._operation_sizer.Add(
                        self._active_operation, *self._active_operation.wx_add_options
                    )
                    self._active_operation.enable()
                except Exception as e:
                    # If something went wrong clear the created UI
                    self._active_operation = None
                    self._operation_sizer.Clear(delete_windows=True)
                    for window in self.canvas.GetChildren():
                        window: wx.Window
                        # remove orphaned windows.
                        # If the Sizer.Add method was not run it will not be in self._operation_sizer
                        if window.GetContainingSizer() is None:
                            window.Destroy()
                    log.error("Error loading Operation UI.", exc_info=True)
                    notify_exception(
                        self.canvas,
                        "Error loading Operation UI.",
                        str(e),
                        traceback.format_exc(),
                    )
                finally:
                    self._last_active_operation_id = operation.identifier
            finally:
                self._operation_panel.Thaw()
                self._resize()

    def bind_events(self):
        if self._active_operation is not None:
            self._active_operation.bind_events()
        self.canvas.Bind(wx.EVT_SIZE, self._on_resize)

    def enable(self):
        if self._active_operation is None:
            self._setup_operation()
        else:
            self._active_operation.enable()
        self._settings_panel.Show()
        self._operation_panel.Show()
        self._resize()

    def disable(self):
        if self._active_operation is not None:
            self._active_operation.disable()
        self._settings_panel.Hide()
        self._operation_panel.Hide()

    def _on_reload_operations(self, evt):
        """Run when the button is pressed to reload the operations."""
        self.reload_operations()

    def reload_operations(self):
        """Reload all operations and repopulate the UI."""
        # store the id of the old operation
        operation_id = self.active_operation_id

        # reload the operations
        self._operations.reload()

        # repopulate the selection
        self._operation_choice.SetItems(
            {op.identifier: op.name for op in self._operations.operations}
        )

        if operation_id:
            identifiers = self._operation_choice.values

            if identifiers:
                if operation_id in identifiers:
                    self._operation_choice.SetSelection(identifiers.index(operation_id))
                else:
                    log.info(f"Operation {operation_id} was not found.")
                    self._operation_choice.SetSelection(0)
            else:
                log.error("No operations found. Something has gone wrong.")

            self._setup_operation()
            self.canvas.reset_bound_events()

    def _on_open_folder(self, evt):
        path = self._operations.public_path
        if not os.path.exists(path):
            os.makedirs(path)
        if sys.platform == "win32":
            os.startfile(path)
        else:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            process.call([opener, path])

    def _on_resize(self, evt):
        self._resize()
        evt.Skip()

    def _resize(self):
        settings_panel_size = self._settings_panel.GetBestSize()
        self._settings_panel.SetSize(
            wx.Rect(
                0, 30, settings_panel_size.GetWidth(), settings_panel_size.GetHeight()
            )
        )
        self._settings_panel.Raise()

        self._operation_panel.Layout()
        panel_size = self._operation_panel.GetBestSize()
        canvas_height = self.canvas.GetSize().GetHeight()
        allowed_canvas_height = canvas_height - 60 - settings_panel_size.GetHeight()
        ideal_path_height = panel_size.GetHeight()
        panel_height = min(ideal_path_height, allowed_canvas_height)
        panel_width = panel_size.GetWidth()
        self._operation_panel.SetSize(
            wx.Rect(0, 30 + settings_panel_size.GetHeight(), panel_width, panel_height)
        )
        self._operation_panel.Raise()
