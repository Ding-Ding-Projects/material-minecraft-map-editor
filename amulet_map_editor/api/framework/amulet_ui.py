from __future__ import annotations
import wx

from amulet_map_editor.api.studio import tokens

from wx.lib.agw import flatnotebook
from typing import Any, Dict, List, Optional, Union
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
from amulet_map_editor.api.material_menu import MaterialMenuItem
from amulet_map_editor.api.process import no_window_kwargs
from amulet_map_editor.api.wx.components import MaterialButton, MaterialMenu
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
from amulet_map_editor.api.wx.ui.notification_toast import NotificationToast, wrap_lines
from amulet_map_editor.api.wx.nonblocking import notify, notify_exception
from amulet_map_editor.api.progress import FAILED, RUNNING, ProgressTask
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
#: How long to wait before retrying automatic staging when a long operation
#: was already running and staging deliberately stood aside for it.
AUTO_STAGE_RETRY_MS = 60 * 1000
#: How long an informational toast stays before retiring itself.
#: Warnings and errors are exempt: they persist until dismissed.
NOTIFICATION_DISMISS_MS = 8000

#: How long to wait before looking again for an editor canvas that is still
#: being built, and how long to keep looking before saying it never arrived.
#: The canvas is created on a worker thread that loads a resource pack and
#: builds a texture atlas, so it is genuinely absent for a few seconds after a
#: world opens rather than merely slow to appear.
CANVAS_HOST_RETRY_MS = 400
CANVAS_HOST_TIMEOUT_SECONDS = 300.0

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


def _clamp_window_metrics(
    default_w: int, default_h: int, min_w: int, min_h: int
) -> tuple[int, int, int, int]:
    """Clamp a desired default/minimum window size to the usable screen area.

    A scaled minimum size that exceeds what the display can physically show
    makes the window impossible to fit -- it gets forced past the screen
    edges, content overflows, and the whole interface reads as "oversized".
    This clamps both the default and the minimum to (at most) 95% of the
    usable client area of the display the window is about to open on, so a
    laptop running at a high display scale still gets a window it can
    actually see and resize.
    """
    try:
        display_index = wx.Display.GetFromPoint(wx.GetMousePosition())
        if display_index == wx.NOT_FOUND:
            display_index = 0
        client = wx.Display(display_index).GetClientArea()
        usable_w, usable_h = client.width, client.height
    except Exception:
        rect = wx.GetClientDisplayRect()
        usable_w, usable_h = rect.width, rect.height
    # Leave real margin: 95% of usable area, not 100%, so the window is not
    # flush against the taskbar and the title bar stays grabbable.
    usable_w = max(1, int(usable_w * 0.95))
    usable_h = max(1, int(usable_h * 0.95))
    clamped_min_w = min(min_w, usable_w)
    clamped_min_h = min(min_h, usable_h)
    clamped_default_w = min(default_w, usable_w)
    clamped_default_h = min(default_h, usable_h)
    # The default may never be smaller than the (already clamped) minimum.
    clamped_default_w = max(clamped_default_w, clamped_min_w)
    clamped_default_h = max(clamped_default_h, clamped_min_h)
    return clamped_default_w, clamped_default_h, clamped_min_w, clamped_min_h


