"""The 3D editor must not redraw a still world on a metronome.

Before this change, ``Renderer._do_draw`` posted a ``PreDrawEvent`` and
called ``Refresh(False)`` on every single ``wx.Timer`` tick -- roughly 66
times a second -- whether or not the camera, the selection, the active tool,
the dimension, or the loaded chunks had changed since the previous tick. On a
still camera looking at already-loaded chunks that is a full GL redraw of the
world 66 times a second producing an identical image each time.

This module tests the gating logic directly, against ``Renderer`` instances
built with :func:`object.__new__` rather than a real world, resource pack,
and OpenGL context: :meth:`Renderer.__init__` eagerly constructs a
``RenderLevel`` from a real ``amulet`` level and a real ``OpenGLResourcePack``,
neither of which the redraw-gating logic under test touches. Building the real
things just to prove a boolean flag would make this test slow and fragile for
no coverage gained; the real-world, real-canvas measurement lives in
``scripts/measure_renderer_redraw_rate.py`` instead, which drives the shipped
fixture world end to end.
"""

from __future__ import annotations

import time
import unittest

import wx

from amulet_map_editor.programs.edit.api.renderer import (
    Renderer,
    _IDLE_REDRAW_INTERVAL,
)


def _make_renderer(canvas: wx.Window) -> Renderer:
    """Build a ``Renderer`` with only the state ``_do_draw``/``mark_dirty``
    touch, skipping the real world/resource-pack/OpenGL construction that
    ``__init__`` otherwise performs."""
    renderer = object.__new__(Renderer)
    # EditCanvasContainer.__init__ just stores a weakref to the canvas.
    from amulet_map_editor.programs.edit.api.edit_canvas_container import (
        EditCanvasContainer,
    )

    EditCanvasContainer.__init__(renderer, canvas)
    renderer._dirty = __import__("threading").Event()
    renderer._last_draw_time = time.monotonic()
    return renderer


class RendererIdleRedrawGateTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.App.Get() or wx.App(False)

    def _events(self, canvas, renderer):
        """Return a (post_count, refresh_count) recorder patched onto the
        module's ``wx.PostEvent`` and the canvas's own ``Refresh``.

        ``wx.PostEvent`` only *queues* the event for the next run of the
        event loop, so counting via a bound handler would need a real
        ``wx.Yield()``/``MainLoop`` per tick to observe delivery. Patching
        the call itself proves the renderer asked to draw, which is exactly
        what ``_do_draw`` is responsible for -- whether the queued event is
        later delivered is wx's job, not this class's.
        """
        counts = {"post": 0, "refresh": 0}
        import amulet_map_editor.programs.edit.api.renderer as renderer_module

        real_post_event = renderer_module.wx.PostEvent

        def counting_post_event(*a, **k):
            counts["post"] += 1
            return real_post_event(*a, **k)

        renderer_module.wx.PostEvent = counting_post_event
        self.addCleanup(setattr, renderer_module.wx, "PostEvent", real_post_event)

        real_refresh = canvas.Refresh

        def counting_refresh(*a, **k):
            counts["refresh"] += 1
            return real_refresh(*a, **k)

        canvas.Refresh = counting_refresh
        return counts

    def test_still_camera_does_not_accumulate_redraws_every_tick(self):
        """A clean (not dirty) renderer ticked many times in a row, faster
        than the idle floor, must draw at most once -- not once per tick."""
        canvas = wx.Frame(None)
        try:
            renderer = _make_renderer(canvas)
            counts = self._events(canvas, renderer)
            renderer._dirty.clear()
            renderer._last_draw_time = time.monotonic()

            for _ in range(50):
                renderer._do_draw(None)

            self.assertLessEqual(
                counts["post"],
                1,
                "a still, non-dirty renderer redrew "
                f"{counts['post']} times across 50 ticks with no idle floor "
                "elapsed; it should draw at most once (the leading edge) "
                f"until {_IDLE_REDRAW_INTERVAL}s of real time has passed",
            )
            self.assertEqual(
                counts["post"],
                counts["refresh"],
                "PreDrawEvent and Refresh() must be posted together, "
                f"got {counts['post']} PreDrawEvents vs "
                f"{counts['refresh']} Refresh() calls",
            )
        finally:
            canvas.Destroy()

    def test_mark_dirty_produces_exactly_one_redraw(self):
        """A single change (camera move, tool switch, ...) must produce
        exactly one redraw, not zero and not a flood."""
        canvas = wx.Frame(None)
        try:
            renderer = _make_renderer(canvas)
            counts = self._events(canvas, renderer)
            renderer._dirty.clear()
            renderer._last_draw_time = time.monotonic()

            # Simulate a camera-moved event's effect directly.
            renderer.mark_dirty()

            renderer._do_draw(None)
            self.assertEqual(
                counts["post"],
                1,
                "marking the renderer dirty once must produce exactly one "
                f"redraw on the next tick, got {counts['post']}",
            )

            # Subsequent ticks with nothing new marked dirty must not redraw
            # again immediately.
            for _ in range(10):
                renderer._do_draw(None)
            self.assertEqual(
                counts["post"],
                1,
                "a single dirty flag must not cause repeated redraws once "
                f"consumed, got {counts['post']} across the following ticks",
            )
        finally:
            canvas.Destroy()

    def test_idle_floor_still_redraws_eventually(self):
        """Even with nothing explicitly marked dirty, a redraw must still
        happen once the idle-floor interval has elapsed, so anything that
        changes the view without calling ``mark_dirty`` still reaches the
        screen."""
        canvas = wx.Frame(None)
        try:
            renderer = _make_renderer(canvas)
            counts = self._events(canvas, renderer)
            renderer._dirty.clear()
            # Pretend the last draw happened long enough ago that the idle
            # floor has elapsed.
            renderer._last_draw_time = time.monotonic() - (_IDLE_REDRAW_INTERVAL + 0.05)

            renderer._do_draw(None)

            self.assertEqual(
                counts["post"],
                1,
                "the idle floor did not fire a redraw once its interval " "had elapsed",
            )
        finally:
            canvas.Destroy()

    def test_continuous_dirty_marking_draws_every_tick(self):
        """While something keeps marking the renderer dirty every tick (an
        orbit, streaming chunks), the draw rate must not drop below the
        timer's own rate -- this is the 'do not slow down real motion'
        requirement."""
        canvas = wx.Frame(None)
        try:
            renderer = _make_renderer(canvas)
            counts = self._events(canvas, renderer)

            for _ in range(30):
                renderer.mark_dirty()  # e.g. a camera-moved event each tick
                renderer._do_draw(None)

            self.assertEqual(
                counts["post"],
                30,
                "continuous interaction must draw on every tick; got "
                f"{counts['post']} draws across 30 dirty ticks",
            )
        finally:
            canvas.Destroy()


if __name__ == "__main__":
    unittest.main()
