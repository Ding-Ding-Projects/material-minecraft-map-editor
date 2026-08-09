from pathlib import Path


def _source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_shared_dialog_constructors_do_not_request_native_caption():
    for path in ("amulet_map_editor/api/wx/ui/simple.py",):
        source = _source(path)
        assert "wx.CAPTION" not in source
        assert "wx.NO_BORDER" in source


def test_shared_dialogs_still_use_shared_material_helper():
    for path in ("amulet_map_editor/api/wx/ui/simple.py",):
        assert "apply_material3" in _source(path)


def test_core_m3_dialogs_remove_default_caption_chrome():
    for path in (
        "amulet_map_editor/api/wx/ui/preferences.py",
        "amulet_map_editor/api/wx/ui/documentation.py",
        "amulet_map_editor/api/wx/ui/notifications.py",
    ):
        source = _source(path)
        assert "wx.NO_BORDER" in source
        assert "wx.RESIZE_BORDER" in source
