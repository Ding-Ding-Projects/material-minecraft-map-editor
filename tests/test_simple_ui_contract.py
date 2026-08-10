"""Static contract checks for the shared wx UI foundation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_shared_simple_controls_apply_material3_after_creation():
    source = (ROOT / "amulet_map_editor/api/wx/ui/simple.py").read_text(
        encoding="utf-8"
    )
    assert source.count("apply_material3(self)") >= 5
    assert "class SimpleDialog" in source
    assert "CreateButtonSizer(wx.OK | wx.CANCEL)" in source
