import json
import unittest
from unittest import mock

from amulet_map_editor.api import appearance_presets, preferences


class AppearancePresetsTestCase(unittest.TestCase):
    def setUp(self):
        self.storage = {}
        self.get_patch = mock.patch.object(
            appearance_presets.config,
            "get",
            side_effect=lambda key, default=None: self.storage.get(key, default),
        )
        self.put_patch = mock.patch.object(
            appearance_presets.config,
            "put",
            side_effect=lambda key, value: self.storage.__setitem__(key, value),
        )
        self.get_patch.start()
        self.put_patch.start()

    def tearDown(self):
        self.put_patch.stop()
        self.get_patch.stop()

    def test_named_presets_persist_and_apply_existing_preferences(self):
        with mock.patch.object(
            appearance_presets.preferences, "update"
        ) as update_preferences:
            values = appearance_presets.AppearanceValues(
                theme="dark",
                density="compact",
                accent="#abcdef80",
                ui_font="Noto Sans",
                ui_scale=1.25,
            )
            appearance_presets.save_preset("Night work", values)
            stored = appearance_presets.load_presets()
            self.assertEqual(stored[0].values.accent, "#ABCDEF80")

            appearance_presets.apply_preset("night WORK")

        update_preferences.assert_called_once_with(
            theme="dark",
            density="compact",
            accent="#ABCDEF80",
            ui_font="Noto Sans",
            ui_scale=1.25,
        )

    def test_export_import_round_trip_and_duplicate_protection(self):
        preset = appearance_presets.AppearancePreset(
            "Large text",
            appearance_presets.AppearanceValues(ui_font="Atkinson", ui_scale=1.6),
        )
        exported = appearance_presets.export_preset(preset)
        imported = appearance_presets.import_preset(exported)
        self.assertEqual(imported, preset)
        with self.assertRaisesRegex(
            appearance_presets.AppearancePresetValidationError, "already exists"
        ):
            appearance_presets.import_preset(exported)

        changed = json.loads(exported)
        changed["preset"]["values"]["theme"] = "dark"
        replaced = appearance_presets.import_preset(json.dumps(changed), replace=True)
        self.assertEqual(replaced.values.theme, "dark")

    def test_import_rejects_unknown_fields_versions_and_unbounded_values(self):
        valid = json.loads(
            appearance_presets.export_preset(
                appearance_presets.AppearancePreset(
                    "Safe", appearance_presets.AppearanceValues()
                )
            )
        )
        cases = []
        unknown = json.loads(json.dumps(valid))
        unknown["preset"]["values"]["surprise"] = True
        cases.append(unknown)
        future = json.loads(json.dumps(valid))
        future["version"] = 2
        cases.append(future)
        bad_scale = json.loads(json.dumps(valid))
        bad_scale["preset"]["values"]["ui_scale"] = 99
        cases.append(bad_scale)
        bad_font = json.loads(json.dumps(valid))
        bad_font["preset"]["values"]["ui_font"] = "x" * 129
        cases.append(bad_font)

        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(
                appearance_presets.AppearancePresetValidationError
            ):
                appearance_presets.import_preset(json.dumps(payload))
        self.assertEqual(appearance_presets.load_presets(), ())

    def test_corrupt_stored_entries_fail_closed_without_a_write(self):
        valid = appearance_presets.AppearancePreset(
            "Valid", appearance_presets.AppearanceValues()
        ).to_dict()
        self.storage[appearance_presets.APPEARANCE_PRESETS_ID] = {
            "version": appearance_presets.APPEARANCE_PRESETS_VERSION,
            "presets": [
                {7: "Broken", "values": {"theme": "dark"}},
                valid,
            ],
        }
        with self.assertRaisesRegex(
            appearance_presets.AppearancePresetValidationError, "keys must be text"
        ):
            appearance_presets.load_presets()
        self.assertEqual(
            self.storage[appearance_presets.APPEARANCE_PRESETS_ID]["presets"][0][7],
            "Broken",
        )

    def test_future_library_version_is_preserved_and_blocks_save(self):
        future = {"version": 2, "presets": [{"future": "shape"}]}
        self.storage[appearance_presets.APPEARANCE_PRESETS_ID] = future
        with self.assertRaises(appearance_presets.UnsupportedAppearancePresetVersion):
            appearance_presets.save_preset(
                "Do not overwrite", appearance_presets.AppearanceValues()
            )
        self.assertIs(self.storage[appearance_presets.APPEARANCE_PRESETS_ID], future)

    def test_legacy_seven_digit_preference_accent_captures_safe_default(self):
        current = preferences.Preferences(accent="#1234567", ui_font=7)
        values = appearance_presets.AppearanceValues.from_preferences(current)
        self.assertEqual(values.accent, appearance_presets.SHIPPED_APPEARANCE.accent)
        self.assertEqual(values.ui_font, "")
        self.assertEqual(current.accent, "#1234567")
        self.assertEqual(current.ui_font, 7)

    def test_domain_api_reports_wrong_value_types(self):
        with self.assertRaisesRegex(
            appearance_presets.AppearancePresetValidationError,
            "AppearanceValues instance",
        ):
            appearance_presets.AppearancePreset("Wrong", {}).validated()
        with self.assertRaises(appearance_presets.AppearancePresetValidationError):
            appearance_presets.apply_values({})
        with self.assertRaisesRegex(
            appearance_presets.AppearancePresetValidationError, "valid UTF-8"
        ):
            appearance_presets.import_preset("\ud800")

    def test_property_and_global_resets_preserve_nonappearance_settings(self):
        current = preferences.Preferences(
            language_mode="bilingual",
            funny_level_english=5,
            theme="dark",
            density="compact",
            accent="#123456",
            ui_font="Noto Sans",
            ui_scale=1.5,
        )
        updates = []

        def update_preferences(**changes):
            updates.append(changes)
            for key, value in changes.items():
                setattr(current, key, value)
            return current

        with mock.patch.object(
            appearance_presets.preferences,
            "update",
            side_effect=update_preferences,
        ):
            appearance_presets.reset_property("accent")
            appearance_presets.reset_appearance()

        self.assertEqual(updates[0], {"accent": "#6750A4"})
        self.assertEqual(set(updates[1]), set(appearance_presets.APPEARANCE_FIELDS))
        self.assertEqual(current.language_mode, "bilingual")
        self.assertEqual(current.funny_level_english, 5)
        self.assertEqual(current.theme, "system")
        with self.assertRaises(KeyError):
            appearance_presets.reset_property("language_mode")


if __name__ == "__main__":
    unittest.main()
