"""A generic, content-agnostic display-text overlay.

This module knows nothing about what any particular user's overlay says.  It
loads a bounded JSON file the user chooses from their own machine, validates
it against a small fixed schema, caches the validated result in the
application's own data directory, and exposes a substitution boundary that a
UI layer calls wherever display copy or an accessible name is about to reach
the screen.

With no overlay loaded, every function in this module is a no-op: the shipped
wording renders completely unchanged, and nothing here hints that a
substitution mechanism exists.  The overlay file itself never leaves the
user's machine through this module -- it is not logged, not cached anywhere
but the application's own data directory, and never bundled or defaulted.

Expected file shape, and nothing beyond it::

    {
        "version": 1,
        "replacements": {"<display string>": "<replacement string>"},
        "required_phrases": ["<phrase that must never be rewritten>"]
    }

All three top-level keys are required; an unrecognised key is refused rather
than silently ignored, so a typo is reported instead of doing nothing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union

from amulet_map_editor.api import config

__all__ = [
    "OVERLAY_SCHEMA_VERSION",
    "MAX_OVERLAY_FILE_BYTES",
    "MAX_REPLACEMENT_ENTRIES",
    "MAX_REQUIRED_PHRASES",
    "MAX_KEY_LENGTH",
    "MAX_VALUE_LENGTH",
    "OVERLAY_CACHE_ID",
    "OverlayError",
    "OverlayValidationError",
    "UnsupportedOverlayVersion",
    "OverlayFileError",
    "TextOverlay",
    "parse_overlay_bytes",
    "load_overlay_file",
    "load_cached_overlay",
    "clear_cached_overlay",
    "substitute_text",
    "substitute_accessible_name",
]

#: The only schema version this build understands.  A file naming any other
#: version is refused rather than guessed at.
OVERLAY_SCHEMA_VERSION = 1

#: Generous but bounded: this is untrusted input read straight off disk.
MAX_OVERLAY_FILE_BYTES = 64 * 1024
MAX_REPLACEMENT_ENTRIES = 500
MAX_REQUIRED_PHRASES = 500
MAX_KEY_LENGTH = 300
MAX_VALUE_LENGTH = 300

#: Identifier the validated overlay is cached under, via :mod:`config`.  The
#: cache lives in the application's own profile directory -- never inside a
#: user's opened project and never inside this repository.
OVERLAY_CACHE_ID = "amulet_text_overlay_cache"

_TOP_LEVEL_KEYS = ("version", "replacements", "required_phrases")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class OverlayError(Exception):
    """Base class for every error this module raises."""


class OverlayValidationError(OverlayError, ValueError):
    """Raised when an overlay document does not satisfy the bounded schema.

    The message always names what was wrong and the exact limit involved; it
    never includes the overlay's own replacement or phrase text, because that
    text must never reach a log line -- see the module docstring.
    """


class UnsupportedOverlayVersion(OverlayValidationError):
    """Raised when the overlay's ``version`` is not one this build reads."""


class OverlayFileError(OverlayError, OSError):
    """Raised when the chosen overlay file cannot be read from disk."""


def _compile_alternation(literals: Iterable[str]) -> Optional["re.Pattern[str]"]:
    """Build a longest-match-first alternation over literal strings.

    ``re`` alternation tries each branch in order and takes the first one
    that matches at a given position rather than the longest one overall, so
    ordering the branches by descending length is what makes a longer key
    win over a shorter key that happens to be one of its prefixes.
    """

    ordered = sorted(
        {literal for literal in literals if literal}, key=len, reverse=True
    )
    if not ordered:
        return None
    return re.compile("|".join(re.escape(literal) for literal in ordered))


