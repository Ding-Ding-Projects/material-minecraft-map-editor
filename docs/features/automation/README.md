# Automation

Three surfaces for doing the same thing many times, or later, rather than once
now. They live on the Automate ribbon tab.

## Behaviour

| Surface | What it does |
| --- | --- |
| **Operation console** (`scriptConsole`) | Write and run an operation against the open project, with its output and its errors in place. |
| **Batch queue** (`batchQueue`) | A list of queued operations with their targets, run in order, with per-item progress and results. |
| **Macro recorder** (`macroRecorder`) | Record a sequence of actions and replay it. |

Each queued or replayed action is an ordinary operation: it produces a commit in
the project repository, it can be restored, and anything irreversible in it
passes the two-key gate before it runs rather than at the end of the batch.

The queue reports honestly. An item that failed says so and says why; the batch
does not report success because it finished. A long-running batch stays
cancellable and reports partial results rather than claiming a whole run
succeeded when part of it did not.

## Configuration

Queues and recorded macros are stored locally with the project. The console's
history persists for the session. Every list carries the shared search field
with its regex opt-in and `.*` builder.

## Failure modes

An operation that raises is caught, reported with its traceback in the console,
and does not take the batch or the application down with it. The queue continues
or stops according to the choice the user made when the batch was started, and
that choice is shown rather than assumed.

A macro replayed against a different world, or a different selection, checks
that its assumptions still hold and refuses with the specific mismatch instead
of applying an action to the wrong region.

## Security and accessibility

The console runs Python with the application's own permissions against the
loaded world. That is what it is for, and it is worth saying plainly: an
operation typed or pasted into it can do anything the application can do,
including deleting world data. Nothing is fetched from the network, and no
script is executed except one the user ran deliberately.

Recorded macros and queues are local files in the application's data area; they
carry no credentials and are never transmitted.

The console is keyboard-operable with a visible focus ring, its output region is
a named live region so results are announced, and long output scrolls rather
than clipping.

## Verification

```powershell
py -3 -m pytest tests/test_studio_spec_registry.py -q
```

That proves the three surfaces exist, are complete, and resolve. Running an
operation needs a build with a loaded world.

Suggested articles: [panels and views](../panels/README.md),
[per-project version history](../project-history/README.md),
[destructive-action gate](../destructive-gate/README.md), and
[bulk actions](../bulk-actions/README.md).
