"""Bounded, local notification history for non-blocking app messages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import re
import secrets
from typing import Any, Iterable, List, Sequence

from amulet_map_editor.api import config

NOTIFICATIONS_ID = "notification_history"
MAX_NOTIFICATIONS = 200
MAX_TEXT_LENGTH = 600
SEVERITIES = ("info", "success", "progress", "warning", "error")


@dataclass(frozen=True)
class Notification:
    notification_id: str
    created_at: str
    severity: str
    title: str
    body: str
    dismissed: bool = False


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = value.strip()
    if not value or len(value) > MAX_TEXT_LENGTH or any(ord(c) < 32 for c in value):
        raise ValueError(f"{field} must be 1-{MAX_TEXT_LENGTH} printable characters")
    return value


def _coerce(value: Any) -> Notification | None:
    if not isinstance(value, dict):
        return None
    try:
        item = Notification(
            notification_id=_text(value.get("notification_id"), "notification_id"),
            created_at=_text(value.get("created_at"), "created_at"),
            severity=value.get("severity"),
            title=_text(value.get("title"), "title"),
            body=_text(value.get("body"), "body"),
            dismissed=bool(value.get("dismissed", False)),
        )
    except ValueError:
        return None
    if item.severity not in SEVERITIES:
        return None
    return item


def list_notifications(*, include_dismissed: bool = True) -> List[Notification]:
    raw = config.get(NOTIFICATIONS_ID, [])
    if not isinstance(raw, list):
        return []
    values = [item for item in (_coerce(value) for value in raw) if item]
    if not include_dismissed:
        values = [item for item in values if not item.dismissed]
    return values


def _save(values: Sequence[Notification]) -> List[Notification]:
    bounded = list(values)[-MAX_NOTIFICATIONS:]
    config.put(NOTIFICATIONS_ID, [asdict(value) for value in bounded])
    return bounded


def add(severity: str, title: str, body: str) -> Notification:
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}")
    item = Notification(
        notification_id=secrets.token_hex(12),
        created_at=datetime.now(timezone.utc).isoformat(),
        severity=severity,
        title=_text(title, "title"),
        body=_text(body, "body"),
    )
    _save([*list_notifications(), item])
    return item


def search(
    query: str = "", *, regex: bool = False, flags: int = 0, include_dismissed: bool = True
) -> List[Notification]:
    query = _text(query, "query") if query else ""
    try:
        matcher = re.compile(
            query if regex else re.escape(query), int(flags) | re.IGNORECASE
        )
    except re.error as exc:
        raise ValueError(f"Invalid notification search pattern: {exc}") from exc
    values = list_notifications(include_dismissed=include_dismissed)
    if not query:
        return values
    return [item for item in values if matcher.search(f"{item.title} {item.body}")]


def bulk_dismiss(notification_ids: Iterable[str]) -> int:
    wanted = {str(value) for value in notification_ids}
    values = list_notifications()
    changed = 0
    updated: List[Notification] = []
    for item in values:
        if item.notification_id in wanted and not item.dismissed:
            item = Notification(**{**asdict(item), "dismissed": True})
            changed += 1
        updated.append(item)
    _save(updated)
    return changed


def export_json(values: Sequence[Notification] | None = None) -> str:
    return (
        json.dumps(
            [
                asdict(item)
                for item in (list_notifications() if values is None else values)
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def export_markdown(values: Sequence[Notification] | None = None) -> str:
    selected = list_notifications() if values is None else list(values)
    lines = [
        "# Notification history",
        "",
        "| Time (UTC) | Severity | Title | Body | State |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in selected:
        state = "dismissed" if item.dismissed else "active"
        title = item.title.replace("|", "\\|")
        body = item.body.replace("|", "\\|")
        lines.append(
            f"| {item.created_at} | {item.severity} | {title} | {body} | {state} |"
        )
    return "\n".join(lines) + "\n"
