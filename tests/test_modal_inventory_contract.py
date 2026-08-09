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
        (
            "amulet_map_editor/api/wx/ui/tab_manager.py",
            "TabManagerDialog._new_group",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/tab_manager.py",
            "TabManagerDialog._open_regex_builder",
            "dialog",
        ),
        (
            "amulet_map_editor/api/wx/ui/tab_manager.py",
            "TabManagerDialog._open_close_regex_builder",
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
    )
)

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
            if "_open_local_history" in key[1] or "open_element_appearance" in key[1]
        ),
        *(
            (key, "picker: apply or cancel an explicit user selection")
            for key in EXPECTED_MODAL_CALLS
            if key[1]
            not in {
                "AmuletUI._open_preferences",
                "AmuletUI._open_local_history",
                "AmuletUI._open_tab_manager",
                "EditExtension._edit_controls",
                "EditExtension._edit_options",
                "open_element_appearance",
                "show_material_confirmation",
                "ChunkTool._ask_delete_chunks",
            }
        ),
        (
            next(
                key
                for key in EXPECTED_MODAL_CALLS
                if key[1] == "show_material_confirmation"
            ),
            "decision: return an explicit yes, no, or cancel result",
        ),
        (
            next(
                key
                for key in EXPECTED_MODAL_CALLS
                if key[1] == "ChunkTool._ask_delete_chunks"
            ),
            "destructive: authorize, decline, or cancel chunk deletion",
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
