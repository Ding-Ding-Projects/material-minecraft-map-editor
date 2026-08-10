from pathlib import Path

NOTIFICATIONS = Path("amulet_map_editor/api/wx/ui/notifications.py").read_text(
    encoding="utf-8"
)
DOCUMENTATION = Path("amulet_map_editor/api/wx/ui/documentation.py").read_text(
    encoding="utf-8"
)
API = Path("amulet_map_editor/api/notifications.py").read_text(encoding="utf-8")


def test_notification_history_uses_adjacent_builder_and_bounded_flags():
    assert "RegexBuilderDialog" in NOTIFICATIONS
    assert 'label="Regex…"' in NOTIFICATIONS
    assert "self.search.GetValue()[:4096]" in NOTIFICATIONS
    assert "flags=self._search_flags" in NOTIFICATIONS
    assert "flags: int = 0" in API


def test_documentation_browser_uses_adjacent_builder_and_flags():
    assert "RegexBuilderDialog" in DOCUMENTATION
    assert 'label="Regex…"' in DOCUMENTATION
    assert "flags=self._search_flags" in DOCUMENTATION
    assert "self.query.GetValue()[:4096]" in DOCUMENTATION
