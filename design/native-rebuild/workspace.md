# Terrain workspace and action contract

## Visual composition

The workspace has five stable regions: a top command/search bar, world-tab strip, world navigator, terrain viewport with tool controls, and contextual inspector. An operations/history drawer expands from the bottom. Version and provenance remain visible in the bottom status region on the initial screen as well as the editor.

At 1600 × 900 logical client units, use 24-unit outer spacing, an 80-unit top region, a 48-unit tab strip, a 248-unit navigator, 16-unit gutters, a 288-unit inspector and a 40-unit status region. The viewport absorbs remaining width and height. The drawer defaults to its 48-unit collapsed summary and expands to 224 units, retaining at least 320 units of terrain height. Splitters have 8-unit interactive targets, keyboard resizing and persisted per-world proportions; double-click resets. Use a frameless window with a custom Material Design 3 title bar and window controls; the operating system's default title bar is not product chrome. The custom title bar is included in the stated client dimensions.

The top region reserves distinct 48-unit targets for Minimize, Maximize/Restore and Close. Only unoccupied title-bar space initiates native system move; controls and search never initiate a drag. Preserve native system resize, snap, keyboard system-menu and Alt+F4 behavior through supported Qt/platform interfaces. Closing delegates to the existing unsaved-work/write-in-progress decision. Maximized, restored, focused, inactive and full-screen states are explicit. Full-screen exit remains keyboard-accessible and visibly discoverable. Window controls carry accessible names, focus and hover/pressed states; none are decorative.

At 1280 × 720 logical units, navigation becomes a temporary leading side sheet opened by a visible World button. Inspector is 280 units. The drawer remains collapsed unless invoked; an expanded drawer may become a full-height work panel with a visible Return to terrain action when remaining terrain height would fall below 320. No automatic scrolling of the complete editor canvas. Each sheet owns its vertical scroll area. Do not silently hide selected-block facts to make the geometry fit.

At smaller effective sizes caused by extreme text enlargement, offer one active contextual sheet at a time, retain terrain and the World/Inspect/Operations controls, and let forms scroll. Dialog actions remain in a fixed footer. Viewport camera controls must never be covered by a snackbar or sheet footer.

## Pure Material Design 3 implementation boundary

Use PySide6-hosted Qt Quick for the native presentation. This is the selected framework. A later terrain increment uses a native terrain item, with application state and Rust work dispatched outside the UI thread. This specification does not authorize replacing native terrain with a browser. A QML rectangle with rounded corners, a recolored stock widget, or the Qt Quick Controls Material theme alone does not establish Material Design 3 compliance.

Before implementation, register a small component set with exact implementation paths, source/provenance, anatomy and state tests. Each visible control references a registered component. Required components: search bar, filled/tonal/text/icon buttons, segmented buttons, primary and secondary tabs, navigation drawer items, list items, filter chips, outlined text fields, exposed dropdowns, checkboxes, radios, switches, sliders, menus, dialogs, side sheets, bottom sheets, tooltips, snackbar, linear/circular progress, and focus/state layers. No fallback to stock desktop chrome inside the client area when a component is absent; record it unfinished. Terrain itself is a data visualization and can retain actual block colors, but its chrome uses the same registered controls.

The hand-written design registration is [components.md](components.md). Its component identifiers, anatomy, state matrix and source references are normative for review. Proposed implementation paths are explicitly pending, not existing or accepted components.

## Bounded first increment: read-only world probe

Implement only a frameless PySide6 Qt Quick shell with real Open world, Cancel probe, window controls, accessibility entry and truthful version/provenance display. Its screen states are `probe-shell/empty`, `probe-shell/probing`, `probe-shell/result` and `probe-shell/unsupported`. Failure and acknowledged cancellation return to an explicit empty state with a retained factual result message. A result distinguishes readable metadata from unsupported editing. The shell calls the actual read-only Rust probe and renders only returned metadata and capability facts. Never show invented version support, synthetic terrain, placeholder dimensions, enabled editing, a working-looking Save button or fabricated progress counts. The populated workspace SVG is future composition guidance, not this increment's startup screen.

