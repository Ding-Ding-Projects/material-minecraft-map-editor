"""Non-blocking generation-safe refresh for scheduled external sources."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Callable

from amulet_map_editor.api.scheduled_sources import (
    ScheduleSource,
    SourceResult,
    fetch_source,
)


@dataclass(frozen=True)
class RefreshResult:
    source: SourceResult
    applied: bool
    stale: bool = False


class ScheduledRefreshCoordinator:
    """Run at most one meaningful generation and ignore late responses."""

    def __init__(self, fetcher: Callable[..., SourceResult] = fetch_source):
        self._fetcher = fetcher
        self._lock = threading.Lock()
        self._generation = 0
        self._stopped = False
        self._threads: set[threading.Thread] = set()

    def refresh(
        self,
        source: ScheduleSource,
        *,
        token: str | None = None,
        apply: Callable[[dict[str, str]], None] | None = None,
    ) -> RefreshResult:
        with self._lock:
            if self._stopped:
                return RefreshResult(
                    SourceResult(False, {}, "refresh is stopped"), False
                )
            self._generation += 1
            generation = self._generation
        result = self._fetcher(source, token=token)
        with self._lock:
            stale = self._stopped or generation != self._generation
        if stale:
            return RefreshResult(result, False, True)
        if not result.ok or not result.values or apply is None:
            return RefreshResult(result, False)
        try:
            apply(dict(result.values))
        except Exception as exc:
            return RefreshResult(SourceResult(False, {}, str(exc)[:240]), False)
        return RefreshResult(result, True)

    def refresh_async(
        self,
        source: ScheduleSource,
        *,
        token_provider: Callable[[], str | None] | None = None,
        apply: Callable[[dict[str, str]], None] | None = None,
        on_result: Callable[[RefreshResult], None] | None = None,
    ) -> threading.Thread:
        def run() -> None:
            try:
                result = self.refresh(
                    source,
                    token=token_provider() if token_provider else None,
                    apply=apply,
                )
                if on_result:
                    on_result(result)
            finally:
                with self._lock:
                    self._threads.discard(thread)

        thread = threading.Thread(
            target=run, name="amulet-scheduled-refresh", daemon=True
        )
        with self._lock:
            if self._stopped:
                return thread
            self._threads.add(thread)
        thread.start()
        return thread

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            self._generation += 1
            self._threads.clear()


__all__ = ["RefreshResult", "ScheduledRefreshCoordinator"]
