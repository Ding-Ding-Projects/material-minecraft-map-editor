"""Synthetic publication-rule mechanics, not complete private-data approval.

Real catalog generation and publication require the external protected policy
producer plus its complete source scan. No private inventory is bundled here.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_changelog import sanitise_subject
from publication_policy import PublicationPolicyError, read_policy, validate_policy


def synthetic_policy():
    return validate_policy({"version": 1, "replacements": [["amber widget", "review step"], ["violet marker", "release"]], "forbidden": ["amber widget", "violet marker", "blocked sample"]})


def test_boundaries_case_and_longest_literal_matching():
    policy = synthetic_policy()
    assert sanitise_subject("Amber widget and VIOLET MARKER", policy) == "Review step and Release"
    subject = "amber widgetry and preamber widget remain"
    assert sanitise_subject(subject, policy) == subject
    assert sanitise_subject("(amber widget)", policy) == "(review step)"
    assert sanitise_subject("Fix the chunk builder", policy) == "Fix the chunk builder"
    special = validate_policy({"version": 1, "replacements": [["sample.*", "literal"]], "forbidden": ["sample.*"]})
    assert sanitise_subject("sampleXYZ", special) == "sampleXYZ"
    assert sanitise_subject("sample.*", special) == "literal"


def test_known_blocked_leftover_is_not_raw_fallback():
    with pytest.raises(PublicationPolicyError, match="Blocked publication content"):
        sanitise_subject("contains blocked sample", synthetic_policy())
    with pytest.raises(TypeError):
        sanitise_subject("ordinary subject")


@pytest.mark.parametrize("payload", [None, {}, {"version": True, "replacements": [], "forbidden": ["sample"]}, {"version": 2, "replacements": [], "forbidden": ["sample"]}, {"version": 1, "replacements": [], "forbidden": []}, {"version": 1, "replacements": [["sample", "ok"]], "forbidden": ["other"]}, {"version": 1, "replacements": [["sample", "sample"]], "forbidden": ["sample"]}])
def test_invalid_policies_fail_closed(payload):
    with pytest.raises(PublicationPolicyError):
        validate_policy(payload)


def test_stdin_bounds_duplicate_fields_and_invalid_json():
    for data in [b"", b"{", b"\xff", b" " * 1_048_577, b'{"version":1,"version":1,"replacements":[],"forbidden":["sample"]}']:
        with pytest.raises(PublicationPolicyError):
            read_policy(io.BytesIO(data))


def test_generator_does_not_write_without_valid_policy(tmp_path):
    output = tmp_path / "nested" / "catalog.json"
    for arguments, data in [([], b""), (["--policy-stdin"], b"{}")]:
        result = subprocess.run([sys.executable, str(ROOT / "scripts/generate_changelog.py"), "--output", str(output), *arguments], input=data, capture_output=True)
        assert result.returncode != 0
        assert not output.parent.exists()


def test_generator_sanitises_fixture_history_and_blocks_leftovers(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    git("init")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-m", "Add amber widget")
    git("tag", "v1")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-m", "Next")
    output = tmp_path / "out.json"
    command = [sys.executable, "-I", "-S", str(ROOT / "scripts/generate_changelog.py"), "--repo", str(tmp_path), "--output", str(output), "--policy-stdin"]
    data = json.dumps({"version": 1, "replacements": [["amber widget", "review step"]], "forbidden": ["amber widget"]}).encode()
    result = subprocess.run(command, input=data, capture_output=True)
    assert result.returncode == 0
    assert json.loads(output.read_text())["entries"][0]["changes"][0]["summary"] == "Add review step"
    output.write_text("preserved")
    data = json.dumps({"version": 1, "replacements": [], "forbidden": ["amber widget"]}).encode()
    result = subprocess.run(command, input=data, capture_output=True)
    assert result.returncode != 0
    assert output.read_text() == "preserved"
    assert b"amber widget" not in result.stderr.lower()
