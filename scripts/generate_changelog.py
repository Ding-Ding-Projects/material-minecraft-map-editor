#!/usr/bin/env python3
"""Generate the bundled changelog catalog from reachable Git release tags."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Sequence

SCHEMA_VERSION = 1
DEFAULT_REPOSITORY_URL = (
    "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor"
)


def _git(repo: Path, arguments: Sequence[str]) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def classify_action(subject: str) -> str:
    """Apply a documented, deterministic category to an unchanged Git subject."""

    first_word = subject.lstrip().split(maxsplit=1)[0].casefold().rstrip(":")
    if first_word in {"add", "adds", "added", "enable", "implement", "introduce"}:
        return "added"
    if first_word in {"fix", "fixes", "fixed", "repair", "correct"}:
        return "fixed"
    if first_word in {"remove", "removes", "removed", "delete", "drop", "disable"}:
        return "removed"
    return "changed"


def generate_catalog(repo: Path, repository_url: str) -> dict[str, object]:
    head = _git(repo, ["rev-parse", "HEAD"])
    tags = _git(
        repo,
        [
            "for-each-ref",
            "--merged=HEAD",
            "--sort=-creatordate",
            "--format=%(refname:strip=2)",
            "refs/tags",
        ],
    ).splitlines()
    entries = []
    for tag in tags:
        revision = _git(repo, ["rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"])
        # A release workflow creates its lightweight tag after the source
        # commit has already been built.  A tag pointing at this exact
        # checkout therefore describes publication *after* this catalog
        # snapshot, not a release that was reachable when the snapshot was
        # generated.  Ancestor tags remain required and are included below.
        if revision == head:
            continue
        record = _git(
            repo,
            ["show", "-s", "--format=%cs%x1f%s", "--end-of-options", revision],
        )
        released_on, subject = record.split("\x1f", 1)
        entries.append(
            {
                "version": tag,
                "released_on": released_on,
                "commit_sha": revision,
                "changes": [
                    {
                        "action": classify_action(subject),
                        "summary": subject,
                        "commit_sha": revision,
                    }
                ],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "repository_url": repository_url.removesuffix("/").removesuffix(".git"),
        "source_revision": head,
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("amulet_map_editor/api/changelog_catalog.json"),
    )
    parser.add_argument("--repository-url", default=DEFAULT_REPOSITORY_URL)
    arguments = parser.parse_args()
    repo = arguments.repo.resolve()
    output = arguments.output
    if not output.is_absolute():
        output = repo / output
    catalog = generate_catalog(repo, arguments.repository_url)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(catalog['entries'])} tagged releases to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
