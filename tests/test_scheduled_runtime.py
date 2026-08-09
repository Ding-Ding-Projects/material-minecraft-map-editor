from __future__ import annotations

from datetime import datetime

from amulet_map_editor.api import scheduled_runtime


def test_runtime_controller_resolves_local_values(monkeypatch):
    schedules = __import__("amulet_map_editor.api.scheduled_settings", fromlist=["x"])
    rule = schedules.ScheduleRule(
        rule_id="night",
        label="Night",
        values=schedules.ScheduledValues(theme="dark"),
        start_time="00:00",
        end_time="00:00",
    )
    monkeypatch.setattr(schedules, "load", lambda: schedules.ScheduleDocument((rule,)))
    states = []
    controller = scheduled_runtime.ScheduledRuntimeController(on_state=states.append)
    state = controller.refresh({"theme": "light", "density": "comfortable", "accent": "#6750A4", "language_mode": "english"})
    assert state.values["theme"] == "dark"
    assert state.matched_rule_ids == ("night",)
    assert states[-1] == state
    controller.stop()


def test_runtime_controller_invalid_storage_fails_safe(monkeypatch):
    schedules = __import__("amulet_map_editor.api.scheduled_settings", fromlist=["x"])
    monkeypatch.setattr(schedules, "load", lambda: (_ for _ in ()).throw(ValueError("bad schedule")))
    state = scheduled_runtime.ScheduledRuntimeController().refresh({"theme": "light"})
    assert state.error == "bad schedule"
    assert state.values == {"theme": "light"}


def test_refresh_coordinator_reports_result_to_callback():
    from amulet_map_editor.api.scheduled_refresh import ScheduledRefreshCoordinator
    from amulet_map_editor.api.scheduled_sources import ScheduleSource, SourceResult

    seen = []
    coordinator = ScheduledRefreshCoordinator(
        fetcher=lambda *_args, **_kwargs: SourceResult(False, {}, "offline")
    )
    thread = coordinator.refresh_async(
        ScheduleSource(kind="api", url="https://example.test/settings"),
        on_result=seen.append,
    )
    thread.join(timeout=2)
    assert seen and seen[0].source.detail == "offline"
    coordinator.stop()
