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

#: A trailing ellipsis on a control means "this opens a further surface". It is
#: a convention, not sentence punctuation, and treating it as the latter made
#: every "Remove from list…" and "Export list…" read as prose -- so they were
#: the only two strings in the entire interface that received a funny-level
#: aside, which is precisely the case the label rule exists to prevent.
_TRAILING_ELLIPSIS = re.compile(r"(\.\.\.|…)\s*$")

#: A string of at most this many words with no sentence punctuation is a
#: control label, not a message, and is left alone. Five rather than three
#: because real labels reach that length -- "Restart to install update" is four,
#: "Select all matches" is three -- while a genuine message almost always
#: carries sentence punctuation and is caught by that test instead.
_MAX_LABEL_WORDS = 5


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
    # Judge the label without its "opens something" ellipsis.
    without_ellipsis = _TRAILING_ELLIPSIS.sub("", value).strip()
    return (
        len(words) <= _MAX_LABEL_WORDS
        and _SENTENCE_END.search(without_ellipsis) is None
    )


def _style(text: str, language: str, level: int) -> str:
    """Apply the shared narrator tone to prose, leaving facts untouched."""
    value = str(text).strip()
    if is_verbatim(value):
        return value
    return tts_narrator.style_text(value, language, level)


def studio_label(english: str, cantonese: str = "") -> str:
    """Return a CONTROL label in the reader's language, with no tone applied.

    A funny level styles the application's voice.  It has no business inside the
    text on a button, a tab, a placeholder, a column heading, a window title or a
    menu item, for two reasons.

    The first is that those strings are not the application talking, they are
    the application naming a thing, and a name with an aside on the end stops
    being a name.  A palette button reading "Tell me what to do (the code is
    dancing; the facts stay put)" tells the reader nothing extra and costs them
    the label.

    The second is layout.  A control is sized to its label.  Appending a clause
    to every label at level five overflows tab strips, truncates buttons to
    "Confirm clo..." and pushes search fields off the edge of the ribbon.  The
    clipping reads as a broken interface, and it is really a tone setting
    applied one layer too deep.

    Messages keep their tone; use :func:`studio_text` for those.
    """
    english_text = str(english).strip()
    cantonese_text = str(cantonese).strip()
    if not cantonese_text:
        return english_text
    if not english_text:
        return cantonese_text
    mode = _presentation().language_mode
    if mode == "cantonese":
        return cantonese_text
    if mode == "bilingual":
        return f"{english_text}\n{cantonese_text}"
    return english_text


def studio_text(english: str, cantonese: str = "") -> str:
    """Return one visible MESSAGE in the reader's language and tone.

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
    "studio_label",
    "funny_levels",
    "is_school_mode",
    "is_verbatim",
    "language_mode",
    "studio_text",
]
