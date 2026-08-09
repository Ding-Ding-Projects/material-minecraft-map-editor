# Non-blocking error reporting

Operational failures no longer open a traceback dialog over the editor. The
application records an error notification, keeps the active surface usable,
and preserves the complete exception message and traceback in Notification
history.

## Behaviour

- Error and warning toasts never request focus. They remain visible until the
  user dismisses them.
- The toast contains a bounded summary. Selecting its record in Notification
  history shows the complete multiline technical details and provides a
  **Copy details** action.
- Notification Markdown and JSON exports include the technical details, so
  evidence does not disappear when a toast is dismissed.
- Read-only documentation, changelog, and third-party-license references open
  modelessly. Waterlogging help is stored as a notification detail instead of
  interrupting an operation.
- Blocking modals remain only for explicit input, configuration, restore,
  destructive, file-selection, and confirmation workflows.

## Configuration

There is no switch that restores blocking error dialogs. Notification history
keeps at most 200 records. Summary fields accept at most 600 characters and a
technical-details field accepts at most 262,144 characters.

## Failure modes

If the top-level shell cannot paint a toast, the same record still remains in
local Notification history and the status-bar bridge is attempted. Malformed
or oversized persisted records are ignored instead of being rendered as
trusted content. The application log remains the independent diagnostic
record for process-level crashes that occur before the shell exists.

## Security considerations

Technical details stay in the local application configuration and exports the
user explicitly creates. They are never uploaded automatically. Control
characters other than tabs and line breaks are rejected, and the details size
is bounded to prevent one failure from creating an unbounded configuration
record.

## Verification

- `tests/test_nonblocking_error_reporting_contract.py` lists every known
  exception caller and verifies that it uses the non-blocking details bridge.
- `tests/test_modal_inventory_contract.py` is the hand-written completeness
  guard for every remaining `ShowModal` call.
- `tests/test_notifications.py` verifies details persistence, validation, and
  Markdown and JSON export.
- `tests/test_notifications_ui_contract.py` verifies the review and copy
  controls in Notification history.

## Suggested articles

- [Notification centre](../notification-centre/README.md)
- [Local history](../local-history/README.md)
- [Material application shell](../material-shell/README.md)
