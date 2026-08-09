from __future__ import annotations

import unittest

from scripts.release_timing import parse_utc, release_duration


class ReleaseTimingTests(unittest.TestCase):
    def test_duration_uses_actual_supplied_completion(self):
        self.assertEqual(
            "01:02:03",
            release_duration("2026-08-09T10:00:00Z", "2026-08-09T11:02:03Z"),
        )

    def test_duration_keeps_hours_beyond_one_day(self):
        self.assertEqual(
            "26:00:01",
            release_duration("2026-08-08T09:00:00Z", "2026-08-09T11:00:01Z"),
        )

    def test_completion_must_not_precede_start(self):
        with self.assertRaisesRegex(ValueError, "cannot precede"):
            release_duration("2026-08-09T11:00:00Z", "2026-08-09T10:59:59Z")

    def test_timezone_is_required(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            parse_utc("2026-08-09T11:00:00")


if __name__ == "__main__":
    unittest.main()
