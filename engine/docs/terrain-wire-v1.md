# Terrain wire contract, encoding version 1

These examples are synthetic protocol/codec fixtures, not installed-source or rendering evidence. `terrain-wire-v1-fixtures.json` is generated independently by `../tests/make_terrain_wire_fixtures.py`; Rust checks its positive/negative byte vectors and canonical payload hashes. The fixture files are synthetic NBT/region inputs with symbolic file identity/time evidence. Never use them as default terrain or relabel their stamps as runtime observations.

Runtime startup requires paired explicit `--reference-root <absolute-directory> --reference-profile vanilla-java-1.20.1`. Existing read methods retain their schemas. The new terrain methods require a persistent process session; they are not implemented by the codec alone.

## Fixed request identities

Generation is an integer from 0 through 9,007,199,254,740,991, never boolean. New method ids are exact strings: `terrain:{generation}:begin`, `terrain:{generation}:page:{pageIndex}`, and `terrain:{generation}:end`. Fixed ids make each preadvertised complete page-envelope `encodedBytes` exact. Existing `engine.info` retains its ordinary id route.

Begin parameters are exactly `path`, `worldId`, `dimension`, `generation`, `geometryCapability`, `limitProfile`, `chunkXMin`, `chunkXMax`, `chunkZMin`, `chunkZMax`, `sectionYMin`, `sectionYMax`. The profile is `terrain-small-v1`; geometry capability is `cube-shapes-v1`. Bounds are inclusive, at most three coordinates per axis, with signed 32-bit chunk coordinates and section Y -128 through 127. `worldId` is a caller-owned opaque visible ASCII identity, not a world path.

Page/end parameters repeat the complete identity tuple: `worldId`, `dimension`, `generation`, `sceneId`, `readSetDigest`, `registry`, `geometrySchema`, `geometryCapability`, `shapeEvidenceSha256`. Page adds `pageIndex`; end adds nothing. No path, mesh filename or host command is accepted there.

## Manifest and page records

Result identities contain `schemaVersion: 1`, `readSetEncoding: 1`, the tuple above, and registry `{schemaVersion:1,version:"vanilla-java-1.20.1",sha256:"f10d5da83ec8cd995d4f484b788c5b1467a490728e687c629a681450e3253017"}`. The registry hash identifies the strict blocks report; the fixed profile binds the other report and original attestation pins. Shape evidence hash is `88b22690a55926aa1e6b3cc4a29ca52107a1699983d7a36a504c4d8ef1320a21`.

The manifest adds `bounds` with the same six bound names, `limitProfile`, `readOnly:true`, `editingSupported:false`, `coverage`, `sources`, `pages` and `totals`. Coverage entries contain chunkX/chunkZ/sectionY, availability, nullable dataVersion, decodedCells/cubeCells/airCells/unsupportedCells, and reasonCode. `cube-shapes-v1` admits no air classification: airCells is zero, and unverified air is unsupported. Other versions/numeric encodings initially have unavailable coverage, zero cells and no fabricated named states.

State ids are scene-local integers 0 through 4095. State pages have payload `{states:[...]}`; each entry has stateId, dataVersion, nullable registryStateId, exact name, property-pair array and classification `unitCubeShape` or `unsupported`. Null registryStateId means membership was not verified, never a guessed registry id. Explicitly known propertyless stone/cobblestone require strict membership and shape evidence. Cells payloads contain chunkX/chunkZ/sectionY and exactly 4096 scene-local `stateIds` in y-z-x order. Their recordCount is 4096, not one.

Faces payloads contain `faces` arrays. Each row is exactly `[chunkX,chunkZ,sectionY,localX,localY,localZ,direction,stateId]`. Directions are `xp,xn,yp,yn,zp,zn`. Emit all six for every supported cell, including adjacent supported cells; no neighbor occlusion. Page kinds are ordered states, cells, faces. A state page has at most 16 entries, each state entry at most 4096 encoded bytes. A face page has at most 2048 records; each cells page covers exactly one section.

Each page result adds pageIndex, kind, recordCount, payloadSha256 and payload. Manifest descriptors contain pageIndex, kind, recordCount, encodedBytes and payloadSha256. `encodedBytes` includes the entire version/id/result envelope, without the four-byte transport header. The page itself has no self-referential encodedBytes field. Begin/page envelope caps are 262,144 bytes; complete begin/page/end cap is 64 MiB and at most 1024 pages.

End acknowledges `released:true`, exact `releasedCounts` matching the staged manifest totals, and actual `deliveredPages`. Early cancellation may end before all pages; normal completion requires every advertised page. Ending releases staged data, not a writable world handle. A process accepts at most one successful begin during its lifetime.

## Hash encodings

Read-set bytes exactly follow the approved terrain-workspace encoding: `MWETERRAIN\0READSET\0`, big-endian encoding version 1, dimension, six signed bounds, geometry schema, length-prefixed capability, raw shape hash, registry schema/version/raw hash, sorted complete coverage and sorted source records. UTF-8 strings use big-endian u32 byte lengths; no NUL, rewriting or normalization. Optional fields use one 00/01 tag. Windows identity is scheme 1, u64 volume serial and 16 raw FILE_ID_INFO bytes. The fixtures include full expected byte hex and SHA-256, with independently generated source-file hashes.

Sources contain relativePath, observation (`absent`/`present`), fileIdentity (`null` or `{scheme:1,volumeSerial:u64,fileId:<32 lowercase hex>}`), nullable fileBytes, nullable lastWriteFileTime and nullable contentSha256. Absence requires all optionals null; presence requires all. Paths use `/`, never absolute or traversal paths; duplicate paths or present identities are invalid. Missing files must be rechecked by the reader before snapshot admission. Symbolic fixture identities are deliberately not runtime proof.

Page payload digest is SHA-256 over exact compact sorted-key JSON UTF-8 of `payload` only. Object keys sort lexically; arrays retain order. Use Unicode directly (`ensure_ascii=False`), separators `,`/`:`, required JSON escaping only, no floats or unpaired surrogates. Request ids, generation, worldId, sceneId, camera state and page descriptors do not enter read-set digest; consumers must validate those separate identities even when a digest agrees.
