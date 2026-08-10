"""Amulet Studio — the project-workspace user interface.

The package is import-safe without a display.  Every data module -- the surface
index, the command registry, the surface descriptions, and the shared search
state -- is plain Python and is re-exported eagerly, so a test, a build step, or
a documentation generator can read the whole feature inventory without wx.

The two names that genuinely need wxPython, :class:`~shell.StudioShell` and
:func:`~surfaces.open_surface`, are resolved on first use through the module
``__getattr__`` below.  Importing this package therefore never pulls in a
window class, while ``studio.StudioShell`` still reads as an ordinary attribute
at the one moment there is a display to build it on.
"""

from __future__ import annotations

from typing import Any, Tuple

from amulet_map_editor.api.studio.commands import COMMANDS, Command
from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.studio.spec import (
    Section,
    Spec,
    sec,
    searchable,
    tex_section,
)
from amulet_map_editor.api.studio.specs import SPECS
from amulet_map_editor.api.studio.surfaces import (
    SURFACES,
    SURFACE_GROUPS,
    Surface,
)

__all__ = [
    "COMMANDS",
    "Command",
    "SPECS",
    "SURFACES",
    "SURFACE_GROUPS",
    "SearchState",
    "Section",
    "Spec",
    "StudioShell",
    "Surface",
    "open_surface",
    "sec",
    "searchable",
    "tex_section",
]

#: Attribute name to the module it is imported from, for the names whose module
#: imports wxPython at module scope.
_LAZY: dict = {
    "StudioShell": ("amulet_map_editor.api.studio.shell", "StudioShell"),
    "open_surface": ("amulet_map_editor.api.studio.surfaces", "open_surface"),
}


def __getattr__(name: str) -> Any:
    """Resolve the display-dependent names on first use.

    Raising :class:`AttributeError` for anything else is what keeps ``from
    amulet_map_editor.api.studio import typo`` an immediate, obvious failure
    rather than a ``None`` that surfaces much later.
    """
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    import importlib

    value = getattr(importlib.import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__() -> Tuple[str, ...]:
    """List the lazy names too, so tab completion shows the whole package."""
    return tuple(sorted(set(globals()) | set(_LAZY)))
