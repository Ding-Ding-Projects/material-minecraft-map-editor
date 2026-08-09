from pathlib import Path


SIMPLE = Path("amulet_map_editor/api/wx/ui/simple.py").read_text(encoding="utf-8")
KEY_CONFIG = Path("amulet_map_editor/api/wx/util/key_config.py").read_text(
    encoding="utf-8"
)


def test_text_entry_prompt_is_app_owned_material_chrome():
    assert "class MaterialTextEntryDialog(wx.Dialog)" in SIMPLE
    assert "wx.NO_BORDER | wx.RESIZE_BORDER" in SIMPLE
    assert "apply_material3(self)" in SIMPLE
    assert "wx.TextEntryDialog" not in KEY_CONFIG
    assert "MaterialTextEntryDialog" in KEY_CONFIG
