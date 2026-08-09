from pathlib import Path

from amulet_map_editor.api import export_actions, external_editor


def test_open_exported_path_delegates_and_preserves_target(tmp_path):
    target = tmp_path / "history.md"
    target.write_text("# history", encoding="utf-8")
    calls = []

    def opener(path):
        calls.append(path)
        return external_editor.EditorResult(True, "opened", "Opened history.md")

    action = export_actions.open_exported_path(target, opener=opener)

    assert action.ok
    assert action.target == target
    assert calls == [target]


def test_open_exported_path_converts_unavailable_editor_to_safe_result(tmp_path):
    target = tmp_path / "preset.json"
    target.write_text("{}", encoding="utf-8")

    action = export_actions.open_exported_path(
        target,
        opener=lambda _path: external_editor.EditorResult(
            False, "unavailable", "No external editor is configured."
        ),
    )

    assert not action.ok
    assert action.result.status == "unavailable"
    assert "configured" in action.message


def test_open_exported_path_contains_launcher_exceptions(tmp_path):
    target = Path(tmp_path) / "export.json"
    target.write_text("{}", encoding="utf-8")

    action = export_actions.open_exported_path(
        target, opener=lambda _path: (_ for _ in ()).throw(OSError("no Code"))
    )

    assert not action.ok
    assert action.result.status == "launch_failed"
    assert "no Code" in action.message
