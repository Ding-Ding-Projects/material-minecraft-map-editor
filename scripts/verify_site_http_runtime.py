"""Verify a running owner-hosted site before it is called deployable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

def fetch(base: str, path: str) -> tuple[bytes, object]:
    request = Request(urljoin(base.rstrip("/") + "/", path.lstrip("/")))
    with urlopen(request, timeout=10) as response:  # noqa: S310 - bounded test URL
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        return response.read(), response.headers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument(
        "--expected-manifest",
        type=Path,
        default=Path("docs/site/release-manifest.json"),
    )
    args = parser.parse_args()
    if not args.base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise SystemExit("runtime verification is limited to a loopback origin")

    home, home_headers = fetch(args.base_url, "/")
    if (
        b'id="command-palette"' not in home
        or b'id="release-download"' not in home
        or b'id="release-code-name-link"' not in home
    ):
        raise SystemExit("home page is missing palette or release controls")
    if home_headers.get("X-Content-Type-Options") != "nosniff":
        raise SystemExit("home page is missing nosniff")

    module, module_headers = fetch(args.base_url, "/theme.mjs")
    content_type = module_headers.get_content_type()
    if content_type != "application/javascript" or b"deriveThemeRoles" not in module:
        raise SystemExit(f"theme.mjs has an unsafe MIME contract: {content_type}")
    worker, worker_headers = fetch(args.base_url, "/regex-worker.mjs")
    worker_content_type = worker_headers.get_content_type()
    if worker_content_type != "application/javascript" or b"evaluateRegex" not in worker:
        raise SystemExit(
            f"regex-worker.mjs has an unsafe MIME contract: {worker_content_type}"
        )

    catalog_bytes, _headers = fetch(args.base_url, "/articles.json")
    catalog = json.loads(catalog_bytes)
    if catalog.get("articleCount") != 18 or len(catalog.get("articles", [])) != 18:
        raise SystemExit("running site does not expose all 18 feature articles")

    deep_route, _headers = fetch(args.base_url, "/docs/release-delivery")
    if b'id="article-view"' not in deep_route:
        raise SystemExit("owner host does not fall back to the site shell on deep routes")

    expected = json.loads(args.expected_manifest.read_text(encoding="utf-8"))
    manifest_bytes, _headers = fetch(args.base_url, "/release-manifest.json")
    manifest = json.loads(manifest_bytes)
    if manifest != expected or manifest.get("verified") is not True:
        raise SystemExit("running site does not expose the exact verified release")

    print(
        "Owner-host runtime verified: UI/Worker JavaScript MIME, nosniff, 18 articles, "
        "deep route, palette shell, and verified release manifest"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
