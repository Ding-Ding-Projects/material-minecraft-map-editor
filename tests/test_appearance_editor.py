import unittest

from amulet_map_editor.api import appearance_editor


class AppearanceEditorHelpersTestCase(unittest.TestCase):
    def test_hex_rgb_hsl_round_trip_is_bounded(self):
        rgb = appearance_editor.parse_hex("#6750A4")
        self.assertEqual(rgb, (103, 80, 164))
        self.assertEqual(appearance_editor.parse_rgb("rgb(103, 80, 164)"), rgb)
        self.assertEqual(appearance_editor.parse_rgb("103, 80, 164"), rgb)
        self.assertEqual(
            appearance_editor.parse_hsl(appearance_editor.format_hsl(rgb)), rgb
        )
        self.assertEqual(appearance_editor.rgb_to_hex(rgb), "#6750A4")

    def test_rejects_invalid_or_out_of_range_values(self):
        for value in ("#12345", "#GGGGGG", "rgb(256, 0, 0)", "1, 2"):
            with self.assertRaises(ValueError):
                (
                    appearance_editor.parse_hex(value)
                    if value.startswith("#")
                    else appearance_editor.parse_rgb(value)
                )
        with self.assertRaises(ValueError):
            appearance_editor.parse_hsl("0, 101%, 50%")

    def test_contrast_and_font_search_are_deterministic(self):
        self.assertEqual(
            appearance_editor.contrast_ratio((0, 0, 0), (255, 255, 255)), 21.0
        )
        self.assertIn("21:1", appearance_editor.contrast_summary((0, 0, 0)))
        self.assertEqual(
            appearance_editor.filter_font_names(
                ["Noto Sans", "Arial", "Noto Sans", "  Noto Serif "], "noto"
            ),
            ("Noto Sans", "Noto Serif"),
        )


if __name__ == "__main__":
    unittest.main()
