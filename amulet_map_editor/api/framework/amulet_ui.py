from __future__ import annotations
import wx
from wx.lib.agw import flatnotebook
from typing import Dict, Union
import traceback
import logging
import sys
import os
import subprocess
import threading
import time

from amulet.api.errors import LoaderNoneMatched
from amulet_map_editor.api.wx.ui.select_world import open_level_from_dialog
from amulet_map_editor import __version__, lang
from amulet_map_editor.api.framework.pages import WorldPageUI
from .pages import AmuletMainMenu, BasePageUI

from amulet_map_editor.api import (
    dim_sum_surprise,
    image,
    notifications,
    preferences,
    school_mode,
    tts_narrator,
    scheduled_runtime,
)
from . import update_copy
from amulet_map_editor.api.wx.components import MaterialButton
from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.api.wx.modeless import show_modeless_dialog
from amulet_map_editor.api.wx.title_bar import MaterialTitleBar
from amulet_map_editor.api.wx.ui.preferences import (
    PreferencesDialog,
    CommandPaletteDialog,
    ChangelogDialog,
)
from amulet_map_editor.api.wx.ui.documentation import DocumentationDialog
from amulet_map_editor.api.wx.ui.notifications import NotificationHistoryDialog
from amulet_map_editor.api.wx.ui.local_history import LocalHistoryDialog
from amulet_map_editor.api.wx.ui.tab_manager import TabManagerDialog
from amulet_map_editor.api.tab_groups import TabDock, TabWorkspace
from amulet_map_editor.api.wx.ui.dim_sum_surprise import DimSumSurpriseToast
from amulet_map_editor.api.wx.ui.notification_toast import NotificationToast
from amulet_map_editor.api.wx.nonblocking import notify, notify_exception
from .squirrel_update import (
    build_restart_command,
    check_for_update,
    find_update_exe,
    stage_update,
    SquirrelUpdateState,
    validate_release_notes_url,
)

log = logging.getLogger(__name__)

NOTEBOOK_MENU_STYLE = (
    flatnotebook.FNB_NO_X_BUTTON
    | flatnotebook.FNB_HIDE_ON_SINGLE_TAB
    | flatnotebook.FNB_NAV_BUTTONS_WHEN_NEEDED
)
NOTEBOOK_STYLE = NOTEBOOK_MENU_STYLE | flatnotebook.FNB_X_ON_TAB
UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000

CLOSEABLE_PAGE_TYPE = Union[WorldPageUI]