class TextOverlay:
    """A validated, bounded display-text overlay.

    Holds nothing about what any particular replacement means -- just a
    bounded mapping of literal strings to literal strings, plus the phrases
    that substitution must never touch.  Construct one only through
    :func:`parse_overlay_bytes` or :func:`load_overlay_file`; both apply the
    full bounded-schema validation before an instance is returned.
    """

    __slots__ = (
        "_version",
        "_replacements",
        "_required_phrases",
        "_replacement_pattern",
        "_required_phrase_pattern",
    )

    def __init__(
        self,
        version: int,
        replacements: Mapping[str, str],
        required_phrases: Sequence[str],
    ) -> None:
        self._version = version
        self._replacements: Mapping[str, str] = MappingProxyType(dict(replacements))
        self._required_phrases: Tuple[str, ...] = tuple(required_phrases)
        self._replacement_pattern = _compile_alternation(self._replacements.keys())
        self._required_phrase_pattern = _compile_alternation(self._required_phrases)

    @property
    def version(self) -> int:
        return self._version

    @property
    def replacements(self) -> Mapping[str, str]:
        return self._replacements

    @property
    def required_phrases(self) -> Tuple[str, ...]:
        return self._required_phrases

    def as_mapping(self) -> Dict[str, Any]:
        """Return the plain structure this overlay represents.

        Safe to hand to :func:`json.dumps` or to :func:`config.put` -- it is
        exactly the validated shape, nothing more.
        """

        return {
            "version": self._version,
            "replacements": dict(self._replacements),
            "required_phrases": list(self._required_phrases),
        }

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, TextOverlay):
            return NotImplemented
        return (
            self._version == other._version
            and dict(self._replacements) == dict(other._replacements)
            and self._required_phrases == other._required_phrases
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"TextOverlay(version={self._version!r}, "
            f"replacements={{...{len(self._replacements)} entries...}}, "
            f"required_phrases=(...{len(self._required_phrases)} entries...))"
        )


def _validate_top_level_keys(document: Mapping[str, Any]) -> None:
    if any(not isinstance(key, str) for key in document):
        raise OverlayValidationError("Overlay file keys must all be text.")
    actual = set(document)
    expected = set(_TOP_LEVEL_KEYS)
    missing = expected - actual
    unknown = actual - expected
    if missing or unknown:
        details = []
        if missing:
            details.append(
                "missing " + ", ".join(f"'{key}'" for key in sorted(missing))
            )
        if unknown:
            details.append(
                "unexpected " + ", ".join(f"'{key}'" for key in sorted(unknown))
            )
        raise OverlayValidationError(
            "Overlay file must have exactly the keys 'version', 'replacements', "
            "and 'required_phrases' (" + "; ".join(details) + ")."
        )


