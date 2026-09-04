import wx
from collections.abc import Mapping
from typing import TYPE_CHECKING, Optional, Iterable, List, Tuple
import traceback
import logging

import os
import sys
import subprocess
from amulet_map_editor.api import process

from amulet_map_editor.api import image
from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.widgets import Card
from amulet_map_editor.api.wx.nonblocking import notify, notify_exception
from amulet_map_editor.api.wx.ui.material_forms import MaterialChoice

from amulet_map_editor.programs.edit.api.operations import OperationUIType
from amulet_map_editor.programs.edit.api.operations.manager import UIOperationManager
from amulet_map_editor.programs.edit.api.ui.material_tool_panel import (
    IconButton,
    ToolPanel,
)
from .base_tool_ui import BaseToolUI

if TYPE_CHECKING:
    from amulet_map_editor.programs.edit.api.canvas import EditCanvas

log = logging.getLogger(__name__)


class _OperationChoice(MaterialChoice):
    """The operation dropdown, keeping the identifier/name mapping the
    ``wx.Choice``-based ``SimpleChoiceAny`` this replaces was built around.

    ``MaterialChoice`` already answers the ``wx.Choice`` vocabulary this file
    is written against -- ``GetSelection``, ``SetSelection``,
    ``GetStringSelection`` -- by index into the list of displayed *names*.
    What this file actually keys everything on is the operation's
    *identifier*, a module path that a display name is never guaranteed to be
    unique against on its own, so a second parallel list keeps the two in
    step exactly as ``SimpleChoiceAny``'s own ``_keys``/``_values`` did.
    """

    #: Narrower than the shell's default combo, matching the paste tool's own
    #: dropdown: this sits in a compact strip above the operation panel, not
    #: a settings form, and the widest of the stock operations' names still
    #: needs to be readable rather than only the ceiling being generous.
    WIDTH = 190

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, (), label="Operation", name="Operation")
        self._identifiers: List[str] = []

    @property
    def values(self) -> Tuple[str, ...]:
        """The identifier behind each displayed name, in list order."""
        return tuple(self._identifiers)

    @property
    def items(self) -> Tuple[Tuple[str, str], ...]:
        """Each displayed name paired with the identifier behind it."""
        return tuple(zip(self.GetStrings(), self._identifiers))

    def SetItems(  # noqa: N802 - wx API spelling
        self, items: Mapping[str, str], default: Optional[str] = None
    ) -> None:
        """Replace the option list from an ``{identifier: name}`` mapping.

        Sorted by the displayed name, as ``SimpleChoiceAny`` was by default --
        so the list a person picks from reads alphabetically rather than in
        whatever order plugins happened to load in.
        """
        if not items:
            return
        pairs = sorted(
            (
                (str(name).strip(), str(identifier))
                for identifier, name in items.items()
            ),
            key=lambda pair: pair[0],
        )
        names = [name for name, _identifier in pairs]
        self._identifiers = [identifier for _name, identifier in pairs]
        self.Set(names)
        if default is not None and default in self._identifiers:
            self.SetSelection(self._identifiers.index(default))
        elif names:
            self.SetSelection(0)

    def GetCurrentObject(self) -> Optional[str]:
        """Return the identifier behind the selected name, or ``None``."""
        index = self.GetSelection()
        if 0 <= index < len(self._identifiers):
            return self._identifiers[index]
        return None


