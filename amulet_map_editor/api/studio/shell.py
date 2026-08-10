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
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

import wx

from amulet_map_editor.api import local_history, preferences
from amulet_map_editor.api.studio import commands, surfaces, tokens
from amulet_map_editor.api.studio import recents
from amulet_map_editor.api.studio.backstage import BackstageView
from amulet_map_editor.api.studio.copy import studio_text
from amulet_map_editor.api.studio.title_bar import (
    StudioTitleBar,
    install_palette_shortcut,
)
from amulet_map_editor.api.studio.workspace import WorkspaceView

log = logging.getLogger(__name__)

__all__ = ["DEFAULT_PROJECT_TITLE", "StudioShell"]

#: What the shell calls a project nobody has named yet.
DEFAULT_PROJECT_TITLE = "Untitled project"

#: The interface densities, in the order the command cycles them.
_DENSITIES: Tuple[str, ...] = ("compact", "comfortable", "spacious")

#: How many descendant windows a delegated action will search before giving up.
#: A world page holds a few hundred controls; a bound stops a pathological tree
#: from freezing the interface while a keystroke is being routed.
_MAX_DESCENDANTS = 600


@dataclass(frozen=True)
class _EditorAction:
    """One command carried out by the live world editor rather than the shell.

    ``names`` are tried in order on the editor canvas and then on the active
    program.  ``event`` records that the target is a wx event handler and
    therefore takes an event argument, which is passed as ``None``.

    ``descend`` additionally searches the world page's own controls, because a
    few actions live on a tool panel rather than on the canvas.  It is off by
    default and named per action rather than applied to everything: a walk over
    every descendant looking for a method called ``save`` would eventually find
    one on something that is not the world.
    """

    names: Tuple[str, ...]
    event: bool = False
    descend: bool = False


#: Commands the world editor owns.  The Studio deliberately does not
#: reimplement them: undo depth, the clipboard, and chunk operations belong to
#: the level that is open, and a second implementation would be a second answer
#: to the same question.
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
        "reloadPlugins": _EditorAction(("reload_operations",), descend=True),
        "createChunks": _EditorAction(("_create_chunks",), event=True, descend=True),
        "deleteChunks": _EditorAction(("_delete_chunks",), event=True, descend=True),
        "deleteUnselectedChunks": _EditorAction(
            ("_prune_chunks",), event=True, descend=True
        ),
        "importChunks": _EditorAction(("_import_chunks",), event=True, descend=True),
        "rotate": _EditorAction(("rotate",)),
        "flip": _EditorAction(("mirror", "flip")),
    }
)

