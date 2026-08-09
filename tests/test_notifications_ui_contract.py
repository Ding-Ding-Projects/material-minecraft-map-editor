"""Static contract checks for localized notification-history chrome."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_notification_history_uses_persisted_language_resources():
    source = (ROOT / "amulet_map_editor/api/wx/ui/notifications.py").read_text(
        encoding="utf-8"
    )
    resources = (ROOT / "amulet_map_editor/lang/en.lang").read_text(encoding="utf-8")
    for marker in (
        "preferences.load().language_mode",
        "_copy(\"title\", self._language_mode)",
        "notifications.en.title",
        "notifications.zh.title",
        "notifications.en.exported_to",
    ):
        assert marker in source + resources
