#!/usr/bin/env python3
"""Create a deterministic ZIP from a materialized repository or kit."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import stat
import zipfile

EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    ".idea",
    ".vscode",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".pre-m3-completion"}
ZIP_TIME = (2026, 8, 10, 0, 0, 0)


def _include(path: Path, source: Path) -> bool:
    relative = path.relative_to(source)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if path.name in {"Thumbs.db", ".DS_Store"}:
        return False
    return not any(path.name.endswith(suffix) for suffix in EXCLUDED_SUFFIXES)


def package(source: Path, output: Path, prefix: str) -> tuple[int, str]:
    source = source.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Source directory does not exist: {source}")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and _include(path, source) and path.resolve() != output
    )
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in files:
            relative = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(f"{prefix.rstrip('/')}/{relative}", ZIP_TIME)
            mode = path.stat().st_mode
            permissions = 0o755 if mode & stat.S_IXUSR else 0o644
            info.external_attr = (stat.S_IFREG | permissions) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest}  {output.name}\n", encoding="utf-8", newline="\n"
    )
    return len(files), digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", "--repo", dest="source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prefix", default="material-minecraft-map-editor-m3-complete")
    args = parser.parse_args()
    count, digest = package(args.source, args.output, args.prefix)
    print(f"Packaged {count} files: {args.output}")
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
