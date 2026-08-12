"""Persisted user-facing preferences shared by every Amulet surface.

This module deliberately keeps the storage contract small and versioned.  UI
code can use the same values for the desktop frame, tabs, and documentation
surfaces without each surface inventing its own language or appearance state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import re
from typing import Any, Dict, Tuple
import unicodedata

from amulet_map_editor.api import config

PREFERENCES_ID = "amulet_preferences"
PREFERENCES_VERSION = 3
DEFAULT_DISPLAY_NAME = "Amulet"
MAX_DISPLAY_NAME_LENGTH = 64
LANGUAGE_MODES: Tuple[str, ...] = ("english", "cantonese", "bilingual")
THEMES: Tuple[str, ...] = ("light", "dark", "system")
DENSITIES: Tuple[str, ...] = ("compact", "comfortable", "spacious")


@dataclass
class Preferences:
    """The persisted, bounded appearance and language settings."""

    version: int = PREFERENCES_VERSION
    display_name: str = DEFAULT_DISPLAY_NAME
    language_mode: str = "english"
    funny_level_english: int = 1
    funny_level_cantonese: int = 1
    show_dialog_emojis: bool = True
    theme: str = "system"
    density: str = "comfortable"
    accent: str = "#6750A4"
    ui_font: str = ""
    ui_scale: float = 1.0
    external_editor_path: str = ""
    auto_stage_updates: bool = True

    def normalised(self) -> "Preferences":
        """Return a safe value even when an older profile was hand-edited."""
        self.version = PREFERENCES_VERSION
        try:
            self.display_name = validate_display_name(self.display_name)
        except ValueError:
            self.display_name = DEFAULT_DISPLAY_NAME
        self.language_mode = (
            self.language_mode if self.language_mode in LANGUAGE_MODES else "english"
        )
        self.theme = self.theme if self.theme in THEMES else "system"
        self.density = self.density if self.density in DENSITIES else "comfortable"
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
        if not isinstance(self.external_editor_path, str):
            self.external_editor_path = ""
        self.external_editor_path = self.external_editor_path.strip()[:4096]
        if not isinstance(self.accent, str) or not re.fullmatch(
            r"#[0-9a-fA-F]{6,8}", self.accent
        ):
            self.accent = "#6750A4"
        self.auto_stage_updates = bool(self.auto_stage_updates)
        return self


def validate_display_name(value: Any) -> str:
    """Return a safe user-facing app name or raise a plain validation error.

    The display label is deliberately independent from package, application-data,
    and update identities. Leading and trailing whitespace is ignored, while the
    user's remaining Unicode spelling is preserved exactly.
    """
    if not isinstance(value, str):
        raise ValueError("App display name must be text.")
    value = value.strip()
    if not value:
        raise ValueError("App display name cannot be empty.")
    if len(value) > MAX_DISPLAY_NAME_LENGTH:
        raise ValueError(
            f"App display name must be {MAX_DISPLAY_NAME_LENGTH} characters or fewer."
        )
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("App display name cannot contain control characters.")
    return value


DISPLAY_NAME_TOKEN = "{display_name}"


def resolve_display_name(text: str) -> str:
    """Replace the literal display-name token using current valid preferences."""
    if not isinstance(text, str):
        raise TypeError("Display-name text must be a string.")
    display_name = validate_display_name(load().display_name)
    return text.replace(DISPLAY_NAME_TOKEN, display_name)


def format_window_title(
    version: str, *, display_name: str | None = None, source: bool = False
) -> str:
    """Format the visible frame title without changing application identity."""
    name = validate_display_name(
        load().display_name if display_name is None else display_name
    )
    title = f"{name} {version}"
    return title + " (source)" if source else title


#: The persisted field names, resolved once.  ``load`` runs underneath every
#: appearance token and therefore from inside paint handlers, and it was asking
#: for these by building a whole default ``Preferences`` and deep-copying it
#: into a dict on every call, to read nothing but the keys.
_FIELD_NAMES: Tuple[str, ...] = tuple(field.name for field in fields(Preferences))


def load() -> Preferences:
    """Load preferences, migrating missing keys to the shipped values."""
    raw: Dict[str, Any] = config.get(PREFERENCES_ID, {})
    if not isinstance(raw, dict):
        raw = {}
    values = {key: raw[key] for key in _FIELD_NAMES if key in raw}
    return Preferences(**values).normalised()


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


def reset_display_name() -> Preferences:
    """Reset only the visible app label, preserving every other preference."""
    return update(display_name=DEFAULT_DISPLAY_NAME)
