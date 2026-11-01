# Dimension and chunk inspection increment

Status: proposed design contract, awaiting independent review and implementation authorization. Baseline `b1e48b9d1961f09d790de7432f096816b6f00f17`. Source facts were read from `engine/src/protocol.rs`, `engine/src/world_read.rs` and `engine/src/chunk.rs`. This increment advances real world exploration; it does not replace the full objective of a 3D terrain editor with editing and transactional saving.

## Product and layout

Retain the verified frameless PySide6 Qt Quick shell, bounded header/footer, theme preferences, accessible text size and orderly shutdown. After a successful real world probe, the workspace shows a dimension navigator on the left, a central horizontal chunk slice and a block inspector on the right. Do not turn the screen into cards, a command catalogue or an image of invented terrain. The slice is a literal 16 × 16 data view at one Y coordinate, clearly labelled **Chunk slice, read-only**. No brush, fill, Apply or Save action is enabled or presented as working.

Normal client size is 1600 × 900 logical units; minimum is 1280 × 720. Keep the repaired header/action bounds. Left navigator: 240 units; inspector: 280 units; gutters: 16 units; central area takes the remainder. At minimum size or enlarged text, the inspector becomes a user-opened side sheet, with selected-block coordinates and an Inspect block action retained beside the slice. Do not shrink controls or identifiers to preserve three columns. Slice rendering can pan/scroll at user-selected zoom. Zoom changes cell geometry only, never data or world coordinates. No automatic camera movement is implied.

The top contextual row contains labelled Chunk X and Chunk Z fields and a **Read chunk** action. Below it are an actual section selector, a labelled local Y control and the derived exact world Y. The data view has X across columns increasing rightward and Z down rows increasing downward, both labelled 0…15 locally. A selected cell has a strong outline and row/column markers, not color alone. Block-state colors are deterministic categorical data encodings with a legend, explicitly **Block categories, not textures**. They do not imply official textures, lighting, biome colors or 3D geometry.

## Actual protocol contract

The engine handshake must advertise both methods before the UI enables their actions. Existing version-1 envelope framing and 1,048,576-byte response limit remain unchanged.

| Method | Request parameters | Actual successful result |
| --- | --- | --- |
| `world.dimensions` | `path` | `dimensions: [{id, readOnly: true}], readOnly: true` |
| `world.chunk_summary` | `path`, discovered `dimension`, signed 32-bit `chunkX`, `chunkZ` | Absent: requested identity, `available: false`, `readOnly: true`. Present: same identity, `available: true`, `readOnly: true`, `editingSupported: false`, `dataVersion`, `blockOrder: "y-z-x"`, `sections` |

Each section contains `sectionY`, `minimumBlockY` and `blocks`. A palette section has `kind: "palette"`, `palette: [{name, properties}]` and exactly 4096 `indices`. A numeric section has `kind: "numeric"` and exactly 4096 `[blockId, metadata]` pairs in `blocks`. Numeric values are raw version-specific identifiers, not modern names. Do not invent a registry mapping or silently label numeric zero as air.

Dimension discovery returns only dimensions whose actual region directories were discovered. It is not a complete declaration of every dimension a world might support. The UI preserves exact returned identifiers, including custom namespaces, and never fabricates Overworld/Nether/End entries. Empty discovery says **No region-backed dimensions found**. It never creates a directory. Discovery limits of 64 dimensions, 4096 visited entries and bounded directory depth are engine constraints; a limit failure is not an empty list.

## User actions and validation

1. **Discover dimensions:** run after a successful world probe. Validate the returned envelope and read-only flag; require an array with unique nonempty string identifiers and correct per-entry flags. Invalid or incomplete payloads do not populate the navigator.
2. **Choose dimension:** select only a returned identifier. Clear the previous chunk, slice and inspector immediately. Keep the user's coordinate draft, but require a new Read chunk action. Do not silently issue repeated reads while moving keyboard focus through the list.
3. **Enter chunk coordinates:** separate signed integer fields accept decimal `-2147483648` through `2147483647`; reject fractions, exponents, overflow and empty values. A temporary minus sign remains editable but disables Read chunk. Validate before dispatch, never clamp silently. Label these as chunk coordinates, not block coordinates. Initial drafts may be explicit `0`, but no data is loaded until requested. Clear controls produce empty validation states. Each field has local guidance and a labelled clear control.
4. **Read chunk:** freeze the validated dimension/X/Z tuple into the request identity. Display real indeterminate progress with Cancel. A result must echo that tuple exactly. A missing chunk clears the slice and shows **Chunk not stored at these coordinates**. It never draws 256 air cells.
5. **Choose section:** list only returned sections, sorted by numeric `sectionY`, displaying their exact inclusive world-Y interval `minimumBlockY…minimumBlockY + 15`. Require unique signed integer section values and consistency `minimumBlockY == sectionY * 16`. A present chunk with no returned sections has an explicit **No decoded sections available** state. Do not insert missing vertical sections or infer their contents. On first successful read, explicitly select the lowest returned section and local Y 0; keep neither from an unrelated prior request.
6. **Choose local Y:** integer 0…15 only. This selects a slice from the already validated section, with no extra engine request. World Y is `minimumBlockY + localY`. Typed input, stepper and keyboard alternatives remain synchronized.
7. **Select cell:** click or use arrow keys within the 16 × 16 data view. Home/End moves to row edges; Ctrl+Home/Ctrl+End moves to the first/last cell; Enter focuses the block inspector; Escape returns focus to the slice. Keep one roving focus target, rather than forcing 256 Tab presses. A coordinate-based local X/Z picker provides an equivalent nonvisual selection path.
8. **Inspect block:** show exact local X/Y/Z, world X/Y/Z, dimension, chunk coordinates and data version. Palette states show the exact name and property pairs; numeric states show block ID and metadata separately. Empty properties say **No properties recorded**. No entity, biome, lighting or registry-compatibility claim is inferred from these fields.

