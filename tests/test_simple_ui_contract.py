"""Static contract checks for the shared wx UI foundation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_shared_simple_controls_apply_material3_after_creation():
    source = (ROOT / "amulet_map_editor/api/wx/ui/simple.py").read_text(
        encoding="utf-8"
    )
    assert source.count("apply_material3(self)") >= 5
    assert "class SimpleDialog" in source
    # ``CreateButtonSizer`` built native ``wx.Button`` instances hidden inside
    # the wx library itself -- invisible to any grep of the caller's source,
    # and blank on a desktop with no compositor exactly like every other
    # native control this project has replaced. ``_painted_ok_cancel`` is the
    # shared owner-drawn OK/Cancel row every dialog in this module uses now.
    assert "def _painted_ok_cancel(" in source
    assert "_painted_ok_cancel(self)" in source
