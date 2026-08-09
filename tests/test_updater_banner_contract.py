from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "amulet_map_editor"
    / "api"
    / "framework"
    / "amulet_ui.py"
).read_text(encoding="utf-8")


def test_update_banner_has_persistent_actions_and_bounded_refresh():
    assert "UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000" in SOURCE
    assert 'self._update_banner.SetName("Update notification")' in SOURCE
    assert "self._update_banner_later.Bind" in SOURCE
    assert "Restart to install update" in SOURCE
    assert "Stage available update" in SOURCE
    assert "self._update_banner.Show()" in SOURCE


def test_update_states_are_rendered_without_modal_dialogs():
    for status in ("available", "ready_to_restart", "failed"):
        assert f'state.status == "{status}"' in SOURCE
    update_function = SOURCE[SOURCE.index("def _show_update_state") : SOURCE.index("\n\n\nclass AmuletLevelNotebook")]
    assert "ShowModal" not in update_function
