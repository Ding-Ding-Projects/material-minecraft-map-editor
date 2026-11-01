# Java world engine foundation

This Rust crate is an independent, read-only structural foundation. It does not import or invoke Amulet packages. It does not yet replace the existing editor backend.

## Current behavior

- All twelve Java NBT payload types with big-endian reading and writing. Compound ordering, duplicate names, string bytes (including modified UTF-8), unknown application fields and floating-point bit patterns survive round trips. Unknown tag type IDs are rejected because their payload lengths cannot be determined safely.
- NBT defaults: 64 MiB input/output, depth 64, one million aggregate element budget. Negative lengths, invalid list types, truncation and trailing bytes are rejected. Strings remain bytes rather than incorrectly interpreting modified UTF-8 as standard UTF-8; text decoding is not provided yet.
- Region header validation checks sector alignment, bounds, reserved header sectors, missing-location consistency and overlapping allocations. Indexed chunk reading checks declared length, compression and bounded NBT. Compression 1 (gzip), 2 (zlib) and 3 (uncompressed) are supported. External `.mcc` streams and compression 4 (LZ4) are explicitly unsupported. No region writes are available.
- `level.dat` probe accepts gzip NBT, requires one compound `Data` and reports optional integer `DataVersion`. The probe reads at most 64 MiB compressed and decompressed. It does not claim that a structurally readable world is semantically supported for editing. It performs no world writes and returns no world names or filesystem paths.

## Protocol version 1

The executable reads binary stdin and writes only framed responses to binary stdout. Each frame starts with a four-byte unsigned big-endian byte length followed by UTF-8 JSON. Request frame size is 1 through 1,048,576 bytes. EOF between frames ends normally. Partial or oversized frames terminate with nonzero status and a generic stderr diagnostic. Invalid JSON receives a framed error with null id and permits another request. Requests are processed serially.

Request fields: `version: 1`, `id` (integer or string up to 128 UTF-8 bytes), `method`, optional `params`. Responses carry `version`, the unchanged `id`, and either `result` or `error` containing `code` and `message`. Unsupported methods return `method_not_found`; the engine never pretends that edits happened.

- `engine.info`: returns version, methods, format scope and `editingSupported: false`.
- `world.probe`: requires `params.path` with the local Java world directory. Paths are caller-supplied local read authority, not an authentication boundary. Only `level.dat` is opened. Error responses use fixed messages, never OS diagnostics or paths.

The process bridge must remain local and must not expose this protocol to untrusted network clients. Host permission handling, request cancellation and concurrency are not implemented.

## Verification and next slices

Focused development verification: `cargo test --locked --manifest-path engine/Cargo.toml`. This does not stand in for root build entrypoint, installer, installed runtime or GUI acceptance. `Cargo.lock` fixes the complete resolved dependency graph.

Remaining work includes a representative real-world fixture corpus for every stable Java version from 1.12 onward, modified UTF-8 text views, semantic version adapters, block-state palettes and packed arrays, dimensions and chunk coordinate mapping, entities and block entities, modern external/LZ4 chunk streams, world locking and coherent snapshots, atomic region/world transactions, backup and recovery, selection and edit operations, migration, cancellation, bridge integration and packaged delivery. There is no all-version editing support claim in this foundation. No user world was modified for these tests.

## Read-only semantic views

`mutf8::decode_units` validates Java modified UTF-8 and returns UTF-16 code units, preserving isolated surrogates. `mutf8::decode` returns Unicode text only when surrogate pairs are valid; malformed encodings, literal zero bytes, standard four-byte UTF-8 and overlong non-null sequences are rejected. `encode_units` provides the inverse unit representation. Original NBT strings remain byte-exact.

`chunk::summarize(&NamedTag)` borrows the original NBT and returns chunk X/Z, DataVersion, sorted section Y coordinates and decoded block views. Local block index is `y * 256 + z * 16 + x`; all local coordinates are 0 through 15. Section Y is signed, and world Y is `section_y * 16 + local_y`, using checked arithmetic. Chunk X/Z are chunk coordinates, not block coordinates. Missing sections remain absent and are not synthesized as air. Unknown tags remain in the borrowed raw tree.

The initial, deliberately finite dispatch allowlist is:

| DataVersion | Section representation |
| --- | --- |
| 1343 | `Level.Sections`, numeric `Blocks`, `Data`, optional `Add` nibble arrays |
| 1631, 1976, 2230 | `Level.Sections`, `Palette` and continuous `BlockStates` |
| 2586, 2730 | `Level.Sections`, `Palette` and padded `BlockStates` |
| 2975, 3337, 3465 | root `sections`, nested `block_states.palette/data`, padded words |

This is structural dispatch with synthetic fixture coverage, not real-world acceptance or a promise that every chunk in those versions is supported. Other DataVersion values fail explicitly. Sections without block data (including modern light-only sections) currently fail instead of implying block contents. Historical empty palettes or omitted legacy packed arrays are not accepted. A modern one-entry palette may omit `data`; present arrays must have the exact expected length. Block names are retained text, not resolved against a version-specific registry. Numeric ids are not translated to modern names. Palette entries and properties are views, not a validated registry schema. Biomes, lighting, status, heightmaps, ticks, structures, entities and block entities remain raw-only.

Semantic tests cover continuous cross-word and padded word boundaries at five bits, first/final indices, palette overflow, truncated arrays, malformed numeric arrays, property views, duplicate semantic fields, unknown versions, modified UTF-8 null/BMP/supplementary text, isolated surrogates and negative section Y. Full real-world version fixtures and registry validation are still required before declaring semantic compatibility.

Region allocation metadata is exposed through a shared read-only `locations()` view. Chunk reads also recheck checked allocation ranges before slicing. A regression deliberately corrupts internal metadata and requires an error rather than a panic; a compile-fail documentation test proves external code cannot replace allocations.

Semantic block states are limited to 64 properties each (`MAX_STATE_PROPERTIES`). Larger compounds produce `block property budget exceeded` before decoding keys or allocating the membership table. This is a conservative resource boundary, not a registry completeness claim; the raw NBT remains unchanged and accessible. Duplicate detection uses a randomized `HashSet` while the returned property vector preserves source order. The former linear search per property required `n*(n-1)/2` comparisons for distinct names (4,999,950,000 at 100,000 entries). A bounded 65-entry negative fixture was observed failing before the repair; regression coverage proves 64-entry acceptance/order, 65-entry rejection and duplicate rejection.
