"""Bounded literal publication rules supplied by an external private producer.

This module contains no private dictionary. Synthetic tests prove mechanics only;
complete publication approval requires the external policy and full-source scan.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import BinaryIO

MAX_POLICY_BYTES = 1_048_576
MAX_RULES = 10_000
MAX_LITERAL_CHARS = 512
MAX_TEXT_CHARS = 4_194_304


class PublicationPolicyError(ValueError):
    """Invalid policy or content that cannot safely be published."""


def _literal(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_LITERAL_CHARS:
        raise PublicationPolicyError("Invalid policy literal")
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        raise PublicationPolicyError("Invalid policy literal")
    return value


def _pattern(literal: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(literal) + r"(?!\w)", re.IGNORECASE)


@dataclass(frozen=True)
class PublicationPolicy:
    replacements: tuple[tuple[re.Pattern[str], str], ...]
    forbidden: tuple[re.Pattern[str], ...]

    def assert_clean(self, text: str) -> None:
        if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
            raise PublicationPolicyError("Publication text exceeds limit")
        if any(pattern.search(text) for pattern in self.forbidden):
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
    forbidden_keys = {term.casefold() for term in forbidden}
    if len(forbidden_keys) != len(forbidden):
        raise PublicationPolicyError("Duplicate publication policy rule")
    replacements: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            raise PublicationPolicyError("Invalid replacement pair")
        source, target = map(_literal, pair)
        key = source.casefold()
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
    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PublicationPolicyError("Invalid publication policy JSON") from None
    return validate_policy(payload)
