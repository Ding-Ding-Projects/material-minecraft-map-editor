from __future__ import annotations

import pytest

from amulet_map_editor.api.material_menu import (
    MAX_QUERY_CHARS,
    MAX_RESULTS,
    MaterialMenuItem,
    MenuSelection,
    filter_menu_items,
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


def test_item_validation_is_fail_closed() -> None:
    with pytest.raises(ValueError):
        MaterialMenuItem("&\tCtrl+X", _noop)
    with pytest.raises(TypeError):
        MaterialMenuItem("Broken", None)  # type: ignore[arg-type]
