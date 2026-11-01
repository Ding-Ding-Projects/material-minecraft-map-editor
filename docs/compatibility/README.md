# Native Java compatibility target

The native rebuild targets the 54 stable Java releases from 1.12 through 26.3 listed in `java-releases.json`. This inventory was frozen from Mojang's official version manifest on 2026-11-01. It is a target, not a support claim. All read, edit and round-trip verdicts remain unverified until version-specific evidence exists.

Each row retains its official per-version metadata URL and SHA-1. Data versions must come from validated version metadata or generated fixtures, never from guessed version-number ranges. Record fixture provenance, hashes and evidence before changing a row's verdict. Preserve the frozen inventory when later upstream releases arrive; expanding it is a separate explicit scope decision.

Use generated disposable worlds and synthetic malformed inputs. Never copy a user's world into the repository. For each release, verify no-op preservation, edited-world reopening, dimensions, negative coordinates, region boundaries, entities, block entities, unknown tags, cancellation and interrupted-save recovery. The engine's synthetic layout tests alone do not satisfy these rows.

Bedrock, snapshots, future versions and arbitrary mod-specific semantics are outside the initial release. Unsupported inputs must remain visibly unavailable rather than falling through to a similar adapter. HTTP API collections are not applicable to the engine's private local process protocol.

## Official metadata evidence

`java-reference-evidence.json` records verified official archive sizes and hashes for all 54 frozen releases. Embedded metadata supplies 48 data versions; the six releases from 1.12 through 1.13.2 remain explicitly unknown in this evidence set. `java-releases.json` links those facts without changing any fixture, read, edit or round-trip verdict. Archive identity is not world compatibility.

## Initial geometry references

`java-geometry-reference-evidence.json` records the pinned official 1.20.1 client archive and ten bounded model/blockstate member hashes. All inspected stone and cobblestone variants resolve to full-cube geometry. This is limited geometry provenance, not opacity, collision, lighting, complete renderer or world-edit acceptance. No client/model assets are redistributed.
