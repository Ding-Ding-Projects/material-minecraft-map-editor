# Local history

Amulet's local history is an append-only, Git-backed audit trail for
application-owned records such as settings, notifications, and future
document metadata. It is deliberately separate from a user's opened project:
the default repository is under the operating system's application-data
directory (`%APPDATA%/AmuletMapEditor/history` on Windows,
`$XDG_DATA_HOME/AmuletMapEditor/history` on Linux, and the equivalent macOS
Application Support directory). A caller may provide a test or profile path,
but the history API never derives a path from a project folder.

## Behaviour

`LocalHistory.record()` stores a bounded JSON snapshot and commits it as a new
local Git commit. The first snapshot is `created`; later changes are
`updated`. `delete()` records `deleted` and keeps the previous value in the
immutable event, so `restore(event_id)` can create a new `restored` event
without rewriting the earlier history. An unchanged snapshot produces no
event. Event files have unique IDs and are never replaced by later writes.

The store also provides plain-text-first search, optional explicitly enabled
regular expressions, action/type/date filters, JSON and Markdown exports, and
file exports. Queries and payloads are size-bounded. Regex is opt-in so a
setting name such as `[` remains ordinary text rather than accidentally
becoming an invalid pattern.

The native **View → Local history…** dialog provides bounded search, explicit
regex mode, action filtering, date pickers, multi-selection, **Select all**,
**Invert selection**, batch restore-as-new-event, JSON export, and an
**Open export in VS Code** action. `Ctrl+A` selects the visible events,
`Ctrl+I` inverts the selection, and `Enter` restores the selected events. A
partial restore reports the number completed and the exact failure instead of
pretending the whole batch succeeded. It keeps the history surface
non-blocking and returns focus through the normal dialog close path.

`LocalHistory.export_and_open()` writes the selected JSON or Markdown export
first, then uses the shared external-editor action to offer that file to VS
Code. If the editor is unavailable, its structured result reports the safe
failure while the export remains intact on disk.

## Failure and security boundaries

History is an audit aid, not the operation's source of truth. Use
`safe_record`, `safe_delete`, `safe_restore`, or the one-shot `safe_record`
helper around a primary operation: Git absence, an unwritable profile, corrupt
history, and validation failures return `None` rather than blocking the
setting/document change. Payloads are finite UTF-8 JSON and capped at 1 MiB.
Record IDs are hashed for filenames, so user text cannot traverse out of the
history directory. Credentials and project files are not copied into this
repository by the history module.

The local repository uses a fixed local author identity and has no configured
upstream. It is never synchronized or pushed unless a future user-facing export
flow explicitly offers that choice. Restoring is itself a new commit, keeping
undo operations undoable.

## Verification

`tests/test_local_history.py` covers default application-data placement,
created/updated/deleted/restored commits, no-change suppression, plain and
regex searches, date filters, exports, bounded payloads, and non-blocking safe
wrappers. The module has no wx dependency and can be tested on a headless
runner.

## Suggested articles

- [Scheduled settings](../scheduled-settings/README.md) — record temporary
  overrides and their recovery in the same local history.
- [Notification centre](../notification-centre/README.md) — review and export
  dismissed notifications.
- [Appearance presets](../appearance-presets/README.md) — preserve named
  appearance changes as user-owned records.
