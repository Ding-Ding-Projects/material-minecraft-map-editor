"""Localized, bounded search model for the native Preferences surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

from amulet_map_editor.api import lang
from amulet_map_editor.api.regex_builder import (
    RegexBuilder,
    RegexResult,
    evaluate_regex_bounded,
)


def localized_copy(
    key: str,
    mode: str,
    *,
    bilingual_separator: str = " · ",
    **values: object,
) -> str:
    """Resolve one Preferences search string independently of OS locale."""

    english = lang.get(f"preferences.en.search.{key}")
    cantonese = lang.get(f"preferences.zh.search.{key}")
    if mode == "cantonese":
        text = cantonese
    elif mode == "bilingual":
        text = f"{english}{bilingual_separator}{cantonese}"
    else:
        text = english
    return text.format(**values)


@dataclass(frozen=True)
class SettingSearchSpec:
    """One hand-written Preferences setting that must remain discoverable."""

    key: str
    tab_id: str
    control_name: str
    sensitive: bool = False

    def localized(self, mode: str) -> "LocalizedSettingSearchSpec":
        resource = self.key.replace("-", ".")
        return LocalizedSettingSearchSpec(
            key=self.key,
            tab_id=self.tab_id,
            control_name=self.control_name,
            tab=localized_copy(f"tab.{self.tab_id}", mode),
            label=localized_copy(f"setting.{resource}.label", mode),
            description=localized_copy(f"setting.{resource}.description", mode),
            sensitive=self.sensitive,
        )

    @property
    def tab(self) -> str:
        return self.localized("english").tab

    @property
    def label(self) -> str:
        return self.localized("english").label

    @property
    def description(self) -> str:
        return self.localized("english").description


@dataclass(frozen=True)
class LocalizedSettingSearchSpec:
    key: str
    tab_id: str
    control_name: str
    tab: str
    label: str
    description: str
    sensitive: bool = False


@dataclass(frozen=True)
class SettingSearchDocument:
    """A live setting value projected into the selected language's index."""

    spec: SettingSearchSpec
    current_value: str = ""
    language_mode: str = "english"

    @property
    def localized_spec(self) -> LocalizedSettingSearchSpec:
        return self.spec.localized(self.language_mode)

    @property
    def searchable_text(self) -> str:
        localized = self.localized_spec
        parts = (localized.label, localized.description)
        if self.current_value and not self.spec.sensitive:
            parts += (self.current_value,)
        return "\n".join(parts)

    @property
    def result_label(self) -> str:
        suffix = ""
        if self.current_value and not self.spec.sensitive:
            suffix = f" · {self.current_value}"
        if self.language_mode == "bilingual":
            english = self.spec.localized("english")
            cantonese = self.spec.localized("cantonese")
            english_result = localized_copy(
                "result",
                "english",
                label=english.label,
                tab=english.tab,
                value=suffix,
            )
            cantonese_result = localized_copy(
                "result",
                "cantonese",
                label=cantonese.label,
                tab=cantonese.tab,
                value=suffix,
            )
            return f"{english_result} · {cantonese_result}"
        localized = self.localized_spec
        return localized_copy(
            "result",
            self.language_mode,
            label=localized.label,
            tab=localized.tab,
            value=suffix,
        )


# This list is deliberately hand-written. Adding a persisted setting without
# adding it here must fail the UI completeness contract instead of silently
# creating a Preferences control that search cannot discover.
PREFERENCES_SETTING_SPECS: Tuple[SettingSearchSpec, ...] = (
    SettingSearchSpec("language-mode", "language", "language"),
    SettingSearchSpec("funny-english", "language", "funny_en"),
    SettingSearchSpec("funny-cantonese", "language", "funny_yue"),
    SettingSearchSpec("dialog-emojis", "language", "dialog_emojis"),
    SettingSearchSpec("display-name", "appearance", "display_name"),
    SettingSearchSpec("school-name", "appearance", "school_name"),
    SettingSearchSpec("school-enabled", "appearance", "school_enabled"),
    SettingSearchSpec(
        "school-credential", "appearance", "school_credential", sensitive=True
    ),
    SettingSearchSpec("theme", "appearance", "theme"),
    SettingSearchSpec("density", "appearance", "density"),
    SettingSearchSpec("accent", "appearance", "accent"),
    SettingSearchSpec("ui-font", "appearance", "font"),
    SettingSearchSpec("external-editor", "appearance", "external_editor_path"),
    SettingSearchSpec("ui-scale", "appearance", "scale"),
    SettingSearchSpec("appearance-presets", "appearance", "appearance_preset_list"),
    SettingSearchSpec("schedule-enabled", "schedule", "schedule_enabled"),
    SettingSearchSpec("schedule-label", "schedule", "schedule_label"),
    SettingSearchSpec("schedule-priority", "schedule", "schedule_priority"),
    SettingSearchSpec("schedule-source-kind", "schedule", "schedule_source_kind"),
    SettingSearchSpec("schedule-source-url", "schedule", "schedule_source_url"),
    SettingSearchSpec("schedule-source-entity", "schedule", "schedule_source_entity"),
    SettingSearchSpec("schedule-source-refresh", "schedule", "schedule_source_refresh"),
    SettingSearchSpec("schedule-weekdays", "schedule", "schedule_every_day"),
    SettingSearchSpec("schedule-start-date", "schedule", "schedule_start_date"),
    SettingSearchSpec("schedule-end-date", "schedule", "schedule_end_date"),
    SettingSearchSpec("schedule-start-time", "schedule", "schedule_start_time"),
    SettingSearchSpec("schedule-end-time", "schedule", "schedule_end_time"),
    SettingSearchSpec("schedule-language", "schedule", "schedule_language"),
    SettingSearchSpec("schedule-theme", "schedule", "schedule_theme"),
    SettingSearchSpec("schedule-density", "schedule", "schedule_density"),
    SettingSearchSpec("schedule-accent", "schedule", "schedule_accent"),
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


def documents_from_result(
    documents: Tuple[SettingSearchDocument, ...], result: RegexResult
) -> Tuple[SettingSearchDocument, ...]:
    """Project safe worker indices back to the immutable source documents."""

    return tuple(documents[index] for index in result.matched_indices)


def filter_setting_documents(
    documents: Iterable[SettingSearchDocument], builder: RegexBuilder
) -> Tuple[SettingSearchDocument, ...]:
    """Process-bound matching retained for wx-independent callers and tests."""

    source = tuple(documents)
    result = evaluate_regex_bounded(
        builder.request(tuple(document.searchable_text[:4096] for document in source))
    )
    if result.timed_out:
        raise TimeoutError(result.error or "Regular-expression evaluation timed out")
    if not result.valid:
        raise ValueError(result.error or "Invalid regular expression")
    return documents_from_result(source, result)
