import os
import glob
from sys import platform
from typing import List, Dict, Tuple, Callable, TYPE_CHECKING
import traceback
import logging
import zipfile
import subprocess
import threading
from amulet_map_editor.api import process

import wx

from amulet import load_format
from amulet.api.errors import FormatError

from amulet_map_editor import lang, CONFIG
from amulet_map_editor.api.studio import widgets as studio
from amulet_map_editor.api.wx.ui import simple
from amulet_map_editor.api.wx.ui.path_dialog import choose_path
from amulet_map_editor.api.wx.nonblocking import notify, notify_exception
from amulet_map_editor.api.wx.progress import begin_progress
from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.api.framework import app

if TYPE_CHECKING:
    from amulet.api.wrapper import WorldFormatWrapper

log = logging.getLogger(__name__)


# Windows 	%APPDATA%\.minecraft
# macOS 	~/Library/Application Support/minecraft
# Linux 	~/.minecraft

minecraft_world_paths: list[tuple[str, str]] = []


def find_world_paths() -> None:
    """Discover automatic world locations for the world picker."""
    minecraft_world_paths.clear()
    modrinth_path = ""
    curseforge_path = ""

    if platform == "win32":
        appdata = os.getenv("APPDATA")
        localappdata = os.getenv("LOCALAPPDATA")

        if appdata:
            minecraft_world_paths.extend(
                (
                    (
                        lang.get("world.java_platform"),
                        os.path.join(appdata, ".minecraft", "saves"),
                    ),
                    (
                        lang.get("world.bedrock_education_desktop"),
                        os.path.join(
                            appdata,
                            "Minecraft Education Edition",
                            "games",
                            "com.mojang",
                            "minecraftWorlds",
                        ),
                    ),
                    (
                        lang.get("world.bedrock_netease"),
                        os.path.join(
                            appdata,
                            "MinecraftPE_Netease",
                            "minecraftWorlds",
                        ),
                    ),
                    (
                        lang.get("world.legends_legacy"),
                        os.path.join(
                            appdata,
                            "MinecraftPE",
                            "games",
                            "com.mojang",
                            "minecraftWorlds",
                        ),
                    ),
                )
            )
            for group, key in (
                ("Minecraft Bedrock", "world.bedrock_gdk"),
                ("Minecraft Bedrock Preview", "world.bedrock_gdk_preview"),
            ):
                for worlds_path in glob.glob(
                    os.path.join(
                        glob.escape(appdata),
                        group,
                        "Users",
                        "*",
                        "games",
                        "com.mojang",
                        "minecraftWorlds",
                    )
                ):
                    user_id = worlds_path.split(os.sep)[-4]
                    minecraft_world_paths.append(
                        (
                            f"{lang.get(key)} {user_id}",
                            worlds_path,
                        )
                    )
            modrinth_path = os.path.join(appdata, "ModrinthApp")
            curseforge_path = os.path.join(appdata, "curseforge", "minecraft")

        if localappdata:
            minecraft_world_paths.extend(
                (
                    (
                        lang.get("world.bedrock_uwp"),
                        os.path.join(
                            localappdata,
                            "Packages",
                            "Microsoft.MinecraftUWP_8wekyb3d8bbwe",
                            "LocalState",
                            "games",
                            "com.mojang",
                            "minecraftWorlds",
                        ),
                    ),
                    (
                        lang.get("world.bedrock_uwp_beta"),
                        os.path.join(
                            localappdata,
                            "Packages",
                            "Microsoft.MinecraftWindowsBeta_8wekyb3d8bbwe",
                            "LocalState",
                            "games",
                            "com.mojang",
                            "minecraftWorlds",
                        ),
                    ),
                    (
                        lang.get("world.bedrock_education_store"),
                        os.path.join(
                            localappdata,
                            "Packages",
                            "Microsoft.MinecraftEducationEdition_8wekyb3d8bbwe",
                            "LocalState",
                            "games",
                            "com.mojang",
                            "minecraftWorlds",
                        ),
                    ),
                )
            )

    elif platform == "darwin":
        minecraft_world_paths.append(
            (
                lang.get("world.java_platform"),
                os.path.join(
                    os.path.expanduser("~"),
                    "Library",
                    "Application Support",
                    "minecraft",
                    "saves",
                ),
            )
        )
        minecraft_world_paths.append(
            (
                lang.get("world.pocket_platform"),
                os.path.join(
                    os.path.expanduser("~"),
                    "Library",
                    "Application Support",
                    "minecraftpe",
                    "games",
                    "com.mojang",
                    "minecraftWorlds",
                ),
            )
        )
        modrinth_path = os.path.join(
            os.path.expanduser("~"), "Library", "Application Support", "ModrinthApp"
        )
        curseforge_path = os.path.join(
            os.path.expanduser("~"), "Documents", "curseforge", "minecraft"
        )
    elif platform == "linux":
        minecraft_world_paths.append(
            (
                lang.get("world.java_platform"),
                os.path.join(os.path.expanduser("~"), ".minecraft", "saves"),
            )
        )
        modrinth_path = os.path.join(
            os.path.expanduser("~"), ".local", "share", "ModrinthApp"
        )
        curseforge_path = os.path.join(
            os.path.expanduser("~"), "Documents", "curseforge", "minecraft"
        )

    if os.path.isdir(modrinth_path):
        for path in glob.glob(
            os.path.join(glob.escape(modrinth_path), "profiles", "*", "saves")
        ):
            if os.path.isdir(path):
                profile = os.path.basename(os.path.dirname(path))
                minecraft_world_paths.append(
                    (
                        f"{lang.get('world.modrinth')} - {profile}",
                        path,
                    )
                )
    if os.path.isdir(curseforge_path):
        for path in glob.glob(
            os.path.join(glob.escape(curseforge_path), "Instances", "*", "saves")
        ):
            if os.path.isdir(path):
                profile = os.path.basename(os.path.dirname(path))
                minecraft_world_paths.append(
                    (
                        f"{lang.get('world.curseforge')} - {profile}",
                        path,
                    ),
                )


