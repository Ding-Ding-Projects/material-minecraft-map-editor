#!/usr/bin/env python3
"""Print the reproducible line and surviving-authorship table used by releases.

Only Git-tracked, line-oriented text files are counted.  Hand-written project
code is separated from generated and deliberately excluded text, while binary
assets remain outside a line-based metric.  Attribution comes from ``git
blame`` at the checked-out revision so deleted churn never inflates either
author class.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

COUNTED_SUFFIXES = {
    ".bat",
    ".cfg",
    ".cmd",
    ".conf",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".ps1",
    ".psm1",
    ".py",
    ".pyi",
    ".rst",
    ".sh",
    ".spec",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".xsd",
    ".yaml",
    ".yml",
}
COUNTED_FILENAMES = {
    ".dockerignore",
    ".gitattributes",
    ".gitignore",
    "Dockerfile",
    "Makefile",
}
GENERATED_PATHS = {
    "amulet_map_editor/api/changelog_catalog.json",
    "amulet_map_editor/api/docs_articles.json",
}
EXCLUDED_PATHS = {
    # A legacy distribution-channel notice, not application source.
    "amulet_app.exe.txt",
}
EXCLUDED_PARTS = {
    ".venv",
    "build",
    "dist",
    "node_modules",
    "third-party",
    "third_party",
    "vendor",
    "vendored",
    "venv",
}
LOCKFILE_NAMES = {
    "cargo.lock",
    "composer.lock",
    "package-lock.json",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}
MARKUP_SUFFIXES = {".css", ".html", ".js", ".md", ".mjs", ".rst"}
DETAIL_ROWS = ("source", "tests", "styles-markup", "generated", "excluded")
_BLAME_HEADER = re.compile(r"^(?P<sha>[0-9a-f]{40,64})\s+\d+\s+\d+(?:\s+\d+)?$")
_COAUTHOR = re.compile(
    r"^Co-Authored-By:\s*(?P<identity>.+)$", re.IGNORECASE | re.MULTILINE
)
_AGENT_IDENTITY = re.compile(
    r"\b(?:agent|anthropic|automation|bot|claude|codex|copilot|github-actions|openai)\b",
    re.IGNORECASE,
)


@dataclass
class LineRow:
    total_lines: int = 0
    nonblank_lines: int = 0
    agent_lines: int = 0
    person_lines: int = 0
    unattributed_lines: int = 0

    def add(self, other: "LineRow") -> None:
        self.total_lines += other.total_lines
        self.nonblank_lines += other.nonblank_lines
        self.agent_lines += other.agent_lines
        self.person_lines += other.person_lines
        self.unattributed_lines += other.unattributed_lines

    def validate(self, label: str) -> None:
        attributed = self.agent_lines + self.person_lines + self.unattributed_lines
        if attributed != self.total_lines:
            raise RuntimeError(
                f"attribution mismatch for {label}: {attributed} != {self.total_lines}"
            )
        if self.nonblank_lines > self.total_lines:
            raise RuntimeError(
                f"nonblank line count exceeds total for {label}: "
                f"{self.nonblank_lines} > {self.total_lines}"
            )


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def tracked_paths(root: Path = ROOT) -> list[PurePosixPath]:
    output = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    return [
        PurePosixPath(item.decode("utf-8", errors="surrogateescape"))
        for item in output.split(b"\0")
        if item
    ]


def is_counted_text(path: PurePosixPath) -> bool:
    return path.name in COUNTED_FILENAMES or path.suffix.lower() in COUNTED_SUFFIXES


def classify(path: PurePosixPath) -> str:
    text = path.as_posix()
    lower_name = path.name.lower()
    if text in GENERATED_PATHS:
        return "generated"
    if (
        text in EXCLUDED_PATHS
        or lower_name in LOCKFILE_NAMES
        or lower_name.endswith(".lock")
        or any(part.lower() in EXCLUDED_PARTS for part in path.parts)
    ):
        return "excluded"
    if path.parts and path.parts[0] == "tests":
        return "tests"
    if (
        path.parts and path.parts[0] == "docs"
    ) or path.suffix.lower() in MARKUP_SUFFIXES:
        return "styles-markup"
    return "source"


def _is_agent_identity(identity: str) -> bool:
    return bool(_AGENT_IDENTITY.search(identity))


def agent_commit_map(root: Path = ROOT) -> dict[str, bool]:
    # Record separators keep arbitrary multiline commit bodies intact.
    log = _git(root, "log", "--format=%H%x1f%an%x1f%ae%x1f%B%x1e", "HEAD")
    commits: dict[str, bool] = {}
    for record in log.split("\x1e"):
        record = record.strip("\r\n")
        if not record:
            continue
        fields = record.split("\x1f", 3)
        if len(fields) != 4:
            raise RuntimeError("could not parse Git commit metadata for attribution")
        sha, author_name, author_email, body = fields
        coauthors = (match.group("identity") for match in _COAUTHOR.finditer(body))
        commits[sha] = _is_agent_identity(f"{author_name} <{author_email}>") or any(
            _is_agent_identity(identity) for identity in coauthors
        )
    return commits


def _line_counts(path: Path) -> tuple[int, int]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return len(lines), sum(bool(line.strip()) for line in lines)


def _blame_counts(
    root: Path, path: PurePosixPath, agent_commits: dict[str, bool]
) -> tuple[int, int, int]:
    blame = _git(root, "blame", "--line-porcelain", "--", path.as_posix())
    agent = person = unattributed = 0
    for line in blame.splitlines():
        match = _BLAME_HEADER.fullmatch(line)
        if not match:
            continue
        sha = match.group("sha")
        if not sha.strip("0") or sha not in agent_commits:
            unattributed += 1
        elif agent_commits[sha]:
            agent += 1
        else:
            person += 1
    return agent, person, unattributed


def collect_rows(root: Path = ROOT) -> dict[str, LineRow]:
    rows = {name: LineRow() for name in DETAIL_ROWS}
    commits = agent_commit_map(root)
    for relative in tracked_paths(root):
        if not is_counted_text(relative):
            continue
        total, nonblank = _line_counts(root / Path(relative.as_posix()))
        agent, person, unattributed = _blame_counts(root, relative, commits)
        file_row = LineRow(total, nonblank, agent, person, unattributed)
        file_row.validate(relative.as_posix())
        rows[classify(relative)].add(file_row)

    project = LineRow()
    for name in ("source", "tests", "styles-markup"):
        project.add(rows[name])
    rows["project-total"] = project

    grand = LineRow()
    for name in DETAIL_ROWS:
        grand.add(rows[name])
    rows["repository-grand-total"] = grand

    for name, row in rows.items():
        row.validate(name)
    return rows


def write_csv(rows: dict[str, LineRow], output: object = sys.stdout) -> None:
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "category",
            "total_lines",
            "nonblank_lines",
            "agent_lines",
            "person_lines",
            "unattributed_lines",
        )
    )
    for name in (*DETAIL_ROWS, "project-total", "repository-grand-total"):
        row = rows[name]
        writer.writerow(
            (
                name,
                row.total_lines,
                row.nonblank_lines,
                row.agent_lines,
                row.person_lines,
                row.unattributed_lines,
            )
        )


def main() -> None:
    write_csv(collect_rows())


if __name__ == "__main__":
    main()
