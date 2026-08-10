"""Shared search state for every Amulet Studio search surface.

Plain-text matching is the default everywhere; regular expressions are an
explicit opt-in.  An invalid pattern is reported through :meth:`SearchState.feedback`
and matches nothing, rather than silently behaving like an empty query.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Sequence, TypeVar

#: Patterns longer than this are refused outright so a pathological expression
#: never reaches the engine.  The bound matches the design's ``maxlength``.
MAX_PATTERN_LENGTH = 500

#: Sample text handed to a fresh regex builder when a field has no sample yet.
DEFAULT_SAMPLE = "1.17 Height · Debug 1.14"

_T = TypeVar("_T")


@dataclass
class SearchState:
    """The query, mode, and validation feedback behind one search field."""

    query: str = ""
    regex: bool = False
    flags: str = "iu"
    sample: str = DEFAULT_SAMPLE
    #: Optional label used by the regex builder and by screen readers.
    label: str = "Search"
    _compiled: Optional[re.Pattern] = field(
        default=None, init=False, repr=False, compare=False
    )
    _compiled_key: Optional[tuple] = field(
        default=None, init=False, repr=False, compare=False
    )
    _error: str = field(default="", init=False, repr=False, compare=False)

    # ------------------------------------------------------------------
    # compilation
    # ------------------------------------------------------------------
    def _regex_flags(self) -> int:
        """Translate the textual flag string into ``re`` flags."""
        value = re.UNICODE
        text = self.flags or ""
        if "i" in text:
            value |= re.IGNORECASE
        if "m" in text:
            value |= re.MULTILINE
        if "s" in text:
            value |= re.DOTALL
        if "x" in text:
            value |= re.VERBOSE
        return value

    def _compile(self) -> Optional[re.Pattern]:
        """Compile and memoise the active pattern, recording any failure."""
        key = (self.query, self.flags)
        if self._compiled_key == key:
            return self._compiled
        self._compiled_key = key
        self._compiled = None
        self._error = ""
        pattern = self.query or ""
        if not pattern.strip():
            return None
        if len(pattern) > MAX_PATTERN_LENGTH:
            self._error = f"Pattern is longer than {MAX_PATTERN_LENGTH} characters."
            return None
        try:
            self._compiled = re.compile(pattern, self._regex_flags())
        except re.error as error:
            self._error = f"Invalid pattern: {error}"
            self._compiled = None
        return self._compiled

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def is_active(self) -> bool:
        """Return whether the field is currently filtering anything."""
        return bool((self.query or "").strip())

    def is_valid(self) -> bool:
        """Return whether the current pattern can actually be evaluated."""
        if not self.regex or not self.is_active():
            return True
        self._compile()
        return not self._error

    def error(self) -> str:
        """Return the exact compilation failure, or an empty string."""
        if not self.regex:
            return ""
        self._compile()
        return self._error

    def feedback(self) -> str:
        """Return the honest one-line status shown beside the field."""
        if not self.is_active():
            return "Plain-text search. Enable regex deliberately."
        if not self.regex:
            return "Filtering by plain text."
        self._compile()
        if self._error:
            return self._error
        return "Regex is valid."

    def matches(self, haystack: object) -> bool:
        """Return whether ``haystack`` satisfies the current query."""
        if not self.is_active():
            return True
        text = "" if haystack is None else str(haystack)
        if not self.regex:
            return self.query.strip().lower() in text.lower()
        compiled = self._compile()
        if compiled is None:
            # An invalid pattern matches nothing; the failure is reported by
            # ``feedback`` rather than being hidden behind an empty result.
            return False
        return bool(compiled.search(text))

    def filter(
        self,
        items: Iterable[_T],
        key: Callable[[_T], str] = str,
    ) -> List[_T]:
        """Return the members of ``items`` whose ``key`` matches the query."""
        if not self.is_active():
            return list(items)
        return [item for item in items if self.matches(key(item))]

    def highlights(self, haystack: str) -> Sequence[tuple[int, int]]:
        """Return ``(start, end)`` spans to emphasise inside ``haystack``."""
        if not self.is_active() or not haystack:
            return ()
        if not self.regex:
            needle = self.query.strip().lower()
            lowered = haystack.lower()
            spans: List[tuple[int, int]] = []
            start = lowered.find(needle)
            while start != -1 and needle:
                spans.append((start, start + len(needle)))
                start = lowered.find(needle, start + len(needle))
            return tuple(spans)
        compiled = self._compile()
        if compiled is None:
            return ()
        return tuple(
            (match.start(), match.end()) for match in compiled.finditer(haystack)
        )

    def describe_matches(self, count: int, noun: str = "result") -> str:
        """Return an honest count line, including the empty case."""
        plural = noun if count == 1 else f"{noun}s"
        if not self.is_active():
            return f"{count} {plural}"
        if self.regex and not self.is_valid():
            return f"No {noun}s — {self.feedback().lower()}"
        if count == 0:
            return f"No {noun}s match “{self.query}”."
        return f"{count} {plural} match “{self.query}”."

    def reset(self) -> None:
        """Clear the query while keeping the mode the user chose."""
        self.query = ""
        self._compiled = None
        self._compiled_key = None
        self._error = ""
