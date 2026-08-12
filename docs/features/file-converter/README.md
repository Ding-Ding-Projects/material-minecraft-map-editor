# File converter

A guided, entirely local pipeline for converting one standalone file into
another format — a Minecraft structure into type-preserving JSON and back, or
an image between PNG, JPEG, BMP, and GIF. It never trusts a file's extension,
never touches the network, never overwrites the source it was given, and
never offers a target format the build cannot actually produce.

This is a different converter from the world-conversion page reachable from
Backstage ▸ Convert, which merges an *open world's* chunks into another world
through the platform translation layer. The file converter, covered here,
converts a *standalone file* sitting on disk — nothing about it requires a
project to be open.

## Where it lives

Backstage ▸ **File converter** hosts the real panel
(`amulet_map_editor.api.studio.converter_panel.ConverterPanel`) directly. The
panel is built from four modules under
`amulet_map_editor/api/converter/`:

| Module | Responsibility |
| --- | --- |
| `signatures.py` | Bounded byte-signature detection of a file's real format |
| `registry.py` | The documented, fixed list of every adapter this build ships |
| `adapters.py` | Pure `bytes -> bytes` implementations, one per format pair |
| `sandbox.py` | Runs one adapter call in an isolated, bounded child process |
| `core.py` | Orchestrates one conversion or a batch, and records local history |

## Behaviour

**Detection never trusts the extension.** `signatures.detect_format` reads at
most 64 KiB from the front of the file and matches it against real magic
bytes — PNG's `\x89PNG\r\n\x1a\n`, JPEG's `\xff\xd8\xff`, BMP's `BM`, GIF's
`GIF87a`/`GIF89a`, gzip's `\x1f\x8b` (used for compressed NBT structures), and
NBT's own `0x0A` root-compound tag byte. A file that starts with none of these
is reported as **unknown**, not guessed at — the panel then offers no targets
for it at all, and `core.detect_source` performs the same check with a bound
tied to the real file size rather than only the sniff window: a JSON
candidate larger than the read bound is reported unknown rather than trusted
on a partial parse. `core.detect_source` further calls
`signatures.detect_format_full`, which — for a file that merely opens with `{`
or `[` — actually parses the complete JSON rather than trusting the opening
brace, so a truncated or malformed document is correctly reported unknown
instead of accepted as JSON.

**Only real adapters are offered.** `registry.adapters_for_source` filters the
fixed `ADAPTERS` tuple down to whatever the detected format allows, and the
panel builds its "Convert to" list from exactly that filtered set — never
every format the build knows how to produce in general. Choosing a source
file whose bytes lie about their extension (a PNG saved as `not_really.json`)
offers only PNG's real targets, never JSON's.

**Every adapter declares itself.** Each `Adapter` in the registry states, in
one place: its source and target format, a bilingual-ready display name,
whether the conversion is lossy and exactly what it loses, what happens to
metadata and encoding, and the resource limits the sandbox enforces around
it. The panel's disclosure card renders this — lossy/lossless, what may
change, and the metadata/encoding note — *before* a user commits to a
conversion, not after.

### Supported format pairs

**Minecraft NBT ↔ JSON**, both compressed and uncompressed:

| Adapter id | Source | Target | Lossy |
| --- | --- | --- | --- |
| `gzip_nbt_to_json` | Compressed NBT (structure/schematic) | JSON | No |
| `json_to_gzip_nbt` | JSON | Compressed NBT | No |
| `nbt_to_json` | Uncompressed NBT | JSON | No |
| `json_to_nbt` | JSON | Uncompressed NBT | No |

The JSON representation is structurally lossless: every tag keeps an explicit
`{"type": ..., "value": ...}` shape (`adapters._TAG_TYPE_NAMES` /
`_NAME_TO_CTOR`), so a byte tag stays a byte, a list of longs stays a list of
longs, and converting back reproduces the original tag tree rather than a
JSON-native approximation that would silently promote every integer to a
bare JSON number. The document also carries `__nbt_root_name__`, so the named
root tag survives the round trip. Hand-written JSON that does not use this
shape is refused rather than guessed at — `json_to_nbt`/`json_to_gzip_nbt`
raise a `ValueError` naming the malformed node instead of inventing a tag
type for it. NBT structures nested deeper than 512 levels are refused for
the same reason: unbounded recursion is a resource-exhaustion vector, not a
legitimate structure.

