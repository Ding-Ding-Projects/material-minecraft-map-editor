"""Versioned, wx-independent appearance presets.

The active appearance remains stored by :mod:`preferences`.  This module owns
only a named preset library and deliberately applies the existing preference
fields instead of introducing a competing active-settings schema.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import re
from typing import Any, Dict, Iterable, Mapping, Tuple

from amulet_map_editor.api import config, preferences

APPEARANCE_PRESETS_ID = "amulet_appearance_presets"
APPEARANCE_PRESETS_VERSION = 1
EXPORT_SCHEMA = "amulet-appearance-preset"
APPEARANCE_FIELDS: Tuple[str, ...] = (
    "theme",
    "density",
    "accent",
    "ui_font",
    "ui_scale",
)
MAX_PRESETS = 100
MAX_NAME_LENGTH = 64
MAX_FONT_LENGTH = 128
MAX_IMPORT_BYTES = 32 * 1024
_ACCENT = re.compile(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class AppearancePresetValidationError(ValueError):
    """Raised when a preset or import does not satisfy the public schema."""


class UnsupportedAppearancePresetVersion(AppearancePresetValidationError):
    """Raised when readable data belongs to a newer or older schema."""


def _require_exact_keys(
    value: Mapping[str, Any], expected: Iterable[str], label: str
) -> None:
    if any(not isinstance(key, str) for key in value):
        raise AppearancePresetValidationError(f"{label} keys must be text")
    expected_keys = set(expected)
    actual_keys = set(value)
    missing = expected_keys - actual_keys
    unknown = actual_keys - expected_keys
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unknown " + ", ".join(sorted(unknown)))
        raise AppearancePresetValidationError(f"{label} has " + "; ".join(details))


def _validate_text(value: Any, label: str, maximum: int, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise AppearancePresetValidationError(f"{label} must be text")
    if not allow_empty and not value.strip():
        raise AppearancePresetValidationError(f"{label} must not be empty")
    if len(value) > maximum:
        raise AppearancePresetValidationError(
            f"{label} must be at most {maximum} characters"
        )
    if _CONTROL_CHARACTERS.search(value):
        raise AppearancePresetValidationError(
            f"{label} must not contain control characters"
        )
    return value


@dataclass(frozen=True)
class AppearanceValues:
    """The complete versioned value set captured by one preset."""

    version: int = APPEARANCE_PRESETS_VERSION
    theme: str = "system"
    density: str = "comfortable"
    accent: str = "#6750A4"
    ui_font: str = ""
    ui_scale: float = 1.0

    def validated(self) -> "AppearanceValues":
        """Return a canonical copy or raise for unsupported data."""
        if type(self.version) is not int or self.version != APPEARANCE_PRESETS_VERSION:
            raise AppearancePresetValidationError(
                f"appearance version must be {APPEARANCE_PRESETS_VERSION}"
            )
        if self.theme not in preferences.THEMES:
            raise AppearancePresetValidationError("theme is not supported")
        if self.density not in preferences.DENSITIES:
            raise AppearancePresetValidationError("density is not supported")
        if not isinstance(self.accent, str) or _ACCENT.fullmatch(self.accent) is None:
            raise AppearancePresetValidationError("accent must be #RRGGBB or #RRGGBBAA")
        font = _validate_text(self.ui_font, "ui_font", MAX_FONT_LENGTH, True)
        if isinstance(self.ui_scale, bool) or not isinstance(
            self.ui_scale, (int, float)
        ):
            raise AppearancePresetValidationError("ui_scale must be a number")
        scale = float(self.ui_scale)
        if not math.isfinite(scale) or not 0.8 <= scale <= 2.0:
            raise AppearancePresetValidationError(
                "ui_scale must be between 0.8 and 2.0"
            )
        return AppearanceValues(
            version=self.version,
            theme=self.theme,
            density=self.density,
            accent=self.accent.upper(),
            ui_font=font,
            ui_scale=scale,
        )

    @classmethod
    def from_dict(cls, raw: Any) -> "AppearanceValues":
        if not isinstance(raw, Mapping):
            raise AppearancePresetValidationError("values must be an object")
        _require_exact_keys(raw, asdict(cls()).keys(), "values")
        return cls(**dict(raw)).validated()

    @classmethod
    def from_preferences(
        cls, current: preferences.Preferences | None = None
    ) -> "AppearanceValues":
        current = (
            preferences.load()
            if current is None
            else preferences.Preferences(**asdict(current)).normalised()
        )
        accent = current.accent
        if _ACCENT.fullmatch(accent) is None:
            # Preferences historically accepted one ambiguous seven-digit form.
            # Presets keep the documented 6/8-digit contract and safely capture
            # the shipped accent instead of failing on that legacy value.
            accent = preferences.Preferences().accent
        try:
            font = _validate_text(current.ui_font, "ui_font", MAX_FONT_LENGTH, True)
        except AppearancePresetValidationError:
            font = preferences.Preferences().ui_font
        return cls(
            theme=current.theme,
            density=current.density,
            accent=accent,
            ui_font=font,
            ui_scale=current.ui_scale,
        ).validated()


SHIPPED_APPEARANCE = AppearanceValues.from_preferences(preferences.Preferences())


@dataclass(frozen=True)
class AppearancePreset:
    """A validated named snapshot of all appearance values."""

    name: str
    values: AppearanceValues

    def validated(self) -> "AppearancePreset":
        if not isinstance(self.values, AppearanceValues):
            raise AppearancePresetValidationError(
                "values must be an AppearanceValues instance"
            )
        return AppearancePreset(
            _validate_text(self.name, "name", MAX_NAME_LENGTH, False).strip(),
            self.values.validated(),
        )

    @classmethod
    def from_dict(cls, raw: Any) -> "AppearancePreset":
        if not isinstance(raw, Mapping):
            raise AppearancePresetValidationError("preset must be an object")
        _require_exact_keys(raw, ("name", "values"), "preset")
        return cls(
            name=raw["name"], values=AppearanceValues.from_dict(raw["values"])
        ).validated()

    def to_dict(self) -> Dict[str, Any]:
        preset = self.validated()
        return {"name": preset.name, "values": asdict(preset.values)}


def _library_payload(presets: Iterable[AppearancePreset]) -> Dict[str, Any]:
    return {
        "version": APPEARANCE_PRESETS_VERSION,
        "presets": [preset.to_dict() for preset in presets],
    }


def load_presets() -> Tuple[AppearancePreset, ...]:
    """Load presets, failing closed on readable unsupported or invalid data."""
    raw = config.get(APPEARANCE_PRESETS_ID, None)
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        raise AppearancePresetValidationError("preset library must be an object")
    _require_exact_keys(raw, ("version", "presets"), "preset library")
    if type(raw["version"]) is not int or raw["version"] != APPEARANCE_PRESETS_VERSION:
        raise UnsupportedAppearancePresetVersion(
            f"preset library version {raw['version']!r} is not supported"
        )
    stored = raw.get("presets")
    if not isinstance(stored, list):
        raise AppearancePresetValidationError("presets must be a list")
    if len(stored) > MAX_PRESETS:
        raise AppearancePresetValidationError(
            f"no more than {MAX_PRESETS} presets may be stored"
        )
    presets = []
    names = set()
    for item in stored:
        preset = AppearancePreset.from_dict(item)
        folded = preset.name.casefold()
        if folded in names:
            raise AppearancePresetValidationError(
                "preset names must be unique case-insensitively"
            )
        names.add(folded)
        presets.append(preset)
    return tuple(presets)


def save_preset(
    name: str,
    values: AppearanceValues | None = None,
    *,
    replace: bool = False,
) -> AppearancePreset:
    """Persist a named preset, rejecting accidental duplicate names."""
    preset = AppearancePreset(
        name=name,
        values=AppearanceValues.from_preferences() if values is None else values,
    ).validated()
    stored = list(load_presets())
    index = next(
        (
            i
            for i, item in enumerate(stored)
            if item.name.casefold() == preset.name.casefold()
        ),
        None,
    )
    if index is not None and not replace:
        raise AppearancePresetValidationError("a preset with this name already exists")
    if index is None:
        if len(stored) >= MAX_PRESETS:
            raise AppearancePresetValidationError(
                f"no more than {MAX_PRESETS} presets may be stored"
            )
        stored.append(preset)
    else:
        stored[index] = preset
    config.put(APPEARANCE_PRESETS_ID, _library_payload(stored))
    return preset


def delete_preset(name: str) -> bool:
    """Delete a preset by case-insensitive name and report whether it existed."""
    name = _validate_text(name, "name", MAX_NAME_LENGTH, False).strip()
    stored = list(load_presets())
    remaining = [item for item in stored if item.name.casefold() != name.casefold()]
    if len(remaining) == len(stored):
        return False
    config.put(APPEARANCE_PRESETS_ID, _library_payload(remaining))
    return True


def apply_values(values: AppearanceValues) -> preferences.Preferences:
    """Apply only appearance fields through the existing preferences schema."""
    if not isinstance(values, AppearanceValues):
        raise AppearancePresetValidationError(
            "values must be an AppearanceValues instance"
        )
    validated = values.validated()
    return preferences.update(
        **{field: getattr(validated, field) for field in APPEARANCE_FIELDS}
    )


def apply_preset(name: str) -> preferences.Preferences:
    """Apply a stored preset by case-insensitive name."""
    requested = _validate_text(name, "name", MAX_NAME_LENGTH, False).strip().casefold()
    for preset in load_presets():
        if preset.name.casefold() == requested:
            return apply_values(preset.values)
    raise KeyError(name)


def reset_property(property_name: str) -> preferences.Preferences:
    """Reset one appearance property while preserving every other preference."""
    if property_name not in APPEARANCE_FIELDS:
        raise KeyError(property_name)
    return preferences.update(
        **{property_name: getattr(SHIPPED_APPEARANCE, property_name)}
    )


def reset_appearance() -> preferences.Preferences:
    """Reset all appearance values without resetting language or humour state."""
    return apply_values(SHIPPED_APPEARANCE)


def export_preset(preset: AppearancePreset) -> str:
    """Return a deterministic, versioned JSON export for one preset."""
    payload = {
        "schema": EXPORT_SCHEMA,
        "version": APPEARANCE_PRESETS_VERSION,
        "preset": preset.to_dict(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def import_preset(payload: str | bytes, *, replace: bool = False) -> AppearancePreset:
    """Validate and persist one exported preset without trusting its contents."""
    if isinstance(payload, bytes):
        if len(payload) > MAX_IMPORT_BYTES:
            raise AppearancePresetValidationError("import is too large")
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AppearancePresetValidationError("import must be UTF-8") from exc
    elif not isinstance(payload, str):
        raise AppearancePresetValidationError("import must be text or UTF-8 bytes")
    try:
        payload_size = len(payload.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise AppearancePresetValidationError("import must be valid UTF-8") from exc
    if payload_size > MAX_IMPORT_BYTES:
        raise AppearancePresetValidationError("import is too large")
    try:
        raw = json.loads(payload)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise AppearancePresetValidationError("import is not valid JSON") from exc
    if not isinstance(raw, Mapping):
        raise AppearancePresetValidationError("import root must be an object")
    _require_exact_keys(raw, ("schema", "version", "preset"), "import")
    if raw["schema"] != EXPORT_SCHEMA:
        raise AppearancePresetValidationError("import schema is not supported")
    if type(raw["version"]) is not int or raw["version"] != APPEARANCE_PRESETS_VERSION:
        raise AppearancePresetValidationError(
            f"import version must be {APPEARANCE_PRESETS_VERSION}"
        )
    preset = AppearancePreset.from_dict(raw["preset"])
    return save_preset(preset.name, preset.values, replace=replace)
