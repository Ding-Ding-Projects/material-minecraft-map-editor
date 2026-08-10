"""Amulet Studio — the project-workspace user interface.

The package is import-safe without a display: the data modules (:mod:`spec`,
:mod:`search`, :mod:`surfaces`, :mod:`ribbon_defs`, :mod:`commands`) carry no wx
dependency, and the widget modules are imported lazily by the shell.
"""

from __future__ import annotations

from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.studio.spec import (
    Section,
    Spec,
    sec,
    searchable,
    tex_section,
)

__all__ = [
    "SearchState",
    "Section",
    "Spec",
    "sec",
    "searchable",
    "tex_section",
]
