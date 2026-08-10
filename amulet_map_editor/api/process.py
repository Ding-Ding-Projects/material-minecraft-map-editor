"""Launch child processes without ever flashing a console window.

Amulet is a windowed application.  On Windows every ``subprocess`` call made
from a GUI process opens its own console unless the creation flags say
otherwise, so a background ``git`` call for the project history, an updater
probe, or an editor launch would each flash a black window over the user's
work.  ``CREATE_NO_WINDOW`` plus a hidden ``STARTUPINFO`` suppresses that, and
every process this application starts routes through the helpers here.

The helpers are no-ops on other platforms, so call sites stay identical
everywhere rather than growing a platform branch each.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Dict

#: ``subprocess.CREATE_NO_WINDOW`` only exists on Windows builds of CPython.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

#: Detached children still inherit the parent console without this flag.
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)

_IS_WINDOWS = os.name == "nt"


def is_windows() -> bool:
    """Return whether console suppression is meaningful on this platform."""
    return _IS_WINDOWS


def hidden_startupinfo() -> Any:
    """Return a ``STARTUPINFO`` that hides any window the child would show.

    ``CREATE_NO_WINDOW`` covers console allocation, but a child that explicitly
    creates a window still shows it; ``SW_HIDE`` covers that second case.  The
    two are complementary rather than redundant.
    """
    if not _IS_WINDOWS:
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return startupinfo


def no_window_kwargs(**extra: Any) -> Dict[str, Any]:
    """Return the keyword arguments that keep a child process invisible.

    Pass the result straight into ``subprocess.run``/``Popen``::

        subprocess.run(["git", "status"], **no_window_kwargs())

    ``extra`` is merged in so a caller can add its own creation flags without
    losing the console suppression.
    """
    kwargs: Dict[str, Any] = dict(extra)
    if not _IS_WINDOWS:
        return kwargs
    kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | CREATE_NO_WINDOW
    kwargs.setdefault("startupinfo", hidden_startupinfo())
    return kwargs


def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
    """``subprocess.run`` that never opens a console window."""
    return subprocess.run(*args, **no_window_kwargs(**kwargs))


def popen(*args: Any, **kwargs: Any) -> subprocess.Popen:
    """``subprocess.Popen`` that never opens a console window."""
    return subprocess.Popen(*args, **no_window_kwargs(**kwargs))


def call(*args: Any, **kwargs: Any) -> int:
    """``subprocess.call`` that never opens a console window."""
    return subprocess.call(*args, **no_window_kwargs(**kwargs))


def has_console() -> bool:
    """Return whether this process actually owns a usable console.

    A windowed build has no standard streams at all, so anything that would
    ``print`` or ``input`` has to check first rather than raising on a ``None``
    stream and turning a diagnostic into a second failure.
    """
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        if stream is None:
            return False
        try:
            if not stream.isatty() and getattr(sys, "frozen", False):
                return False
        except (AttributeError, ValueError, OSError):
            return False
    return True


def write_console(message: str) -> None:
    """Write a diagnostic line when — and only when — a console exists."""
    stream = sys.stdout
    if stream is None:
        return
    try:
        stream.write(f"{message}\n")
        stream.flush()
    except (ValueError, OSError):
        # A closed or detached stream in a windowed build is expected, not an
        # error worth propagating over whatever the caller was reporting.
        pass
