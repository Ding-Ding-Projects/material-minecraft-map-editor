# Java world engine foundation

This Rust crate is an independent structural foundation with a read-only process interface and isolated in-memory edit APIs. It does not import or invoke Amulet packages. It does not yet replace the existing editor backend.

## Current behavior

- All twelve Java NBT payload types with big-endian reading and writing. Compound ordering, duplicate names, string bytes (including modified UTF-8), unknown application fields and floating-point bit patterns survive round trips. Unknown tag type IDs are rejected because their payload lengths cannot be determined safely.
- NBT defaults: 64 MiB input/output, depth 64, one million aggregate element budget. Negative lengths, invalid list types, truncation and trailing bytes are rejected. Strings remain bytes rather than incorrectly interpreting modified UTF-8 as standard UTF-8; text decoding is not provided yet.
- Region header validation checks sector alignment, bounds, reserved header sectors, missing-location consistency and overlapping allocations. Indexed chunk reading checks declared length, compression and bounded NBT. Compression 1 (gzip), 2 (zlib) and 3 (uncompressed) are supported. External `.mcc` streams and compression 4 (LZ4) are explicitly unsupported. Region serialization is available only as a new in-memory byte buffer; no filesystem save operation is available.
- `level.dat` probe accepts gzip NBT, requires one compound `Data` and reports optional integer `DataVersion`. The probe reads at most 64 MiB compressed and decompressed. It does not claim that a structurally readable world is semantically supported for editing. It performs no world writes and returns no world names or filesystem paths.

## Protocol version 1

The executable reads binary stdin and writes only framed responses to binary stdout. Each frame starts with a four-byte unsigned big-endian byte length followed by UTF-8 JSON. Request frame size is 1 through 1,048,576 bytes. EOF between frames ends normally. Partial or oversized frames terminate with nonzero status and a generic stderr diagnostic. Invalid JSON receives a framed error with null id and permits another request. Requests are processed serially.

Request fields: `version: 1`, `id` (integer or string up to 128 UTF-8 bytes), `method`, optional `params`. Responses carry `version`, the unchanged `id`, and either `result` or `error` containing `code` and `message`. Unsupported methods return `method_not_found`; the engine never pretends that edits happened.

- `engine.info`: returns version, all four methods, format scope and `editingSupported: false`.
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

## Read-only dimension and chunk protocol

`world.dimensions` takes `params.path` and discovers existing dimension storage with a `region` directory. Standard identifiers map to the selected world root (`minecraft:overworld`), `DIM-1` (`minecraft:the_nether`) and `DIM1` (`minecraft:the_end`). Custom identifiers map under `dimensions/<namespace>/<path>`. Discovery returns sorted identifiers and read-only state, never filesystem paths. Empty dimensions without region storage are not listed. Custom traversal is limited to 4,096 entries, 64 dimensions and nine identifier components including namespace. Standard storage subtrees (`region`, `entities`, `poi`, `data`) below a custom dimension are not interpreted as nested dimension identifiers. Unknown, duplicate or cyclic mappings fail explicitly.

`world.chunk_summary` requires `params.path`, a discovered `params.dimension`, and signed 32-bit `params.chunkX` / `params.chunkZ`. Identifiers use lowercase ASCII resource components; absolute paths, backslashes, empty components, `.` and `..` are rejected. Regions use Euclidean floor division and remainder: chunk `(-1,-1)` maps to `r.-1.-1.mca` at header index 1023; `(32,32)` maps to `r.1.1.mca` at index 0. The stored chunk coordinates must match the requested coordinates.

Each existing dimension, region directory and region file resolves through canonical child containment before access. Symlinks and junctions that resolve outside the owning parent are rejected. The selected world root itself is resolved to its canonical target. This is a local read interface, not a sandbox for a hostile process concurrently replacing paths: it does not provide handle-bound race-proof containment, filesystem locking or coherent snapshots of an actively changing world. Use an owner-controlled stable snapshot until those capabilities exist. No files in a world are created or changed.

Region files must be regular files and at most 256 MiB, checked both before and during bounded reading. Existing region allocation, compression, NBT and finite semantic DataVersion checks apply. A missing region file or unallocated requested chunk returns `available: false`, with no fabricated block data. An undiscovered dimension, malformed file, unsupported version or inconsistent coordinates returns a fixed structured error without operating-system diagnostics or filesystem paths.

