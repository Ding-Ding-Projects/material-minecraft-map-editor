from pathlib import Path


SOURCE = Path("amulet_map_editor/api/wx/ui/traceback_dialog.py").read_text(
    encoding="utf-8"
)


def test_traceback_dialog_starts_borderless_for_m3_chrome():
    assert "wx.DEFAULT_DIALOG_STYLE" not in SOURCE
    assert "wx.NO_BORDER | wx.RESIZE_BORDER" in SOURCE
    assert "apply_material3(self)" in SOURCE


def test_traceback_dialog_keeps_copy_and_close_actions():
    assert "copy_button.Bind(wx.EVT_BUTTON, self._on_copy_error)" in SOURCE
    assert "wx.ID_OK" in SOURCE
