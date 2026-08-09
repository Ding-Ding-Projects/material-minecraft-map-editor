"""Resolve one unused public dim-sum code name for release notes."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

CATALOG_URL = "https://raw.githubusercontent.com/Ding-Ding-Projects/dim-sum-photos/main/catalog/index.json"
RELEASES_URL = "https://api.github.com/repos/Ding-Ding-Projects/dim-sum-photos/releases?per_page=100"
ASSET_URL = "https://github.com/Ding-Ding-Projects/dim-sum-photos/releases/download/{tag}/{name}"
CODE_NAME_RE = re.compile(r"Dim-sum code name:\s*(.+?)\s*·\s*(.+)", re.I)


def _get_json(url: str):
    request = Request(url, headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def resolve(catalog: dict, releases: list[dict]) -> tuple[str, str, str]:
    used: set[tuple[str, str]] = set()
    published: dict[str, str] = {}
    for release in releases:
        body = release.get("body") or ""
        for match in CODE_NAME_RE.finditer(body):
            used.add((match.group(1).strip(), match.group(2).strip()))
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if name.lower().endswith((".png", ".jpg", ".jpeg")):
                published[name] = release.get("tag_name", "")
    for dish in catalog.get("dishes", []):
        name = dish.get("name") or {}
        en, zh = str(name.get("en", "")).strip(), str(name.get("zhHant", "")).strip()
        image_name = Path(str((dish.get("image") or {}).get("path", ""))).name
        if not en or not zh or not image_name or (en, zh) in used:
            continue
        tag = published.get(image_name)
        if tag:
            return en, zh, ASSET_URL.format(tag=tag, name=image_name)
    raise RuntimeError("No unused catalog dish with a published public image asset was found")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        en, zh, url = resolve(_get_json(CATALOG_URL), _get_json(RELEASES_URL))
    except Exception as exc:  # noqa: BLE001 - CI must report the real boundary
        print(f"dim-sum code-name resolution failed: {exc}", file=sys.stderr)
        return 1
    print(f"DIM_SUM_CODE_NAME={en} · {zh}")
    print(f"DIM_SUM_PHOTO_URL={url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