**Images**, every ordered pairing among PNG, JPEG, BMP, and GIF (twelve
adapters, `image_<source>_to_<target>`), via Pillow:

| Target | What is lost |
| --- | --- |
| JPEG | Recompresses with lossy quantisation; transparency is flattened onto white |
| PNG | Lossless pixel data; palette/animation source frames beyond the first are dropped |
| BMP | Lossless pixel data; alpha and any animation beyond the first frame are dropped |
| GIF | Reduces to a 256-colour palette and drops full alpha to binary transparency |

EXIF/ICC metadata and animation frames beyond the first are never carried
across for any image pairing; pixel colour data is what survives. Every image
adapter enforces a 64,000,000-pixel decode limit (`Image.MAX_IMAGE_PIXELS`)
so a maliciously crafted image cannot exhaust memory through decompression
alone — an oversized image is refused with the exact dimensions and the
limit named, not silently truncated.

## The sandbox

Every adapter call — NBT parsing, JSON parsing, image decoding — runs inside
`sandbox.run_adapter`, in a freshly spawned child process (`multiprocessing`
with the `"spawn"` context, never `"fork"`, so the child never inherits the
parent's open state) that receives nothing but the adapter's pure `convert`
callable and the source bytes over a pipe. Nothing about the child depends on
global registry state, an open file handle, or a network socket, because
`adapters.py` is deliberately pure: every function is `bytes -> bytes`, and
touches no filesystem path, no network, and no process-global state.

Bounds enforced around every call, all declared per adapter as `Limits`:

- **Input size** — checked before the child is even started; oversized input
  is reported as `input_too_large` with the exact byte count and the limit.
- **Wall-clock timeout** — the parent polls the pipe for at most
  `timeout_seconds`; a child that has not answered is killed
  (`terminate()`, then `kill()` if it does not exit) and reported as
  `timeout`.
- **Recursion depth** — the child sets `sys.setrecursionlimit(2000)`
  independently of the interpreter's own default, so a pathological input
  cannot exhaust the child's C stack before the adapter's own structural
  depth check (NBT/JSON nesting past 512 levels) applies.
- **Memory** — best-effort on POSIX via `resource.setrlimit(RLIMIT_AS, ...)`
  at 512 MiB; Windows exposes no equivalent syscall, so on Windows the
  enforced bounds are the timeout and the output-size check below. This gap
  is stated here rather than silently assumed closed.
- **Output size** — checked against `max_output_bytes` after the child
  reports success, before that output is ever offered to a user.
- **Output validity** — every adapter also declares a `validate_output`
  function (real magic-byte checks for images, a real NBT re-parse for
  NBT/JSON) that must return `True` before the sandbox will hand the bytes
  back. A `convert` implementation that produced garbage is caught here even
  if it never raised.

Every one of those failure modes is reported as a distinct, honest
`SandboxOutcome.status` — `input_too_large`, `timeout`, `crashed`,
`output_too_large`, `output_invalid` — never folded into a bare `False` a
caller has to guess the reason for.

## Conversion, batching, and history

`core.convert_one` is the single-file entry point the panel's **Convert**
button calls. Before it ever runs the sandboxed adapter it:

1. Refuses to write over the source file itself (compares absolute paths).
2. Refuses to overwrite an existing destination unless the caller has
   already confirmed that (`overwrite_confirmed=True` — the panel passes
   this only when `os.path.exists(destination_path)` was already true when
   the button was pressed, i.e. an implicit confirmation rather than a
   blocking dialog for what is a reversible, undo-able local write).
3. Re-reads the source bytes and re-detects the format with
   `detect_format_full`, and refuses to run the adapter at all if the bytes
   no longer match what the adapter declares as its `source_format` — this
   is what stops a source file that changed on disk between being picked and
   being converted from being silently fed to the wrong adapter.

The actual write is atomic: `core._atomic_write` writes to a temporary file
in the destination's own directory, flushes and `fsync`s it, then
`os.replace`s it into place — so a crash or a killed process during the
write can never leave a half-written destination file where a real one used
to be, or should be.

Every outcome — `CONVERTED`, `SKIPPED`, `CANCELLED`, `FAILED` — is recorded
in a bounded local history (`config` key `converter_history`, capped at 500
entries) via `core._record_history`, readable with `core.read_history()` and
clearable with `core.clear_history()`. A batch (`core.convert_batch`) reports
all four counts honestly and separately rather than collapsing them into one
number — a job in a cancelled batch is recorded as `CANCELLED` with a stated
reason, never silently dropped from the report.

## Security considerations of converting an untrusted file

The converter's whole design is aimed at the fact that a file a user picks to
convert may be attacker-crafted, so:

- **The extension is never trusted for anything.** Detection is always from
  real bytes, bounded to a fixed read size, so a file that lies about its
  format cannot make the converter run the wrong parser on it.
- **Parsing happens in an isolated, least-privileged child process**, not in
  the panel's own process. A crafted NBT or image file that manages to
  trigger a parser bug crashes an expendable, freshly spawned child — it
  does not corrupt the running application, and the crash is reported back
  as an honest `crashed` outcome with a bounded traceback (`limit=2`, so a
  crash cannot dump the child's whole call stack, including any bytes still
  live in its frames, into the parent's history).
- **Every resource an attacker could try to exhaust is bounded**: input size
  before the child starts, wall-clock time once it is running, recursion
  depth inside it, memory on POSIX, and output size and validity once it
  finishes. None of these bounds depend on the adapter's own code behaving —
  they are enforced by the sandbox around it.
- **Output is never trusted on the adapter's word alone.** The
  `validate_output` check re-parses or re-checks the magic bytes of what
  came back before it is offered to a user, catching an adapter that
  produced well-formed-looking bytes that are not actually valid in the
  target format.
- **The source file is never modified.** The converter only ever reads it;
  every conversion writes to a separate destination path, and that
  destination write is atomic so an interrupted conversion cannot corrupt
  either the source or a pre-existing file at the destination.

## Localization

Every string the panel renders — field labels, the detected-format line, the
loss/metadata disclosure, button labels and their accessible names, section
headings, search hints, the batch queue's row status, and every conversion
outcome shown in the results list — goes through
`amulet_map_editor.api.studio.copy.studio_label` / `studio_text`, the same
mechanism the rest of the Studio shell uses. This means the panel honours all
three language modes (English, playful Hong Kong-style Cantonese, bilingual)
and both funny-level sliders automatically: control labels stay untoned (a
button name is a name, not a message with an aside on the end), while
messages such as the "no file chosen yet" and disclosure text are styled by
the active English/Cantonese funny levels the same way every other Studio
message is. The factual parts of any message — a detected format name, a
byte count, a path — are protected by `copy.is_verbatim` and are never
altered by the styling pass.

## Verification

- `tests/test_converter_core.py` exercises detection, every adapter pairing,
  the sandbox's bounds and failure modes, atomic writes, and batch/history
  behaviour directly against the `amulet_map_editor.api.converter` package.
- `tests/test_converter_panel_ui_contract.py` builds the real `ConverterPanel`
  in a real `wx.Frame`, feeds it genuinely crafted files (a real gzip-NBT
  structure, a real PNG, and a file whose extension lies about its bytes),
  and captures the composited result to prove the panel actually paints and
  actually detects real bytes — not merely that its widgets exist in source.
- `tests/test_file_converter_reachable_from_backstage.py` builds the real
  `BackstageView`, drives its navigation rail exactly as a user's click
  would (`set_tab("file_convert")`), and asserts the real `ConverterPanel` is
  present in the built page and paints — closing the gap where a fully built
  panel existed in source but nothing in the running application ever routed
  to it.

## Suggested articles

- [Exports](../exports/README.md) — the project's general export system,
  covering structured records and other data the converter's history does
  not itself replace
- [Local history](../local-history/README.md) — the same append-only,
  restorable pattern the converter's own conversion history follows
- [Backstage](../backstage/README.md) — the Home/Open/Info/Convert/File
  converter/All surfaces/Workspace destinations this panel is one of
- [Sandboxed automation](../automation/README.md) — another surface that
  runs untrusted-shaped work in a bounded child process
