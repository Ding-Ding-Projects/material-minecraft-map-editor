"""Synthetic protected-input transport checks, without private production data."""
import base64
import gzip
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from publication_policy import PublicationPolicyError, read_policy


def envelope():
    return {
        "schemaVersion": 1,
        "dictionary": {"terms": [{"alias": "INTERNAL_SENTINEL", "forms": ["INTERNAL_SENTINEL"]}], "publicationForms": []},
        "publicSafePhrases": [],
        "changelog": {"version": 1, "replacements": [["INTERNAL_SENTINEL", "ordinary wording"]], "forbidden": ["INTERNAL_SENTINEL"]},
    }


def raw(value):
    return json.dumps(value).encode()


def carrier(data):
    return raw({"schemaVersion": 1, "encoding": "gzip+base64", "payload": base64.b64encode(data).decode()})


@pytest.mark.parametrize("compressed", [False, True])
def test_current_envelope(compressed):
    data = raw(envelope())
    if compressed:
        data = carrier(gzip.compress(data))
    policy = read_policy(io.BytesIO(data))
    assert policy.sanitise("Replace INTERNAL_SENTINEL") == "Replace Ordinary wording"
    assert policy.sanitise("Unrelated text") == "Unrelated text"


@pytest.mark.parametrize("change", [
    lambda e: e.pop("changelog"),
    lambda e: e.update(extra=True),
    lambda e: e.update(schemaVersion=True),
    lambda e: e["changelog"].update(forbidden=["OTHER_SENTINEL"], replacements=[]),
    lambda e: e["dictionary"].update(terms=[]),
])
def test_invalid_or_incomplete_envelope(change):
    value = envelope()
    change(value)
    with pytest.raises(PublicationPolicyError):
        read_policy(io.BytesIO(raw(value)))


def test_compressed_tail_and_expansion():
    valid = gzip.compress(raw(envelope()))
    for invalid in (valid + b"tail", valid + valid, valid[:-1], gzip.compress(b" " * 2_097_153)):
        with pytest.raises(PublicationPolicyError):
            read_policy(io.BytesIO(carrier(invalid)))


def test_duplicate_keys_and_invalid_base64():
    for invalid in (b'{"version":1,"version":1}', raw({"schemaVersion":1,"encoding":"gzip+base64","payload":"!!!!"})):
        with pytest.raises(PublicationPolicyError):
            read_policy(io.BytesIO(invalid))


def test_obfuscated_forbidden_text_stays_blocked():
    policy = read_policy(io.BytesIO(raw(envelope())))
    for text in ("ＩＮＴＥＲＮＡＬ＿ＳＥＮＴＩＮＥＬ", "INTERNAL_\u200bSENTINEL"):
        with pytest.raises(PublicationPolicyError):
            policy.sanitise(text)


@pytest.mark.parametrize("rule", ["ＩＮＴＥＲＮＡＬ＿ＳＥＮＴＩＮＥＬ", "INTERNAL_\u200bSENTINEL"])
def test_normalized_inventory_rules_are_effective(rule):
    value = envelope()
    value["changelog"] = {"version": 1, "replacements": [], "forbidden": [rule]}
    policy = read_policy(io.BytesIO(raw(value)))
    with pytest.raises(PublicationPolicyError):
        policy.assert_clean("INTERNAL_SENTINEL")


def test_casefold_inventory_matches_detection():
    value = envelope()
    value["dictionary"]["terms"] = [{"alias": "straße_sentinel", "forms": ["straße_sentinel"]}]
    value["changelog"] = {"version": 1, "replacements": [], "forbidden": ["STRASSE_SENTINEL"]}
    policy = read_policy(io.BytesIO(raw(value)))
    with pytest.raises(PublicationPolicyError):
        policy.assert_clean("straße_sentinel")
