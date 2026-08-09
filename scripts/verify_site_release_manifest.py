"""Validate the static site's publication and immutable-release contracts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit


SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
COMMIT = re.compile(r"^[0-9a-fA-F]{40}$")
RELEASE_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ASSET_KEYS = ("Setup.exe", "RELEASES", "full.nupkg")


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _validate_base_url(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("site baseUrl must be a non-empty string")
    if value == "./":
        return value
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("site baseUrl must be ./ or an absolute HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("site baseUrl must not contain credentials, query, or fragment")
    if not value.endswith("/"):
        raise ValueError("site baseUrl must end with '/'")
    return value


def _validate_asset(key: str, asset: object, release_tag: str) -> None:
    name = asset.get("name") if isinstance(asset, dict) else None
    if not isinstance(asset, dict):
        raise ValueError(f"asset {key!r} must be an object")
    if key in ("Setup.exe", "RELEASES") and name != key:
        raise ValueError(f"asset {key!r} has a mismatched name")
    if key == "full.nupkg" and (not isinstance(name, str) or not name.endswith("-full.nupkg")):
        raise ValueError("full.nupkg asset name must end with -full.nupkg")
    digest = asset.get("sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise ValueError(f"asset {key!r} must include a 64-character SHA-256 digest")
    url = asset.get("url")
    if not isinstance(url, str):
        raise ValueError(f"asset {key!r} must include a URL")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"asset {key!r} URL must be absolute HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"asset {key!r} URL must be immutable (no credentials/query/fragment)")
    if not parsed.path.endswith("/" + str(name)):
        raise ValueError(f"asset {key!r} URL must end with /{name}")
    if f"/download/{release_tag}/" not in parsed.path:
        raise ValueError(f"asset {name!r} URL must identify release {release_tag!r}")


def validate_site_config(path: Path) -> dict:
    config = _read_json(path)
    if config.get("schemaVersion") != 1:
        raise ValueError("site config schemaVersion must be 1")
    _validate_base_url(config.get("baseUrl"))
    manifest = config.get("releaseManifest")
    if not isinstance(manifest, str) or not manifest:
        raise ValueError("site config releaseManifest must be a non-empty path")
    if ".." in Path(manifest).parts:
        raise ValueError("site config releaseManifest must stay inside the site bundle")
    return config


def validate_release_manifest(path: Path) -> dict:
    manifest = _read_json(path)
    if manifest.get("schemaVersion") != 1:
        raise ValueError("release manifest schemaVersion must be 1")
    if not isinstance(manifest.get("verified"), bool):
        raise ValueError("release manifest verified must be boolean")
    assets = manifest.get("assets")
    if not isinstance(assets, dict):
        raise ValueError("release manifest assets must be an object")
    if not manifest["verified"]:
        if assets:
            raise ValueError("unverified release manifest must not contain installer assets")
        if manifest.get("releaseTag") or manifest.get("commit"):
            raise ValueError("unverified release manifest must not claim a release or commit")
        return manifest
    release_tag = manifest.get("releaseTag")
    commit = manifest.get("commit")
    if not isinstance(release_tag, str) or not RELEASE_TAG.fullmatch(release_tag):
        raise ValueError("verified release manifest has an invalid releaseTag")
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        raise ValueError("verified release manifest has an invalid 40-character commit")
    if set(assets) != set(ASSET_KEYS):
        raise ValueError("verified release manifest must contain Setup.exe, RELEASES, and full.nupkg")
    for key, asset in assets.items():
        _validate_asset(key, asset, release_tag)
    return manifest


def validate_bundle(site_dir: Path) -> None:
    config = validate_site_config(site_dir / "site-config.json")
    manifest_path = site_dir / config["releaseManifest"]
    validate_release_manifest(manifest_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("site_dir", type=Path)
    args = parser.parse_args()
    validate_bundle(args.site_dir)
    print(f"Site publication contract verified: {args.site_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
