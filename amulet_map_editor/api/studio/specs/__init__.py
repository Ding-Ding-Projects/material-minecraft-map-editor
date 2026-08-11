"""The one registry every declarative Amulet Studio surface is looked up in.

Each submodule owns one family of surfaces and exposes its own ``SPECS`` map;
this package merges them so a caller asks for a key rather than knowing which
family it came from.  The merge is deliberately defensive: a single malformed
family would otherwise take every surface in the application down with it at
import time.  A family that fails to import is logged with its traceback and
skipped, never swallowed silently, and so is a key that two families both claim
-- a duplicate means one surface is quietly shadowing another, which is a
defect in the data rather than something to resolve by luck of import order.

**A surface whose content is live is rebuilt on every lookup.**  A family may
expose a ``REBUILDERS`` mapping of surface key to a no-argument builder, and
:func:`get` calls it instead of serving the import-time snapshot.  That is what
keeps the Key Select window showing the key group the editor is listening to
*now* rather than the one it was listening to when this package was imported.
A rebuilder that fails falls back to the snapshot and says so in the log: a
surface that opens with slightly stale content beats a surface that refuses to
open at all.
"""

from __future__ import annotations

import importlib
import logging
from typing import Callable, Dict, Tuple

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


#: A no-argument builder returning one surface description.
Rebuilder = Callable[[], Spec]


def _load() -> Tuple[Dict[str, Spec], Tuple[str, ...], Dict[str, Rebuilder]]:
    """Import every family and merge it, returning the map and what failed."""
    merged: Dict[str, Spec] = {}
    origin: Dict[str, str] = {}
    rebuilders: Dict[str, Rebuilder] = {}
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
        for key, builder in (getattr(module, "REBUILDERS", None) or {}).items():
            if not callable(builder):
                log.error(
                    "Studio spec family %r declared a rebuilder for %r that is "
                    "not callable; the import-time description will be served",
                    name,
                    key,
                )
                continue
            rebuilders.setdefault(str(key), builder)
    return merged, tuple(failed), rebuilders


SPECS, UNAVAILABLE_MODULES, REBUILDERS = _load()


def get(key: str) -> Spec | None:
    """Return the surface description for ``key``, or ``None`` when unknown.

    A key with a registered rebuilder is built fresh, so a surface whose
    content is read from live state -- the user's key group, say -- is current
    every time it is opened rather than frozen at import.  A rebuilder that
    fails or answers with something that is not a :class:`Spec` falls back to
    the import-time description, because a slightly stale window beats none.
    """
    name = str(key)
    builder = REBUILDERS.get(name)
    if builder is not None:
        try:
            rebuilt = builder()
        except Exception:
            log.exception("The rebuilder for Studio surface %r failed", name)
        else:
            if isinstance(rebuilt, Spec):
                return rebuilt
            log.error(
                "The rebuilder for Studio surface %r returned %r", name, type(rebuilt)
            )
    return SPECS.get(name)


def keys() -> Tuple[str, ...]:
    """Return every registered surface key, sorted for stable listings."""
    return tuple(sorted(SPECS))


__all__ = [
    "REBUILDERS",
    "SPECS",
    "SPEC_MODULES",
    "UNAVAILABLE_MODULES",
    "Rebuilder",
    "get",
    "keys",
]