Available results contain actual section Y, minimum block Y, and all 4,096 block entries per section in `y-z-x` order. Numeric sections return `[numericId, metadata]` pairs. Palette sections return decoded names/properties plus exact palette indices. These are read-only observations; names are not registry-validated, missing sections are not synthesized, and lighting/biomes/mesh generation remain unavailable. The original parsed NBT is retained unmodified for semantic inspection but is not echoed over the protocol.

Response frames are capped at the same 1 MiB as requests. Oversized successful results become `response_too_large` errors rather than being truncated. Invalid request ids return null ids, preventing oversized invalid-id error echoes. There is no pagination or streaming response protocol yet.

Synthetic filesystem fixtures write real zlib `.mca` records and verify negative coordinates, 31/32 boundaries, nested custom discovery, missing regions/chunks, malformed region data, unknown versions, mismatched stored coordinates, region byte limits and response bounds. Canonical parent escape and a real outside junction were rejected on the current Windows test host. Unix symlink coverage is present but was not executed on this host. These tests do not constitute a real user-world or all-version acceptance corpus.

Before opening a region path, metadata must identify a regular file within the byte budget. Open-handle metadata is then checked again. This rejects static directories and special files before a potentially blocking open; it does not remove the documented concurrent path-replacement race. A nonregular-directory fixture passed on the current Windows host. No FIFO open or Unix runtime proof was attempted.

## Isolated in-memory editing foundation

The process protocol remains read-only and continues to report `editingSupported: false`. The following library APIs construct new memory values only. They do not open source files, save worlds, acquire world locks or perform atomic transactions.

`Region::rebuild(&[RegionEdit], Limits)` produces a separate region byte buffer. Each edit explicitly supplies a chunk index, new named NBT root and timestamp. Invalid indices and duplicate edits fail. Unchanged allocated sectors, including their exact compressed/opaque bytes and sector padding, and timestamps are preserved byte-for-byte. Allocations may move within the new buffer. Timestamp entries for unallocated chunks are retained. Empty or semantically identical edits with matching timestamps return the complete original bytes, including free sectors. A nontrivial rebuild does not retain unallocated free-sector contents.

Changed chunks use zlib with bounded output. The NBT limits apply before compression; a chunk may occupy at most 255 sectors, and the new region is capped at 256 MiB. Rebuilt allocation headers are reparsed before returning. Unsupported unchanged compression payloads are copied opaquely, never interpreted or rewritten. There is no deletion API, external-stream writer, timestamp inference or source filesystem mutation.

`edit::replace_section_blocks` takes a named chunk root, a signed section Y and at most 4,096 explicit local block replacements. It admits only DataVersion `3465` for this initial fixture-bound vertical slice. Missing sections, malformed source palettes, duplicate positions, invalid local coordinates, unsupported versions and palette capacity overflow fail without altering the input. Replacement state names/properties receive bounded structural validation; there is no version-specific block registry or proof that an arbitrary named state exists in the game.

The edit operates on cloned NBT. Existing palette entries retain their original unknown fields and ordering. New states append to the palette; padded words are re-encoded for the resulting bit width, including singleton-to-two and sixteen-to-seventeen transitions. The palette is bounded at 4,096 entries and is not compacted to rescue an overflowing append. No-op edits retain complete NBT byte identity. Entities, biomes, lighting, unknown fields and other sections remain unchanged.

An actual state change returns `changed_blocks`, `relighting_required: true` and `derived_data_stale: true`. Lighting, heightmaps, block entities, scheduled ticks, structures, POIs and other dependent data are not repaired or validated. Unchanged block-entity data can be incompatible with the replacement block. These outputs are incomplete edit candidates, not valid finished world saves. No-op results set both flags false. No world-save protocol method is exposed until the missing consistency, relighting, transaction, backup/recovery and real-world validation work is implemented.

Focused tests prove no-op region/NBT byte identity, unchanged chunk bytes/timestamps (including opaque payloads), changed readback, bounded incompressible encoding, negative section Y, property/unknown-data preservation, palette growth and capacity, malformed arrays, unsupported versions and invalid/duplicate selections. All edit fixtures are in memory; no user world was touched. Real-world DataVersion `3465` editing acceptance remains unverified.

## Official reference metadata acquisition

The standard-library helper `scripts/java_reference.py --manifest <frozen-manifest.json>` is a read-only reference acquisition tool for the selected `1.20.1` release. It verifies the frozen manifest's metadata SHA-1 before trusting download fields, then verifies the official server's exact declared size and SHA-1 and records SHA-256. HTTPS hosts are explicitly allowlisted, redirect targets and final destinations are validated, and downloads have byte and time limits. Cached bytes are hash-verified before reuse; an invalid cache fails rather than repeatedly downloading unchanged inputs.

