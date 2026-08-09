# Release dim-sum code names

## Behaviour

The Windows release workflow resolves one unused bilingual dish name from the public `Ding-Ding-Projects/dim-sum-photos` catalog. It selects only a dish whose image filename appears in a published `catalog-v1*` release asset, then records the factual English and Traditional Chinese names plus the immutable public asset URL in the release notes.

## Configuration and failure modes

The resolver is network-backed during publication and accepts an optional `GH_TOKEN` for GitHub API rate-limit headroom. It fails closed when the catalog, release inventory, bilingual name, or public image asset cannot be verified; this prevents a guessed code name from entering a release. A release can still be retried after the public catalog is available.

## Security

Catalog values are parsed as fixed workflow output keys; they are never passed through shell evaluation. The release notes link to the public asset and do not copy the photo into this repository or attach a duplicate consumer asset.

## Verification

Run `py -3 -m pytest -q tests/test_dim_sum_release_code.py` for the deterministic selection and fail-closed tests. Run `python scripts/resolve_dim_sum_code_name.py` to exercise the live public catalog boundary locally.

## Suggested articles

- [Dim-sum surprise](../dim-sum-surprise/README.md)
- [Squirrel packaging](../../../installer/PACKAGING.md)
- [Offline documentation browser](../offline-documentation/README.md)
