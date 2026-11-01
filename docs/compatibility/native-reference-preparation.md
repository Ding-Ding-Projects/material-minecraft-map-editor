# Prepare native rendering references

The experimental native terrain profile requires exact vanilla Java 1.20.1
reports and two small reviewed metadata records. Reference preparation is
separate from world compatibility, renderer acceptance and world saving.

## Prepare an explicitly selected directory

Obtain the official reports through a separately reviewed acquisition process.
The selected report directory must contain `blocks.json` and `registries.json`
matching the hashes in `java-reference-evidence.json`. This command does not
download archives, execute a generator, accept a licence or start a server:

```powershell
python scripts/prepare_native_references.py --reports "D:/SelectedReports" --destination "D:/NewReferenceProfile"
```

The destination's parent must already exist. The destination itself must not
exist, including an empty directory. A successful result reports `prepared`,
profile `vanilla-java-1.20.1`, four verified files and 5,300,402 verified bytes.
It explicitly reports that downloading, generator execution and world
compatibility verification did not occur.

The resulting layout is:

```text
NewReferenceProfile/
  reports/
    blocks.json
    registries.json
  registry-source-receipt.json
  java-geometry-reference-evidence.json
```

The two metadata records come from the reviewed source files beside this
article. Their LF line endings are pinned through `.gitattributes`; the helper
never normalizes untrusted inputs. The producer receipt describes the original
observed generation, not a later user's execution. No official report or archive
assets are bundled in the repository.

## Preservation and incomplete results

Every input is checked before creating output. Reads require a regular,
non-reparse file, exact size, stable observed identity and SHA-256. Output uses
exclusive directory/file creation, flushes and synchronizes each file, then
validates its bytes again. Existing caller content is never overwritten.

These operations assume explicitly selected, stable, caller-controlled
ancestors. They are not a hostile-path sandbox, a live-source snapshot,
an atomic directory transaction or complete crash-durability proof.

| Reason | Result and recovery |
| --- | --- |
| `destination_exists` | Existing content remains untouched. Select a new destination. |
| `directory_not_regular` | Select a regular directory rather than a link/reparse entry. |
| `reference_type_or_size_mismatch` | No output is created. Recheck the selected input and exact profile. |
| `reference_hash_mismatch` | No output is created. Do not rewrite bytes to force a match. |
| `reference_changed` | The input changed during validation. Retry only after obtaining a stable source. |
| `reference_io_unavailable` | Input access was unavailable. Check access without weakening protections. |
| `destination_creation_failed` | Creation failed before the helper established its destination. Existing content is preserved. |
| `incomplete_destination_retained` | Partial newly created output remains for inspection. It is not a prepared profile. Select another destination for a retry. |

Operational errors return bounded codes rather than selected paths or contents.
The helper does not delete partial output or automatically resume it. The runtime
must independently validate the complete selected profile before advertising
geometry capability; the helper's success is not a substitute for that check.

## Generate the reports through the pinned data entrypoint

When the reports are not already available, the separate generation command
uses an explicitly selected trusted Java 17.0.19 runtime and the exact official
1.20.1 server archive. The archive can first be acquired and verified through
`python scripts/java_reference.py --manifest docs/compatibility/java-releases.json`.
That acquisition command retains binaries only in its verified ignored cache.

```powershell
python scripts/generate_native_references.py --java "D:/TrustedJava/bin/java.exe" --server-archive "D:/VerifiedArchives/server.jar" --work-directory "D:/NewGenerationWork" --destination "D:/NewReferenceProfile"
```

All four paths must be absolute. Work and destination directories must be new,
nonoverlapping directories under existing stable parents. The helper verifies
the archive before creation, copies it into owned work, checks the Java version,
and invokes only `net.minecraft.data.Main` with `--reports`. It does not start
a server, generate a world or accept an EULA. It does not install Java or
download anything itself. Missing supported tooling remains an incomplete
result, not an automatic-installation claim.

The version probe has a ten-second deadline and generation has a 120-second
deadline. Each retained log is capped at 2 MiB. Java option-injection variables
and unrelated environment values are excluded. Normal timeout, excess output
and cancellation stop the owned direct child and wait for exit; unavailable
exit/output confirmation remains a non-success result. This is not a process-
tree sandbox and requires the explicitly trusted runtime and pinned archive.

Generation work and logs remain available on failure. `generation-receipt.json`
records the newly observed arguments, exit and log hash. A separate
`preparation-receipt.json` records successful report verification/preparation;
the earlier execution record is never rewritten to manufacture a completed
state. The profile's original producer receipt is still the original attestation,
not a renamed receipt for this new run. No file is overwritten or automatically
removed to retry; choose new work/output directories.

## Verification and current delivery state

Eleven focused tests cover source preservation, exclusive output, corrupt and
short input, partial-output retention, exact metadata pins and path-free errors.
An actual pinned local report pair was prepared and all four outputs read back
successfully. Independent review accepted the stated stable-directory boundary.

Nine additional orchestration tests cover a real child's bounded output and
timeout, environment selection, existing destinations, invalid archive identity,
generator failure and separate receipts. All twenty combined checks passed.
The actual pinned Java data-generator route also completed on the current
Windows host; its newly produced profile passed both explicit engine reference
tests. Actual generator cancellation, fresh-machine tooling installation,
broader platforms and complete crash recovery remain unverified.

The native reference-selection and terrain-session implementation is still in
progress. The approved design lives in
[`terrain-workspace.md`](../../design/native-rebuild/terrain-workspace.md).
No completed 3D renderer, material behavior, editing or save acceptance follows
from preparing these files.

Related: [compatibility target](README.md),
[registry producer receipt](java-1201-registry-producer-receipt.json),
[geometry provenance](java-geometry-reference-evidence.json).
