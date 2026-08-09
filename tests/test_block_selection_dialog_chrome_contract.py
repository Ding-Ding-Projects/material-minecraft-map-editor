from pathlib import Path


FILES = (
    "amulet_map_editor/api/wx/ui/block_select/block_select.py",
    "amulet_map_editor/api/wx/ui/block_select/block_define.py",
    "amulet_map_editor/api/wx/ui/block_select/multi_block_define.py",
    "amulet_map_editor/api/wx/ui/block_select/properties.py",
    "amulet_map_editor/api/wx/ui/version_select.py",
)


def test_block_selection_entry_dialogs_use_borderless_material_chrome():
    for relative in FILES:
        source = Path(relative).read_text(encoding="utf-8")
        assert "wx.NO_BORDER | wx.RESIZE_BORDER" in source, relative
        assert "apply_material3" in source, relative
