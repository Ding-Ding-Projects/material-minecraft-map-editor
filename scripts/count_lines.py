#!/usr/bin/env python3
"""Print the reproducible source/test/markup line table used by releases."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "dist", "build"}


def bucket(path: Path) -> str:
    text = path.as_posix()
    if text.startswith("tests/"):
        return "tests"
    if text.startswith("docs/") or path.suffix.lower() in {".html", ".css", ".js"}:
        return "styles-markup"
    return "source"


def count(path: Path) -> tuple[int, int]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return len(lines), sum(bool(line.strip()) for line in lines)


totals: dict[str, list[int]] = {key: [0, 0] for key in ("source", "tests", "styles-markup")}
for path in ROOT.rglob("*"):
    if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
        continue
    if path.suffix.lower() not in {".py", ".md", ".rst", ".txt", ".html", ".css", ".js", ".yml", ".yaml"}:
        continue
    key = bucket(path.relative_to(ROOT))
    total, nonblank = count(path)
    totals[key][0] += total
    totals[key][1] += nonblank

print("category,total_lines,nonblank_lines")
for key in ("source", "tests", "styles-markup"):
    print(f"{key},{totals[key][0]},{totals[key][1]}")
print(f"total,{sum(v[0] for v in totals.values())},{sum(v[1] for v in totals.values())}")
