from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_native_export_surfaces_offer_the_shared_editor_action():
    notification_source = (
        ROOT / "amulet_map_editor/api/wx/ui/notifications.py"
    ).read_text(encoding="utf-8")
    preferences_source = (
        ROOT / "amulet_map_editor/api/wx/ui/preferences.py"
    ).read_text(encoding="utf-8")

    assert "export_actions.open_exported_path" in notification_source
    assert 'label="Open export in VS Code"' in notification_source
    assert "export_actions.open_exported_path" in preferences_source
    assert "_open_appearance_export" in preferences_source

    changelog_start = preferences_source.index("class ChangelogDialog")
    changelog_source = preferences_source[changelog_start:]
    assert "export_actions.open_exported_path" in changelog_source
    assert 'label="Open export in VS Code"' in changelog_source
