# Test suite

```powershell
py -3 -m pytest tests -q
```

Most of this suite runs without a display. The application's data layer — the
Studio surface index, the command registry, every surface description, the
shared search state, the NBT model, the Memory Console's content, the
preferences, the changelog, and the release tooling — imports without wxPython
by design, so a machine with no wx can still prove almost all of it.

The handful of checks that genuinely need wx guard themselves with
`pytest.importorskip("wx")` and skip with that reason stated, rather than
passing silently.

## Two generated resources

Two files in the package are generated from the repository and the suite checks
them against their sources:

- `amulet_map_editor/api/docs_articles.json` — rebuilt by
  `python scripts/build_docs_bundle.py` from every `docs/features/*/README.md`.
  An article added without regenerating fails `test_docs_browser.py`, which is
  the point: it cannot ship missing from the in-app browser.
- `amulet_map_editor/api/changelog_catalog.json` — rebuilt by
  `python scripts/generate_changelog.py` from the reachable tags. `conftest.py`
  regenerates it automatically when the checkout has moved on, so a developer
  does not have to know about an undocumented preparation step.

## Hand-written lists, and why they are not generated

Several files carry an enumeration written by hand:

| File | The list |
| --- | --- |
| `test_studio_surface_index.py` | every surface, under its group heading |
| `test_studio_regex_builder_coverage.py` | every search field in the shell |
| `test_studio_accessibility_contract.py` | every widget and composed surface |
| `test_studio_memory_content.py` | the thirteen Memory Console views |
| `test_m3_surface_inventory.py` | every hand-written Material dialog |
| `test_site_publication_contract.py` | every setting the site must render |
| `test_site_palette_inventory_contract.py` | every module the palette reads |

A rule alone cannot catch a disappearance. "Every surface in the index resolves"
is satisfied by an index holding none; "every search bar carries a builder" is
satisfied by a file with no search bar. The enumeration is what turns something
going missing into a failure.

**Adding a thing means adding its line in the same change. Deleting a line to
make the suite green is the one edit that defeats the file's purpose.** When
something is genuinely removed, remove it from the documented inventory first,
and from the list as part of that same change.

A new guard is worth verifying in the failing direction — break the thing it
guards on purpose, watch it go red, then restore. A guard nobody has watched
fail proves nothing.

## Style

The suite is source-contract heavy: most files read a module as text or parse it
with `ast` and assert on what is there, rather than constructing windows. That
is deliberate — it keeps the checks runnable on any machine, and it is honest
about what they prove. A static check is evidence about wiring, never about
rendering; rendering evidence needs a real build on a Windows desktop and is
reported separately.
