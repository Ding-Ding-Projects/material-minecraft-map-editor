"""Validate one Build Windows handoff and atomically stage its site manifest."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from create_site_release_handoff import EXPECTED_REPOSITORY
from verify_site_release_manifest import (
    validate_github_release_api,
    validate_release_manifest,
)


class OutOfOrderHandoff(ValueError):
    """The triggering run is older than the newest successful default-branch run."""


def _read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


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


def stage_handoff(
    *,
    handoff: dict,
    release: dict,
    expected_repository: str,
    expected_workflow_run_id: int,
    expected_workflow_run_number: int,
    expected_head_sha: str,
    expected_tag: str,
    latest_successful_run_id: int,
) -> tuple[dict, dict]:
    if latest_successful_run_id != expected_workflow_run_id:
        raise OutOfOrderHandoff(
            f"run {expected_workflow_run_id} is older than successful run "
            f"{latest_successful_run_id}; staging is a no-op"
        )
    expected = {
        "schemaVersion": 1,
        "repository": expected_repository,
        "sourceWorkflow": "Build Windows",
        "sourceWorkflowFile": ".github/workflows/build-windows.yml",
        "workflowRunId": expected_workflow_run_id,
        "workflowRunNumber": expected_workflow_run_number,
        "headSha": expected_head_sha,
        "releaseTag": expected_tag,
    }
    allowed_keys = set(expected) | {"releaseId", "releaseManifest", "publishedAssets"}
    if set(handoff) != allowed_keys:
        raise ValueError("release handoff fields differ from the exact schema")
    for key, value in expected.items():
        if handoff.get(key) != value:
            raise ValueError(f"release handoff {key} differs from the triggering run")
    if expected_repository != EXPECTED_REPOSITORY:
        raise ValueError("triggering repository is not the expected owner/repository")
    if expected_tag != f"0.10.0-dev.{expected_workflow_run_number}":
        raise ValueError("default-branch push release tag does not match its run number")

    manifest = handoff.get("releaseManifest")
    if not isinstance(manifest, dict):
        raise ValueError("release handoff has no site release manifest")
    with tempfile.TemporaryDirectory() as temporary:
        manifest_path = Path(temporary) / "release-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        validate_release_manifest(manifest_path)
    if manifest.get("commit") != expected_head_sha:
        raise ValueError("site release manifest commit differs from the triggering SHA")
    if manifest.get("releaseTag") != expected_tag:
        raise ValueError("site release manifest tag differs from the triggering run")
    validate_github_release_api(manifest, release)

    published = handoff.get("publishedAssets")
    if not isinstance(published, list) or not published:
        raise ValueError("release handoff has no complete published asset inventory")
    api_assets = release.get("assets")
    if not isinstance(api_assets, list):
        raise ValueError("release API has no asset inventory")
    expected_assets = {
        asset.get("name"): {
            "name": asset.get("name"),
            "url": asset.get("browser_download_url"),
            "bytes": asset.get("size"),
            "sha256": str(asset.get("digest", "")).removeprefix("sha256:"),
        }
        for asset in api_assets
        if isinstance(asset, dict) and isinstance(asset.get("name"), str)
    }
    actual_assets = {
        asset.get("name"): asset for asset in published if isinstance(asset, dict)
    }
    if len(actual_assets) != len(published):
        raise ValueError("release handoff asset inventory contains duplicates or invalid rows")
    if actual_assets != expected_assets:
        raise ValueError("release handoff asset inventory differs from the live API")
    release_id = handoff.get("releaseId")
    if not isinstance(release_id, int) or release_id != release.get("id"):
        raise ValueError("release handoff release id differs from the live API")

    staging = {
        "schemaVersion": 1,
        "repository": expected_repository,
        "sourceWorkflow": "Build Windows",
        "sourceWorkflowRunId": expected_workflow_run_id,
        "sourceWorkflowRunNumber": expected_workflow_run_number,
        "sourceSha": expected_head_sha,
        "releaseId": release_id,
        "releaseTag": expected_tag,
        "mustRecheckLatestRunBeforePromotion": True,
    }
    return manifest, staging


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--release-api", type=Path, required=True)
    parser.add_argument("--expected-repository", required=True)
    parser.add_argument("--expected-workflow-run-id", type=int, required=True)
    parser.add_argument("--expected-workflow-run-number", type=int, required=True)
    parser.add_argument("--expected-head-sha", required=True)
    parser.add_argument("--expected-tag", required=True)
    parser.add_argument("--latest-successful-run-id", type=int, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--staging-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest, staging = stage_handoff(
            handoff=_read_object(args.handoff),
            release=_read_object(args.release_api),
            expected_repository=args.expected_repository,
            expected_workflow_run_id=args.expected_workflow_run_id,
            expected_workflow_run_number=args.expected_workflow_run_number,
            expected_head_sha=args.expected_head_sha,
            expected_tag=args.expected_tag,
            latest_successful_run_id=args.latest_successful_run_id,
        )
    except OutOfOrderHandoff as error:
        print(str(error))
        return 20
    _atomic_json(args.manifest_output.resolve(), manifest)
    _atomic_json(args.staging_output.resolve(), staging)
    print(
        "Staged exact release manifest for "
        f"{staging['sourceSha']} / {staging['releaseTag']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
