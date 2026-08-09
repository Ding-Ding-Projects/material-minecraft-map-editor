"""Fail when the site workflow and its dependency inventory diverge."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "site" / "ci-job-inventory.json"


def main() -> int:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    if inventory.get("schemaVersion") != 1:
        raise SystemExit("site CI inventory schemaVersion must be 1")
    workflow_path = ROOT / inventory["workflow"]
    workflow = workflow_path.read_text(encoding="utf-8")
    jobs_block = workflow.split("\njobs:\n", 1)
    if len(jobs_block) != 2:
        raise SystemExit("site workflow has no jobs mapping")
    actual_jobs = set(
        re.findall(r"^  ([a-zA-Z0-9_-]+):\n    runs-on:", jobs_block[1], re.MULTILINE)
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
        for dependency in dependencies:
            if set(dependency) != {"name", "constraint", "source", "bootstrap"}:
                raise SystemExit(f"site CI job {job} has an incomplete dependency record")
            if not all(isinstance(value, str) and value for value in dependency.values()):
                raise SystemExit(f"site CI job {job} has an empty dependency field")
    required_contracts = (
        "docker/setup-buildx-action@v3",
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
    print(f"Site CI inventory verified: {len(actual_jobs)} job, complete dependencies and evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
