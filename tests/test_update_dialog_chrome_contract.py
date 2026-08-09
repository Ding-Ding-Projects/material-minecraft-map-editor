from pathlib import Path


SOURCE = Path("amulet_map_editor/api/framework/update_check.py").read_text(
    encoding="utf-8"
)


def test_legacy_update_dialog_starts_borderless_and_uses_m3():
    assert "wx.DEFAULT_DIALOG_STYLE" not in SOURCE
    assert "wx.NO_BORDER | wx.RESIZE_BORDER" in SOURCE
    assert "apply_material3(self)" in SOURCE


def test_legacy_update_dialog_keeps_update_and_dismiss_actions():
    assert "self.goto_download_page(new_version, evt)" in SOURCE
    assert "lambda evt: self.Close()" in SOURCE