#: Commands whose real controls live on a surface.  Used when the live editor
#: has no method for the action, so the user still lands on the window where the
#: action is configured instead of on a message saying nothing happened.
_COMMAND_SURFACES: Mapping[str, str] = MappingProxyType(
    {
        "export": "exportStructure",
        "importFile": "pendingImports",
        "importChunks": "importChunks",
        "runOperation": "operationOptions",
        "rotate": "stackArray",
        "flip": "stackArray",
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

#: Editor actions whose binding the user configures, quoted back when the
#: command is a press-and-hold gesture rather than something to run once.
_MOVE_COMMANDS: Mapping[str, Tuple[str, str]] = MappingProxyType(
    {
        "moveBox": ("ACT_BOX_CLICK", "the active selection box"),
        "movePoint1": ("ACT_BOX_CLICK", "the green selection point"),
        "movePoint2": ("ACT_BOX_CLICK_ADD", "the blue selection point"),
    }
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
        self._remove_palette_shortcut: Optional[Callable[[], None]] = (
            install_palette_shortcut(self, self.open_palette)
        )
        # Registered after every child exists so a theme change can never reach
        # a half-built shell.
        self._theme_unsubscribe: Optional[Callable[[], None]] = (
            tokens.register_theme_listener(self._repaint)
        )
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self._apply_theme()

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
        event.Skip()

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
                    studio_text("That project did not open", "呢個專案開唔到"),
                    f"{target} could not be loaded. The details are in the log.",
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
        self.set_saved(True)
        self.title_bar.set_title(self.doc_title)
        self.workspace.set_project(self.doc_title, self.project_path)
        self.backstage.set_project(
            True, self.doc_title, self.project_path, self.project_platform
        )
        self._remember_recent()
        self.show_workspace()

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
        self.show_backstage("home")

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
        """Host the real renderer inside the workspace viewport."""
        self.workspace.set_canvas(window)

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
        """Open one surface, and report honestly when it does not open."""
        return surfaces.open_surface(self, key)

    def open_palette(self) -> Optional[wx.Window]:
        """Open the command palette over every command, surface, and setting."""
        from amulet_map_editor.api.studio import palette_dialog

        return palette_dialog.open_palette(self)

    def notify(self, title: str, body: str, severity: str = "info") -> None:
        """Report a result without blocking anything the user is doing."""
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
            "projection": self._cmd_projection,
            "cameraSpeed": self._cmd_camera_speed,
            "setDimension": self._cmd_set_dimension,
            "togglePane": self._cmd_toggle_pane,
            "toggleRibbon": self._cmd_toggle_ribbon,
            "toggleTheme": self._cmd_toggle_theme,
            "setDensity": self._cmd_set_density,
            "openPalette": self._cmd_open_palette,
            "updateRestart": self._cmd_update_restart,
        }
        for key in _OPEN_COMMANDS:
            handlers[key] = self._cmd_open_registered_surface
        for key in _MOVE_COMMANDS:
            handlers[key] = self._cmd_move_gesture
        for key in _EDITOR_ACTIONS:
            handlers.setdefault(key, self._cmd_editor)
        for key in _COMMAND_SURFACES:
            handlers.setdefault(key, self._cmd_editor)
        return handlers

    def run_command(self, key: str) -> None:
        """Run one command, whatever asked for it."""
        resolved = commands.resolve(key)
        if not resolved:
            log.error("run_command was called without a command key")
            return
        handler = self._handlers.get(resolved)
        if handler is None:
            entry = commands.command(resolved)
            log.error("No Studio handler is registered for the command %r", resolved)
            self.notify(
                studio_text("That command is not connected", "呢個指令未接到"),
                f"Nothing is registered to run the command {resolved!r}"
                + (f" ({entry.label})." if entry is not None else "."),
                severity="warning",
            )
            return
        try:
            handler(resolved)
        except Exception:
            log.exception("The Studio command %r failed", resolved)
            self.notify(
                studio_text("That command failed", "呢個指令失敗咗"),
                f"Running {resolved!r} raised an error. The details are in the log.",
                severity="error",
            )

    def _command_label(self, key: str) -> str:
        """Return a command's registered label, falling back to its key."""
        entry = commands.command(key)
        return entry.label if entry is not None else key

    # -- project commands ----------------------------------------------------
    def _cmd_save(self, key: str) -> None:
        if not self._require_project(key):
            return
        if self._editor_call(_EDITOR_ACTIONS["save"]):
            self.set_saved(True)
            self._record("save", {"project": self.doc_title, "path": self.project_path})
            self.notify(
                studio_text("Saved", "已經儲存"),
                f"{self.doc_title} was written to disk.",
                severity="success",
            )
            return
        self.notify(
            studio_text("Nothing was saved", "冇嘢儲存到"),
            "No world editor is attached to this project, so there was nothing "
            "to write.",
            severity="warning",
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
                studio_text("The operations folder is unknown", "搵唔到操作資料夾"),
                "This build has no data directory configured, so the operations "
                "folder cannot be located.",
                severity="warning",
            )
            return
        target = os.path.join(data_dir, "plugins")
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as error:
            self.notify(
                studio_text("The operations folder is unavailable", "操作資料夾開唔到"),
                f"{target} could not be created: {error}",
                severity="error",
            )
            return
        if not wx.LaunchDefaultApplication(target):
            self.notify(
                studio_text("The operations folder did not open", "操作資料夾開唔到"),
                f"Windows refused to open {target}.",
                severity="warning",
            )
            return
        self.notify(
            studio_text("Operations folder", "操作資料夾"),
            f"Opened {target}.",
        )

    def _cmd_open_in_editor(self, _key: str) -> None:
        """Open the project's folder in the configured external editor."""
        from amulet_map_editor.api import export_actions

        target = self.project_path
        if not target:
            self.notify(
                studio_text("There is nothing to open", "冇嘢可以開"),
                "Open a project first; the external editor opens the project's "
                "own folder.",
                severity="warning",
            )
            return
        action = export_actions.open_exported_path(target)
        self.notify(
            studio_text("External editor", "外部編輯器"),
            action.message or f"Opened {action.target}.",
            severity="success" if action.ok else "warning",
        )

    def _cmd_update_restart(self, _key: str) -> None:
        restart = getattr(self.frame, "restart_to_install_update", None)
        if not callable(restart):
            self.notify(
                studio_text("Updates are unavailable here", "呢度冇更新功能"),
                "This window is not hosted by the application frame, so no "
                "staged update can be installed.",
                severity="warning",
            )
            return
        restart()

    # -- selection commands --------------------------------------------------
    def _cmd_add_box(self, _key: str) -> None:
        box = self.workspace.navigator.add_box()
        self.workspace.refresh_state()
        self.set_saved(False)
        self.workspace.record_revision(
            f"Added {box.label}", f"{box.corner_text(box.minimum)} · 1x1x1"
        )
        self.notify(
            studio_text("Selection box added", "加咗一個選取框"),
            f"{box.label} starts at {box.corner_text(box.minimum)}.",
            severity="success",
        )

    def _cmd_remove_box(self, _key: str) -> None:
        navigator = self.workspace.navigator
        box = navigator.selected_box()
        if box is None:
            self.notify(
                studio_text("No selection box is active", "冇選取框揀咗"),
                "Select a box in the navigator before removing one.",
                severity="warning",
            )
            return
        remaining = [item for item in navigator.boxes if item is not box]
        navigator.set_boxes(remaining)
        self.workspace.refresh_state()
        self.set_saved(False)
        self.workspace.record_revision(
            f"Removed {box.label}", f"{len(remaining)} boxes remain"
        )
        self.notify(
            studio_text("Selection box removed", "刪咗個選取框"),
            f"{box.label} is gone; {len(remaining)} remain.",
            severity="success",
        )

    def _cmd_move_gesture(self, key: str) -> None:
        """Report the real binding for a press-and-hold selection gesture.

        These three are gestures rather than one-shot actions: the user holds a
        button and then uses the movement keys.  The binding is read from the
        editor's own key configuration, so a rebound control is quoted as the
        user set it rather than as the shipped default.
        """
        from amulet_map_editor.api.studio.context_menu import viewport_accelerator

        action, subject = _MOVE_COMMANDS[key]
        if self._editor_call(_EditorAction((key,))):
            return
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
        if binding:
            body = (
                f"Hold {binding} in the viewport and use the movement controls"
                + (f" ({movement})" if movement else "")
                + f" to move {subject}."
            )
        else:
            body = (
                f"The binding that moves {subject} is not set in this profile. "
                "Open Key configuration to give it one."
            )
        self.notify(studio_text(self._command_label(key), ""), body, severity="info")

    # -- view commands -------------------------------------------------------
    def _cmd_projection(self, _key: str) -> None:
        status = self.workspace.status
        current = status.projection()
        following = "top" if current == "3d" else "3d"
        status.set_projection(following, notify=True)
        self.notify(
            studio_text("Projection", "投影"),
            f"The viewport is now {'top-down' if following == 'top' else '3D'}.",
        )

    def _cmd_camera_speed(self, _key: str) -> None:
        """Put the keyboard on the real camera-speed control and say where."""
        slider = self.workspace.status.speed_slider
        slider.SetFocus()
        self.notify(
            studio_text("Camera speed", "鏡頭速度"),
            f"The camera moves at {self.workspace.status.speed()} blocks per second. "
            "The status bar slider now has the keyboard.",
        )

    def _cmd_set_dimension(self, _key: str) -> None:
        value = self._ribbon_value("Dimension")
        navigator = self.workspace.navigator
        target = self._dimension_key(value)
        if not target:
            self.notify(
                studio_text("That dimension is not in this project", "呢個維度唔喺度"),
                (
                    f"No dimension matching {value!r} is loaded."
                    if value
                    else "Choose a dimension in the ribbon first."
                ),
                severity="warning",
            )
            return
        navigator.select_dimension(target)
        self.workspace.refresh_state()
        entry = navigator.dimension(target)
        self.notify(
            studio_text("Dimension", "維度"),
            f"Editing {entry.label if entry is not None else target}.",
        )

    def _dimension_key(self, value: str) -> str:
        """Resolve a ribbon dimension value against the loaded dimensions.

        The ribbon stores short values (``nether``) while the navigator keys are
        the level's own (``the_nether``), so the match is made against the real
        list rather than by assuming either spelling.
        """
        wanted = str(value or "").strip().lower()
        if not wanted:
            return ""
        entries = self.workspace.navigator.dimensions
        for entry in entries:
            if entry.key.lower() == wanted:
                return entry.key
        for entry in entries:
            if entry.key.lower().endswith(wanted) or wanted in entry.label.lower():
                return entry.key
        return ""

    def _cmd_toggle_pane(self, _key: str) -> None:
        self.workspace.toggle_properties()
        self.notify(
            studio_text("Properties pane", "屬性面板"),
            "The properties pane is now "
            + ("visible." if self.workspace.properties_visible() else "hidden."),
        )

    def _cmd_toggle_ribbon(self, _key: str) -> None:
        self.workspace.toggle_ribbon()

    def _cmd_toggle_theme(self, _key: str) -> None:
        theme = "light" if tokens.is_dark() else "dark"
        preferences.update(theme=theme)
        self.refresh_theme()
        self._record("appearance", {"theme": theme})
        self.notify(
            studio_text("Theme", "主題"),
            f"The interface is now using the {theme} theme.",
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
            studio_text("Density", "密度"),
            f"Controls are now {value}; every surface resized with it.",
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

    # -- commands the world editor owns --------------------------------------
    def _cmd_editor(self, key: str) -> None:
        """Hand a command to the live editor, or open the surface that owns it."""
        action = _EDITOR_ACTIONS.get(key)
        if action is not None and self._editor_call(action):
            if key in _MUTATING_COMMANDS:
                # An undo can land back on the state that was last written, but
                # the shell cannot tell from here, and claiming "saved" when the
                # world differs from disk is the error that loses work.  The
                # unsaved mark is therefore the conservative claim: the worst it
                # costs is one save the user did not strictly need.
                self.set_saved(False)
            return
        fallback = _COMMAND_SURFACES.get(key)
        if fallback:
            self.open_surface(fallback)
            return
        if not self.project_open:
            self._require_project(key)
            return
        self.notify(
            studio_text(self._command_label(key), ""),
            f"The open project has no editor able to run {key!r}. Open the 3D "
            "editor tab for this world and try again.",
            severity="warning",
        )

    def _require_project(self, key: str) -> bool:
        """Report that a command needs an open project, and return whether one is."""
        if self.project_open:
            return True
        self.notify(
            studio_text("No project is open", "冇專案開住"),
            f"{self._command_label(key)} needs an open project. Choose one on the "
            "project screen first.",
            severity="warning",
        )
        return False

    def _editor_targets(self, descend: bool) -> Iterator[wx.Window]:
        """Yield the objects a delegated command may be carried out by.

        The canvas first, because that is where the level's own operations
        live; then the active program; then -- only when the action asked for
        it -- the world page's controls, because the chunk and operation tools
        keep their actions on their own panels.
        """
        canvas = self._frame_call("active_editor_canvas")
        if canvas is not None:
            yield canvas
        program = self._frame_call("active_editor_program")
        if program is not None:
            yield program
        if not descend:
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
        for target in self._editor_targets(action.descend):
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
