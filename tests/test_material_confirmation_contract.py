from pathlib import Path

CONFIRM = Path("amulet_map_editor/api/wx/ui/confirm.py").read_text(encoding="utf-8")


def test_confirmation_dialog_is_borderless_and_material_styled():
    assert "wx.NO_BORDER | wx.RESIZE_BORDER" in CONFIRM
    assert "apply_material3(self)" in CONFIRM
    assert "wx.ID_YES" in CONFIRM
    assert "wx.ID_NO" in CONFIRM
    assert "wx.ID_CANCEL" in CONFIRM


def test_decision_surfaces_no_longer_construct_native_message_dialogs():
    for path in (
        "amulet_map_editor/programs/edit/edit.py",
        "amulet_map_editor/api/wx/util/key_config.py",
        "amulet_map_editor/programs/edit/api/canvas/base_edit_canvas.py",
    ):
        source = Path(path).read_text(encoding="utf-8")
        assert "wx.MessageDialog" not in source
        assert "show_material_confirmation" in source
