# Scheduled settings foundation

## Scope

Amulet has a local schedule contract for four existing user preferences:
language mode, theme, density, and accent colour. The native wx Preferences
dialog includes a **Schedule** tab for loading, adding, editing, removing, and
reordering these rules. The persistence, validation, matching, and precedence
module remains wx-independent. Resolved values are not applied at runtime yet.

The contract is in `amulet_map_editor/api/scheduled_settings.py`, and the native
editor is in `amulet_map_editor/api/wx/ui/preferences.py`. It uses the
application's existing local config store and does not perform network access.
The separate `amulet_map_editor.api.scheduled_sources` module now provides a
validated source contract for a future refresh bridge: local, HTTPS API, and
Home Assistant boolean sources without storing tokens or remote values.

## Native editor

The Schedule tab presents the stored rules as a list and keeps the rule editor
on the same tab. Each rule exposes an enabled state, label, integer priority,
every-day or Monday-through-Sunday choices, optional ISO start/end dates,
24-hour start/end times, and optional language, theme, density, and accent
overrides. **Add rule** starts a blank rule, **Apply rule** validates it into the
in-memory list, and **Remove selected** removes the selected rule. Move controls
change stored order so equal-priority precedence is visible and editable. The
Preferences dialog's **OK** action validates any edited rule and saves the
complete list through the schedule module.

Switching to another list row never silently discards an edited form: the tab
asks the user to apply it first. Validation remains inline on the tab and is
localized through the existing language resources. If a readable stored
schedule has invalid or unsupported data, the editor is disabled, the exact
validation failure is shown, and the file is left unchanged rather than being
replaced with an empty schedule.

## Versioned storage

The local document has schema version `1` and a bounded maximum of 256 rules.
Each rule has a unique stable identifier, a non-empty label, an enabled state,
an integer priority from `-10000` through `10000`, weekdays, optional date
bounds, a local start/end time, at least one scheduled value, and a versioned
source object. Existing profiles migrate to the explicit `local` source.

Readable documents with unknown fields, invalid values, or an unsupported
version fail validation. This prevents a typo or newer schema from being
silently treated as an applied schedule. A missing or unreadable config file
loads as an empty version-1 document through the existing config-store behavior.

## Time and date semantics

- Weekdays use Python's stable numbering: Monday is `0` and Sunday is `6`.
- Times use strict 24-hour `HH:MM` values.
- Date bounds use strict ISO `YYYY-MM-DD` values and are inclusive.
- The caller supplies a `datetime` already expressed in the configured local
  timezone. This module does not guess or convert timezones.
- A start time equal to the end time is an all-day window.
- A start time later than the end time is a cross-midnight window. Its
  after-midnight portion belongs to the weekday and date on which the window
  started.
- The end time is exclusive, avoiding two adjacent rules both owning the same
  minute at their boundary.

The native Preferences editor pairs every typed ISO date and `HH:MM` value with
an M3-styled wx date or time picker. Typed text remains the canonical value for
validation and keyboard workflows; choosing a picker value synchronizes the
same field rather than creating a second schedule representation.

## Deterministic precedence

All matching rules are applied from lower to higher integer priority. Rules at
the same priority are applied in stored order, so the later stored rule wins for
any value both rules define. Scheduled values are partial: a rule that changes
only theme does not erase a language value supplied by another matching rule.
The resolution result includes the matching rule identifiers in application
order for diagnostics and future UI explanations.

## Failure and security boundaries

Rule construction, deserialization, and saving validate every bounded field.
Invalid documents raise `ScheduleValidationError`; unsupported schema versions
raise `UnsupportedScheduleVersion`. The wx editor surfaces these failures as
localized inline status while keeping unrelated base preferences usable.

Schedules contain no tokens, URLs, credentials, or remote response bodies. The
wx tab only edits the local document. The source layer rejects credentials,
queries, fragments, redirects, public HTTP, unknown fields, unsupported
versions, oversized payloads, and malformed entity IDs; it returns a
non-blocking failure result with a three-second bound and expects callers to
obtain Home Assistant tokens from the operating-system credential vault.
Runtime refresh application, cancellation generations, and UI status remain
explicit follow-up work.

`ScheduledRefreshCoordinator` supplies the non-blocking runtime primitive for
that follow-up. It runs a daemon refresh, obtains a Home Assistant token only
through a caller-provided vault callback, invalidates late responses when a
newer generation or shutdown wins, and invokes an apply callback only for a
validated non-empty result. It never writes the remote value to base
preferences.

## Verification

Run the focused, wx-independent suite:

```powershell
python -m unittest -v tests.test_scheduled_settings
```

The suite covers local persistence, schema versioning, deterministic precedence,
partial overrides, disabled rules, all-day and cross-midnight windows, date and
weekday boundaries, invalid input, unknown fields, duplicate identifiers, and
future-version rejection.

The wx-free structural contract test also confirms that the Preferences dialog
creates the Schedule tab, exposes weekday/date/time/override controls, and
routes loading and saving through the schedule module without adding network or
Home Assistant behavior.

`tests/test_scheduled_sources.py` covers URL policy, versioned allowlisted
payloads, Home Assistant on/off behavior, and malformed-response fallback.
`tests/test_scheduled_refresh.py` covers apply success, fetch failure,
non-blocking apply failure, asynchronous cancellation, and stale-response
suppression.

## Suggested articles

- [`README.md`](../../../README.md) for the project entry points.
- [`ROADMAP.md`](../../../ROADMAP.md) for the distinction between this
  foundation and future wx runtime integration.
- [`tests/README.md`](../../../tests/README.md) for the test-area entry point.
