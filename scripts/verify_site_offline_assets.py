"""Verify the static site loads no asset from a remote origin.

The site is a dependency-free bundle: every script, stylesheet, font, and image
must resolve inside the bundle so the page works from a file:// preview, an
air-gapped host, and an owner-controlled static host alike. A CDN reference is
easy to introduce and invisible until the network it depends on is missing, so
it is refused here rather than discovered in production.

Navigation links are deliberately *not* asset references. The site links to
GitHub for source, issues, and releases, and those stay untouched -- this
checks only the references a browser fetches on its own to render the page.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable, List, Tuple

#: Attributes whose value the browser fetches without the user clicking.
_HTML_ASSET_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("script src", re.compile(r"<script\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)", re.I)),
    ("img src", re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)", re.I)),
    ("source src", re.compile(r"<source\b[^>]*?\bsrc(?:set)?\s*=\s*[\"']([^\"']+)", re.I)),
    ("iframe src", re.compile(r"<iframe\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)", re.I)),
    ("link href", re.compile(r"<link\b[^>]*?\bhref\s*=\s*[\"']([^\"']+)", re.I)),
)

#: CSS fetches these itself, whatever the surrounding markup says.
_CSS_ASSET_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("css url()", re.compile(r"url\(\s*[\"']?([^\"')]+)", re.I)),
    ("css @import", re.compile(r"@import\s+[\"']([^\"']+)", re.I)),
)

#: A reference that names another origin, or defers to whatever origin is live.
_REMOTE = re.compile(r"\A\s*(?:[a-z][a-z0-9+.-]*:)?//", re.I)

#: Schemes that never leave the document.
_INLINE_PREFIXES = ("data:", "#")


def _is_remote(reference: str) -> bool:
    value = reference.strip()
    if not value or value.startswith(_INLINE_PREFIXES):
        return False
    # http://, https://, and protocol-relative //cdn.example are all remote.
    return bool(_REMOTE.match(value))


def _scan(text: str, patterns: Iterable[Tuple[str, "re.Pattern[str]"]]) -> List[Tuple[str, str]]:
    found: List[Tuple[str, str]] = []
    for label, pattern in patterns:
        for match in pattern.finditer(text):
            reference = match.group(1)
            if _is_remote(reference):
                found.append((label, reference.strip()))
    return found


def find_remote_assets(site_dir: Path) -> List[Tuple[str, str, str]]:
    """Return ``(file, kind, reference)`` for every remote asset reference."""
    offences: List[Tuple[str, str, str]] = []
    for path in sorted(site_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".html", ".css", ".js"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(site_dir).as_posix()
        patterns = _CSS_ASSET_PATTERNS
        if path.suffix.lower() == ".html":
            patterns = _HTML_ASSET_PATTERNS + _CSS_ASSET_PATTERNS
        for kind, reference in _scan(text, patterns):
            offences.append((relative, kind, reference))
    return offences


def verify_offline_assets(site_dir: Path) -> None:
    offences = find_remote_assets(site_dir)
    if offences:
        lines = "\n".join(
            f"  {path}: {kind} -> {reference}" for path, kind, reference in offences
        )
        raise ValueError(
            "the site must not fetch assets from another origin; bundle these "
            f"locally instead:\n{lines}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("site_dir", type=Path)
    args = parser.parse_args()
    verify_offline_assets(args.site_dir)
    print(f"Site offline-asset contract verified: {args.site_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
