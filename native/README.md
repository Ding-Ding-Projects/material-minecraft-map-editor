# Native read-only world inspector

This is a PySide6 Qt Quick read-only increment, not a replacement editor release. It opens a real local world directory, discovers actual region-backed dimensions and requests decoded chunk data from the Rust engine. A horizontal 16 × 16 section slice and block inspector expose exact returned data. A native 3D consumer is now implemented in source, but its persistent engine session and actual renderer interaction must be verified together before claiming 3D delivery. It never writes world files, edits blocks, converts worlds or claims full version compatibility.

## Build and launch

Use the repository root `build.bat /native` to prepare the isolated pinned runtime and engine. From the repository root, launch with the resulting interpreter:

```powershell
native/.venv/Scripts/python.exe -m native.amulet_native
```

The controller resolves `engine/target/debug/material-world-engine.exe` relative to the repository root on Windows. It does not search PATH or invoke a shell. Missing or incompatible engine binaries produce a visible incomplete state.

References are selected explicitly through the References dialog, or with `--reference-root <absolute-directory>` on the launch command. The startup override applies only to that launch. No world-derived or guessed cache is searched. The engine's actual pinned-reference acknowledgement is separate from the presence of terrain streaming methods; a build with only reference support reports that streaming remains unavailable. The prepared directory contains `reports/blocks.json`, `reports/registries.json` and the two pinned metadata records specified in the design contract.

## Implementation boundaries

- `framing.py`: bounded big-endian length framing, envelope validation, identity matching and truthful metadata validation. No Qt dependency.
- `controller.py`: one owned asynchronous QProcess, handshake then probe, 30-second deadline, bounded diagnostic/response handling, request generations, cancellation and close acknowledgement.
- `chunks.py`: strict dimension/chunk schemas, immutable dispatched tuple, absent/present distinction, palette and numeric validation, exact indexing and world coordinates.
- `explorer.py`: dimension/section/local-Y/cell selection model, with no file IO or process ownership.
- `ChunkWorkspace.qml`, `ChunkSlice.qml`, `BlockInspector.qml`: functional dimension/coordinate controls, categorical slice visualization and exact read-only inspection. Categories are not textures, biome colors or lighting.
- `qml/`: frameless Qt Quick shell and registered button components. The selected Qt Material foundation and custom anatomy require rendered conformance review before claiming Material Design 3 parity.

## Native 3D consumer, runtime acceptance pending

- `engine_coordinator.py` owns the single engine-process lease; `terrain_session.py` holds it through handshake, begin, ordered pages, release acknowledgement and process exit.
- `terrain_digest.py` implements the deterministic read-set encoding. `terrain_scene.py` validates exact wire identities, complete cell/shape inventories, page hashes and byte counts, duplicate faces, bounded allocations and immutable retained state. Its outputs agree with the engine's independent synthetic codec fixtures; those fixtures are not installed-world evidence.
- `terrain_math.py`, `terrain_picking.py` and `terrain_mesh.py` handle transactional camera changes, exact cell identities, bounded CPU picking and cooperative packed-buffer construction. World-to-Qt mapping is translation only. All six shape faces remain present; no neighbor opacity is inferred.
- `terrain_geometry.py` mutates actual QQuick3DGeometry objects only on their owning thread. `terrain_model.py` separates GUI acceptance from matched frame-submission receipts and waits for owned worker/geometry retirement during cancellation and close. A frame-submission signal is not a GPU-completion fence.
- `TerrainViewport.qml` and `TerrainWorkspace.qml` provide camera controls, explicit bounded area loading, picking, inclusive selection, cutaway and inspection. Top is a dedicated north-up/east-right orthographic preset. Ordinary orbit/fly retains its finite pitch/domain limits. The existing slice can project cells from the same accepted terrain snapshot without rereading or inventing missing data.

The initial capability is only `cube-shapes-v1`: verified unit-cube shape for the pinned propertyless 1.20.1 stone/cobblestone states. Material opacity, textures, lighting, full-world compatibility, additional shapes, editing, undo and saving remain unfinished. Unsupported cells stay unsupported. The full objective has not been reduced to this bounded preview. Current native 3D source has not yet been driven on the hidden runtime route; no screenshot or runtime completion is claimed here.

The synthetic `write_terrain_world` helper in `native/tests/chunk_fixture.py` creates a nonlaunchable 3465 MCA fixture with 1,024 stone cells, 28 cobblestone cells and 3,044 unsupported cells. Its expected supported-shape inventory is 6,312 faces. It is test data only and is never loaded as product startup content.

Theme and larger-text preferences persist locally through QSettings. There is no private mapping bundled into this package. The current UI is English only. Localization, complete accessibility tools, first-run setup, regex-equipped search, required feature inventory, actual build provenance, rendering and editing remain incomplete. Their absence is not evidence of product completion.

The normal client size is 1600×900 logical units, minimum 1280×720. Independent hidden-desktop verification found and repaired an initial vertical layout defect and shutdown-time null bindings. At source `c178b3943fd87c06476428a61618d7c6b7ed3cfb`, the initial English/light window rendered at 1600×900 logical units and 150% scale, and both startup and post-close diagnostic logs were empty. The earlier layout-only check covered the normal dark and minimum light initial states at the same scale and an actual dark-to-light transition. These bounded checks do not establish the complete theme/language/scale matrix, accessibility or Material Design 3 conformance. No installer/release acceptance is claimed.

## Focused checks

```powershell
python -m unittest discover -s native/tests -v
python -m compileall -q native/amulet_native native/tests
```

The five framing tests run without Qt. They verify fragmented/coalesced frames, hostile lengths/envelopes, paths as data, stale generations/identities and refusal to claim editing from a structural probe. Four QCoreApplication integration tests require the pinned runtime and engine: real probe with unchanged world bytes, cancellation during startup, reselection and close acknowledgement. Two lifecycle tests reproduce premature backend destruction and verify ordered root, engine and backend teardown. All eleven passed with PySide6 6.12.0 and the debug engine. These tests create no visible GUI. QML lint completed with context-property qualification warnings; the independent hidden-desktop evidence above is the separate bounded runtime verdict.

The chunk increment adds six schema/index tests and four real MCA/controller tests. They cover both block representations, missing data, malformed arrays/properties, exact coordinate extremes, unchanged fixture files, cancellation, request replacement and dimension invalidation. The slice and inspector have not yet received a pinned hidden-runtime review. Selectors now own plain-text filters and independent bounded Python re workbenches with actual flags, literal escaping and sample spans. Unsupported advanced capabilities remain visible; full RegexBuddy parity is unfinished. Numeric fields have independent clear/help actions. The final focused suite has 30 passing checks, including startup/early-exit status, schema regressions, grid navigation and regex timeout/isolation. See COMPONENTS.md for source provenance and exact capability boundaries.

The subsequent ownership repair brings the focused suite to 37 passing checks. Direct-interpreter PID handshakes, native process-tree absence receipts, timeout/supersession/close acknowledgement, cancel-close, final-drain bounds and complete result-shape validation are covered. No GUI launch was performed for this repair; hidden runtime acceptance remains pending.
