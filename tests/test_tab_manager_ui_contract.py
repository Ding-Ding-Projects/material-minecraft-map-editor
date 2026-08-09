from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCE = (ROOT / "amulet_map_editor/api/wx/ui/tab_manager.py").read_text(
    encoding="utf-8"
)
FRAME = (ROOT / "amulet_map_editor/api/framework/amulet_ui.py").read_text(
    encoding="utf-8"
)


def test_tab_manager_is_borderless_searchable_and_regex_enabled():
    assert "wx.NO_BORDER | wx.RESIZE_BORDER" in SOURCE
    assert 'name="Tab manager search"' in SOURCE
    assert 'name="Tab manager regex builder"' in SOURCE
    assert "RegexBuilderDialog" in SOURCE
    assert "self._workspace.set_dock" in SOURCE
    assert "self._workspace.set_pinned" in SOURCE
    assert "self._workspace.move_tab" in SOURCE
    assert "local_history.safe_record" in SOURCE
    assert "Bulk close tab query" in SOURCE
    assert "Bulk close regex builder" in SOURCE
    assert "Include pinned" in SOURCE
    assert "Close tabs containing text" in SOURCE
    assert "Close tabs not containing text" in SOURCE
    assert "show_material_confirmation" in SOURCE
    assert "Unsaved-work protection still applies" in SOURCE


def test_tab_manager_is_reachable_from_view_and_palette():
    assert '"Tabs and groups…": self._open_tab_manager' in FRAME
    assert '("Tabs and groups…", self._open_tab_manager)' in FRAME
    assert "TabManagerDialog(self, self._level_notebook)" in FRAME
