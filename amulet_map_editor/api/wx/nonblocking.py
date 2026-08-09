"""Non-blocking native notification bridge for wx-owned workflows."""

from __future__ import annotations

from typing import Any

from amulet_map_editor.api import notifications


def _escape_unsupported_controls(value: str, *, multiline: bool) -> str:
    allowed = "\n\t" if multiline else ""
    return "".join(
        (
            character
            if ord(character) >= 32 or character in allowed
            else f"\\x{ord(character):02x}"
        )
        for character in value
    )


def notify(
    parent: Any,
    title: str,
    body: str,
    *,
    severity: str = "info",
    details: str = "",
) -> notifications.Notification:
    """Record an informational result without halting the active workflow."""

    full_body = str(body).strip() or "No additional message was provided."
    # Toast rows stay single-line and bounded. When the source is longer, keep
    # it intact in the reviewable details field rather than silently dropping
    # the remainder.
    safe_body = (
        full_body.replace("\r\n", " · ")
        .replace("\n", " · ")
        .replace("\r", " · ")
        .replace("\t", " ")
    )
    safe_body = _escape_unsupported_controls(safe_body, multiline=False)
    details = _escape_unsupported_controls(str(details), multiline=True)
    if len(safe_body) > notifications.MAX_TEXT_LENGTH:
        details = details or full_body
        suffix = "… Full details are available in Notification history."
        safe_body = safe_body[: notifications.MAX_TEXT_LENGTH - len(suffix)] + suffix
    item = notifications.add(severity, title, safe_body, details=details)
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
    try:
        top.show_notification(title, safe_body, severity=severity)
    except AttributeError:
        # Non-shell wx owners retain the durable history/status fallback.
        pass
    return item


def notify_exception(
    parent: Any, title: str, error: str, traceback_text: str
) -> notifications.Notification:
    """Publish a non-blocking error while retaining its complete traceback."""

    error = str(error).strip() or "The operation failed without an error message."
    traceback_text = str(traceback_text).strip()
    details = f"Error:\n{error}"
    if traceback_text:
        details += f"\n\nTraceback:\n{traceback_text}"
    return notify(
        parent,
        title,
        f"{error} Full technical details are available in Notification history.",
        severity="error",
        details=details,
    )


__all__ = ["notify", "notify_exception"]
