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

    def test_resize_reveals_same_cell_without_changing_selection(self):
        selected = 255
        self.assertEqual(reveal_cell(selected, 28, 1000, 1000, 0, 0), {"x": 0, "y": 0})
        small = reveal_cell(selected, 28, 250, 150, 0, 0)
        self.assertEqual(small, {"x": 234, "y": 334})
        self.assertEqual(reveal_cell(selected, 28, 1000, 1000, small["x"], small["y"]), {"x": 0, "y": 0})
