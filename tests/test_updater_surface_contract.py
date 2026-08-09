"""Keep the app on the non-blocking Squirrel updater surface."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_startup_does_not_wire_the_legacy_modal_update_dialog():
    app = (ROOT / "amulet_map_editor/api/framework/app.py").read_text(
        encoding="utf-8"
    )
    ui = (ROOT / "amulet_map_editor/api/framework/amulet_ui.py").read_text(
        encoding="utf-8"
    )
    assert "update_check" not in app
    assert "UpdateDialog" not in app
    assert "_check_for_updates_async" in ui
    assert "_stage_update_async" in ui
    assert "_restart_to_install_update" in ui
