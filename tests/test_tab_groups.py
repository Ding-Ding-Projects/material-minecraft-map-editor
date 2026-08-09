import re

import pytest

from amulet_map_editor.api.tab_groups import (
    Tab,
    TabDock,
    TabState,
    TabWorkspace,
    apply_wx_tab_accessibility,
    tab_aria,
    tab_keyboard_target,
    tab_strip_aria,
)


def test_versioned_state_round_trips_and_normalises_invalid_dock():
    state = TabState.from_dict(
        {
            "version": 999,
            "dock": "diagonal",
            "tabs": [
                {"tab_id": "one", "title": "One", "group_id": "g", "pinned": True},
                {"tab_id": "one", "title": "duplicate"},
            ],
            "groups": [{"group_id": "g", "name": "Maps", "collapsed": True}],
            "active_tab_id": "one",
        }
    )
    assert state.version == 1
    assert state.dock is TabDock.LEFT
    assert len(state.tabs) == 1
    assert state.tabs[0].pinned is True
    assert state.groups[0].collapsed is True
    assert TabState.from_dict(state.to_dict()) == state


def test_workspace_persists_dock_pins_groups_and_moves(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    workspace = TabWorkspace("worlds/main")
    group = workspace.add_group("World views")
    first = workspace.add_tab("Overview", tab_id="overview")
    second = workspace.add_tab("Chunks", tab_id="chunks", pinned=True)
    workspace.move_tab(first.tab_id, group.group_id)
    workspace.set_group_collapsed(group.group_id, True)
    workspace.set_dock(TabDock.RIGHT)

    restored = TabWorkspace("worlds/main")
    assert restored.state.dock is TabDock.RIGHT
    assert restored.state.tabs[0].pinned is True
    assert restored.state.tabs[1].group_id == group.group_id
    assert restored.state.groups[0].collapsed is True
    assert restored.state.active_tab_id == first.tab_id
    assert second.tab_id in {tab.tab_id for tab in restored.state.tabs}


def test_reorder_keeps_pinned_region_protected_and_groups_ordered(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    workspace = TabWorkspace("ordering")
    first_group = workspace.add_group("First", group_id="first")
    workspace.add_group("Second", group_id="second")
    workspace.add_tab("Pinned A", tab_id="a", pinned=True)
    workspace.add_tab("Pinned B", tab_id="b", pinned=True)
    workspace.add_tab("Normal A", tab_id="c")
    workspace.add_tab("Normal B", tab_id="d")

    workspace.reorder_tab("a", 1)
    assert [tab.tab_id for tab in workspace.state.tabs] == ["b", "a", "c", "d"]
    workspace.reorder_tab("d", 0)
    assert [tab.tab_id for tab in workspace.state.tabs] == ["b", "a", "d", "c"]
    workspace.reorder_group(first_group.group_id, 1)
    assert [group.group_id for group in workspace.state.groups] == ["second", "first"]


def test_four_searches_are_independent_and_plain_text_first(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    workspace = TabWorkspace("search")
    group = workspace.add_group("Build [release]")
    workspace.add_tab("Build [release] notes", tab_id="notes", group_id=group.group_id)
    workspace.add_tab("World map", tab_id="map")
    workspace.add_group("Other")

    assert [item.tab_id for item in workspace.search_strip("[")] == ["notes"]
    assert [
        item.tab_id for item in workspace.search_group(group.group_id, "notes")
    ] == ["notes"]
    assert [item.group_id for item in workspace.search_group_names("release")] == [
        group.group_id
    ]
    assert [item.tab_id for item in workspace.search_master("world")] == ["map"]
    assert workspace.search_master(r"^Build", regex=True)[0].tab_id == "notes"
    with pytest.raises(ValueError):
        workspace.search_master("(", regex=True)
    with pytest.raises(ValueError):
        workspace.search_group("missing", "x")


def test_search_result_location_and_aria_keyboard_contract():
    tab = Tab("one", "Overview", pinned=True)
    assert tab_strip_aria(TabDock.LEFT) == {
        "role": "tablist",
        "aria-orientation": "vertical",
    }
    assert tab_strip_aria(TabDock.TOP)["aria-orientation"] == "horizontal"
    attrs = tab_aria(tab, active=True, position=1, panel_id="panel-one")
    assert attrs["role"] == "tab"
    assert attrs["aria-selected"] == "true"
    assert attrs["aria-posinset"] == "2"
    assert attrs["aria-controls"] == "panel-one"
    assert tab_keyboard_target("ArrowDown", dock=TabDock.LEFT, current=2, count=3) == 0
    assert tab_keyboard_target("ArrowLeft", dock=TabDock.TOP, current=2, count=3) == 1
    assert tab_keyboard_target("End", dock=TabDock.BOTTOM, current=0, count=3) == 2
    assert (
        tab_keyboard_target("PageDown", dock=TabDock.BOTTOM, current=0, count=3) is None
    )

    class Control:
        def SetName(self, value):
            self.name = value

        def SetHelpText(self, value):
            self.help = value

    control = Control()
    projected = apply_wx_tab_accessibility(
        control, tab=tab, active=False, position=0, panel_id="panel-one"
    )
    assert control.name == "Overview"
    assert control.help == "Pinned tab"
    assert projected["tabindex"] == "-1"
