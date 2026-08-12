"""Profile the real StudioShell under a real wx.MainLoop.

Not a test -- a diagnostic script.  Builds the shell exactly like the shell
tests do, pumps a genuine ``wx.MainLoop`` (a bare ``wx.Yield()`` does not
deliver WM_PAINT on this build), and profiles: idle, pointer movement over
the ribbon, ribbon tab switches, and backstage tab switches.

Run with:  py -3.11 scripts/profile_studio_idle.py
"""

from __future__ import annotations

import cProfile
import io
import os
import pstats
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

_dir = tempfile.TemporaryDirectory()
os.environ["CONFIG_DIR"] = _dir.name

import wx  # noqa: E402

import amulet_map_editor  # noqa: E402

assert amulet_map_editor.__file__.startswith(REPO), amulet_map_editor.__file__

from amulet_map_editor.api import config, preferences, school_mode  # noqa: E402
from amulet_map_editor.api.studio.shell import StudioShell  # noqa: E402

config.invalidate()
preferences.save(preferences.load())
school_mode.set_mode_name(school_mode.load().mode_name)

app = wx.App(False)
frame = wx.Frame(None, size=wx.Size(1440, 920))
panel = StudioShell(frame, frame)
sizer = wx.BoxSizer(wx.VERTICAL)
sizer.Add(panel, 1, wx.EXPAND)
frame.SetSizer(sizer)
frame.Show()
frame.Layout()

# ---- instrumentation: count paints/layouts/refreshes/timer ticks --------
_counts = {"paint": 0, "layout": 0, "refresh": 0, "timer": 0}

_orig_refresh = wx.Window.Refresh


def _counting_refresh(self, *a, **k):
    _counts["refresh"] += 1
    return _orig_refresh(self, *a, **k)


wx.Window.Refresh = _counting_refresh

_orig_layout = wx.Window.Layout


def _counting_layout(self, *a, **k):
    _counts["layout"] += 1
    return _orig_layout(self, *a, **k)


wx.Window.Layout = _counting_layout


def _on_paint_any(evt):
    _counts["paint"] += 1
    evt.Skip()


frame.Bind(wx.EVT_PAINT, _on_paint_any)
panel.Bind(wx.EVT_PAINT, _on_paint_any)

steps = []


def step_idle_start():
    steps.append(("idle-start", time.monotonic()))


def step_move_mouse():
    size = panel.GetSize()
    for i in range(0, 200, 4):
        x = 50 + (i % 300)
        y = 40 + (i % 100)
        evt = wx.MouseEvent(wx.wxEVT_MOTION)
        evt.SetPosition(wx.Point(x, y))
        panel.GetEventHandler().ProcessEvent(evt)
    steps.append(("moved-mouse", time.monotonic()))


def step_idle_end():
    steps.append(("idle-end", time.monotonic()))
    wx.CallLater(50, finish)


def finish():
    app.ExitMainLoop()


profiler = cProfile.Profile()
profiler.enable()

wx.CallLater(10, step_idle_start)
wx.CallLater(3000, step_move_mouse)
wx.CallLater(6000, step_idle_end)

app.MainLoop()

profiler.disable()

frame.Destroy()

buf = io.StringIO()
ps = pstats.Stats(profiler, stream=buf).sort_stats("cumulative")
ps.print_stats(30)
print("=== BY CUMULATIVE TIME ===")
print(buf.getvalue())

buf2 = io.StringIO()
ps2 = pstats.Stats(profiler, stream=buf2).sort_stats("ncalls")
ps2.print_stats(30)
print("=== BY CALL COUNT ===")
print(buf2.getvalue())

print("=== EVENT COUNTS OVER ~6s ===")
print(_counts)
print("=== STEP TIMESTAMPS ===")
print(steps)
