# Native rebuild continuation

Implement the accepted complete native Java editor replacement with pure Material Design 3 and task-specific editing workflows. The Qt Quick shell and Rust engine are an incomplete development increment, not a shipped replacement.

Baseline: 371b470c6ab79b90b03769eb66e108abd7549c7d. Integrated engine and protected-policy consumer: 43f8239a. Design, native shell and experimental build route are preserved with this record. Current target: 54 stable Java releases from 1.12 through 26.3; Bedrock, snapshots and future releases are excluded from the first native release.

Evidence: 18 engine unit tests plus one compile-fail documentation test; eleven native framing/controller/lifetime tests including the real Rust probe and unchanged fixture bytes; successful current-host `build.bat /native` with PySide6 6.12.0. Initial-state hidden runtime checks repaired layout compression and shutdown diagnostics. Source c178b394 launched and closed with empty logs. Normal/minimum initial layouts at 150% were inspected. Full rendered/accessibility acceptance and engine editing remain unavailable.

Next: verify the native shell on an isolated hidden desktop; complete version-bound fixtures, terrain and editing, transactional save-copy/recovery; complete required features, documentation, packaging and release. Preserve existing user worlds and applications. Do not mistake read-only probing for compatibility.

Candidate 71d4d3f551a9f3f8c9d413c40b2dcef02b93b812 is preserved on ai/feature/20261101-native-candidate after a complete publication scan passed with exact reviewed historical technical-literal exceptions and bounded binary-icon interpretation. Earlier local development history remains retained. No unfinished release was activated. Protected changelog build-input wiring remains pending before production integration. A newer read-only engine dimension/chunk slice is separately committed locally and under independent review; it is not part of this candidate yet. Do not weaken the scanner or expose policy data.

Status reporting uses SSH to the verified host. Connectivity succeeded, but its deployed older private-emission validator rejected the current client; no session update was claimed. The separate shared-instructions SSH requirement was pushed and synchronized. The full rebuild goal remains active.
