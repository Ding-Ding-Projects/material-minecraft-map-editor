"""Static contract checks for the world-selection M3 surface."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_world_selection_applies_m3_without_fixed_legacy_button_typography():
    source = (ROOT / "amulet_map_editor/api/wx/ui/select_world.py").read_text(
        encoding="utf-8"
    )
    assert "from amulet_map_editor.api.wx.material3 import apply_material3" in source
    assert source.count("apply_material3(self)") >= 2
    assert "SetPointSize(16)" not in source
