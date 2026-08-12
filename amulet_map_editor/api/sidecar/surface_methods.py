"""Sidecar methods for the universal app-wide surfaces: non-blocking
notifications with history, local Git-backed version history, and the
external-editor handoff.

Every handler here calls straight into the same portable core module a wx
surface would call -- :mod:`amulet_map_editor.api.notifications`,
:mod:`amulet_map_editor.api.local_history`, and
:mod:`amulet_map_editor.api.external_editor`. Nothing here reimplements a
list, a filter, or an export: it converts between the sidecar's JSON wire
format and the dataclasses those modules already return.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List

from amulet_map_editor.api import external_editor as EXTERNAL_EDITOR
from amulet_map_editor.api import local_history as LOCAL_HISTORY
from amulet_map_editor.api import notifications as NOTIFICATIONS
from amulet_map_editor.api.sidecar.protocol import ERR_INVALID_PARAMS, ProtocolError

MethodHandler = Any

# One process-lifetime store, matching how ``local_history.LocalHistory`` is
# meant to be used: a single append-only repository under the application's
# data directory, never re-created per call.
_HISTORY_STORE: LOCAL_HISTORY.LocalHistory | None = None


def _history() -> LOCAL_HISTORY.LocalHistory:
    global _HISTORY_STORE
    if _HISTORY_STORE is None:
        _HISTORY_STORE = LOCAL_HISTORY.LocalHistory()
    return _HISTORY_STORE


def _require(params: Dict[str, Any], field: str) -> Any:
    if field not in params or params[field] in (None, ""):
        raise ProtocolError(ERR_INVALID_PARAMS, f"'{field}' is required")
    return params[field]


# --------------------------------------------------------------- notifications


def _notifications_list(params: Dict[str, Any]) -> Dict[str, Any]:
    include_dismissed = bool(params.get("include_dismissed", True))
    items = NOTIFICATIONS.list_notifications(include_dismissed=include_dismissed)
    return {"notifications": [asdict(item) for item in items]}


def _notifications_add(params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        item = NOTIFICATIONS.add(
            _require(params, "severity"),
            _require(params, "title"),
            _require(params, "body"),
            details=params.get("details", ""),
        )
    except ValueError as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return asdict(item)


def _notifications_search(params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        items = NOTIFICATIONS.search(
            params.get("query", ""),
            regex=bool(params.get("regex", False)),
            include_dismissed=bool(params.get("include_dismissed", True)),
        )
    except ValueError as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return {"notifications": [asdict(item) for item in items]}


def _notifications_bulk_dismiss(params: Dict[str, Any]) -> Dict[str, Any]:
    ids = params.get("notification_ids")
    if not isinstance(ids, list) or not ids:
        raise ProtocolError(ERR_INVALID_PARAMS, "'notification_ids' must be a non-empty list")
    changed = NOTIFICATIONS.bulk_dismiss(str(value) for value in ids)
    return {"dismissed": changed}


def _notifications_export(params: Dict[str, Any]) -> Dict[str, Any]:
    fmt = params.get("format", "json")
    if fmt not in ("json", "markdown"):
        raise ProtocolError(ERR_INVALID_PARAMS, "'format' must be 'json' or 'markdown'")
    include_dismissed = bool(params.get("include_dismissed", True))
    ids = params.get("notification_ids")
    items = NOTIFICATIONS.list_notifications(include_dismissed=include_dismissed)
    if isinstance(ids, list) and ids:
        wanted = {str(value) for value in ids}
        items = [item for item in items if item.notification_id in wanted]
    content = (
        NOTIFICATIONS.export_json(items)
        if fmt == "json"
        else NOTIFICATIONS.export_markdown(items)
    )
    return {"format": fmt, "content": content, "count": len(items)}


# --------------------------------------------------------------- local history


def _history_event_dict(event: LOCAL_HISTORY.HistoryEvent) -> Dict[str, Any]:
    return event.to_dict()


def _history_events(params: Dict[str, Any]) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"query": params.get("query", "")}
    if params.get("actions"):
        kwargs["actions"] = list(params["actions"])
    if params.get("record_type"):
        kwargs["record_type"] = params["record_type"]
    if params.get("regex") is not None:
        kwargs["regex"] = bool(params["regex"])
    if params.get("limit") is not None:
        kwargs["limit"] = int(params["limit"])
    since = params.get("since")
    until = params.get("until")
    from datetime import datetime

    if since:
        kwargs["since"] = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
    if until:
        kwargs["until"] = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
    try:
        events = _history().events(**kwargs)
    except LOCAL_HISTORY.LocalHistoryError as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return {"events": [_history_event_dict(e) for e in events]}


def _history_restore(params: Dict[str, Any]) -> Dict[str, Any]:
    event_id = _require(params, "event_id")
    try:
        event = _history().restore(str(event_id))
    except LOCAL_HISTORY.LocalHistoryError as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return _history_event_dict(event)


def _history_export(params: Dict[str, Any]) -> Dict[str, Any]:
    fmt = params.get("format", "json")
    if fmt not in ("json", "markdown"):
        raise ProtocolError(ERR_INVALID_PARAMS, "'format' must be 'json' or 'markdown'")
    kwargs: Dict[str, Any] = {"query": params.get("query", "")}
    if params.get("actions"):
        kwargs["actions"] = list(params["actions"])
    try:
        content = (
            _history().export_json(**kwargs)
            if fmt == "json"
            else _history().export_markdown(**kwargs)
        )
    except LOCAL_HISTORY.LocalHistoryError as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return {"format": fmt, "content": content}


def _history_root(_params: Dict[str, Any]) -> Dict[str, Any]:
    return {"root": str(_history().root)}


# --------------------------------------------------------------- external editor


def _editor_discover(_params: Dict[str, Any]) -> Dict[str, Any]:
    candidates = EXTERNAL_EDITOR.discover_editors()
    return {
        "candidates": [
            {"path": str(c.path), "label": c.label, "source": c.source}
            for c in candidates
        ]
    }


def _editor_open(params: Dict[str, Any]) -> Dict[str, Any]:
    path = _require(params, "path")
    result = EXTERNAL_EDITOR.open_path(path)
    return asdict(result)


def _editor_select(params: Dict[str, Any]) -> Dict[str, Any]:
    path = _require(params, "path")
    result = EXTERNAL_EDITOR.select_editor(path)
    return asdict(result)


def _editor_selected(_params: Dict[str, Any]) -> Dict[str, Any]:
    return {"path": EXTERNAL_EDITOR.load_selected()}


SURFACE_METHODS: Dict[str, MethodHandler] = {
    "notifications.list": _notifications_list,
    "notifications.add": _notifications_add,
    "notifications.search": _notifications_search,
    "notifications.bulkDismiss": _notifications_bulk_dismiss,
    "notifications.export": _notifications_export,
    "history.events": _history_events,
    "history.restore": _history_restore,
    "history.export": _history_export,
    "history.root": _history_root,
    "editor.discover": _editor_discover,
    "editor.open": _editor_open,
    "editor.select": _editor_select,
    "editor.selected": _editor_selected,
}
