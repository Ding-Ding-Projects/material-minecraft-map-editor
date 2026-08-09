import os
import tempfile
import unittest
from datetime import datetime


class ScheduledSettingsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._config_dir = tempfile.TemporaryDirectory()
        cls._original_config_env = os.environ.get("CONFIG_DIR")
        os.environ["CONFIG_DIR"] = cls._config_dir.name
        from amulet_map_editor.api import scheduled_settings

        cls.schedules = scheduled_settings
        cls._original_config_path = scheduled_settings.config._path
        scheduled_settings.config._path = cls._config_dir.name

    @classmethod
    def tearDownClass(cls):
        cls.schedules.config._path = cls._original_config_path
        if cls._original_config_env is None:
            os.environ.pop("CONFIG_DIR", None)
        else:
            os.environ["CONFIG_DIR"] = cls._original_config_env
        cls._config_dir.cleanup()

    def setUp(self):
        self.schedules.replace_rules(())

    def rule(self, rule_id="rule", **changes):
        values = changes.pop("values", self.schedules.ScheduledValues(theme="dark"))
        return self.schedules.ScheduleRule(
            rule_id=rule_id, label=rule_id.title(), values=values, **changes
        )

    def test_versioned_document_round_trips_through_local_config(self):
        document = self.schedules.replace_rules(
            (
                self.rule(
                    weekdays=(0, 2, 4),
                    start_date="2026-08-01",
                    end_date="2026-08-31",
                    start_time="08:30",
                    end_time="17:15",
                    values=self.schedules.ScheduledValues(
                        language_mode="bilingual",
                        theme="light",
                        density="compact",
                        accent="#12345678",
                    ),
                ),
            )
        )
        loaded = self.schedules.load()
        self.assertEqual(loaded, document)
        self.assertEqual(loaded.as_dict()["version"], 1)

    def test_rule_round_trips_an_external_source_contract(self):
        rule = self.rule(
            source={
                "kind": "home_assistant",
                "url": "https://ha.example.test",
                "entity_id": "input_boolean.night",
                "refresh_seconds": 600,
            }
        )
        restored = self.schedules.ScheduleRule.from_dict(rule.as_dict())
        self.assertEqual(restored.source["kind"], "home_assistant")
        self.assertEqual(restored.source["refresh_seconds"], 600)

    def test_higher_priority_and_later_order_win_per_setting(self):
        document = self.schedules.ScheduleDocument(
            rules=(
                self.rule(
                    "base-theme",
                    priority=1,
                    values=self.schedules.ScheduledValues(
                        theme="light", density="spacious"
                    ),
                ),
                self.rule(
                    "first-tie",
                    priority=5,
                    values=self.schedules.ScheduledValues(theme="dark"),
                ),
                self.rule(
                    "last-tie",
                    priority=5,
                    values=self.schedules.ScheduledValues(
                        theme="system", accent="#ABCDEF"
                    ),
                ),
            )
        )
        resolution = document.resolve(
            datetime(2026, 8, 9, 12, 0),
            {
                "language_mode": "english",
                "theme": "dark",
                "density": "comfortable",
                "accent": "#6750A4",
            },
        )
        self.assertEqual(resolution.values["theme"], "system")
        self.assertEqual(resolution.values["density"], "spacious")
        self.assertEqual(resolution.values["accent"], "#ABCDEF")
        self.assertEqual(
            resolution.matched_rule_ids,
            ("base-theme", "first-tie", "last-tie"),
        )

    def test_overnight_window_uses_the_starting_weekday_and_date(self):
        friday_night = self.rule(
            weekdays=(4,),
            start_date="2026-08-07",
            end_date="2026-08-07",
            start_time="22:00",
            end_time="02:00",
        )
        self.assertTrue(friday_night.matches(datetime(2026, 8, 7, 23, 59)))
        self.assertTrue(friday_night.matches(datetime(2026, 8, 8, 1, 59)))
        self.assertFalse(friday_night.matches(datetime(2026, 8, 8, 2, 0)))
        self.assertFalse(friday_night.matches(datetime(2026, 8, 8, 23, 0)))

    def test_equal_start_and_end_is_an_all_day_window(self):
        all_day = self.rule(weekdays=(6,), start_time="09:00", end_time="09:00")
        self.assertTrue(all_day.matches(datetime(2026, 8, 9, 0, 0)))
        self.assertTrue(all_day.matches(datetime(2026, 8, 9, 23, 59)))
        self.assertFalse(all_day.matches(datetime(2026, 8, 10, 9, 0)))

    def test_disabled_rule_does_not_match(self):
        self.assertFalse(self.rule(enabled=False).matches(datetime(2026, 8, 9, 12, 0)))

    def test_invalid_weekdays_dates_times_and_values_are_rejected(self):
        invalid_changes = (
            {"weekdays": ()},
            {"weekdays": (7,)},
            {"weekdays": (1, 1)},
            {"start_date": "08/09/2026"},
            {"start_date": "2026-08-10", "end_date": "2026-08-09"},
            {"start_time": "24:00"},
            {"end_time": "9:00"},
        )
        for changes in invalid_changes:
            with self.subTest(changes=changes):
                with self.assertRaises(self.schedules.ScheduleValidationError):
                    self.rule(**changes)

        with self.assertRaises(self.schedules.ScheduleValidationError):
            self.schedules.ScheduledValues(accent="purple")
        with self.assertRaises(self.schedules.ScheduleValidationError):
            self.schedules.ScheduledValues()

    def test_unknown_fields_duplicate_ids_and_versions_are_rejected(self):
        with self.assertRaises(self.schedules.ScheduleValidationError):
            self.schedules.ScheduleDocument(rules=(self.rule(), self.rule()))
        with self.assertRaises(self.schedules.ScheduleValidationError):
            self.schedules.ScheduleDocument.from_dict(
                {"version": 1, "rules": [], "network_source": "https://example.com"}
            )
        with self.assertRaises(self.schedules.UnsupportedScheduleVersion):
            self.schedules.ScheduleDocument.from_dict({"version": 2, "rules": []})
        with self.assertRaises(self.schedules.UnsupportedScheduleVersion):
            self.schedules.ScheduleDocument.from_dict({"version": True, "rules": []})
        with self.assertRaises(self.schedules.ScheduleValidationError):
            self.schedules.ScheduleDocument(rules=("not-a-rule",))


if __name__ == "__main__":
    unittest.main()
