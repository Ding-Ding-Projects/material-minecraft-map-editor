"""Fail when the site workflow and its dependency inventory diverge."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "site" / "ci-job-inventory.json"


def main() -> int:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    if inventory.get("schemaVersion") != 2:
        raise SystemExit("site CI inventory schemaVersion must be 2")
    workflow_path = ROOT / inventory["workflow"]
    workflow = workflow_path.read_text(encoding="utf-8")
    collector = (ROOT / "scripts" / "collect_site_ci_evidence.py").read_text(
        encoding="utf-8"
    )
    jobs_block = workflow.split("\njobs:\n", 1)
    if len(jobs_block) != 2:
        raise SystemExit("site workflow has no jobs mapping")
    actual_jobs = set(
        re.findall(r"^  ([a-zA-Z0-9_-]+):\s*$", jobs_block[1], re.MULTILINE)
    )
    expected_jobs = set(inventory.get("jobs", {}))
    if actual_jobs != expected_jobs:
        raise SystemExit(
            f"site workflow jobs {sorted(actual_jobs)} differ from inventory {sorted(expected_jobs)}"
        )
    for job, record in inventory["jobs"].items():
        dependencies = record.get("dependencies")
        evidence = record.get("requiredEvidence")
        if not isinstance(dependencies, list) or not dependencies:
            raise SystemExit(f"site CI job {job} has no dependency inventory")
        if not isinstance(evidence, list) or not evidence:
            raise SystemExit(f"site CI job {job} has no evidence inventory")
        fresh_environment = record.get("freshEnvironmentProof")
        if not isinstance(fresh_environment, str) or not fresh_environment.strip():
            raise SystemExit(f"site CI job {job} has no cache-miss bootstrap proof")
        for dependency in dependencies:
            if set(dependency) != {"name", "constraint", "source", "bootstrap"}:
                raise SystemExit(f"site CI job {job} has an incomplete dependency record")
            if not all(isinstance(value, str) and value for value in dependency.values()):
                raise SystemExit(f"site CI job {job} has an empty dependency field")
        missing_evidence = [
            name
            for name in evidence
            if name != "context.json" and f'"{name}"' not in collector
        ]
        if missing_evidence:
            raise SystemExit(
                f"site CI job {job} evidence is not collected safely: {missing_evidence}"
            )
    required_contracts = (
        "workflow_run:",
        'workflows: ["Build Windows"]',
        "github.event.workflow_run.head_repository.full_name == github.repository",
        "github.event.workflow_run.head_branch == github.event.repository.default_branch",
        "cancel-in-progress: false",
        "persist-credentials: false",
        "gh run download",
        "scripts/stage_site_release_handoff.py",
        "--latest-successful-run-id",
        "--expected-manifest build/site/release-manifest.json",
        "browser-actions/setup-chrome@2e1d749697dd1612b833dba4a722266286fbefcd",
        "chrome-version: 151.0.7922.47",
        "docker/setup-docker-action@77e84dbf09b47d1e29270283c22f16145aa85ca1",
        "version: type=archive,version=29.6.2",
        "docker/setup-buildx-action@bb05f3f5519dd87d3ba754cc423b652a5edd6d2c",
        "version: v0.36.1",
        "docker info",
        "scripts/verify_site_http_runtime.py",
        "scripts/verify_site_cdp.mjs",
        "scripts/collect_site_ci_evidence.py",
        "if: ${{ always() }}",
        "github.run_id",
        "github.sha",
        "job.status",
        "runner.os",
        "runner.arch",
    )
    missing = [value for value in required_contracts if value not in workflow]
    if missing:
        raise SystemExit(f"site workflow is missing CI contracts: {missing}")
    prohibited = ("git push", "git commit", "gh release", "contents: write")
    present = [value for value in prohibited if value in workflow]
    if present:
        raise SystemExit(
            f"site staging workflow must not mutate the base repository or releases: {present}"
        )
    handoff_path = ROOT / inventory["releaseHandoffWorkflow"]
    handoff_workflow = handoff_path.read_text(encoding="utf-8")
    handoff_contracts = (
        "scripts/create_site_release_handoff.py",
        "gh api \"/repos/$GITHUB_REPOSITORY/releases/tags/$tag\"",
        "amulet-release-handoff-${{ github.run_id }}",
        "release-handoff/site-release-handoff.json",
        "if-no-files-found: error",
    )
    missing_handoff = [
        value for value in handoff_contracts if value not in handoff_workflow
    ]
    if missing_handoff:
        raise SystemExit(
            f"Build Windows is missing release handoff contracts: {missing_handoff}"
        )
    prohibited_dependencies = inventory.get("prohibitedDependencies")
    if not isinstance(prohibited_dependencies, list) or len(prohibited_dependencies) != 3:
        raise SystemExit("site CI inventory must explicitly prohibit signing dependencies")
    print(
        f"Site CI inventory verified: {len(actual_jobs)} jobs, complete fresh-environment "
        "dependencies, bounded evidence, and non-mutating release staging"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
