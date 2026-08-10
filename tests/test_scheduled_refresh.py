import threading

from amulet_map_editor.api.scheduled_refresh import ScheduledRefreshCoordinator
from amulet_map_editor.api.scheduled_sources import ScheduleSource, SourceResult


def test_refresh_applies_only_valid_values():
    applied = []
    source = ScheduleSource(kind="api", url="https://example.test/feed")
    coordinator = ScheduledRefreshCoordinator(
        lambda *_args, **_kwargs: SourceResult(True, {"theme": "dark"})
    )
    result = coordinator.refresh(source, apply=applied.append)
    assert result.applied is True
    assert applied == [{"theme": "dark"}]


def test_refresh_is_non_blocking_on_fetch_or_apply_failure():
    source = ScheduleSource(kind="api", url="https://example.test/feed")
    coordinator = ScheduledRefreshCoordinator(
        lambda *_args, **_kwargs: SourceResult(False, {}, "offline")
    )
    result = coordinator.refresh(
        source,
        apply=lambda _values: (_ for _ in ()).throw(RuntimeError("apply failed")),
    )
    assert result.applied is False
    assert result.source.detail == "offline"


def test_stop_invalidates_late_async_result():
    source = ScheduleSource(kind="api", url="https://example.test/feed")
    gate = threading.Event()

    def fetcher(*_args, **_kwargs):
        gate.wait(1)
        return SourceResult(True, {"theme": "dark"})

    applied = []
    coordinator = ScheduledRefreshCoordinator(fetcher)
    thread = coordinator.refresh_async(source, apply=applied.append)
    coordinator.stop()
    gate.set()
    thread.join(2)
    assert applied == []
