"""Completeness checks for non-blocking exception and information surfaces."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXCEPTION_CALLERS = (
    "amulet_map_editor/api/framework/amulet_ui.py",
    "amulet_map_editor/api/framework/pages/world_page.py",
    "amulet_map_editor/api/wx/ui/select_world.py",
    "amulet_map_editor/programs/edit/edit.py",
    "amulet_map_editor/programs/edit/api/canvas/base_edit_canvas.py",
    "amulet_map_editor/programs/edit/api/canvas/edit_canvas.py",
    "amulet_map_editor/programs/edit/api/ui/tool/base_operation_choice.py",
    "amulet_map_editor/programs/edit/api/ui/tool/default_base_tool_ui.py",
    "amulet_map_editor/programs/edit/plugins/tools/import_tool.py",
)


def test_every_known_exception_surface_uses_complete_nonblocking_details():
    for relative in EXCEPTION_CALLERS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "notify_exception" in source, relative
        assert "TracebackDialog" not in source, relative
        assert "traceback.format_exc()" in source or "tb," in source, relative


def test_removed_traceback_dialog_cannot_return_as_a_hidden_modal_route():
    assert not (ROOT / "amulet_map_editor/api/wx/ui/traceback_dialog.py").exists()
    for path in (ROOT / "amulet_map_editor").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "TracebackDialog" not in source, path.relative_to(ROOT)


def test_read_only_help_and_reference_surfaces_do_not_block_the_editor():
    waterlog = (
        ROOT
        / "amulet_map_editor/programs/edit/plugins/operations/stock_plugins/operations/waterlog.py"
    ).read_text(encoding="utf-8")
    menu = (ROOT / "amulet_map_editor/api/framework/pages/main_menu.py").read_text(
        encoding="utf-8"
    )
    shell = (ROOT / "amulet_map_editor/api/framework/amulet_ui.py").read_text(
        encoding="utf-8"
    )
    assert "details=details" in waterlog
    assert "ShowModal" not in waterlog
    assert 'show_modeless_dialog(self, "documentation", DocumentationDialog)' in menu
    assert 'show_modeless_dialog(self, "third-party-licences", LicenceDialog)' in menu
    assert 'show_modeless_dialog(self, "changelog", ChangelogDialog)' in shell
    assert 'self, "notification-history", NotificationHistoryDialog' in shell


def test_exception_bridge_preserves_traceback_and_routes_to_history():
    bridge = (ROOT / "amulet_map_editor/api/wx/nonblocking.py").read_text(
        encoding="utf-8"
    )
    storage = (ROOT / "amulet_map_editor/api/notifications.py").read_text(
        encoding="utf-8"
    )
    for marker in (
        "def notify_exception(",
        'details += f"\\n\\nTraceback:\\n{traceback_text}"',
        "Full technical details are available in Notification history.",
    ):
        assert marker in bridge
    for marker in ("MAX_DETAILS_LENGTH", "details=_details", "item.details"):
        assert marker in storage
