"""Synthetic bundle-scanning mechanics only.

The full published bundle must additionally pass the external complete private
publication-policy scan. These sentinels prove local matching behavior and do
not certify a real bundle against unavailable private rules.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from publication_policy import PublicationPolicy, PublicationPolicyError, validate_policy

SHIPPED = (".html", ".js", ".css", ".json", ".md", ".svg")


def scan_bundle(root: Path, policy: PublicationPolicy) -> None:
    files = [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in SHIPPED]
    if not files:
        raise PublicationPolicyError("No published bundle files")
    for path in files:
        policy.assert_clean(path.read_text(encoding="utf-8"))


def test_bundle_scanner_detects_synthetic_blocked_text(tmp_path):
    policy = validate_policy({"version": 1, "replacements": [], "forbidden": ["violet sample"]})
    page = tmp_path / "index.html"
    page.write_text("<p>VIOLET SAMPLE</p>", encoding="utf-8")
    with pytest.raises(PublicationPolicyError, match="Blocked publication content"):
        scan_bundle(tmp_path, policy)
    page.write_text("<p>violet sampler</p>", encoding="utf-8")
    scan_bundle(tmp_path, policy)


def test_missing_bundle_is_not_success(tmp_path):
    policy = validate_policy({"version": 1, "replacements": [], "forbidden": ["violet sample"]})
    with pytest.raises(PublicationPolicyError, match="No published bundle files"):
        scan_bundle(tmp_path, policy)
