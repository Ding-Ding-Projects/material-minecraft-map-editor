from pathlib import Path

LEGAL = Path("amulet_map_editor/api/framework/pages/_legal.py").read_text(
    encoding="utf-8"
)
MENU = Path("amulet_map_editor/api/framework/pages/main_menu.py").read_text(
    encoding="utf-8"
)


def test_legal_dialog_starts_borderless_and_keeps_resize():
    assert "wx.DEFAULT_DIALOG_STYLE" not in LEGAL
    assert "wx.NO_BORDER | wx.RESIZE_BORDER" in LEGAL
    assert "apply_material3(self)" in LEGAL


def test_language_dialog_starts_borderless_and_keeps_resize():
    assert "wx.DEFAULT_DIALOG_STYLE" not in MENU
    assert "wx.NO_BORDER | wx.RESIZE_BORDER" in MENU
    assert "apply_material3(self)" in MENU
