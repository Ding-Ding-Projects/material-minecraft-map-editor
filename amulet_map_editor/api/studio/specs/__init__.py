"""The one registry every declarative Amulet Studio surface is looked up in.

Each submodule owns one family of surfaces and exposes its own ``SPECS`` map;
this package merges them so a caller asks for a key rather than knowing which
family it came from.  The merge is deliberately defensive: a single malformed
family would otherwise take every surface in the application down with it at
import time.  A family that fails to import is logged with its traceback and
skipped, never swallowed silently, and so is a key that two families both claim
-- a duplicate means one surface is quietly shadowing another, which is a
defect in the data rather than something to resolve by luck of import order.
"""

from __future__ import annotations

import importlib
import logging
from typing import Dict, Tuple

from amulet_map_editor.api.studio.spec import Spec

log = logging.getLogger(__name__)

#: The spec families, in the order their keys are merged.  The order only
#: decides which module keeps a duplicated key; every conflict is reported.
SPEC_MODULES: Tuple[str, ...] = (
    "core",
    "terrain_build",
    "entities_data",
    "analysis_worldgen",
    "tools_panels",
)


def _load() -> Tuple[Dict[str, Spec], Tuple[str, ...]]:
    """Import every family and merge it, returning the map and what failed."""
    merged: Dict[str, Spec] = {}
    origin: Dict[str, str] = {}
    failed = []
    for name in SPEC_MODULES:
        try:
            module = importlib.import_module(f"{__name__}.{name}")
        except Exception:
            log.exception("Studio spec family %r could not be imported", name)
            failed.append(name)
            continue
        family = getattr(module, "SPECS", None)
        if not isinstance(family, dict):
            log.error("Studio spec family %r exposes no SPECS dictionary", name)
            failed.append(name)
            continue
        for key, spec in family.items():
            if key in merged:
                log.error(
                    "Studio spec key %r is defined by both %r and %r; keeping %r",
                    key,
                    origin[key],
                    name,
                    origin[key],
                )
                continue
            merged[key] = spec
            origin[key] = name
    return merged, tuple(failed)


SPECS, UNAVAILABLE_MODULES = _load()


def get(key: str) -> Spec | None:
    """Return the surface description for ``key``, or ``None`` when unknown."""
    return SPECS.get(str(key))


def keys() -> Tuple[str, ...]:
    """Return every registered surface key, sorted for stable listings."""
    return tuple(sorted(SPECS))


__all__ = ["SPECS", "SPEC_MODULES", "UNAVAILABLE_MODULES", "get", "keys"]