world_images: Dict[str, Tuple[int, wx.Bitmap, int]] = {}


def get_world_image(image_path: str) -> Tuple[wx.Bitmap, int]:
    if (
        image_path not in world_images
        or world_images[image_path][0] != os.stat(image_path)[8]
    ):
        img = wx.Image(image_path, wx.BITMAP_TYPE_ANY)
        width = min(int((img.GetWidth() / img.GetHeight()) * 128), 300)

        world_images[image_path] = (
            os.stat(image_path)[8],
            img.Scale(width, 128, wx.IMAGE_QUALITY_NEAREST).ConvertToBitmap(),
            width,
        )

    return world_images[image_path][1:3]


class WorldUI(wx.Panel):
    """A Panel UI element with the world image, name and description"""

    def __init__(self, parent: wx.Window, world_format: "WorldFormatWrapper"):
        super().__init__(parent)
        self.SetWindowStyle(wx.TAB_TRAVERSAL | wx.BORDER_RAISED)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(sizer)

        img, width = get_world_image(world_format.world_image_path)

        self.img = wx.StaticBitmap(self, wx.ID_ANY, img, (0, 0), (width, 128))
        sizer.Add(self.img)

        self.world_name = studio.StudioText(
            self,
            "\n".join(
                [
                    world_format.level_name,
                    world_format.game_version_string,
                    os.path.join(
                        *os.path.normpath(world_format.path).split(os.sep)[-3:]
                    ),
                ]
            ),
            size_px=13,
            role="on_surface",
            name=world_format.level_name,
        )
        sizer.Add(self.world_name, 0, wx.ALL | wx.ALIGN_CENTER, 5)


class WorldUIButton(WorldUI):
    """A Panel UI element that behaves like a button with the world image, name and description"""

    def __init__(
        self,
        parent: wx.Window,
        world_format: "WorldFormatWrapper",
        open_world_callback,
    ):
        super().__init__(parent, world_format)
        self.path = world_format.path
        self.open_world_callback = open_world_callback

        self.Bind(wx.EVT_LEFT_UP, self._call_callback)
        self.img.Bind(wx.EVT_LEFT_UP, self._call_callback)
        self.world_name.Bind(wx.EVT_LEFT_DOWN, self._call_callback)

    def _call_callback(self, evt):
        self.open_world_callback(self.path)


