"""Localized, School-mode-safe copy for notification infrastructure.

The notification bridge can be called from error handlers before a wx surface
is available. Keeping presentation selection here makes that path testable
without importing wx while still honoring the shared language and tone
preferences.
"""

from __future__ import annotations

from typing import Any

from amulet_map_editor.api import lang, preferences, school_mode

_TONE_NAMES = ("one", "two", "three", "four", "five")


def _presentation() -> Any:
    return school_mode.presentation_preferences(preferences.load())


def _localized(key: str, language: str, level: int, *, styled: bool) -> str:
    fact = lang.get(f"notifications.{language}.{key}")
    if not styled:
        return fact
    tone = lang.get(f"notifications.{language}.tone.{_TONE_NAMES[level - 1]}")
    return f"{fact} {tone}".strip()


def notification_text(key: str, *, styled: bool = True) -> str:
    """Return localized notification copy for the active presentation.

    School mode is projected through :func:`presentation_preferences`, so it
    receives serious English copy without exposing hidden language controls.
    Bilingual copy remains compact because notification summaries are rendered
    in a bounded single-line row.
    """

    current = _presentation()
    english = _localized(
        key,
        "en",
        current.funny_level_english,
        styled=styled,
    )
    cantonese = _localized(
        key,
        "zh",
        current.funny_level_cantonese,
        styled=styled,
    )
    if current.language_mode == "cantonese":
        return cantonese
    if current.language_mode == "bilingual":
        return f"{english} · {cantonese}"
    return english


__all__ = ["notification_text"]
