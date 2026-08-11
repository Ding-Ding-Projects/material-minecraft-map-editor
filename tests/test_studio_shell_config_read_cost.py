"""Constructing the Studio shell must not re-read the profile file per widget.

Every owner-drawn control resolves an appearance token while it paints, and the
shell builds dozens of them: the ribbon, the navigator, the backstage cards,
the properties pane.  Before ``config.get`` cached a profile read, each of
those tokens cost a ``stat`` plus a gzip decompress plus an unpickle -- 207us,
measured -- and building the shell alone made 3,793 of those reads against
just two files.  This is the regression test for that fix at the scope where
it actually matters: constructing the real shell, not a synthetic loop of
token calls.

This is a call-count assertion, not a timing one, for the same reason the
token-level tests already in this suite are: a stopwatch on a shared runner
measures the runner.  It is also deliberately not a plain call-count-in-real-
time assertion either, because :data:`config.CACHE_SECONDS` is a time window
and real shell construction can legitimately take longer than it on a slow or
antivirus-scanned CI runner -- which would make an unfrozen clock flaky in
exactly the direction that hides a real regression less reliably.  Freezing
``config``'s clock for the construction removes that variable: with time held
still, the read window cannot lapse no matter how long the surrounding work
takes, so the count this asserts is the shape of the caching itself, not an
artifact of how fast this particular machine drew the frame.
"""

from __future__ import annotations

import gzip
import os
import tempfile
import unittest
from unittest import mock


class ShellConstructionConfigReadCostTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        os.environ["CONFIG_DIR"] = cls._dir.name
        import wx

        from amulet_map_editor.api import config, preferences, school_mode
        from amulet_map_editor.api.studio import tokens
        from amulet_map_editor.api.studio.shell import StudioShell

        config.invalidate()
        preferences.save(preferences.load())
        school_mode.set_mode_name(school_mode.load().mode_name)

        cls.wx = wx
        cls.config = config
        cls.tokens = tokens
        cls.StudioShell = StudioShell
        cls.app = wx.App(False)

    @classmethod
    def tearDownClass(cls):
        cls.config.invalidate()
        cls._dir.cleanup()

    def setUp(self):
        self.tokens.reset_caches()
        self.tokens._build_font.cache_clear()
        self.config.invalidate()

    def _count_opens_building_a_shell(self) -> int:
        """Build, show, and paint one real shell; return how many profile
        files it opened, with :mod:`config`'s clock held still throughout."""
        real_open = gzip.open
        opened = []

        def counting_open(path, *args, **kwargs):
            opened.append(os.path.basename(str(path)))
            return real_open(path, *args, **kwargs)

        frame = self.wx.Frame(None, size=self.wx.Size(1440, 920))
        frozen_at = self.config.time.monotonic()
        try:
            with mock.patch.object(gzip, "open", counting_open), mock.patch.object(
                self.config.time, "monotonic", return_value=frozen_at
            ):
                panel = self.StudioShell(frame, frame)
                sizer = self.wx.BoxSizer(self.wx.VERTICAL)
                sizer.Add(panel, 1, self.wx.EXPAND)
                frame.SetSizer(sizer)
                frame.Show()
                frame.Layout()
                frame.Refresh()
                frame.Update()
                self.wx.Yield()
        finally:
            frame.Destroy()
            self.wx.Yield()
        return opened

    def test_building_the_shell_opens_the_profile_a_bounded_number_of_times(self):
        opened = self._count_opens_building_a_shell()

        # Measured on a cold profile: constructing, showing, laying out, and
        # painting the whole shell -- title bar, backstage, ribbon,
        # navigator, viewport chrome, properties pane -- opens the two
        # profile files exactly twice between them (one read each) once the
        # clock cannot lapse the cache window mid-build.  The bound below is
        # generous room above that measured floor -- enough for a few more
        # identifiers to join this path later without this test needing a
        # rewrite -- while staying two orders of magnitude below what an
        # uncached read (one open per config.get() call; thousands, per the
        # call count below) would produce, so a real regression still fails
        # loudly rather than by a hair.
        self.assertLessEqual(
            len(opened),
            8,
            "constructing the shell opened the profile files "
            f"{len(opened)} times: {sorted(opened)}; a cached read should "
            "open each identifier once regardless of how many widgets ask "
            "for a token during construction",
        )

    def test_the_bound_is_not_met_by_accident(self):
        # A guard nobody has watched fail proves nothing: confirm the low
        # open count above is actually the cache doing work, rather than
        # the shell simply never asking for a token while it builds.  Every
        # owner-drawn control resolves the presentation on its own --
        # control_height/scaled/font/palette/density/emoji each call it --
        # so this counts entries into that resolution, not just the
        # profile-file opens the test above bounds.  If the caching in this
        # module (config's read cache, or tokens' own presentation cache)
        # were ever bypassed, every one of these would become its own
        # profile read, and the open count above would jump from single
        # digits to hundreds.
        from amulet_map_editor.api.studio import tokens as tokens_module

        calls = []
        real_presentation = tokens_module._presentation

        def counting_presentation():
            calls.append(1)
            return real_presentation()

        with mock.patch.object(tokens_module, "_presentation", counting_presentation):
            self._count_opens_building_a_shell()

        self.assertGreater(
            len(calls),
            50,
            "this test's premise is that building the shell resolves the "
            f"presentation far more than a handful of times; it only did "
            f"so {len(calls)} times, so the open-count bound above is not "
            "actually exercising the cache",
        )


if __name__ == "__main__":
    unittest.main()
