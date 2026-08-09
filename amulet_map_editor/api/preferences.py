"""Persisted user-facing preferences shared by every Amulet surface.

This module deliberately keeps the storage contract small and versioned.  UI
code can use the same values for the desktop frame, tabs, and documentation
surfaces without each surface inventing its own language or appearance state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Dict, Tuple

from amulet_map_editor.api import config

PREFERENCES_ID = "amulet_preferences"
PREFERENCES_VERSION = 1
LANGUAGE_MODES: Tuple[str, ...] = ("english", "cantonese", "bilingual")
THEMES: Tuple[str, ...] = ("light", "dark", "system")


@dataclass
class Preferences:
    """The persisted, bounded appearance and language settings."""

    version: int = PREFERENCES_VERSION
    language_mode: str = "english"
    funny_level_english: int = 1
    funny_level_cantonese: int = 1
    show_dialog_emojis: bool = True
    theme: str = "system"
    density: str = "comfortable"
    accent: str = "#6750A4"
    ui_font: str = ""
    ui_scale: float = 1.0

    def normalised(self) -> "Preferences":
        """Return a safe value even when an older profile was hand-edited."""
        self.language_mode = (
            self.language_mode if self.language_mode in LANGUAGE_MODES else "english"
        )
        self.theme = self.theme if self.theme in THEMES else "system"
        self.density = (
            self.density
            if self.density in ("compact", "comfortable", "spacious")
            else "comfortable"
        )
        try:
            self.funny_level_english = min(5, max(1, int(self.funny_level_english)))
        except (TypeError, ValueError):
            self.funny_level_english = 1
        try:
            self.funny_level_cantonese = min(5, max(1, int(self.funny_level_cantonese)))
        except (TypeError, ValueError):
            self.funny_level_cantonese = 1
        try:
            self.ui_scale = min(2.0, max(0.8, float(self.ui_scale)))
        except (TypeError, ValueError):
            self.ui_scale = 1.0
        if not isinstance(self.accent, str) or not re.fullmatch(
            r"#[0-9a-fA-F]{6,8}", self.accent
        ):
            self.accent = "#6750A4"
        return self


def load() -> Preferences:
    """Load preferences, migrating missing keys to the shipped values."""
    raw: Dict[str, Any] = config.get(PREFERENCES_ID, {})
    if not isinstance(raw, dict):
        raw = {}
    fields = {key: raw[key] for key in asdict(Preferences()) if key in raw}
    return Preferences(**fields).normalised()


def save(preferences: Preferences) -> Preferences:
    """Persist and return normalised preferences."""
    preferences = preferences.normalised()
    config.put(PREFERENCES_ID, asdict(preferences))
    return preferences


def update(**changes: Any) -> Preferences:
    """Apply named changes atomically and persist them."""
    preferences = load()
    unknown = set(changes) - set(asdict(preferences))
    if unknown:
        raise KeyError("Unknown preference(s): " + ", ".join(sorted(unknown)))
    for key, value in changes.items():
        setattr(preferences, key, value)
    return save(preferences)


def reset() -> Preferences:
    """Restore the documented shipped values."""
    return save(Preferences())
