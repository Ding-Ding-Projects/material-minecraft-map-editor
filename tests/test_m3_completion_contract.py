from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATERIAL3 = ROOT / "amulet_map_editor/api/wx/material3.py"
COMPONENTS = ROOT / "amulet_map_editor/api/wx/components.py"
AMULET_UI = ROOT / "amulet_map_editor/api/framework/amulet_ui.py"
GLOBAL_CONTRACT = ROOT / "tests/test_material3_global_contract.py"


def test_theme_pass_has_one_preference_resolution_and_no_recursive_apply() -> None:
    source = MATERIAL3.read_text(encoding="utf-8")
    assert source.count("preferences.load()") == 1
    assert source.count("scheduled_runtime.current_values()") == 1
    assert source.count("load_overrides()") == 1
    assert "stack: list[wx.Window] = [window]" in source
    assert "apply_material3(child)" not in source
    assert "window.Layout()" in source
    assert "MaterialThemeContext" in source
    assert "MappingProxyType(palette)" in source
    assert "MappingProxyType(frozen)" in source


def test_owner_drawn_controls_harden_capture_and_keyboard_activation() -> None:
    source = COMPONENTS.read_text(encoding="utf-8")
    assert "wx.EVT_MOUSE_CAPTURE_LOST" in source
    assert "wx.EVT_KEY_UP" in source
    assert "_keyboard_armed" in source
    assert "class MaterialMenu(wx.PopupTransientWindow)" in source
    assert "class MaterialSearchField" in source
    assert "PU_CONTAINS_CONTROLS" in source
    assert "filter_menu_items" in source
    assert "wx.Menu(" not in source


def test_integration_replaces_native_command_menu_when_worktree_is_materialized() -> (
    None
):
    if not AMULET_UI.exists():
        return
    source = AMULET_UI.read_text(encoding="utf-8")
    start = source.index("    def create_menu(self):")
    end = source.index("    def _open_preferences", start)
    menu_source = source[start:end]
    assert "BEGIN CODEX MATERIAL 3 COMMAND MENU" in menu_source
    assert "MaterialMenuItem(" in menu_source
    assert "MaterialMenu(" in menu_source
    assert "wx.Menu(" not in menu_source
    assert "_scheduled_refresh_thread" in source


def test_custom_best_size_does_not_reenter_itself_and_deferred_api_survives() -> None:
    material_source = MATERIAL3.read_text(encoding="utf-8")
    component_source = COMPONENTS.read_text(encoding="utf-8")
    assert "natural_height: int = 0" in material_source
    assert "def apply_material3_deferred" in material_source
    assert "weakref.ref(window)" in material_source
    assert "_control_min_height(self)" not in component_source
    assert "_control_min_height(natural_height=height + 20)" in component_source


def test_system_theme_dynamic_focus_and_contract_compatibility() -> None:
    material_source = MATERIAL3.read_text(encoding="utf-8")
    component_source = COMPONENTS.read_text(encoding="utf-8")
    assert 'theme = "system"' in material_source
    assert "def _system_uses_dark_theme" in material_source
    assert "wx.SystemSettings.GetAppearance()" in material_source
    assert 'requested == "system"' in material_source
    assert "theme = _resolve_theme(" in material_source
    assert "wx.EVT_SYS_COLOUR_CHANGED" in material_source
    assert "def _bind_system_colour_refresh" in material_source
    assert "parent.Layout()" in component_source
    assert "self._name_tracks_label = name is None" in component_source
    assert "if self._name_tracks_label:" in component_source
    assert "_restore_focus_if_live" in component_source
    assert "_is_deleted_wrapped_object_error(error)" in component_source
    assert "anchor = self._anchor" in component_source

    if GLOBAL_CONTRACT.exists():
        contract_source = GLOBAL_CONTRACT.read_text(encoding="utf-8")
        assert "wx.CallAfter(apply_material3, window)" not in contract_source
        assert 'assert "apply_material3_deferred" in source' in contract_source
        assert 'assert "apply_material3_deferred(window)" in source' in contract_source