Selecting a world canonicalizes its stable identity and increments a monotonic request generation. Requests and replies carry that generation, request identifier and world identity. Accept a reply only when all three match the active probe and the shell still exists. Selecting another world invalidates the old generation before work begins. Late success, failure and progress events cannot replace the current result. Paths are local inputs, never arbitrary command strings. Probing never writes world files or acquires an editing claim.

Cancel requests cancellation from the worker and displays Cancel requested until acknowledgement or actual worker termination. Invalidating a reply prevents stale rendering immediately but does not prove the worker stopped. A bounded cancellation timeout produces an explicit incomplete state and uses the documented task-owned worker termination route if supported; never terminate unrelated processes. Closing during a probe requests cancellation and defers destruction until the worker acknowledges stopping or is safely terminated. Offer Wait or Cancel close while stopping remains unresolved. Do not block the UI thread indefinitely in destruction. Workers hold no UI-object references and release file handles on every exit. Cover late reply, rapid reselection, cancel-after-completion, worker failure and close-during-probe in lifecycle tests.

The proposed components used by this increment become actual registered implementations during implementation. Existing source is not required before it can be authored. Before shell acceptance, attach exact implementation paths, pinned Qt/source/license receipts, state tests and rendered audit for those components. Other registered components remain pending. Minimum-size and bilingual first-shell references remain required before visual acceptance.

### Future editing decisions and write boundary

Apply changes only the editing session plus its application-owned recovery journal. Apply never writes the source world's region or metadata files. Save is the explicit operation that writes world bytes transactionally. A journal write is not a saved world. Save copy writes only the explicitly selected destination. Journal locations, durability, transaction IDs, backup retention and atomic replacement strategy need engine contracts and verification before editing is enabled.

Coordinate fields present inclusive minimum and maximum block coordinates; document any internal half-open conversion and checked volume arithmetic at the engine boundary. Before editing implementation, finalize the camera gesture/key map and keyboard alternatives, external-writer/lock revalidation immediately before each write, and append-only discard history with restoration semantics. These are open design/engine decisions, not permission for the read-only shell to guess. The first increment needs no editing capability.

### Role palette

| Role | Light | Dark |
| --- | --- | --- |
| surface | #F7FBF2 | #101510 |
| surfaceContainerLow | #F1F5EC | #191D18 |
| surfaceContainer | #EBEFE6 | #1D211C |
| surfaceContainerHigh | #E5E9E0 | #272B26 |
| onSurface | #191D18 | #E1E5DC |
| onSurfaceVariant | #424940 | #C2C9BD |
| outline | #72796F | #8C9388 |
| outlineVariant | #C2C9BD | #424940 |
| primary | #3F6837 | #A5D395 |
| onPrimary | #FFFFFF | #10380A |
| primaryContainer | #C0EFAF | #285020 |
| onPrimaryContainer | #072102 | #C0EFAF |
| secondaryContainer | #DCE7D3 | #3E4A36 |
| onSecondaryContainer | #151F0F | #DCE7D3 |
| error | #BA1A1A | #FFB4AB |
| onError | #FFFFFF | #690005 |
| errorContainer | #FFDAD6 | #93000A |
| onErrorContainer | #410002 | #FFDAD6 |

These are candidate semantic roles, not a completed contrast audit. Measure actual rendered text and focus contrast in both themes, including user-customized colors. Never use terrain colors for error, focus or selection meaning. Selection uses a primary-colored outline plus corner handles and a pattern; preview changes use add/remove patterns and a text legend, not red/green alone.

Use an explicitly bundled, licensed sans family covering Latin and Traditional Chinese with real font fallback metrics. Body: 14/20 and 16/24; label: 14/20 medium; title: 22/28; section title: 16/24 medium. Coordinates and identifiers use a bundled monospace at 13/20 minimum. Do not impose letter spacing on Chinese text. Material Symbols may be used only with retained license and official glyph provenance; icon-only controls require names and tooltips.