class SideTabRail(wx.Panel):
    """Material side projection for the persisted left/right tab dock."""

    def __init__(self, parent: wx.Window, notebook: "AmuletLevelNotebook"):
        super().__init__(parent)
        self._notebook = notebook
        self._ids: list[int] = []
        self.list = wx.ListBox(self, name="Side tab rail")
        self.list.SetMinSize(wx.Size(160, -1))
        self.list.Bind(wx.EVT_LISTBOX, self._activate)
        root = wx.BoxSizer(wx.VERTICAL)
        heading = wx.StaticText(self, label="Open tabs")
        heading.SetName("Side tab rail heading")
        root.Add(heading, 0, wx.ALL | wx.EXPAND, 10)
        root.Add(self.list, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        self.SetSizer(root)
        apply_material3(self)

    def sync(self) -> None:
        self._ids = list(range(self._notebook.GetPageCount()))
        self.list.Set([self._notebook.GetPageText(index) for index in self._ids])
        selection = self._notebook.GetSelection()
        if selection != wx.NOT_FOUND and selection < self.list.GetCount():
            self.list.SetSelection(selection)

    def _activate(self, event: wx.CommandEvent) -> None:
        row = event.GetSelection()
        if 0 <= row < len(self._ids):
            self._notebook.SetSelection(self._ids[row])


wx.Image.SetDefaultLoadFlags(0)


class AmuletUI(wx.Frame):
    """This is the top level frame that Amulet exists within."""

    # The notebook to hold world pages
    _level_notebook: AmuletLevelNotebook

    def __init__(self, parent):
        title = self._format_display_title()
        wx.Frame.__init__(
            self,
            parent,
            id=wx.ID_ANY,
            title=title,
            pos=wx.DefaultPosition,
            size=wx.Size(1000, 620),
            style=wx.NO_BORDER | wx.TAB_TRAVERSAL | wx.CLIP_CHILDREN | wx.RESIZE_BORDER,
        )
        self.SetMinSize(wx.Size(570, 620))
        icon = wx.Icon()
        icon.CopyFromBitmap(image.logo.amulet_logo.bitmap())
        self.SetIcon(icon)

        self._shell = wx.Panel(self)
        self._shell_sizer = wx.BoxSizer(wx.VERTICAL)
        self._title_bar = MaterialTitleBar(self._shell, title)
        self._shell_sizer.Add(self._title_bar, 0, wx.EXPAND)
        self._command_bar = wx.Panel(self._shell, name="Application command bar")
        self._command_bar._material3_surface_role = "surface_container"
        self._command_bar_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._command_bar.SetSizer(self._command_bar_sizer)
        self._command_menus: list[wx.Menu] = []
        self._shell_sizer.Add(self._command_bar, 0, wx.EXPAND)
        self._update_banner = wx.Panel(self._shell)
        self._update_banner.SetName("Update notification")
        self._update_banner_sizer = wx.BoxSizer(wx.VERTICAL)
        self._update_banner_actions_sizer = wx.BoxSizer(wx.VERTICAL)
        self._update_banner_text = wx.StaticText(self._update_banner)
        self._update_banner_text.SetName("Update notification message")
        self._update_banner_text.Wrap(620)
        self._update_banner_sizer.Add(
            self._update_banner_text, 0, wx.EXPAND | wx.BOTTOM, 8
        )
        self._update_banner_action = MaterialButton(
            self._update_banner,
            "Update action",
            variant="filled",
            name="Update notification primary action",
        )
        self._update_banner_actions_sizer.Add(
            self._update_banner_action, 0, wx.ALIGN_RIGHT | wx.BOTTOM, 4
        )
        self._update_banner_release_notes = MaterialButton(
            self._update_banner,
            "Release notes",
            variant="text",
            name="Update notification release notes",
        )
        self._update_banner_release_notes.Hide()
        self._update_banner_actions_sizer.Add(
            self._update_banner_release_notes, 0, wx.ALIGN_RIGHT | wx.BOTTOM, 4
        )
        self._update_banner_later = MaterialButton(
            self._update_banner,
            "Later",
            variant="text",
            name="Update notification later action",
        )
        self._update_banner_actions_sizer.Add(
            self._update_banner_later, 0, wx.ALIGN_RIGHT
        )
        self._update_banner_sizer.Add(self._update_banner_actions_sizer, 0, wx.EXPAND)
        self._update_banner.SetSizer(self._update_banner_sizer)
        self._update_banner.Hide()
        self._shell_sizer.Add(self._update_banner, 0, wx.EXPAND | wx.ALL, 8)
        self._tab_content = wx.Panel(self._shell)
        self._tab_content_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._level_notebook = AmuletLevelNotebook(
            self._tab_content, agwStyle=NOTEBOOK_MENU_STYLE
        )
        self._level_notebook._owner_frame = self
        self._tab_rail = SideTabRail(self._tab_content, self._level_notebook)
        self._tab_content_sizer.Add(self._tab_rail, 0, wx.EXPAND)
        self._tab_content_sizer.Add(self._level_notebook, 1, wx.EXPAND)
        self._tab_content.SetSizer(self._tab_content_sizer)
        self._level_notebook.init()
        self._shell_sizer.Add(self._tab_content, 1, wx.EXPAND)
        self._shell.SetSizer(self._shell_sizer)
        root_sizer = wx.BoxSizer(wx.VERTICAL)
        root_sizer.Add(self._shell, 1, wx.EXPAND)
        self.SetSizer(root_sizer)
        # Apply the shared M3 roles after pages exist so newly-created shell
        # controls receive the same palette and accessible sizing.
        apply_material3(self)
        self._apply_tab_rail()

        # Keep the global command palette reachable while any child has focus.
        self._palette_id = int(wx.NewIdRef())
        self.SetAcceleratorTable(
            wx.AcceleratorTable(
                [(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("F"), self._palette_id)]
            )
        )
        self.Bind(wx.EVT_MENU, self._open_command_palette, id=self._palette_id)

        self._update_thread = None
        self._update_stage_thread = None
        self._update_state = SquirrelUpdateState("unknown")
        self._update_state_generation = 0
        self._update_restart_generation: int | None = None
        self._update_restart_process: subprocess.Popen | None = None
        # The narrator is opt-in and defaults to a no-op backend, so wiring the
        # event boundary never makes startup depend on an installed voice.
        self._narrator = tts_narrator.Narrator()
        # One controller represents exactly one application launch.  It owns
        # the ten-percent draw and resolves catalog metadata off the UI thread.
        self._dim_sum_controller = dim_sum_surprise.StartupDimSumSurprise()
        self._dim_sum_toast = None
        self._last_update_notification_key = None
        self._update_timer = None
        self._scheduled_runtime = scheduled_runtime.ScheduledRuntimeController(
            on_state=self._apply_scheduled_runtime_state
        )
        self._scheduled_timer = wx.CallLater(1000, self._refresh_scheduled_runtime)
        self._notification_toasts: list[NotificationToast] = []
        self._update_banner_action.Bind(wx.EVT_BUTTON, self._update_primary_action)
        self._update_banner_release_notes.Bind(
            wx.EVT_BUTTON, self._open_update_release_notes
        )
        self._update_banner_later.Bind(wx.EVT_BUTTON, self._hide_update_banner)
        self.CreateStatusBar()
        wx.CallLater(1000, self._check_for_updates_async)
        self._update_timer = wx.CallLater(
            UPDATE_CHECK_INTERVAL_MS, self._periodic_update_check
        )

        self.Bind(wx.EVT_CLOSE, self._on_app_close)
        self.Bind(wx.EVT_SIZE, self._on_frame_size)

    def show_notification(
        self, title: str, body: str, *, severity: str = "info"
    ) -> None:
        """Show a stacked, non-modal M3 toast without moving focus."""
        if self.IsBeingDeleted():
            return
        toast = NotificationToast(
            self._shell, title, body, severity, self._dismiss_notification
        )
        self._notification_toasts.append(toast)
        self._shell_sizer.Insert(
            1, toast, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8
        )
        self._shell.Layout()

    def _dismiss_notification(self, toast: NotificationToast) -> None:
        if toast not in self._notification_toasts:
            return
        self._notification_toasts.remove(toast)
        self._shell_sizer.Detach(toast)
        toast.Destroy()
        self._shell.Layout()

    def _refresh_scheduled_runtime(self) -> None:
        if self.IsBeingDeleted():
            return
        prefs = school_mode.presentation_preferences(preferences.load())
        base = {
            key: getattr(prefs, key)
            for key in ("language_mode", "theme", "density", "accent")
        }
        threading.Thread(
            target=self._scheduled_runtime.refresh,
            args=(base,),
            name="amulet-scheduled-settings",
            daemon=True,
        ).start()
        self._scheduled_timer = wx.CallLater(
            5 * 60 * 1000, self._refresh_scheduled_runtime
        )

    def _apply_scheduled_runtime_state(
        self, state: scheduled_runtime.RuntimeScheduleState
    ) -> None:
        wx.CallAfter(self._finish_scheduled_runtime_state, state)

    def _finish_scheduled_runtime_state(
        self, state: scheduled_runtime.RuntimeScheduleState
    ) -> None:
        if self.IsBeingDeleted():
            return
        apply_material3(self)
        if state.matched_rule_ids:
            self.SetStatusText(
                "Scheduled settings active: " + ", ".join(state.matched_rule_ids)
            )
        elif state.error:
            self.SetStatusText("Scheduled settings unavailable: " + state.error)

    def begin_startup_dim_sum_surprise(self) -> None:
        """Start the optional delight after startup gates have completed.

        The controller returns immediately and the callback re-enters wx only
        through ``CallAfter``.  If the user has opened a world or School mode
        is enabled before catalog resolution finishes, this remains a quiet
        no-op rather than interrupting their work.
        """

        prefs = school_mode.presentation_preferences(preferences.load())
        if school_mode.load().enabled:
            return

        def on_ready(payload: dim_sum_surprise.DimSumSurprisePayload) -> None:
            wx.CallAfter(self._show_startup_dim_sum_surprise, payload)

        self._dim_sum_controller.begin(
            prefs.language_mode,
            on_ready,
            eligible=self._level_notebook.GetCurrentPage()
            is self._level_notebook._main_menu,
        )

    def _show_startup_dim_sum_surprise(
        self, payload: dim_sum_surprise.DimSumSurprisePayload
    ) -> None:
        """Project a ready payload as a non-modal, auto-dismissing panel."""

        if self.IsBeingDeleted() or school_mode.load().enabled:
            return
        if self._level_notebook.GetCurrentPage() is not self._level_notebook._main_menu:
            return
        if self._update_state.status in {"available", "ready_to_restart", "failed"}:
            return
        if self._dim_sum_toast is not None:
            self._dim_sum_toast.dismiss()
        for toast in list(self._notification_toasts):
            toast.dismiss()
        self._dim_sum_toast = DimSumSurpriseToast(
            self._shell,
            payload,
            on_dismiss=self._dismiss_dim_sum_toast,
        )
        self._shell_sizer.Insert(
            1,
            self._dim_sum_toast,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            8,
        )
        self._shell.Layout()
        # Keep the surprise in notification history as well; this is useful
        # when the user misses the eight-second non-blocking surface.
        title, body = dim_sum_surprise.notification_copy(payload)
        notifications.add("info", title, body)

    def _dismiss_dim_sum_toast(self, toast: DimSumSurpriseToast) -> None:
        if self._dim_sum_toast is not toast:
            return
        self._shell_sizer.Detach(toast)
        self._dim_sum_toast = None
        toast.Hide()
        toast.Destroy()
        self._shell.Layout()

    @staticmethod
    def _is_source_build() -> bool:
        return not (getattr(sys, "frozen", False) or os.path.exists("/.flatpak-info"))

    def _format_display_title(self, display_name: str | None = None) -> str:
        return preferences.format_window_title(
            __version__, display_name=display_name, source=self._is_source_build()
        )

    def refresh_display_identity(self, display_name: str | None = None) -> None:
        """Apply the persisted display label without changing stable app IDs."""
        self.SetTitle(self._format_display_title(display_name))
        self._title_bar.set_title(self.GetTitle())

    def open_level(self, path: str):
        """Open a level. You should use the method in the app."""
        self._level_notebook.open_level(path)

    def close_level(self, path: str):
        """Close a given level. You should use the method in the app."""
        self._level_notebook.close_level(path)

    def create_menu(self):
        """
        Create the UI menu.

        Adds the top level menu items then extends it from the active page
        """
        menu_dict = {}
        menu_dict.setdefault(lang.get("menu_bar.file.menu_name"), {}).setdefault(
            "system", {}
        ).setdefault(
            lang.get("menu_bar.file.open_world"),
            lambda evt: open_level_from_dialog(self),
        )
        # menu_dict.setdefault(lang.get('menu_bar.file.menu_name'), {}).setdefault('system', {}).setdefault('Create World', lambda: self.world.save())
        menu_dict.setdefault(lang.get("menu_bar.file.menu_name"), {}).setdefault(
            "exit", {}
        ).setdefault(lang.get("menu_bar.file.quit"), lambda evt: self.Close())
        menu_dict.setdefault("View", {}).setdefault("application", {}).update(
            {
                "Preferences…": self._open_preferences,
                "Notification history…": self._open_notification_history,
                "Local history…": self._open_local_history,
                "Tabs and groups…": self._open_tab_manager,
                "Changelog…": self._open_changelog,
                "Documentation…": self._open_documentation,
                "Command palette\tCtrl+Shift+F": self._open_command_palette,
                "Check for updates": self._check_for_updates_async,
                "Stage available update": self._stage_update_async,
                "Restart to install update": self._restart_to_install_update,
            }
        )
        menu_dict = self._level_notebook.extend_menu(menu_dict)
        self._command_bar_sizer.Clear(delete_windows=True)
        for old_menu in self._command_menus:
            old_menu.Destroy()
        self._command_menus.clear()
        for menu_name, menu_data in menu_dict.items():
            menu = wx.Menu()
            separator = False
            for menu_section in menu_data.values():
                if separator:
                    menu.AppendSeparator()
                separator = True
                for menu_item_name, menu_item_options in menu_section.items():
                    callback = None
                    menu_item_description = None
                    wx_id = None
                    if callable(menu_item_options):
                        callback = menu_item_options
                    elif isinstance(menu_item_options, tuple):
                        if len(menu_item_options) >= 1:
                            callback = menu_item_options[0]
                        if len(menu_item_options) >= 2:
                            menu_item_description = menu_item_options[1]
                        if len(menu_item_options) >= 3:
                            wx_id = menu_item_options[2]
                    else:
                        continue

                    if not menu_item_description:
                        menu_item_description = ""
                    if not wx_id:
                        wx_id = wx.ID_ANY

                    menu_item: wx.MenuItem = menu.Append(
                        wx_id, menu_item_name, menu_item_description
                    )
                    menu.Bind(wx.EVT_MENU, callback, menu_item)
            label = menu_name.replace("&", "")
            button = MaterialButton(
                self._command_bar,
                label,
                variant="text",
                name=f"{label} menu",
            )
            button.SetMinSize(wx.Size(max(72, button.GetBestSize().width), 40))
            button.Bind(
                wx.EVT_BUTTON,
                lambda _event, control=button, popup=menu: control.PopupMenu(
                    popup, wx.Point(0, control.GetClientSize().height)
                ),
            )
            self._command_bar_sizer.Add(button, 0, wx.LEFT | wx.RIGHT, 2)
            self._command_menus.append(menu)
        apply_material3(self._command_bar)
        self._command_bar.Layout()

    def _open_preferences(self, _event=None) -> None:
        dialog = PreferencesDialog(self)
        dialog.CentreOnParent()
        dialog.ShowModal()
        dialog.Destroy()

    def _open_changelog(self, _event=None) -> None:
        show_modeless_dialog(self, "changelog", ChangelogDialog)

    def _open_documentation(self, _event=None) -> None:
        show_modeless_dialog(self, "documentation", DocumentationDialog)

    def _open_notification_history(self, _event=None) -> None:
        show_modeless_dialog(self, "notification-history", NotificationHistoryDialog)
        self._level_notebook.apply_tab_workspace()

    def _open_local_history(self, _event=None) -> None:
        dialog = LocalHistoryDialog(self)
        dialog.CentreOnParent()
        dialog.ShowModal()
        dialog.Destroy()

    def _open_tab_manager(self, _event=None) -> None:
        dialog = TabManagerDialog(self, self._level_notebook)
        dialog.CentreOnParent()
        dialog.ShowModal()
        dialog.Destroy()

    def _apply_tab_rail(self) -> None:
        """Project left/right docking into a live keyboard-selectable rail."""

        dock = self._level_notebook._tab_workspace.state.dock
        side = (
            dock in (TabDock.LEFT, TabDock.RIGHT)
            and self._level_notebook.GetPageCount() > 1
        )
        self._tab_rail.Show(side)
        self._tab_content_sizer.Detach(self._tab_rail)
        if side and dock is TabDock.RIGHT:
            self._tab_content_sizer.Add(self._tab_rail, 0, wx.EXPAND)
        elif side:
            self._tab_content_sizer.Insert(0, self._tab_rail, 0, wx.EXPAND)
        if side:
            rail_width = 160 if self.GetClientSize().width < 900 else 200
            self._tab_rail.SetMinSize(wx.Size(rail_width, -1))
            self._tab_rail.sync()
        self._tab_content.Layout()

    def _on_frame_size(self, event: wx.SizeEvent) -> None:
        """Keep the side rail compact while preserving the editor viewport."""

        self._apply_tab_rail()
        self._update_banner_text.Wrap(max(240, event.GetSize().width - 48))
        self._update_banner.Layout()
        event.Skip()

    def _open_command_palette(self, _event=None) -> None:
        page = self._level_notebook.GetCurrentPage()
        commands = [
            ("Open world", lambda: open_level_from_dialog(self)),
            ("Preferences…", self._open_preferences),
            ("Notification history…", self._open_notification_history),
            ("Local history…", self._open_local_history),
            ("Tabs and groups…", self._open_tab_manager),
            ("Changelog…", self._open_changelog),
            ("Documentation…", self._open_documentation),
            ("Check for updates", self._check_for_updates_async),
            ("Stage available update", self._stage_update_async),
            ("Restart to install update", self._restart_to_install_update),
        ]
        if hasattr(page, "path"):
            commands.append(("Close current tab", lambda: self.close_level(page.path)))
        dialog = CommandPaletteDialog(self, commands)
        dialog.CentreOnParent()
        dialog.ShowModal()
        dialog.Destroy()

    def _check_for_updates_async(self, _event=None) -> None:
        """Check without blocking startup or the active editing surface."""
        if (
            self._update_restart_generation is not None
            or self._update_state.status == "ready_to_restart"
            or (
                self._update_stage_thread is not None
                and self._update_stage_thread.is_alive()
            )
        ):
            return
        if self._update_thread is not None and self._update_thread.is_alive():
            return
        self._update_state_generation += 1
        generation = self._update_state_generation
        self.SetStatusText("Checking for updates…")
        self._update_thread = threading.Thread(
            target=self._update_worker,
            args=(generation,),
            name="amulet-update-check",
            daemon=True,
        )
        self._update_thread.start()

    def _periodic_update_check(self) -> None:
        """Refresh the feed on a bounded cadence without interrupting editing."""
        if self.IsBeingDeleted():
            return
        self._check_for_updates_async()
        self._update_timer = wx.CallLater(
            UPDATE_CHECK_INTERVAL_MS, self._periodic_update_check
        )

    def _update_worker(self, generation: int) -> None:
        state = check_for_update()
        wx.CallAfter(self._show_update_state, state, generation)

    def _stage_update_async(self, _event=None) -> None:
        """Stage a discovered update without interrupting active editing."""
        if self._update_state.status != "available":
            self.SetStatusText("No update is ready to stage; check for updates first")
            return
        if (
            self._update_stage_thread is not None
            and self._update_stage_thread.is_alive()
        ):
            return
        self.SetStatusText("Downloading update in the background…")
        self._update_state_generation += 1
        generation = self._update_state_generation
        feed_url = self._update_state.feed_url
        version = self._update_state.version
        release_notes_url = self._update_state.release_notes_url
        self._update_stage_thread = threading.Thread(
            target=self._stage_update_worker,
            args=(feed_url, version, release_notes_url, generation),
            name="amulet-update-stage",
            daemon=True,
        )
        self._update_stage_thread.start()

    def _stage_update_worker(
        self,
        feed_url: str | None,
        version: str | None,
        release_notes_url: str | None,
        generation: int,
    ) -> None:
        if not feed_url:
            state = SquirrelUpdateState("failed", detail="Update feed is missing")
        else:
            state = stage_update(
                feed_url,
                version=version,
                release_notes_url=release_notes_url,
            )
        wx.CallAfter(self._show_update_state, state, generation)

    def _open_update_release_notes(self, _event=None) -> None:
        """Open only the immutable release URL carried by the selected feed."""

        release_notes_url = self._update_state.release_notes_url
        if not release_notes_url:
            self.SetStatusText("Release notes are unavailable for this update")
            return
        try:
            release_notes_url = validate_release_notes_url(release_notes_url)
        except ValueError as exc:
            self.SetStatusText(f"Release notes URL was rejected: {exc}")
            return
        if not wx.LaunchDefaultBrowser(release_notes_url):
            self.SetStatusText("Could not open the release notes")

    def _restart_to_install_update(self, _event=None) -> None:
        """Restart only after Squirrel has reported a ready staged update."""
        ready_state = self._update_state
        generation = self._update_state_generation
        if ready_state.status != "ready_to_restart":
            self.SetStatusText("Stage an update before restarting")
            return
        if self._update_restart_generation is not None:
            return
        if not self._level_notebook.begin_preapproved_app_close(generation):
            self.SetStatusText(
                "Save or close unsaved work before installing the update"
            )
            return
        updater = find_update_exe()
        if updater is None:
            self._level_notebook.cancel_preapproved_app_close(generation)
            self.SetStatusText("Update restart unavailable in this installation")
            return
        self._update_restart_generation = generation
        try:
            process = subprocess.Popen(build_restart_command(updater), close_fds=True)
        except (OSError, ValueError) as exc:
            self._update_restart_generation = None
            self._level_notebook.cancel_preapproved_app_close(generation)
            self.SetStatusText(f"Could not restart for update: {exc}")
            return
        self._update_restart_process = process
        # Give Update.exe a bounded handoff window before the parent exits.
        time.sleep(0.5)
        exit_code = process.poll()
        if exit_code is not None:
            self._update_restart_process = None
            self._update_restart_generation = None
            self._level_notebook.cancel_preapproved_app_close(generation)
            self.SetStatusText(
                "Could not restart for update: Update.exe exited during the "
                f"handoff with code {exit_code}; the update remains ready"
            )
            return
        if (
            self._update_restart_generation != generation
            or self._update_state_generation != generation
            or self._update_state is not ready_state
        ):
            try:
                process.terminate()
            except OSError:
                pass
            self._update_restart_process = None
            self._update_restart_generation = None
            self._level_notebook.cancel_preapproved_app_close(generation)
            self.SetStatusText("Update restart state changed; try again")
            return
        if self.Close() is False:
            try:
                process.terminate()
            except OSError:
                pass
            self._update_restart_process = None
            self._update_restart_generation = None
            self._level_notebook.cancel_preapproved_app_close(generation)
            self.SetStatusText("Update restart was cancelled; the update remains ready")

    def _on_app_close(self, event: wx.CloseEvent) -> None:
        """Stop the refresh timer before the notebook applies close protection."""
        generation = self._update_restart_generation
        if not self._level_notebook.on_app_close(
            event, preapproved_generation=generation
        ):
            if generation is not None:
                process = self._update_restart_process
                if process is not None and process.poll() is None:
                    try:
                        process.terminate()
                    except OSError:
                        pass
                self._update_restart_process = None
                self._update_restart_generation = None
                self._level_notebook.cancel_preapproved_app_close(generation)
                self.SetStatusText(
                    "Update restart was cancelled; the update remains ready"
                )
            return
        if self._update_timer is not None and self._update_timer.IsRunning():
            self._update_timer.Stop()
        if self._scheduled_timer is not None and self._scheduled_timer.IsRunning():
            self._scheduled_timer.Stop()
        self._scheduled_runtime.stop()
        self._narrator.close()
        if self._dim_sum_toast is not None:
            self._dim_sum_toast.dismiss()

    def _update_primary_action(self, _event=None) -> None:
        if self._update_state.status == "available":
            self._stage_update_async()
        elif self._update_state.status == "ready_to_restart":
            self._restart_to_install_update()
        elif self._update_state.status == "failed":
            self._check_for_updates_async()

    def _hide_update_banner(self, _event=None) -> None:
        self._update_banner.Hide()
        self._shell.Layout()

    def _render_update_banner(self, state: SquirrelUpdateState) -> None:
        title, body = update_copy.update_copy(
            state.status, version=state.version, detail=state.detail
        )
        self._update_banner_text.SetLabel(f"{title}\n{body}")
        action_label, later_label = update_copy.action_labels(state.status)
        self._update_banner_action.SetLabel(action_label)
        self._update_banner_later.SetLabel(later_label)
        self._update_banner_release_notes.SetLabel(update_copy.release_notes_label())
        release_notes_url = state.release_notes_url
        try:
            if release_notes_url:
                validate_release_notes_url(release_notes_url)
        except ValueError:
            release_notes_url = None
        self._update_banner_release_notes.Show(release_notes_url is not None)
        self._update_banner_release_notes.SetToolTip(
            "Open the immutable GitHub release notes for this update."
        )
        if state.status == "available":
            self._update_banner_action.SetToolTip(
                "Download the unsigned update in the background."
            )
        elif state.status == "ready_to_restart":
            self._update_banner_action.SetToolTip(
                "Restart only after saving your work."
            )
        else:
            self._update_banner_action.SetToolTip("Retry the bounded update check.")
        self._update_banner.Show()
        self._shell.Layout()

    def _show_update_state(
        self, state: SquirrelUpdateState, generation: int | None = None
    ) -> None:
        """Render a persistent, non-modal status message for update state."""
        if self._update_restart_generation is not None:
            return
        if generation is not None and generation != self._update_state_generation:
            return
        self._update_state = state
        if state.status in {"available", "ready_to_restart", "failed"}:
            self._render_update_banner(state)
            title, body = update_copy.update_copy(
                state.status, version=state.version, detail=state.detail
            )
            notification_key = (
                state.status,
                state.version,
                state.release_notes_url,
                state.detail,
                title,
                body,
            )
            if notification_key != self._last_update_notification_key:
                notifications.add(
                    (
                        "error"
                        if state.status == "failed"
                        else (
                            "success" if state.status == "ready_to_restart" else "info"
                        )
                    ),
                    title,
                    body,
                )
                tts_narrator.announce_event(
                    self._narrator,
                    "updates",
                    title + ". " + body,
                    title + ". " + body,
                )
                self._last_update_notification_key = notification_key
        elif state.status in {"up_to_date", "not_installed"}:
            self._hide_update_banner()
        if state.status == "available":
            self.SetStatusText(
                f"Update available: {state.version or 'new version'} (unsigned) — choose Stage available update"
            )
        elif state.status == "ready_to_restart":
            self.SetStatusText(
                f"Update {state.version or 'new version'} ready (unsigned) — choose Restart to install update"
            )
        elif state.status == "failed":
            self.SetStatusText(f"Update check failed: {state.detail or 'offline'}")
        elif state.status == "not_installed":
            self.SetStatusText("Updates unavailable in this installation")
        else:
            self.SetStatusText(f"{preferences.load().display_name} is up to date")


class AmuletLevelNotebook(flatnotebook.FlatNotebook):
    """A notebook to hold all world tabs."""

    # The main menu tab
    _main_menu: AmuletMainMenu

    # Storage of open world tabs for easy lookup
    _open_worlds: Dict[str, CLOSEABLE_PAGE_TYPE]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.Bind(flatnotebook.EVT_FLATNOTEBOOK_PAGE_CLOSING, self._on_page_closing)
        self.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGING, self._page_changing, self)
        self.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._page_changed, self)

        self._main_menu = AmuletMainMenu(self)
        self._open_worlds = {}
        self._tab_workspace = TabWorkspace("main-window")
        self._owner_frame = None
        self._preapproved_app_close: (
            tuple[int, tuple[CLOSEABLE_PAGE_TYPE, ...]] | None
        ) = None
        self._active_preapproved_close_generation: int | None = None

    def init(self):
        self._add_world_tab(self._main_menu, lang.get("main_menu.tab_name"))
        self.apply_tab_workspace()

    def apply_tab_workspace(self) -> None:
        """Project persisted notebook docking where AGW supports it."""
        dock = self._tab_workspace.state.dock
        style = (
            NOTEBOOK_STYLE
            if self.GetCurrentPage() is not self._main_menu
            else NOTEBOOK_MENU_STYLE
        )
        if dock is TabDock.BOTTOM:
            style |= flatnotebook.FNB_BOTTOM
        self.SetAGWWindowStyleFlag(style)
        self.SetName(f"Amulet tabs ({dock.value})")
        if self._owner_frame is not None:
            self._owner_frame._apply_tab_rail()

    def set_tab_dock(self, dock: TabDock | str) -> None:
        self._tab_workspace.set_dock(dock)
        self.apply_tab_workspace()

    def open_level(self, path: str):
        """Open a world panel add it to the notebook"""
        if path in self._open_worlds:
            self.SetSelection(self.GetPageIndex(self._open_worlds[path]))
        else:
            try:
                world = WorldPageUI(self, path)
            except LoaderNoneMatched as e:
                log.error(f"Could not find a loader for this world.\n{e}")
                notify(
                    self,
                    "World loader unavailable",
                    f"{lang.get('select_world.no_loader_found')}\n{e}",
                    severity="error",
                )
            except Exception as e:
                log.error(lang.get("select_world.loading_world_failed"), exc_info=True)
                notify_exception(
                    self,
                    lang.get("select_world.loading_world_failed"),
                    str(e),
                    traceback.format_exc(),
                )
            else:
                self._open_worlds[path] = world
                self._add_world_tab(world, world.world_name)

    def _add_world_tab(self, page: BasePageUI, obj_name: str):
        """Add a tab and enable it."""
        self.AddPage(page, obj_name, True)
        if self._owner_frame is not None:
            self._owner_frame._apply_tab_rail()

    def close_level(self, path: str):
        """Close a given world and remove it from the notebook"""
        if path in self._open_worlds:
            world = self._open_worlds[path]
            # note we don't remove it from the dictionary here
            # delete page starts the deletion but it can be vetoed
            # it is deleted from the dictionary in _on_page_closing
            self.DeletePage(self.GetPageIndex(world))

    def _on_page_closing(self, evt: flatnotebook.EVT_FLATNOTEBOOK_PAGE_CLOSING):
        """Handle the page closing."""
        page: CLOSEABLE_PAGE_TYPE = self.GetPage(evt.GetSelection())
        if page is not self._main_menu:
            preapproved = False
            if (
                self._preapproved_app_close is not None
                and self._active_preapproved_close_generation
                == self._preapproved_app_close[0]
            ):
                preapproved = any(
                    page is approved_page
                    for approved_page in self._preapproved_app_close[1]
                )
            if preapproved or (page.can_disable() and page.can_close()):
                path = page.path
                page.disable()
                page.close()
                del self._open_worlds[path]
            else:
                evt.Veto()
        if self._owner_frame is not None:
            wx.CallAfter(self._owner_frame._apply_tab_rail)

    def _page_changing(self, evt: wx.BookCtrlEvent):
        old_selection_index = evt.GetOldSelection()
        if old_selection_index != wx.NOT_FOUND:
            old_page = self.GetPage(old_selection_index)
            if old_page is not None and not old_page.can_disable():
                evt.Veto()

    def _page_changed(self, evt: wx.BookCtrlEvent):
        """Handle the page changing."""
        if evt.GetOldSelection() != evt.GetSelection():
            if evt.GetOldSelection() != wx.NOT_FOUND:
                # self.GetPage(evt.GetOldSelection()).disable()
                old_page = self.GetPage(evt.GetOldSelection())
                if old_page is not None:
                    old_page.disable()

            if self.GetCurrentPage() is self._main_menu:
                self.apply_tab_workspace()
            else:
                self.apply_tab_workspace()

        if self.GetCurrentPage() is not None:
            self.GetCurrentPage().enable()
        if self._owner_frame is not None:
            self._owner_frame._tab_rail.sync()

    def begin_preapproved_app_close(self, generation: int) -> bool:
        """Ask each open page once and retain an exact close transaction."""

        if self._preapproved_app_close is not None:
            return False
        pages = tuple(self._open_worlds.values())
        for page in pages:
            if not page.can_disable() or not page.can_close():
                return False
        self._preapproved_app_close = generation, pages
        return True

    def cancel_preapproved_app_close(self, generation: int) -> None:
        if (
            self._preapproved_app_close is not None
            and self._preapproved_app_close[0] == generation
        ):
            self._preapproved_app_close = None
            self._active_preapproved_close_generation = None

    def on_app_close(
        self,
        evt: wx.CloseEvent,
        *,
        preapproved_generation: int | None = None,
    ) -> bool:
        preapproved = self._preapproved_app_close
        if preapproved_generation is not None:
            current_pages = tuple(self._open_worlds.values())
            if (
                preapproved is None
                or preapproved[0] != preapproved_generation
                or len(current_pages) != len(preapproved[1])
                or any(
                    current is not approved
                    for current, approved in zip(current_pages, preapproved[1])
                )
            ):
                self.cancel_preapproved_app_close(preapproved_generation)
                evt.Veto()
                return False
            self._active_preapproved_close_generation = preapproved_generation
        try:
            for path, page in list(self._open_worlds.items()):
                self.close_level(path)
        finally:
            if preapproved_generation is not None:
                self._active_preapproved_close_generation = None
                self._preapproved_app_close = None
        if self.GetPageCount() > 1:
            notify(
                self,
                "World still open",
                lang.get("app.world_still_used"),
                severity="warning",
            )
            return False
        else:
            evt.Skip()
            return True

    def extend_menu(self, menu_dict: dict) -> dict:
        return self.GetCurrentPage().menu(menu_dict)