class AmuletUI(wx.Frame):
    """This is the top level frame that Amulet exists within.

    The frame's content is the Amulet Studio shell: a title bar, the backstage
    project screen, and the editing workspace.  The world notebook still exists
    below it -- it owns world loading, per-page unsaved-work protection, and the
    tab dock the tab manager edits -- but it stays hidden.  What the workspace
    viewport is given is the active editor's canvas itself, so the viewport
    shows the world and nothing else: no second tab strip, and no About or
    Convert page nested inside the view of the world.  Those two extensions
    stay reachable from the ribbon, the command palette, and the backstage.

    The canvas is borrowed rather than taken.  Its owning extension keeps it in
    the notebook's page tree and is handed it back before that page is closed,
    because a canvas left parented to the viewport after its extension is
    destroyed is a window drawing a world that no longer exists.
    """

    # The notebook to hold world pages
    _level_notebook: AmuletLevelNotebook

    # The Studio shell, or None when this build could not construct one.
    _studio: Optional[wx.Panel]

    def __init__(self, parent):
        title = self._format_display_title()
        default_w, default_h, min_w, min_h = _clamp_window_metrics(
            tokens.scaled(1000),
            tokens.scaled(620),
            tokens.scaled(570),
            tokens.scaled(620),
        )
        wx.Frame.__init__(
            self,
            parent,
            id=wx.ID_ANY,
            title=title,
            pos=wx.DefaultPosition,
            size=wx.Size(default_w, default_h),
            style=wx.NO_BORDER | wx.TAB_TRAVERSAL | wx.CLIP_CHILDREN | wx.RESIZE_BORDER,
        )
        # Scaled, because this is the size below which the layout stops fitting
        # -- and on a 150% display the layout needs 150% of the pixels to fit
        # in. A fixed floor here lets the window be dragged to a size where
        # every scaled child inside it is clipped, which reads as a broken
        # interface rather than as a window that is simply too small.
        # Both the default and the minimum are clamped above to the usable
        # screen area, so a small/high-DPI laptop display never receives a
        # minimum size larger than the screen itself.
        self.SetMinSize(wx.Size(min_w, min_h))
        icon = wx.Icon()
        icon.CopyFromBitmap(image.logo.amulet_logo.bitmap())
        self.SetIcon(icon)

        # The canvas the Studio viewport has borrowed, with the page and the
        # extension it must go back to: ``(page, owner, canvas)``.
        self._hosted_canvas: Optional[tuple[WorldPageUI, wx.Window, wx.Window]] = None
        self._canvas_host_timer: Optional[wx.CallLater] = None
        self._canvas_host_deadline: Optional[float] = None
        self._world_context_key: Optional[tuple[str, int]] = None

        self._shell = wx.Panel(self)
        self._shell_sizer = wx.BoxSizer(wx.VERTICAL)
        self._title_bar = MaterialTitleBar(self._shell, title)
        self._shell_sizer.Add(self._title_bar, 0, wx.EXPAND)
        self._command_bar = wx.Panel(self._shell, name="Application command bar")
        self._command_bar._material3_surface_role = "surface_container"
        self._command_bar_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._command_bar.SetSizer(self._command_bar_sizer)
        self._command_menus: list[MaterialMenu] = []
        self._shell_sizer.Add(self._command_bar, 0, wx.EXPAND)
        self._update_banner = wx.Panel(self._shell)
        self._update_banner.SetName("Update notification")
        self._update_banner_sizer = wx.BoxSizer(wx.VERTICAL)
        self._update_banner_actions_sizer = wx.BoxSizer(wx.VERTICAL)
        self._update_banner_text = wx.StaticText(self._update_banner)
        self._update_banner_text.SetName("Update notification message")
        self._update_banner_text.Wrap(620)
        # The unwrapped source text.  ``wx.StaticText.Wrap`` silently stops
        # rewrapping after its first call on wxWidgets 3.3.3 (see
        # NotificationToast._rewrap), so every later resize measures its own
        # breaks from this raw string instead of re-wrapping an already
        # wrapped label.
        self._update_banner_raw_text = ""
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
        # Deliberately not added to the shell sizer: see
        # _position_notification_toasts. A sizer child here is a banner
        # that displaces the interface; this is an overlay that does not.
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
        # The Studio is the frame's content. The notebook is kept because it
        # owns world loading and unsaved-work protection, and is parked hidden
        # until a world opens, at which point the workspace viewport hosts it.
        # A build whose Studio package cannot be constructed still shows the
        # notebook it has always shown rather than an empty window.
        self._studio = self._create_studio()
        if self._studio is None:
            self._shell_sizer.Add(self._tab_content, 1, wx.EXPAND)
        else:
            self._title_bar.Hide()
            self._command_bar.Hide()
            self._tab_content.Hide()
            self._shell_sizer.Add(self._studio, 1, wx.EXPAND)
        self._shell.SetSizer(self._shell_sizer)
        root_sizer = wx.BoxSizer(wx.VERTICAL)
        root_sizer.Add(self._shell, 1, wx.EXPAND)
        self.SetSizer(root_sizer)
        # Apply the shared M3 roles after pages exist so newly-created shell
        # controls receive the same palette and accessible sizing.
        apply_material3(self)
        self._apply_tab_rail()

        # Keep the global command palette reachable while any child has focus,
        # and install every other real binding the Studio registry declares.
        # The Studio binds its own handlers and returns the rows, because this
        # frame owns the single table wx consults.
        self._palette_id = int(wx.NewIdRef())
        self.Bind(wx.EVT_MENU, self._open_command_palette, id=self._palette_id)
        accelerator_entries = [
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("F"), self._palette_id)
        ]
        if self._studio is not None:
            accelerator_entries.extend(self._studio.install_accelerators())
        self.SetAcceleratorTable(wx.AcceleratorTable(accelerator_entries))

        self._update_thread = None
        self._update_stage_thread = None
        self._update_state = SquirrelUpdateState("unknown")
        # Update workers may finish while a close attempt is awaiting unsaved-
        # work confirmation. Accepted closes invalidate their generation before
        # teardown; vetoed closes reconcile the deferred current result.
        self._update_worker_lock = threading.RLock()
        self._is_closing = False
        self._closing_update_generation: int | None = None
        self._pending_update_state: tuple[SquirrelUpdateState, int] | None = None
        self._update_state_generation = 0
        self._update_restart_generation: int | None = None
        self._update_restart_process: subprocess.Popen | None = None
        # Automatic staging retries when a long operation is already running
        # rather than competing with it, so it needs its own bounded timer
        # distinct from the six-hour feed-check cadence.
        self._auto_stage_retry_timer: wx.CallLater | None = None
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
        self._scheduled_refresh_thread: threading.Thread | None = None
        self._scheduled_timer = wx.CallLater(1000, self._refresh_scheduled_runtime)
        self._notification_toasts: list[NotificationToast] = []
        # Built the first time something reports progress. A session that never
        # runs a long operation never pays for the surface that would have
        # watched it.
        self._progress_overlay: Optional[wx.Panel] = None
        self._progress_overlay_failed = False
        # A failed row keeps being republished while it sits on screen, so the
        # announcement is keyed rather than fired per update -- otherwise one
        # failure narrates itself once per repaint.
        self._announced_progress_failures: set[str] = set()
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
        # Float it over the interface rather than inserting it into the shell's
        # sizer. As a sizer child a toast became a full-width banner across the
        # top that reflowed the whole window and pushed the application down --
        # which is displacement, not notification, and it is what a
        # non-blocking surface must never do.
        self._notification_toasts.append(toast)
        toast.SetName(f"Notification toast: {title}")
        self._position_notification_toasts()
        toast.Raise()
        toast.Show()
        # Informational toasts retire themselves; warnings and errors stay until
        # they are read, because those are the ones that matter after the moment
        # has passed.
        if severity not in ("warning", "error"):
            wx.CallLater(
                NOTIFICATION_DISMISS_MS,
                lambda: self._dismiss_notification(toast),
            )

    def _fit_and_clamp_overlay_card(
        self,
        window: wx.Window,
        min_width: int,
        max_width: int,
        manual_rewrap=None,
    ) -> wx.Size:
        """Return ``window``'s size once it fits its content at a clamped width.

        Clamping a card's width with a bare ``SetSize`` and then reading
        ``GetSize().height`` for stacking measures a height computed for the
        *previous* width -- the label has not re-wrapped yet, or has just
        re-wrapped to more lines, and either way the number read back is
        stale. That stale height is exactly why two toasts could land in the
        same place: the shorter, pre-wrap height was used to step up from the
        one below it. This measures again after the width settles, so the
        height that is actually stacked with is the height the card ends up
        drawn at.
        """
        window.Fit()
        size = window.GetSize()
        target_width = min(max(size.width, min_width), max_width)
        if target_width != size.width:
            if manual_rewrap is not None:
                manual_rewrap(target_width)
            # For a NotificationToast this SetSize alone re-wraps its own
            # text, synchronously, through the EVT_SIZE handler it binds to
            # itself -- the same width change that grows a two-line bilingual
            # message to three or four lines.
            window.SetSize(wx.Size(target_width, size.height))
            window.Layout()
            window.Fit()
            size = window.GetSize()
            target_width = min(max(size.width, min_width), max_width)
            if size.width != target_width:
                window.SetSize(wx.Size(target_width, size.height))
                size = window.GetSize()
        return size

    def _position_notification_toasts(self) -> None:
        """Stack the live toasts up from the bottom-right of the interface.

        They are positioned, never laid out: a toast must not take space from
        the surface it is reporting about, and it must not move anything the
        reader is currently looking at. The stack is re-clamped on every
        call -- including a resize -- so nothing is ever pushed off the
        bottom or the right of the window.
        """
        if self.IsBeingDeleted():
            return
        shell = getattr(self, "_shell", None)
        if shell is None:
            return
        margin = 16
        width, height = shell.GetClientSize()
        bottom = height - margin
        # However narrow the window gets, a card must still fit between the
        # margins -- never wider than the client area it is floating over.
        max_card_width = max(160, width - margin * 2)

        # The update card sits lowest so a burst of toasts never pushes a
        # standing offer off the bottom of the window.
        banner = getattr(self, "_update_banner", None)
        if banner is not None and banner.IsShown():
            try:
                size = self._fit_and_clamp_overlay_card(
                    banner,
                    min(320, max_card_width),
                    max_card_width,
                    manual_rewrap=self._rewrap_update_banner_text,
                )
                bottom = max(margin, bottom - size.height)
                banner.SetPosition(wx.Point(width - size.width - margin, bottom))
                bottom -= 8
                banner.Raise()
            except RuntimeError:
                pass

        for toast in reversed(self._notification_toasts):
            try:
                if toast.IsBeingDeleted():
                    continue
                size = self._fit_and_clamp_overlay_card(
                    toast, min(280, max_card_width), max_card_width
                )
                bottom = max(margin, bottom - size.height)
                toast.SetPosition(wx.Point(width - size.width - margin, bottom))
                bottom -= 8
                toast.Raise()
            except RuntimeError:
                # A toast destroyed between the list and here is not an error;
                # the next reposition drops it.
                continue

    def _dismiss_notification(self, toast: NotificationToast) -> None:
        if toast not in self._notification_toasts:
            return
        self._notification_toasts.remove(toast)
        self._position_notification_toasts()
        self._shell_sizer.Detach(toast)
        toast.Destroy()
        self._shell.Layout()

    # -- progress ------------------------------------------------------------
    def progress_overlay(self) -> Optional[wx.Panel]:
        """Return the shell's progress overlay, building it on first use.

        Imported here rather than at module scope for the same reason the
        Studio is: a failure inside the Studio package must degrade the
        application rather than prevent it from starting.  A build that cannot
        construct the overlay still reports progress -- in the status bar,
        which is a poorer surface but a truthful one -- rather than running a
        long save with nothing on screen at all.
        """
        if self._progress_overlay is not None or self._progress_overlay_failed:
            return self._progress_overlay
        try:
            from amulet_map_editor.api.studio.progress_overlay import ProgressOverlay

            self._progress_overlay = ProgressOverlay(self._shell)
        except Exception:
            self._progress_overlay_failed = True
            log.exception(
                "Could not build the progress overlay; progress will be reported "
                "in the status bar only"
            )
        return self._progress_overlay

    def update_progress(self, task: ProgressTask) -> None:
        """Show or refresh one operation on the overlay, blocking nothing.

        This is the whole of what the shell does about progress.  It never
        disables a window, never takes focus, and never inserts anything into a
        sizer -- the overlay is positioned over the interface exactly as the
        notification toasts are, so an operation starting cannot reflow the
        surface the user is working on.
        """
        if self.IsBeingDeleted():
            return
        # The status bar carries the same sentence regardless, so the report
        # survives a build with no overlay and reaches a screen reader that is
        # following the frame rather than the overlay.
        try:
            self.SetStatusText(task.accessible_name())
        except Exception:
            log.debug("Status-bar progress fallback unavailable", exc_info=True)
        overlay = self.progress_overlay()
        if overlay is None:
            return
        overlay.publish(task)
        self._position_progress_overlay()
        if task.state == FAILED and task.key not in self._announced_progress_failures:
            self._announced_progress_failures.add(task.key)
            # The row itself is the visible report and it stays until dismissed,
            # so this deliberately does not raise a toast as well: several call
            # sites already publish their own error with a traceback attached,
            # and two red surfaces for one failure is noise, not emphasis.
            #
            # It still reaches the two places a row on screen does not: history,
            # so the failure is reviewable after the row is dismissed, and the
            # narrator, so a listener hears it.
            try:
                notifications.add(
                    "error", task.title, task.error or "The operation failed."
                )
            except Exception:
                log.exception("Could not record the progress failure in history")
            tts_narrator.announce_event(
                self._narrator,
                "progress",
                f"{task.title}. {task.error}",
                f"{task.title}。{task.error}",
            )

    def clear_progress(self, key: str) -> None:
        """Retire a finished operation's row."""
        if self.IsBeingDeleted():
            return
        self._announced_progress_failures.discard(str(key))
        overlay = self._progress_overlay
        if overlay is None:
            return
        overlay.retire(str(key))
        self._position_progress_overlay()

    def _progress_overlay_top(self) -> int:
        """Return the y at which the overlay may start without covering chrome.

        An overlay that covers the window controls is an overlay that takes the
        close button away for the length of a save, so it starts below whatever
        title bar is currently in use -- the frame's own when the notebook is
        showing, the Studio's when it is.
        """
        top = 0
        studio = self._studio
        if studio is not None:
            bar = getattr(studio, "title_bar", None)
            if bar is not None and bar.IsShown():
                return studio.GetPosition().y + bar.GetSize().height
            return studio.GetPosition().y
        for chrome in (self._title_bar, self._command_bar):
            if chrome is not None and chrome.IsShown():
                top = max(top, chrome.GetPosition().y + chrome.GetSize().height)
        return top

    def _position_progress_overlay(self) -> None:
        """Float the overlay across the top of the interface.

        Positioned, never laid out: progress must not take space from the
        surface it is reporting about.
        """
        overlay = self._progress_overlay
        if overlay is None or self.IsBeingDeleted():
            return
        try:
            if not overlay.tasks:
                overlay.Hide()
                return
            width = self._shell.GetClientSize().width
            height = overlay.best_height()
            overlay.SetSize(wx.Size(width, height))
            overlay.SetPosition(wx.Point(0, self._progress_overlay_top()))
            overlay.Raise()
            overlay.Show()
        except RuntimeError:  # pragma: no cover - overlay destroyed mid-update
            self._progress_overlay = None

    def _refresh_scheduled_runtime(self) -> None:
        """Refresh scheduled values without ever overlapping worker threads."""
        if self.IsBeingDeleted():
            return
        self._scheduled_timer = wx.CallLater(
            5 * 60 * 1000, self._refresh_scheduled_runtime
        )
        if (
            self._scheduled_refresh_thread is not None
            and self._scheduled_refresh_thread.is_alive()
        ):
            return
        prefs = school_mode.presentation_preferences(preferences.load())
        base = {
            key: getattr(prefs, key)
            for key in ("language_mode", "theme", "density", "accent")
        }
        self._scheduled_refresh_thread = threading.Thread(
            target=self._scheduled_refresh_worker,
            args=(base,),
            name="amulet-scheduled-settings",
            daemon=True,
        )
        self._scheduled_refresh_thread.start()

    def _scheduled_refresh_worker(self, base: dict[str, object]) -> None:
        try:
            self._scheduled_runtime.refresh(base)
        except Exception:  # keep a scheduled preference error off the UI thread
            log.exception("Scheduled settings refresh failed")

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
        self._level_notebook._main_menu.refresh_display_identity()

    def _create_studio(self) -> Optional[wx.Panel]:
        """Build the Studio shell, or report why the notebook is showing instead.

        Imported here rather than at module scope so a failure inside the
        Studio package degrades to the previous shell, with the traceback in the
        log, instead of preventing the application from starting at all.
        """
        try:
            from amulet_map_editor.api.studio.shell import StudioShell

            return StudioShell(self._shell, self)
        except Exception:
            log.exception(
                "The Amulet Studio shell could not be created; "
                "falling back to the world notebook"
            )
            return None

    def open_level(self, path: str):
        """Open a level. You should use the method in the app."""
        self._level_notebook.open_level(path)
        self.sync_studio_project()

    def close_level(self, path: str):
        """Close a given level. You should use the method in the app."""
        self._level_notebook.close_level(path)
        self.sync_studio_project()

    def open_project_dialog(self) -> None:
        """Open the world picker the Studio's Open project command asks for."""
        open_level_from_dialog(self)

    def open_preferences(self) -> None:
        """Show options, through the frame's own call site.

        The preferences dialog ends itself with ``EndModal`` and so has to be
        shown modally.  The Studio surface index therefore asks the frame to
        show it rather than opening a second, non-modal copy that would fail the
        moment the user pressed Save.
        """
        self._open_preferences()

    def open_local_history(self) -> None:
        """Show the local version history, through the frame's own call site."""
        self._open_local_history()

    def open_tab_manager(self) -> None:
        """Show the tab and group manager over this frame's real notebook."""
        self._open_tab_manager()

    def select_language(self) -> None:
        """Show the language chooser the start page owns."""
        self._level_notebook._main_menu._select_language(None)

    def active_world_page(self) -> Optional[WorldPageUI]:
        """Return the world page the user is working in, if there is one.

        The selected tab answers first; when the start tab is selected while
        worlds are still open, the most recently opened world is the project the
        shell should still be showing.
        """
        page = self._level_notebook.GetCurrentPage()
        if isinstance(page, WorldPageUI):
            return page
        open_worlds = list(self._level_notebook._open_worlds.values())
        return open_worlds[-1] if open_worlds else None

    def active_editor_program(self) -> Optional[wx.Window]:
        """Return the selected program inside the active world page."""
        page = self.active_world_page()
        if page is None:
            return None
        try:
            return page.GetPage(page.GetSelection())
        except Exception:
            # A world page whose selection is not a program is a legitimate
            # state while a page is being built or torn down.
            return None

    def active_editor_canvas(self) -> Optional[wx.Window]:
        """Return the 3D editor canvas of the active program, if it has one."""
        return getattr(self.active_editor_program(), "_canvas", None)

    def sync_studio_project(self) -> None:
        """Tell the Studio which world is open and give it the renderer.

        Called after every open, close, and tab change, so the shell's project
        state is read from the notebook rather than assumed from whatever the
        user last asked for.
        """
        studio = getattr(self, "_studio", None)
        if studio is None or self.IsBeingDeleted():
            return
        page = self.active_world_page()
        if page is None:
            self.release_hosted_canvas()
            self._cancel_canvas_host_retry()
            self._clear_world_context()
            studio.detach_project()
            return
        # The Studio owns tab management, so the legacy side rail would be a
        # second, contradictory list of the same tabs inside the viewport.
        self._tab_rail.Hide()
        self._select_editor_program(page)
        self._host_editor_canvas(page, studio)
        if not (studio.project_open and studio.project_path == page.path):
            studio.attach_project(
                page.world_name, page.path, self._world_platform(page)
            )
        self._publish_world_context(page)

    # -- the editor canvas inside the Studio viewport ------------------------
    def hosted_canvas(self) -> Optional[wx.Window]:
        """Return the canvas the Studio viewport is currently showing."""
        return None if self._hosted_canvas is None else self._hosted_canvas[2]

    def _host_editor_canvas(self, page: WorldPageUI, studio) -> None:
        """Put the active editor's canvas and its own controls in the viewport.

        The canvas moves, and so does every panel the editor draws over it.
        The extension itself stays where the world notebook put it, so the
        notebook's page tree is never handed a window that is no longer one of
        its children -- but its panels are not part of that tree's layout, and
        leaving them behind is what used to strand every editing control on a
        hidden page.  See :meth:`_host_editor_overlays`.
        """
        program = self.active_editor_program()
        if program is None:
            self.release_hosted_canvas()
            studio.set_canvas(None)
            self._set_viewport_reason(
                "This world loaded no 3D editor, so there is no renderer to show. "
                "The log records which extension failed to load."
            )
            return
        canvas = getattr(program, "_canvas", None)
        building = getattr(program, "_setup_thread", None) is not None
        if canvas is None or building or not canvas.IsShown():
            self.release_hosted_canvas()
            studio.set_canvas(None)
            self._await_editor_canvas()
            return
        self._cancel_canvas_host_retry()
        if self._hosted_canvas is not None and self._hosted_canvas[2] is canvas:
            studio.set_canvas(canvas)
            return
        self.release_hosted_canvas()
        owner = canvas.GetParent()
        sizer = owner.GetSizer() if owner is not None else None
        if sizer is not None:
            sizer.Detach(canvas)
        self._hosted_canvas = (page, owner, canvas)
        studio.set_canvas(canvas)
        self._host_editor_overlays(canvas, canvas.GetParent())
        self._set_viewport_reason("")
        # The world pages are outside the Studio's own token traversal, so they
        # are styled from here rather than being left with the default palette.
        apply_material3(self._tab_content)
        self._tab_content.Layout()

    @staticmethod
    def editor_overlay_windows(canvas: Optional[wx.Window]) -> List[wx.Window]:
        """Return every panel the editor draws over ``canvas``.

        The editor builds its controls as siblings of the canvas rather than
        as children of it -- the undo/save panel, the row of tool buttons, and
        one options panel per tool -- and positions them in canvas
        coordinates.  They are what a user presses to paste, to place, to pick
        an operation and to run it.

        Every registered tool is asked, not just the running one.  The tool
        manager's own ``windows()`` answers for the active tool alone, which
        would be enough to move what is on screen right now and would strand
        the next tool the user picks: all six are constructed eagerly at
        startup, so all six are moved once, here.
        """
        windows: List[wx.Window] = []
        if canvas is None:
            return windows

        def take(source: Any) -> None:
            getter = getattr(source, "windows", None)
            if not callable(getter):
                return
            try:
                found = list(getter())
            except Exception:  # noqa: BLE001 - a tool mid-teardown answers this
                log.debug("An editor tool would not list its windows", exc_info=True)
                return
            windows.extend(window for window in found if window)

        take(getattr(canvas, "_file_panel", None))
        manager = getattr(canvas, "_tool_sizer", None)
        if manager is not None:
            panel = getattr(manager, "_tool_panel", None)
            if panel:
                windows.append(panel)
            try:
                tools = list(canvas.tools.values())
            except Exception:  # noqa: BLE001 - a canvas without its tool manager
                log.debug("The editor tools could not be listed", exc_info=True)
                tools = []
            for tool in tools:
                take(tool)
        # One tool can hand back a window another already listed, and
        # reparenting the same window twice is wasted work rather than an
        # error; the order is kept so the file panel stays on top.
        unique: List[wx.Window] = []
        for window in windows:
            if not any(window is seen for seen in unique):
                unique.append(window)
        return unique

    def _host_editor_overlays(
        self, canvas: Optional[wx.Window], host: Optional[wx.Window]
    ) -> int:
        """Move the editor's own control panels onto ``host``, beside the canvas.

        The viewport gives the canvas its whole client area at ``(0, 0)``, so
        host coordinates and canvas coordinates are the same numbers.  That is
        why nothing here repositions anything: each panel's own ``_resize``
        already places it in canvas coordinates, and it goes on being right.

        Returns how many panels moved, so a caller can tell "there were none"
        from "they are all still on the hidden page".
        """
        if canvas is None or host is None:
            return 0
        moved = 0
        for window in self.editor_overlay_windows(canvas):
            try:
                if window.GetParent() is not host:
                    window.Reparent(host)
                    moved += 1
                # Raised whether or not it moved: the viewport raises the
                # children it knew about at the moment it took the canvas, and
                # these arrived afterwards, so an unraised panel would sit
                # behind the GL surface and never be seen.
                window.Raise()
            except Exception:  # noqa: BLE001 - a window already being destroyed
                log.debug("An editor panel could not follow the canvas", exc_info=True)
        if moved:
            try:
                # The panels size themselves from the canvas, which has just
                # been given the viewport's size; without this they keep the
                # geometry they were built with on the hidden page.
                canvas.SendSizeEvent()
            except Exception:  # noqa: BLE001 - the canvas is tearing down
                log.debug("The editor canvas refused a resize", exc_info=True)
        return moved

    def _await_editor_canvas(self) -> None:
        """Say the renderer is still starting, and look again shortly.

        The alternative -- showing the drawn stand-in with no explanation --
        reads as a renderer that failed rather than one that has not finished
        loading its resource pack yet.
        """
        now = time.monotonic()
        if self._canvas_host_deadline is None:
            self._canvas_host_deadline = now + CANVAS_HOST_TIMEOUT_SECONDS
        if now > self._canvas_host_deadline:
            self._set_viewport_reason(
                "The 3D editor did not finish starting within "
                f"{int(CANVAS_HOST_TIMEOUT_SECONDS)} seconds. The log records why; "
                "nothing is being drawn from the world."
            )
            self._cancel_canvas_host_retry()
            return
        self._set_viewport_reason(
            "The 3D editor is still starting: it is loading the resource pack "
            "and building its texture atlas. Nothing here is read from the "
            "world yet."
        )
        # A fresh one-shot each time rather than a guard on the old one being
        # idle: a `wx.CallLater` still reports itself as running while it is
        # inside its own callback, so a guard would let the very first retry
        # cancel the whole chain and the canvas would never be looked for
        # again -- which looks exactly like a renderer that failed to start.
        if self._canvas_host_timer is not None:
            self._canvas_host_timer.Stop()
        self._canvas_host_timer = wx.CallLater(
            CANVAS_HOST_RETRY_MS, self.sync_studio_project
        )

    def _cancel_canvas_host_retry(self) -> None:
        if self._canvas_host_timer is not None and self._canvas_host_timer.IsRunning():
            self._canvas_host_timer.Stop()
        self._canvas_host_timer = None
        self._canvas_host_deadline = None

    def release_hosted_canvas(
        self, page: Optional[WorldPageUI] = None, *, closing: bool = False
    ) -> None:
        """Give a borrowed canvas back to the extension that owns it.

        Called before a world page closes and whenever the viewport is about to
        show a different one.  ``page`` narrows it to one world's canvas, so
        closing one world never takes the renderer away from another, and
        ``closing`` says the extension is about to destroy it rather than use
        it again.
        """
        record = self._hosted_canvas
        if record is None:
            return
        hosted_page, owner, canvas = record
        if page is not None and page is not hosted_page:
            return
        self._hosted_canvas = None
        studio = getattr(self, "_studio", None)
        if studio is not None:
            try:
                studio.set_canvas(None)
            except RuntimeError:  # pragma: no cover - the shell is being torn down
                pass
        try:
            if not canvas or canvas.IsBeingDeleted():
                return
            if owner and not owner.IsBeingDeleted():
                canvas.Reparent(owner)
                # The panels were borrowed alongside the canvas and go back
                # with it. Left on the viewport they would outlive the page
                # that owns them, and the extension's next enable() would
                # rebuild its layout around windows that are no longer its
                # children.
                self._host_editor_overlays(canvas, owner)
                sizer = owner.GetSizer()
                if sizer is not None and sizer.GetItem(canvas) is None:
                    sizer.Add(canvas, 1, wx.EXPAND)
                if not closing:
                    # The viewport hides a canvas as it lets go of it, and the
                    # extension lent it shown. Handing back a hidden canvas
                    # makes the extension's next `enable()` fail: an OpenGL
                    # context cannot be made current on a canvas that is not
                    # shown, and the failure surfaces while closing an
                    # unrelated world. Showing it is skipped for a canvas whose
                    # page is closing, because showing queues a deferred resize
                    # that would then run against a destroyed window.
                    canvas.Show()
                owner.Layout()
        except RuntimeError:  # pragma: no cover - either window already gone
            log.debug("The borrowed canvas could not be returned", exc_info=True)

    def _set_viewport_reason(self, reason: str) -> None:
        """Tell the viewport why it has no renderer, when it has none."""
        studio = getattr(self, "_studio", None)
        viewport = getattr(getattr(studio, "workspace", None), "viewport", None)
        setter = getattr(viewport, "set_placeholder_reason", None)
        if callable(setter):
            try:
                setter(reason)
            except RuntimeError:  # pragma: no cover - the workspace is going away
                pass

    # -- the world every Studio surface reads from ---------------------------
    def _publish_world_context(self, page: WorldPageUI) -> None:
        """Make the open level the world every Studio surface reads from.

        The snapshot walks the world folder and counts its chunks, so it is
        taken once per world rather than on every tab change; attaching the
        canvas afterwards only replaces the selection and the dimension, which
        costs nothing.
        """
        try:
            from amulet_map_editor.api.studio import context as world_context
        except Exception:  # pragma: no cover - a build without the Studio
            log.debug("The Studio world context is unavailable", exc_info=True)
            return
        canvas = self.hosted_canvas()
        key = (page.path, id(getattr(page, "world", None)))
        try:
            if key != self._world_context_key:
                world_context.set_level(
                    page.world, path=page.path, name=page.world_name, canvas=canvas
                )
                self._world_context_key = key
            elif canvas is not None:
                world_context.set_canvas(canvas)
        except Exception:
            log.exception("Could not publish the open world to the Studio surfaces")

    def _clear_world_context(self) -> None:
        """Record that no world is open, for every surface that reads one."""
        self._world_context_key = None
        try:
            from amulet_map_editor.api.studio import context as world_context

            world_context.clear()
        except Exception:  # pragma: no cover - a build without the Studio
            log.debug("The Studio world context could not be cleared", exc_info=True)

    @staticmethod
    def _select_editor_program(page: WorldPageUI) -> None:
        """Open a world on its 3D editor rather than on the About page.

        The world notebook selects its first extension, which is About.  Inside
        the Studio viewport that reads as the renderer being broken, because the
        viewport is showing a text page where the world should be.
        """
        try:
            for index in range(page.GetPageCount()):
                if page.GetPageText(index) == "3D Editor":
                    if page.GetSelection() != index:
                        page.SetSelection(index)
                    return
        except RuntimeError:
            # The page can be mid-teardown; selecting nothing is correct then.
            return

    @staticmethod
    def _world_platform(page: WorldPageUI) -> str:
        """Return the world's platform name, or an empty string when unknown."""
        try:
            return str(page.world.level_wrapper.platform)
        except Exception:
            return ""

    def create_menu(self):
        """Build the app-owned, searchable Material 3 command menus."""
        # BEGIN CODEX MATERIAL 3 COMMAND MENU
        menu_dict = {}
        menu_dict.setdefault(lang.get("menu_bar.file.menu_name"), {}).setdefault(
            "system", {}
        ).setdefault(
            lang.get("menu_bar.file.open_world"),
            lambda evt: open_level_from_dialog(self),
        )
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
            items: list[MaterialMenuItem] = []
            for section_name, menu_section in menu_data.items():
                if not isinstance(menu_section, dict):
                    continue
                section_label = str(section_name).replace("_", " ").strip().title()
                for menu_item_name, menu_item_options in menu_section.items():
                    callback = None
                    description = ""
                    wx_id = wx.ID_ANY
                    if callable(menu_item_options):
                        callback = menu_item_options
                    elif isinstance(menu_item_options, tuple):
                        if len(menu_item_options) >= 1:
                            callback = menu_item_options[0]
                        if len(menu_item_options) >= 2:
                            description = str(menu_item_options[1] or "")
                        if len(menu_item_options) >= 3 and menu_item_options[2]:
                            wx_id = int(menu_item_options[2])
                    if not callable(callback):
                        continue
                    items.append(
                        MaterialMenuItem(
                            label=str(menu_item_name),
                            callback=callback,
                            description=description,
                            identifier=int(wx_id),
                            section=section_label,
                        )
                    )

            label = str(menu_name).replace("&", "")
            popup = MaterialMenu(self._command_bar, title=label, items=items)
            button = MaterialButton(
                self._command_bar,
                label,
                variant="text",
                name=f"{label} menu",
            )
            button.SetMinSize(wx.Size(max(72, button.GetBestSize().width), 40))
            button.Bind(
                wx.EVT_BUTTON,
                lambda _event, control=button, menu=popup: menu.show_for(control),
            )
            self._command_bar_sizer.Add(button, 0, wx.LEFT | wx.RIGHT, 2)
            self._command_menus.append(popup)
        apply_material3(self._command_bar)
        self._command_bar.Layout()
        # END CODEX MATERIAL 3 COMMAND MENU

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
        self._rewrap_update_banner_text(max(288, event.GetSize().width - 32))
        self._update_banner.Layout()
        # A positioned overlay is not laid out by a sizer, so nothing else moves
        # it when the window resizes -- it would keep the width the shell had
        # when the operation started and hang off the edge or stop short of it.
        self._position_progress_overlay()
        # The toast/banner stack is positioned, not laid out, for the same
        # reason: nothing else re-clamps it on resize, so a shrink used to
        # leave a card hanging off the right edge or the bottom of the window
        # until the next unrelated reposition happened to run.
        #
        # Deferred with CallAfter rather than called here directly: this
        # dynamically bound handler runs *before* wx's own built-in sizer
        # layout for this frame, which only happens once ``event.Skip()``
        # below hands the event on. Reading ``self._shell.GetClientSize()``
        # right now would read the size the shell had before this resize --
        # the stack would be clamped to where the window used to end.
        wx.CallAfter(self._position_notification_toasts)
        event.Skip()

    def _open_command_palette(self, _event=None) -> None:
        """Open the palette over every command, surface, and setting.

        The Studio palette covers the whole application, so it is the palette
        this frame opens whenever the Studio shell exists.  The smaller list
        below is what a build without the Studio falls back to, and is still
        reachable from the command bar in exactly that case.
        """
        if self._studio is not None:
            self._studio.open_palette()
            return
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

    def _update_generation_is_active(self, generation: int) -> bool:
        """Return whether an update result can still reach this frame.

        A close attempt temporarily reserves its current generation so a worker
        that completes while unsaved-work protection is deciding can be
        reconciled if that close is vetoed. Accepted close teardown clears the
        reservation before destroying controls.
        """

        with self._update_worker_lock:
            return generation == self._update_state_generation or (
                self._is_closing and generation == self._closing_update_generation
            )

    def _resume_update_after_close_veto(
        self,
    ) -> tuple[SquirrelUpdateState, int] | None:
        """Restore the pending worker generation after a close veto."""

        with self._update_worker_lock:
            closing_generation = self._closing_update_generation
            pending_state = self._pending_update_state
            self._is_closing = False
            self._closing_update_generation = None
            self._pending_update_state = None
            if closing_generation is not None:
                self._update_state_generation = closing_generation
            if pending_state is not None and pending_state[1] == closing_generation:
                return pending_state
            return None

    def _discard_pending_update_after_accepted_close(self) -> None:
        """Keep update callbacks suppressed after a close starts teardown."""

        with self._update_worker_lock:
            self._closing_update_generation = None
            self._pending_update_state = None

    def _check_for_updates_async(self, _event=None) -> None:
        """Check without blocking startup or the active editing surface."""
        if self._is_closing or self.IsBeingDeleted():
            return
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

    def _queue_update_state(self, state: SquirrelUpdateState, generation: int) -> None:
        """Return a worker result to wx without reviving accepted teardown."""

        if self._update_generation_is_active(generation):
            wx.CallAfter(self._deliver_update_state, state, generation)

    def _deliver_update_state(
        self, state: SquirrelUpdateState, generation: int
    ) -> None:
        """Deliver a worker result or retain it across a vetoed close."""

        if self.IsBeingDeleted():
            return
        with self._update_worker_lock:
            if self._is_closing:
                if generation == self._closing_update_generation:
                    self._pending_update_state = state, generation
                return
        self._show_update_state(state, generation)

    def _update_worker(self, generation: int) -> None:
        self._queue_update_state(check_for_update(), generation)

    def _stage_update_async(self, _event=None) -> None:
        """Stage a discovered update without interrupting active editing."""
        if self._is_closing or self.IsBeingDeleted():
            return
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
        # The download itself has no worker result to wait for -- Squirrel's
        # staging call blocks the thread below until it finishes -- so the
        # banner's own "downloading" render is the only visible surface for
        # this state. It disables the action button rather than hiding the
        # banner, so the standing offer never silently disappears mid-fetch.
        self._render_update_banner(
            SquirrelUpdateState(
                "downloading",
                version=version,
                feed_url=feed_url,
                release_notes_url=release_notes_url,
            )
        )
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
        self._queue_update_state(state, generation)

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

    def restart_to_install_update(self) -> None:
        """Install the staged update, for callers outside this frame.

        The Studio's update command asks for this rather than reaching for the
        handler behind the banner button, so both routes run the same
        unsaved-work protection and the same Squirrel handoff.
        """
        self._restart_to_install_update()

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
            # Update.exe is a console program: restarting for an update must
            # not flash a terminal over the editor as it closes.
            process = subprocess.Popen(
                build_restart_command(updater),
                close_fds=True,
                **no_window_kwargs(),
            )
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
        """Invalidate async update work before wx begins destroying this frame."""
        if self._is_closing:
            # Consume a re-entrant EVT_CLOSE so it cannot skip past the
            # in-flight notebook transaction and its unsaved-world protection.
            # A forced shutdown cannot be vetoed, but it must never be skipped
            # from this handler as a second independent close transaction.
            if event.CanVeto():
                event.Veto()
            return
        with self._update_worker_lock:
            self._is_closing = True
            self._closing_update_generation = self._update_state_generation
            self._update_state_generation += 1
        generation = self._update_restart_generation
        if not self._level_notebook.on_app_close(
            event, preapproved_generation=generation
        ):
            pending_state = self._resume_update_after_close_veto()
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
            if pending_state is not None:
                self._show_update_state(*pending_state)
            return
        self._discard_pending_update_after_accepted_close()
        self.release_hosted_canvas()
        self._cancel_canvas_host_retry()
        if self._update_timer is not None and self._update_timer.IsRunning():
            self._update_timer.Stop()
        if (
            self._auto_stage_retry_timer is not None
            and self._auto_stage_retry_timer.IsRunning()
        ):
            self._auto_stage_retry_timer.Stop()
        if self._scheduled_timer is not None and self._scheduled_timer.IsRunning():
            self._scheduled_timer.Stop()
        self._scheduled_runtime.stop()
        self._narrator.close()
        if self._progress_overlay is not None:
            self._progress_overlay.stop()
            self._progress_overlay.dismiss_all()
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
        self._position_notification_toasts()

    def _rewrap_update_banner_text(self, card_width: int | None = None) -> None:
        """Re-flow the banner's title and body for the width it now has.

        Measured with :func:`wrap_lines` rather than repeated
        ``wx.StaticText.Wrap`` calls, which stop rewrapping after the first
        one on wxWidgets 3.3.3 -- the exact bug that left "Choose Stage
        avai..." clipped mid-word instead of wrapping to a second line.
        """
        text = self._update_banner_raw_text
        if not text:
            return
        if card_width is None:
            card_width = self._update_banner.GetSize().width
        available = max(160, card_width - 48)
        dc = wx.ClientDC(self._update_banner_text)
        lines = wrap_lines(dc, self._update_banner_text.GetFont(), text, available)
        self._update_banner_text.SetLabel("\n".join(lines))
        self._update_banner_text.InvalidateBestSize()

    def _render_update_banner(self, state: SquirrelUpdateState) -> None:
        title, body = update_copy.update_copy(
            state.status, version=state.version, detail=state.detail
        )
        self._update_banner_raw_text = f"{title}\n{body}"
        self._rewrap_update_banner_text()
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
        self._update_banner_action.Enable(state.status != "downloading")
        if state.status == "available":
            self._update_banner_action.SetToolTip(
                "Download the unsigned update in the background."
            )
        elif state.status == "downloading":
            self._update_banner_action.SetToolTip(
                "The unsigned update is already downloading in the background."
            )
        elif state.status == "ready_to_restart":
            self._update_banner_action.SetToolTip(
                "Restart only after saving your work."
            )
        else:
            self._update_banner_action.SetToolTip("Retry the bounded update check.")
        self._update_banner.Show()
        # Positioned, not laid out. As a sizer child under the Studio shell this
        # card collapsed to twenty pixels square and was never seen, so the
        # updater worked perfectly and reported into nothing. It now floats in
        # the same corner stack as the notifications, above them, and persists
        # until acted on -- an update is a standing offer, not a passing message.
        self._position_notification_toasts()
        self._update_banner.Raise()

    def _show_update_state(
        self, state: SquirrelUpdateState, generation: int | None = None
    ) -> None:
        """Render a persistent, non-modal status message for update state."""
        if self._is_closing or self.IsBeingDeleted():
            return
        if self._update_restart_generation is not None:
            return
        if generation is not None and not self._update_generation_is_active(generation):
            return
        self._update_state = state
        if self._studio is not None:
            # The backstage reports only what this frame has actually observed,
            # so it is told the state rather than checking the feed itself.
            self._studio.set_update_state(
                state.status, state.version or "", state.detail or ""
            )
        # With automatic staging on, "available" is not a user-facing moment --
        # it silently becomes a staging attempt below, so it earns neither a
        # banner ("press this to stage") nor a notification/narration nobody
        # needs to act on. The banner reappears once staging actually resolves
        # to "ready_to_restart" or "failed".
        auto_staging_now = (
            state.status == "available" and preferences.load().auto_stage_updates
        )
        if (
            state.status in {"available", "ready_to_restart", "failed"}
            and not auto_staging_now
        ):
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
                notify(
                    self,
                    title,
                    body,
                    severity=(
                        "error"
                        if state.status == "failed"
                        else (
                            "success" if state.status == "ready_to_restart" else "info"
                        )
                    ),
                    details=(state.detail or "") if state.status == "failed" else "",
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
        if auto_staging_now:
            self.SetStatusText(
                f"Update {state.version or 'new version'} found — staging automatically…"
            )
        elif state.status == "available":
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
        if auto_staging_now:
            self._maybe_auto_stage_update(
                generation if generation is not None else self._update_state_generation
            )

    def _progress_overlay_busy(self) -> bool:
        """Report whether a long operation is running that staging should avoid.

        Automatic staging must never compete with active editing, so it treats
        any currently-running progress row -- world load/save, export, and the
        rest -- as a reason to stand aside and retry rather than download now.
        """
        overlay = self._progress_overlay
        if overlay is None:
            return False
        return any(task.state == RUNNING for task in overlay.tasks())

    def _maybe_auto_stage_update(self, generation: int) -> None:
        """Stage a discovered update by itself, deferring around busy work.

        This is the automatic-staging counterpart to the banner's manual
        "Stage available update" button: it runs the exact same worker, so a
        validated feed, a hash mismatch, and every other outcome are reported
        identically whichever route reached them.
        """
        if self._is_closing or self.IsBeingDeleted():
            return
        if not preferences.load().auto_stage_updates:
            return
        if self._update_state.status != "available":
            return
        if not self._update_generation_is_active(generation):
            return
        if self._progress_overlay_busy():
            if (
                self._auto_stage_retry_timer is not None
                and self._auto_stage_retry_timer.IsRunning()
            ):
                self._auto_stage_retry_timer.Stop()
            self._auto_stage_retry_timer = wx.CallLater(
                AUTO_STAGE_RETRY_MS, self._maybe_auto_stage_update, generation
            )
            return
        self._stage_update_async()


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
        # The Studio viewport may be showing this page's renderer. Give it back
        # before anything closes the world, so the canvas is destroyed with the
        # extension that owns it rather than outliving it inside the viewport.
        if self._owner_frame is not None:
            self._owner_frame.release_hosted_canvas(page, closing=True)
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
            # Deferred as well: the page is still being closed here, so the
            # project state is read once the notebook is settled rather than
            # while it still lists a world that is on its way out.
            wx.CallAfter(self._owner_frame.sync_studio_project)

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

            self.apply_tab_workspace()

        if self.GetCurrentPage() is not None:
            self.GetCurrentPage().enable()
        if self._owner_frame is not None:
            self._owner_frame._tab_rail.sync()
            self._owner_frame.sync_studio_project()

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