Use 4-unit spacing increments, 12-unit field corners, 16-unit side-sheet corners, 28-unit dialogs and pill-shaped primary actions. No arbitrary border around every layout region. Tonal surfaces establish hierarchy. Use elevation only for floating controls, dialogs and menus, with opaque surfaces underneath. Interactive targets are at least 48 × 48 logical units unless a reviewed density mode preserves an equivalent hit area.

Hover state layer: 8%; focus/pressed: 12%; disabled content: 38%, disabled containers: 12%. A strong visible focus outline remains independent of state tint. Routine transition 150 ms, sheet transition 250 ms; no terrain-camera motion triggered by changing theme or language. Reduced motion removes spatial transitions and retains immediate state changes or a short opacity change. Default terrain-camera movement is user-driven only.

## Native state boundaries

The UI consumes typed world session, capability, dimension, selection, camera, operation preview, progress, history, recovery and save-result models. Rust reports facts, including coordinate bounds, block-state validity, supported data versions, dirty chunks and transaction outcome. The UI never invents counts, successful writes or available operations.

Each operation request carries stable world identity, dimension, selection revision, world revision and typed arguments. Preview results carry that same identity. A changed world/selection invalidates the preview. Applying stale results requires recomputing, not a warning that permits stale writes. All file writes pass through an engine transaction and journal/backup policy. Cancellation waits for the engine's acknowledged safe boundary. A hidden progress animation is not cancellation.

## Action contracts

| Action / entry | Preconditions and input | Visible result and recovery |
| --- | --- | --- |
| Open world / Ctrl+O | Native directory picker; probe metadata without mutation; deduplicate by canonical identity | Open existing world tab or show support/lock verdict; incompatible worlds remain unopened with exact reason |
| Choose dimension | Decoded dimension inventory; stable dimension identifier | Retain per-dimension camera and selection; cancel/invalidate previews tied to prior dimension |
| Pan/orbit/fly | Focused viewport; documented modifier map; user input only | Camera HUD updates exact coordinates; Esc exits pointer capture; keyboard alternative available |
| Go to coordinates | Signed numeric X/Y/Z; engine world bounds; visible dimension | Validate before moving; preserve prior camera for Back to previous view |
| Select box | Drag handles or numeric minimum/maximum bounds; inclusive/exclusive convention explicit | Patterned volume, exact extents and count; no mutation; empty/oversized states explained |
| Inspect block | Engine-backed hit result | Block identifier, state properties, coordinates and block-entity presence; absent chunk shows unavailable, never air |
| Fill/replace | Valid selection, writable world, version-valid block state | Read-only preview with count, affected chunks, limits and backup destination; Apply separate from Preview |
| Apply preview | Same world/dimension/selection/revision as preview | Transaction progress in initiating inspector and drawer; successful session edit adds undo entry; failure retains original data and recovery explanation |
| Undo/redo | Engine reports available transaction and current revision | Acknowledge actual applied transaction; update terrain and counts; unavailable states expose reason |
| Save / Ctrl+S | Dirty session; verified writable target; no external conflicting writer | Progress then actual saved revision; external change offers Reload/Save copy/Cancel; never overwrite automatically |
| Save copy | User-selected destination, space/collision checks, backup policy | New verified target without changing source world; partial output clearly isolated and recoverable |
| Close world | Engine identifies pending writes and dirty changes | Save / Discard session changes / Cancel; Cancel initial focus; no force-closing live writes |
| Find blocks | Independent plain-text or regex query plus dimension/selection scope | Bounded, cancelable indexed results; selecting a result navigates camera; never mutates |
| Import structure | Actual parser and version capability, destination preview | Ghost placement with transforms and bounds; Apply only when validated; unsupported formats explicitly unavailable |
| Export selection | Actual exporter capability and typed format options | Destination and omitted-data disclosure; exact output success or partial/failure state |
| NBT edit | Typed tree, bounds, engine-valid types; sensitive player information protected | Changes staged and validated before transaction; raw identifiers remain exact; safe recovery on parse failure |
| Command/search | Search local actions, worlds and contextual destinations | Disabled results explain context; selecting tools focuses their real UI, never executes destructive edits immediately |
| New tab | Explicit catalog of registered destinations | User choice alone opens utility tab; one world tab per stable world; settings navigation does not manufacture world tabs |

