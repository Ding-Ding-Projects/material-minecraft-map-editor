"""Hand-written inventory preventing unreviewed blocking modal calls."""

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Every remaining ShowModal call must be a deliberate input, configuration,
# editing, or consequential-action boundary. Informational and error-only
# surfaces are intentionally absent.
EXPECTED_MODAL_CALLS = Counter(
    (
        (
            "amulet_map_editor/api/framework/amulet_ui.py",
            "AmuletUI._open_preferences",
            "dialog",
        ),
        (
            "amulet_map_editor/api/framework/amulet_ui.py",
            "AmuletUI._open_local_history",
            "dialog",
        ),
        (
            "amulet_map_editor/api/framework/amulet_ui.py",
            "AmuletUI._open_tab_manager",
            "dialog",
        ),
        (
            "amulet_map_editor/api/framework/amulet_ui.py",
            "AmuletUI._open_command_palette",
            "dialog",
        ),
        (
            "amulet_map_editor/api/framework/pages/main_menu.py",
            "AmuletMainMenu._select_language",
            "dialog",
        ),
        (
            "amulet_map_editor/api/studio/widgets.py",
            "SearchBar._open_builder_dialog",
            "dialog",
        ),
        (
            "amulet_map_editor/api/studio/widgets.py",
            "PathField._browse_folder",
            "dialog",
        ),
        (
            "amulet_map_editor/api/studio/widgets.py",
            "PathField._browse_file",
            "dialog",
        ),
        ("amulet_map_editor/api/studio/widgets.py", "ImageSlot.browse", "dialog"),
        # Exporting a surface writes a file, and where it is written and in
        # which format is the user's decision to make before anything is
        # written -- the one kind of question this contract keeps modal.
        (
            "amulet_map_editor/api/studio/spec_dialog.py",
            "SpecDialog._do_export",
            "chooser",
        ),
        (
            "amulet_map_editor/api/wx/ui/base_select.py",
            "BaseSelect._open_regex_builder",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/confirm.py",
            "show_material_confirmation",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/documentation.py",
            "DocumentationDialog._open_regex_builder",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/element_appearance.py",
            "open_element_appearance",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/local_history.py",
            "LocalHistoryDialog._open_regex_builder",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/notifications.py",
            "NotificationHistoryDialog._open_regex_builder",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/path_dialog.py",
            "MaterialPathDialog._browse",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/path_dialog.py",
            "MaterialPathDialog._browse",
            "dialog",
        ),
        ("amulet_map_editor/api/wx/ui/path_dialog.py", "choose_path", "dialog"),
        (
            "amulet_map_editor/api/wx/ui/preferences.py",
            "PreferencesDialog._open_font_regex_builder",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/preferences.py",
            "PreferencesDialog._open_preset_regex_builder",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/preferences.py",
            "PreferencesDialog._open_search_regex_builder",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/preferences.py",
            "PreferencesDialog._open_app_mark_regex_builder",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/authenticator_dialog.py",
            "AuthenticatorDialog._on_add",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/preferences.py",
            "CommandPaletteDialog._open_regex_builder",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/preferences.py",
            "ChangelogDialog._open_regex_builder",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/select_world.py",
            "open_level_from_dialog",
            "select_world",
        ),
        # The tab manager's four searches and its bulk-close query are shared
        # ``SearchBar`` fields now, so their builders open the anchored popover
        # and fall back to ``SearchBar._open_builder_dialog`` above rather than
        # to two modals of the tab manager's own.
        (
            "amulet_map_editor/api/wx/ui/tab_manager.py",
            "TabManagerDialog._new_group",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/util/key_config.py",
            "KeyConfig._request_group_name",
            "msg",
        ),
        (
            "amulet_map_editor/api/wx/util/key_config.py",
            "KeyConfig._modify_button",
            "catcher",
        ),
        (
            "amulet_map_editor/programs/convert/convert.py",
            "ConvertExtension._show_world_select",
            "select_world",
        ),
        (
            "amulet_map_editor/programs/edit/api/ui/file.py",
            "FilePanel.__init__.set_speed",
            "dialog",
        ),
        ("amulet_map_editor/programs/edit/api/ui/goto.py", "show_goto", "dialog"),
        (
            "amulet_map_editor/programs/edit/edit.py",
            "EditExtension._edit_controls",
            "key_config",
        ),
        (
            "amulet_map_editor/programs/edit/edit.py",
            "EditExtension._edit_options",
            "dialog",
        ),
        (
            "amulet_map_editor/programs/edit/plugins/tools/chunk.py",
            "ChunkTool._ask_delete_chunks",
            "d",
        ),
        (
            "amulet_map_editor/programs/edit/plugins/tools/chunk.py",
            "ChunkTool._import_chunks",
            "select_world",
        ),
        (
            "amulet_map_editor/api/studio/backstage.py",
            "BackstageView._preview",
            "dialog",
        ),
        (
            "amulet_map_editor/api/studio/backstage.py",
            "BackstageView._write_export",
            "dialog",
        ),
        (
            "amulet_map_editor/api/studio/backstage.py",
            "BackstageView._open_detected_world",
            "dialog",
        ),
        (
            "amulet_map_editor/api/studio/backstage.py",
            "BackstageView._open_structure_file",
            "dialog",
        ),
        (
            "amulet_map_editor/api/studio/memory_console.py",
            "MemoryConsoleDialog.export_article",
            "dialog",
        ),
        (
            "amulet_map_editor/api/studio/nbt_studio.py",
            "NbtStudioDialog._edit_element",
            "dialog",
        ),
        (
            "amulet_map_editor/api/studio/nbt_studio.py",
            "NbtStudioDialog.add_tag",
            "dialog",
        ),
        (
            "amulet_map_editor/api/studio/nbt_studio.py",
            "NbtStudioDialog.rename_tag",
            "dialog",
        ),
        (
            "amulet_map_editor/api/studio/nbt_studio.py",
            "NbtStudioDialog.delete_tag",
            "dialog",
        ),
        (
            "amulet_map_editor/api/studio/nbt_studio.py",
            "NbtStudioDialog.import_snbt",
            "dialog",
        ),
        (
            "amulet_map_editor/api/studio/nbt_studio.py",
            "NbtStudioDialog.export_snbt",
            "dialog",
        ),
    )
)

