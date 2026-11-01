#!/usr/bin/env python3
"""Generate the bundled changelog catalog from reachable Git release tags."""

from __future__ import annotations

import argparse
import json
import sys
import subprocess
from pathlib import Path
from typing import Sequence

# Isolated Python excludes the script directory; import only this trusted sibling.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from publication_policy import PublicationPolicy, PublicationPolicyError, read_policy

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


def sanitise_subject(subject: str, policy: PublicationPolicy) -> str:
    """Apply explicit externally validated literal publication rules."""
    if not isinstance(policy, PublicationPolicy):
        raise PublicationPolicyError("Validated publication policy required")
    return policy.sanitise(subject)

def classify_action(subject: str) -> str:
    """Apply a documented, deterministic category to an unchanged Git subject."""

    words = subject.lstrip().split(maxsplit=1)
    first_word = words[0].casefold().rstrip(":") if words else ""
    if first_word in {"add", "adds", "added", "enable", "implement", "introduce"}:
        return "added"
    if first_word in {"fix", "fixes", "fixed", "repair", "correct"}:
        return "fixed"
    if first_word in {"remove", "removes", "removed", "delete", "drop", "disable"}:
        return "removed"
    return "changed"


def generate_catalog(repo: Path, repository_url: str, policy: PublicationPolicy) -> dict[str, object]:
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
                        "summary": sanitise_subject(subject, policy),
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
    parser.add_argument("--policy-stdin", action="store_true", required=True,
                        help="Read versioned publication policy from standard input")
    arguments = parser.parse_args()
    try:
        policy = read_policy(sys.stdin.buffer)
    except PublicationPolicyError:
        parser.exit(2, "Publication policy validation failed\n")
    repo = arguments.repo.resolve()
    output = arguments.output
    if not output.is_absolute():
        output = repo / output
    try:
        catalog = generate_catalog(repo, arguments.repository_url, policy)
        rendered = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
        policy.assert_clean(rendered)
    except PublicationPolicyError:
        parser.exit(2, "Publication content validation failed\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        rendered, encoding="utf-8"
    )
    print(f"Wrote {len(catalog['entries'])} tagged releases to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
