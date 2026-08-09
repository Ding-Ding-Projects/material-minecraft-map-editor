from pathlib import Path


SOURCE = Path("amulet_map_editor/api/wx/material3.py").read_text(encoding="utf-8")


def test_common_search_and_disclosure_controls_have_explicit_m3_roles():
    for control in (
        "wx.CollapsiblePane",
        "wx.SearchCtrl",
        "wx.RadioBox",
        "wx.StaticLine",
    ):
        assert control in SOURCE


def test_common_controls_use_shared_surface_and_touch_tokens():
    assert 'palette["surface"]' in SOURCE
    assert "_control_min_height(child)" in SOURCE
    assert 'palette["outline"]' in SOURCE
