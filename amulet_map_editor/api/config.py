import os
import pickle
import gzip
import time
from typing import Any, Dict, Optional, Tuple

_last_config_env = os.environ.get("CONFIG_DIR")
_path = os.path.abspath(os.path.join(_last_config_env or "."))

#: How long a read of a profile file stands in for the next one, in seconds.
#:
#: :func:`get` is called from inside paint handlers -- resolving one appearance
#: token reads two profile files, and a single repaint of the shell asks for
#: hundreds of them.  Without this window every one of those is a ``stat`` plus
#: a gzip decompress plus an unpickle, which measured at 207us each and made
#: re-reading the preferences file the largest single cost in the interface.
#:
#: The file stays the authority rather than the cache: School mode is a switch
#: deliberately shared with other applications, so a write by another process
#: must still be picked up by a running shell.  This window bounds how late
#: that is by a quarter of a second, which no one can perceive, while
#: collapsing a repaint's worth of reads into one.
CACHE_SECONDS = 0.25

#: identifier -> (monotonic time the payload was read, pickled payload bytes).
#: ``None`` payload records "there is nothing readable here", so a missing or
#: corrupt file is not re-opened on every call either.
_cache: Dict[str, Tuple[float, Optional[bytes]]] = {}

#: Bumped by every call to :func:`invalidate`, including the one :func:`put`
#: makes on every write.  A caller layering its own cache on top of this
#: module -- :func:`amulet_map_editor.api.studio.tokens._presentation` does --
#: can compare this against a remembered value to notice an in-process write
#: at once, instead of only after :data:`CACHE_SECONDS` lapses.  The counter is
#: process-local on purpose: a write from *another* process does not touch it,
#: and that gap is exactly what the time-based window above still covers.
_generation = 0


def generation() -> int:
    """Return a counter that increases on every local write or invalidation.

    A caller may safely hold this alongside a cached value it derived from
    :func:`get`: unchanged means nothing this process wrote could have made
    that value stale.
    """
    return _generation


def invalidate(identifier: Optional[str] = None) -> None:
    """Forget cached profile data, for one identifier or for all of them.

    Anything that writes a profile file behind :func:`put`'s back must call
    this, or the write is invisible until the read window lapses.
    """
    global _generation
    _generation += 1
    if identifier is None:
        _cache.clear()
    else:
        _cache.pop(identifier, None)


def _config_path() -> str:
    """Resolve the active profile directory for each operation.

    Tests and multi-surface hosts intentionally switch temporary profiles
    within one Python process; caching the environment at import time makes
    one surface read another surface's settings.
    """
    global _last_config_env, _path
    current = os.environ.get("CONFIG_DIR")
    if current != _last_config_env:
        _path = os.path.abspath(os.path.join(current or "."))
        _last_config_env = current
        # The cache is keyed by identifier alone, so a profile switch has to
        # empty it: the same identifier names a different file now.
        _cache.clear()
    return _path


def _read_payload(path: str) -> Optional[bytes]:
    """Return the pickled payload of a profile file, or ``None`` if unusable.

    The payload is unpickled once here purely to prove it can be, so a corrupt
    file is diagnosed on the read that found it rather than on every call that
    is later served from the cache.
    """
    try:
        with gzip.open(path, "rb") as fp:
            data = fp.read()
        pickle.loads(data)
    except Exception:
        return None
    return data


def get(identifier: str, default: Any = None) -> Any:
    """
    Get the config data for a given identifier. Use an identifier unique to your program.
    :param identifier: An identifier unique to your program
    :param default: The value to return if one could not be loaded
    :return: config data
    """
    path = os.path.join(_config_path(), identifier + ".config")
    now = time.monotonic()
    entry = _cache.get(identifier)
    if entry is None or now - entry[0] >= CACHE_SECONDS:
        payload = _read_payload(path) if os.path.isfile(path) else None
        entry = (now, payload)
        _cache[identifier] = entry
    if entry[1] is None:
        return default
    try:
        # Unpickled per call rather than shared, because that is what reading
        # the file gave every caller: a caller that mutates what it got back
        # must not be editing the next caller's copy.
        return pickle.loads(entry[1])
    except Exception:
        _cache[identifier] = (now, None)
        return default


def put(identifier: str, data: Any):
    """
    Add data to the config file and save to disk.
    :param identifier: An identifier unique to your program
    :param data: The data to be saved. Must be JSON serialisable
    :return:
    """
    path_root = _config_path()
    if not os.path.isdir(path_root):
        os.makedirs(path_root)
    path = os.path.join(path_root, identifier + ".config")
    with gzip.open(path, "wb") as fp:
        pickle.dump(data, fp)
    # This process just changed the file, so the window does not apply: the
    # next read must see what was written, not what was there a moment ago.
    invalidate(identifier)
