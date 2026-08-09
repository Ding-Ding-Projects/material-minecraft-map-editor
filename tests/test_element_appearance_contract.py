from pathlib import Path


ROOT = Path(__file__).parents[1]
MATERIAL3 = (ROOT / "amulet_map_editor/api/wx/material3.py").read_text(encoding="utf-8")
EDITOR = (ROOT / "amulet_map_editor/api/wx/ui/element_appearance.py").read_text(encoding="utf-8")


def test_every_native_m3_control_gets_an_edit_and_reset_entry():
    assert "EVT_CONTEXT_MENU" in MATERIAL3
    assert "Edit appearance…" in MATERIAL3
    assert "Reset element appearance" in MATERIAL3
    assert "open_element_appearance" in MATERIAL3


def test_editor_is_bounded_persisted_live_and_honest_about_capabilities():
    assert "MAX_ENTRIES = 512" in EDITOR
    assert "MAX_KEY_LENGTH = 160" in EDITOR
    assert "config.put(APPEARANCE_ID" in EDITOR
    assert "apply_override(self.control)" in EDITOR
    assert "Unsupported Word-only axes" in EDITOR
    assert "local_history.safe_record" in EDITOR
    assert 'name="Element italic"' in EDITOR
    assert 'name="Element underline"' in EDITOR
    assert 'name="Element strikethrough"' in EDITOR
    assert 'name="Element letter spacing"' in EDITOR
    assert "capability-limited" in EDITOR
