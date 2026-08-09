"""Validate the static site's publication and immutable-release contracts."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import urlsplit

SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
COMMIT = re.compile(r"^[0-9a-fA-F]{40}$")
RELEASE_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ASSET_KEYS = ("Setup.exe", "RELEASES", "full.nupkg")
ARTICLE_SLUG = re.compile(r"^[a-z0-9-]{1,80}$")
ARTICLE_SOURCE = re.compile(r"^docs/features/([a-z0-9-]+)/README\.md$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DURATION = re.compile(r"^(\d{2}):(\d{2}):(\d{2})$")
EXPECTED_GITHUB_HOST = "github.com"
EXPECTED_RELEASE_REPOSITORY = "/Ding-Ding-Projects/material-minecraft-map-editor"
EXPECTED_PHOTO_REPOSITORY = "/Ding-Ding-Projects/dim-sum-photos"


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
        raise ValueError(
            "site baseUrl must not contain credentials, query, or fragment"
        )
    if not value.endswith("/"):
        raise ValueError("site baseUrl must end with '/'")
    return value


def _validate_bundle_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"site config {label} must be a non-empty POSIX path")
    parsed = urlsplit(value)
    path = PurePosixPath(parsed.path)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or path.is_absolute()
        or ".." in path.parts
    ):
        raise ValueError(f"site config {label} must stay inside the site bundle")
    return value


def _validate_asset(key: str, asset: object, release_tag: str) -> None:
    if not isinstance(asset, dict):
        raise ValueError(f"asset {key!r} must be an object")
    name = asset.get("name")
    if key in ("Setup.exe", "RELEASES") and name != key:
        raise ValueError(f"asset {key!r} has a mismatched name")
    if key == "full.nupkg" and (
        not isinstance(name, str) or not name.endswith("-full.nupkg")
    ):
        raise ValueError("full.nupkg asset name must end with -full.nupkg")
    digest = asset.get("sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise ValueError(f"asset {key!r} must include a 64-character SHA-256 digest")
    size = asset.get("bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ValueError(f"asset {key!r} must include a positive byte size")
    url = asset.get("url")
    if not isinstance(url, str):
        raise ValueError(f"asset {key!r} must include a URL")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != EXPECTED_GITHUB_HOST:
        raise ValueError(
            f"asset {key!r} URL must use the expected GitHub repository host"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            f"asset {key!r} URL must be immutable (no credentials/query/fragment)"
        )
    expected_path = (
        f"{EXPECTED_RELEASE_REPOSITORY}/releases/download/{release_tag}/{name}"
    )
    if parsed.path != expected_path:
        raise ValueError(
            f"asset {key!r} URL must use the exact expected owner/repository/tag path"
        )


def validate_site_config(path: Path) -> dict:
    config = _read_json(path)
    if config.get("schemaVersion") != 1:
        raise ValueError("site config schemaVersion must be 1")
    _validate_base_url(config.get("baseUrl"))
    _validate_bundle_path(config.get("releaseManifest"), "releaseManifest")
    _validate_bundle_path(config.get("articles"), "articles")
    return config


def validate_article_catalog(path: Path) -> dict:
    catalog = _read_json(path)
    if catalog.get("schemaVersion") != 1:
        raise ValueError("article catalog schemaVersion must be 1")
    articles = catalog.get("articles")
    if not isinstance(articles, list) or not articles:
        raise ValueError("article catalog must contain articles")
    if catalog.get("articleCount") != len(articles):
        raise ValueError("article catalog count does not match its records")
    slugs = [article.get("slug") for article in articles if isinstance(article, dict)]
    if len(slugs) != len(articles) or len(set(slugs)) != len(slugs):
        raise ValueError("article catalog slugs must be unique")
    slug_set = set(slugs)
    for article in articles:
        slug = article.get("slug")
        title = article.get("title")
        summary = article.get("summary")
        markdown = article.get("markdown")
        source = article.get("sourcePath")
        digest = article.get("sha256")
        suggested = article.get("suggested")
        if not isinstance(slug, str) or not ARTICLE_SLUG.fullmatch(slug):
            raise ValueError("article catalog contains an invalid slug")
        if not isinstance(title, str) or not title.strip() or len(title) > 160:
            raise ValueError(f"article {slug!r} has an invalid title")
        if not isinstance(summary, str) or len(summary) > 240:
            raise ValueError(f"article {slug!r} has an invalid summary")
        if not isinstance(markdown, str) or not markdown.startswith("# "):
            raise ValueError(f"article {slug!r} has invalid Markdown")
        source_match = (
            ARTICLE_SOURCE.fullmatch(source) if isinstance(source, str) else None
        )
        if not source_match or source_match.group(1) != slug:
            raise ValueError(f"article {slug!r} has invalid provenance")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError(f"article {slug!r} has invalid SHA-256 provenance")
        if not isinstance(suggested, list) or not 2 <= len(suggested) <= 3:
            raise ValueError(f"article {slug!r} needs two or three suggested articles")
        if len(set(suggested)) != len(suggested):
            raise ValueError(f"article {slug!r} repeats a suggested article")
        if any(value not in slug_set or value == slug for value in suggested):
            raise ValueError(f"article {slug!r} has an invalid suggested article")
    return catalog


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
            raise ValueError(
                "unverified release manifest must not contain installer assets"
            )
        if manifest.get("releaseTag") or manifest.get("commit"):
            raise ValueError(
                "unverified release manifest must not claim a release or commit"
            )
        return manifest
    release_tag = manifest.get("releaseTag")
    commit = manifest.get("commit")
    if not isinstance(release_tag, str) or not RELEASE_TAG.fullmatch(release_tag):
        raise ValueError("verified release manifest has an invalid releaseTag")
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        raise ValueError("verified release manifest has an invalid 40-character commit")
    expected_release_url = (
        f"https://{EXPECTED_GITHUB_HOST}{EXPECTED_RELEASE_REPOSITORY}/releases/tag/{release_tag}"
    )
    if manifest.get("releaseUrl") != expected_release_url:
        raise ValueError("verified release manifest has an invalid release URL")
    published_at = manifest.get("publishedAt")
    if not isinstance(published_at, str) or not UTC_TIMESTAMP.fullmatch(published_at):
        raise ValueError("verified release manifest needs an exact UTC publishedAt")
    code_name = manifest.get("codeName")
    if not isinstance(code_name, dict) or set(code_name) != {
        "en",
        "zhHant",
        "photoUrl",
    }:
        raise ValueError("verified release manifest needs a complete code name")
    if not all(
        isinstance(code_name.get(key), str) and code_name[key].strip()
        for key in ("en", "zhHant")
    ):
        raise ValueError("release code-name labels must be non-empty")
    photo = urlsplit(str(code_name.get("photoUrl", "")))
    if (
        photo.scheme != "https"
        or photo.netloc != EXPECTED_GITHUB_HOST
        or photo.username
        or photo.password
        or photo.query
        or photo.fragment
        or not photo.path.startswith(
            f"{EXPECTED_PHOTO_REPOSITORY}/releases/download/catalog-v1"
        )
        or not photo.path.endswith(".png")
    ):
        raise ValueError("release code-name photo must use the published catalog path")
    delta = manifest.get("delta")
    if (
        not isinstance(delta, dict)
        or set(delta) != {"emitted", "reason"}
        or delta.get("emitted") is not False
        or not isinstance(delta.get("reason"), str)
        or not delta["reason"].strip()
    ):
        raise ValueError("verified release manifest must record the no-delta state")
    timing = manifest.get("workflowTiming")
    if not isinstance(timing, dict) or set(timing) != {
        "started",
        "completed",
        "duration",
    }:
        raise ValueError("verified release manifest needs complete workflow timing")
    started_text = timing.get("started")
    completed_text = timing.get("completed")
    duration_text = timing.get("duration")
    if not all(
        isinstance(value, str) and UTC_TIMESTAMP.fullmatch(value)
        for value in (started_text, completed_text)
    ):
        raise ValueError("workflow timing timestamps must use UTC ISO-8601 seconds")
    duration_match = (
        DURATION.fullmatch(duration_text) if isinstance(duration_text, str) else None
    )
    if not duration_match:
        raise ValueError("workflow duration must use HH:mm:ss")
    started = datetime.strptime(started_text, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    completed = datetime.strptime(completed_text, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    hours, minutes, seconds = map(int, duration_match.groups())
    recorded_seconds = hours * 3600 + minutes * 60 + seconds
    if (
        completed <= started
        or int((completed - started).total_seconds()) != recorded_seconds
    ):
        raise ValueError("workflow timing duration does not match its timestamps")
    if completed_text != published_at:
        raise ValueError("workflow completion must match the verified publication time")
    if set(assets) != set(ASSET_KEYS):
        raise ValueError(
            "verified release manifest must contain Setup.exe, RELEASES, and full.nupkg"
        )
    for key, asset in assets.items():
        _validate_asset(key, asset, release_tag)
    return manifest


def validate_github_release_api(manifest: dict, release: object) -> None:
    """Compare committed release facts with one GitHub release API response."""

    if not isinstance(release, dict):
        raise ValueError("GitHub release API evidence must be an object")
    if release.get("draft") is not False or release.get("prerelease") is not False:
        raise ValueError("GitHub release API evidence must identify a published release")
    if release.get("tag_name") != manifest["releaseTag"]:
        raise ValueError("GitHub release API tag does not match the manifest")
    if release.get("html_url") != manifest["releaseUrl"]:
        raise ValueError("GitHub release API URL does not match the manifest")
    if release.get("published_at") != manifest["publishedAt"]:
        raise ValueError("GitHub release API publication time does not match the manifest")
    api_assets = release.get("assets")
    if not isinstance(api_assets, list):
        raise ValueError("GitHub release API evidence has no asset list")
    by_name: dict[str, dict] = {}
    for asset in api_assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise ValueError("GitHub release API contains an invalid asset record")
        if asset["name"] in by_name:
            raise ValueError("GitHub release API contains duplicate asset names")
        by_name[asset["name"]] = asset
    for expected in manifest["assets"].values():
        actual = by_name.get(expected["name"])
        if actual is None:
            raise ValueError(f"GitHub release API is missing {expected['name']}")
        if actual.get("size") != expected["bytes"]:
            raise ValueError(f"GitHub release API size differs for {expected['name']}")
        if actual.get("digest") != f"sha256:{expected['sha256']}":
            raise ValueError(f"GitHub release API digest differs for {expected['name']}")
        if actual.get("browser_download_url") != expected["url"]:
            raise ValueError(f"GitHub release API URL differs for {expected['name']}")


def validate_bundle(site_dir: Path) -> dict:
    config = validate_site_config(site_dir / "site-config.json")
    manifest_path = site_dir / config["releaseManifest"]
    manifest = validate_release_manifest(manifest_path)
    validate_article_catalog(site_dir / config["articles"])
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("site_dir", type=Path)
    parser.add_argument("--github-api-json", type=Path)
    args = parser.parse_args()
    manifest = validate_bundle(args.site_dir)
    if args.github_api_json:
        validate_github_release_api(manifest, _read_json(args.github_api_json))
    print(f"Site publication contract verified: {args.site_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
