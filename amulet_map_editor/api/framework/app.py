import wx
from . import amulet_ui
import sys
import locale
import logging
import os

from amulet_map_editor.api.wx.material3 import apply_material3

# Disable OpenGL_accelerate logging
logging.getLogger("OpenGL.acceleratesupport").setLevel(logging.CRITICAL)
logging.getLogger("OpenGL.GL.shaders").setLevel(logging.INFO)
logging.getLogger("PIL.PngImagePlugin").setLevel(logging.INFO)

log = logging.getLogger(__name__)


def centre_on_main_screen(window: wx.TopLevelWindow) -> None:
    # The normal CentreOnParent method makes the window no larger than its parent which is often undesired.
    # CentreOnScreen for some reason in select cases displays the window on the wrong screen.
    window.CentreOnScreen()

    if wx.Display.GetCount() and not wx.Display(0).GetGeometry().Intersects(
        window.GetRect()
    ):
        # If the window does not intersect the main screen, manually position the window.
        log.debug(f"Window {window} was incorrectly displayed.")
        screen_rect = wx.Display(0).GetGeometry()
        window_size = window.GetSize()

        x = screen_rect.x + max(20, (screen_rect.width - window_size.GetWidth()) // 2)
        y = screen_rect.y + max(20, (screen_rect.height - window_size.GetHeight()) // 2)
        window.Move(wx.Point(x, y))


class AmuletApp(wx.App):
    _amulet_ui: amulet_ui.AmuletUI

    def OnInit(self):
        # Theme every subsequently-created dialog and tool window, not only
        # the shell that happens to exist during startup.  wx creates many
        # editor surfaces lazily, so a one-time frame pass would leave a
        # visibly mixed legacy/M3 application.
        self.Bind(wx.EVT_WINDOW_CREATE, self._on_window_create)
        for i in range(wx.Display.GetCount()):
            display = wx.Display(i)
            log.debug(f"Display {i} {display.GetGeometry()}")

        self._amulet_ui = amulet_ui.AmuletUI(None)
        self.SetTopWindow(self._amulet_ui)
        self._amulet_ui.Maximize()
        self._amulet_ui.Show()
        log.debug(
            f"Shown AmuletUI at {self._amulet_ui.GetRect()} maximised={self._amulet_ui.IsMaximized()}"
        )

        # Startup has no acknowledgement, purchase, review, or promotional
        # gate. Schedule the optional delight only after the usable shell has
        # returned to the event loop.
        wx.CallLater(0, self._amulet_ui.begin_startup_dim_sum_surprise)

        return True

    def _on_window_create(self, event: wx.WindowCreateEvent) -> None:
        """Apply the shared M3 tree theme to every native surface."""

        window = event.GetWindow()
        if window is not None and not getattr(window, "_material3_opt_out", False):
            wx.CallAfter(apply_material3, window)
            # Dialog/frame constructors frequently install their sizer after
            # EVT_WINDOW_CREATE. Retry once after layout construction so the
            # shared title bar and role tokens cannot miss a lazily-built
            # surface while remaining idempotent.
            wx.CallLater(100, apply_material3, window)
        event.Skip()

    def InitLocale(self):
        # https://discuss.wxpython.org/t/what-is-wxpython-doing-to-the-locale-to-makes-pandas-crash/34606/18
        if sys.version_info[:2] >= (3, 8):
            super().InitLocale()
        else:
            self.ResetLocale()
            lang, enc = locale.getlocale()
            if lang is None:
                self._initial_locale = wx.Locale(wx.LANGUAGE_DEFAULT)

    def open_level(self, path: str):
        """
        Open a level and create a tab for it.
        If a tab already exists it will just be shown.

        :param path: The path to the level to open.
        """
        self._amulet_ui.open_level(path)

    def close_level(self, path: str):
        """
        Close a level tab.

        :param path: The path to the level to close.
        """
        self._amulet_ui.close_level(path)


def get_app() -> AmuletApp:
    """Get the app instance."""
    app = wx.App.Get()
    if isinstance(app, AmuletApp):
        return app
    else:
        raise Exception("wx App is not an instance of AmuletApp")


def open_level(path: str):
    """
    Open a level and create a tab for it.
    If a tab already exists it will just be shown.

    :param path: The path to the level to open.
    """
    get_app().open_level(path)


def close_level(path: str):
    """
    Close a level tab.

    :param path: The path to the level to close.
    """
    get_app().close_level(path)
