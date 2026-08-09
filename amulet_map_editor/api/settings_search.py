"""Bounded, wx-independent search model for the Preferences surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

from amulet_map_editor.api.regex_builder import RegexBuilder


@dataclass(frozen=True)
class SettingSearchSpec:
    """One hand-written Preferences setting that must remain discoverable."""

    key: str
    tab: str
    control_name: str
    label: str
    description: str
    sensitive: bool = False


@dataclass(frozen=True)
class SettingSearchDocument:
    """A live setting value projected into the local search index."""

    spec: SettingSearchSpec
    current_value: str = ""

    @property
    def searchable_text(self) -> str:
        parts = (self.spec.label, self.spec.description)
        if self.current_value and not self.spec.sensitive:
            parts += (self.current_value,)
        return "\n".join(parts)

    @property
    def result_label(self) -> str:
        suffix = ""
        if self.current_value and not self.spec.sensitive:
            suffix = f" · {self.current_value}"
        return f"{self.spec.label} — {self.spec.tab}{suffix}"


# This list is deliberately hand-written. Adding a persisted setting without
# adding it here must fail the UI completeness contract instead of silently
# creating a Preferences control that search cannot discover.
PREFERENCES_SETTING_SPECS: Tuple[SettingSearchSpec, ...] = (
    SettingSearchSpec(
        "language-mode",
        "Language",
        "language",
        "Language mode",
        "Choose English, playful Hong Kong-style Cantonese, or bilingual copy.",
    ),
    SettingSearchSpec(
        "funny-english",
        "Language",
        "funny_en",
        "English funny level",
        "Set the English message voice from serious to maximally playful.",
    ),
    SettingSearchSpec(
        "funny-cantonese",
        "Language",
        "funny_yue",
        "Cantonese funny level",
        "Set the Cantonese message voice from serious to maximally playful.",
    ),
    SettingSearchSpec(
        "dialog-emojis",
        "Language",
        "dialog_emojis",
        "Dialog emojis",
        "Show decorative emoji in dialogs and message boxes.",
    ),
    SettingSearchSpec(
        "display-name",
        "Appearance",
        "display_name",
        "App display name",
        "Change the name shown in title bars and app messages.",
    ),
    SettingSearchSpec(
        "school-name",
        "Appearance",
        "school_name",
        "School mode name",
        "Rename the shared local presentation mode.",
    ),
    SettingSearchSpec(
        "school-enabled",
        "Appearance",
        "school_enabled",
        "School mode enabled",
        "Force English, serious copy, and no dialog emojis.",
    ),
    SettingSearchSpec(
        "school-credential",
        "Appearance",
        "school_credential",
        "Unlock credential",
        "Set or enter the local credential used to leave School mode.",
        sensitive=True,
    ),
    SettingSearchSpec(
        "theme",
        "Appearance",
        "theme",
        "Theme",
        "Select light, dark, or the operating-system theme.",
    ),
    SettingSearchSpec(
        "density",
        "Appearance",
        "density",
        "Density",
        "Control spacing throughout tabs, panels, and dialogs.",
    ),
    SettingSearchSpec(
        "accent",
        "Appearance",
        "accent",
        "Accent colour",
        "Set the Material 3 seed colour using a HEX value.",
    ),
    SettingSearchSpec(
        "ui-font",
        "Appearance",
        "font",
        "UI font",
        "Choose an installed user-interface font family.",
    ),
    SettingSearchSpec(
        "external-editor",
        "Appearance",
        "external_editor_path",
        "External editor",
        "Choose Visual Studio Code or a compatible Code executable.",
    ),
    SettingSearchSpec(
        "ui-scale",
        "Appearance",
        "scale",
        "UI scale",
        "Scale native text and controls from 80 to 200 percent.",
    ),
    SettingSearchSpec(
        "appearance-presets",
        "Appearance",
        "appearance_preset_list",
        "Named appearance presets",
        "Load, save, import, export, update, or delete appearance presets.",
    ),
    SettingSearchSpec(
        "schedule-enabled",
        "Schedule",
        "schedule_enabled",
        "Schedule enabled",
        "Enable or disable the selected scheduled-settings rule.",
    ),
    SettingSearchSpec(
        "schedule-label",
        "Schedule",
        "schedule_label",
        "Schedule label",
        "Name the selected scheduled-settings rule.",
    ),
    SettingSearchSpec(
        "schedule-priority",
        "Schedule",
        "schedule_priority",
        "Schedule priority",
        "Resolve matching rules using a deterministic priority.",
    ),
    SettingSearchSpec(
        "schedule-source-kind",
        "Schedule",
        "schedule_source_kind",
        "Schedule source",
        "Use local values, a validated HTTPS API, or Home Assistant.",
    ),
    SettingSearchSpec(
        "schedule-source-url",
        "Schedule",
        "schedule_source_url",
        "Schedule source URL",
        "Set the bounded HTTPS endpoint for an external rule source.",
    ),
    SettingSearchSpec(
        "schedule-source-entity",
        "Schedule",
        "schedule_source_entity",
        "Home Assistant entity",
        "Set the Home Assistant boolean entity that activates the rule.",
    ),
    SettingSearchSpec(
        "schedule-source-refresh",
        "Schedule",
        "schedule_source_refresh",
        "Source refresh interval",
        "Set the bounded external-source refresh interval in seconds.",
    ),
    SettingSearchSpec(
        "schedule-weekdays",
        "Schedule",
        "schedule_every_day",
        "Schedule weekdays",
        "Apply the rule every day or on selected weekdays.",
    ),
    SettingSearchSpec(
        "schedule-start-date",
        "Schedule",
        "schedule_start_date",
        "Schedule start date",
        "Set the optional local start date.",
    ),
    SettingSearchSpec(
        "schedule-end-date",
        "Schedule",
        "schedule_end_date",
        "Schedule end date",
        "Set the optional local end date.",
    ),
    SettingSearchSpec(
        "schedule-start-time",
        "Schedule",
        "schedule_start_time",
        "Schedule start time",
        "Set the local start time, including cross-midnight windows.",
    ),
    SettingSearchSpec(
        "schedule-end-time",
        "Schedule",
        "schedule_end_time",
        "Schedule end time",
        "Set the local end time, including cross-midnight windows.",
    ),
    SettingSearchSpec(
        "schedule-language",
        "Schedule",
        "schedule_language",
        "Scheduled language",
        "Temporarily override the active language mode.",
    ),
    SettingSearchSpec(
        "schedule-theme",
        "Schedule",
        "schedule_theme",
        "Scheduled theme",
        "Temporarily override the active theme.",
    ),
    SettingSearchSpec(
        "schedule-density",
        "Schedule",
        "schedule_density",
        "Scheduled density",
        "Temporarily override the active density.",
    ),
    SettingSearchSpec(
        "schedule-accent",
        "Schedule",
        "schedule_accent",
        "Scheduled accent colour",
        "Temporarily override the Material 3 accent colour.",
    ),
)


@dataclass(frozen=True)
class PreferencesSearchSurface:
    """One Preferences-owned search field and its adjacent builder controls."""

    query_control: str
    regex_mode_control: str
    regex_button_control: str


PREFERENCES_SEARCH_SURFACES: Tuple[PreferencesSearchSurface, ...] = (
    PreferencesSearchSurface("font_search", "font_regex", "font_regex_button"),
    PreferencesSearchSurface(
        "appearance_preset_search",
        "appearance_preset_regex",
        "appearance_preset_regex_button",
    ),
    PreferencesSearchSurface("regex", "regex_mode", "regex_button"),
)


def filter_setting_documents(
    documents: Iterable[SettingSearchDocument], builder: RegexBuilder
) -> Tuple[SettingSearchDocument, ...]:
    """Return matching documents in source order using one bounded pattern."""

    compiled = builder.compile()
    return tuple(
        document
        for document in documents
        if compiled.search(document.searchable_text[:4096]) is not None
    )
