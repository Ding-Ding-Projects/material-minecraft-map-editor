# Native rebuild handoff

## Current verified state

The complete Windows-first Qt Quick/PySide6 and Rust rebuild remains active and unfinished. The candidate branch `ai/feature/20261101-native-candidate` is remotely verified through `8a3121c3dc74839a99e693dd172191cfc37a4b7b`. It is an inactive development checkpoint, not a completed default-branch integration or native release. Existing released applications remain preserved.

| Area | Verified evidence and boundary |
| --- | --- |
| Engine | Bounded NBT/region readers, pinned 1.20.1 registry membership, protected working-copy foundations, explicit reference resolver, cross-language terrain codec and selected-sector reader are integrated. 75 ordinary tests, one compile-fail test and two explicitly selected reference tests passed. Persistent terrain RPC is still being implemented separately. |
| Native consumer | 75 tests passed at 8a3121c3. Scene/page validation, geometry buffers, cancellation and camera math are implemented. Camera mutation defects were repaired and independently reviewed. Translation-only coordinates preserve handedness. Full real-engine terrain exchange remains pending. |
| Actual UI | Hidden startup, References dialog, empty 3D view and normal close passed with zero diagnostic bytes at 8a3121c3. All owned processes and the desktop were removed. No world was opened, no reference handshake ran in that UI check and no terrain geometry was rendered. |
| Reference provisioning | Reviewed preparation/generation helpers passed 20 focused tests and actual pinned Java data-generator execution. Four files totaling 5300402 bytes matched their pins and passed engine admission. No server was started and no EULA was accepted. Original producer provenance and new execution receipts remain separate. |
| Publication | The complete 8a3121c3 scan passed 891 text files and 1266 binary files with zero findings. Hosted execution, full protected-branch enforcement and release acceptance remain separate unfinished work. |

## Next bounded integration

1. Review and integrate the engine's persistent begin/page/end session, strict raw JSON admission, retained-scene budget and timeout behavior.
2. Run the explicit native real-engine acceptance module against the generated pinned reference directory and synthetic 3465 fixture. Missing methods must fail rather than skip.
3. Build through the exact root entrypoint, freeze the candidate, then verify actual hidden rendering, asymmetric projection/picking, cancellation, stale scenes, resource retirement and close.
4. Preserve the first real vertical slice, then expand geometry/material coverage, coherent editing/saving/recovery and version-specific acceptance without reducing the full target.

The current geometry capability is limited to verified propertyless stone/cobblestone shapes. It emits all six faces and makes no opacity, texture, lighting or collision claim. Independent research identified additional conservative cube candidates, but that research has not expanded runtime admission.

## Full remaining objective

The frozen target remains 54 stable Java releases from 1.12 through 26.3. Official embedded metadata identifies 48 data versions and six explicit gaps; every release's read/edit/round-trip acceptance remains unverified. Full materials and shapes, coherent saves, recovery, all-version compatibility, required features, documentation companions, native installer, normal release and installed update remain unfinished. Bedrock, snapshots, later releases, arbitrary mod semantics and unrelated backlog remain excluded.

Actual world generation requires explicit user EULA acceptance through the product workflow. The report-generation route does not grant that acceptance. Never modify user worlds to manufacture test evidence.

## Evidence and tracking

- [Rolling progress discussion](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/discussions/9)
- [Task and titled handoff issue](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/issues/8)
- [Terrain architecture](design/native-rebuild/terrain-workspace.md)
- [Frozen wire examples](engine/docs/terrain-wire-v1.md)
- [Compatibility and reference evidence](docs/compatibility/README.md)
- [Historical development notes](docs/history/development-handoff-through-8a3121c3.md)

A scoped project is formally linked to this repository; its task item remains In Progress. Existing issue 4 and the older implementation discussion remain unchanged. Path-bearing UI evidence, generated announcement images and official reference binaries remain private/ignored. Active branches and working directories remain retained.

Operational status reporting requires SSH. The deployed service rejects the current validation metadata, so no delivered status or service upgrade is claimed. Account allowance is unknown. The goal remains active.
