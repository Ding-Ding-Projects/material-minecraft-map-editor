"""Live, non-persistent application of scheduled appearance values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import threading
from typing import Callable, Mapping

from amulet_map_editor.api import scheduled_settings
from amulet_map_editor.api.scheduled_refresh import ScheduledRefreshCoordinator
from amulet_map_editor.api.scheduled_sources import ScheduleSource


@dataclass(frozen=True)
class RuntimeScheduleState:
    values: dict[str, str]
    matched_rule_ids: tuple[str, ...] = ()
    error: str | None = None


_lock = threading.RLock()
_state = RuntimeScheduleState({})


def current_values() -> dict[str, str]:
    with _lock:
        return dict(_state.values)


def current_state() -> RuntimeScheduleState:
    with _lock:
        return _state


def _set_state(state: RuntimeScheduleState) -> None:
    global _state
    with _lock:
        _state = state


class ScheduledRuntimeController:
    """Resolve local rules and refresh active external rules without persistence."""

    def __init__(self, *, on_state: Callable[[RuntimeScheduleState], None] | None = None):
        self._on_state = on_state
        self._coordinator = ScheduledRefreshCoordinator()
        self._lock = threading.RLock()
        self._stopped = False

    def refresh(self, base_values: Mapping[str, str]) -> RuntimeScheduleState:
        try:
            document = scheduled_settings.load()
        except Exception as exc:
            state = RuntimeScheduleState(dict(base_values), error=str(exc)[:240])
            _set_state(state)
            if self._on_state:
                self._on_state(state)
            return state
        moment = datetime.now().astimezone().replace(tzinfo=None)
        resolution = document.resolve(moment, base_values)
        state = RuntimeScheduleState(dict(resolution.values), resolution.matched_rule_ids)
        _set_state(state)
        if self._on_state:
            self._on_state(state)
        for rule in document.rules:
            if rule.rule_id not in resolution.matched_rule_ids:
                continue
            raw_source = dict(rule.source or {})
            raw_source.pop("version", None)
            source = ScheduleSource(**raw_source)
            if source.kind != "local":
                self._coordinator.refresh_async(source, apply=self._apply_remote)
        return state

    def _apply_remote(self, values: dict[str, str]) -> None:
        with self._lock:
            if self._stopped:
                return
            state = RuntimeScheduleState(
                {**current_values(), **values}, current_state().matched_rule_ids
            )
        _set_state(state)
        if self._on_state:
            self._on_state(state)

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
        self._coordinator.stop()


__all__ = ["RuntimeScheduleState", "ScheduledRuntimeController", "current_values", "current_state"]
