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
- The native history list supports multi-selection, localized **Select all**
  and **Invert selection** actions, plus `Ctrl+A`, `Ctrl+I`, and `Enter`
  keyboard paths. Dismissal still applies only to selected records or the
  explicitly chosen visible set.
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
