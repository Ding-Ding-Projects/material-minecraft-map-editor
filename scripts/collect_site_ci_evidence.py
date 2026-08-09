"""Collect a bounded, explicitly safe site CI evidence directory."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
SAFE_INPUTS = {
    "staging-decision.txt": "staging-decision.txt",
    "github-cli-version.txt": "github-cli-version.txt",
    "chrome-version.txt": "chrome-version.txt",
    "docker-version.txt": "docker-version.txt",
    "site-tests.xml": "site-tests.xml",
    "release-api.json": "release-api.json",
    "site-cdp-report.json": "site-cdp-report.json",
    "site-http-runtime.txt": "site-http-runtime.txt",
    "chrome-runtime.log": "chrome-runtime.log",
}


def copy_bounded(source: Path, destination: Path) -> dict:
    size = source.stat().st_size
    copied = min(size, MAX_FILE_BYTES)
    with source.open("rb") as reader, destination.open("wb") as writer:
        remaining = copied
        while remaining:
            chunk = reader.read(min(64 * 1024, remaining))
            if not chunk:
                break
            writer.write(chunk)
            remaining -= len(chunk)
    return {"sourceBytes": size, "copiedBytes": copied, "truncated": size > copied}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    source_root = args.input.resolve()
    output.mkdir(parents=True, exist_ok=True)
    copied: dict[str, dict] = {}
    for source_name, destination_name in SAFE_INPUTS.items():
        source = source_root / source_name
        if source.is_file() and not source.is_symlink():
            copied[destination_name] = copy_bounded(source, output / destination_name)
    context = {
        "schemaVersion": 1,
        "runId": os.environ.get("CI_RUN_ID", "unavailable"),
        "runAttempt": os.environ.get("CI_RUN_ATTEMPT", "unavailable"),
        "commitSha": os.environ.get("CI_COMMIT_SHA", "unavailable"),
        "jobStatus": os.environ.get("CI_JOB_STATUS", "unavailable"),
        "runner": {
            "os": os.environ.get("CI_RUNNER_OS", "unavailable"),
            "arch": os.environ.get("CI_RUNNER_ARCH", "unavailable"),
            "environment": os.environ.get("CI_RUNNER_ENVIRONMENT", "unavailable"),
            "name": os.environ.get("CI_RUNNER_NAME", "unavailable"),
        },
        "files": copied,
    }
    (output / "context.json").write_text(
        json.dumps(context, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    total = sum(path.stat().st_size for path in output.iterdir() if path.is_file())
    if total > MAX_TOTAL_BYTES:
        raise SystemExit(f"bounded site evidence is too large: {total} bytes")
    print(f"Collected {len(copied)} safe evidence files ({total} bytes) at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
