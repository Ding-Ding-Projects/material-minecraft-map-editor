from pathlib import Path


SOURCE = Path("amulet_map_editor/api/framework/pages/main_menu.py").read_text(
    encoding="utf-8"
)


def test_main_menu_delegates_typography_and_sizing_to_material3_tokens():
    assert "SetFont(" not in SOURCE
    assert "size=(400, 70)" not in SOURCE
    assert "wx.EXPAND" in SOURCE
    assert "apply_material3(self)" in SOURCE
