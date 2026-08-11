# Bundled interface fonts

This directory is where the application looks for the design's own typefaces.
It ships empty on purpose. Nothing here is downloaded at build time or at run
time, and an empty directory is the normal, supported state — not a fault.

## What the application does with it

At first use, `amulet_map_editor.api.studio.tokens` registers every `.ttf` and
`.otf` file in this directory through `wx.Font.AddPrivateFont`, once per
process, *before* it enumerates the installed faces. A private face is visible
only to this application: it is not installed for the rest of the machine, and
it disappears when the process exits.

Registration happens before enumeration because a face wx has not been told
about is a face the enumerator does not list, and a face the enumerator does not
list is one the token layer will silently skip in favour of a substitute.

## What to put here

The design's type identity is **IBM Plex Sans** for interface text and **IBM
Plex Mono** for coordinates, identifiers, tags, and hashes. Drop the font files
you are licensed to redistribute into this directory, keeping their own file
names:

```
IBMPlexSans-Regular.ttf
IBMPlexSans-Medium.ttf
IBMPlexSans-SemiBold.ttf
IBMPlexMono-Regular.ttf
IBMPlexMono-Medium.ttf
```

Any `.ttf` or `.otf` file is picked up; those names are the set the interface
actually asks for by name. A face that is already installed system-wide does not
need to be duplicated here.

## Why the files are not committed

Font files are redistributable binaries with their own licence terms, and a
repository is the wrong place to carry them:

- **Licensing is per-file and per-distribution.** Whoever ships a build is the
  party bound by the licence, so the choice of which faces to include belongs to
  the packaging step, not to the source tree.
- **They are large binaries.** A handful of weights runs to several megabytes
  that would be re-fetched on every clone, forever, and would be the wrong kind
  of file for ordinary Git storage.
- **They are optional.** The application resolves a documented fallback chain of
  platform faces when this directory is empty, so a checkout without them builds
  and runs exactly as it does with them — it just does not look like the design.

## Telling the truth about it

`tokens.bundled_font_status()` returns a one-line summary of what actually
happened: how many files were loaded as private faces, or that none were found
and which faces are rendering instead. The About surface and the documentation
report that string rather than asserting the design's typography is present, so
a build without these files says so plainly instead of implying otherwise.

Three things are worth knowing when reading that line:

- `wx.Font.AddPrivateFont` does not exist on every platform build. Where it is
  missing, files placed here are found and reported, and are not loaded.
- A file wx refuses is reported as refused rather than counted as loaded.
- Private faces cannot be unregistered, so they are loaded once per process and
  survive a theme change without being registered again.

## Packaging

A packaging step that supplies these files must also make sure they reach the
installed application. The source distribution manifest lists file types
explicitly, so `*.ttf` and `*.otf` need to be included there for a packaged
build to carry them.
