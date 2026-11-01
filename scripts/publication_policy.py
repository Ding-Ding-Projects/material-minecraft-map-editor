"""Bounded literal publication rules supplied by an external private producer.

This module contains no private dictionary. Synthetic tests prove mechanics only;
complete publication approval requires the external policy and full-source scan.
"""
from __future__ import annotations

import json
import re
import base64
import binascii
import unicodedata
import zlib
from dataclasses import dataclass
from typing import BinaryIO

MAX_POLICY_BYTES = 1_048_576
MAX_RULES = 10_000
MAX_LITERAL_CHARS = 512
MAX_TEXT_CHARS = 4_194_304
MAX_ENVELOPE_BYTES = 262_144
MAX_DECODED_BYTES = 2_097_152


class PublicationPolicyError(ValueError):
    """Invalid policy or content that cannot safely be published."""


def _detection_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return "".join(char for char in normalized if unicodedata.category(char) != "Cf").casefold()


def _literal(value: object) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > MAX_LITERAL_CHARS):
        raise PublicationPolicyError("Invalid policy literal")
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        raise PublicationPolicyError("Invalid policy literal")
    if not _detection_text(value).strip() or len(_detection_text(value)) > MAX_LITERAL_CHARS:
        raise PublicationPolicyError("Invalid policy literal")
    return value


def _pattern(literal: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(_detection_text(literal)) + r"(?!\w)", re.IGNORECASE)


@dataclass(frozen=True)
class PublicationPolicy:
    replacements: tuple[tuple[re.Pattern[str], str], ...]
    forbidden: tuple[re.Pattern[str], ...]

    def assert_clean(self, text: str) -> None:
        if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
            raise PublicationPolicyError("Publication text exceeds limit")
        normalized = _detection_text(text)
        if len(normalized) > MAX_TEXT_CHARS:
            raise PublicationPolicyError("Publication text exceeds limit")
        if any(pattern.search(normalized) for pattern in self.forbidden):
            raise PublicationPolicyError("Blocked publication content")

    def sanitise(self, text: str) -> str:
        if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
            raise PublicationPolicyError("Publication text exceeds limit")
        result = text
        for pattern, replacement in self.replacements:
            def swap(match: re.Match[str], replacement: str = replacement) -> str:
                return replacement[:1].upper() + replacement[1:] if match.group(0)[:1].isupper() else replacement
            result = pattern.sub(swap, result)
            if len(result) > MAX_TEXT_CHARS:
                raise PublicationPolicyError("Publication text exceeds limit")
        self.assert_clean(result)
        return result


def validate_policy(payload: object) -> PublicationPolicy:
    if not isinstance(payload, dict) or set(payload) != {"version", "replacements", "forbidden"}:
        raise PublicationPolicyError("Invalid publication policy schema")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise PublicationPolicyError("Unsupported publication policy version")
    pairs, blocked = payload["replacements"], payload["forbidden"]
    if not isinstance(pairs, list) or not isinstance(blocked, list) or not 1 <= len(blocked) <= MAX_RULES or len(pairs) > MAX_RULES:
        raise PublicationPolicyError("Invalid publication policy inventory")
    forbidden = [_literal(term) for term in blocked]
    forbidden_keys = {_detection_text(term) for term in forbidden}
    if len(forbidden_keys) != len(forbidden):
        raise PublicationPolicyError("Duplicate publication policy rule")
    replacements: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            raise PublicationPolicyError("Invalid replacement pair")
        source, target = map(_literal, pair)
        key = _detection_text(source)
        if key in seen or key not in forbidden_keys:
            raise PublicationPolicyError("Invalid replacement inventory")
        seen.add(key)
        replacements.append((source, target))
    rules = PublicationPolicy(tuple((_pattern(source), target) for source, target in sorted(replacements, key=lambda pair: -len(pair[0]))), tuple(map(_pattern, forbidden)))
    for _, target in replacements:
        rules.assert_clean(target)
    return rules


def read_policy(stream: BinaryIO) -> PublicationPolicy:
    data = stream.read(MAX_POLICY_BYTES + 1)
    if len(data) > MAX_POLICY_BYTES:
        raise PublicationPolicyError("Publication policy exceeds limit")
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PublicationPolicyError("Duplicate publication policy field")
            result[key] = value
        return result
    def parse(raw: bytes) -> object:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    try:
        payload = parse(data)
        if isinstance(payload, dict) and ("encoding" in payload or "schemaVersion" in payload):
            if len(data) > MAX_ENVELOPE_BYTES:
                raise PublicationPolicyError("Publication envelope exceeds limit")
            if "encoding" in payload:
                if (set(payload) != {"schemaVersion", "encoding", "payload"}
                        or type(payload["schemaVersion"]) is not int or payload["schemaVersion"] != 1
                        or payload["encoding"] != "gzip+base64" or not isinstance(payload["payload"], str)):
                    raise PublicationPolicyError("Invalid publication transport")
                encoded = payload["payload"]
                compressed = base64.b64decode(encoded, validate=True)
                if base64.b64encode(compressed).decode("ascii") != encoded:
                    raise PublicationPolicyError("Invalid publication transport")
                inflater = zlib.decompressobj(31)
                decoded = inflater.decompress(compressed, MAX_DECODED_BYTES + 1)
                if (len(decoded) > MAX_DECODED_BYTES or not inflater.eof
                        or inflater.unused_data or inflater.unconsumed_tail):
                    raise PublicationPolicyError("Invalid publication transport")
                payload = parse(decoded)
            payload = _envelope_policy(payload)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PublicationPolicyError("Invalid publication policy JSON") from None
    except (binascii.Error, zlib.error):
        raise PublicationPolicyError("Invalid publication transport") from None
    return validate_policy(payload)


def _envelope_policy(envelope: object) -> object:
    if (not isinstance(envelope, dict)
            or set(envelope) != {"schemaVersion", "dictionary", "publicSafePhrases", "changelog"}
            or type(envelope["schemaVersion"]) is not int or envelope["schemaVersion"] != 1):
        raise PublicationPolicyError("Protected changelog policy unavailable")
    dictionary, safe, policy = envelope["dictionary"], envelope["publicSafePhrases"], envelope["changelog"]
    if (not isinstance(dictionary, dict) or not isinstance(dictionary.get("terms"), list)
            or not 1 <= len(dictionary["terms"]) <= MAX_RULES or not isinstance(safe, list)
            or len(safe) > MAX_RULES or not isinstance(policy, dict)):
        raise PublicationPolicyError("Invalid protected inventory")
    safe_keys = {_detection_text(_literal(value)) for value in safe}
    required = set()
    forms = dictionary.get("publicationForms", [])
    if not isinstance(forms, list) or len(forms) > MAX_RULES:
        raise PublicationPolicyError("Invalid protected inventory")
    forms = list(forms)
    for term in dictionary["terms"]:
        if (not isinstance(term, dict) or not isinstance(term.get("forms"), list)
                or len(term["forms"]) > MAX_RULES):
            raise PublicationPolicyError("Invalid protected inventory")
        forms.append(term.get("alias"))
        forms.extend(term["forms"])
        if len(forms) > MAX_RULES:
            raise PublicationPolicyError("Invalid protected inventory")
    for value in forms:
        key = _detection_text(_literal(value))
        if key not in safe_keys:
            required.add(key)
    blocked = policy.get("forbidden")
    if not isinstance(blocked, list):
        raise PublicationPolicyError("Invalid protected inventory")
    present = {_detection_text(_literal(value)) for value in blocked}
    if not required.issubset(present):
        raise PublicationPolicyError("Incomplete protected inventory")
    return policy
