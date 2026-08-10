from pathlib import Path


def test_schedule_fields_use_native_picker_companions_and_typed_text():
    simple = Path("amulet_map_editor/api/wx/ui/simple.py").read_text(encoding="utf-8")
    prefs = Path("amulet_map_editor/api/wx/ui/preferences.py").read_text(
        encoding="utf-8"
    )
    assert "class MaterialDateTimeField(wx.Panel)" in simple
    assert "wx.adv.DatePickerCtrl" in simple
    assert "wx.adv.TimePickerCtrl" in simple
    assert 'MaterialDateTimeField(page, "date")' in prefs
    assert 'MaterialDateTimeField(page, "time")' in prefs
    assert "self.schedule_start_date.GetValue().strip()" in prefs
