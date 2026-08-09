from pathlib import Path


SOURCE = Path("amulet_map_editor/api/wx/ui/select_world.py").read_text(
    encoding="utf-8"
)


def test_world_select_starts_on_borderless_material_chrome():
    assert "wx.CAPTION" not in SOURCE
    assert "wx.NO_BORDER" in SOURCE
    assert "apply_material3(self)" in SOURCE


def test_world_select_retains_resize_and_close_semantics():
    assert "wx.RESIZE_BORDER" in SOURCE
    assert "wx.CLOSE_BOX" in SOURCE
    assert "self.Bind(wx.EVT_CLOSE, self._hide_event)" in SOURCE
