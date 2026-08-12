"""The Python sidecar: the core running as a child process, spoken to over stdio.

This package is the process boundary described by the migration plan's
"Phase 2 -- a process boundary, not a rewrite": the Python core keeps running
exactly as it does today, but as a child process supervised by an Electron
main process (or any other host, including the test suite), reached only
through a typed, versioned, newline-delimited JSON protocol on stdin/stdout.

Every module here imports only from :mod:`amulet_map_editor.api.core_boundary`
and the modules it lists -- the sidecar cannot serve a method whose
implementation carries a ``wx`` dependency, because that dependency would
never have been importable in the first place on a machine that only ships
the sidecar.

See ``docs/features/sidecar/README.md`` for the wire format, the method
catalog, and the bounds this boundary enforces.
"""

from __future__ import annotations

from amulet_map_editor.api.sidecar.protocol import PROTOCOL_VERSION

__all__ = ["PROTOCOL_VERSION"]
