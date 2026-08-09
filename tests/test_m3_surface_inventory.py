from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


M3_SURFACES = (
    "amulet_map_editor/api/framework/warning_dialog.py",
    "amulet_map_editor/api/framework/update_check.py",
    "amulet_map_editor/api/framework/licence_dialog.py",
    "amulet_map_editor/api/framework/pages/main_menu.py",
    "amulet_map_editor/api/framework/pages/_legal.py",
    "amulet_map_editor/api/wx/util/key_config.py",
    "amulet_map_editor/api/wx/ui/simple.py",
    "amulet_map_editor/api/wx/ui/traceback_dialog.py",
    "amulet_map_editor/api/wx/ui/select_world.py",
    "amulet_map_editor/api/wx/ui/notifications.py",
    "amulet_map_editor/api/wx/ui/documentation.py",
    "amulet_map_editor/api/wx/ui/path_dialog.py",
    "amulet_map_editor/api/wx/ui/preferences.py",
    "amulet_map_editor/api/wx/ui/element_appearance.py",
    "amulet_map_editor/api/wx/ui/local_history.py",
    "amulet_map_editor/api/wx/ui/tab_manager.py",
    "amulet_map_editor/api/wx/ui/regex_dialog.py",
    "amulet_map_editor/api/wx/ui/nbt_editor.py",
    "amulet_map_editor/api/wx/ui/confirm.py",
    "amulet_map_editor/api/wx/ui/block_select/block_select.py",
    "amulet_map_editor/api/wx/ui/block_select/block_define.py",
    "amulet_map_editor/api/wx/ui/block_select/multi_block_define.py",
    "amulet_map_editor/api/wx/ui/block_select/properties.py",
    "amulet_map_editor/api/wx/ui/version_select.py",
)


def test_handwritten_dialog_inventory_uses_shared_material_helper():
    missing = []
    for relative in M3_SURFACES:
        source = (ROOT / relative).read_text(encoding="utf-8")
        if "apply_material3" not in source:
            missing.append(relative)
    assert not missing, f"M3 surfaces missing apply_material3: {missing}"


def test_native_message_dialogs_are_not_reintroduced():
    offenders = []
    for path in (ROOT / "amulet_map_editor").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "wx.MessageDialog" in source or "wx.MessageBox" in source:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"native blocking message surfaces remain: {offenders}"
