"""Every article the application ships must actually be in the repository.

A file that exists locally and is excluded by ``.gitignore`` passes every test
on the machine that wrote it and fails on every machine that did not.  That is
how ``docs/features/build/README.md`` reached continuous integration as a
missing file: the unanchored ``build/`` rule matched at any depth and swallowed
an article nobody had reason to suspect.

This checks the two things that failure needed, and neither is expressible as a
rule about content: that each referenced article is tracked by Git, and that no
path the application reads is ignored.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FEATURES = REPO_ROOT / "docs" / "features"


def _tracked_paths() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "docs"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def test_every_feature_article_is_tracked() -> None:
    """An article on disk but not in Git is an article nobody else has."""
    tracked = _tracked_paths()
    on_disk = sorted(
        path.relative_to(REPO_ROOT).as_posix() for path in FEATURES.rglob("README.md")
    )
    assert on_disk, "no feature articles were found at all"
    untracked = [path for path in on_disk if path not in tracked]
    assert not untracked, (
        "these articles exist locally but are not committed, so every other "
        f"machine is missing them: {untracked}"
    )


def test_no_documentation_path_is_ignored() -> None:
    """``.gitignore`` must not match anything under the documentation tree."""
    candidates = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in FEATURES.rglob("*")
        if path.is_file()
    ]
    assert candidates, "no documentation files were found to check"
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=REPO_ROOT,
        input="\n".join(candidates),
        capture_output=True,
        text=True,
        check=False,
    )
    ignored = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert not ignored, (
        "these documentation paths are excluded by .gitignore and will be "
        f"missing everywhere but here: {ignored}"
    )
