from pathlib import Path

ROOT = Path(__file__).parents[1]

NOTIFICATION_INFRASTRUCTURE_KEYS = (
    "fallback.empty",
    "fallback.operation",
    "details.available",
    "details.technical",
    "details.truncated",
    "label.error",
    "label.traceback",
    "label.message",
    "action.dismiss",
    "tone.one",
    "tone.two",
    "tone.three",
    "tone.four",
    "tone.five",
)


def test_notification_toast_is_nonblocking_and_bounded():
    source = (ROOT / "amulet_map_editor/api/wx/ui/notification_toast.py").read_text(
        encoding="utf-8"
    )
    assert "class NotificationToast" in source
    assert "wx.CallLater(6000" in source
    assert "Dismiss notification toast" in source
    assert 'notification_text("action.dismiss", styled=False)' in source
    assert "apply_material3(self)" in source


def test_shell_exposes_notification_toast_bridge():
    source = (ROOT / "amulet_map_editor/api/framework/amulet_ui.py").read_text(
        encoding="utf-8"
    )
    bridge = (ROOT / "amulet_map_editor/api/wx/nonblocking.py").read_text(
        encoding="utf-8"
    )
    assert "def show_notification" in source
    assert "top.show_notification" in bridge
    assert "_notification_toasts" in source


def test_every_language_bundle_contains_notification_infrastructure_copy():
    for filename in ("en.lang", "zh_TW.lang"):
        path = ROOT / "amulet_map_editor/lang" / filename
        source = path.read_text(encoding="utf-8")
        for language in ("en", "zh"):
            for key in NOTIFICATION_INFRASTRUCTURE_KEYS:
                assert f"notifications.{language}.{key}=" in source, (path, key)
