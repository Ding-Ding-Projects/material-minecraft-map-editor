from pathlib import Path


def test_local_history_dialog_is_reachable_and_filterable():
    source = Path("amulet_map_editor/api/wx/ui/local_history.py").read_text(
        encoding="utf-8"
    )
    frame = Path("amulet_map_editor/api/framework/amulet_ui.py").read_text(
        encoding="utf-8"
    )
    assert "class LocalHistoryDialog(wx.Dialog)" in source
    assert "wx.adv.DatePickerCtrl" in source
    assert "RegexBuilderDialog" in source
    assert "self._store.restore" in source
    assert "wx.LC_MULTIPLE_SEL" in source
    assert "Select all" in source
    assert "Invert selection" in source
    assert "_list_key_down" in source
    assert "event.ControlDown()" in source
    assert "Restored {restored}" in source
    assert "Local history…" in frame
