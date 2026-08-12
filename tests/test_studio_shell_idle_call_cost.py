"""An idle Studio shell must not paint, layout, or refresh on its own.

A prior pass fixed ``config.get()`` being re-read from disk inside the paint
loop (see :mod:`tests.test_studio_shell_config_read_cost`).  This is the
companion regression for a different report -- "still very laggy" after that
fix landed -- covering the shape a lagging idle window usually takes: a
runaway ``wx.Timer``, a hover handler that refreshes every mouse-move instead
of only on a real hover change, or a ``Layout()`` called from inside a paint
handler.

Profiling the real shell under a genuine ``wx.MainLoop`` (a bare
``wx.Yield()`` delivers no ``WM_PAINT`` on this build; see
``scripts/profile_studio_idle.py`` for the harness this borrows from) found
none of those shapes: an idle shell paints once (the initial frame), never
calls ``Layout()`` on its own, and a burst of synthetic ``EVT_MOTION`` events
over the ribbon produces no additional ``Refresh()`` calls, because the
motion handlers on this tree only touch drag state or are bound to
enter/leave rather than motion.

This is a call-count assertion, not a timing one, for the same reason the
other shell-construction test in this suite is: a stopwatch on a shared
runner measures the runner, not the code.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock


class StudioShellIdleCallCostTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        os.environ["CONFIG_DIR"] = cls._dir.name
        import wx

        from amulet_map_editor.api import config, preferences, school_mode
        from amulet_map_editor.api.studio.shell import StudioShell

        config.invalidate()
        preferences.save(preferences.load())
        school_mode.set_mode_name(school_mode.load().mode_name)

        cls.wx = wx
        cls.config = config
        cls.StudioShell = StudioShell
        existing = wx.App.Get()
        cls._created_app = existing is None and wx.App(False)
        cls.app = existing or cls._created_app

    @classmethod
    def tearDownClass(cls):
        if cls._created_app:
            cls._created_app.Destroy()
        cls.config.invalidate()
        cls._dir.cleanup()

    def _build_shell(self):
        frame = self.wx.Frame(None, size=self.wx.Size(1440, 920))
        panel = self.StudioShell(frame, frame)
        sizer = self.wx.BoxSizer(self.wx.VERTICAL)
        sizer.Add(panel, 1, self.wx.EXPAND)
        frame.SetSizer(sizer)
        frame.Show()
        frame.Layout()
        frame.Refresh()
        frame.Update()
        self.wx.Yield()
        return frame, panel

    def test_idle_shell_does_not_refresh_or_layout_on_its_own(self):
        """A shell sitting idle -- and then jostled by mouse motion, exactly
        as a user resting the pointer on the ribbon would do -- must not
        call ``Refresh()`` or ``Layout()`` on its own initiative.  Any call
        recorded here happened without a real state change: nothing was
        clicked, nothing was typed, and the synthetic motion events below
        never leave the panel's own bounds."""
        counts = {"refresh": 0, "layout": 0}
        real_refresh = self.wx.Window.Refresh
        real_layout = self.wx.Window.Layout

        def counting_refresh(win, *a, **k):
            counts["refresh"] += 1
            return real_refresh(win, *a, **k)

        def counting_layout(win, *a, **k):
            counts["layout"] += 1
            return real_layout(win, *a, **k)

        frame, panel = self._build_shell()
        try:
            with mock.patch.object(
                self.wx.Window, "Refresh", counting_refresh
            ), mock.patch.object(self.wx.Window, "Layout", counting_layout):
                # A quiet moment, then a burst of pointer movement over the
                # ribbon -- the shape a resting or wandering mouse actually
                # produces, and the shape a hover-refresh regression would
                # show up in first.
                for _ in range(3):
                    self.wx.Yield()
                for i in range(0, 200, 4):
                    evt = self.wx.MouseEvent(self.wx.wxEVT_MOTION)
                    evt.SetPosition(self.wx.Point(50 + (i % 300), 40 + (i % 100)))
                    panel.GetEventHandler().ProcessEvent(evt)
                for _ in range(3):
                    self.wx.Yield()
        finally:
            frame.Destroy()
            self.wx.Yield()

        self.assertEqual(
            counts["layout"],
            0,
            "an idle shell called Layout() on its own after construction; "
            "Layout() belongs to a real size or content change, never to "
            "idle time or mouse movement",
        )
        self.assertLessEqual(
            counts["refresh"],
            5,
            "an idle shell jostled by mouse movement issued "
            f"{counts['refresh']} Refresh() calls with no real hover "
            "change or click; a hover handler is refreshing on every "
            "motion event instead of only on a real state change: "
            f"{counts}",
        )


if __name__ == "__main__":
    unittest.main()