Binary and receipt storage is restricted to the ignored `build/java-reference/1.20.1` cache after `git check-ignore` proof. Redirected cache ancestors, symlink targets, multiply linked files and nonregular destinations are rejected. These path checks do not provide race-proof protection against a hostile concurrent local writer. The helper never executes Java, starts a server, accepts an EULA, reads a user world, extracts classes or publishes a binary. Downloaded archives are not source deliverables.

Inspection reads exact `version.json` metadata, or a bounded `META-INF/versions.list` and SHA-256-verified nested archive. JSON identity and integer `world_version` are validated. ZIP directory/member counts and byte limits apply; split and ZIP64 archives are explicitly unsupported. A successful receipt proves the version metadata's provenance only. It does not supply a generated world fixture, runtime acceptance, complete format support or editing correctness.

## Stable-snapshot working-copy library

`working_copy::build(source, destination, limits, observer)` copies a caller-selected stable world snapshot into a new working directory. It is not exposed over the process protocol or GUI. The source is opened for reading only; the builder never modifies source bytes, removes caller paths or overwrites an existing destination. Unknown regular files and empty directories are retained with exact default-stream bytes. It validates both source and copied `level.dat` using bounded gzip/NBT inspection.

The destination parent must already exist. Source/destination overlap and nested destinations are rejected before staging. Source root and descendant links, Windows reparse/junction entries, hard-linked files and nonregular entries are rejected. Canonical child containment and opened-file identity checks apply. Paths require lossless Unicode representation. These checks assume stable caller-controlled ancestors and staging: they are not a sandbox against a hostile process replacing ancestor paths concurrently.

Defaults bound the complete inventory (including root and directories) to 10,000 entries, depth 64, 8 GiB per file and 64 GiB total. Explicit limits have hard ceilings of 100,000 entries, depth 128, 512 GiB per file and 1 TiB total. An additional conservative 4 MiB inventory-cost budget bounds recovery-record construction, and each recovery JSON is capped at 8 MiB. Regular-file data streams in 64 KiB blocks. SHA-256 is computed while copying, then source and staged contents are independently rehashed. Repeated inventories compare relative paths, file kinds, lengths, modification times and platform identities; observed additions, removals, replacements and content changes prevent publication.

A fresh owned `.world-copy-*` staging directory is created beside the destination, with copied files under `payload/`. Create-new numbered recovery records retain completed-file sizes/hashes and the current state without overwriting earlier records. They contain local source/destination paths and belong with the local recovery data, not in published evidence. Cancellation and failure retain owned staging, complete prior records and any partial payload. No automatic deletion, rollback or resume is performed. A failed recovery-record write is reported explicitly; earlier complete records remain. Successful publication retains the staging shell and records, with payload moved to the destination. If only the final post-publication record fails, the receipt reports that fact without falsely claiming publication failed.

Publication uses a same-parent native no-replace rename. Windows calls `MoveFileExW` with flags zero, omitting replacement and cross-volume-copy options; Linux uses `renameat2(RENAME_NOREPLACE)`. There is no check-then-overwriting-rename fallback. A destination created during copying or verification remains untouched, including an empty directory. Unavailable kernel/filesystem support produces a retained-stage failure. Windows native behavior is covered on the current host; the Linux route and Unix symlink/nonregular fixtures remain unrun here. Reference semantics: [MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw) and [renameat2](https://man7.org/linux/man-pages/man2/rename.2.html).

The observer can cancel after inventory, during each copied or verified block, after completed files and before publication verification. It must not mutate source or staging. Filesystem calls, initial bounded level validation and inventory traversal are synchronous; cancellation is not a guarantee of interrupting a blocked operating-system call. Tests deliberately mutate owned fixtures through observers to verify change detection and publication races.

This is not atomic consistency for a live running world. Source changes after the last observation cannot be excluded without locking or an actual snapshot provider. Permissions, timestamps, alternate data streams, extended attributes, sparse allocation and filesystem metadata are not preserved as a backup format. File sync and native rename do not establish a complete power-loss/directory-durability contract. Automatic resume, journal validation, retention policy, free-space reservation, source locking, concurrent-writer isolation, integration with edits and crash recovery remain unfinished. No user world was used for acceptance.

Current-host fixtures cover exact unknown bytes and empty directories, existing and nested destinations, hard links and a real junction, all inventory bounds, malformed level metadata, source changes with restored modification time, partial-copy and verification cancellation, unexpected staging data, retained recovery records and native destination races for both files and empty directories.
