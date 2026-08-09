from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE_WORKFLOW = (ROOT / ".github" / "workflows" / "site.yml").read_text(
    encoding="utf-8"
)
BUILD_WORKFLOW = (ROOT / ".github" / "workflows" / "build-windows.yml").read_text(
    encoding="utf-8"
)


def test_workflow_run_is_same_repo_successful_default_branch_push_only():
    required = (
        "workflow_run:",
        'workflows: ["Build Windows"]',
        "github.event.workflow_run.conclusion == 'success'",
        "github.event.workflow_run.event == 'push'",
        "github.event.workflow_run.head_repository.full_name == github.repository",
        "github.event.workflow_run.head_branch == github.event.repository.default_branch",
        "ref: ${{ github.event.workflow_run.head_sha }}",
        "persist-credentials: false",
    )
    for value in required:
        assert value in SITE_WORKFLOW


def test_post_release_staging_is_serial_non_mutating_and_order_guarded():
    stage = SITE_WORKFLOW[SITE_WORKFLOW.index("  stage-post-release:") :]
    assert "cancel-in-progress: false" in stage
    assert "contents: read" in stage
    assert "gh run download \"$TRIGGER_RUN_ID\"" in stage
    assert "--latest-successful-run-id \"$LATEST_RUN_ID\"" in stage
    assert stage.count("gh run list") >= 2
    assert "A newer successful Build Windows run exists" in stage
    for forbidden in ("git push", "git commit", "gh release", "contents: write"):
        assert forbidden not in SITE_WORKFLOW


def test_build_windows_uploads_only_the_api_verified_tiny_handoff():
    publish = BUILD_WORKFLOW[BUILD_WORKFLOW.index("  publish:") :]
    assert "scripts/create_site_release_handoff.py" in publish
    assert 'gh api "/repos/$GITHUB_REPOSITORY/releases/tags/$tag"' in publish
    assert "name: amulet-release-handoff-${{ github.run_id }}" in publish
    assert "path: release-handoff/site-release-handoff.json" in publish
    assert "if-no-files-found: error" in publish


def test_runtime_bootstrap_is_pinned_and_cache_miss_capable():
    expected = {
        "browser-actions/setup-chrome@2e1d749697dd1612b833dba4a722266286fbefcd": "151.0.7922.47",
        "docker/setup-docker-action@77e84dbf09b47d1e29270283c22f16145aa85ca1": "29.6.2",
        "docker/setup-buildx-action@bb05f3f5519dd87d3ba754cc423b652a5edd6d2c": "v0.36.1",
    }
    for action, version in expected.items():
        assert action in SITE_WORKFLOW
        assert version in SITE_WORKFLOW
    inventory = json.loads(
        (ROOT / "docs" / "site" / "ci-job-inventory.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(inventory["jobs"]) == {"validate-source", "stage-post-release"}
    assert all(job["freshEnvironmentProof"] for job in inventory["jobs"].values())
    assert inventory["prohibitedDependencies"] == [
        "code-signing certificate",
        "signing credential",
        "signer service",
    ]


def test_runtime_expectations_are_manifest_parameterized_and_sites_are_separate():
    cdp = (ROOT / "scripts" / "verify_site_cdp.mjs").read_text(encoding="utf-8")
    http = (ROOT / "scripts" / "verify_site_http_runtime.py").read_text(
        encoding="utf-8"
    )
    docs = (ROOT / "docs" / "site" / "README.md").read_text(encoding="utf-8")
    assert "--expected-manifest" in cdp
    assert "--expected-manifest" in http
    assert "0.10.0-dev.426" not in cdp
    assert "0.10.0-dev.426" not in http
    assert "separately controlled Sites source repository" in docs
    assert "mustRecheckLatestRunBeforePromotion" in (
        ROOT / "scripts" / "stage_site_release_handoff.py"
    ).read_text(encoding="utf-8")
