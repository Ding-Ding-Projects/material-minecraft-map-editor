"""Bounded regular-expression search shared by every search field."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Pattern, Tuple

MAX_PATTERN_LENGTH = 4096
MAX_SAMPLE_LENGTH = 100_000


@dataclass(frozen=True)
class RegexResult:
    valid: bool
    error: Optional[str] = None
    matches: Tuple[str, ...] = ()
    groups: Tuple[Tuple[str, ...], ...] = ()


class RegexBuilder:
    """Build and evaluate Python ``re`` patterns with explicit validation."""

    def __init__(self, pattern: str = "", flags: int = 0, regex_enabled: bool = False):
        self.pattern = pattern
        self.flags = flags
        self.regex_enabled = regex_enabled

    def compile(self) -> Pattern[str]:
        if len(self.pattern) > MAX_PATTERN_LENGTH:
            raise ValueError(f"Pattern is limited to {MAX_PATTERN_LENGTH} characters")
        return re.compile(
            self.pattern if self.regex_enabled else re.escape(self.pattern), self.flags
        )

    def validate(self) -> RegexResult:
        try:
            self.compile()
        except (re.error, ValueError) as exc:
            return RegexResult(False, str(exc))
        return RegexResult(True)

    def evaluate(self, sample: str) -> RegexResult:
        if len(sample) > MAX_SAMPLE_LENGTH:
            return RegexResult(
                False, f"Sample is limited to {MAX_SAMPLE_LENGTH} characters"
            )
        try:
            compiled = self.compile()
            found = tuple(compiled.finditer(sample))
        except (re.error, ValueError) as exc:
            return RegexResult(False, str(exc))
        return RegexResult(
            True,
            matches=tuple(match.group(0) for match in found),
            groups=tuple(
                tuple(group or "" for group in match.groups()) for match in found
            ),
        )

    def search(self, values: List[str]) -> List[str]:
        """Return matching values while preserving source order."""
        compiled = self.compile()
        return [value for value in values if compiled.search(value)]
