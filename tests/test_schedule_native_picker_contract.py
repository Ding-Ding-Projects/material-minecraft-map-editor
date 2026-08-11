from pathlib import Path


def test_schedule_fields_use_native_picker_companions_and_typed_text():
    simple = Path("amulet_map_editor/api/wx/ui/simple.py").read_text(encoding="utf-8")
    prefs = Path("amulet_map_editor/api/wx/ui/preferences.py").read_text(
        encoding="utf-8"
    )
    assert "class MaterialDateTimeField(wx.Panel)" in simple
    assert "wx.adv.DatePickerCtrl" in simple
    assert "wx.adv.TimePickerCtrl" in simple
    # Every field on this page -- this one included -- is built on its own
    # ``SettingRow.body`` rather than directly on the scrolled page, which is
    # what ``SettingRow.set_control`` requires: wx asserts at construction time
    # if a control added to a row's sizer is not actually parented to that
    # row's ``body``.  ``MaterialDateTimeField(page, ...)`` would crash the
    # dialog the moment this page opens.
    assert 'MaterialDateTimeField(start_date_row.body, "date")' in prefs
    assert 'MaterialDateTimeField(start_time_row.body, "time")' in prefs
    assert "self.schedule_start_date.GetValue().strip()" in prefs
