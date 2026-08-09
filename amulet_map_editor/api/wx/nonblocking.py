"""Non-blocking native notification bridge for wx-owned workflows."""

from __future__ import annotations

from typing import Any

from amulet_map_editor.api import notifications


def notify(parent: Any, title: str, body: str, *, severity: str = "info") -> None:
    """Record an informational result without halting the active workflow."""

    notifications.add(severity, title, body)
    top = parent
    try:
        top = parent.GetTopLevelParent() or parent
    except AttributeError:
        pass
    try:
        top.SetStatusText(f"{title}: {body}")
    except AttributeError:
        # Non-wx callers still get durable notification history.
        pass