## Slice decoding and data integrity

The indexing formula is `localY * 256 + localZ * 16 + localX`, with all three local coordinates 0…15. World block X/Z are `chunkX * 16 + localX` and `chunkZ * 16 + localZ`. Compute with exact integer arithmetic and expose large coordinates without a signed-32-bit intermediate; the protocol's extreme chunk coordinates can exceed 32-bit block coordinates. Python integer models are the source of truth; QML displays provided decimal strings.

Validate the entire chunk before displaying any slice. Reject wrong read-only/editing flags, wrong `blockOrder`, wrong echoed tuple, duplicate sections, wrong array lengths, noninteger/bool indices, out-of-range palette indices, malformed name/property values, invalid numeric pairs or unsupported block kinds. Numeric IDs must be integers 0…4095 and metadata 0…15. Palette properties are an array of two-string pairs, serialized from `Vec<(String, String)>` in `chunk.rs`; validate that shape and verify it against a real protocol fixture. Do not reinterpret a JSON object as that ordered pair list. Preserve exact identifiers and property values as plain text, never rich-text markup.

A response that fails validation is unsupported/unavailable, not a partly rendered slice. Missing sections, missing region files, failed decompression, unknown data versions, unsupported encodings and corrupt arrays never become default air. Block category colors are derived only after successful validation and are supplemented by exact text and selection markers. A finite engine allowlist is not proof of all stable Java-version support.

## Request ownership, cancellation and errors

Retain the tested one-owned-child lifecycle, 30-second deadline, bounded buffers, diagnostic budget and explicit root → QML engine → backend destruction. Extend the request identity to world identity, generation, method, dimension and chunk tuple where applicable. World changes, dimension changes, new reads and cancellation invalidate earlier generations before updating the UI. Late replies cannot populate an old world, dimension or coordinate selection.

Only one active request chain owns progress. A new request safely stops the old child before launching the next. Section/local-Y/cell changes operate on validated local data and do not spawn engine processes. Cancel remains **Cancel requested** until the child actually stops. Closing uses the existing acknowledged stop route. Do not shorten those semantics to make the new panel feel faster.

| State | Visible result and allowed recovery |
| --- | --- |
| Dimensions loading | Indeterminate progress and Cancel; previous world data unavailable |
| No dimensions | Factual empty state; choose another world or retry discovery |
| Coordinate invalid | Field-specific explanation; Read chunk disabled; no request sent |
| Chunk loading | Requested dimension and X/Z remain visible; Cancel available; stale slice cleared |
| Chunk absent | Exact requested tuple and absence explanation; edit coordinates and retry |
| No decoded sections | Present chunk identity retained; slice unavailable; no inferred air |
| Slice ready | Validated 256 cells and exact selected-block facts; read-only status visible |
| Unsupported/corrupt | Actual bounded error code/message as plain text; retry only on explicit action |
| Response too large | `response_too_large` shown as **Chunk response exceeds the supported transport limit**; no truncated rendering or automatic retry loop; smaller-response engine work remains a separate prerequisite |
| Canceled/timed out | Exact terminal state; prior data not restored as current; safe retry remains explicit |

## Components, accessibility and module boundaries

Use the existing registered Material Design 3 title bar/buttons and add explicit registrations for outlined numeric fields with help/clear, dimension/section selection, local-Y control, contextual side sheet, progress and the block inspector. Exact Qt source/license receipts and real rendered audit remain necessary; recolored generic widgets do not establish conformance. The slice is a native data visualization, not chrome, and has a textual accessible equivalent.

Every selector's popup owns a local plain-text filter and adjacent independent regex-builder entry; pending full regex parity must be reported honestly, never implied by a tiny tester or inert button. No filtering mutates world data. Preserve all existing product-wide obligations and their unfinished inventory; this bounded increment is not permission to declare those obligations satisfied.

Keep the bridge/process lifecycle separate from chunk validation/slicing models. Put pure parsing/validation/indexing into a focused module with no Qt dependency. Put the dimension controls, slice view and block inspector into separate QML components. Avoid enlarging `Main.qml` into a mixed-responsibility file. Do not change engine protocol/source in this GUI lane.

## Verification before acceptance

- Independent review of this contract precedes implementation.
- Pure model tests cover palette and numeric sections, all local-index axes, negative chunk/section coordinates, signed-32-bit chunk extremes, malformed arrays and every missing/unsupported distinction.
- Real framed-engine fixture tests prove dimension discovery, present/absent chunks and both returned block representations; all input world files remain byte-identical.
- Lifecycle tests prove stale world/dimension/chunk results cannot land, cancellation is acknowledged, oversized responses remain bounded and close waits for owned teardown.
- Real hidden runtime interaction proves selection, numeric validation, section/local-Y changes, keyboard cell navigation and exact inspector values against independently decoded fixture expectations.
- Inspect normal 1600×900 and minimum 1280×720 logical sizes at DPI 144 for the first integration evidence, both themes and enlarged text. The full language/scale matrix remains pending until those modes exist; do not substitute these initial tuples for complete acceptance.
- Runtime logs remain empty through close. Preserve source/binary hashes, exact fixture identity, geometry and screenshots, without user paths/data in public evidence.

No implementation, screenshot, compatibility expansion, editing capability or release is claimed by this contract.
