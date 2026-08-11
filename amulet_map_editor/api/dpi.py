"""Tell Windows this application can draw its own pixels.

A Windows process that says nothing about DPI is assumed to have been written
before high-resolution displays existed.  Windows therefore does it a favour:
it lies about the screen, reports a plain 96 DPI, lets the application lay
itself out for that, and then bitmap-stretches the finished frame up to the
display's real scale.

The favour is invisible at 100%.  At 150% or 200% -- which is the factory
setting on essentially every laptop sold with a high-resolution panel -- the
whole interface arrives enlarged and softened, as though somebody had zoomed a
screenshot.  Nothing inside the application looks wrong to the application: it
measured 96 DPI, it drew for 96 DPI, and every size it reports back is the size
it intended.  That is exactly why the fault is so hard to find from the inside,
and why it reproduces on one machine and not another.

Declaring per-monitor v2 awareness ends the stretching.  In exchange the
application takes on the work Windows was doing: it must scale its own pixel
constants (see :func:`amulet_map_editor.api.studio.tokens.scaled`) and it must
cope with the factor *changing* while it runs, because a window dragged from a
laptop panel to an external monitor crosses a DPI boundary mid-session.  That
last part is what separates per-monitor v2 from the older "system aware" mode,
which picks one factor at startup and is wrong the moment a second display is
involved.

This must run before the first window exists.  Windows resolves a process's
awareness the first time it needs it, and after that the value is fixed for the
life of the process.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from typing import Optional

log = logging.getLogger(__name__)

#: ``DPI_AWARENESS_CONTEXT`` values, as pseudo-handles rather than an enum.
#: Per-monitor v2 is the one that rescales non-client area -- the title bar and
#: window frame -- along with the client area.  Per-monitor v1 leaves the frame
#: at the startup scale, which produces a correctly drawn interface inside a
#: visibly wrong-sized window border.
_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
_PER_MONITOR_AWARE_V1 = ctypes.c_void_p(-3)

#: ``PROCESS_DPI_AWARENESS`` for the older Windows 8.1 entry point.
_PROCESS_PER_MONITOR_DPI_AWARE = 2

#: Set once the declaration has been attempted, so a second call cannot report
#: a different answer than the first.
_declared: Optional[str] = None


def declare_awareness() -> str:
    """Declare DPI awareness and return the mode that was accepted.

    Returns one of ``"per-monitor-v2"``, ``"per-monitor-v1"``, ``"system"``,
    ``"manifest"`` (already declared by the executable's manifest, which is the
    normal case for a packaged build) or ``"unavailable"``.

    Never raises.  A failure here degrades the interface on one class of
    display; it must not prevent the application from starting.
    """
    global _declared
    if _declared is not None:
        return _declared
    if sys.platform != "win32":
        # Every other platform this ships on scales through the toolkit
        # already, so there is nothing to declare and nothing to get wrong.
        _declared = "unavailable"
        return _declared

    # Windows 10 1703 and later. This is the only entry point that can be
    # called after the process starts AND supports per-monitor v2.
    try:
        user32 = ctypes.windll.user32
        if user32.SetProcessDpiAwarenessContext(_PER_MONITOR_AWARE_V2):
            _declared = "per-monitor-v2"
            log.debug("Declared per-monitor v2 DPI awareness")
            return _declared
        # A non-zero return is success; zero means it was refused. The usual
        # reason is that a manifest already declared awareness, which is not a
        # failure at all -- it is the packaged build working as intended.
        if ctypes.get_last_error() == 5:  # ERROR_ACCESS_DENIED
            _declared = "manifest"
            log.debug("DPI awareness was already declared by the manifest")
            return _declared
    except (AttributeError, OSError):
        log.debug("SetProcessDpiAwarenessContext is unavailable", exc_info=True)

    # Windows 8.1 through Windows 10 1607.
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(
            _PROCESS_PER_MONITOR_DPI_AWARE
        ) in (0, -2147024891):
            # S_OK, or E_ACCESSDENIED meaning a manifest already set it.
            _declared = "per-monitor-v1"
            log.debug("Declared per-monitor v1 DPI awareness")
            return _declared
    except (AttributeError, OSError):
        log.debug("SetProcessDpiAwareness is unavailable", exc_info=True)

    # Vista through Windows 8. System-aware is a poor third choice -- it is
    # wrong on any second monitor with a different scale -- but it is still far
    # better than being stretched.
    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            _declared = "system"
            log.debug("Declared system DPI awareness")
            return _declared
    except (AttributeError, OSError):
        log.debug("SetProcessDPIAware is unavailable", exc_info=True)

    _declared = "unavailable"
    log.warning(
        "Could not declare DPI awareness; the interface may be scaled by Windows"
    )
    return _declared


def declared_mode() -> Optional[str]:
    """Return the mode :func:`declare_awareness` settled on, or ``None``."""
    return _declared
