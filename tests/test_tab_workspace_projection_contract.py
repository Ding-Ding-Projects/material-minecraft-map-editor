from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_notebook_projects_persisted_bottom_dock():
    source = (ROOT / "amulet_map_editor/api/framework/amulet_ui.py").read_text(
        encoding="utf-8"
    )
    assert "def apply_tab_workspace" in source
    assert "flatnotebook.FNB_BOTTOM" in source
    assert "def set_tab_dock" in source
    assert "class SideTabRail" in source
    assert 'name="Side tab rail"' in source
    assert "_apply_tab_rail" in source
    assert "TabDock.RIGHT" in source


def test_tab_manager_updates_the_live_notebook_projection():
    source = (ROOT / "amulet_map_editor/api/wx/ui/tab_manager.py").read_text(
        encoding="utf-8"
    )
    assert "_tab_workspace" in source
    assert "self._notebook.apply_tab_workspace()" in source
