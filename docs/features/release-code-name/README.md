# Release dim-sum code names

## Behaviour

The Windows release workflow tries to add one unused bilingual dish name to each release. The resolver reads the public `Ding-Ding-Projects/dim-sum-photos` catalog, inventories every bounded page of this project's releases, and compares normalized English and Traditional Chinese name pairs so a dish is not deliberately reused. It preserves catalog order when choosing the first eligible unused dish.

An image is eligible only when its exact filename is an uploaded, non-empty asset on a published, non-draft `catalog-v1*` release. The asset's GitHub download URL must match that release and filename. Release notes link directly to that public asset; this repository never copies the image or attaches a duplicate photo.

## Configuration and failure modes

`GITHUB_REPOSITORY` identifies the project whose complete release history is checked. `GH_TOKEN` is optional rate-limit headroom for GitHub API calls and is sent only to `api.github.com`, never to the raw catalog host or an asset URL.

The resolver has two explicit output states:

- `DIM_SUM_STATUS=available` is accompanied by `DIM_SUM_CODE_NAME` and `DIM_SUM_PHOTO_URL`.
- `DIM_SUM_STATUS=unavailable` is accompanied by a bounded `DIM_SUM_WARNING`. Catalog downtime, malformed or oversized input, unsafe pagination, an unavailable photo, or exhaustion of all eligible unused dishes produces this state with exit code zero. Publication continues with the version alone; it never invents or reuses a dish merely to fill the field.

The network boundary permits at most 20 pages and 2,000 releases per inventory, 5,000 catalog dishes, and 16 MiB per response. It rejects redirects, non-HTTPS or changed hosts, cross-endpoint pagination, repeated pages, unexpected query fields, non-JSON API responses, oversized bodies, and malformed metadata. If the repository eventually exceeds those bounds, code-name decoration becomes unavailable while the software release remains non-blocking.

## Security

Catalog values are parsed as fixed workflow output keys and are never passed through shell evaluation. Dish names, image paths, asset metadata, pagination links, response type, final URL, and response size are validated before use. Redirects are refused so an authorization header cannot be forwarded to another origin. Warning text is single-line and bounded, and unexpected exception details are not echoed, preventing a token-like value from entering release logs.

## Verification

Run `py -3 -m pytest -q tests/test_dim_sum_release_code.py` for deterministic selection, five-page/477-release pagination, duplicate detection, catalog-tag and uploaded-asset eligibility, exhaustion fallback, malformed data, redirect, host, size, token, and network-boundary coverage. Set `GITHUB_REPOSITORY=Ding-Ding-Projects/material-minecraft-map-editor` before running `python scripts/resolve_dim_sum_code_name.py` to exercise the live public boundary locally; either `available` or a clear non-blocking `unavailable` result is valid, depending on the current catalog pool.

## Suggested articles

- [Dim-sum surprise](../dim-sum-surprise/README.md)
- [Squirrel packaging](../../../installer/PACKAGING.md)
- [Offline documentation browser](../offline-documentation/README.md)