class BaseOperationChoiceToolUI(wx.BoxSizer, BaseToolUI):
    OperationGroupName = None
    _active_operation: Optional[OperationUIType]

    ShowOpenFolder = True

    def __init__(self, canvas: "EditCanvas"):
        wx.BoxSizer.__init__(self, wx.VERTICAL)
        BaseToolUI.__init__(self, canvas)

        self._active_operation: Optional[OperationUIType] = None
        self._last_active_operation_id: Optional[str] = None

        self._settings_panel = Card(canvas.GetParent(), role="surface_container_high")
        self._settings_panel.Hide()
        self._settings_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._settings_panel.SetSizer(self._settings_sizer)

        self._operation_panel = ToolPanel(canvas.GetParent(), "Operation options")
        self._operation_panel.Hide()
        self._operation_sizer = self._operation_panel.sizer

        assert isinstance(
            self.OperationGroupName, str
        ), "OperationGroupName has not been set or is not a string."
        # The operation selection
        self._operation_choice = _OperationChoice(self._settings_panel)
        self._settings_sizer.Add(
            self._operation_choice,
            0,
            wx.ALL | wx.ALIGN_CENTER_VERTICAL,
            tokens.scaled(6),
        )
        self._operations = UIOperationManager(self.OperationGroupName)
        self._operation_choice.SetItems(
            {op.identifier: op.name for op in self._operations.operations}
        )
        self._operation_choice.Bind(wx.EVT_CHOICE, self._on_operation_change)

        # The reload button
        self._reload_operation = IconButton(
            self._settings_panel,
            image.REFRESH_ICON.bitmap(),
            hint="Reload Operations",
            name="Reload operations",
        )
        self._settings_sizer.Add(
            self._reload_operation,
            0,
            wx.ALL | wx.ALIGN_CENTER_VERTICAL,
            tokens.scaled(4),
        )
        self._reload_operation.Bind(wx.EVT_BUTTON, self._on_reload_operations)

        # The open folder button
        if self.ShowOpenFolder:
            self._open_folder = IconButton(
                self._settings_panel,
                image.TABLERICONS.folder.bitmap(),
                hint="Open Plugin Folder",
                name="Open plugin folder",
            )
            self._settings_sizer.Add(
                self._open_folder,
                0,
                wx.ALL | wx.ALIGN_CENTER_VERTICAL,
                tokens.scaled(4),
            )
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

        # A ScrolledPanel's scrollable (virtual) area is computed once, from
        # whatever the sizer held the moment scrolling was set up -- it is not
        # kept in step with later content by ``Layout()`` alone.  Every stock
        # operation past the first one replaces this panel's children in
        # ``_setup_operation``, so without recomputing it here the scroll
        # region stays sized for whichever operation built it first (Clone,
        # alphabetically) and ``ScrollChildIntoView`` can never reach a Run
        # button that a taller operation -- Fill, Replace, Set Biome,
        # Waterlog -- laid out past that stale boundary.
        #
        # Set directly rather than through another ``SetupScrolling()`` call:
        # that helper's own ``wx.CallAfter(self._SetupAfter, ...)`` overwrites
        # whatever virtual size is set here with ``GetBestVirtualSize()`` the
        # next time the event loop turns -- which is exactly the width-cap
        # fix below, undone a moment after being applied.  The scroll rate it
        # would also set is already fixed once, at construction, and does not
        # need revisiting.
        sizer_min = self._operation_sizer.CalcMin()
        self._operation_panel.SetVirtualSize(sizer_min)
        self._operation_panel.Layout()
        panel_size = self._operation_panel.GetBestSize()
        # The panel is positioned at y ``30 + settings_panel_size.height``
        # inside the viewport that hosts the canvas, so the height it may
        # occupy is whatever is left *below that offset* -- not the canvas's
        # whole size less a guess.  Measuring from GetSize() also double-counts
        # the strip this tool's own floating panels are reserved out of; the
        # parent's client area is the space the panel actually lives in.
        host_client = self.canvas.GetParent().GetClientSize()
        panel_top_offset = 30 + settings_panel_size.GetHeight()
        allowed_canvas_height = (
            host_client.GetHeight() - panel_top_offset
        )
        ideal_path_height = panel_size.GetHeight()
        panel_height = min(ideal_path_height, allowed_canvas_height)
        panel_width = panel_size.GetWidth()
        self._operation_panel.SetSize(
            wx.Rect(0, panel_top_offset, panel_width, panel_height)
        )
        # A panel short enough to need vertical scrolling grows a scrollbar,
        # which eats into its *client* width -- narrower than the
        # ``panel_width`` just set above, which came from the sizer's natural
        # (scrollbar-free) minimum size, and than the virtual width just set
        # for the sizer to lay children out against.  Horizontal scrolling is
        # deliberately off (``scroll_x=False`` at construction), so that gap
        # is not a pannable margin -- it is a strip along the right edge of
        # every full-width ``wx.EXPAND`` child (Fill's, Replace's, Set
        # Biome's and Waterlog's Run button all included) that sits past the
        # client area and is not inside the panel, whatever ``IsShown`` says.
        # Capping the virtual width to the real client width and laying out
        # once more against that narrower target shrinks those children to
        # fit inside the scrollbar instead of behind it.
        self._operation_panel.Layout()
        client_size = self._operation_panel.GetClientSize()
        virtual_size = self._operation_panel.GetVirtualSize()
        if virtual_size.GetWidth() > client_size.GetWidth():
            self._operation_panel.SetVirtualSize(
                wx.Size(client_size.GetWidth(), virtual_size.GetHeight())
            )
            self._operation_panel.Layout()
        self._operation_panel.Raise()
