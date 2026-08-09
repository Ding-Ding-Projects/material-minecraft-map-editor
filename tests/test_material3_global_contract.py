from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_app_themes_lazily_created_windows():
    source = (ROOT / "amulet_map_editor/api/framework/app.py").read_text(
        encoding="utf-8"
    )
    assert "self.Bind(wx.EVT_WINDOW_CREATE, self._on_window_create)" in source
    assert "wx.CallAfter(apply_material3, window)" in source


def test_material3_consumes_persisted_appearance_tokens():
    source = (ROOT / "amulet_map_editor/api/wx/material3.py").read_text(
        encoding="utf-8"
    )
    assert "prefs.ui_scale" in source
    assert "prefs.ui_font" in source
    assert "prefs.density" in source


def test_material3_covers_common_collection_and_selection_controls():
    source = (ROOT / "amulet_map_editor/api/wx/material3.py").read_text(
        encoding="utf-8"
    )
    for control in ("wx.ListBox", "wx.ListCtrl", "wx.TreeCtrl", "wx.Notebook", "wx.CheckBox", "wx.Gauge"):
        assert control in source


def test_dialogs_receive_borderless_material_chrome():
    source = (ROOT / "amulet_map_editor/api/wx/material3.py").read_text(
        encoding="utf-8"
    )
    assert "_ensure_material_dialog_chrome" in source
    assert "wx.NO_BORDER" in source
    assert "MaterialTitleBar(window" in source


def test_editable_controls_use_m3_surface_roles():
    source = (ROOT / "amulet_map_editor/api/wx/material3.py").read_text(
        encoding="utf-8"
    )
    assert 'child.SetBackgroundColour(palette["surface_container"])' in source
    assert 'child.SetForegroundColour(palette["on_surface"])' in source
