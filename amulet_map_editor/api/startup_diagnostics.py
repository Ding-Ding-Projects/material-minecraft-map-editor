"""Log a single, dense startup block naming the environment the app is in.

Three real defects in this project would each have been obvious from these
lines alone: an interface Windows silently stretched (the DPI mode), a window
taller than the screen (the display geometry and the window's actual size),
and fonts a third too large (the resolved theme/density/ui_scale). Before this
module existed, none of that survived past the moment it happened; a user
could only send a screenshot and an agent had to reason backwards from a
picture.

Nothing sensitive is gathered here. Display-text overlay contents, TOTP
secrets, credentials and file contents never pass through this module or
:mod:`amulet_map_editor.api.startup_diagnostics`'s caller -- only geometry,
version strings and named settings.
"""

from __future__ import annotations

import logging
import platform
import sys
from typing import Optional, Sequence, Tuple

from amulet_map_editor.api import process

log = logging.getLogger(__name__)


def _git_commit(repo_root: Optional[str] = None) -> Optional[str]:
    """Return the short commit hash for the running checkout, if any.

    A frozen/packaged build has no ``.git`` directory to ask, so a failure
    here is normal and silent -- the version string alone still identifies
    the build.
    """
    try:
        result = process.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def _wx_version() -> Optional[str]:
    try:
        import wx

        return wx.version()
    except Exception:
        return None


def _display_lines() -> Tuple[str, ...]:
    """Describe every display: geometry, usable client area, and scale."""
    lines = []
    try:
        import wx

        count = wx.Display.GetCount()
        for index in range(count):
            try:
                display = wx.Display(index)
                geometry = display.GetGeometry()
                client = display.GetClientArea()
                try:
                    scale = display.GetScaleFactor()
                except Exception:
                    scale = None
                lines.append(
                    f"  display[{index}]: geometry=({geometry.x},{geometry.y},"
                    f"{geometry.width}x{geometry.height}) "
                    f"client=({client.x},{client.y},{client.width}x{client.height}) "
                    f"scale={scale}"
                )
            except Exception as error:
                lines.append(f"  display[{index}]: unavailable ({error})")
    except Exception as error:
        lines.append(f"  displays: unavailable ({error})")
    return tuple(lines)


def _window_lines(window: object) -> Tuple[str, ...]:
    """Describe a top-level window's requested, minimum, and actual size."""
    if window is None:
        return ("  window: none constructed yet",)
    lines = []
    for label, getter in (
        ("actual", "GetSize"),
        ("min", "GetMinSize"),
        ("client", "GetClientSize"),
    ):
        try:
            size = getattr(window, getter)()
            lines.append(f"  window[{label}]: {size.GetWidth()}x{size.GetHeight()}")
        except Exception as error:
            lines.append(f"  window[{label}]: unavailable ({error})")
    try:
        lines.append(f"  window[maximized]: {window.IsMaximized()}")
    except Exception:
        pass
    return tuple(lines)


def _preferences_lines() -> Tuple[str, ...]:
    """Describe the resolved theme, density, ui_scale, language and funny levels."""
    try:
        from amulet_map_editor.api import preferences

        current = preferences.load()
    except Exception as error:
        return (f"  preferences: unavailable ({error})",)
    return (
        f"  theme={current.theme} density={current.density} "
        f"ui_scale={current.ui_scale} accent={current.accent}",
        f"  language_mode={current.language_mode} "
        f"funny_level_english={current.funny_level_english} "
        f"funny_level_cantonese={current.funny_level_cantonese}",
    )


def _dpi_line() -> str:
    try:
        from amulet_map_editor.api import dpi

        return f"  dpi_awareness={dpi.declared_mode()}"
    except Exception as error:
        return f"  dpi_awareness: unavailable ({error})"


def build_report(window: object = None, repo_root: Optional[str] = None) -> str:
    """Return the multi-line startup diagnostic block."""
    try:
        from amulet_map_editor import __version__
    except Exception:
        __version__ = "unknown"  # type: ignore[assignment]
    commit = _git_commit(repo_root)

    lines = [
        "Startup diagnostics:",
        f"  version={__version__} commit={commit or 'unknown'}",
        f"  python={platform.python_version()} ({sys.executable})",
        f"  wx={_wx_version() or 'unavailable'}",
        f"  platform={platform.platform()}",
        _dpi_line(),
    ]
    lines.extend(_display_lines())
    lines.extend(_window_lines(window))
    lines.extend(_preferences_lines())
    return "\n".join(lines)


def log_startup(
    logger: Optional[logging.Logger] = None,
    window: object = None,
    repo_root: Optional[str] = None,
) -> str:
    """Build and emit the startup diagnostic block; return it for testing."""
    active_logger = logger or log
    report = build_report(window=window, repo_root=repo_root)
    active_logger.info(report)
    return report
