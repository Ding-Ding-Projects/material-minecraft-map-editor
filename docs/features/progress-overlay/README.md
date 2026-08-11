# In-app progress

Long operations report on a linear progress indicator drawn over the top of the
application, not in a dialog. Saving a world, closing one, extracting one, and
running an operation over one all used to open a `wx.ProgressDialog`, which is
application-modal: it takes focus, disables the window behind it, and puts a
second title bar in front of the interface for as long as the work runs.

That surface is reserved in this project for a decision the user has to make
before anything else can happen. Progress is not a decision. It is information,
so it goes on a non-blocking surface and the interface underneath keeps working.

## Behaviour

- One overlay, in the shell, shared by every operation. It is **positioned**
  over the interface rather than added to a sizer, exactly as the notification
  toasts are, so a row appearing takes no space and reflows nothing.
- It sits below whichever title bar is currently in use — the frame's own when
  the world notebook is showing, the Studio's when it is — so the window
  controls are never covered by it.
- Each row carries the title, a detail line, a reading, and the progress
  indicator itself. Several concurrent operations stack as several rows.
- **Work that can report a fraction fills a bar; work that cannot draws a
  travelling band.** These are deliberately different pictures: "cannot say" is
  not "nothing yet", and drawing an empty bar for unmeasurable work claims a
  measurement nobody took. Both come from `api/studio/loading.py`, so the
  startup screen and the overlay cannot drift into disagreeing about it.
- The reading beside the title says `42%` when there is a percentage and
  `Working…` when there is not, rather than leaving a blank where a number
  should be.
- An operation begins indeterminate and becomes determinate the moment
  something reports a fraction. `OperationThread` tracks this explicitly with a
  `reported` flag, because an operation that has not yielded yet leaves its
  progress at `0.0` — which is indistinguishable from one genuinely at zero.
- **Cancellable work keeps its cancel, on the row.** A row draws a Cancel
  control exactly when the work behind it can actually be stopped; work that
  cannot be cancelled draws none, because a control that appears to abort and
  does not is worse than no control.
- Where an operation genuinely does make something unavailable, the row names
  which thing — running an edit says that another edit cannot start until this
  one finishes — rather than leaving the window apparently frozen with no
  explanation.
- **A completion retires its row; a failure keeps it.** A failed row turns red,
  keeps its message, and stays until the user dismisses it, and is also written
  into notification history so the failure is reviewable after the row is gone.

## Configuration

There is nothing to configure. The overlay appears when work is running and
goes when it is not. It cannot be turned off, because the alternative to
showing progress is a silent wait.

Reduced motion is honoured through `widgets.reduced_motion()`, which reads the
platform preference and the `AMULET_REDUCED_MOTION` environment variable.

## Failure modes

- **A failure inside the work.** `begin_progress` returns a context manager, so
  an exception leaving the block marks the row failed and leaves it on screen.
  That makes the reporting structural rather than something each call site has
  to remember.
- **A row left open by a crash.** `EditCanvas._run_operation` closes its
  reporter in a `finally`, so an operation that dies before its loop finishes
  cannot leave a progress indicator on screen forever.
- **No shell to draw on.** A surface constructed outside the application frame
  still gets a working reporter that has nowhere to draw. An operation must
  never fail on account of the surface that was watching it.
- **No overlay at all.** A build whose Studio package cannot be constructed
  reports progress in the status bar instead. Poorer, but truthful.
- **A worker thread reporting.** `ProgressReporter` marshals through
  `wx.CallAfter` when it is called off the main thread.

## Accessibility

- The overlay carries an accessible name that is the whole stack read as a
  sentence, refreshed on every update, so the value announced is the current
  one rather than the one the row opened with. Unmeasurable work says
  "remaining time unknown" instead of going silent — silence from a progress
  indicator is indistinguishable from one that has stopped.
- It never takes focus. A row appearing must not move the cursor out of what
  the user is typing.
- Reduced motion stops the animation, and the still appearance is a *different*
  picture rather than a frozen one: the track is drawn as evenly spaced
  segments across its whole width. A stationary band would be the exact shape
  of a part-filled determinate bar and would be read as a percentage that does
  not exist.
- The status bar carries the same sentence, so the report reaches a reader
  following the frame rather than the overlay.
- Failures are announced through the narrator, once per failure rather than
  once per repaint.

## Verification

`tests/test_progress_overlay_contract.py` holds the source-text half: no module
may use `wx.ProgressDialog`, `wx.BusyInfo`, or `PD_APP_MODAL`, checked against
the parsed tree rather than the text so the prose explaining the ban does not
trip it. Beside that ban is a hand-written list of the four long operations that
must report, because a ban cannot catch an operation that reports nothing at
all — a file with no progress in it passes every rule about how progress is
drawn.

`tests/test_progress_overlay_runtime.py` holds the half that matters. It builds
the real frame and drives `WorldSelectUI._extract_archive` over a real 900-member
zip archive, asserting that no blocking dialog was opened, that the overlay was
on screen while the work ran, that its fraction moved through intermediate
values, and that a click queued during the operation was handled *before* the
operation finished. It compares the rendered pixels of the determinate,
indeterminate, and reduced-motion bars to prove the three are genuinely
different pictures, and it photographs the overlay through the capture harness
and checks the result is not one flat colour.

Two defects were found by writing those and neither was visible in the source:
the travelling band was pinned stationary at the left edge for the first fifth
of every cycle, because the visible band clamped its left edge while keeping its
full width instead of intersecting with the track; and a `wx.Timer` heartbeat is
useless for measuring responsiveness inside a yield loop, because `WM_TIMER` is
low priority and a busy loop starves it.

## Related reading

- [Notification centre](../notification-centre/README.md) — where a failed
  operation's record goes once its row is dismissed
- [Non-blocking error reporting](../non-blocking-error-reporting/README.md) —
  the same rule applied to errors
- [Material application shell](../material-shell/README.md) — the frame that
  positions the overlay and the toasts
- [The capture matrix](../capture-matrix/README.md) — how the overlay is
  photographed
