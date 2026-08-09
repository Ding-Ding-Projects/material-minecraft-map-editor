# Dim-sum surprise foundation

## Behaviour

`amulet_map_editor.api.dim_sum_surprise` provides a wx-independent startup
controller. Each controller represents one application launch and makes at
most one fresh random draw. Values from `0` up to, but not including, `0.10`
qualify. An ineligible first-run, update, error, or mid-task launch is a no-op.

A qualifying draw resolves catalog data on a daemon thread and returns a
focus-safe payload for a future notification adapter. The payload identifies
itself as non-blocking, forbids focus stealing, supplies an eight-second
auto-dismiss hint, and localizes the authoritative dish name and meaningful
image alt text for English, Cantonese, or bilingual presentation.

## Public source and photo boundary

Dish metadata is fetched only from the canonical public catalog:

`https://raw.githubusercontent.com/Ding-Ding-Projects/dim-sum-photos/main/catalog/index.json`

The request has a three-second maximum timeout and an eight-MiB response cap.
Only schema `1.0.0` records with bounded `name.en`, `name.zhHant`, image alt text,
and a safe `images/*.png` catalog path are accepted. Network, timeout, decoding,
schema, and selection failures quietly produce no surprise, so offline startup
remains fully usable.

This consumer repository does not generate, download, vendor, or cache photo
files. The payload deliberately exposes only the catalog's image asset path.
A future presentation adapter must verify that path against a published
`catalog-v1*` release asset from `Ding-Ding-Projects/dim-sum-photos`, then use
the public asset URL or an application-data cache outside this repository.
Until that adapter exists, this module is a tested state and source-boundary
foundation rather than a complete visible startup notification.

## Security and failure modes

- The source URL is constant, HTTPS, and redirect changes are rejected.
- Response size is checked from both `Content-Length` and the actual bounded
  read before JSON decoding.
- Untrusted catalog strings and paths have explicit length and shape bounds.
- The background callback is invoked only after a valid dish is selected.
- Any callback or background resolution failure remains a startup-safe no-op.

## Verification

Run:

```powershell
py -3 -m unittest tests.test_dim_sum_surprise -v
```

The tests cover the exact probability boundary, concurrent-safe single-fire
state, all three language modes, bounded catalog parsing, offline failure, and
the absence of dim-sum image copies in the consumer repository.

## Suggested articles

- [Scheduled settings](../scheduled-settings/README.md) explains persisted
  language and appearance overrides.
- [Appearance presets](../appearance-presets/README.md) documents the shared
  user-facing preference foundation that supplies the active language mode.
