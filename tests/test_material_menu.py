from __future__ import annotations

from pathlib import Path
import unittest

import pytest

from amulet_map_editor.api.material_menu import (
    MAX_COMMAND_VIEWPORT_HEIGHT,
    MAX_QUERY_CHARS,
    MAX_RESULTS,
    MIN_COMMAND_VIEWPORT_HEIGHT,
    MaterialMenuItem,
    MenuSelection,
    filter_menu_items,
    fit_menu_command_viewport,
    visible_menu_label,
)


def _noop(*_args):
    return None


def test_visible_label_removes_mnemonic_and_accelerator_markup() -> None:
    assert visible_menu_label("&File\tAlt+F") == "File"
    item = MaterialMenuItem("&File\tAlt+F", _noop)
    assert item.label == "File"
    assert item.shortcut == "Alt+F"
    assert visible_menu_label("Save && Close\tCtrl+W") == "Save & Close"


def test_filter_is_literal_casefolded_and_searches_metadata() -> None:
    items = (
        MaterialMenuItem("Open [World]", _noop, section="File"),
        MaterialMenuItem("Preferences", _noop, description="Theme and density"),
        MaterialMenuItem("Close", _noop, keywords=("quit", "exit")),
    )
    assert filter_menu_items(items, "[world]") == (items[0],)
    assert filter_menu_items(items, "THEME density") == (items[1],)
    assert filter_menu_items(items, "exit") == (items[2],)


def test_filter_ranking_is_stable_and_prefix_first() -> None:
    items = (
        MaterialMenuItem("World close", _noop),
        MaterialMenuItem("Open world", _noop),
        MaterialMenuItem("World", _noop),
        MaterialMenuItem("World export", _noop),
    )
    assert filter_menu_items(items, "world") == (
        items[2],
        items[0],
        items[3],
        items[1],
    )


def test_filter_bounds_query_and_result_count() -> None:
    items = tuple(MaterialMenuItem(f"Command {index}", _noop) for index in range(300))
    assert len(filter_menu_items(items)) == MAX_RESULTS
    assert filter_menu_items(items, "x" * (MAX_QUERY_CHARS + 50)) == ()
    assert filter_menu_items(items, limit=10) == items[:10]
    assert filter_menu_items(items, limit=-1) == ()


def test_selection_skips_disabled_items_and_wraps() -> None:
    selection = MenuSelection()
    enabled = (False, True, False, True)
    assert selection.reset(enabled) == 1
    assert selection.move(1, enabled) == 3
    assert selection.move(1, enabled) == 1
    assert selection.move(-1, enabled) == 3
    selection.index = -1
    assert selection.move(1, enabled) == 1
    selection.index = -1
    assert selection.move(-1, enabled) == 3
    assert selection.clamp((False, False)) == -1


class MenuViewportLayoutTestCase(unittest.TestCase):
    """Regression tests also discovered by the hosted unittest command."""

    def test_expands_observed_24_pixel_command_strip(self) -> None:
        # Packaged wx reported a 293 px popup containing 269 px of title/search
        # chrome and a 24 px command viewport, while command children extended
        # at least another 381 px.  Virtual content must drive the desired
        # height instead of the scrolled window's tiny native best size.
        layout = fit_menu_command_viewport(
            chrome_height=269,
            command_content_height=381,
            area_height=1080,
        )
        self.assertEqual(620, layout.popup_height)
        self.assertEqual(351, layout.command_viewport_height)
        self.assertGreater(layout.command_viewport_height, 24)
        self.assertLessEqual(
            layout.command_viewport_height, MAX_COMMAND_VIEWPORT_HEIGHT
        )

    def test_stays_bounded_and_reserves_command_rows(self) -> None:
        layout = fit_menu_command_viewport(
            chrome_height=269,
            command_content_height=900,
            area_height=400,
        )
        self.assertEqual(400, layout.popup_height)
        self.assertEqual(131, layout.command_viewport_height)
        self.assertGreaterEqual(
            layout.command_viewport_height, MIN_COMMAND_VIEWPORT_HEIGHT
        )
        self.assertEqual(layout.popup_height, 269 + layout.command_viewport_height)

    def test_tiny_display_never_creates_a_negative_viewport(self) -> None:
        layout = fit_menu_command_viewport(
            chrome_height=269,
            command_content_height=381,
            area_height=200,
        )
        self.assertEqual(200, layout.popup_height)
        self.assertEqual(0, layout.command_viewport_height)

    def test_does_not_reserve_space_for_empty_results(self) -> None:
        layout = fit_menu_command_viewport(
            chrome_height=140,
            command_content_height=0,
            area_height=1080,
        )
        self.assertEqual(180, layout.popup_height)
        self.assertEqual(0, layout.command_viewport_height)

    def test_wx_view_applies_virtual_content_height_and_scrollbar_width(self) -> None:
        source = (
            Path(__file__).parents[1]
            / "amulet_map_editor"
            / "api"
            / "wx"
            / "components.py"
        ).read_text(encoding="utf-8")
        self.assertIn("self._buttons_sizer.GetMinSize().height", source)
        self.assertIn("fit_menu_command_viewport(", source)
        self.assertIn("wx.Size(300, viewport_layout.command_viewport_height)", source)
        self.assertIn("wx.SystemSettings.GetMetric(wx.SYS_VSCROLL_X, self)", source)
        self.assertIn("self._scroll.Scroll(0, 0)", source)


def test_item_validation_is_fail_closed() -> None:
    with pytest.raises(ValueError):
        MaterialMenuItem("&\tCtrl+X", _noop)
    with pytest.raises(TypeError):
        MaterialMenuItem("Broken", None)  # type: ignore[arg-type]
