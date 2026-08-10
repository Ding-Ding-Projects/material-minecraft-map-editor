"""Non-blocking native notification bridge for wx-owned workflows."""

from __future__ import annotations

import logging
from typing import Any

from amulet_map_editor.api import notification_copy, notifications


log = logging.getLogger(__name__)


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


def _bound_details(value: str) -> str:
    """Bound technical details without turning the reporter into a new error."""

    value = _escape_unsupported_controls(str(value), multiline=True)
    if len(value) <= notifications.MAX_DETAILS_LENGTH:
        return value
    marker = "\n\n[" + notification_copy.notification_text("details.truncated") + "]"
    available = max(0, notifications.MAX_DETAILS_LENGTH - len(marker))
    return value[:available].rstrip() + marker


def notify(
    parent: Any,
    title: str,
    body: str,
    *,
    severity: str = "info",
    details: str = "",
) -> notifications.Notification | None:
    """Record an informational result without halting the active workflow."""

    full_body = str(body).strip() or notification_copy.notification_text(
        "fallback.empty"
    )
    # Toast rows stay single-line and bounded. When the source is longer, move
    # it into the reviewable details field; the details bound adds an explicit
    # marker rather than silently dropping an oversized remainder.
    safe_body = (
        full_body.replace("\r\n", " · ")
        .replace("\n", " · ")
        .replace("\r", " · ")
        .replace("\t", " ")
    )
    safe_body = _escape_unsupported_controls(safe_body, multiline=False)
    details = _escape_unsupported_controls(str(details), multiline=True)
    if len(safe_body) > notifications.MAX_TEXT_LENGTH:
        message_details = (
            f"{notification_copy.notification_text('label.message', styled=False)}:\n"
            f"{full_body}"
        )
        details = f"{details}\n\n{message_details}" if details else message_details
        suffix = "… " + notification_copy.notification_text("details.available")
        available = max(0, notifications.MAX_TEXT_LENGTH - len(suffix))
        safe_body = safe_body[:available].rstrip() + suffix
    details = _bound_details(details)
    item: notifications.Notification | None = None
    try:
        item = notifications.add(severity, title, safe_body, details=details)
    except Exception:
        # A notification must not turn its caller's wx callback into an
        # exception path when its optional durable-history store is unavailable.
        log.exception(
            "Could not persist notification history; showing an ephemeral notification"
        )
    top = parent
    try:
        top = parent.GetTopLevelParent() or parent
    except AttributeError:
        pass
    try:
        top.SetStatusText(f"{title}: {safe_body}")
    except (AttributeError, RuntimeError):
        # The parent may already be tearing down; an ephemeral fallback must
        # stay best-effort just like the normal toast path.
        pass
    try:
        top.show_notification(title, safe_body, severity=severity)
    except (AttributeError, RuntimeError):
        # Non-shell and closing wx owners retain the diagnostic fallback.
        pass
    if item is not None:
        return item
    # Do not fabricate a history record when persistence failed. The
    # display/status work above remains explicitly ephemeral.
    return None


def notify_exception(
    parent: Any, title: str, error: str, traceback_text: str
) -> notifications.Notification | None:
    """Publish a non-blocking error while retaining bounded traceback text."""

    error = str(error).strip() or notification_copy.notification_text(
        "fallback.operation"
    )
    traceback_text = str(traceback_text).strip()
    error_label = notification_copy.notification_text("label.error", styled=False)
    traceback_label = notification_copy.notification_text(
        "label.traceback", styled=False
    )
    details = f"{error_label}:\n{error}"
    if traceback_text:
        details += f"\n\n{traceback_label}:\n{traceback_text}"
    return notify(
        parent,
        title,
        f"{error} {notification_copy.notification_text('details.technical')}",
        severity="error",
        details=details,
    )


__all__ = ["notify", "notify_exception"]
