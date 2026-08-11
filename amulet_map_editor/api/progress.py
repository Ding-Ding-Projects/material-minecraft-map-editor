"""What a running operation is currently able to say about itself.

This is the model behind the shell's progress overlay, kept separate from the
widget that draws it and from the wx bridge that publishes it, so that the
thing an operation reports can be constructed, asserted on, and read by a
screen reader without a display anywhere in sight.

The one distinction it exists to preserve is between a fraction and no
fraction.  ``fraction is None`` means the work genuinely cannot say how far
along it is; ``fraction == 0.0`` means it can, and it is at the beginning.
Those are different facts and the interface draws them differently, so
collapsing them here -- by defaulting the unknown to zero, which is the obvious
thing to do -- would make the two indistinguishable before anything reached the
screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

#: The work is under way.
RUNNING = "running"
#: The work finished and the row is retiring itself.
DONE = "done"
#: The work failed.  A failed row stays until somebody dismisses it, because an
#: error that vanishes on a timer is an error nobody read.
FAILED = "failed"


@dataclass
class ProgressTask:
    """One operation's current state, as the overlay will draw it.

    ``key`` identifies the row across updates so a running operation refreshes
    in place rather than stacking a new row per report.
    """

    key: str
    title: str
    detail: str = ""
    #: ``None`` means "cannot say", which is not the same as ``0.0``.  See the
    #: module docstring.
    fraction: Optional[float] = None
    state: str = RUNNING
    #: What the user cannot do while this runs.  Empty when the interface stays
    #: fully usable, which is the normal case and the one worth preserving:
    #: naming a restriction that does not exist is its own kind of lie.
    unavailable: str = ""
    error: str = ""
    #: Set only when the work can genuinely be stopped.  A cancel control that
    #: does nothing is worse than none, so the overlay draws one exactly when
    #: this is not ``None``.
    on_cancel: Optional[Callable[[], None]] = None

    def __post_init__(self) -> None:
        self.key = str(self.key)
        self.title = str(self.title)
        self.detail = str(self.detail)
        if self.fraction is not None:
            self.fraction = max(0.0, min(1.0, float(self.fraction)))

    @property
    def determinate(self) -> bool:
        return self.fraction is not None

    @property
    def finished(self) -> bool:
        return self.state in (DONE, FAILED)

    @property
    def cancellable(self) -> bool:
        return self.on_cancel is not None and self.state == RUNNING

    def percent(self) -> Optional[int]:
        """Return the whole percent to show, or ``None`` when there is none."""
        if self.fraction is None:
            return None
        return int(round(self.fraction * 100))

    def accessible_value(self) -> str:
        """Return the value a screen reader should hear for this row.

        A row whose progress cannot be measured says so in words rather than
        going silent, because silence from a progress indicator is
        indistinguishable from one that has stopped moving.
        """
        if self.state == FAILED:
            return self.error or "failed"
        if self.state == DONE:
            return "finished"
        percent = self.percent()
        if percent is None:
            return "in progress, remaining time unknown"
        return f"{percent} percent"

    def accessible_name(self) -> str:
        """Return the whole row as one announceable sentence."""
        parts = [self.title, self.accessible_value()]
        if self.detail:
            parts.append(self.detail)
        if self.unavailable:
            parts.append(self.unavailable)
        return ". ".join(part for part in parts if part)


__all__ = ["ProgressTask", "RUNNING", "DONE", "FAILED"]
