"""Non-blocking native notification bridge for wx-owned workflows."""

from __future__ import annotations

from typing import Any

from amulet_map_editor.api import notifications


def notify(parent: Any, title: str, body: str, *, severity: str = "info") -> None:
    """Record an informational result without halting the active workflow."""

    # Notification history is deliberately single-line and control-character
    # free; preserve the facts while keeping multiline exception text safe.
    safe_body = str(body).replace("\r\n", " · ").replace("\n", " · ").replace("\r", " · ")
    notifications.add(severity, title, safe_body)
    top = parent
    try:
        top = parent.GetTopLevelParent() or parent
    except AttributeError:
        pass
    try:
        top.SetStatusText(f"{title}: {safe_body}")
    except AttributeError:
        # Non-wx callers still get durable notification history.
        pass
