# Exports

Anything Amulet Studio can show, it can write out. A surface that renders data
and offers no way out of it is incomplete, and "you can copy it off the screen"
is not an export.

## Behaviour

**What can be exported.** Analysis results, block and biome histograms, entity
and loot audits, selection metadata, the notification history, the changelog,
the local version history, appearance presets, feature articles from the Memory
Console, and structure data from the selection.

**Which formats.** The choice is per datum rather than per application, so a
format that would silently drop a field is not offered for that datum:

| Shape of the data | Formats offered |
| --- | --- |
| Tabular results | CSV, TSV |
| Structured records | JSON, YAML, TOML, XML |
| Prose and articles | Markdown, plain text, HTML |
| Structures | `.construction`, `.mcstructure`, `.schematic`, `.schem` |

Every export states its encoding — UTF-8 unless there is a reason — its line
endings, and the schema or version it follows, so the file is readable by
something other than the application that wrote it. Where a round trip is
possible, the export is re-importable.

**Where it goes.** A path field with a native browse control beside the free-text
entry. A typed path and a browsed path run through exactly the same validation;
a browsed value is never trusted more than a typed one.

**Opening it afterwards.** An export can be opened in Visual Studio Code
directly from the surface that produced it, in one action. A folder opens as a
workspace root rather than as a single file with no context. When no
installation is found, the surface says so and offers the download rather than
opening some other editor the user did not ask for.

**Archives.** Multi-file exports are ZIP or 7z. The 7z path exposes what 7z
actually offers — the compression methods, the levels, dictionary and solid
block sizes, multi-threading, split volumes, and AES-256 with encrypted headers
— rather than one hard-coded default. An archive whose contents are encrypted
but whose filenames are not is never presented as protected.

## Configuration

The last format and the last directory persist per surface. An export honours
whatever filter and search are currently active, so what is written matches what
is on screen; the file states the range it covers.

## Failure modes

Where a format genuinely cannot carry something, the surface says what will be
lost **before** the export runs rather than truncating quietly.

A path that cannot be written is reported with the reason. A partially written
file is removed rather than left as a plausible-looking truncated export.

A long export reports progress, stays cancellable, and reports partial results
honestly instead of claiming a whole export succeeded when part of it did not.

## Security and accessibility

Exports go to a local path the user chose and are never transmitted. No export
contains a credential, a token, or the School-mode unlock material; presets and
profiles are written without them.

Every export control is keyboard reachable and named, the browse button has its
own accessible name distinct from the field it fills, and the format chooser is
a searchable dropdown like every other dropdown in the shell.

## Verification

```powershell
py -3 -m pytest tests/test_export_actions.py tests/test_external_editor.py tests/test_notifications.py -q
```

Those cover the shared export action, the Visual Studio Code bridge including
the unavailable and launch-failed paths, and the notification history's own
export.

Suggested articles: [bulk actions](../bulk-actions/README.md),
[external editor](../external-editor/README.md),
[analysis tools](../analysis/README.md), and
[Memory Console](../memory-console/README.md).