class WorldList(wx.Panel):
    """A Panel containing zero or more `WorldUIButton`s."""

    def __init__(self, parent: wx.Window, world_dirs, open_world_callback, sort=True):
        super().__init__(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)

        self.worlds = []

        world_formats = []
        for world_path in world_dirs:
            if os.path.isdir(world_path):
                try:
                    world_formats.append(load_format(world_path))
                except FormatError as e:
                    log.info(f"Could not find loader for {world_path} {e}")
                except Exception:
                    log.error(
                        f"Error loading format wrapper for {world_path} {traceback.format_exc()}"
                    )
        if sort:
            world_formats = reversed(sorted(world_formats, key=lambda f: f.last_played))

        for world_format in world_formats:
            try:
                world_button = WorldUIButton(self, world_format, open_world_callback)
                sizer.Add(
                    world_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 5
                )
                self.worlds.append(world_button)
            except Exception as e:
                log.info(f"Failed to display world button for {world_format.path} {e}")

        self.Layout()


class CollapsibleWorldListUI(wx.CollapsiblePane):
    """a drop down list of `WorldUIButton`s for a given directory"""

    def __init__(
        self,
        parent,
        paths: List[str],
        group_name: str,
        open_world_callback,
        root_directory: str | None = None,
    ):
        super().__init__(parent, label=group_name)
        self.parent = parent
        self.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self.eval_layout)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.sizer)

        panel = self.GetPane()
        panel_sizer = wx.BoxSizer(wx.VERTICAL)
        panel.SetSizer(panel_sizer)

        if root_directory is not None and os.path.isdir(root_directory):

            def open_directory(evt):
                if platform == "win32":
                    os.startfile(root_directory)
                elif platform == "darwin":
                    process.call(["open", root_directory])
                else:
                    process.call(["xdg-open", root_directory])
                evt.Skip()

            open_directory_button = studio.StudioButton(
                panel,
                lang.get("select_world.open_directory"),
                variant="outlined",
                name=lang.get("select_world.open_directory"),
            )
            panel_sizer.Add(
                open_directory_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 5
            )
            open_directory_button.Bind(wx.EVT_BUTTON, open_directory)

        panel_sizer.Add(WorldList(panel, paths, open_world_callback), 0, wx.EXPAND)

    def eval_layout(self, evt):
        self.Layout()
        self.parent.FitInside()
        evt.Skip()


class ScrollableWorldsUI(simple.SimpleScrollablePanel):
    # a frame to allow scrolling
    def __init__(self, parent, open_world_callback):
        super(ScrollableWorldsUI, self).__init__(parent)
        self.open_world_callback = open_world_callback

        self.dirs: Dict[str, CollapsibleWorldListUI] = {}
        self.reload()

        self.Layout()

    def reload(self):
        find_world_paths()
        for val in self.dirs.values():
            val.Destroy()
        self.dirs.clear()
        for group_name, directory in sorted(minecraft_world_paths, key=lambda x: x[0]):
            if os.path.isdir(directory):
                world_list = CollapsibleWorldListUI(
                    self,
                    glob.glob(os.path.join(glob.escape(directory), "*")),
                    group_name,
                    self.open_world_callback,
                    directory,
                )
                self.add_object(world_list, 0, wx.EXPAND)
                self.dirs[directory] = world_list

    def OnChildFocus(self, event):
        event.Skip()


