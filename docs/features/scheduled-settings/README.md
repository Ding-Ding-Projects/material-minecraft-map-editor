# Scheduled settings foundation

## Scope

Amulet has a wx-independent, local schedule contract for four existing user
preferences: language mode, theme, density, and accent colour. This foundation
defines persistence, validation, matching, and precedence. It does **not** add a
schedule editor to the wx interface or claim that resolved values are applied
at runtime yet.

The implementation is in
`amulet_map_editor/api/scheduled_settings.py`. It uses the application's existing
local config store and does not perform network access. API-backed rules, Home
Assistant, credential storage, background refresh, and remote-value application
are deliberately outside this bounded foundation.

## Versioned storage

The local document has schema version `1` and a bounded maximum of 256 rules.
Each rule has a unique stable identifier, a non-empty label, an enabled state,
an integer priority from `-10000` through `10000`, weekdays, optional date
bounds, a local start/end time, and at least one scheduled value.

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
raise `UnsupportedScheduleVersion`. Callers should surface those failures as a
non-blocking localized error when the future wx integration is added, while
continuing to use the base preferences.

Schedules contain no tokens, URLs, credentials, or remote response bodies. The
foundation neither imports wx nor starts timers, threads, network requests, or
Home Assistant polling. Those capabilities require separate runtime design,
secure credential storage, cancellation, and UI verification before shipping.

## Verification

Run the focused, wx-independent suite:

```powershell
python -m unittest -v tests.test_scheduled_settings
```

The suite covers local persistence, schema versioning, deterministic precedence,
partial overrides, disabled rules, all-day and cross-midnight windows, date and
weekday boundaries, invalid input, unknown fields, duplicate identifiers, and
future-version rejection.

## Suggested articles

- [`README.md`](../../../README.md) for the project entry points.
- [`ROADMAP.md`](../../../ROADMAP.md) for the distinction between this
  foundation and future wx runtime integration.
- [`tests/README.md`](../../../tests/README.md) for the test-area entry point.
