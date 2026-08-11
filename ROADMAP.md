# Roadmap

Legend: ✅ landed and covered by tests · 🏃 in progress · ⏳ waiting on evidence
this repository cannot produce by itself.

## Amulet Studio interface

- ✅ Two-view project shell: `StudioShell` hosts a backstage and a ribbon
  workspace, and `AmuletUI` builds it as the frame's content with the earlier
  chrome hidden. A build that cannot construct the Studio falls back to the
  world notebook rather than opening an empty window.
- ✅ Design token layer: fourteen colour roles in a light and a dark palette,
  three density heights (32, 36, 44), the spacing and radius scales, local-only
  font fallback, and accent reseeding that recomputes readable inks.
- ✅ Declarative surface renderer: all sixteen section kinds implemented and all
  sixteen in use. 111 surface descriptions across five spec families.
- ✅ Surface index: 119 surfaces in fourteen groups, every one of them routed to
  a spec, a hand-built window, or the legacy dialog that is still its real
  implementation. `surfaces.unrouted_keys()` is empty.
- ✅ Ribbon: seventeen tabs, structurally validated, with every tile resolving to
  a registered surface or a registered command and every group launcher
  resolving to an indexed surface.
- ✅ Shared search behaviour with an anchored regex builder on every search
  field, a hand-written census of those fields, and no bare `wx.Choice`,
  `wx.ComboBox`, or `wx.SearchCtrl` anywhere in the package.
- ✅ Two hand-built windows: the NBT editor and the Memory Console.
- ✅ NBT model: twelve tag types, SNBT round-tripping for all six sample
  documents, per-type validation, retype previews reporting every loss, and
  append-only per-tag history where a restore writes a new revision.
- ✅ Memory Console: thirteen views, a card grid, and a two-pane reader over the
  feature articles with domain filters and search.
- ✅ Accessibility contract: every interactive widget names itself, answers the
  keyboard as well as a click, and re-reads the palette on a theme change.
- 🏃 Runtime rendering evidence. Every claim above is source and automated-test
  evidence. **No capture of the Studio interface exists yet**, and none should
  be implied until a real build has been photographed on a Windows desktop.
- ⏳ Driving the built application from a clean profile, which is how surfaces
  nobody thought to capture get found.

## Material 3 foundations

- ✅ Shared wxPython colour, typography, spacing, shape, and control-size tokens
  for the dialogs that predate the Studio, reading the same persisted profile so
  the two halves cannot drift into two themes.
- ✅ Persisted language, funny-level, appearance, and regex-builder foundation.
- ✅ Versioned named appearance presets, validated JSON interchange, and native
  Appearance-tab load/save/import/export and staged reset controls.
- ✅ Versioned scheduled-settings foundation with local precedence and boundary
  tests.
- 🏃 Complete per-element appearance editing and live tab-strip projection. The
  native controls expose a bounded persisted element editor and the tab/group
  manager covers persisted docking, pinning, grouping, search, and notebook
  activation; the notebook's visual edge projection and full word-processor
  typography depth remain open.

## Windows delivery

- ✅ Unsigned PyInstaller + Squirrel.Windows contract with `Setup.exe`,
  `RELEASES`, full `.nupkg`, and Authenticode `NotSigned` checks.
- ✅ Bounded startup and manual update check with a non-blocking status surface.
- ✅ Automated Squirrel versions rank numerically above legacy stable 0.10.76;
  patch range 100000..999999 is reserved against stable collisions, and the
  explicit-channel resolver binds the exact immutable project feed and release
  notes through one documented 900-second apply-and-verify deadline. All
  inventory pages and the CLI check share one deadline; canonical
  build/manual/release tags, strict record separators, empty-result version
  equality, five-page inventory discovery, exact post-stage version proof, and
  the guarded process-start handoff are covered by focused boundary tests.
- ✅ Hosted release publication produces unsigned `Setup.exe`, `RELEASES`, and
  the full `.nupkg`, with publication timing measured from the confirmed publish
  timestamp and release notes reporting reproducible line attribution.
- ⏳ Hosted delta publication and a three-version installed-client update proof,
  before delta delivery is advertised to clients.

## Documentation

- ✅ One article per feature area under `docs/features/`, each covering
  behaviour, configuration, failure modes, security, and verification, and each
  ending with related reading. Forty-eight articles are bundled.
- ✅ Offline documentation bundle generated from those articles, with a
  completeness check that fails the suite when an article is added without
  regenerating it.
- ✅ Memory Console reader over the same articles, with every article path
  asserted to name a file that actually exists.
- 🏃 Material 3 landing site under `docs/site/`, published through Pages. The
  feature and article data now describe Amulet Studio; complete settings parity
  with the application remains open.
- ⏳ Screenshots of the Studio interface for the README, the articles, and the
  site. Every image currently tracked shows a superseded build and says so.
