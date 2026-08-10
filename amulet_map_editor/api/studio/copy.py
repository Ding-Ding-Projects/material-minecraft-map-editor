"""User-facing copy for the Studio, in the reader's language and tone.

Every visible string in the Studio goes through :func:`studio_text` so the
language mode and the two funny-level sliders reach the whole shell rather than
the handful of surfaces someone remembered to wire.  The tone itself is not
reinvented here: it is
:func:`amulet_map_editor.api.tts_narrator.style_text`, the same styling the
spoken narrator and the notification copy use, so a message never sounds like
one product when it is read and another when it is spoken.

Tone styles the voice around a fact and never the fact itself.  An identifier,
a coordinate, a count, a path, or a version is returned exactly as it was
given, and so is a short control label -- a button whose name grew an aside
would both mislead and clip.
"""

from __future__ import annotations

import re
from typing import Tuple

from amulet_map_editor.api import preferences, school_mode, tts_narrator

#: A whitespace-separated token counts as factual when it carries a digit, a
#: namespace colon, a path separator, a hash sign, or a dotted suffix --
#: between them these cover identifiers, coordinates, counts, paths, hashes,
#: and version numbers.
_FACT_TOKEN = re.compile(r"^\S*(?:\d|[:/\\#]|\.[0-9A-Za-z])\S*$")

#: Sentence punctuation in both languages, used to tell prose from a label.
_SENTENCE_END = re.compile(r"[.!?…。！？]")

#: A string of at most this many words with no sentence punctuation is a
#: control label, not a message, and is left alone.
_MAX_LABEL_WORDS = 3


def _presentation() -> preferences.Preferences:
    """Return preferences projected through School mode.

    Reading the projection rather than the raw record is what makes School mode
    forced English at funny level 1 without every caller checking the mode.
    """
    return school_mode.presentation_preferences(preferences.load())


def language_mode() -> str:
    """Return the active language mode: english, cantonese, or bilingual."""
    return _presentation().language_mode


def funny_levels() -> Tuple[int, int]:
    """Return the English and Cantonese funny levels, each 1 to 5."""
    current = _presentation()
    return (current.funny_level_english, current.funny_level_cantonese)


def is_school_mode() -> bool:
    """Return whether the shared local School mode is currently enabled.

    Surfaces use this to omit -- not merely disable -- the language, tone, and
    dim-sum controls while the mode is on.
    """
    try:
        return bool(school_mode.load().enabled)
    except (OSError, AttributeError, TypeError, ValueError):
        return False


def is_verbatim(text: str) -> bool:
    """Return whether a string must be shown exactly as written.

    Two kinds of string are protected: one made entirely of factual tokens, and
    a short control label.  Everything else is prose, and prose is what the
    funny levels are for.
    """
    value = str(text).strip()
    if not value:
        return True
    words = value.split()
    if all(_FACT_TOKEN.match(word) for word in words):
        return True
    return len(words) <= _MAX_LABEL_WORDS and _SENTENCE_END.search(value) is None


def _style(text: str, language: str, level: int) -> str:
    """Apply the shared narrator tone to prose, leaving facts untouched."""
    value = str(text).strip()
    if is_verbatim(value):
        return value
    return tts_narrator.style_text(value, language, level)


def studio_text(english: str, cantonese: str = "") -> str:
    """Return one visible string in the reader's language and tone.

    Bilingual mode returns both lines separated by a newline so a caller can
    render them as a prominent primary label above a compact secondary one, as
    the design does, rather than crowding one line.  When no Cantonese source
    was supplied the English is shown instead: inventing a translation here
    would put words in the product's mouth that nobody wrote.
    """
    english_text = str(english).strip()
    cantonese_text = str(cantonese).strip()
    current = _presentation()

    english_styled = _style(english_text, "english", current.funny_level_english)
    if not cantonese_text:
        return english_styled
    cantonese_styled = _style(
        cantonese_text, "cantonese", current.funny_level_cantonese
    )
    if not english_text:
        return cantonese_styled

    mode = current.language_mode
    if mode == "cantonese":
        return cantonese_styled
    if mode == "bilingual":
        return f"{english_styled}\n{cantonese_styled}"
    return english_styled


__all__ = [
    "funny_levels",
    "is_school_mode",
    "is_verbatim",
    "language_mode",
    "studio_text",
]
