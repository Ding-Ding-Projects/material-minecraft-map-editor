from pathlib import Path


SOURCE = Path("amulet_map_editor/api/wx/ui/select_world.py").read_text(
    encoding="utf-8"
)


def test_world_selection_does_not_override_shared_m3_typography():
    assert "SetFont(wx.Font(" not in SOURCE
    assert "apply_material3(self)" in SOURCE
