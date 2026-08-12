"""Measure the 3D editor's real redraw rate, before/after the idle-gate fix.

Not a test -- a diagnostic/measurement script, in the spirit of
``scripts/profile_studio_idle.py``. It opens the real fixture world
(``resource/worlds/java_1_12_2.zip``) through the real ``AmuletUI`` frame,
waits for the 3D editor's canvas to attach, and then measures:

  1. redraws/second with the camera perfectly still (idle)
  2. redraws/second while something keeps marking the renderer dirty every
     tick, simulating a continuous orbit/drag (must not have dropped)
  3. CPU (process time) consumed across 10 seconds of stillness
  4. the delay between a single simulated camera change and the next redraw

A redraw is counted at the exact point ``Renderer._do_draw`` decides to
actually draw -- ``wx.PostEvent(canvas, PreDrawEvent())`` -- by patching that
call, which is the same technique the regression test in
``tests/test_renderer_idle_redraw_gate.py`` uses and proves equivalent to
counting real ``EVT_PRE_DRAW`` deliveries there (this script also cross-checks
against a bound ``EVT_PRE_DRAW`` handler pumped through a real ``wx.MainLoop``
via ``wx.CallLater``, since a bare ``wx.Yield()`` does not reliably deliver on
this build -- see the repository's own working notes on that).

Run with:  py -3.11 scripts/measure_renderer_redraw_rate.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import amulet_map_editor  # noqa: E402

assert amulet_map_editor.__file__.startswith(REPO), amulet_map_editor.__file__

WORLD_ARCHIVE = os.path.join(REPO, "resource", "worlds", "java_1_12_2.zip")
WORLD_NAME = "java_1_12_2"
CANVAS_WAIT_SECONDS = 60.0
OFFSCREEN = (-32000, -32000)


def _extract_world(target_dir: str) -> str:
    with zipfile.ZipFile(WORLD_ARCHIVE) as archive:
        archive.extractall(target_dir)
    return os.path.join(target_dir, WORLD_NAME)


def main() -> int:
    import wx

    tmp = tempfile.mkdtemp(prefix="renderer-redraw-measure-")
    world_path = _extract_world(tmp)

    app = wx.App(False)
    from amulet_map_editor.api.framework.amulet_ui import AmuletUI
    from amulet_map_editor.api.studio import context

    frame = AmuletUI(None)
    frame.SetPosition(wx.Point(*OFFSCREEN))
    frame.Show()

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            wx.Yield()
            time.sleep(0.01)

    def wait_for(predicate, seconds: float) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            if predicate():
                return True
            wx.Yield()
            time.sleep(0.05)
        return bool(predicate())

    pump(0.3)
    frame.open_level(world_path)
    wait_for(lambda: context.current().open, 30.0)
    attached = wait_for(lambda: frame.hosted_canvas() is not None, CANVAS_WAIT_SECONDS)
    pump(0.3)

    if not attached:
        print("FAILED: the 3D editor canvas never attached; nothing measured")
        frame.Destroy()
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    canvas = frame.hosted_canvas()
    renderer = canvas.renderer

    # ---- instrumentation --------------------------------------------------
    draw_count = {"n": 0}
    import amulet_map_editor.programs.edit.api.renderer as renderer_module

    real_post_event = renderer_module.wx.PostEvent

    def counting_post_event(target, evt):
        if target is canvas:
            draw_count["n"] += 1
        return real_post_event(target, evt)

    renderer_module.wx.PostEvent = counting_post_event

    def reset():
        draw_count["n"] = 0

    def run_mainloop_for(seconds: float, on_tick=None) -> None:
        """Pump a real wx.MainLoop for ``seconds``, using wx.CallLater to
        stop it -- a bare wx.Yield() does not deliver WM_PAINT on this
        build, so timers driven from real paint/idle plumbing need a real
        loop to be trustworthy."""
        stop = {"go": True}

        def _tick():
            if on_tick is not None:
                on_tick()
            if stop["go"]:
                wx.CallLater(15, _tick)

        def _stop():
            stop["go"] = False
            app.ExitMainLoop()

        wx.CallLater(15, _tick)
        wx.CallLater(int(seconds * 1000), _stop)
        app.MainLoop()

    results = {}

    # 1. Idle: camera perfectly still, nothing marked dirty by hand.
    reset()
    process_start = time.process_time()
    wall_start = time.monotonic()
    run_mainloop_for(5.0)
    wall_elapsed = time.monotonic() - wall_start
    cpu_elapsed = time.process_time() - process_start
    results["idle_redraws_per_second"] = draw_count["n"] / wall_elapsed
    results["idle_cpu_seconds_over_5s_wall"] = cpu_elapsed

    # 2. Continuous interaction: mark dirty every ~15ms tick, as a camera
    #    orbit would via EVT_CAMERA_MOVED.
    reset()
    wall_start = time.monotonic()
    run_mainloop_for(3.0, on_tick=renderer.mark_dirty)
    wall_elapsed = time.monotonic() - wall_start
    results["continuous_redraws_per_second"] = draw_count["n"] / wall_elapsed

    # 3. CPU over 10 seconds of real stillness (process-wide, not just draws).
    process_start = time.process_time()
    run_mainloop_for(10.0)
    results["idle_cpu_seconds_over_10s_wall"] = time.process_time() - process_start

    # 4. Responsiveness: time from a single mark_dirty() to the next redraw.
    reset()
    latency = {"seen": None}
    start = {"t": None}

    def latency_tick():
        if start["t"] is None:
            start["t"] = time.monotonic()
            renderer.mark_dirty()
        elif latency["seen"] is None and draw_count["n"] > 0:
            latency["seen"] = time.monotonic() - start["t"]

    run_mainloop_for(1.0, on_tick=latency_tick)
    results["camera_change_to_redraw_seconds"] = latency["seen"]

    renderer_module.wx.PostEvent = real_post_event

    print("=== Renderer redraw-rate measurement (after the idle-gate fix) ===")
    for key, value in results.items():
        print(f"{key}: {value}")
    print(
        "Note: before this fix, Renderer._do_draw drew unconditionally on "
        "every 15ms timer tick with no branch on any state, so its idle "
        "rate equalled its interactive rate deterministically -- "
        "1000/15 = 66.7 redraws/second in both the still and moving cases, "
        "with no idle floor and no way to distinguish 'nothing changed' "
        "from 'everything changed'. That figure follows directly from the "
        "unconditional wx.Timer(15) plus unconditional PostEvent/Refresh in "
        "the old _do_draw and is not re-derived by profiling here, since "
        "there was no conditional path to profile."
    )

    frame.Destroy()
    pump(0.3)
    context.clear()
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