class WorldSelectUI(wx.Panel):
    # a frame containing a refresh button for the UI, a sort order for the worlds
    # and a vertical list of `WorldDirectoryUI`s for each directory
    # perhaps also a select directory option
    def __init__(self, parent, open_world_callback):
        super().__init__(parent)
        self.open_world_callback = open_world_callback

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)

        header_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(header_sizer, 0, wx.EXPAND)
        header_sizer.AddStretchSpacer()

        self.header_open_world = studio.StudioButton(
            self,
            lang.get("select_world.open_world_button"),
            variant="filled",
            name=lang.get("select_world.open_world_button"),
        )
        self.header_open_world.Bind(wx.EVT_BUTTON, self._open_world)
        header_sizer.Add(self.header_open_world)

        header_sizer.AddSpacer(20)

        self.header_open_mcworld = studio.StudioButton(
            self,
            lang.get("select_world.open_mcworld_button"),
            variant="outlined",
            name=lang.get("select_world.open_mcworld_button"),
        )
        self.header_open_mcworld.Bind(wx.EVT_BUTTON, self._open_mcworld)
        header_sizer.Add(self.header_open_mcworld)

        header_sizer.AddStretchSpacer()

        content = ScrollableWorldsUI(self, open_world_callback)
        sizer.Add(content, 1, wx.EXPAND)
        apply_material3(self)

    def _open_world(self, evt):
        path = choose_path(
            self, lang.get("select_world.open_world_dialogue"), directory=True
        )
        if path is None:
            return
        self.open_world_callback(path)

    def _open_mcworld(self, evt):
        mcworld_path = choose_path(
            self,
            lang.get("select_world.open_mcworld_dialogue"),
            wildcard="Bedrock world archive (*.mcworld)|*.mcworld",
        )
        if mcworld_path is None:
            return

        extract_dir = choose_path(
            self,
            lang.get("select_world.extract_mcworld_dialogue"),
            directory=True,
        )
        if extract_dir is None:
            return

        # ``wx.BusyInfo`` used to stand in for this: a borderless banner that
        # blocks input and reports nothing at all, so a large archive looked
        # identical after ten seconds and after ten minutes.  The overlay says
        # what is being extracted and how far through it is, and the shell
        # underneath stays live.
        #
        # An archive knows how many members it holds, so this is genuinely
        # measurable and draws a filling bar.  It is extracted member by member
        # on a worker thread rather than through ``extractall`` for exactly that
        # reason -- ``extractall`` returns one number, at the end.  Per-member
        # extraction goes through the same ``ZipFile.extract`` that
        # ``extractall`` calls, so the member-name sanitising that stops an
        # archive writing outside its destination is unchanged.
        report = begin_progress(
            self,
            key=f"extract-mcworld-{id(self)}",
            title=lang.get("select_world.extracting_world_wait"),
            detail=os.path.basename(mcworld_path),
        )
        try:
            if not os.path.isdir(extract_dir):
                raise NotADirectoryError(
                    f"Extraction destination is not an existing directory: {extract_dir}"
                )
            if next(os.scandir(extract_dir), None) is not None:
                report.finish()
                wx.LogError(lang.get("select_world.extracting_world_not_empty"))
                return
            self._extract_archive(mcworld_path, extract_dir, report)
        except Exception as e:
            report.fail(str(e) or type(e).__name__)
            notify_exception(
                self,
                lang.get("select_world.extracting_world_failed"),
                str(e),
                traceback.format_exc(),
            )
            return
        else:
            report.finish()

        notify(
            self,
            "World extraction finished",
            lang.get("select_world.extracting_world_finished"),
            severity="success",
        )

        self.open_world_callback(extract_dir)

    @staticmethod
    def _extract_archive(archive_path: str, destination: str, report) -> None:
        """Extract ``archive_path`` into ``destination``, reporting as it goes.

        The work runs on a worker thread and this yields between joins, which
        is what keeps the shell responsive and the overlay repainting.  An
        error on that thread is re-raised here so the caller's existing failure
        path -- which carries the traceback into notification history -- is the
        one that reports it.
        """
        state: Dict[str, object] = {"done": 0, "total": 0, "error": None}

        def work() -> None:
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    members = archive.infolist()
                    state["total"] = len(members)
                    for index, member in enumerate(members, 1):
                        archive.extract(member, destination)
                        state["done"] = index
            except BaseException as error:  # re-raised on the caller's thread
                state["error"] = error

        thread = threading.Thread(target=work, name="amulet-mcworld-extract")
        thread.daemon = True
        thread.start()
        while thread.is_alive():
            thread.join(0.05)
            total = int(state["total"] or 0)
            done = int(state["done"] or 0)
            # Until the archive has been opened there is no member count, so
            # there is no fraction to draw -- and an empty bar would claim a
            # measurement nobody has taken yet.
            report.update(
                fraction=(done / total) if total else None,
                indeterminate=not total,
                detail=(
                    f"{done} of {total} files"
                    if total
                    else os.path.basename(archive_path)
                ),
            )
            application = wx.GetApp()
            if application is not None:
                application.Yield()
        # ``is_alive()`` can already read False by the time the loop rechecks
        # it, even though the poll published one join earlier was still short
        # of the true final count -- the thread can finish its last member
        # between that publish and the next check. Flushing the state once
        # more here, now that the thread has genuinely terminated and every
        # member is written, is what guarantees the row is never left
        # reporting less than what actually happened.
        total = int(state["total"] or 0)
        done = int(state["done"] or 0)
        report.update(
            fraction=(done / total) if total else None,
            indeterminate=not total,
            detail=(
                f"{done} of {total} files" if total else os.path.basename(archive_path)
            ),
        )
        error = state["error"]
        if error is not None:
            raise error


