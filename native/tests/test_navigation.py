import unittest
from native.amulet_native.navigation import move_cell, reveal_cell


class NavigationTests(unittest.TestCase):
    def test_horizontal_keys_never_wrap_rows(self):
        self.assertEqual(move_cell(16, "left"), 16)
        self.assertEqual(move_cell(31, "right"), 31)
        self.assertEqual(move_cell(17, "left"), 16)
        self.assertEqual(move_cell(30, "right"), 31)

    def test_reveal_at_large_zoom_and_return(self):
        self.assertEqual(reveal_cell(255, 64, 300, 200, 0, 0), {"x": 760, "y": 860})
        self.assertEqual(reveal_cell(0, 64, 300, 200, 760, 860), {"x": 36, "y": 36})
        self.assertEqual(reveal_cell(255, 24, 1000, 1000, 760, 860), {"x": 0, "y": 0})
