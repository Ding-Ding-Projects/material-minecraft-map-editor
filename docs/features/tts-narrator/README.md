# Optional TTS narrator

The wx-independent `amulet_map_editor.api.tts_narrator` module provides an
opt-in spoken event queue. It is deliberately a small integration boundary:
the application can announce an update, save, or error without making the
event flow depend on a speech package, a network connection, or a visible
dialog.

## Behaviour

- Narration is **off by default** and is persisted in the profile under
  `amulet_tts_narrator`.
- The language choice is `english`, `cantonese`, or `both`. In `both` mode the
  English utterance finishes before the Cantonese utterance begins.
- Events are serialized through one worker. A newer event replaces an older
  queued event in the same category, preventing a burst of stale announcements.
- A short debounce groups rapid updates. A bounded per-category cooldown keeps
  repeated progress messages infrequent while retaining the newest event.
- English and Cantonese funny levels style the surrounding voice only. The
  event text and all factual details remain supplied by the caller.

## Configuration

`load_settings()`, `save_settings()`, and `update_settings()` validate the
versioned settings record. Cooldowns are bounded to 0–3600 seconds and debounce
to 0–10 seconds. The narrator language and settings are independent from the
app's package identity and from its update feed.

Applications inject a `SpeechBackend` with a synchronous `speak(text,
language)` method. `default_backend()` intentionally returns
`NullSpeechBackend`: this checkout does not claim that a Cantonese voice is
available, does not install optional speech dependencies, and never speaks
unless the user has enabled narration.

## Failure and security boundaries

Backend exceptions are logged and do not interrupt the originating operation.
The queue stores only bounded event text in memory and settings in the existing
local profile store; it stores no voice credentials, audio, telemetry, or
network response. `close()` clears pending events and joins the worker for safe
application shutdown. Screen-reader coordination and platform voice selection
belong to the future native adapter; the no-op backend is the honest fallback
until those capabilities are available.

## Verification

Run the wx-independent suite:

```powershell
python -m unittest -v tests.test_tts_narrator
```

The tests cover off-by-default persistence and bounds, same-category
debounce/replacement, serialized bilingual order, cooldown retention of the
latest event, funny-level styling, and the unavailable-backend no-op path.

### Suggested articles

- [Notification centre](../notification-centre/README.md) — review and export
  the non-blocking event that may also be narrated.
- [Scheduled settings](../scheduled-settings/README.md) — the shared local
  preference scheduling contract.
- [School mode](../school-mode/README.md) — why narration is suppressed when
  the user-facing presentation lock is enabled.
