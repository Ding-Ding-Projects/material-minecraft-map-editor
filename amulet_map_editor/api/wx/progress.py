"""The one way a wx-owned workflow reports progress, without blocking anything.

This is to progress what :mod:`amulet_map_editor.api.wx.nonblocking` is to
notifications: a caller anywhere in the tree hands it a window and a sentence,
and it finds the shell and puts the report on the shell's overlay.  A caller
that is not under a shell -- a dialog constructed in a test, a page whose frame
has already gone -- still gets a working reporter that simply has nowhere to
draw, because an operation must never fail on account of the surface that was
watching it.

Use it as a context manager wherever the work is a block of code::

    with begin_progress(self, "save", "Saving world", cancellable=True) as report:
        for fraction in write_the_world():
            report.update(fraction=fraction)
            if report.cancelled:
                break

Doing it that way is what makes requirement five structural rather than
remembered: an exception leaving the block marks the row failed and leaves it on
screen, so a save that dies halfway cannot take its own progress indicator down
with it and leave the user believing it finished.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import wx

from amulet_map_editor.api.progress import DONE, FAILED, RUNNING, ProgressTask

log = logging.getLogger(__name__)


def _shell(parent: Any) -> Optional[Any]:
    """Return the window that owns the progress overlay, or ``None``.

    ``None`` is an ordinary answer here, not an error: plenty of surfaces are
    constructed outside a shell and every one of them may still run work.
    """
    if parent is None:
        return None
    top = parent
    try:
        top = parent.GetTopLevelParent() or parent
    except AttributeError:
        pass
    return top if hasattr(top, "update_progress") else None


class ProgressReporter:
    """A handle on one row of the shell's progress overlay.

    The reporter owns the :class:`~amulet_map_editor.api.progress.ProgressTask`
    and the shell only draws it, so the record a caller reads is the same one
    the user is looking at rather than a copy that can drift from it.
    """

    def __init__(self, owner: Optional[Any], task: ProgressTask) -> None:
        self._owner = owner
        self._task = task
        self._cancelled = False
        self._closed = False
        if task.on_cancel is None:
            # Only wire a cancel when the caller said the work can stop. A
            # control that appears to abort and does not is the exact defect
            # this project forbids everywhere else.
            pass
        else:
            task.on_cancel = self._cancel

    # -- state ---------------------------------------------------------------
    @property
    def task(self) -> ProgressTask:
        return self._task

    @property
    def cancelled(self) -> bool:
        """Whether the user has asked for this work to stop."""
        return self._cancelled

    @property
    def closed(self) -> bool:
        return self._closed

    def _cancel(self) -> None:
        self._cancelled = True
        self.update(detail="Stopping…")

    # -- reporting -----------------------------------------------------------
    def update(
        self,
        *,
        fraction: Optional[float] = None,
        detail: Optional[str] = None,
        title: Optional[str] = None,
        unavailable: Optional[str] = None,
        indeterminate: bool = False,
    ) -> None:
        """Refresh the row.

        ``indeterminate=True`` is how a caller says the work has stopped being
        measurable, which is deliberately harder to do by accident than passing
        no fraction: omitting ``fraction`` leaves the last one alone, because a
        caller that only wants to change the detail line must not silently
        erase the reading beside it.
        """
        if self._closed:
            return
        if indeterminate:
            self._task.fraction = None
        elif fraction is not None:
            self._task.fraction = max(0.0, min(1.0, float(fraction)))
        if detail is not None:
            self._task.detail = str(detail)
        if title is not None:
            self._task.title = str(title)
        if unavailable is not None:
            self._task.unavailable = str(unavailable)
        self._publish()

    def finish(self, detail: str = "") -> None:
        """Retire the row.  A completed operation does not need a monument."""
        if self._closed:
            return
        self._closed = True
        self._task.state = DONE
        if detail:
            self._task.detail = str(detail)
        owner = self._owner
        if owner is None:
            return
        try:
            owner.clear_progress(self._task.key)
        except (AttributeError, RuntimeError):
            log.debug("Progress overlay went away before the row could retire")

    def fail(self, message: str) -> None:
        """Mark the row failed and leave it up until somebody dismisses it."""
        if self._closed:
            return
        self._closed = True
        self._task.state = FAILED
        self._task.error = str(message)
        self._task.on_cancel = None
        self._publish()

    def _publish(self) -> None:
        owner = self._owner
        if owner is None:
            return
        try:
            if wx.IsMainThread():
                owner.update_progress(self._task)
            else:
                # A worker thread may report; wx may only be touched from the
                # main one. Copying nothing here is deliberate -- the shell
                # reads the same live record a moment later.
                wx.CallAfter(owner.update_progress, self._task)
        except (AttributeError, RuntimeError):
            log.debug("Progress overlay went away before the row could update")

    # -- context manager -----------------------------------------------------
    def __enter__(self) -> "ProgressReporter":
        return self

    def __exit__(self, exc_type, exc, _tb) -> bool:
        if exc_type is None:
            self.finish()
        else:
            self.fail(str(exc) or exc_type.__name__)
        return False


def begin_progress(
    parent: Any,
    key: str,
    title: str,
    *,
    detail: str = "",
    fraction: Optional[float] = None,
    cancellable: bool = False,
    unavailable: str = "",
) -> ProgressReporter:
    """Start reporting one operation on the shell's progress overlay.

    ``fraction`` left as ``None`` starts the row indeterminate, which is the
    honest opening state for almost everything: at the moment work begins,
    nothing has reported a number yet, and drawing an empty determinate bar
    would claim a measurement that has not been taken.
    """
    task = ProgressTask(
        key=key,
        title=title,
        detail=detail,
        fraction=fraction,
        state=RUNNING,
        unavailable=unavailable,
        # A placeholder the reporter replaces with its own handler; the point
        # is only that a cancellable row has one and an uncancellable row does
        # not, which is what the overlay draws a Cancel control from.
        on_cancel=(lambda: None) if cancellable else None,
    )
    reporter = ProgressReporter(_shell(parent), task)
    reporter._publish()
    return reporter


__all__ = ["ProgressReporter", "begin_progress"]
