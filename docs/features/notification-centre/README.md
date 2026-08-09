# Notification centre

The notification history is a bounded local record for non-blocking
information, progress, warning, success, and error messages. It keeps
dismissed messages reviewable instead of erasing the only explanation of what
the app did.

## Behaviour

- Stores at most 200 validated records with UTC timestamps, severity, title,
  body, and dismissed state.
- Searches title and body in plain-text mode by default; explicit regex mode
  validates the pattern and reports invalid input before changing anything.
- Bulk dismiss reports the number changed and leaves already-dismissed records
  untouched.
- JSON and Markdown exports preserve the active selection and state.

## Failure and security boundaries

Text is bounded and control characters are rejected. Malformed persisted rows
are ignored rather than shown as trusted content. Records stay in the local
application configuration and are not sent to a network service.

## Verification

`tests/test_notifications.py` covers add/search, regex validation, bulk
dismiss, bounded input, and both export formats. The wx toast/notification
centre surface remains a follow-up adapter; this module is the shared storage
and bulk-action contract.