class RecentWorldUI(wx.Panel):
    def __init__(self, parent, open_world_callback):
        super().__init__(parent)
        self._open_world_callback = open_world_callback

        self._sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self._sizer)

        text = studio.StudioText(
            self,
            lang.get("select_world.recent_worlds"),
            size_px=13,
            role="on_surface",
        )
        self._sizer.Add(
            text,
            0,
            wx.ALL | wx.ALIGN_CENTER,
            5,
        )

        self._world_list = None
        self.rebuild()

    def rebuild(self, new_world: str = None):
        meta: dict = CONFIG.get("amulet_meta", {})
        recent_worlds: list = meta.setdefault("recent_worlds", [])
        if new_world is not None:
            while new_world in recent_worlds:
                recent_worlds.remove(new_world)
            recent_worlds.insert(0, new_world)
            while len(recent_worlds) > 5:
                recent_worlds.pop(5)
        if self._world_list is not None:
            self._world_list.Destroy()
        self._world_list = WorldList(
            self, recent_worlds, self._open_world_callback, sort=False
        )
        self._sizer.Add(self._world_list, 1, wx.EXPAND, 5)
        self.Layout()
        CONFIG.put("amulet_meta", meta)


class WorldSelectAndRecentUI(wx.Panel):
    def __init__(self, parent, open_world_callback):
        super(WorldSelectAndRecentUI, self).__init__(parent, wx.HORIZONTAL)
        self._open_world_callback = open_world_callback

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)

        warning_text = studio.StudioText(
            self,
            lang.get("select_world.open_world_warning"),
            size_px=13,
            role="on_surface",
        )
        sizer.Add(warning_text, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.TOP, 5)
        # bar

        bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(bottom_sizer, 1, wx.EXPAND)

        left_sizer = wx.BoxSizer(wx.VERTICAL)
        bottom_sizer.Add(left_sizer, 1, wx.EXPAND)
        select_world = WorldSelectUI(self, self._update_recent)
        left_sizer.Add(select_world, 1, wx.ALL | wx.EXPAND, 5)

        right_sizer = wx.BoxSizer(wx.VERTICAL)
        bottom_sizer.Add(right_sizer, 1, wx.EXPAND)
        self._recent_worlds = RecentWorldUI(self, self._update_recent)
        right_sizer.Add(self._recent_worlds, 1, wx.EXPAND, 5)

    def _update_recent(self, path):
        self._recent_worlds.rebuild(path)
        self._open_world_callback(path)


class WorldSelectDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, open_world_callback: Callable[[str], None]):
        super().__init__(
            parent,
            title=lang.get("select_world.title"),
            pos=wx.Point(50, 50),
            size=wx.Size(*[int(s * 0.95) for s in parent.GetSize()]),
            # The shared M3 helper supplies the title bar and window controls;
            # keeping the native caption here would flash legacy chrome first.
            style=wx.NO_BORDER
            | wx.CLOSE_BOX
            | wx.TAB_TRAVERSAL
            | wx.CLIP_CHILDREN
            | wx.RESIZE_BORDER,
        )
        self.Bind(wx.EVT_CLOSE, self._hide_event)

        self._open_world_callback = open_world_callback
        root = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(root)
        self.world_select = WorldSelectAndRecentUI(self, self._run_callback)
        root.Add(self.world_select, 1, wx.EXPAND | wx.ALL, 12)
        root.Layout()
        apply_material3(self)

    def _run_callback(self, path):
        self._close()
        self._open_world_callback(path)

    def _hide_event(self, evt):
        self._close()
        evt.Skip()

    def _close(self):
        if self.IsModal():
            self.EndModal(0)
        else:
            self.Close()


def open_level_from_dialog(parent: wx.Window):
    """Show the open world dialog and open the selected world."""
    with WorldSelectDialog(parent, app.open_level) as select_world:
        select_world.CentreOnScreen()
        log.debug(f"Showing WorldSelectDialog at {select_world.GetRect()}")
        select_world.ShowModal()
