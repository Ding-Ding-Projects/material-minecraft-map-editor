# Notification centre

The notification history is a bounded local record for non-blocking
information, progress, warning, success, and error messages. It keeps
dismissed messages reviewable instead of erasing the only explanation of what
the app did.

Application startup is deliberately quiet: it does not open acknowledgement,
purchase, review, rating, donation, sponsorship, or promotional prompts. Safety
guidance remains available in context and in the offline documentation. The
bounded unsigned-updater banner is operational status rather than promotion;
it appears only for available, ready, or failed update states and never blocks
the editor.

## Behaviour

- Stores at most 200 validated records with UTC timestamps, severity, title,
  body, and dismissed state.
- Searches title and body in plain-text mode by default; explicit regex mode
  validates the pattern and reports invalid input before changing anything.
- Bulk dismiss reports the number changed and leaves already-dismissed records
  untouched.
- The history list supports multi-selection, localized **Select all** and
  **Invert selection** actions, plus `Ctrl+A`, `Ctrl+I`, and `Enter` keyboard
  paths. Dismissal still applies only to selected records or the explicitly
  chosen visible set.
- The window is Material 3 throughout: a frameless shell with the shared
  Material title bar, an outlined search field, owner-drawn actions, and a
  painted record table. The rows are `material_dialog.RecordTable` rather than
  a native `wx.ListCtrl`, which is a capture decision as much as a design one —
  a native list photographs as an empty white rectangle on a desktop with no
  compositor, while the capture report calls the row drawn, so the one part of
  this window worth checking was the one part no screenshot could show.
- Escape closes the window, and the close action works whether the centre was
  opened modally or modeless.

## Accessibility

The record table is one focusable control rather than one item per row, which
is the same shape the Studio's other painted lists use. Its accessible name
carries the row in focus, the row count, whether that row is selected, and how
many rows are selected, and it is updated on every move. Everything a pointer
can do a keyboard can do: arrows, `Home`/`End`, `Page Up`/`Page Down`, `Shift`
to extend from the anchor, `Space` to toggle one row, `Ctrl+A`, `Ctrl+I`, and
`Enter` to dismiss. A cell narrower than its value is elided and the whole row
is available as a tooltip, so nothing is lost at a narrow width.

The one control here that is still native is the technical-details box: it
keeps a real `wx.TextCtrl` inside a painted outline so caret movement,
selection, the clipboard and screen-reader text review stay the platform's own.
That box is consequently the one part of this window that does not appear in a
capture.
- JSON and Markdown exports preserve the active selection and state.
- The desktop shell projects each new record into a non-modal Material 3 toast
  stack. Informational and success toasts dismiss after six seconds; warnings
  and errors remain until the user chooses **Dismiss**. Toasts never request
  focus or block the active editor.
- Exception records keep a bounded summary in the toast and the complete
  multiline error and traceback in a selectable technical-details panel.
  **Copy details**, Markdown export, and JSON export preserve that evidence.

## Failure and security boundaries

Text is bounded and control characters are rejected. Malformed persisted rows
are ignored rather than shown as trusted content. Records stay in the local
application configuration and are not sent to a network service.

## Verification

`tests/test_notifications.py` covers add/search, regex validation, bulk
dismiss, bounded input, and both export formats. The native toast bridge is
covered by `tests/test_notification_toast_contract.py`.
`tests/test_notifications_ui_contract.py` constructs the window, selects two
records and dismisses them, so multi-selection is proved by running rather than
by the file mentioning a selection constant.

## Suggested articles

- [Local history](../local-history/README.md) — the other record list built on
  the same Material dialog scaffold.
- [Non-blocking error reporting](../non-blocking-error-reporting/README.md) —
  where the records in this centre come from.
- [Exports](../exports/README.md) — the formats this centre writes and the
  external-editor handoff that opens them.
