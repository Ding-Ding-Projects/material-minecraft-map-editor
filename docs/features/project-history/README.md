# Per-project version history

Every project owns an isolated Git repository beside its world data. That is
what makes undo depth unlimited: the stack is not a buffer in memory that a
restart empties, it is a real commit history.

The repository is the application's, not the user's. It lives beside the project
in the application's own data area — never as a `.git` directory inside the
folder the user keeps their world in — so opening a world in Amulet never makes
that folder a Git working tree.

## Behaviour

One commit per applied operation, rename, or selection change. The message says
what changed rather than that something did: "Filled 4,096 blocks with
minecraft:stone", not "Updated".

**Restoring writes a new revision rather than rewinding.** The state you
restored *from* stays reachable, so an undo can be undone and that undo undone
in turn. History is append-only; nothing a restore replaces is discarded. This
is the single property that makes experimenting safe, and it is the same rule
the NBT editor's per-tag history follows.

The history is surfaced in six places, all reading the same repository:

- **Project history** — the commit graph, with Diff and Restore per revision.
- **Undo history** — the stack, with jump-to-point.
- The **breadcrumb context bar** — the head revision, always visible while
  editing.
- The **status bar** — the current revision and the unsaved-work state.
- **Project info** in the backstage.
- The **History tab** of the properties pane.

The history browser filters by date and by action, and carries the shared search
field with its regex opt-in and `.*` builder. The action filter is derived from
the actions actually recorded, with a count beside each, so an action with none
is visibly empty rather than mysteriously absent.

## Configuration

Retention and pruning are the user's to set. The repository stays local: it is
never pushed, synchronised, or shared unless the user explicitly asks for that.
Snapshots preserve whatever encryption the live data uses, so the history is
never more sensitive than the store it mirrors.

## Failure modes

A history write that fails never fails the operation the user actually asked
for. The failure is logged and reported through the non-blocking notifier, and
the edit stands.

If the repository cannot be created or read at all, the application says so and
keeps working with the in-memory undo the editor already had, rather than
refusing to open the project.

An unchanged state records nothing, so the browser stays a list of real events
rather than a list of times something was saved.

## Security and accessibility

Nothing leaves the machine. The repository holds the project's own data and no
credentials; identifiers used to bind encrypted records survive a delete and a
restore, so a restored row is still readable rather than failing in a way that
looks like corruption.

The browser is keyboard-operable end to end, every revision row is named with
its message and its timestamp, and the date picker accepts a typed date in the
locale's format and in plain ISO alongside the calendar.

## Verification

```powershell
py -3 -m pytest tests/test_local_history.py tests/test_studio_nbt_model.py -q
```

The first covers the local-history store and its append-only contract; the
second proves the same rule inside the NBT editor, including that a snapshot is
detached so later edits cannot reach back into it and that restoring a container
brings its children back.

Suggested articles: [local version history](../local-history/README.md),
[properties pane](../properties-pane/README.md),
[project shell](../project-shell/README.md), and
[destructive-action gate](../destructive-gate/README.md).
