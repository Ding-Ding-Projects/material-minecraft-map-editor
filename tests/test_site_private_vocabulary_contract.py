"""Nothing published may carry the project's private working vocabulary.

This is not hypothetical here. Five occurrences of one conversation-only term
reached the live GitHub Pages site inside feature-card copy and a link target,
and a sixth described a managed service in wording meant for a private
conversation. A public site is the furthest a leak can travel, and unlike a
commit message it can be corrected -- so it is, and then it is guarded.

The guard scans the shipped site bundle rather than the source that generates
it, because the bundle is what a visitor actually receives.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE = REPO_ROOT / "docs" / "site"

#: Terms that belong in conversation between the people building this and
#: nowhere a stranger can read. Word-boundary matched so ordinary prose
#: containing them as substrings is not flagged.
PRIVATE_TERMS: tuple[str, ...] = (
    r"yum[- ]tong",
    r"mat day",
    r"dew (?:hui|jerjer|all branches)",
    r"dewed hui",
    r"gerk tong hui",
    r"lap sap tong",
    r"day teet hui",
    r"poke guy",
    r"lat tat",
    r"huipoint",
    r"ultrahui",
    r"i am dewing hui",
)

#: Extensions a visitor's browser actually loads.
SHIPPED = (".html", ".js", ".css", ".json", ".md", ".svg")


def _shipped_files() -> list[Path]:
    return [
        path
        for path in SITE.rglob("*")
        if path.is_file() and path.suffix.lower() in SHIPPED
    ]


def test_the_published_site_carries_no_private_vocabulary() -> None:
    """Scan the bundle a visitor downloads, not the generator behind it."""
    files = _shipped_files()
    assert files, "no shipped site files were found to scan"
    offenders: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for term in PRIVATE_TERMS:
            for match in re.finditer(term, text, re.IGNORECASE):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(
                    f"{path.relative_to(REPO_ROOT).as_posix()}:{line} {match.group(0)!r}"
                )
    assert not offenders, (
        "these strings ship to every visitor of the public site and are "
        f"conversation-only: {offenders[:10]}"
    )


def test_the_guard_would_actually_catch_a_leak() -> None:
    """A guard nobody has watched fail proves nothing.

    Rather than trusting that the scan works, run the same patterns over a
    string that definitely contains one and require a hit.
    """
    probe = "The yum-tong workflow runs before mat day."
    hits = [term for term in PRIVATE_TERMS if re.search(term, probe, re.IGNORECASE)]
    assert len(hits) >= 2, f"the patterns missed an obvious leak: {hits}"
