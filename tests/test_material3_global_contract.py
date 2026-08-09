from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_app_themes_lazily_created_windows():
    source = (ROOT / "amulet_map_editor/api/framework/app.py").read_text(
        encoding="utf-8"
    )
    assert "self.Bind(wx.EVT_WINDOW_CREATE, self._on_window_create)" in source
    assert "wx.CallAfter(apply_material3, window)" in source
    assert "wx.CallLater(100, apply_material3, window)" in source


def test_material3_consumes_persisted_appearance_tokens():
    source = (ROOT / "amulet_map_editor/api/wx/material3.py").read_text(
        encoding="utf-8"
    )
    assert "prefs.ui_scale" in source
    assert "prefs.ui_font" in source
    assert "prefs.density" in source
    assert "_blend_colour" in source
    assert "_on_colour" in source
    assert 'palette["primary_container"] = _blend_colour' in source


def test_material3_covers_common_collection_and_selection_controls():
    source = (ROOT / "amulet_map_editor/api/wx/material3.py").read_text(
        encoding="utf-8"
    )
    for control in (
        "wx.ListBox",
        "wx.ListCtrl",
        "wx.TreeCtrl",
        "wx.Notebook",
        "wx.CheckBox",
        "wx.Gauge",
    ):
        assert control in source


def test_dialogs_receive_borderless_material_chrome():
    source = (ROOT / "amulet_map_editor/api/wx/material3.py").read_text(
        encoding="utf-8"
    )
    assert "_ensure_material_dialog_chrome" in source
    assert "wx.NO_BORDER" in source
    assert "MaterialTitleBar(window" in source


def test_secondary_frames_receive_the_same_material_chrome():
    source = (ROOT / "amulet_map_editor/api/wx/material3.py").read_text(
        encoding="utf-8"
    )
    assert "_ensure_material_frame_chrome" in source
    assert "wx.Frame.SetSizer(window, outer)" in source
    assert 'hasattr(window, "_title_bar")' in source


def test_editable_controls_use_m3_surface_roles():
    source = (ROOT / "amulet_map_editor/api/wx/material3.py").read_text(
        encoding="utf-8"
    )
    assert 'child.SetBackgroundColour(palette["surface_container"])' in source
    assert 'child.SetForegroundColour(palette["on_surface"])' in source


def test_flat_notebook_tab_roles_are_explicitly_m3_themed():
    source = (ROOT / "amulet_map_editor/api/wx/material3.py").read_text(
        encoding="utf-8"
    )
    for setter in (
        "SetTabAreaColour",
        "SetActiveTabColour",
        "SetNonActiveTabColour",
        "SetActiveTabTextColour",
        "SetNonActiveTabTextColour",
    ):
        assert setter in source


def test_flat_notebook_palette_declares_both_surface_text_roles():
    source = (ROOT / "amulet_map_editor/api/wx/material3.py").read_text(
        encoding="utf-8"
    )
    assert '"on_surface_variant": wx.Colour' in source
    assert "_ignore_destroyed_window" in source


def test_informational_workflows_use_nonblocking_notifications():
    bridge = (ROOT / "amulet_map_editor/api/wx/nonblocking.py").read_text(
        encoding="utf-8"
    )
    assert "notifications.add" in bridge
    for relative in (
        "amulet_map_editor/api/framework/amulet_ui.py",
        "amulet_map_editor/programs/convert/convert.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "from amulet_map_editor.api.wx.nonblocking import notify" in source
        assert "wx.MessageBox" not in source


def test_startup_has_no_acknowledgement_or_purchase_gate():
    source = (ROOT / "amulet_map_editor/api/framework/app.py").read_text(
        encoding="utf-8"
    )
    assert "LicenceDialog" not in source
    assert "WarningDialog" not in source
    assert "Buy a license" not in source
    assert "ShowModal()" not in source


def test_main_menu_has_no_unsolicited_sponsor_promotion_and_styles_legal_surfaces():
    main_menu = (ROOT / "amulet_map_editor/api/framework/pages/main_menu.py").read_text(
        encoding="utf-8"
    )
    legal = (ROOT / "amulet_map_editor/api/framework/pages/_legal.py").read_text(
        encoding="utf-8"
    )
    assert "urlopen" not in main_menu
    assert "sponsors" not in main_menu
    assert "pathway_logo" not in main_menu
    assert "apply_material3(self)" in main_menu
    assert "apply_material3(self)" in legal


def test_main_menu_user_manual_uses_the_bundled_offline_documentation_browser():
    source = (ROOT / "amulet_map_editor/api/framework/pages/main_menu.py").read_text(
        encoding="utf-8"
    )
    assert (
        "from amulet_map_editor.api.wx.ui.documentation import DocumentationDialog"
        in source
    )
    assert "with DocumentationDialog(self) as dialog:" in source
    assert (
        "github.com/Amulet-Team/Amulet-Map-Editor/blob/master/amulet_map_editor/readme.md"
        not in source
    )


def test_removed_sponsor_labels_do_not_remain_in_localization_resources():
    for path in (ROOT / "amulet_map_editor/lang").glob("*.lang"):
        source = path.read_text(encoding="utf-8")
        assert "main_menu.our_sponsors" not in source
        assert "main_menu.sponsor_link" not in source


def test_nonblocking_bridge_normalises_multiline_exception_text():
    bridge = (ROOT / "amulet_map_editor/api/wx/nonblocking.py").read_text(
        encoding="utf-8"
    )
    assert 'replace("\\n", " · ")' in bridge


def test_editing_and_world_selection_info_flows_are_nonblocking():
    for relative in (
        "amulet_map_editor/programs/edit/plugins/tools/paste.py",
        "amulet_map_editor/programs/edit/plugins/tools/import_tool.py",
        "amulet_map_editor/api/wx/ui/select_world.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "nonblocking import notify" in source
        assert "wx.MessageBox" not in source


def test_remaining_informational_paths_use_the_notification_bridge():
    for relative in (
        "amulet_map_editor/programs/edit/api/canvas/edit_canvas.py",
        "amulet_map_editor/programs/edit/api/ui/tool/default_base_tool_ui.py",
        "amulet_map_editor/api/wx/ui/nbt_editor.py",
        "amulet_map_editor/api/wx/ui/preferences.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "nonblocking import notify" in source
        assert "wx.MessageBox" not in source


def test_operation_error_message_dialog_is_nonblocking():
    source = (
        ROOT / "amulet_map_editor/programs/edit/api/canvas/edit_canvas.py"
    ).read_text(encoding="utf-8")
    assert "Operation failed" in source
    assert "with wx.MessageDialog(self, msg, style=wx.OK)" not in source


def test_preferences_use_the_m3_owned_path_picker():
    source = (ROOT / "amulet_map_editor/api/wx/ui/preferences.py").read_text(
        encoding="utf-8"
    )
    picker = (ROOT / "amulet_map_editor/api/wx/ui/path_dialog.py").read_text(
        encoding="utf-8"
    )
    assert "from amulet_map_editor.api.wx.ui.path_dialog import choose_path" in source
    assert source.count("choose_path(") >= 4
    assert "class MaterialPathDialog" in picker
    assert "Browse path" in picker
