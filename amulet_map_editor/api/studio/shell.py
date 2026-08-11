"""The Studio shell: the title bar, the two views, and the command router.

:class:`StudioShell` is the only child the application frame needs.  It owns the
Studio title bar, the backstage project screen, and the workspace, swaps the two
views, and is the single place a ribbon button, a menu row, a palette result, or
a keyboard accelerator arrives at.  Everything below it -- the ribbon, the
navigator, the viewport, the properties pane -- reports what the user did and
lets the shell decide what that means.

Three routes leave this class and nothing else does:

* **a surface** goes to :func:`amulet_map_editor.api.studio.surfaces.open_surface`;
* **a command** goes to :meth:`StudioShell.run_command`, which either acts on the
  Studio's own state, hands the action to the live world editor, or opens the
  surface that owns it;
* **an informational result** goes to
  :func:`amulet_map_editor.api.wx.nonblocking.notify`, never to a modal dialog.

A command that cannot be carried out says why, naming the exact key and the
exact thing that is missing.  A button that appears to work and quietly does
nothing is the defect this routing exists to prevent.

**Nothing here reimplements an editing operation.**  Saving, the undo stack, the
clipboard, chunk creation and deletion, imports, exports, and the operation
plugins all belong to :mod:`amulet_map_editor.programs.edit`, which owns the
level and its history.  This class finds the live canvas, finds the tool that
owns the action, calls it, and then reads the world back to report what actually
changed.  A second implementation of undo would be a second answer to the same
question, and the two would disagree the first time either of them changed.

The shell is also the one place that says which world is open: it publishes the
level to :mod:`amulet_map_editor.api.studio.context` when a project attaches and
clears it when the last one closes, which is what every surface reads its
numbers from.
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

import wx

from amulet_map_editor.api import local_history, preferences
from amulet_map_editor.api.studio import commands, context, surfaces, tokens
from amulet_map_editor.api.studio import recents, ribbon_defs
from amulet_map_editor.api.studio.backstage import BackstageView
from amulet_map_editor.api.studio.copy import studio_label, studio_text
from amulet_map_editor.api.studio.title_bar import (
    StudioTitleBar,
    install_palette_shortcut,
)
from amulet_map_editor.api.studio.workspace import WorkspaceView

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_PROJECT_TITLE",
    "StudioShell",
    "frame_camera",
    "framing_distance",
    "look_at",
    "top_down_framing",
]

#: What the shell calls a project nobody has named yet.
DEFAULT_PROJECT_TITLE = "Untitled project"

#: The interface densities, in the order the command cycles them.
_DENSITIES: Tuple[str, ...] = ("compact", "comfortable", "spacious")

#: How many descendant windows a delegated action will search before giving up.
#: A world page holds a few hundred controls; a bound stops a pathological tree
#: from freezing the interface while a keystroke is being routed.
_MAX_DESCENDANTS = 600

#: The shortest gap between two live enablement passes, in seconds.  The pass
#: runs on idle so that a selection dragged in the viewport greys the commands
#: that need one without the viewport having to know they exist; the throttle is
#: what stops that costing anything measurable while the user drags.
_ENABLEMENT_INTERVAL = 0.15

#: What Selection > Coordinates says when there is no selection to describe.
#: The six boxes shipped holding the design's mock numbers, which meant a world
#: with nothing selected still showed a box, and a reader had no way to tell
#: that from a box that really existed.  They are emptied instead, and this
#: sentence says why and what to press.
_NO_SELECTION_MESSAGE = (
    "Nothing is selected, so there are no coordinates to show. Press Add box "
    "to start a selection and these will fill in."
)

#: And what it says when there is no world at all.  A separate sentence rather
#: than the one above, because Add box is greyed out too when nothing is open,
#: so pointing at it would send the reader to press a dead control.
_NO_WORLD_MESSAGE = (
    "No world is open, so there is no selection to show. Open a world and "
    "these will fill in from it."
)


@dataclass(frozen=True)
class _EditorAction:
    """One command carried out by the live world editor rather than the shell.

    ``names`` are tried in order on each target.  ``event`` records that the
    target is a wx event handler and therefore takes an event argument, which is
    passed as ``None``.

    ``tool`` names the editor tool that owns the action -- ``"Chunk"`` for the
    chunk operations, ``"Operation"`` for the plugin runner.  Those tools are
    ``wx.Sizer`` subclasses rather than windows, so a walk over the world page's
    *windows* never reaches them however deep it goes; the canvas's own ``tools``
    mapping is the only route to them and is tried before any walk.

    ``descend`` additionally searches the world page's controls, for an action
    that lives on a panel rather than on a tool.  It is off by default and named
    per action rather than applied to everything: a walk looking for a method
    called ``save`` would eventually find one on something that is not the world.
    """

    names: Tuple[str, ...]
    event: bool = False
    descend: bool = False
    tool: str = ""


#: Commands the world editor owns, and the method on it that carries each out.
_EDITOR_ACTIONS: Mapping[str, _EditorAction] = MappingProxyType(
    {
        "save": _EditorAction(("save",)),
        "undo": _EditorAction(("undo",)),
        "redo": _EditorAction(("redo",)),
        "copy": _EditorAction(("copy",)),
        "cut": _EditorAction(("cut",)),
        "paste": _EditorAction(("paste_from_cache",)),
        "delete": _EditorAction(("delete",)),
        "selectAll": _EditorAction(("select_all",)),
        "goto": _EditorAction(("goto",)),
        "reloadPlugins": _EditorAction(
            ("reload_operations",), tool="Operation", descend=True
        ),
        "createChunks": _EditorAction(
            ("_create_chunks",), event=True, tool="Chunk", descend=True
        ),
        "deleteChunks": _EditorAction(
            ("_delete_chunks",), event=True, tool="Chunk", descend=True
        ),
        "deleteUnselectedChunks": _EditorAction(
            ("_prune_chunks",), event=True, tool="Chunk", descend=True
        ),
        "importChunks": _EditorAction(
            ("_import_chunks",), event=True, tool="Chunk", descend=True
        ),
    }
)

#: The editor tool a command puts the user in front of.  Activating a tool is
#: itself the action for these: the import tool opens the file chooser as it
#: enables, and the export and operation tools are where the selection is turned
#: into a file or handed to a plugin.
_COMMAND_TOOLS: Mapping[str, str] = MappingProxyType(
    {
        "importFile": "Import",
        "export": "Export",
        "runOperation": "Operation",
    }
)


def _same_operation(left: str, right: str) -> bool:
    """Return whether two operation names are the same one, spelled either way.

    The construction exporter registers itself as ``"\\tExport Construction"``
    -- a literal tab, so that it sorts to the top of an alphabetical chooser --
    and every other comparison of that name is against the string without it.
    Comparing exactly would report a correct arrival as a failure, so case and
    surrounding space are dropped rather than either spelling being declared
    the right one.  Same rule as
    :func:`amulet_map_editor.api.studio.editor_tools._same_operation`, which
    exists for the same tab.
    """
    return (
        " ".join(str(left or "").split()).casefold()
        == " ".join(str(right or "").split()).casefold()
    )


#: Commands whose real controls live on a surface.  Consulted only when a
#: project is open and the editor could not carry the command out, so the user
#: lands on the window where the action is configured instead of on a message
#: saying nothing happened.
_COMMAND_SURFACES: Mapping[str, str] = MappingProxyType(
    {
        "export": "exportStructure",
        "importFile": "pendingImports",
        "importChunks": "importChunks",
        "runOperation": "operationOptions",
    }
)

#: The commands that open one surface and nothing else.
_OPEN_COMMANDS: Mapping[str, str] = MappingProxyType(
    {
        "openPrefs": "prefs",
        "openNotifications": "notifications",
        "openHistory": "history",
        "openChangelog": "changelog",
        "openDocs": "docs",
        "openMemory": "memory",
        "openRegex": "regex",
    }
)

#: Editor commands after which the world may differ from what is on disk.
_MUTATING_COMMANDS: Tuple[str, ...] = (
    "cut",
    "paste",
    "delete",
    "rotate",
    "flip",
    "undo",
    "redo",
    "createChunks",
    "deleteChunks",
    "deleteUnselectedChunks",
    "importChunks",
)

#: Editor commands ``_after_editor_command`` answers with a branch of its own,
#: because the undo depth is not their evidence.
#:
#: Reload plugins was in neither tuple, and a command in neither tuple falls
#: off the end of that function and says *nothing at all*.  Listing it here
#: rather than in ``_MUTATING_COMMANDS`` is the distinction that matters: it
#: does not write to the world, so the mutating report would have answered a
#: reload that worked perfectly with "the world recorded no new undo point, so
#: nothing in it changed".  Its evidence is the operation list, and it reports
#: from the thing it actually did.
#:
#: ``undo`` and ``redo`` appear here *and* in ``_MUTATING_COMMANDS``, which is
#: correct for those two alone: they genuinely move the world, and they also
#: report the resulting depth themselves rather than through the generic
#: sentence.
_REPORTED_COMMANDS: Tuple[str, ...] = (
    "undo",
    "redo",
    "selectAll",
    "goto",
    "reloadPlugins",
)

#: Editor commands whose report is raised by the editor's own canvas method
#: rather than anywhere in this shell, and which this shell therefore stays
#: deliberately quiet about.
#:
#: Copy is here because the shell is the wrong layer for it.  It reported from
#: ``_after_editor_command``, which only ever runs for a command the shell
#: routed -- and two shipped controls call ``EditCanvas.copy`` directly and
#: never come through here at all: the Select tool's own Copy button and the
#: 3D editor's Edit ▸ Copy / Ctrl+C.  Measured on a running editor, both moved
#: the clipboard and raised zero notifications at any severity, so the command
#: with nothing to look at afterwards was still silent from the two places most
#: people press it.  ``EditCanvas.copy`` reports for itself now, which is the
#: one layer all three routes share; a second report here would put two toasts
#: on screen for one Ctrl+C.
_EDITOR_REPORTED_COMMANDS: Tuple[str, ...] = ("copy",)

#: The three press-and-hold selection gestures: the keybind the editor listens
#: for, what it moves, and the button on the Select tool that does the same job
#: from the keyboard.
_MOVE_COMMANDS: Mapping[str, Tuple[str, str, str]] = MappingProxyType(
    {
        "moveBox": ("ACT_BOX_CLICK", "the active selection box", "_selection_move"),
        "movePoint1": ("ACT_BOX_CLICK", "the green selection point", "_point1_move"),
        "movePoint2": ("ACT_BOX_CLICK_ADD", "the blue selection point", "_point2_move"),
    }
)


#: The rotation the 3D editor itself installs while the camera looks straight
#: down, copied from ``CameraBehaviour.move_camera_relative`` rather than
#: guessed: the top-down projection ignores any other rotation, so framing a
#: dimension from above has to hand back the one it uses.  The camera normalises
#: yaw into ``[-180, 180)`` and therefore stores this as ``(-180.0, 90.0)``,
#: which is the same bearing written the other way round.
_TOP_DOWN_ROTATION: Tuple[float, float] = (180.0, 90.0)

#: How far above the horizontal the framing camera sits, in degrees.  A flat
#: view hides the terrain behind the nearest hill and a vertical one throws away
#: the perspective that makes a landscape readable; this is the angle a mapping
#: tool conventionally opens at.
_FRAME_PITCH = 35.0

#: The fraction of the viewport's far clipping distance the framing camera is
#: allowed to retreat to.  A camera beyond the far plane frames a dimension by
#: not drawing it.
_FRAME_CLIP_MARGIN = 0.9


def look_at(
    location: Tuple[float, float, float], target: Tuple[float, float, float]
) -> Tuple[float, float]:
    """Return the ``(yaw, pitch)`` that points a camera at ``location`` at ``target``.

    The angles are in the convention
    :class:`~amulet_map_editor.api.opengl.camera.camera.Camera` uses -- yaw 0
    faces +Z, positive pitch looks downwards -- and were checked against the
    renderer's own ``camera_matrix``: each pair puts the target on the camera's
    -Z axis at exactly the separating distance, which is what "looking at it"
    means to the matrix that draws the frame.

    A target the camera is already standing on has no direction to face, so the
    camera's job is done and ``(0.0, 0.0)`` is returned rather than an angle
    derived from a zero-length vector.
    """
    dx = float(target[0]) - float(location[0])
    dy = float(target[1]) - float(location[1])
    dz = float(target[2]) - float(location[2])
    if dx == 0.0 and dy == 0.0 and dz == 0.0:
        return (0.0, 0.0)
    return (
        math.degrees(math.atan2(-dx, dz)),
        math.degrees(math.atan2(-dy, math.hypot(dx, dz))),
    )


def framing_distance(radius: float, fov: float, aspect: float) -> float:
    """Return how far back a camera must sit for a sphere to fit in view.

    ``fov`` is the vertical field of view in degrees, which is what
    ``perspective_matrix`` is handed, and ``aspect`` is width over height.  A
    window wider than it is tall shows more sideways than it does vertically, so
    the vertical angle is the binding one; a taller-than-wide window inverts
    that, and the narrower of the two is used either way.

    The result is the distance from the sphere's *centre*, not from its near
    face, so the caller places the camera at ``centre + direction * distance``.
    """
    span = max(0.0, float(radius))
    half_vertical = math.radians(max(1.0, min(179.0, float(fov)))) / 2.0
    ratio = max(0.01, float(aspect))
    half_horizontal = math.atan(math.tan(half_vertical) * ratio)
    limiting = min(half_vertical, half_horizontal)
    return span / math.sin(limiting)


def frame_camera(
    minimum: Tuple[int, int, int],
    maximum: Tuple[int, int, int],
    *,
    fov: float,
    aspect: float,
    far: float,
) -> Tuple[Tuple[float, float, float], Tuple[float, float], bool]:
    """Return where a perspective camera goes to hold a box in view.

    The box is bounded by a sphere rather than fitted face-on, because a
    dimension viewed from an angle presents its diagonal rather than its width;
    fitting the width is what leaves the far corners off the screen.  The camera
    retreats due north of the centre and :data:`_FRAME_PITCH` degrees above it,
    so it looks south and downwards -- Minecraft's own default facing, which is
    the orientation a player's mental map of their world is already in -- and it
    is stopped short of the viewport's far clipping plane.

    Returns ``(location, rotation, capped)``.  ``capped`` is ``True`` when the
    dimension is larger than the viewport can draw, which the caller says out
    loud rather than presenting a partial view as a complete one.
    """
    centre = tuple(
        (float(low) + float(high)) / 2.0 for low, high in zip(minimum, maximum)
    )
    radius = (
        math.dist(
            [float(value) for value in minimum], [float(value) for value in maximum]
        )
        / 2.0
    )
    wanted = framing_distance(radius, fov, aspect)
    limit = max(1.0, float(far) * _FRAME_CLIP_MARGIN)
    capped = wanted > limit
    distance = min(wanted, limit)
    pitch = math.radians(_FRAME_PITCH)
    location = (
        centre[0],
        centre[1] + distance * math.sin(pitch),
        centre[2] - distance * math.cos(pitch),
    )
    return location, look_at(location, centre), capped


def top_down_framing(
    minimum: Tuple[int, int, int],
    maximum: Tuple[int, int, int],
    aspect: float,
) -> Tuple[Tuple[float, float, float], float]:
    """Return the camera position and orthographic radius for a top-down frame.

    ``orthographic_matrix`` takes a radius measured up the *screen*, and the
    renderer's own matrices were asked which world axis that is: looking down at
    rotation :data:`_TOP_DOWN_ROTATION`, world Z runs up the screen and world X
    runs across it, widened by the aspect ratio.  So Z is bounded directly and X
    is bounded after dividing by the aspect -- the other way round frames a
    long, thin dimension by cutting its ends off.
    """
    centre = tuple(
        (float(low) + float(high)) / 2.0 for low, high in zip(minimum, maximum)
    )
    ratio = max(0.01, float(aspect))
    half_x = abs(float(maximum[0]) - float(minimum[0])) / 2.0
    half_z = abs(float(maximum[2]) - float(minimum[2])) / 2.0
    radius = max(1.0, half_z, half_x / ratio)
    height = float(maximum[1]) + radius
    return (centre[0], height, centre[2]), radius


@dataclass(frozen=True)
class _CommandState:
    """What the open world can answer right now, read from the live editor.

    Every field is a fact about the world rather than about the interface, and
    every one of them is read fresh: a stale copy of "something is selected" is
    what makes a control enabled after the selection has gone.
    """

    project: bool = False
    editor: bool = False
    selection: bool = False
    clipboard: bool = False
    undo: bool = False
    redo: bool = False

    def unmet(self, needs: Tuple[str, ...]) -> Tuple[str, ...]:
        """Return the conditions in ``needs`` this state does not satisfy."""
        return tuple(name for name in needs if not getattr(self, name, False))

    def signature(self) -> Tuple[bool, ...]:
        """Return a cheap value that changes exactly when the state does."""
        return (
            self.project,
            self.editor,
            self.selection,
            self.clipboard,
            self.undo,
            self.redo,
        )


class StudioShell(wx.Panel):
    """The application's one content panel: title bar, backstage, workspace.

    The frame keeps its update banner, its notification toasts, and its world
    notebook; this panel is what the user actually looks at, and the notebook's
    renderer is handed to the workspace viewport so the real world still draws
    inside the new shell rather than beside it.
    """

    def __init__(self, parent: wx.Window, frame: wx.Frame) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.frame = frame
        self.view = "backstage"
        self.doc_title = DEFAULT_PROJECT_TITLE
        self.project_path = ""
        self.project_platform = ""
        self.saved = True
        self.project_open = False

        self.SetName("Amulet Studio")
        # The Studio paints itself from its own tokens, so the shared Material
        # helper must not restyle it on its way through the frame.  Set before
        # any child exists, because that traversal stops at this panel.
        self._material3_opt_out = True

        self.title_bar = StudioTitleBar(
            self,
            frame,
            title=self.doc_title,
            saved=self.saved,
            on_command=self.run_command,
            on_surface=self.open_surface,
            on_palette=self.open_palette,
        )
        self.backstage = BackstageView(
            self,
            on_surface=self.open_surface,
            on_command=self.run_command,
            on_open_project=self.open_project,
            on_workspace=self.show_workspace,
        )
        self.workspace = WorkspaceView(
            self,
            on_surface=self.open_surface,
            on_command=self.run_command,
            on_backstage=self.show_backstage,
            title=self.doc_title,
        )
        self.workspace.Hide()

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self.title_bar, 0, wx.EXPAND)
        root.Add(self.backstage, 1, wx.EXPAND)
        root.Add(self.workspace, 1, wx.EXPAND)
        self.SetSizer(root)

        self._handlers: Dict[str, Callable[[str], None]] = self._build_handlers()
        self._accelerator_ids: Dict[str, int] = {}
        self._opening_project = False
        #: The last state the enablement pass applied, so an idle tick that
        #: changed nothing costs one tuple comparison rather than a tree walk.
        self._enablement_signature: Optional[Tuple[Any, ...]] = None
        self._enablement_checked = 0.0
        #: The Coordinates group these six values were last written into, and
        #: the selection box they were written from.  Kept so the idle pass can
        #: tell "the world moved" from "the user is in the middle of typing".
        self._selection_panel: Any = None
        self._selection_seeded: Any = None
        self._remove_palette_shortcut: Optional[Callable[[], None]] = (
            install_palette_shortcut(self, self.open_palette)
        )
        # Registered after every child exists so a theme change can never reach
        # a half-built shell.
        self._theme_unsubscribe: Optional[Callable[[], None]] = (
            tokens.register_theme_listener(self._repaint)
        )
        context.subscribe(self._on_world_context)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self.Bind(wx.EVT_IDLE, self._on_idle)
        self._apply_theme()
        self._refresh_enablement(force=True)

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        """Drop the shell's global hooks before wx tears the panel down."""
        if event.GetEventObject() is self:
            if self._theme_unsubscribe is not None:
                self._theme_unsubscribe()
                self._theme_unsubscribe = None
            if self._remove_palette_shortcut is not None:
                try:
                    self._remove_palette_shortcut()
                except RuntimeError:  # pragma: no cover - frame already gone
                    pass
                self._remove_palette_shortcut = None
            context.unsubscribe(self._on_world_context)
            # A shell going away takes the world it published with it; leaving
            # the context pointing at a level whose window has been destroyed
            # would let the next surface read numbers out of a closed world.
            if context.current().open:
                context.clear()
        event.Skip()

    def _on_idle(self, event: wx.IdleEvent) -> None:
        """Keep the ribbon's enabled states true while the user works.

        The selection is dragged in the viewport, the undo stack moves when an
        operation finishes, and the clipboard fills the first time anything is
        copied.  None of those go through this class, and a tile that stays
        pressable after its precondition has gone is exactly the control that
        looks live and does nothing.  Re-reading the world on idle, throttled,
        is what keeps every one of them honest without the viewport, the
        operation runner, and the clipboard each having to report to the shell.
        """
        event.Skip()
        now = time.monotonic()
        if now - self._enablement_checked < _ENABLEMENT_INTERVAL:
            return
        self._enablement_checked = now
        self._refresh_enablement()

    # ------------------------------------------------------------------
    # views
    # ------------------------------------------------------------------
    def show_backstage(self, tab: str = "home") -> None:
        """Show the project screen, on ``tab``."""
        self.view = "backstage"
        self.backstage.set_tab(str(tab or "home"))
        self.workspace.Hide()
        self.backstage.Show()
        self.Layout()
        self.backstage.SetFocus()

    def show_workspace(self) -> None:
        """Show the editing workspace."""
        self.view = "workspace"
        self.backstage.Hide()
        self.workspace.Show()
        self.Layout()
        self.workspace.SetFocus()

    # ------------------------------------------------------------------
    # project state
    # ------------------------------------------------------------------
    def open_project(self, title: str = "", path: str = "", platform: str = "") -> None:
        """Open a project the user chose on the backstage.

        A project with a path is opened by the frame, because the frame owns the
        world notebook, the loader, and the unsaved-work protection; the frame
        then reports back through :meth:`attach_project`.  A project without a
        path -- a template the user started from -- is attached directly, since
        there is no world on disk to load yet.

        A second request arriving while a load is in flight is dropped rather
        than queued: loading a world is slow enough for an impatient second
        press to be a duplicate rather than a new instruction.
        """
        if self._opening_project:
            return
        name = str(title or "").strip() or DEFAULT_PROJECT_TITLE
        target = str(path or "").strip()
        opener = getattr(self.frame, "open_level", None)
        if target and callable(opener):
            self._opening_project = True
            try:
                opener(target)
            except Exception:
                log.exception("The frame could not open the level at %r", target)
                self.notify(
                    studio_label("That project did not open", "呢個專案開唔到"),
                    studio_text(
                        f"{target} could not be loaded. The details are in the log."
                    ),
                    severity="error",
                )
            finally:
                self._opening_project = False
            return
        self.attach_project(name, target, platform)

    def attach_project(self, title: str, path: str = "", platform: str = "") -> None:
        """Record that a project is now open and show it.

        Called by the frame once a world has genuinely loaded, so the shell
        never claims a project is open because somebody asked for it.
        """
        self.doc_title = str(title or "").strip() or DEFAULT_PROJECT_TITLE
        self.project_path = str(path or "")
        self.project_platform = str(platform or "")
        self.project_open = True
        self.title_bar.set_title(self.doc_title)
        self.workspace.set_project(self.doc_title, self.project_path)
        self.backstage.set_project(
            True, self.doc_title, self.project_path, self.project_platform
        )
        self._remember_recent()
        self.show_workspace()
        # Published last, and only once every panel has been told the project
        # is open: the subscribers redraw from the world, and one that redrew
        # against a half-attached shell would show the previous project's name
        # beside this project's numbers.
        self._publish_world()

    def detach_project(self) -> None:
        """Record that no project is open and return to the project screen."""
        self.project_open = False
        self.doc_title = DEFAULT_PROJECT_TITLE
        self.project_path = ""
        self.project_platform = ""
        self.set_saved(True)
        self.title_bar.set_title(self.doc_title)
        self.workspace.set_canvas(None)
        self.workspace.set_project(self.doc_title, "")
        self.backstage.set_project(False)
        context.clear()
        self.show_backstage("home")
        self._refresh_enablement(force=True)

    def _publish_world(self) -> None:
        """Hand the open level to the world context every surface reads.

        The level is taken from the notebook page the frame reports, not from
        anything the shell was told: a project the shell believes is open but
        whose page has already gone must publish nothing rather than publish a
        name with no world behind it.
        """
        level = self._level()
        if level is None:
            if self.project_open:
                log.debug(
                    "No level is reachable for %r, so the world context stays "
                    "empty rather than describing a world nothing can read",
                    self.doc_title,
                )
            context.clear()
            self._refresh_enablement(force=True)
            return
        context.set_level(
            level,
            path=self.project_path,
            name=self.doc_title,
            canvas=self._canvas(),
        )
        self._sync_world_state()

    def _on_world_context(self, ctx: context.WorldContext) -> None:
        """Re-read the enabled states whenever the open world changes."""
        self._refresh_enablement(force=True)

    def close_project(self) -> None:
        """Close the open project, letting unsaved-work protection decide.

        The frame's close can be vetoed by a page holding unsaved work, so the
        shell asks and then reads the result rather than assuming it succeeded.
        """
        closer = getattr(self.frame, "close_level", None)
        if self.project_open and self.project_path and callable(closer):
            closer(self.project_path)
            sync = getattr(self.frame, "sync_studio_project", None)
            if callable(sync):
                sync()
            return
        self.detach_project()

    def set_saved(self, saved: bool) -> None:
        """Record whether the project has unsaved changes, everywhere at once."""
        self.saved = bool(saved)
        self.title_bar.set_saved(self.saved)
        self.workspace.set_saved(self.saved)

    def set_canvas(self, window: Optional[wx.Window]) -> None:
        """Host the real renderer inside the workspace viewport.

        The renderer arrives well after the project does -- the editor builds
        its canvas on a background thread -- and it is what the world context
        reads the selection and the shown dimension from.  So the world is
        published again here rather than only when the project attached, or
        every selection-driven surface would spend the rest of the session
        reading a context that was snapshotted before there was a viewport.
        """
        self.workspace.set_canvas(window)
        if self.project_open:
            self._publish_world()

    def set_update_state(
        self, status: str, version: str = "", detail: str = ""
    ) -> None:
        """Pass the frame's observed update state to the backstage."""
        self.backstage.set_update_state(status, version, detail)

    def _remember_recent(self) -> None:
        """Add the open project to the recent list, ignoring a read-only store."""
        try:
            recents.store().add(
                self.doc_title,
                path=self.project_path,
                platform=self.project_platform,
                kind="World" if self.project_path else "Project",
            )
        except Exception:  # pragma: no cover - an unwritable profile
            log.exception("Could not record %r in the recent projects", self.doc_title)

    # ------------------------------------------------------------------
    # surfaces, the palette, and reporting
    # ------------------------------------------------------------------
    def open_surface(self, key: str) -> Optional[wx.Window]:
        """Open one surface, and report honestly when it does not open.

        One key is intercepted.  ``goto`` describes a camera teleport, and the
        live editor already owns a teleport dialog that reads the camera's real
        position and moves it; the Studio's own description of that dialog can
        only show numbers it has no way of reading.  When there is a canvas the
        real one opens, and when there is not the description does, so the user
        never lands on a form that cannot move anything.
        """
        resolved = str(key or "")
        if resolved == "goto" and self._canvas() is not None:
            self.run_command("goto")
            return None
        return surfaces.open_surface(self, resolved)

    def open_palette(self) -> Optional[wx.Window]:
        """Open the command palette over every command, surface, and setting."""
        from amulet_map_editor.api.studio import palette_dialog

        return palette_dialog.open_palette(self)

    def notify(self, title: str, body: str, severity: str = "info") -> None:
        """Report a result without blocking anything the user is doing.

        The two halves are built by different functions, deliberately.  A
        ``title`` names the event -- "Saved", "Camera speed", or the command's
        own label, the very string the ribbon tile and the palette row render --
        so it is built with :func:`~amulet_map_editor.api.studio.copy.
        studio_label` and arrives exactly as written.  A ``body`` is the
        sentence saying what actually happened, which is the application
        talking, so it is built with :func:`~amulet_map_editor.api.studio.copy.
        studio_text` and carries the funny level.

        It shipped the other way round: the title was the only half styled, so
        at level five a toast was headed ``Convert this world to another
        platform (the code is dancing; the facts stay put)`` above an entirely
        deadpan explanation.  The tone was reaching the name and missing the
        words.
        """
        from amulet_map_editor.api.wx import nonblocking

        nonblocking.notify(self, title, body, severity=severity)

    # ------------------------------------------------------------------
    # commands
    # ------------------------------------------------------------------
    def _build_handlers(self) -> Dict[str, Callable[[str], None]]:
        """Map every command key to the method that carries it out."""
        handlers: Dict[str, Callable[[str], None]] = {
            "save": self._cmd_save,
            "openProject": self._cmd_open_project,
            "closeProject": self._cmd_close_project,
            "openBackstage": self._cmd_open_backstage,
            "backToWorkspace": self._cmd_back_to_workspace,
            "convertWorld": self._cmd_convert_world,
            "openOperationsFolder": self._cmd_operations_folder,
            "openInEditor": self._cmd_open_in_editor,
            "addBox": self._cmd_add_box,
            "removeBox": self._cmd_remove_box,
            "duplicateBox": self._cmd_duplicate_box,
            "deselectAllBoxes": self._cmd_deselect_all_boxes,
            "setSelectionBounds": self._cmd_set_selection_bounds,
            "rotate": self._cmd_transform,
            "flip": self._cmd_transform,
            "projection": self._cmd_projection,
            "frameDimension": self._cmd_frame_dimension,
            "cameraSpeed": self._cmd_camera_speed,
            "setDimension": self._cmd_set_dimension,
            "togglePane": self._cmd_toggle_pane,
            "toggleRibbon": self._cmd_toggle_ribbon,
            "toggleTheme": self._cmd_toggle_theme,
            "setDensity": self._cmd_set_density,
            "resetOverlays": self._cmd_reset_overlays,
            "setExportFormat": self._cmd_set_export_format,
            "openPalette": self._cmd_open_palette,
            "updateRestart": self._cmd_update_restart,
        }
        for key in _OPEN_COMMANDS:
            handlers[key] = self._cmd_open_registered_surface
        for key in _MOVE_COMMANDS:
            handlers[key] = self._cmd_move_gesture
        for key in _COMMAND_TOOLS:
            handlers.setdefault(key, self._cmd_tool)
        for key in _EDITOR_ACTIONS:
            handlers.setdefault(key, self._cmd_editor)
        for key in _COMMAND_SURFACES:
            handlers.setdefault(key, self._cmd_editor)
        return handlers

    def run_command(self, key: str) -> None:
        """Run one command, whatever asked for it.

        A command whose preconditions are not met is refused here rather than
        inside its handler, so the keyboard, the palette, and a ribbon tile that
        was pressed before the pass could grey it all get the same sentence
        naming the same missing condition.
        """
        resolved = commands.resolve(key)
        if not resolved:
            log.error("run_command was called without a command key")
            return
        handler = self._handlers.get(resolved)
        if handler is None:
            entry = commands.command(resolved)
            log.error("No Studio handler is registered for the command %r", resolved)
            self.notify(
                studio_label("That command is not connected", "呢個指令未接到"),
                studio_text(
                    f"Nothing is registered to run the command {resolved!r}"
                    + (f" ({entry.label})." if entry is not None else ".")
                ),
                severity="warning",
            )
            return
        if not self._require(resolved):
            return
        try:
            handler(resolved)
        except Exception:
            log.exception("The Studio command %r failed", resolved)
            self.notify(
                studio_label("That command failed", "呢個指令失敗咗"),
                studio_text(
                    f"Running {resolved!r} raised an error. The details are in the log."
                ),
                severity="error",
            )
        finally:
            self._refresh_enablement(force=True)

    def unmet_conditions(self, key: str) -> Tuple[str, ...]:
        """Return what ``key`` is waiting for, read from the world right now.

        Public because a control that is about to be drawn has the same question
        as a command that is about to be run, and they must not answer it from
        two readings: the ribbon greys its tiles from the sweep below, and a
        right-click menu -- which is built fresh each time and is nobody's child
        in particular -- walks up to this method and greys its own rows from the
        same conditions.  A menu row saying a command is ready while the tile
        beside it says the opposite is one window disagreeing with itself.

        An empty tuple means the command can run: either it needs nothing, or
        the world already answers everything it needs.
        """
        needs = commands.requirements(key)
        if not needs:
            return ()
        return self._command_state().unmet(needs)

    def _require(self, key: str) -> bool:
        """Report why ``key`` cannot run, and return whether it can.

        The conditions come from the registry rather than from each handler, so
        the sentence a disabled tile shows in its tooltip and the sentence a
        pressed one shows in a notification cannot describe different worlds.
        """
        unmet = self.unmet_conditions(key)
        if not unmet:
            return True
        self.notify(
            studio_label(commands.label_for(key), ""),
            studio_text(commands.unavailable_hint(key, unmet)),
            severity="warning",
        )
        return False

    # -- project commands ----------------------------------------------------
    def _cmd_save(self, key: str) -> None:
        """Write the open world to disk through the editor's own save."""
        before = self._history_counts()
        if not self._editor_call(_EDITOR_ACTIONS["save"]):
            self.notify(
                studio_label("Nothing was saved", "冇嘢儲存到"),
                studio_text(
                    "No world editor is attached to this project, so there was nothing "
                    "to write."
                ),
                severity="warning",
            )
            return
        # The level is asked whether it still differs from disk rather than being
        # marked clean because a save was requested: a save that fails partway
        # leaves the world changed, and a title bar claiming otherwise is how
        # unsaved work gets closed away.
        level = self._level()
        changed = bool(getattr(level, "changed", False)) if level is not None else False
        self._record(
            "save",
            {
                "project": self.doc_title,
                "path": self.project_path,
                "undo_points": before[0],
                "still_changed": changed,
            },
        )
        self._sync_world_state()
        if changed:
            self.notify(
                studio_label("Partly saved", "未完全儲存"),
                studio_text(
                    f"{self.doc_title} still reports unsaved changes after the save "
                    "finished. The details are in the log."
                ),
                severity="warning",
            )
            return
        self.notify(
            studio_label("Saved", "已經儲存"),
            studio_text(
                f"{self.doc_title} was written to {self.project_path or 'disk'}."
            ),
            severity="success",
        )

    def _cmd_open_project(self, _key: str) -> None:
        opener = getattr(self.frame, "open_project_dialog", None)
        if callable(opener):
            opener()
            return
        self.show_backstage("open")

    def _cmd_close_project(self, _key: str) -> None:
        self.close_project()

    def _cmd_open_backstage(self, _key: str) -> None:
        self.show_backstage("home")

    def _cmd_back_to_workspace(self, _key: str) -> None:
        self.show_workspace()

    def _cmd_convert_world(self, _key: str) -> None:
        """Show the backstage destination that sets a conversion up."""
        self.show_backstage("convert")

    def _cmd_operations_folder(self, key: str) -> None:
        """Open the folder the editor loads project operations from."""
        data_dir = os.environ.get("DATA_DIR", "")
        if not data_dir:
            self.notify(
                studio_label("The operations folder is unknown", "搵唔到操作資料夾"),
                studio_text(
                    "This build has no data directory configured, so the operations "
                    "folder cannot be located."
                ),
                severity="warning",
            )
            return
        target = os.path.join(data_dir, "plugins")
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as error:
            self.notify(
                studio_label(
                    "The operations folder is unavailable", "操作資料夾開唔到"
                ),
                studio_text(f"{target} could not be created: {error}"),
                severity="error",
            )
            return
        if not wx.LaunchDefaultApplication(target):
            self.notify(
                studio_label("The operations folder did not open", "操作資料夾開唔到"),
                studio_text(f"Windows refused to open {target}."),
                severity="warning",
            )
            return
        self.notify(
            studio_label("Operations folder", "操作資料夾"),
            studio_text(f"Opened {target}."),
        )

    def _cmd_open_in_editor(self, _key: str) -> None:
        """Open the project's folder in the configured external editor."""
        from amulet_map_editor.api import export_actions

        target = self.project_path
        if not target:
            self.notify(
                studio_label("There is nothing to open", "冇嘢可以開"),
                studio_text(
                    "Open a project first; the external editor opens the project's "
                    "own folder."
                ),
                severity="warning",
            )
            return
        action = export_actions.open_exported_path(target)
        self.notify(
            studio_label("External editor", "外部編輯器"),
            studio_text(action.message or f"Opened {action.target}."),
            severity="success" if action.ok else "warning",
        )

    def _cmd_update_restart(self, _key: str) -> None:
        restart = getattr(self.frame, "restart_to_install_update", None)
        if not callable(restart):
            self.notify(
                studio_label("Updates are unavailable here", "呢度冇更新功能"),
                studio_text(
                    "This window is not hosted by the application frame, so no "
                    "staged update can be installed."
                ),
                severity="warning",
            )
            return
        restart()

    # -- selection commands --------------------------------------------------
    def _cmd_add_box(self, key: str) -> None:
        """Add a one-block selection box where the camera is standing.

        The box goes into the editor's own selection, which is what every
        operation reads and what the renderer draws, rather than into a list the
        Studio keeps beside it.  Its position is the camera's real position: a
        box has to start somewhere, and the place the user is looking from is the
        only origin the world can actually supply.
        """
        canvas = self._canvas()
        corners = list(self._selection_corners())
        origin = self._camera_block(canvas)
        if origin is None:
            self.notify(
                studio_label("The camera has no position", "鏡頭冇位置"),
                studio_text(
                    "The 3D editor has not reported a camera position yet, so there "
                    "is nowhere to put a selection box."
                ),
                severity="warning",
            )
            return
        far = (origin[0] + 1, origin[1] + 1, origin[2] + 1)
        corners.append((origin, far))
        if not self._set_selection_corners(canvas, corners):
            return
        self._record(
            "selection-add-box",
            {
                "path": self.project_path,
                "dimension": self._dimension_name(),
                "minimum": list(origin),
                "maximum": list(far),
                "boxes": len(corners),
            },
        )
        self._sync_world_state()
        self.notify(
            studio_label("Selection box added", "加咗一個選取框"),
            studio_text(
                f"A 1x1x1 box was added at {origin[0]}, {origin[1]}, {origin[2]}; "
                f"the selection now holds {len(corners)} "
                f"{'box' if len(corners) == 1 else 'boxes'}."
            ),
            severity="success",
        )

    def _cmd_remove_box(self, key: str) -> None:
        """Drop the most recently added box from the editor's selection.

        The viewport menu's "Deselect active box" arrives here too, through the
        ``deselectBox`` alias.  The 3D editor's own ``ACT_DESELECT_BOX`` does
        exactly this -- ``self.selection_group = selection_group[:-1]`` in
        :class:`~amulet_map_editor.programs.edit.api.behaviour.
        block_selection_behaviour.BlockSelectionBehaviour` -- so the two names
        share one implementation rather than each growing its own answer to the
        same question.
        """
        canvas = self._canvas()
        corners = list(self._selection_corners())
        if not corners:
            self.notify(
                studio_label("Nothing is selected", "冇嘢揀咗"),
                studio_text("There is no selection box in this world to remove."),
                severity="warning",
            )
            return
        low, high = corners.pop()
        if not self._set_selection_corners(canvas, corners):
            return
        self._record(
            "selection-remove-box",
            {
                "path": self.project_path,
                "dimension": self._dimension_name(),
                "minimum": list(low),
                "maximum": list(high),
                "boxes": len(corners),
            },
        )
        self._sync_world_state()
        self.notify(
            studio_label("Selection box removed", "刪咗個選取框"),
            studio_text(
                f"The box from {low[0]}, {low[1]}, {low[2]} to {high[0]}, {high[1]}, "
                f"{high[2]} is gone; {len(corners)} remain."
            ),
            severity="success",
        )

    def _cmd_deselect_all_boxes(self, key: str) -> None:
        """Clear the editor's whole selection, as the viewport's own key does.

        This is ``ACT_DESELECT_ALL_BOXES`` -- ``self.selection_group =
        SelectionGroup()`` in the editor's selection behaviour -- reached from a
        menu row instead of from the keyboard, and written against the same
        selection the editor's key writes to.
        """
        canvas = self._canvas()
        corners = list(self._selection_corners())
        if not corners:
            self.notify(
                studio_label("Nothing is selected", "冇嘢揀咗"),
                studio_text("There is no selection box in this world to deselect."),
                severity="warning",
            )
            return
        if not self._set_selection_corners(canvas, []):
            return
        self._record(
            "selection-deselect-all",
            {
                "path": self.project_path,
                "dimension": self._dimension_name(),
                "boxes_cleared": len(corners),
            },
        )
        self._sync_world_state()
        self.notify(
            studio_label("Selection cleared", "清晒個選取"),
            studio_text(
                f"{len(corners)} selection {'box' if len(corners) == 1 else 'boxes'} "
                "left the selection; nothing is selected now."
            ),
            severity="success",
        )

    def _cmd_duplicate_box(self, key: str) -> None:
        """Copy the active selection box and place the copy beside it.

        The copy is offset by the box's own width along X rather than laid on
        top of the original.  A duplicate at the same coordinates is a box the
        user cannot see, cannot pick up, and cannot tell apart from the one it
        was made from, so the command would report having done something whose
        only evidence is a number in a panel.  Where the copy went is in the
        notification, because an offset the user did not ask for is a fact they
        have to be told rather than left to discover.
        """
        canvas = self._canvas()
        corners = list(self._selection_corners())
        if not corners:
            self.notify(
                studio_label("Nothing is selected", "冇嘢揀咗"),
                studio_text("There is no selection box in this world to duplicate."),
                severity="warning",
            )
            return
        low, high = corners[-1]
        low = tuple(int(value) for value in low)
        high = tuple(int(value) for value in high)
        # ``max(1, …)`` so a zero-width box still moves: a copy that landed on
        # its original would be the invisible duplicate this offset exists for.
        shift = max(1, abs(high[0] - low[0]))
        copy_low = (low[0] + shift, low[1], low[2])
        copy_high = (high[0] + shift, high[1], high[2])
        corners.append((copy_low, copy_high))
        if not self._set_selection_corners(canvas, corners):
            return
        self._record(
            "selection-duplicate-box",
            {
                "path": self.project_path,
                "dimension": self._dimension_name(),
                "source_minimum": list(low),
                "source_maximum": list(high),
                "minimum": list(copy_low),
                "maximum": list(copy_high),
                "offset": [shift, 0, 0],
                "boxes": len(corners),
            },
        )
        self._sync_world_state()
        self.notify(
            studio_label("Selection box duplicated", "複製咗個選取框"),
            studio_text(
                f"The box at {low[0]}, {low[1]}, {low[2]} was copied to "
                f"{copy_low[0]}, {copy_low[1]}, {copy_low[2]} — {shift} "
                f"{'block' if shift == 1 else 'blocks'} east, so the two do not "
                f"overlap. The selection now holds {len(corners)} boxes."
            ),
            severity="success",
        )

    # -- the six coordinate boxes -------------------------------------------
    def _cmd_set_selection_bounds(self, _key: str) -> None:
        """Move the active selection box to what the six boxes now say.

        Raised when one of Selection > Coordinates is committed -- Enter, or the
        field left -- and reached from the palette too, where it applies
        whatever those boxes are currently showing.

        The write goes through :meth:`_set_selection_corners`, the one path Add
        box, Remove and Duplicate already use, rather than a second route into
        the editor's selection: two ways to move a selection is two places for
        the next change to have to be made, and one of them will be missed.

        A value that cannot be used is refused and said out loud beside the box
        that carries it.  Nothing is guessed at, rounded, or clamped: a
        coordinate the user did not type is a box they did not draw, and the
        cheapest way to lose somebody's work is to silently select something
        near what they asked for and then let them run Delete on it.
        """
        panel = self._selection_field_panel()
        if panel is None:
            # Reachable from the palette while another tab is showing, so this
            # is a real state rather than an impossible one.
            self.notify(
                studio_label("The coordinate boxes are not open", "座標格未開"),
                studio_text(
                    "Open the Selection tab of the ribbon to type the active "
                    "box's coordinates."
                ),
                severity="warning",
            )
            return
        canvas = self._canvas()
        corners = list(self._selection_corners())
        if not corners:
            self._set_selection_feedback(
                panel,
                _NO_SELECTION_MESSAGE if canvas is not None else _NO_WORLD_MESSAGE,
                severity="note",
            )
            return
        box, problem = ribbon_defs.parse_selection_box(
            {label: field.value() for label, field in panel.fields.items()}
        )
        if box is None:
            self._set_selection_feedback(panel, problem)
            return
        was = corners[-1]
        if tuple(tuple(int(v) for v in point) for point in was) == box:
            # Nothing to do, and nothing to say: a field left without being
            # changed, or changed back to what it already held.
            self._set_selection_feedback(panel, "")
            return
        corners[-1] = box
        if not self._set_selection_corners(canvas, corners):
            return
        self._record(
            "selection-set-bounds",
            {
                "path": self.project_path,
                "dimension": self._dimension_name(),
                "minimum": list(box[0]),
                "maximum": list(box[1]),
                "boxes": len(corners),
            },
        )
        self._sync_world_state()
        # Written back explicitly rather than left to the idle pass, which skips
        # a field the user is still standing in -- and after Enter they are.  An
        # axis typed in reverse comes back ordered here, which is what makes the
        # ordering visible rather than silent.
        self._fill_selection_fields(panel, box)
        self._set_selection_feedback(
            panel, self._selection_note(len(corners)), severity="note"
        )
        size = tuple(high - low for low, high in zip(box[0], box[1]))
        self.notify(
            studio_label("Selection box moved", "選取框搬咗"),
            studio_text(
                f"The active box now runs from {box[0][0]}, {box[0][1]}, "
                f"{box[0][2]} to {box[1][0]}, {box[1][1]}, {box[1][2]} — "
                f"{size[0]} by {size[1]} by {size[2]} blocks."
            ),
            severity="success",
        )

    def _cmd_frame_dimension(self, key: str) -> None:
        """Move the camera so the whole of this dimension is in view.

        The extent framed is the *generated* one -- the chunks the world
        actually has -- rather than the dimension's nominal bounds, which on a
        Java world run to thirty million blocks in each direction and would
        frame a mostly empty rectangle with the player's build somewhere inside
        it as a single pixel.  Reading it walks the region files, the same cost
        ``select_all`` already pays, so this is a command the user asks for
        rather than something that runs on its own.
        """
        canvas = self._canvas()
        camera = getattr(canvas, "camera", None)
        if camera is None:
            self.notify(
                studio_label("There is no camera to move", "冇鏡頭可以郁"),
                studio_text(
                    "This world's 3D editor has not reported a camera, so there is "
                    "nothing to frame the dimension with."
                ),
                severity="warning",
            )
            return
        extent = self._dimension_extent()
        if extent is None:
            self.notify(
                studio_label("Nothing to frame", "冇嘢可以望"),
                studio_text(
                    f"{self._dimension_name() or 'This dimension'} has no generated "
                    "chunks, so there is nothing for the camera to frame."
                ),
                severity="warning",
            )
            return
        minimum, maximum = extent
        size = tuple(high - low for low, high in zip(minimum, maximum))
        aspect = float(getattr(camera, "aspect_ratio", 4 / 3) or 4 / 3)
        # Compared by name rather than by importing ``Projection``: this module
        # must stay importable on a machine whose OpenGL stack does not load,
        # and the enumeration lives behind that import.
        projection = str(getattr(getattr(camera, "projection_mode", None), "name", ""))
        if projection == "TOP_DOWN":
            location, radius = top_down_framing(minimum, maximum, aspect)
            camera.location_rotation = (location, _TOP_DOWN_ROTATION)
            camera.fov = radius
            capped = False
        else:
            far = 10000.0
            try:
                far = float(camera.perspective_clipping[1])
            except Exception:  # pragma: no cover - a camera without clipping
                log.debug("Could not read the camera's far clipping plane")
            location, rotation, capped = frame_camera(
                minimum,
                maximum,
                fov=float(getattr(camera, "perspective_fov", 70.0) or 70.0),
                aspect=aspect,
                far=far,
            )
            camera.location_rotation = (location, rotation)
        self._record(
            "camera-frame-dimension",
            {
                "path": self.project_path,
                "dimension": self._dimension_name(),
                "minimum": list(minimum),
                "maximum": list(maximum),
                "camera": [round(value, 3) for value in location],
                "clipped": capped,
            },
        )
        placed = tuple(int(round(value)) for value in camera.location)
        self.notify(
            studio_label("Framed the dimension", "望晒成個維度"),
            studio_text(
                f"{self._dimension_name() or 'This dimension'} spans {size[0]}x"
                f"{size[1]}x{size[2]} blocks from {minimum[0]}, {minimum[1]}, "
                f"{minimum[2]}; the camera is now at {placed[0]}, {placed[1]}, "
                f"{placed[2]}."
                + (
                    " It is larger than the viewport can draw at once, so the far "
                    "edge is beyond the render distance."
                    if capped
                    else ""
                )
            ),
            severity="warning" if capped else "success",
        )

    def _dimension_extent(
        self,
    ) -> Optional[Tuple[Tuple[int, int, int], Tuple[int, int, int]]]:
        """Return the block extent of the generated chunks in this dimension.

        ``None`` means the dimension has no generated chunks or could not be
        read, which the caller reports rather than framing a made-up box.  The
        horizontal extent comes from the chunks that exist and the vertical one
        from the world's own bounds, exactly as ``EditCanvas.select_all`` builds
        the selection it calls "everything".
        """
        canvas = self._canvas()
        level = getattr(canvas, "world", None)
        if level is None:
            return None
        try:
            dimension = canvas.dimension
            coords = tuple(level.all_chunk_coords(dimension))
        except Exception:  # pragma: no cover - a level being torn down
            log.debug("Could not read the dimension's chunks", exc_info=True)
            return None
        if not coords:
            return None
        try:
            span = int(level.sub_chunk_size)
            bounds = level.bounds(dimension)
            low_y = int(bounds.min[1])
            high_y = int(bounds.max[1])
        except Exception:  # pragma: no cover - a level without bounds
            log.debug("Could not read the dimension's bounds", exc_info=True)
            return None
        xs = [int(x) for x, _z in coords]
        zs = [int(z) for _x, z in coords]
        return (
            (min(xs) * span, low_y, min(zs) * span),
            ((max(xs) + 1) * span, high_y, (max(zs) + 1) * span),
        )

    def _cmd_move_gesture(self, key: str) -> None:
        """Put the user on the control that moves a selection point.

        These three are gestures rather than one-shot actions: the editor moves
        a point while a button is held, and there is no single distance a
        command could move it by.  So the command does the part that can be
        done -- it switches the editor to the Select tool, whose nudge buttons
        move the same points from the keyboard, and puts the keyboard on the
        right one -- and then quotes the viewport binding, read from the user's
        own key configuration rather than from the shipped default.
        """
        from amulet_map_editor.api.studio.context_menu import viewport_accelerator

        action, subject, button_name = _MOVE_COMMANDS[key]
        focused = self._focus_select_tool_button(button_name)
        binding = viewport_accelerator(action)
        movement = " ".join(
            part
            for part in (
                viewport_accelerator("ACT_MOVE_FORWARDS"),
                viewport_accelerator("ACT_MOVE_LEFT"),
                viewport_accelerator("ACT_MOVE_BACKWARDS"),
                viewport_accelerator("ACT_MOVE_RIGHT"),
            )
            if part
        )
        parts: List[str] = []
        if focused:
            parts.append(
                f"The Select tool is now showing; its nudge control for {subject} "
                "moves it one block at a time from the keyboard."
            )
        if binding:
            parts.append(
                f"In the viewport, hold {binding} and use the movement controls"
                + (f" ({movement})" if movement else "")
                + f" to drag {subject}."
            )
        else:
            parts.append(
                f"The viewport binding that drags {subject} is not set in this "
                "profile. Open Key configuration to give it one."
            )
        self.notify(
            studio_label(commands.label_for(key), ""),
            studio_text(" ".join(parts)),
            severity="info",
        )

    def _cmd_transform(self, key: str) -> None:
        """Rotate or flip the selection, through the editor's paste transform.

        The editor performs a rotation by floating a copy of the selection and
        transforming it before it is stamped down, which is why this is not a
        one-shot world edit: the copy has to be placed and confirmed.  So when a
        floating paste is already in flight the transform is applied to it, and
        otherwise the selection is copied and floated first -- both through the
        editor's own copy, paste, and transform, never through a second
        implementation of any of them.
        """
        canvas = self._canvas()
        paste = self._editor_tool("Paste")
        if paste is None:
            self.notify(
                studio_label(commands.label_for(key), ""),
                studio_text(
                    "This world's editor has no paste tool, which is what applies a "
                    "rotation, so there is nothing to transform with."
                ),
                severity="warning",
            )
            return
        if getattr(paste, "_is_enabled", False):
            self._apply_paste_transform(key, announce=True)
            return
        try:
            # ``report=False``: this copy is an internal step of a rotation, not
            # something the user asked for, and ``EditCanvas.copy`` otherwise
            # announces what reached the clipboard.  Somebody who pressed
            # Rotate should not be told about a clipboard they never used.
            copied = canvas.copy(report=False)
        except Exception:
            log.exception("Could not float a copy of the selection for %r", key)
            self.notify(
                studio_label(commands.label_for(key), ""),
                studio_text(
                    "The selection could not be copied, so there is nothing to "
                    "transform. The details are in the log."
                ),
                severity="error",
            )
            return
        # ``EditCanvas.copy`` contains the operation's own exceptions, so the
        # ``except`` above could never fire for a copy that failed *inside* the
        # operation -- which is every way a copy actually fails.  The outcome is
        # what says so.  ``None`` means a canvas that predates the outcome and is
        # not evidence either way, so it carries on exactly as before.
        if copied is not None and not copied:
            failed = bool(getattr(copied, "failed", False))
            detail = str(getattr(copied, "message", "") or "")
            log.warning(
                "The copy for %r did not complete: %s", key, detail or "no detail"
            )
            self.notify(
                studio_label(commands.label_for(key), ""),
                studio_text(
                    "The selection was not copied, so there is nothing to transform"
                    + (f": {detail}" if detail else ".")
                ),
                severity="error" if failed else "warning",
            )
            return
        try:
            canvas.paste_from_cache()
        except Exception:
            log.exception("Could not float the copied selection for %r", key)
            self.notify(
                studio_label(commands.label_for(key), ""),
                studio_text(
                    "The copied selection could not be handed to the paste tool, "
                    "so there is nothing to transform. The details are in the log."
                ),
                severity="error",
            )
            return
        # ``paste_from_cache`` posts the tool change, so the paste tool is not
        # holding the structure yet; the transform is applied once that event
        # has been handled and only if it really arrived.
        wx.CallAfter(self._apply_paste_transform, key, True)

    def _apply_paste_transform(self, key: str, announce: bool = False) -> None:
        """Apply one 90-degree rotation or one mirror to the floating paste."""
        paste = self._editor_tool("Paste")
        if paste is None or not getattr(paste, "_is_enabled", False):
            self.notify(
                studio_label(commands.label_for(key), ""),
                studio_text(
                    "The copied selection is not floating in the paste tool, so "
                    "there was nothing to transform."
                ),
                severity="warning",
            )
            return
        method = getattr(
            paste,
            "_on_rotate_right" if key == "rotate" else "_on_mirror_horizontal",
            None,
        )
        if not callable(method):
            self.notify(
                studio_label(commands.label_for(key), ""),
                studio_text(
                    "This build's paste tool exposes no "
                    f"{'rotation' if key == 'rotate' else 'mirror'} control."
                ),
                severity="warning",
            )
            return
        method(None)
        self._record(
            key,
            {
                "path": self.project_path,
                "dimension": self._dimension_name(),
                "rotation": list(
                    getattr(getattr(paste, "_rotation", None), "value", ())
                ),
                "scale": list(getattr(getattr(paste, "_scale", None), "value", ())),
            },
        )
        self._sync_world_state()
        if not announce:
            return
        verb = "rotated 90° to the right" if key == "rotate" else "mirrored"
        self.notify(
            studio_label("Paste transform", "貼上變換"),
            studio_text(
                f"The floating selection was {verb}. Place it in the viewport and "
                "confirm the paste to write it into the world."
            ),
            severity="success",
        )

    # -- view commands -------------------------------------------------------
    def _cmd_projection(self, _key: str) -> None:
        """Switch the projection, on the real camera when there is one."""
        status = self.workspace.status
        current = status.projection()
        following = "top" if current == "3d" else "3d"
        status.set_projection(following, notify=True)
        applied = self._set_camera_projection(following)
        self.notify(
            studio_label("Projection", "投影"),
            studio_text(
                f"The viewport is now {'top-down' if following == 'top' else '3D'}."
                + (
                    ""
                    if applied
                    else " No 3D editor is attached, so only the Studio viewport "
                    "changed."
                )
            ),
        )

    def _set_camera_projection(self, mode: str) -> bool:
        """Point the editor's own camera at ``mode``; say whether one took it."""
        canvas = self._canvas()
        if canvas is None:
            return False
        try:
            from amulet_map_editor.api.opengl.camera import Projection

            canvas.camera.projection_mode = (
                Projection.TOP_DOWN if mode == "top" else Projection.PERSPECTIVE
            )
        except Exception:
            log.exception("Could not set the editor camera projection to %r", mode)
            return False
        return True

    def _cmd_camera_speed(self, _key: str) -> None:
        """Match the editor's camera to the Studio slider, and say where it is.

        The slider is the control the user adjusts, so its value is what the
        real camera is set to rather than the other way round; without an
        editor attached the slider is still the honest answer for the Studio's
        own viewport, and the notification says which of the two happened.
        """
        status = self.workspace.status
        slider = status.speed_slider
        slider.SetFocus()
        speed = status.speed()
        canvas = self._canvas()
        applied = False
        if canvas is not None:
            try:
                canvas.camera.move_speed = float(speed)
                applied = True
            except Exception:
                log.exception("Could not set the editor camera speed to %r", speed)
        self.notify(
            studio_label("Camera speed", "鏡頭速度"),
            studio_text(
                (
                    f"The editor camera now moves at {speed} blocks per second. "
                    if applied
                    else f"The Studio viewport is set to {speed} blocks per second; "
                    "no 3D editor is attached to take it. "
                )
                + "The status bar slider has the keyboard."
            ),
        )

    def _cmd_set_dimension(self, _key: str) -> None:
        """Switch the world -- and the renderer -- to another dimension."""
        wanted = self._ribbon_dimension()
        ctx = context.current()
        target = self._dimension_key(wanted, ctx.dimensions)
        if not target:
            listed = ", ".join(ctx.dimensions) if ctx.dimensions else ""
            self.notify(
                studio_label("That dimension is not in this world", "呢個維度唔喺度"),
                studio_text(
                    (
                        f"{wanted!r} is not a dimension of {self.doc_title}."
                        if wanted
                        else "Choose a dimension in the ribbon first."
                    )
                    + (
                        f" This world reports {listed}."
                        if listed
                        else " This world reports no dimensions at all."
                    )
                ),
                severity="warning",
            )
            return
        canvas = self._canvas()
        applied = False
        # Why it did not move, not merely that it did not.  These were one flag,
        # and the sentence attached to it said "No 3D editor is attached" -- so
        # an editor that *was* attached and had just refused the switch reported
        # a reason the user could see was false by looking at the viewport it
        # was drawn in.
        refused = False
        if canvas is not None:
            try:
                canvas.dimension = target
                applied = True
            except Exception:
                refused = True
                log.exception("The editor refused to switch to dimension %r", target)
        context.set_dimension(target)
        self._select_navigator_dimension(target)
        self._record(
            "set-dimension",
            {"path": self.project_path, "dimension": target, "renderer": applied},
        )
        self._sync_world_state()
        info = context.current().dimension_named(target)
        detail = ""
        if info is not None and info.counted:
            detail = f" It holds {info.chunk_count:,} chunks"
            if info.has_range:
                detail += f" between y {info.min_y} and y {info.max_y}"
            detail += "."
        if refused:
            # The renderer is still showing the dimension it was showing, so
            # saying "Editing <target>" would name a dimension the user is not
            # looking at and cannot edit.
            self.notify(
                studio_label("The dimension did not change", "維度冇轉到"),
                studio_text(
                    f"The 3D editor refused to switch to {target}, so it is still "
                    f"showing {self._dimension_name() or 'the previous dimension'}. "
                    "The details are in the log."
                ),
                severity="error",
            )
            return
        self.notify(
            studio_label("Dimension", "維度"),
            studio_text(
                f"Editing {target}."
                + detail
                + (
                    ""
                    if applied
                    else " No 3D editor is attached, so the renderer did not move."
                )
            ),
            severity="success",
        )

    def _ribbon_dimension(self) -> str:
        """Return the dimension the ribbon's dropdown is currently showing.

        The widget's own value is preferred because it holds the *name* the user
        picked -- ``minecraft:the_nether`` -- while the ribbon's stored value is
        the short identifier the shipped option list was written with.  A world
        whose dimensions the shipped list never anticipated is matchable from
        the first and not from the second.
        """
        choice = self._ribbon_choice("Dimension")
        if choice is not None:
            value = str(getattr(choice, "value", "") or "")
            if value:
                return value
        return self._ribbon_value("Dimension")

    @staticmethod
    def _dimension_key(value: str, dimensions: Tuple[str, ...]) -> str:
        """Resolve a dropdown value against the dimensions the world reports.

        The ribbon ships short values (``nether``) while a level names its
        dimensions in full (``minecraft:the_nether``), so the match is made
        against the world's real list rather than by assuming either spelling.
        Nothing is invented: a value that matches no real dimension resolves to
        an empty string and the caller says so.
        """
        wanted = str(value or "").strip().lower()
        if not wanted or not dimensions:
            return ""
        for name in dimensions:
            if name.lower() == wanted:
                return name
        for name in dimensions:
            tail = name.lower().rpartition(":")[2]
            if tail == wanted or tail.endswith(f"_{wanted}") or wanted in name.lower():
                return name
        return ""

    def _select_navigator_dimension(self, name: str) -> None:
        """Point the navigator at ``name``, whatever spelling its rows use."""
        try:
            navigator = self.workspace.navigator
            for entry in navigator.dimensions:
                if name in (entry.key, entry.label):
                    navigator.select_dimension(entry.key)
                    return
        except Exception:  # pragma: no cover - a navigator mid-rebuild
            log.debug("Could not reveal %r in the navigator", name, exc_info=True)

    def _cmd_toggle_pane(self, _key: str) -> None:
        self.workspace.toggle_properties()
        self.notify(
            studio_label("Properties pane", "屬性面板"),
            studio_text(
                "The properties pane is now "
                + ("visible." if self.workspace.properties_visible() else "hidden.")
            ),
        )

    def _cmd_toggle_ribbon(self, _key: str) -> None:
        self.workspace.toggle_ribbon()

    def _cmd_reset_overlays(self, _key: str) -> None:
        """Put every movable heads-up overlay back where the design puts it.

        The grab handles offer this from the keyboard as Shift+Home, which is
        no use at all to somebody who has dragged one somewhere unhelpful with
        the pointer and never focused a handle in their life.  This is the same
        action from the viewport's own menu and from the command palette.
        """
        self.workspace.viewport.reset_overlay_layout()
        self._record("appearance", {"overlays": "reset"})
        self.notify(
            studio_label("Overlay positions", "浮標位置"),
            studio_text(
                "Every heads-up overlay is back where it shipped.",
                "所有浮標都返返原本位置喇。",
            ),
        )

    def _cmd_toggle_theme(self, _key: str) -> None:
        theme = "light" if tokens.is_dark() else "dark"
        preferences.update(theme=theme)
        self.refresh_theme()
        self._record("appearance", {"theme": theme})
        self.notify(
            studio_label("Theme", "主題"),
            studio_text(f"The interface is now using the {theme} theme."),
            severity="success",
        )

    def _cmd_set_density(self, _key: str) -> None:
        value = self._ribbon_value("Density")
        if value not in _DENSITIES:
            current = tokens.density()
            index = _DENSITIES.index(current) if current in _DENSITIES else 1
            value = _DENSITIES[(index + 1) % len(_DENSITIES)]
        preferences.update(density=value)
        self.refresh_theme()
        self._record("appearance", {"density": value})
        self.notify(
            studio_label("Density", "密度"),
            studio_text(f"Controls are now {value}; every surface resized with it."),
            severity="success",
        )

    def _cmd_set_export_format(self, _key: str) -> None:
        """Say which exporter Export will now run, and retarget a live one.

        The dropdown shipped raising nothing at all, which is how it came to
        decide nothing: a control that stores a value nobody reads is a control
        that operates and means nothing.  It now does the two things a format
        choice can honestly do -- name the exporter it has chosen, and, when the
        Export tool is already the tool on screen, switch that tool over to it
        rather than leaving the user looking at a chooser disagreeing with the
        ribbon above it.
        """
        value = self._ribbon_value("Format")
        operation = ribbon_defs.structure_format_operation(value)
        label = ribbon_defs.structure_format_label(value) or value
        if not operation:
            # The same two refusals ``_tool_message`` tells apart, told apart
            # here for the same reason: listing the writable formats at somebody
            # whose dropdown could not be read sends them to pick again, which
            # is the one thing that cannot help.
            self.notify(
                studio_label("Export format", "匯出格式"),
                studio_text(
                    (
                        f"No exporter is registered for the format {value!r}, so "
                        "Export cannot write it. The formats this build can "
                        "write are "
                        + ", ".join(ribbon_defs.structure_format_values())
                        + "."
                    )
                    if value
                    else (
                        "The ribbon's Format dropdown could not be read, so no "
                        "format is chosen and Export has nothing to write."
                    )
                ),
                severity="warning",
            )
            return
        retargeted = False
        if self._active_tool_name() == _COMMAND_TOOLS["export"]:
            retargeted = self._activate_tool(
                _COMMAND_TOOLS["export"], {"operation": operation}
            )
        showing = self._selected_exporter()
        if retargeted and not _same_operation(showing, operation):
            # Asked back rather than assumed: the tool may refuse, and a
            # dropdown reporting a switch that did not happen is the same defect
            # one layer along.
            self.notify(
                studio_label("Export format", "匯出格式"),
                studio_text(
                    f"The Export tool was asked for {operation} and is showing "
                    f"{showing or 'no exporter'}. Press Export to try again."
                ),
                severity="warning",
            )
            return
        self.notify(
            studio_label("Export format", "匯出格式"),
            studio_text(
                f"Export will write {label} through the {operation} exporter."
                + (" The Export tool has switched to it." if retargeted else "")
            ),
            severity="success",
        )

    def _cmd_open_palette(self, _key: str) -> None:
        self.open_palette()

    def _cmd_open_registered_surface(self, key: str) -> None:
        self.open_surface(_OPEN_COMMANDS[key])

    def _ribbon_value(self, label: str) -> str:
        """Return the value behind one ribbon dropdown, or an empty string."""
        try:
            return self.workspace.ribbon.selected_value(label)
        except Exception:  # pragma: no cover - a ribbon without that dropdown
            log.exception("Could not read the ribbon dropdown %r", label)
            return ""

    def _export_operation(self) -> Tuple[str, str, str]:
        """Return ``(value, label, operation)`` for the chosen export format.

        The value is read from the ribbon and mapped through
        :data:`~amulet_map_editor.api.studio.ribbon_defs.STRUCTURE_FORMATS`.  An
        unmapped value comes back with an empty operation rather than the first
        exporter, because a silent default here is exactly what shipped: four
        options, one destination, and a success toast naming the destination
        back at somebody who had chosen one of the other three.

        Reading *nothing* is refused on the same grounds, and used not to be.
        An unreadable ribbon fell back to ``STRUCTURE_FORMATS[0]``, which built
        that defect again one layer up: the tool was asked for ``Export
        Construction``, the history entry recorded ``format: construction``, and
        the toast said "writing construction (.construction)" -- three confident
        statements about a choice nobody had made.  ``_ribbon_value`` answers
        ``""`` when the read raises, so this is the shape a workspace whose
        ribbon has gone, or one still building when a command arrives, arrives
        in.  Nothing is now nothing, and every caller already handles it.
        """
        value = self._ribbon_value("Format")
        return (
            value,
            ribbon_defs.structure_format_label(value) or value,
            ribbon_defs.structure_format_operation(value),
        )

    def _selected_exporter(self) -> str:
        """Return the operation the Export tool's own chooser is showing."""
        tool = self._editor_tool(_COMMAND_TOOLS["export"])
        if tool is None:
            return ""
        try:
            return str(getattr(tool, "active_operation_name", "") or "")
        except Exception:  # pragma: no cover - a tool without its chooser yet
            log.debug("Could not read the selected exporter", exc_info=True)
            return ""

    # -- commands the world editor owns --------------------------------------
    def _cmd_editor(self, key: str) -> None:
        """Hand a command to the live editor and report what it did."""
        action = _EDITOR_ACTIONS.get(key)
        before = self._history_counts()
        if action is not None and self._editor_call(action):
            self._after_editor_command(key, before)
            return
        fallback = _COMMAND_SURFACES.get(key)
        if fallback:
            self.notify(
                studio_label(commands.label_for(key), ""),
                studio_text(
                    "This world's 3D editor could not run that, so its options "
                    "window is opening instead. Nothing has been changed."
                ),
                severity="warning",
            )
            self.open_surface(fallback)
            return
        self.notify(
            studio_label(commands.label_for(key), ""),
            studio_text(
                f"The open project has no editor able to run {key!r}. Open the 3D "
                "editor tab for this world and try again."
            ),
            severity="warning",
        )

    def _cmd_tool(self, key: str) -> None:
        """Put the user in the editor tool that performs this command.

        Importing a file, exporting a selection, and running an operation are
        all carried out by a tool that asks for a path or a plugin as it opens.
        Activating that tool *is* the command: it is what the editor's own
        buttons do, and the alternative -- guessing a path or a plugin on the
        user's behalf -- would be inventing the one value they came to supply.

        Export is the exception, and it is not an invention: the Format
        dropdown beside the button is the value the user came to supply, and it
        is carried into the tool as the operation to select.  Without it the
        tool started on whichever exporter its chooser sorted first -- which is
        ``Export Construction``, because that plugin's name begins with a tab --
        so three of the four formats on offer wrote a fourth kind of file.
        """
        name = _COMMAND_TOOLS[key]
        state = None
        if key == "export":
            _value, _label, operation = self._export_operation()
            state = {"operation": operation} if operation else None
        tool = self._editor_tool(name)
        if tool is None or not self._activate_tool(name, state):
            fallback = _COMMAND_SURFACES.get(key)
            if fallback:
                self.notify(
                    studio_label(commands.label_for(key), ""),
                    studio_text(
                        f"This world's editor has no {name} tool, so its options "
                        "window is opening instead. Nothing has been changed."
                    ),
                    severity="warning",
                )
                self.open_surface(fallback)
                return
            self.notify(
                studio_label(commands.label_for(key), ""),
                studio_text(
                    f"This world's editor has no {name} tool, so there is nothing "
                    "to run."
                ),
                severity="warning",
            )
            return
        payload: Dict[str, Any] = {
            "path": self.project_path,
            "dimension": self._dimension_name(),
            "tool": name,
            "selection_boxes": len(self._selection_corners()),
        }
        severity = "success"
        if key == "export":
            value, _label, operation = self._export_operation()
            payload["format"] = value
            payload["exporter"] = operation
            # The colour has to agree with the sentence.  Both refusals below
            # explain themselves in the body and were posted green, which reads
            # to a user exactly as the original defect did: the words said
            # nothing had been written and the severity said it had worked.
            if not operation or not _same_operation(
                self._shown_operation_name(tool), operation
            ):
                severity = "warning"
        self._record(key, payload)
        if key == "runOperation":
            wx.CallAfter(self._run_active_operation, tool)
            return
        self.notify(
            studio_label(commands.label_for(key), ""),
            studio_text(self._tool_message(key, name, tool)),
            severity=severity,
        )

    def _shown_operation_name(self, tool: Any) -> str:
        """Return the operation name a tool's chooser is showing a user.

        The *name*, not the identifier behind it.  The identifier is a dotted
        module path, so the sentence built from it read "The selected exporter
        is amulet_map_editor.programs.edit.plugins.operations.stock_plugins.
        export_operations.construction." to somebody who had picked
        "construction (.construction)" from a list.  ``active_operation_name``
        exists for exactly this and says so in its own docstring; the identifier
        is kept as the fallback so a tool that has one and no name still names
        something.
        """
        return str(getattr(tool, "active_operation_name", "") or "") or str(
            getattr(tool, "active_operation_id", "") or ""
        )

    def _tool_message(self, key: str, name: str, tool: Any) -> str:
        """Return what to say once a tool has been brought to the front.

        For Export this sentence has to name the format the user chose, and it
        has to be the one the tool is genuinely on rather than the one it was
        asked for.  It said neither: it read the chooser -- correctly -- and the
        chooser had never been told anything, so a user who picked
        ``schematic (.schematic)`` was told "Export Construction" and had no way
        to tell the difference from the message alone.
        """
        boxes = len(self._selection_corners())
        if key == "importFile":
            return (
                "The Import tool is asking for a structure file. The file you "
                "choose is floated in the viewport for you to place."
            )
        chosen = self._shown_operation_name(tool)
        opening = (
            f"The {name} tool is now showing, with the "
            f"{boxes} selected {'box' if boxes == 1 else 'boxes'} as its input"
        )
        if key != "export":
            return opening + (
                f". The selected exporter is {chosen}." if chosen else "."
            )
        value, label, wanted = self._export_operation()
        if not wanted:
            # Two different refusals, and telling a user the wrong one sends
            # them to fix the wrong thing: an unreadable ribbon is not a format
            # they picked badly, and there is no other format they could pick
            # that would help.
            reason = (
                f"No exporter is registered for the format {value!r}"
                if value
                else "The ribbon's Format dropdown could not be read, so no "
                "format is chosen"
            )
            return (
                f"{opening}. {reason}. The tool is showing "
                f"{chosen or 'no exporter'}; check the exporter in the tool "
                "before running it."
            )
        if not _same_operation(chosen, wanted):
            return (
                f"{opening}. It was asked to write {label} through {wanted} and "
                f"is showing {chosen or 'no exporter'} instead, so check the "
                "exporter in the tool before running it."
            )
        return f"{opening}, writing {label} through the {chosen} exporter."

    def _run_active_operation(self, tool: Any) -> None:
        """Run whatever operation the editor's Operation tool has selected."""
        active = getattr(tool, "_active_operation", None)
        runner = getattr(active, "_run_operation", None)
        chosen = self._shown_operation_name(tool)
        if not callable(runner):
            self.notify(
                studio_label("Operations", "操作"),
                studio_text(
                    "The Operation tool is now showing. Choose an operation in it "
                    "and this command will run the one you chose."
                    + (f" Nothing is selected yet." if not chosen else "")
                ),
                severity="warning" if not chosen else "info",
            )
            return
        # ``runOperation`` needs only ``editor`` in ``commands.REQUIREMENTS``,
        # deliberately: the command's first job is to bring the Operation tool
        # to the front, and gating that on a selection would stop the user
        # reaching the chooser until after they had selected something -- the
        # wrong way round for anybody who wants to see what the operations are.
        # Running one is the other half, and that half does need a selection,
        # because every operation is handed ``selection.selection_group`` and an
        # empty group means it acts on nothing.  So the tool is shown and the
        # run is declined, naming the tool's own Run button so an operation that
        # genuinely ignores the selection is still reachable.
        if not self._selection_corners():
            self.notify(
                studio_label("Operations", "操作"),
                studio_text(
                    f"The Operation tool is now showing with {chosen or 'an operation'} "
                    "selected, and it was not run because nothing is selected -- an "
                    "operation is given the selection to work on. Select a region and "
                    "run it again, or use the tool's own Run button if this operation "
                    "does not need one."
                ),
                severity="warning",
            )
            return
        before = self._history_counts()
        outcome = runner(None)
        # ``failed`` is read off the outcome rather than imported, so this keeps
        # working against a panel whose ``_run_operation`` returns nothing --
        # which is what every one of them did until the canvas learnt to report.
        if getattr(outcome, "failed", False):
            detail = str(getattr(outcome, "message", "") or "")
            log.warning("The operation %r did not complete: %s", chosen, detail)
            self._record(
                "runOperation",
                {
                    "path": self.project_path,
                    "dimension": self._dimension_name(),
                    "subject": chosen or "operation",
                    "undo_points_before": before[0],
                    "undo_points_after": self._history_counts()[0],
                    "failed": True,
                    "error": detail,
                },
            )
            self._sync_world_state()
            self.notify(
                studio_label("Operations", "操作"),
                studio_text(
                    f"{chosen or 'The operation'} stopped with an error, so nothing "
                    f"was written into {self.doc_title}"
                    + (f": {detail}" if detail else ".")
                ),
                severity="error",
            )
            return
        self._after_editor_command(
            "runOperation", before, subject=chosen or "operation"
        )

    def _after_editor_command(
        self,
        key: str,
        before: Tuple[int, int],
        subject: str = "",
    ) -> None:
        """Record, re-read, and report what a delegated command changed.

        The world's own undo depth before and after is the evidence: an
        operation that created an undo point genuinely changed something, and
        one that did not says so rather than reporting a success the user cannot
        see in the viewport.

        It is not evidence for every command, though.  A plugin reload does not
        touch the world at all, so it reports from the operation list it came
        back with; it used to fall off the end of this function and say nothing.

        Copy is not answered here at all, and deliberately so.  It writes
        nothing to the world either, but the wrong thing about reporting it
        from this function was never the evidence -- it was the layer.  This
        function runs only for a command the shell routed, and the Select
        tool's Copy button and the 3D editor's Edit ▸ Copy both call
        ``EditCanvas.copy`` directly.  The report lives on that method now, so
        every route speaks once; see :data:`_EDITOR_REPORTED_COMMANDS`.
        """
        after = self._history_counts()
        level = self._level()
        changed = bool(getattr(level, "changed", False)) if level is not None else False
        self._record(
            key,
            {
                "path": self.project_path,
                "dimension": self._dimension_name(),
                "undo_points_before": before[0],
                "undo_points_after": after[0],
                "redo_points_after": after[1],
                "world_changed": changed,
                "subject": subject,
            },
        )
        # The saved mark and the revision count are both derived from the level
        # inside the refresh below, so nothing is asserted about them here: a
        # command that reported "saved" and a world that still says it changed
        # would be two answers to one question.
        self._sync_world_state()
        if key in ("undo", "redo"):
            self.notify(
                studio_label("Undo" if key == "undo" else "Redo", ""),
                studio_text(
                    f"{self.doc_title} is now {after[0]} undo "
                    f"{'point' if after[0] == 1 else 'points'} deep, with "
                    f"{after[1]} to redo."
                ),
                severity="success",
            )
            return
        if key == "selectAll":
            ctx = context.current()
            self.notify(
                studio_label("Select all", "全選"),
                (
                    studio_text(
                        f"Selected every generated chunk in {ctx.dimension}: "
                        f"{ctx.selection_volume:,} blocks."
                        if ctx.has_selection
                        else f"{ctx.dimension or 'This dimension'} has no generated "
                        "chunks, so nothing was selected."
                    )
                ),
                severity="success" if ctx.has_selection else "warning",
            )
            return
        if key == "goto":
            location = self._camera_block(self._canvas())
            self.notify(
                studio_label("Teleport", "傳送"),
                (
                    studio_text(
                        f"The camera is at {location[0]}, {location[1]}, {location[2]}."
                        if location is not None
                        else "The camera did not report a position."
                    )
                ),
            )
            return
        if key in _EDITOR_REPORTED_COMMANDS:
            # The editor's own method has already spoken from its own evidence.
            return
        if key == "reloadPlugins":
            self._report_plugin_reload()
            return
        # The evidence check and the report it guards are asked the *same*
        # question, deliberately.  They were not: the guard asked only about
        # ``_MUTATING_COMMANDS`` while the report below fired for a ``subject``
        # as well, so ``runOperation`` -- the one command that hands the world
        # to an arbitrary plugin -- walked straight past the check and
        # announced that an operation recording no undo point had "finished".
        # A plugin that silently did nothing, or one whose exception
        # ``EditCanvas.run_operation`` swallowed, therefore reported success in
        # exactly the shape the undo-depth evidence exists to prevent.  Two
        # conditions phrased differently is how that drift happened, so there
        # is now one.
        if (key in _MUTATING_COMMANDS or subject) and after[0] == before[0]:
            self.notify(
                studio_label(commands.label_for(key), ""),
                studio_text(
                    f"The editor ran {subject or 'that'} but the world recorded no "
                    "new undo point, so nothing in it changed."
                ),
                severity="warning",
            )
            return
        if key in _MUTATING_COMMANDS or subject:
            self.notify(
                studio_label(commands.label_for(key), ""),
                studio_text(
                    f"{subject or commands.label_for(key)} finished; "
                    f"{self.doc_title} is now {after[0]} undo "
                    f"{'point' if after[0] == 1 else 'points'} deep."
                ),
                severity="success",
            )

    # -- what the read-only command says -------------------------------------
    # Copy's report used to live here.  It moved to ``EditCanvas.copy``, which
    # is the layer the Select tool's Copy button and the 3D editor's Ctrl+C
    # share with the shell's own ``copy`` command; a report here only ever
    # reached the third of those.  See :data:`_EDITOR_REPORTED_COMMANDS`.
    def _report_plugin_reload(self) -> None:
        """Say how many operations came back, or that none did.

        A reload that found nothing -- because a plugin in the operations
        folder failed to import and took the scan down with it -- looked
        exactly like a reload that found everything, which is to say it looked
        like nothing at all.
        """
        names = self._loaded_operation_names()
        if names is None:
            self.notify(
                studio_label("Operations reloaded", "重新載入咗操作"),
                studio_text(
                    "The editor reloaded its Python operations but did not say "
                    "which ones it found. Open the Operation tool to see what "
                    "is there."
                ),
                severity="warning",
            )
            return
        if not names:
            self.notify(
                studio_label("No operations found", "搵唔到操作"),
                studio_text(
                    "The editor reloaded its Python operations and found none. "
                    "Check the operations folder for a plugin that failed to "
                    "import."
                ),
                severity="warning",
            )
            return
        self.notify(
            studio_label("Operations reloaded", "重新載入咗操作"),
            studio_text(
                f"The editor reloaded its Python operations; {len(names)} "
                f"{'is' if len(names) == 1 else 'are'} available."
            ),
            severity="success",
        )

    def _loaded_operation_names(self) -> Optional[Tuple[str, ...]]:
        """Return the operations the editor is offering, or ``None``.

        ``None`` rather than an empty tuple when the tool could not be asked,
        because "the editor offers no operations" and "nothing could be asked"
        are different sentences and only one of them is a problem to go and
        look at.
        """
        tool = self._editor_tool("Operation")
        names = getattr(tool, "operation_names", None) if tool is not None else None
        if names is None:
            return None
        try:
            return tuple(str(name) for name in names)
        except Exception:  # pragma: no cover - a chooser mid-rebuild
            log.debug("Could not read the loaded operations", exc_info=True)
            return None

    # -- reaching the live editor --------------------------------------------
    def _canvas(self) -> Any:
        """Return the live 3D editor canvas, or ``None`` when there is none."""
        return self._frame_call("active_editor_canvas")

    def _level(self) -> Any:
        """Return the open ``BaseLevel``, or ``None`` when no world is loaded.

        The canvas answers first because it is what every editing operation runs
        against; the notebook page is the fallback for a world whose 3D editor
        is not the selected program, so a surface can still read the world it
        has open even when there is nothing to edit it with.
        """
        canvas = self._canvas()
        level = getattr(canvas, "world", None)
        if level is not None:
            return level
        page = self._frame_call("active_world_page")
        return getattr(page, "world", None)

    def _editor_tool(self, name: str) -> Any:
        """Return one of the editor's tools by name, or ``None``.

        The tools are sizers rather than windows, so the descendant walk below
        never reaches them; this mapping is the only route and is tried first.
        """
        canvas = self._canvas()
        if canvas is None:
            return None
        try:
            return canvas.tools.get(str(name))
        except Exception:  # pragma: no cover - a canvas without its tool sizer
            log.debug("Could not read the editor tools", exc_info=True)
            return None

    def _active_tool_name(self) -> str:
        """Return the name of the editor tool that is currently showing."""
        canvas = self._canvas()
        if canvas is None:
            return ""
        try:
            tools = canvas.tools
        except Exception:  # pragma: no cover - a canvas without its tool sizer
            log.debug("Could not read the editor tools", exc_info=True)
            return ""
        for name, tool in tools.items():
            try:
                windows = list(tool.windows())
            except Exception:  # noqa: BLE001 - a tool without its panels yet
                continue
            if windows and all(window.IsShown() for window in windows):
                return str(name)
        return ""

    def _activate_tool(self, name: str, state: Any = None) -> bool:
        """Ask the editor to switch to one of its tools; say whether it could.

        ``state`` is handed to the tool's own ``set_state`` by the tool manager,
        which is how a caller says *which* operation the tool should arrive on.
        The Export and Operation tools are choosers, and a chooser started with
        nothing to select lands on whatever sorts first.

        A true answer means the change was posted and the queue was drained, not
        that the tool changed: the switch belongs to somebody else's handler and
        it may refuse.  Every caller that reports an outcome therefore reads the
        canvas back afterwards rather than reporting this return value.
        """
        canvas = self._canvas()
        if canvas is None or self._editor_tool(name) is None:
            return False
        try:
            from amulet_map_editor.programs.edit.api.events import ToolChangeEvent

            wx.PostEvent(canvas, ToolChangeEvent(tool=str(name), state=state))
        except Exception:
            log.exception("Could not switch the editor to the %r tool", name)
            return False
        self._settle()
        return True

    @staticmethod
    def _settle(passes: int = 3) -> None:
        """Let the canvas handle the tool change that was just posted at it.

        A tool change is a posted event, so without this the next line reads the
        tool that was active a moment ago and reports it as the one that just
        started -- which is the difference between saying what happened and
        saying what was asked for.  It is the same reason
        :func:`amulet_map_editor.api.studio.editor_tools._post_tool_change`
        settles, and it is why the Export toast could name the previous exporter
        while the tool went on to select a different one.
        """
        app = wx.GetApp()
        if app is None:
            return
        for _pass in range(max(1, passes)):
            try:
                app.ProcessPendingEvents()
                wx.Yield()
            except Exception:  # noqa: BLE001 - yielding inside a yield
                return

    def _focus_select_tool_button(self, attribute: str) -> bool:
        """Show the Select tool and focus one of its nudge buttons.

        The tool is switched to first and unconditionally, because that is the
        part that is genuinely useful on its own: the nudge controls are only on
        screen while the Select tool is showing.  The button itself is focused
        afterwards, once the queued tool change has actually been handled, and
        only if the editor has enabled it -- those buttons stay disabled until a
        box is being edited, and focusing a disabled control does nothing while
        looking exactly like it worked.
        """
        tool = self._editor_tool("Select")
        button = getattr(tool, attribute, None) if tool is not None else None
        if button is None or not hasattr(button, "SetFocus"):
            return False
        if not self._activate_tool("Select"):
            return False
        wx.CallAfter(self._focus_window, button)
        return True

    @staticmethod
    def _focus_window(window: Any) -> None:
        """Focus a control, ignoring a disabled or already destroyed one."""
        try:
            if window.IsEnabled() and window.IsShownOnScreen():
                window.SetFocus()
        except RuntimeError:  # pragma: no cover - destroyed before the call ran
            pass

    def _selection_corners(self) -> Tuple[Tuple[Tuple[int, int, int], ...], ...]:
        """Return the editor's selection corners, or an empty tuple."""
        canvas = self._canvas()
        if canvas is None:
            return ()
        try:
            return tuple(canvas.selection.selection_corners)
        except Exception:  # pragma: no cover - a canvas mid-teardown
            log.debug("Could not read the editor selection", exc_info=True)
            return ()

    def _set_selection_corners(self, canvas: Any, corners: List[Any]) -> bool:
        """Write a new selection into the editor; report whether it took it."""
        if canvas is None:
            return False
        try:
            canvas.selection.selection_corners = tuple(corners)
        except Exception:
            log.exception("The editor refused a new selection")
            self.notify(
                studio_label("The selection did not change", "選取範圍冇改到"),
                studio_text(
                    "The 3D editor refused the new selection. The details are in "
                    "the log."
                ),
                severity="error",
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Selection > Coordinates: six boxes that must say what the world holds
    # ------------------------------------------------------------------
    def _selection_field_panel(self) -> Any:
        """Return the built Coordinates group, or ``None`` when it is not open.

        The ribbon builds only the showing tab's groups, so these six widgets
        exist exactly while the Selection tab is open.  ``None`` is an ordinary
        answer rather than a fault.
        """
        try:
            ribbon = self.workspace.ribbon
        except (AttributeError, RuntimeError):  # pragma: no cover - mid-teardown
            return None
        finder = getattr(ribbon, "group_panel", None)
        panel = finder(ribbon_defs.SELECTION_GROUP) if callable(finder) else None
        if panel is None or not getattr(panel, "fields", None):
            return None
        if any(
            label not in panel.fields for label in ribbon_defs.SELECTION_FIELD_LABELS
        ):
            return None
        return panel

    @staticmethod
    def _set_selection_feedback(
        panel: Any, message: str, *, severity: str = "error"
    ) -> None:
        """Put one sentence under the six boxes, or take it away.

        ``severity`` decides the ink only.  A refusal is painted in the error
        role; the standing note saying which of several boxes is being shown,
        and the line saying nothing is selected, are states rather than faults
        and are painted like ordinary text.
        """
        setter = getattr(panel, "set_feedback", None)
        if not callable(setter):
            return
        try:
            setter(message, severity=severity)
        except RuntimeError:  # pragma: no cover - the group went away mid-pass
            return

    @staticmethod
    def _selection_note(count: int) -> str:
        """Return the standing note for a selection of ``count`` boxes.

        Silence for one box: there is nothing to disambiguate and a permanent
        line under a working control is noise.  With more than one, which box
        these six numbers describe is a real question, and the answer has to be
        the box every other Selection command acts on -- the last -- or the
        numbers and the buttons beside them would be talking about different
        boxes.
        """
        return (
            ""
            if count <= 1
            else f"Showing box {count} of {count} — the active one, which Remove "
            "and Duplicate act on too."
        )

    def _fill_selection_fields(self, panel: Any, box: Any) -> None:
        """Write one selection box into the six widgets, unconditionally."""
        values = ribbon_defs.selection_box_values(box)
        for label, field in panel.fields.items():
            if label not in values:
                continue
            try:
                if field.value() != values[label]:
                    field.set_value(values[label])
                field.Enable(box is not None)
            except RuntimeError:  # pragma: no cover - destroyed mid-pass
                continue

    def _sync_selection_fields(self) -> None:
        """Make the six boxes show the selection the editor is really holding.

        Run from the idle enablement pass, so a box dragged in the viewport, an
        undo, or a command run from anywhere at all moves these numbers without
        the thing that moved the selection having to know they exist.

        The fields are rewritten **only when the selection has actually
        changed**.  That single condition does three jobs at once: it leaves a
        half-typed value alone instead of wiping it 150 milliseconds after the
        first keystroke; it leaves a refused value on screen to be corrected,
        beside the sentence explaining it; and it clears that sentence the
        moment the world moves underneath, because a complaint about text the
        user can no longer see is its own small lie.
        """
        panel = self._selection_field_panel()
        if panel is None:
            # The tab moved away and took the six widgets with it.  Forgetting
            # the panel is what makes the next rebuilt grid a fresh one that has
            # to be filled, rather than one that matches a remembered box and is
            # therefore left showing whatever it was rebuilt with.
            self._selection_panel = None
            return
        corners = self._selection_corners()
        box = corners[-1] if corners else None
        if panel is self._selection_panel and box == self._selection_seeded:
            return
        self._selection_panel = panel
        self._selection_seeded = box
        self._fill_selection_fields(panel, box)
        # Two different empty states, said differently.  "Press Add box" is
        # useless advice with no world open, because Add box is greyed out too;
        # somebody following it would press a dead control and learn nothing.
        empty = (
            _NO_SELECTION_MESSAGE if self._canvas() is not None else _NO_WORLD_MESSAGE
        )
        for label, field in panel.fields.items():
            try:
                field.SetToolTip(
                    empty
                    if box is None
                    else (
                        f"{label} of the active selection box. Type a new value "
                        "and press Enter to move it."
                    )
                )
            except RuntimeError:  # pragma: no cover - destroyed mid-pass
                continue
        self._set_selection_feedback(
            panel,
            empty if box is None else self._selection_note(len(corners)),
            severity="note",
        )

    @staticmethod
    def _camera_block(canvas: Any) -> Optional[Tuple[int, int, int]]:
        """Return the block the camera is inside, or ``None`` when unreadable."""
        if canvas is None:
            return None
        try:
            x, y, z = canvas.camera.location
        except Exception:  # pragma: no cover - a canvas without a camera yet
            log.debug("Could not read the camera location", exc_info=True)
            return None
        return (math.floor(x), math.floor(y), math.floor(z))

    def _dimension_name(self) -> str:
        """Return the dimension being edited, as the world names it."""
        canvas = self._canvas()
        if canvas is not None:
            try:
                return str(canvas.dimension or "")
            except Exception:  # pragma: no cover - a canvas without a renderer
                pass
        return context.current().dimension

    def _history_counts(self) -> Tuple[int, int]:
        """Return the world's real ``(undo, redo)`` depth, or ``(0, 0)``."""
        history = getattr(self._level(), "history_manager", None)
        if history is None:
            return (0, 0)
        try:
            return (int(history.undo_count), int(history.redo_count))
        except Exception:  # pragma: no cover - a history mid-write
            log.debug("Could not read the world's undo depth", exc_info=True)
            return (0, 0)

    def _editor_targets(self, action: _EditorAction) -> Iterator[Any]:
        """Yield the objects a delegated command may be carried out by.

        The canvas first, because that is where the level's own operations
        live; then the tool the action names, because the chunk and operation
        actions are methods on a sizer that no window walk can reach; then the
        active program; then -- only when the action asked for it -- the world
        page's controls.
        """
        canvas = self._canvas()
        if canvas is not None:
            yield canvas
        if action.tool:
            tool = self._editor_tool(action.tool)
            if tool is not None:
                yield tool
        program = self._frame_call("active_editor_program")
        if program is not None:
            yield program
        if not action.descend:
            return
        page = self._frame_call("active_world_page")
        if page is None:
            return
        seen = 0
        stack: List[wx.Window] = [page]
        while stack and seen < _MAX_DESCENDANTS:
            window = stack.pop()
            seen += 1
            yield window
            try:
                stack.extend(window.GetChildren())
            except RuntimeError:  # pragma: no cover - window destroyed mid-walk
                continue

    def _frame_call(self, name: str) -> Any:
        """Call a frame accessor, returning ``None`` when the frame has none."""
        handler = getattr(self.frame, name, None)
        if not callable(handler):
            return None
        try:
            return handler()
        except Exception:
            log.exception("The frame accessor %r failed", name)
            return None

    def _editor_call(self, action: _EditorAction) -> bool:
        """Run the first matching editor method, reporting whether one ran."""
        for target in self._editor_targets(action):
            for name in action.names:
                method = getattr(target, name, None)
                if not callable(method):
                    continue
                if action.event:
                    method(None)
                else:
                    method()
                return True
        return False

    def _record(self, kind: str, payload: Dict[str, Any]) -> None:
        """Write one state change into the local, append-only history."""
        local_history.safe_record(
            f"studio-shell-{kind}",
            dict(payload),
            record_type=f"studio {kind}",
        )

    # ------------------------------------------------------------------
    # what the world can answer, and which controls that leaves live
    # ------------------------------------------------------------------
    def _command_state(self) -> _CommandState:
        """Read, from the live editor, what the open world can do right now."""
        level = self._level()
        if level is None:
            return _CommandState()
        canvas = self._canvas()
        undo, redo = self._history_counts()
        return _CommandState(
            project=True,
            editor=canvas is not None,
            selection=bool(self._selection_corners()),
            clipboard=self._clipboard_holds_a_structure(),
            undo=undo > 0,
            redo=redo > 0,
        )

    @staticmethod
    def _clipboard_holds_a_structure() -> bool:
        """Return whether anything has been copied into the editor's cache."""
        try:
            from amulet.api.structure import structure_cache

            return bool(structure_cache)
        except Exception:  # pragma: no cover - amulet-core unavailable
            return False

    def _refresh_enablement(self, *, force: bool = False) -> None:
        """Grey out every ribbon command whose precondition is unmet.

        A tile that stays pressable after its precondition has gone is the
        defect this exists to stop: the user presses it, the shell explains why
        it did nothing, and the control has taught them nothing they could not
        have been shown beforehand.  The disabled tile carries the reason in its
        own tooltip instead, so the answer is where the question is asked.

        The world's undo depth and its saved state ride along, because they
        change under exactly the same events -- and because the editor's own
        buttons change them without ever telling the shell, so a revision count
        refreshed only by Studio commands would be wrong the first time somebody
        used the Select tool's Delete button instead of the ribbon's.
        """
        try:
            if self.IsBeingDeleted():
                return
            ribbon = self.workspace.ribbon
        except (AttributeError, RuntimeError):  # pragma: no cover - mid-teardown
            return
        state = self._command_state()
        level = self._level()
        undo, redo = self._history_counts()
        changed = bool(getattr(level, "changed", False)) if level is not None else False
        signature = (
            state.signature(),
            undo,
            redo,
            changed,
            getattr(ribbon, "active_tab", ""),
            # The corners themselves, not merely whether there are any.  Every
            # other entry here is about what a command *may* do, and dragging a
            # box in the viewport changes none of them -- so with the state
            # alone this pass returned early and the six coordinate boxes never
            # moved while the selection they describe was being dragged.  They
            # are plain integer tuples: the editor's own setter coerces them on
            # the way in, so comparing two of them is a comparison and not a
            # numpy array's opinion about one.
            self._selection_corners(),
        )
        if not force and signature == self._enablement_signature:
            return
        self._enablement_signature = signature
        for group in self._ribbon_groups(ribbon):
            for tile in getattr(group, "tiles", ()):
                self._apply_enablement(tile, getattr(tile, "definition", None), state)
            for select in getattr(group, "selects", {}).values():
                self._apply_select_enablement(group, select, state)
        self._sync_dimension_choice(ribbon)
        self._sync_selection_fields()
        self._sync_revision(level, undo, changed)

    def _sync_revision(self, level: Any, undo: int, changed: bool) -> None:
        """Put the level's own undo depth on the breadcrumb and the status bar.

        The count is the number of undo points the open world holds, which is
        the same stack the undo command walks; a number the user can act on
        rather than a tally of something the Studio kept beside it.  With no
        world open both readouts are emptied rather than left showing the last
        world's history.
        """
        if level is None:
            marker, count = "", 0
        else:
            marker, count = ("unsaved" if changed else "saved"), undo
            if self.saved != (not changed):
                self.set_saved(not changed)
        for target in (
            getattr(self.workspace, "breadcrumb", None),
            getattr(self.workspace, "status", None),
        ):
            setter = getattr(target, "set_revision", None)
            if not callable(setter):
                continue
            try:
                setter(marker, count)
            except RuntimeError:  # pragma: no cover - destroyed mid-update
                continue

    def _ribbon_groups(self, ribbon: wx.Window) -> List[Any]:
        """Return the ribbon's built group panels, however deep they sit.

        Found by walking rather than by reading the bar's private list, so a
        change to how the bar stores its groups cannot silently leave every
        command enabled: a group panel is recognised by carrying the ribbon
        group it was built from.
        """
        found: List[Any] = []
        seen = 0
        stack: List[wx.Window] = [ribbon]
        while stack and seen < _MAX_DESCENDANTS:
            window = stack.pop()
            seen += 1
            if hasattr(window, "group") and hasattr(window, "tiles"):
                found.append(window)
                continue
            try:
                stack.extend(window.GetChildren())
            except RuntimeError:  # pragma: no cover - destroyed mid-walk
                continue
        return found

    def _apply_enablement(
        self, control: Any, definition: Any, state: _CommandState
    ) -> None:
        """Enable or disable one control, and keep its tooltip truthful."""
        key = str(getattr(definition, "command", "") or "")
        if not key:
            return
        unmet = state.unmet(commands.requirements(key))
        reason = commands.unavailable_hint(key, unmet)
        # The applied reason is remembered on the control so a tile that stays
        # disabled while the *reason* changes -- a world closing under a
        # selection that was already empty -- has its tooltip corrected too.
        if getattr(control, "_studio_unavailable", None) == reason:
            return
        control._studio_unavailable = reason
        try:
            control.Enable(not unmet)
            control.SetToolTip(reason or str(getattr(definition, "hint", "") or ""))
            control.Refresh()
        except RuntimeError:  # pragma: no cover - destroyed mid-pass
            return

    def _apply_select_enablement(
        self, group: Any, select: Any, state: _CommandState
    ) -> None:
        """Do the same for a ribbon dropdown that raises a command."""
        label = str(getattr(select, "label", "") or "")
        definition = next(
            (
                item
                for item in getattr(getattr(group, "group", None), "selects", ())
                if item.label == label
            ),
            None,
        )
        if definition is None or not getattr(definition, "command", ""):
            return
        self._apply_enablement(select, definition, state)

    def _ribbon_choice(self, label: str) -> Any:
        """Return the live dropdown widget behind one ribbon label."""
        try:
            ribbon = self.workspace.ribbon
        except (AttributeError, RuntimeError):  # pragma: no cover - mid-teardown
            return None
        for group in self._ribbon_groups(ribbon):
            choice = getattr(group, "selects", {}).get(str(label))
            if choice is not None:
                return choice
        return None

    def _sync_dimension_choice(self, _ribbon: wx.Window) -> None:
        """Offer the dimensions this world really has, not a shipped list.

        The ribbon ships the three vanilla dimensions because that is what the
        design drew.  A world with a datapack dimension has more, and a
        structure file has fewer, and offering either of them a choice their
        world cannot honour is exactly the invented value this interface is
        meant to stop showing.  The widget's own callback is taken over at the
        same time, because the shipped option table cannot translate a name it
        was never given.
        """
        choice = self._ribbon_choice("Dimension")
        if choice is None or not hasattr(choice, "set_options"):
            return
        ctx = context.current()
        if not ctx.open or not ctx.dimensions:
            return
        wanted = list(ctx.dimensions)
        if list(getattr(choice, "options", ())) != wanted:
            choice.set_options(wanted)
        if ctx.dimension and getattr(choice, "value", "") != ctx.dimension:
            choice.set_value(ctx.dimension)
        if getattr(choice, "on_change", None) is not self._on_dimension_chosen:
            choice.on_change = self._on_dimension_chosen

    def _on_dimension_chosen(self, _label: str) -> None:
        """Run the dimension command after a choice made in the ribbon."""
        self.run_command("setDimension")

    def _sync_world_state(self) -> None:
        """Re-read the world after a command and repaint what it says.

        Called once a command has finished rather than while it is running, so
        what every readout shows is what the world holds *now* -- an operation
        that ran and changed nothing leaves the numbers where they were, and one
        that changed something moves them.
        """
        context.refresh()
        self._refresh_enablement(force=True)

    # ------------------------------------------------------------------
    # accelerators
    # ------------------------------------------------------------------
    def install_accelerators(self) -> List[Tuple[int, int, int]]:
        """Bind one handler per real binding and return the rows for the table.

        Each key gets its own id so the accelerator and the menu row that draws
        it fire exactly the same action.  The palette's chord is absent on
        purpose: it is delivered by a character hook so that it still works
        while a text field has the keyboard, and a second route would open the
        palette twice on one keystroke.

        The rows are returned rather than installed here because the frame may
        have accelerators of its own; it owns the one table wx will consult.
        """
        for key in commands.bindable_keys():
            if key in self._accelerator_ids:
                continue
            identifier = int(wx.NewIdRef())
            self._accelerator_ids[key] = identifier
            self.frame.Bind(
                wx.EVT_MENU,
                lambda _event, name=key: self._run_accelerator(name),
                id=identifier,
            )
        return commands.accelerator_entries(self._accelerator_ids)

    def accelerator_table(self) -> wx.AcceleratorTable:
        """Return the accelerator table for a frame with no rows of its own."""
        self.install_accelerators()
        return commands.accelerator_table(self._accelerator_ids)

    def _run_accelerator(self, key: str) -> None:
        """Route one accelerator to the command or the surface it names."""
        if commands.command(key) is not None:
            self.run_command(key)
            return
        self.open_surface(key)

    # ------------------------------------------------------------------
    # appearance
    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        self.SetBackgroundColour(tokens.palette().surface)

    def _repaint(self) -> None:
        """Repaint this panel after a theme change somewhere else."""
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:  # pragma: no cover - already destroyed
            return
        self._apply_theme()
        self.Refresh()

    def refresh_theme(self) -> None:
        """Re-resolve the tokens and repaint every open Studio window.

        A dialog opened before a theme change would otherwise keep the old
        palette until it was closed and reopened, which looks like two
        applications sharing one window manager.  Every registered listener is
        told first, then every open top-level window that can repaint itself is
        asked directly, so a window that never registered is not left behind.
        """
        tokens.notify_theme_changed()
        self._apply_theme()
        for window in wx.GetTopLevelWindows():
            if window is self.frame:
                continue
            refresh = getattr(window, "refresh_theme", None)
            if not callable(refresh):
                continue
            try:
                refresh()
            except RuntimeError:  # pragma: no cover - closed mid-walk
                continue
            except Exception:
                log.exception("A Studio window could not repaint")
        self._refresh_frame_chrome()
        self.Layout()
        self.Refresh()

    def _refresh_frame_chrome(self) -> None:
        """Restyle the frame's own controls, which are not Studio widgets."""
        try:
            from amulet_map_editor.api.wx.material3 import apply_material3

            apply_material3(self.frame)
        except Exception:  # pragma: no cover - styling helper unavailable
            log.exception("Could not restyle the application frame")
