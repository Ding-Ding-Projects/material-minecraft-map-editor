"""Appearance tokens must not rebuild the world every time a control paints.

Every owner-drawn control resolves these while painting, so each one runs
hundreds of times per repaint.  Two shapes had made that expensive: a
``wx.Font`` was constructed from scratch on every call, and ``control_height``
resolved the persisted presentation twice to answer one question.

These are call-count assertions, not timing ones, because a stopwatch on a
shared runner measures the runner.  They also pin the other half of a cache,
which is that it has to notice when its answer changes: a font that survives a
scale change is a worse defect than a slow one.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock


class AppearanceTokenCostTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        os.environ["CONFIG_DIR"] = cls._dir.name
        import wx

        from amulet_map_editor.api import config, preferences, school_mode
        from amulet_map_editor.api.studio import tokens

        config.invalidate()
        preferences.save(preferences.load())
        school_mode.set_mode_name(school_mode.load().mode_name)

        cls.wx = wx
        cls.config = config
        cls.preferences = preferences
        cls.tokens = tokens
        cls.app = wx.App(False)
        cls.frame = wx.Frame(None, size=(400, 300), pos=(-32000, -32000))

    @classmethod
    def tearDownClass(cls):
        cls.frame.Destroy()
        cls.config.invalidate()
        cls._dir.cleanup()

    def setUp(self):
        self.preferences.reset()
        builder = getattr(self.tokens, "_build_font", None)
        if builder is None:
            self.fail(
                "tokens._build_font is gone, so nothing is caching the font a "
                "control builds on every paint"
            )
        builder.cache_clear()

    def _font_work(self, work, expected_requests):
        """Return how many fonts ``work`` built, asserting the cache was used.

        Counting misses alone is not enough, and the difference matters: a
        ``font`` that stopped consulting the cache and built one every time
        would register no misses at all, so a miss-only assertion passes while
        the defect it exists to catch is present.  Requiring the hits to add up
        is what closes that, because a bypassed cache cannot report them.
        """
        before = self.tokens._build_font.cache_info()
        work()
        after = self.tokens._build_font.cache_info()
        served = (after.hits - before.hits) + (after.misses - before.misses)
        self.assertEqual(
            served,
            expected_requests,
            f"{expected_requests} font requests reached the cache {served} "
            "times; something is building fonts without consulting it",
        )
        return after.misses - before.misses

    def test_repeating_one_font_request_builds_it_once(self):
        self.tokens.font(self.frame, 10)

        built = self._font_work(
            lambda: [self.tokens.font(self.frame, 10) for _ in range(200)], 200
        )

        self.assertEqual(
            built,
            0,
            "200 requests for the same font should build none after the first; "
            f"{built} were built",
        )

    def test_a_row_of_labels_builds_one_font_per_distinct_style(self):
        # What a text-bearing row actually asks for: one face at two sizes and
        # two weights.  Four distinct fonts, however many times they are asked
        # for.
        styles = [
            (10, self.wx.FONTWEIGHT_NORMAL),
            (10, self.wx.FONTWEIGHT_BOLD),
            (12, self.wx.FONTWEIGHT_NORMAL),
            (12, self.wx.FONTWEIGHT_BOLD),
        ]
        for point_size, weight in styles:
            self.tokens.font(self.frame, point_size, weight)

        def repeat():
            for _ in range(50):
                for point_size, weight in styles:
                    self.tokens.font(self.frame, point_size, weight)

        built = self._font_work(repeat, 50 * len(styles))
        self.assertEqual(built, 0, f"{built} fonts rebuilt for four known styles")

    def test_a_cached_font_is_the_callers_own_to_keep(self):
        first = self.tokens.font(self.frame, 10)
        second = self.tokens.font(self.frame, 10)
        self.assertIsNot(
            first,
            second,
            "each caller must get its own font, as it did when every call "
            "built one",
        )
        first.SetPointSize(72)
        self.assertNotEqual(
            self.tokens.font(self.frame, 10).GetPointSize(),
            72,
            "mutating a returned font must not edit the next caller's",
        )

    def test_a_scale_change_is_not_served_from_the_cache(self):
        small = self.tokens.font(self.frame, 10).GetPointSize()
        self.preferences.update(ui_scale=2.0)
        large = self.tokens.font(self.frame, 10).GetPointSize()
        self.assertGreater(
            large,
            small,
            "a font cached before an interface-scale change must not survive it",
        )
        self.preferences.update(ui_scale=1.0)
        self.assertEqual(
            self.tokens.font(self.frame, 10).GetPointSize(),
            small,
            "changing the scale back must restore the original size",
        )

    def test_a_chosen_interface_face_is_not_served_from_the_cache(self):
        installed = self.tokens._available_faces()
        if not installed:  # pragma: no cover - needs a font enumerator
            self.skipTest("no font enumerator on this build")
        chosen = sorted(installed)[0]
        default_face = self.tokens.font(self.frame, 10).GetFaceName()
        self.preferences.update(ui_font=chosen)
        self.assertEqual(
            self.tokens.font(self.frame, 10).GetFaceName(),
            chosen,
            "a newly chosen interface face must reach the next font built",
        )
        self.preferences.update(ui_font="")
        self.assertEqual(
            self.tokens.font(self.frame, 10).GetFaceName(),
            default_face,
            "clearing the chosen face must restore the shipped one",
        )

    def test_control_height_resolves_the_presentation_once(self):
        self.tokens.control_height()
        calls = []
        real = self.preferences.load

        def counting_load():
            calls.append(1)
            return real()

        with mock.patch.object(self.preferences, "load", counting_load):
            self.tokens.control_height()

        self.assertEqual(
            len(calls),
            1,
            "control_height asked for the persisted presentation "
            f"{len(calls)} times to answer one question",
        )

    def test_control_height_still_follows_density_and_scale(self):
        self.preferences.update(density="compact", ui_scale=1.0)
        compact = self.tokens.control_height()
        self.preferences.update(density="spacious")
        spacious = self.tokens.control_height()
        self.assertGreater(spacious, compact, "density must still reach the height")
        self.preferences.update(ui_scale=2.0)
        self.assertGreater(
            self.tokens.control_height(),
            spacious,
            "the interface scale must still reach the height",
        )
        self.preferences.update(density="comfortable", ui_scale=1.0)


if __name__ == "__main__":
    unittest.main()
