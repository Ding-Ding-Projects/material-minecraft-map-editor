"""The profile file is read once per window, not once per question asked of it.

``config.get`` sits underneath every appearance token, so it runs from inside
paint handlers: resolving one colour reads two profile files, and a single
repaint of the shell asked for hundreds of them.  Each read was a ``stat`` plus
a gzip decompress plus an unpickle, which measured 207us, and re-reading the
preferences file was the single largest cost in the interface.

These are call-count assertions rather than timing ones, because a stopwatch on
a shared runner measures the runner.  What they pin down is the shape: a burst
of reads collapses to one, and every route by which the file can change still
reaches the next reader.
"""

from __future__ import annotations

import gzip
import os
import pickle
import tempfile
import time
import unittest
from unittest import mock


class ConfigReadCacheTestCase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        os.environ["CONFIG_DIR"] = self._dir.name
        from amulet_map_editor.api import config

        self.config = config
        # The profile directory changed, so nothing may be carried in from a
        # previous test's cache.
        config.invalidate()

    def tearDown(self):
        self.config.invalidate()
        self._dir.cleanup()

    def _count_opens(self, work):
        """Run ``work`` and return how many times a profile file was opened."""
        real = gzip.open
        opens = []

        def counting_open(path, *args, **kwargs):
            opens.append(path)
            return real(path, *args, **kwargs)

        with mock.patch.object(gzip, "open", counting_open):
            work()
        return len(opens)

    def test_a_burst_of_reads_opens_the_file_once(self):
        self.config.put("burst", {"value": 1})

        opens = self._count_opens(
            lambda: [self.config.get("burst") for _ in range(200)]
        )

        self.assertEqual(
            opens,
            1,
            "200 reads of one identifier should open the profile file once; "
            f"it opened {opens} times",
        )

    def test_a_missing_identifier_is_not_re_opened_either(self):
        # Nothing was written, so every one of these is a miss.  A miss that is
        # not remembered still costs a stat per call, and most identifiers are
        # missing in a fresh profile.
        stats = []
        real_isfile = os.path.isfile

        def counting_isfile(path):
            stats.append(path)
            return real_isfile(path)

        with mock.patch.object(os.path, "isfile", counting_isfile):
            for _ in range(200):
                self.config.get("never_written", {})

        self.assertEqual(
            len(stats),
            1,
            f"200 reads of an absent identifier should stat once, not {len(stats)}",
        )

    def test_each_caller_still_gets_its_own_default(self):
        # One cached "there is nothing here" must not turn into one cached
        # default: callers ask for the same absent identifier with different
        # defaults and each must get its own back.
        self.assertEqual(self.config.get("absent", {}), {})
        self.assertEqual(self.config.get("absent", []), [])
        self.assertEqual(self.config.get("absent", "text"), "text")
        self.assertIsNone(self.config.get("absent"))

    def test_a_write_is_visible_to_the_next_read(self):
        self.config.put("written", {"value": "first"})
        self.assertEqual(self.config.get("written"), {"value": "first"})
        self.config.put("written", {"value": "second"})
        self.assertEqual(
            self.config.get("written"),
            {"value": "second"},
            "a write through put() must not be hidden by the read window",
        )

    def test_a_caller_mutating_what_it_got_does_not_edit_the_next_copy(self):
        self.config.put("shared", {"value": 1})
        first = self.config.get("shared")
        first["value"] = 999
        first["injected"] = True
        self.assertEqual(
            self.config.get("shared"),
            {"value": 1},
            "reading the file gave every caller its own object, and the cache "
            "must keep doing so",
        )

    def test_switching_profile_does_not_serve_the_previous_one(self):
        self.config.put("scoped", "first profile")
        with tempfile.TemporaryDirectory() as other:
            os.environ["CONFIG_DIR"] = other
            self.assertEqual(
                self.config.get("scoped", "absent"),
                "absent",
                "a profile switch must not serve the previous profile's value",
            )
            self.config.put("scoped", "second profile")
            self.assertEqual(self.config.get("scoped"), "second profile")
            os.environ["CONFIG_DIR"] = self._dir.name
            self.assertEqual(
                self.config.get("scoped"),
                "first profile",
                "switching back must serve the first profile again",
            )

    def test_a_write_by_another_process_is_picked_up(self):
        # School mode is deliberately one switch shared with other
        # applications, so the file -- not the cache -- stays the authority.
        # The window bounds how late another process's write is seen; it must
        # not hide it forever.
        self.config.put("shared_state", {"enabled": False})
        self.assertEqual(self.config.get("shared_state"), {"enabled": False})

        path = os.path.join(self._dir.name, "shared_state.config")
        with gzip.open(path, "wb") as handle:
            pickle.dump({"enabled": True}, handle)

        deadline = time.monotonic() + self.config.CACHE_SECONDS * 4
        while time.monotonic() < deadline:
            if self.config.get("shared_state") == {"enabled": True}:
                break
            time.sleep(self.config.CACHE_SECONDS / 4)

        self.assertEqual(
            self.config.get("shared_state"),
            {"enabled": True},
            "a write by another process must be picked up within the read "
            f"window of {self.config.CACHE_SECONDS}s",
        )

    def test_invalidate_makes_an_outside_write_visible_at_once(self):
        self.config.put("watched", "before")
        self.assertEqual(self.config.get("watched"), "before")
        path = os.path.join(self._dir.name, "watched.config")
        with gzip.open(path, "wb") as handle:
            pickle.dump("after", handle)
        self.config.invalidate("watched")
        self.assertEqual(self.config.get("watched"), "after")

    def test_a_corrupt_file_falls_back_without_being_re_read(self):
        path = os.path.join(self._dir.name, "corrupt.config")
        with open(path, "wb") as handle:
            handle.write(b"this is not a gzip stream")

        opens = self._count_opens(
            lambda: [self.config.get("corrupt", "fallback") for _ in range(50)]
        )

        self.assertEqual(
            self.config.get("corrupt", "fallback"),
            "fallback",
            "an unreadable profile file must not stop the caller",
        )
        self.assertEqual(
            opens, 1, f"a corrupt file should be opened once, not {opens} times"
        )


class AppearanceTokenReadCountTestCase(unittest.TestCase):
    """The tokens a paint handler calls must not each reopen the profile.

    This is the regression that matters: ``tokens.scaled`` multiplies an
    integer, and it was reading two gzipped files off disk to do it.
    """

    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        os.environ["CONFIG_DIR"] = cls._dir.name
        from amulet_map_editor.api import config, preferences, school_mode

        cls.config = config
        config.invalidate()
        preferences.save(preferences.load())
        school_mode.set_mode_name(school_mode.load().mode_name)

    @classmethod
    def tearDownClass(cls):
        cls.config.invalidate()
        cls._dir.cleanup()

    def test_resolving_tokens_many_times_reads_each_file_once(self):
        import wx  # noqa: F401  (imported for the same reason tokens needs it)

        from amulet_map_editor.api.studio import tokens

        self.config.invalidate()

        real = gzip.open
        opened = []

        def counting_open(path, *args, **kwargs):
            opened.append(os.path.basename(path))
            return real(path, *args, **kwargs)

        with mock.patch.object(gzip, "open", counting_open):
            for _ in range(50):
                tokens.scaled(8)
                tokens.density()
                tokens.emoji("*")

        # 150 token calls, each of which asks for preferences and School mode.
        self.assertLessEqual(
            len(opened),
            2,
            "150 appearance-token calls should read the two profile files once "
            f"each; they opened {len(opened)} files: {sorted(set(opened))}",
        )


if __name__ == "__main__":
    unittest.main()
