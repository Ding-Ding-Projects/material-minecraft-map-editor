# The core/wx boundary

## What it is

`amulet_map_editor/api/core_boundary.py` names the part of the API package
that does not import `wx` — not directly, and not by importing something else
that eventually does. That list is `PORTABLE_CORE_MODULES`, and it is
hand-written rather than discovered by scanning the tree.

Every module on the list has been verified by importing it in a fresh
subprocess with `wx` actively blocked (removed from `sys.modules` and refused
by a custom `sys.meta_path` finder, not merely absent). If the import
succeeds, the module — and everything it pulls in — genuinely has no wx
dependency at runtime. `tests/test_core_boundary.py` re-runs that exact check
for every listed module on every test run.

As of this writing the confirmed-portable set is:

- `appearance_editor`, `appearance_presets`
- `app_logo`
- `changelog`
- `colour`
- `config`
- `converter` (the whole package: `adapters`, `core`, `registry`, `sandbox`,
  `signatures`)
- `datatypes`
- `dim_sum_surprise`
- `docs_browser`
- `dpi`
- `export_actions`
- `external_editor`
- `lang`
- `local_history`
- `material_menu`
- `notifications`, `notification_copy`
- `outcome`
- `preferences`
- `process`
- `progress`
- `regex_builder`
- `scheduled_refresh`, `scheduled_runtime`, `scheduled_settings`,
  `scheduled_sources`
- `school_mode`
- `startup_diagnostics`
- `tab_groups`
- `text_overlay`
- `tts_narrator`

Three modules that looked like plausible candidates were checked and found
**not** portable yet, and the boundary module records why so nobody has to
rediscover it:

- `authenticator` and `item_locks` both import `forge_accounts` for its
  store-note copy helpers, and `forge_accounts` imports `wx` at module scope
  to define `ForgeAccountsDialog(wx.Dialog)` next to its plain account/token
  data model. The two halves of that file are not split yet.
- `resources` imports `amulet_map_editor.api.image`, whose package `__init__`
  imports `wx` to build `wx.Bitmap`/`wx.Image` objects from bundled PNG bytes.

These three are recorded in `KNOWN_NOT_PORTABLE` in the same module, each with
a one-line reason. A second guard test,
`test_known_not_portable_modules_actually_fail_without_wx`, asserts that they
really do still fail — so if someone splits `forge_accounts` and the wx
dependency goes away, that test starts failing as a prompt to move the module
up into the portable list rather than leaving it stranded in the "known not
portable" pile.

## Why this boundary exists

The migration plan in `HANDOFF.md` (see "Converting to an Electron
application, piece by piece") calls for the portable core to become a Python
sidecar process that the Electron main process supervises over a typed JSON
protocol, while the wx-dependent surfaces are ported to the existing
`docs/site/` Material 3 renderer one at a time. Phase 2 and Phase 3 both need
an honest, currently-true answer to "which modules can run without wx
installed at all" — not an aspiration, not a list of modules that merely
*look* like they should be portable by their name or their folder.

Guessing at this from file names would be wrong in both directions: a module
can look self-contained and still pull in `wx` two imports deep (as
`authenticator` does through `forge_accounts`), and a module that imports
`wx` for one narrow purpose might be trivially fixable while another is a
real, larger refactor. The subprocess-with-wx-blocked check answers the
question directly instead of guessing.

## Why the list is hand-written, not discovered

A test that scans `amulet_map_editor/api/` for modules that "currently don't
import wx" and asserts that fact about whatever it finds would pass on a
package with zero portable modules exactly as readily as one with thirty-four
— it never asked whether the *right* modules are portable, only whether
today's snapshot is internally consistent. That is the same failure mode this
repository's other completeness guards exist to prevent: a rule that only
validates what is already present proves nothing about what is missing.

Hand-writing `PORTABLE_CORE_MODULES` means:

- A module silently **gaining** a wx import (through an edit to itself or to
  something it imports) makes the boundary test fail, because the list still
  claims it is portable and the subprocess check will now say otherwise.
- A module that becomes wx-free is **not** automatically added to the
  boundary's promise. Someone has to look at it, decide it belongs, and add
  it — at which point it is also covered by the enforcement test.

This was verified directly rather than assumed: `import wx` was added
temporarily to `amulet_map_editor/api/config.py` (which is on the portable
list), the test was confirmed to fail, the import was removed, and the test
was confirmed to pass again.

## How to add a module to the boundary

1. Verify it first. Run it through a subprocess with `wx` blocked from
   `sys.modules` and from being imported again — the pattern in
   `tests/test_core_boundary.py`'s `_import_without_wx` helper is reusable
   for this. Do this for the module itself; a clean top-level import can
   still hide a wx dependency in a rarely-imported submodule, so check the
   actual module you're adding, not just its package `__init__`.
2. Add the fully-qualified module name to `PORTABLE_CORE_MODULES` in
   `amulet_map_editor/api/core_boundary.py`, in alphabetical order within its
   neighbours.
3. If the module was previously listed in `KNOWN_NOT_PORTABLE`, remove that
   entry — the two lists must not overlap, and a test asserts that too.
4. Run `tests/test_core_boundary.py`. The new entry is auto-covered by the
   parametrized test; no new test code is needed per module.
5. If a module you expected to be portable fails, read the subprocess
   traceback — it names the exact import chain that reaches `wx`. Add it to
   `KNOWN_NOT_PORTABLE` with that one-line reason instead of silently
   dropping it.

## Failure modes

- **A listed module starts importing wx.** The parametrized test
  `test_portable_core_module_does_not_import_wx` fails for that module,
  naming the subprocess's stdout/stderr (which includes the traceback to the
  offending `import wx`).
- **A `KNOWN_NOT_PORTABLE` module stops needing wx.** The guard test
  `test_known_not_portable_modules_actually_fail_without_wx` fails, which is
  the intended prompt to promote that module to the portable list.
- **The two lists overlap or contain a duplicate.** `test_boundary_lists_do_not_overlap`
  and `test_portable_core_modules_have_no_duplicates` catch bookkeeping
  mistakes in the module itself, independent of any real import behaviour.

## Security considerations

None of the listed modules touch the OS credential vault, network sockets, or
secret material differently because of this boundary — the boundary only
changes *where* a module can run, not what it is trusted to do. The known
risk called out in `HANDOFF.md` (a secret must not be migrated through a
file or a log to cross the process boundary in Phase 2) applies once these
modules actually move into a sidecar process; it is not a property of this
inventory pass itself.

## Verification

- `tests/test_core_boundary.py` — 40 assertions: one parametrized subprocess
  check per portable module, one per known-not-portable module, plus the two
  bookkeeping guards. Run with:

  ```
  py -3.11 -m pytest tests/test_core_boundary.py -q
  ```

- The guard was watched fail: a temporary `import wx` was added to
  `amulet_map_editor/api/config.py`, `pytest tests/test_core_boundary.py -k
  config` went red with a traceback pointing at the injected import, the line
  was reverted, and the same command went green again.

## Suggested articles

- [Local history](../local-history/README.md) — one of the confirmed-portable
  modules, and itself a dependency the sidecar will carry across the
  boundary.
- [File converter](../file-converter/README.md) — the sandboxed child-process
  pattern that Phase 2's sidecar protocol is modelled on.
- [Completeness inventory](../completeness-inventory/README.md) — the
  migration checklist this boundary feeds: a row may not regress from
  complete to incomplete because of a port.
