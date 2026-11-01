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

## Verification and current delivery state

Eleven focused tests cover source preservation, exclusive output, corrupt and
short input, partial-output retention, exact metadata pins and path-free errors.
An actual pinned local report pair was prepared and all four outputs read back
successfully. Independent review accepted the stated stable-directory boundary.

The native reference-selection and terrain-session implementation is still in
progress. The approved design lives in
[`terrain-workspace.md`](../../design/native-rebuild/terrain-workspace.md).
No completed 3D renderer, material behavior, editing or save acceptance follows
from preparing these files.

Related: [compatibility target](README.md),
[registry producer receipt](java-1201-registry-producer-receipt.json),
[geometry provenance](java-geometry-reference-evidence.json).