Every operation has idle, validating, previewing, ready, applying, cancel-requested, canceled, succeeded, failed and recoverable states where relevant. Percentages only appear with a real denominator. Otherwise show processed count and indeterminate progress. Failed save state remains persistent until acknowledged; a transient snackbar alone is insufficient.

## Search and regex

Every search has an adjacent named Regex builder action, anchored to its owning field and independently keyed. This includes global command search, world navigator, blocks, properties/NBT, history, settings, documentation, file lists, catalog, each tab strip/group, group search, master tab search and both bulk-close searches. Default mode is plain text. Query, pattern, flags, validation and mode synchronize in both directions for that field alone. Closing the builder returns focus to its originating field and never changes another field.

The builder is a real structured workbench with construction, syntax explanation, exact engine/version selection, flavor comparison/conversion, sample matching and replacement, debugger, bounded benchmark, code/templates, saved collections, safe local-file search and preferences. Every unsupported engine capability has an explicit reason and unfinished inventory row. No general parity claim is permitted from a tester dialog. Bounds apply to pattern size, input size, CPU/time and result count, with cancelable isolated execution and no catastrophic expression on the UI thread. A builder that cannot fit beside its field becomes a bounded dialog without covering its origin, with persistent ownership context.

## Setup and accessibility

First run is a separate practical wizard: language/accessibility and sound preferences; verified engine availability; backup/recovery location and actual write probe; choose a world or skip the optional opening step; review results and enter the empty productive workspace. Back/Next preserves values, unfinished setup resumes locally, and failed required steps cannot be marked complete. Never silently download game assets or require a Microsoft account merely to open a local world.

Keyboard traversal order: command bar, world tabs, navigator, terrain tools, viewport, inspector, drawer, status actions. F6 cycles major regions. Escape closes the top temporary surface and restores originating focus. Modal dialogs trap focus only for their lifetime; nonmodal notifications never do. Native accessibility roles expose tab selection, tree level, editable values, progress and status. The terrain has a textual alternative containing focused block, coordinates, dimension and selection bounds plus keyboard movement. Screen readers must not receive every frame or camera tick.

Accessibility tools remain visible in the persistent shell and have a local entry inside dialogs/full-screen states. Text size, contrast, reduced motion, focus strength, target size, keyboard help and read-aloud apply immediately and persist. Disabled controls retain accessible reasons. Bilingual controls use stacked primary/secondary labels, grow vertically, and never use fixed heights that crop Cantonese. Technical identifiers remain exact in all languages. Critical facts and action labels remain unambiguous at every tone setting.

## Settings and product-wide obligations

Settings are task groups with a persistent search and independent regex builder: Editing and recovery; Navigation and input; Rendering and performance; Appearance and layout; Language and personal wording; Accessibility and narration; Sound and notifications; Tabs and workspaces; Files and integrations; Local tools; Privacy and diagnostics. Each row must have a real consumer, documented default, persisted storage, reset behavior and unsupported state. The catalog is not an implementation substitute.

The design must retain the full required-feature inventory, including personal-wording upload/drop/replace/clear; independent language tone controls; user-renamable shared mode and its safe unlock; appearance editors and locks; support tickets; command palette; tab pin/group/reorder/search/bulk-close; local version history; bulk operations; exports; conversion; external-editor handoff; local server and model-suite managers; narration with voice/rate controls; action sounds; notifications; schedules and external settings; documentation and changelog; front-screen version and build provenance. Detailed implementation and per-surface acceptance remain pending. These utility destinations must use tailored workflows, not generic command forms, and never displace the terrain workspace.
