# Electron world access -- the read-only half

The Electron renderer can now open a real Minecraft world, ask it what it
is, and close it again. This is deliberately half a feature: it is the
read-only slice, which is the part that is safe to ship before anything can
write a block back into a save. The implementation is
`amulet_map_editor/api/sidecar/world_methods.py`, registered into the
sidecar's dispatch table by `amulet_map_editor/api/sidecar/methods.py`.

This module never writes to a world. There is no method here that commits a
chunk, places a block, or calls anything on a `World` beyond reading its
identity, its dimensions, and closing it. Writing is a separate, later
lane's job.

## The method catalog

| Method | Params | Result |
| --- | --- | --- |
| `world.open` | `{"path": "<absolute path>"}` | `{"world_id": "<uuid>", "status": "pending"}` |
| `world.open_status` | `{"world_id": "<uuid>"}` | `{"status": "pending"}` or `{"status": "ready", "world_id", "path", "name", "platform", "version", "dimensions"}` or `{"status": "failed", "error": {"code", "message"}}` |
| `world.dimensions` | `{"world_id": "<uuid>"}` | `{"world_id", "dimensions": [{"dimension", "bounds": {"min": [x, y, z], "max": [x, y, z]}}, ...]}` |
| `world.close` | `{"world_id": "<uuid>"}` | `{"world_id", "status": "closed"}` |
| `recents.list` | `{}` | `{"entries": [...]}` -- the same records `amulet_map_editor.api.studio.recents.list_entries()` returns to the wx backstage, as plain dicts |

