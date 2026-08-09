from pathlib import Path


FILE_UI = Path("amulet_map_editor/programs/edit/api/ui/file.py").read_text(
    encoding="utf-8"
)
CHUNK_TOOL = Path(
    "amulet_map_editor/programs/edit/plugins/tools/chunk.py"
).read_text(encoding="utf-8")


def test_speed_dialog_uses_borderless_material_chrome():
    assert "wx.NO_BORDER | wx.RESIZE_BORDER" in FILE_UI
    assert "apply_material3(self)" in FILE_UI


def test_delete_chunks_decision_uses_borderless_material_chrome():
    assert "wx.NO_BORDER | wx.RESIZE_BORDER" in CHUNK_TOOL
    assert "apply_material3(self)" in CHUNK_TOOL