def _validate_version(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OverlayValidationError("The 'version' field must be a whole number.")
    if value != OVERLAY_SCHEMA_VERSION:
        raise UnsupportedOverlayVersion(
            f"Overlay version {value} is not supported by this build; "
            f"expected version {OVERLAY_SCHEMA_VERSION}."
        )
    return value


def _validate_short_text(
    value: Any, label: str, index: int, limit: int, *, allow_empty: bool
) -> str:
    if not isinstance(value, str):
        raise OverlayValidationError(
            f"The {label} at position {index} must be a string."
        )
    if not allow_empty and not value:
        raise OverlayValidationError(
            f"The {label} at position {index} cannot be empty."
        )
    if len(value) > limit:
        raise OverlayValidationError(
            f"The {label} at position {index} is longer than {limit} characters."
        )
    if _CONTROL_CHARACTERS.search(value):
        raise OverlayValidationError(
            f"The {label} at position {index} contains a control character, "
            "which is not allowed."
        )
    return value


def _validate_replacements(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        raise OverlayValidationError(
            "The 'replacements' field must be a JSON object mapping strings "
            "to strings."
        )
    if len(value) > MAX_REPLACEMENT_ENTRIES:
        raise OverlayValidationError(
            f"The 'replacements' field has {len(value)} entries; the limit "
            f"is {MAX_REPLACEMENT_ENTRIES}."
        )
    validated: Dict[str, str] = {}
    for index, (key, entry_value) in enumerate(value.items()):
        clean_key = _validate_short_text(
            key, "replacement key", index, MAX_KEY_LENGTH, allow_empty=False
        )
        clean_value = _validate_short_text(
            entry_value,
            "replacement value",
            index,
            MAX_VALUE_LENGTH,
            allow_empty=True,
        )
        validated[clean_key] = clean_value
    return validated


def _validate_required_phrases(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, list):
        raise OverlayValidationError(
            "The 'required_phrases' field must be a list of strings."
        )
    if len(value) > MAX_REQUIRED_PHRASES:
        raise OverlayValidationError(
            f"The 'required_phrases' field has {len(value)} entries; the "
            f"limit is {MAX_REQUIRED_PHRASES}."
        )
    validated = [
        _validate_short_text(
            entry, "required phrase", index, MAX_KEY_LENGTH, allow_empty=False
        )
        for index, entry in enumerate(value)
    ]
    return tuple(validated)


def _validate_document(document: Any) -> TextOverlay:
    """Validate an already-parsed structure against the bounded schema.

    Used both for a freshly loaded file (after :func:`json.loads`) and for
    whatever :func:`config.get` hands back from the cache, so a corrupted or
    foreign cache entry is caught the same way a bad file would be.
    """

    if not isinstance(document, dict):
        raise OverlayValidationError("Overlay file must contain a JSON object.")
    _validate_top_level_keys(document)
    version = _validate_version(document["version"])
    replacements = _validate_replacements(document["replacements"])
    required_phrases = _validate_required_phrases(document["required_phrases"])
    return TextOverlay(version, replacements, required_phrases)


def parse_overlay_bytes(raw: bytes) -> TextOverlay:
    """Validate raw file bytes against the bounded overlay schema.

    Every refusal names what was wrong and the exact limit that was
    exceeded.  Validation happens before anything derived from ``raw`` is
    returned, so nothing unvalidated is ever displayed or cached.
    """

    if len(raw) > MAX_OVERLAY_FILE_BYTES:
        raise OverlayValidationError(
            f"Overlay file is {len(raw)} bytes; the limit is "
            f"{MAX_OVERLAY_FILE_BYTES} bytes."
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OverlayValidationError("Overlay file must be UTF-8 text.") from exc
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OverlayValidationError(f"Overlay file is not valid JSON: {exc}") from exc
    return _validate_document(document)


def _write_cache(overlay: TextOverlay) -> None:
    """Persist a validated overlay to the application's own data directory.

    Routed through :mod:`config`, which already resolves to the
    application's profile directory and never to a user's opened project or
    to this repository.
    """

    config.put(OVERLAY_CACHE_ID, overlay.as_mapping())


def load_overlay_file(path: Union[str, Path]) -> TextOverlay:
    """Load, validate, and cache a display-text overlay chosen by the user.

    ``path`` is a location on the user's own machine.  Nothing here bundles a
    default overlay, reaches the network, or accepts anything outside the
    bounded schema.  On success the validated overlay is cached in the
    application's own data directory so it survives a restart without the
    user re-choosing the file every launch; on failure nothing is cached and
    any previously cached overlay is left untouched.
    """

    file_path = Path(path)
    try:
        raw = file_path.read_bytes()
    except FileNotFoundError as exc:
        raise OverlayFileError(f"Overlay file was not found: {file_path}") from exc
    except OSError as exc:
        raise OverlayFileError(f"Overlay file could not be read: {exc}") from exc
    overlay = parse_overlay_bytes(raw)
    _write_cache(overlay)
    return overlay


def load_cached_overlay() -> Optional[TextOverlay]:
    """Return the most recently validated overlay, or ``None`` if there is none.

    A cache entry that fails validation -- a foreign value, a corrupted
    profile file -- behaves exactly like no overlay ever having been loaded,
    rather than surfacing a cache-internal problem as if it were a defect in
    the user's file.
    """

    cached = config.get(OVERLAY_CACHE_ID)
    if cached is None:
        return None
    try:
        return _validate_document(cached)
    except OverlayValidationError:
        return None


def clear_cached_overlay() -> None:
    """Forget the cached overlay, returning to the shipped, unsubstituted text."""

    config.put(OVERLAY_CACHE_ID, None)


def substitute_text(overlay: Optional[TextOverlay], text: str) -> str:
    """Apply ``overlay`` to one piece of user-facing display text.

    This is the substitution boundary: call it only where display copy is
    about to reach the screen.  Never call it on a command, a URL, an
    identifier, code, a file path, a version string, a commit SHA, error text
    from another system, or any other factual external record -- those must
    reach the user unchanged, and this function has no way to tell a display
    sentence from a technical one on its own.  When a technical fragment is
    embedded *inside* a display sentence, list it in ``required_phrases`` so
    it is protected even though the surrounding sentence is substituted.

    With ``overlay`` absent, or with nothing to substitute, ``text`` is
    returned unchanged -- the whole feature is only as present as the file a
    user chose to load.
    """

    if overlay is None or not isinstance(text, str) or not text:
        return text
    pattern = overlay._replacement_pattern  # noqa: SLF001 - same-module access
    if pattern is None:
        return text
    protected_pattern = overlay._required_phrase_pattern  # noqa: SLF001
    protected_spans = (
        [match.span() for match in protected_pattern.finditer(text)]
        if protected_pattern is not None
        else []
    )

    def _replace(match: "re.Match[str]") -> str:
        start, end = match.span()
        if any(start < p_end and end > p_start for p_start, p_end in protected_spans):
            return match.group(0)
        return overlay.replacements[match.group(0)]

    return pattern.sub(_replace, text)


def substitute_accessible_name(overlay: Optional[TextOverlay], name: str) -> str:
    """The same substitution boundary as :func:`substitute_text`, named for
    accessible-name call sites.

    A screen reader must hear whatever the substituted screen shows, so an
    accessible name is substituted exactly the way the label it names is --
    this alias exists purely so a call site can say what it means.
    """

    return substitute_text(overlay, name)