`world.open` never blocks on the load itself (see "Why `world.open` returns
before the world is open" below); poll `world.open_status` until its
`status` stops being `"pending"`.

## The path is untrusted, and is validated before amulet ever sees it

A world path arrives from the renderer as a JSON string over the sidecar's
stdio pipe. `_validate_world_path` in `world_methods.py` runs before
`amulet.load_level` is ever called, and rejects:

- anything that is not a non-empty string, or contains a NUL byte, or is
  over 1024 characters (`ERR_INVALID_PARAMS` / `invalid_params`);
- a **relative** path -- accepting one would resolve it against the
  sidecar's own working directory, not whatever the renderer's author had
  in mind, which is exactly the kind of silent path confusion this
  validation exists to rule out (`invalid_params`);
- a path that does not resolve to something that exists on disk, including
  a broken symlink or a symlink loop -- `os.path.realpath(path,
  strict=True)` is what does the resolving, so a symlink is followed to
  its real target before any other check runs (`world_path_not_found`);
- a resolved path that is neither an ordinary directory nor an ordinary
  file -- a socket, a FIFO, a character or block device is refused here,
  before it is ever handed to the world-format libraries
  (`world_path_unsupported`).

Only after all of that does the resolved, absolute path reach
`amulet.load_level`. A path that *is* an ordinary directory or file but is
not actually a recognisable world (an empty folder, a text file) is still
refused -- just one step later, as a `world_load_failed` status from
`world.open_status`, because only the world-format libraries themselves know
which directory layouts and file formats they can read.

## Why `world.open` returns before the world is open

The sidecar's dispatcher (`server.py`) reads one stdio line at a time and
runs each request's handler on its own thread with a bounded join -- but
that join still blocks the *next* line from being read for as long as the
handler runs. Parsing a large world's `level.dat` and enumerating its
region files can take far longer than the sidecar's own per-request
timeout (`DEFAULT_TIMEOUT_SECONDS`, 10 seconds), and a slow open must not
make every other in-flight request -- a `preferences.read`, a second
`world.open` -- wait behind it or time out.

`world.open` avoids that by never running the real load inline. It resolves
and validates the path (cheap), mints a `world_id`, starts a **background**
thread that calls `amulet.load_level` on the sidecar's behalf, and returns
`{"status": "pending"}` immediately -- normally in well under a second. The
caller polls `world.open_status`, which only reads an in-memory handle's
current state and is itself always fast, regardless of how long the real
load is taking. `world.close` follows the same shape: dropping the handle
from the registry is immediate, and the potentially-slow
`World.close()` call (releasing file locks, flushing any read caches) runs
on its own background thread too.

This is why the module never touches `amulet_map_editor/api/sidecar/server.py`:
the "don't block the sidecar" requirement is satisfied entirely inside
`world_methods.py`, by never giving the dispatcher's per-request thread
anything slow to run in the first place.

## World handles

Each open (or opening, or failed) world is tracked by an opaque `world_id`
(a UUID4 string) in a module-level, lock-guarded registry --
`_WorldRegistry` in `world_methods.py`. A handle's `status` is one of:

- `pending` -- the background load is still running;
- `ready` -- the load succeeded; `world.open_status` and `world.dimensions`
  both work;
- `failed` -- the load raised (most commonly `LoaderNoneMatched`, when no
  world-format loader recognises the path's contents); the failure is
  reported once as a structured `error` and the handle is not retried.

`world.close` removes the handle from the registry immediately, so a
follow-up call naming the same `world_id` -- to any of the four `world.*`
methods -- gets a structured `world_not_found` error rather than silently
operating on a handle nobody can see any more.

## When the world-format libraries are not installed

`amulet-core` and `PyMCTranslate` (imported as `amulet`) are an optional
dependency of the sidecar's own interpreter, not a hard requirement of the
process boundary itself. `world_methods.py` imports them once at module
load time inside a `try`/`except`; if the import fails for any reason, every
`world.*` method reports a structured `world_backend_unavailable` error
(carrying the real import failure text) instead of letting an `ImportError`
propagate up through the dispatcher as an opaque `internal_error`.
`recents.list` is unaffected -- the recent-projects store
(`amulet_map_editor.api.studio.recents`) has no dependency on the
world-format libraries at all.

This path is exercised directly in
`tests/test_sidecar_world_methods.py::test_world_backend_unavailable_degrades_to_a_structured_error`,
which monkeypatches the module's imported symbol to `None` rather than
uninstalling the real dependency from the test environment.

## Error codes

| Code | Meaning |
| --- | --- |
| `invalid_params` | (from the shared protocol) a malformed `path` or `world_id` |
| `world_path_not_found` | the path does not resolve to something that exists |
| `world_path_unsupported` | the path resolves to something that is neither a directory nor a regular file |
| `world_load_failed` | the path is an ordinary directory/file but no world-format loader could open it |
| `world_not_found` | `world_id` does not name an open, opening, or recently-failed handle |
| `world_not_ready` | `world.dimensions` was called while the handle is still `pending` |
| `world_backend_unavailable` | `amulet` / `PyMCTranslate` are not importable in this interpreter |

## Testing

`tests/test_sidecar_world_methods.py` spawns the **real** sidecar child
process (`python -m amulet_map_editor.api.sidecar`) and talks to it over its
actual stdin/stdout pipes -- the same approach
`tests/test_sidecar_protocol.py` uses, and for the same reason: a handler
called directly, in-process, proves the world-open logic and nothing about
the boundary it has to survive (JSON framing, a background load racing the
next request, a handle id that only makes sense to the process that minted
it).

A fixture builds a genuine, minimal Java world on disk with
`amulet.level.formats.anvil_world.AnvilFormat.create_and_open` -- not a
mock, not a fixture directory checked into the repository, but the real
world-format library writing a real `level.dat` and `session.lock` to a
temp directory, the same way the desktop editor's own "create a new world"
path does. Covered:

- the open -> poll -> ready -> dimensions -> close round trip against that
  real world, asserting real identity fields (platform, version,
  dimensions) and real per-dimension bounds;
- that a `world.open` immediately followed by a `protocol.ping` gets the
  ping answered without waiting for the whole load to finish;
- every path-validation rejection (`None`, empty string, relative path, a
  path that does not exist, and -- on the platform where it is cheap to
  create one -- a special file);
- opening a directory that exists but is not a world, ending in a
  `world_load_failed` status rather than a crash;
- `world.close` and `world.dimensions` against an unknown `world_id`;
- `recents.list` against a real, isolated `AMULET_RECENTS_DIR`;
- the `world_backend_unavailable` degrade path, in-process.

Run just this lane's tests with:

```
py -3.11 -m pytest tests/test_sidecar_world_methods.py -q
```

## Related reading

- `docs/features/sidecar/README.md` -- the wire protocol, versioning, and
  the rest of the method catalog this module's methods join.
- `docs/features/backstage/README.md` -- the wx backstage screen that
  `amulet_map_editor.api.studio.recents` already serves; `recents.list`
  exposes the same store to the Electron renderer.
