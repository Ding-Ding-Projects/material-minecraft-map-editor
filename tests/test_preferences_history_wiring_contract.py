from pathlib import Path


def test_preferences_save_records_nonblocking_local_history_snapshot():
    source = Path("amulet_map_editor/api/wx/ui/preferences.py").read_text(
        encoding="utf-8"
    )
    assert "from dataclasses import asdict" in source
    assert "local_history.safe_record(" in source
    assert '"preferences"' in source
    assert 'record_type="settings"' in source
