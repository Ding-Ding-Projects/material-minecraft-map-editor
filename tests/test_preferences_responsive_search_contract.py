import ast
from pathlib import Path

from amulet_map_editor.api.settings_search import (
    PREFERENCES_SEARCH_SURFACES,
    PREFERENCES_SETTING_SPECS,
)

ROOT = Path(__file__).parents[1]
PREFERENCES_PATH = ROOT / "amulet_map_editor/api/wx/ui/preferences.py"
PREFERENCES_SOURCE = PREFERENCES_PATH.read_text(encoding="utf-8")


def _preferences_class_source() -> str:
    tree = ast.parse(PREFERENCES_SOURCE)
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name == "PreferencesDialog"
    )
    return ast.get_source_segment(PREFERENCES_SOURCE, node) or ""


def test_preferences_pages_stack_and_scroll_instead_of_clipping_horizontal_rows():
    source = _preferences_class_source()
    assert source.count("wx.ScrolledWindow(self._tabs, style=wx.VSCROLL)") == 4
    assert "wx.BoxSizer(wx.HORIZONTAL)" not in source
    assert "wx.FlexGridSizer(0, 2" not in source
    assert "self.SetMinSize(wx.Size(360, 440))" in source
    assert "self._update_responsive_layout()" in source
    assert "page.FitInside()" in source
    assert "page.SetVirtualSize(" in source
    assert "max(1, page.GetClientSize().width)" in source


def test_every_inventory_control_is_wired_into_the_preferences_class():
    source = _preferences_class_source()
    for spec in PREFERENCES_SETTING_SPECS:
        assert f"self.{spec.control_name}" in source, spec.control_name


def test_every_preferences_search_field_has_adjacent_synchronised_builder():
    source = _preferences_class_source()
    for surface in PREFERENCES_SEARCH_SURFACES:
        assert f"self.{surface.query_control}" in source
        assert f"self.{surface.regex_mode_control}" in source
        assert f"self.{surface.regex_button_control}" in source
    for row in (
        "identity_row",
        "school_row",
        "colour_row",
        "font_search_row",
        "editor_row",
        "preset_row",
        "preset_search_row",
        "preset_actions",
        "reset_row",
        "actions",
        "weekday_sizer",
        "row",
    ):
        assert f"{row} = wx.BoxSizer(wx.VERTICAL)" in source
    assert "self.font_search.ChangeValue(dialog.pattern)" in source
    assert "self.appearance_preset_search.ChangeValue(dialog.pattern)" in source
    assert "self.regex.ChangeValue(dialog.pattern)" in source
    assert "self._font_search_flags = dialog.flags" in source
    assert "self._preset_search_flags = dialog.flags" in source


def test_vertical_preferences_rows_do_not_keep_invalid_vertical_alignment_flags():
    vertical_rows = {
        "identity_row",
        "school_row",
        "colour_row",
        "font_search_row",
        "editor_row",
        "preset_row",
        "preset_search_row",
        "preset_actions",
        "reset_row",
        "actions",
        "weekday_sizer",
        "row",
    }
    tree = ast.parse(_preferences_class_source())
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        function = call.func
        if not (
            isinstance(function, ast.Attribute)
            and function.attr == "Add"
            and isinstance(function.value, ast.Name)
            and function.value.id in vertical_rows
        ):
            continue
        assert "ALIGN_CENTER_VERTICAL" not in ast.unparse(call)


def test_search_indexes_live_values_and_teleports_to_exact_control():
    source = _preferences_class_source()
    assert "settings_search.documents_from_result" in source
    assert "current_value=self._settings_search_value(spec)" in source
    assert "self._tabs.FindPage(page)" in source
    assert "GetPageIndex" not in source
    assert "self._tabs.SetSelection(page_index)" in source
    assert 'page, "ScrollChildIntoView"' in source
    assert "page.ScrollChildIntoView(control)" in source
    assert "wx.CallAfter(control.SetFocus)" in source
    assert "spec.sensitive" in source
    assert "self._settings_search_focus_control(document, fragment)" in source
    assert "isinstance(control, MaterialDateTimeField)" in source
    assert (
        "return control.text if control.text.IsEnabled() else control.picker" in source
    )
    assert "for weekday in self.schedule_weekdays" in source
    assert "return weekday" in source


def test_settings_search_refreshes_values_and_preserves_all_builder_flags():
    source = _preferences_class_source()
    assert "self._bind_settings_search_sources()" in source
    assert "self._settings_search_source_changed" in source
    assert "self._tabs.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED" in source
    assert "self._refresh_settings_search(immediate=True)" in source
    assert "flags=self._effective_settings_search_flags()" in source
    assert "self._settings_search_flags = dialog.flags" in source
    assert "self._settings_search_flags & ~re.IGNORECASE" in source
    assert "RegexEvaluationController" in source
    assert "self._settings_search_controller.submit(" in source
    assert "plain_text_match_indices(" in source
    assert "self._settings_search_controller.cancel()" in source
    assert "builder.validate()" not in source


def test_settings_results_wrap_full_labels_and_remain_keyboard_operable():
    assert "class WrappedSearchResults(wx.ScrolledWindow)" in PREFERENCES_SOURCE
    assert "wordwrap(source, wrap_width, dc, breakLongWords=True)" in PREFERENCES_SOURCE
    assert 'setattr(label, "_preferences_source_label", item)' in PREFERENCES_SOURCE
    assert "label.SetMinSize(wx.Size(1," in PREFERENCES_SOURCE
    assert (
        "self.SetVirtualSize(wx.Size(max(1, client.width), height))"
        in PREFERENCES_SOURCE
    )
    assert "wx.WXK_UP" in PREFERENCES_SOURCE
    assert "wx.WXK_DOWN" in PREFERENCES_SOURCE
    assert "self._activate(event)" in PREFERENCES_SOURCE
    assert "WrappedSearchResults(" in _preferences_class_source()
    assert "class _SearchResultsAccessible(wx.Accessible)" in PREFERENCES_SOURCE
    assert "wx.ROLE_SYSTEM_LIST" in PREFERENCES_SOURCE
    assert "wx.ROLE_SYSTEM_LISTITEM" in PREFERENCES_SOURCE
    assert "wx.ACC_STATE_SYSTEM_SELECTED" in PREFERENCES_SOURCE
    assert 'palette["primary_container"]' in PREFERENCES_SOURCE
    assert 'palette["on_primary_container"]' in PREFERENCES_SOURCE
    assert "SYS_COLOUR_HIGHLIGHT" not in PREFERENCES_SOURCE


def test_schedule_date_time_field_stacks_typed_and_picker_routes():
    source = (ROOT / "amulet_map_editor/api/wx/ui/simple.py").read_text(
        encoding="utf-8"
    )
    start = source.index("class MaterialDateTimeField")
    block = source[start:]
    assert "column = wx.BoxSizer(wx.VERTICAL)" in block
    assert "wx.BoxSizer(wx.HORIZONTAL)" not in block
