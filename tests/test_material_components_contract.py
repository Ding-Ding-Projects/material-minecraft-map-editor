from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_owner_drawn_material_components_have_keyboard_and_focus_paths():
    source = (ROOT / "amulet_map_editor/api/wx/components.py").read_text(
        encoding="utf-8"
    )
    for marker in (
        "class MaterialCard",
        "class MaterialButton",
        "class MaterialWindowButton",
        "wx.EVT_KEY_DOWN",
        "wx.WXK_RETURN",
        "wx.WXK_SPACE",
        "self.HasFocus()",
        "DrawRoundedRectangle",
    ):
        assert marker in source
    assert "super().__init__(parent, label=" not in source
    assert "wx.Control.SetLabel(self, label)" in source
    assert "wx.BORDER_NONE | wx.WANTS_CHARS" in source
    assert "self.SetMinSize(self.DoGetBestSize())" in source
    assert "dc.DrawLine" in source


def test_title_bar_resolves_the_real_top_level_owner():
    source = (ROOT / "amulet_map_editor/api/wx/title_bar.py").read_text(
        encoding="utf-8"
    )
    assert "parent.GetTopLevelParent()" in source
    assert "MaterialWindowButton" in source
    assert "wx.Button(" not in source


def test_main_menu_uses_one_card_and_owner_drawn_actions():
    source = (ROOT / "amulet_map_editor/api/framework/pages/main_menu.py").read_text(
        encoding="utf-8"
    )
    assert "MaterialCard" in source
    assert source.count("MaterialButton(") >= 6
    assert source.count("amulet_logo.bitmap(64, 64)") == 1
    assert "InspectionTool" not in source
    assert "wx.BitmapButton" not in source


def test_single_start_tab_does_not_reserve_a_duplicate_side_rail():
    source = (ROOT / "amulet_map_editor/api/framework/amulet_ui.py").read_text(
        encoding="utf-8"
    )
    assert "self._level_notebook.GetPageCount() > 1" in source
    assert "rail_width = 160 if self.GetClientSize().width < 900 else 200" in source


def test_application_commands_use_material_controls_not_native_menu_chrome():
    source = (ROOT / "amulet_map_editor/api/framework/amulet_ui.py").read_text(
        encoding="utf-8"
    )
    assert 'name="Application command bar"' in source
    assert "MaterialButton(" in source
    assert "wx.MenuBar(" not in source
    assert "SetMenuBar(" not in source