#: Modals that complete or cancel an explicit editing task.  The regex builder
#: appears here only as ``_open_builder_dialog``: the primary route is an
#: anchored popover beside the field it belongs to, and this modal is the
#: fallback for a display too small to hold the popover.
_EDITOR_MODALS = {
    "AmuletUI._open_local_history",
    "SearchBar._open_builder_dialog",
    "NbtStudioDialog._edit_element",
    "NbtStudioDialog.add_tag",
    "NbtStudioDialog.rename_tag",
    # Registering an authenticator entry is a credential step: it pairs a
    # secret and then requires one live code back before the factor arms, so
    # it must complete or be abandoned as a whole. Half a registration is a
    # factor that cannot be used and cannot be recovered from.
    "AuthenticatorDialog._on_add",
}

#: Modals the user must answer before anything proceeds.  A bulk-action preview
#: belongs here rather than under "picker": it exists to state exactly what is
#: about to change and to return whether that may happen.
_DECISION_MODALS = {
    "show_material_confirmation",
    "BackstageView._preview",
}

#: Modals guarding irreversible data loss.  These are the only ones allowed to
#: block unconditionally, and each is behind the two-key authorisation gate.
_DESTRUCTIVE_MODALS = {
    "ChunkTool._ask_delete_chunks",
    "NbtStudioDialog.delete_tag",
}


MODAL_REASONS = {
    key: reason
    for key, reason in (
        *(
            (key, "configuration: apply or cancel a bounded settings change")
            for key in EXPECTED_MODAL_CALLS
            if "_open_preferences" in key[1]
            or "_open_tab_manager" in key[1]
            or "_edit_controls" in key[1]
            or "_edit_options" in key[1]
        ),
        *(
            (key, "editor: complete or cancel an explicit editing task")
            for key in EXPECTED_MODAL_CALLS
            if key[1] in _EDITOR_MODALS or "open_element_appearance" in key[1]
        ),
        *(
            (key, "decision: return an explicit yes, no, or cancel result")
            for key in EXPECTED_MODAL_CALLS
            if key[1] in _DECISION_MODALS
        ),
        *(
            (key, "destructive: authorize, decline, or cancel data loss")
            for key in EXPECTED_MODAL_CALLS
            if key[1] in _DESTRUCTIVE_MODALS
        ),
        *(
            (key, "picker: apply or cancel an explicit user selection")
            for key in EXPECTED_MODAL_CALLS
            if key[1]
            not in _EDITOR_MODALS
            | _DECISION_MODALS
            | _DESTRUCTIVE_MODALS
            | {
                "AmuletUI._open_preferences",
                "AmuletUI._open_tab_manager",
                "EditExtension._edit_controls",
                "EditExtension._edit_options",
                "open_element_appearance",
                "show_material_confirmation",
                "ChunkTool._ask_delete_chunks",
            }
        ),
    )
}


class _ModalVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: list[str] = []
        self.calls: Counter[tuple[str, str, str]] = Counter()
        self.path = ""

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "ShowModal":
            self.calls[
                (
                    self.path,
                    ".".join(self.stack) or "<module>",
                    ast.unparse(node.func.value),
                )
            ] += 1
        self.generic_visit(node)


def test_show_modal_inventory_is_complete_and_decision_scoped():
    visitor = _ModalVisitor()
    for path in sorted((ROOT / "amulet_map_editor").rglob("*.py")):
        visitor.path = path.relative_to(ROOT).as_posix()
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
    assert visitor.calls == EXPECTED_MODAL_CALLS
    assert set(MODAL_REASONS) == set(EXPECTED_MODAL_CALLS)
    assert all(
        reason.startswith(
            ("configuration:", "editor:", "picker:", "decision:", "destructive:")
        )
        for reason in MODAL_REASONS.values()
    )
