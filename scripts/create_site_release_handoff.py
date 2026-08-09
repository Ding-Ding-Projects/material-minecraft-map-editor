"""Create the tiny, API-verified handoff consumed by the post-release site job."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from verify_site_release_manifest import (
    EXPECTED_GITHUB_HOST,
    EXPECTED_RELEASE_REPOSITORY,
    validate_github_release_api,
    validate_release_manifest,
)

EXPECTED_REPOSITORY = EXPECTED_RELEASE_REPOSITORY.lstrip("/")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _code_name(value: str) -> tuple[str, str]:
    english, separator, cantonese = value.partition(" · ")
    if separator != " · " or not english.strip() or not cantonese.strip():
        raise ValueError("release code name must contain exact English · zh-Hant labels")
    return english.strip(), cantonese.strip()


def create_handoff(
    *,
    release: dict,
    assets_dir: Path,
    repository: str,
    workflow_run_id: int,
    workflow_run_number: int,
    head_sha: str,
    tag: str,
    started: str,
    completed: str,
    duration: str,
    code_name: str,
    photo_url: str,
) -> dict:
    if repository != EXPECTED_REPOSITORY:
        raise ValueError("release handoff repository is not the expected owner/repository")
    if not isinstance(workflow_run_id, int) or workflow_run_id <= 0:
        raise ValueError("release handoff workflow run id must be positive")
    if not isinstance(workflow_run_number, int) or workflow_run_number <= 0:
        raise ValueError("release handoff workflow run number must be positive")
    if not COMMIT.fullmatch(head_sha):
        raise ValueError("release handoff head SHA must be an exact lowercase commit")
    if not TAG.fullmatch(tag):
        raise ValueError("release handoff tag is invalid")
    if release.get("draft") is not False or release.get("prerelease") is not False:
        raise ValueError("release handoff requires a published non-prerelease release")
    if release.get("tag_name") != tag:
        raise ValueError("release API tag differs from the workflow release tag")
    if release.get("target_commitish") != head_sha:
        raise ValueError("release API target differs from the workflow head SHA")
    if release.get("published_at") != completed:
        raise ValueError("release API publication timestamp differs from workflow timing")
    release_url = (
        f"https://{EXPECTED_GITHUB_HOST}{EXPECTED_RELEASE_REPOSITORY}/releases/tag/{tag}"
    )
    if release.get("html_url") != release_url:
        raise ValueError("release API URL differs from the expected owner/repository/tag")

    api_assets = release.get("assets")
    if not isinstance(api_assets, list) or not api_assets:
        raise ValueError("release API has no published assets")
    local_files = {
        path.name: path for path in assets_dir.rglob("*") if path.is_file()
    }
    published_assets: list[dict] = []
    seen: set[str] = set()
    for asset in api_assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise ValueError("release API has an invalid asset record")
        name = asset["name"]
        if name in seen:
            raise ValueError(f"release API repeats asset {name}")
        seen.add(name)
        local = local_files.get(name)
        if local is None:
            raise ValueError(f"published release asset {name} is absent from the build output")
        size = local.stat().st_size
        digest = _sha256(local)
        expected_url = (
            f"https://{EXPECTED_GITHUB_HOST}{EXPECTED_RELEASE_REPOSITORY}"
            f"/releases/download/{tag}/{name}"
        )
        url = asset.get("browser_download_url")
        parsed = urlsplit(str(url or ""))
        if (
            url != expected_url
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"published release asset {name} has an invalid URL")
        if asset.get("size") != size:
            raise ValueError(f"published release asset {name} has a size mismatch")
        if asset.get("digest") != f"sha256:{digest}":
            raise ValueError(f"published release asset {name} has a digest mismatch")
        published_assets.append(
            {"name": name, "url": expected_url, "bytes": size, "sha256": digest}
        )

    by_name = {asset["name"]: asset for asset in published_assets}
    full_names = sorted(name for name in by_name if name.endswith("-full.nupkg"))
    if set(("Setup.exe", "RELEASES")) - set(by_name) or len(full_names) != 1:
        raise ValueError("release must contain Setup.exe, RELEASES, and one full package")
    delta_names = sorted(name for name in by_name if name.endswith("-delta.nupkg"))
    english_name, cantonese_name = _code_name(code_name)
    manifest = {
        "schemaVersion": 1,
        "verified": True,
        "releaseTag": tag,
        "commit": head_sha,
        "releaseUrl": release_url,
        "publishedAt": completed,
        "codeName": {
            "en": english_name,
            "zhHant": cantonese_name,
            "photoUrl": photo_url,
        },
        "delta": {
            "emitted": bool(delta_names),
            "reason": (
                f"Published delta assets: {', '.join(delta_names)}."
                if delta_names
                else "RELEASES contains the current full package only; no delta asset was emitted."
            ),
        },
        "workflowTiming": {
            "started": started,
            "completed": completed,
            "duration": duration,
        },
        "assets": {
            "Setup.exe": by_name["Setup.exe"],
            "RELEASES": by_name["RELEASES"],
            "full.nupkg": by_name[full_names[0]],
        },
    }
    with tempfile.TemporaryDirectory() as temporary:
        manifest_path = Path(temporary) / "release-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        validate_release_manifest(manifest_path)
    validate_github_release_api(manifest, release)
    release_id = release.get("id")
    if not isinstance(release_id, int) or release_id <= 0:
        raise ValueError("release API is missing its numeric release id")
    return {
        "schemaVersion": 1,
        "repository": repository,
        "sourceWorkflow": "Build Windows",
        "sourceWorkflowFile": ".github/workflows/build-windows.yml",
        "workflowRunId": workflow_run_id,
        "workflowRunNumber": workflow_run_number,
        "headSha": head_sha,
        "releaseId": release_id,
        "releaseTag": tag,
        "releaseManifest": manifest,
        "publishedAssets": published_assets,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-api", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument("--workflow-run-number", type=int, required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--started", required=True)
    parser.add_argument("--completed", required=True)
    parser.add_argument("--duration", required=True)
    parser.add_argument("--code-name", required=True)
    parser.add_argument("--photo-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    handoff = create_handoff(
        release=_read_object(args.release_api),
        assets_dir=args.assets_dir.resolve(),
        repository=args.repository,
        workflow_run_id=args.workflow_run_id,
        workflow_run_number=args.workflow_run_number,
        head_sha=args.head_sha,
        tag=args.tag,
        started=args.started,
        completed=args.completed,
        duration=args.duration,
        code_name=args.code_name,
        photo_url=args.photo_url,
    )
    _atomic_json(args.output.resolve(), handoff)
    print(
        "Created API-verified site release handoff for "
        f"run {handoff['workflowRunId']} / {handoff['releaseTag']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
