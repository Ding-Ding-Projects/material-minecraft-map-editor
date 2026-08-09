import re

from amulet_map_editor.api.regex_builder import RegexBuilder
from amulet_map_editor.api.settings_search import (
    PREFERENCES_SEARCH_SURFACES,
    PREFERENCES_SETTING_SPECS,
    SettingSearchDocument,
    filter_setting_documents,
    localized_copy,
)

EXPECTED_SETTING_KEYS = {
    "language-mode",
    "funny-english",
    "funny-cantonese",
    "dialog-emojis",
    "display-name",
    "school-name",
    "school-enabled",
    "school-credential",
    "theme",
    "density",
    "accent",
    "ui-font",
    "external-editor",
    "ui-scale",
    "appearance-presets",
    "schedule-enabled",
    "schedule-label",
    "schedule-priority",
    "schedule-source-kind",
    "schedule-source-url",
    "schedule-source-entity",
    "schedule-source-refresh",
    "schedule-weekdays",
    "schedule-start-date",
    "schedule-end-date",
    "schedule-start-time",
    "schedule-end-time",
    "schedule-language",
    "schedule-theme",
    "schedule-density",
    "schedule-accent",
}


def test_hand_written_preferences_setting_inventory_is_complete_and_unique():
    assert {spec.key for spec in PREFERENCES_SETTING_SPECS} == EXPECTED_SETTING_KEYS
    assert len({spec.key for spec in PREFERENCES_SETTING_SPECS}) == len(
        PREFERENCES_SETTING_SPECS
    )
    assert len({spec.control_name for spec in PREFERENCES_SETTING_SPECS}) == len(
        PREFERENCES_SETTING_SPECS
    )
    assert {spec.tab for spec in PREFERENCES_SETTING_SPECS} == {
        "Language",
        "Appearance",
        "Schedule",
    }
    assert {spec.tab_id for spec in PREFERENCES_SETTING_SPECS} == {
        "language",
        "appearance",
        "schedule",
    }


def test_hand_written_preferences_search_surface_inventory_is_complete():
    assert {
        (
            surface.query_control,
            surface.regex_mode_control,
            surface.regex_button_control,
        )
        for surface in PREFERENCES_SEARCH_SURFACES
    } == {
        ("font_search", "font_regex", "font_regex_button"),
        (
            "appearance_preset_search",
            "appearance_preset_regex",
            "appearance_preset_regex_button",
        ),
        ("regex", "regex_mode", "regex_button"),
    }


def test_search_matches_labels_descriptions_and_current_values():
    theme = next(spec for spec in PREFERENCES_SETTING_SPECS if spec.key == "theme")
    editor = next(
        spec for spec in PREFERENCES_SETTING_SPECS if spec.key == "external-editor"
    )
    documents = (
        SettingSearchDocument(theme, "Dark"),
        SettingSearchDocument(editor, r"C:\Tools\Code.exe"),
    )
    assert filter_setting_documents(
        documents, RegexBuilder("operating-system", flags=re.IGNORECASE)
    ) == (documents[0],)
    assert filter_setting_documents(
        documents, RegexBuilder("code.exe", flags=re.IGNORECASE)
    ) == (documents[1],)
    assert filter_setting_documents(
        documents,
        RegexBuilder(r"^External editor", regex_enabled=True),
    ) == (documents[1],)


def test_sensitive_current_values_never_enter_index_or_result_copy():
    credential = next(
        spec for spec in PREFERENCES_SETTING_SPECS if spec.key == "school-credential"
    )
    document = SettingSearchDocument(credential, "do-not-index-this")
    assert "do-not-index-this" not in document.searchable_text
    assert "do-not-index-this" not in document.result_label
    assert (
        filter_setting_documents(
            (document,), RegexBuilder("do-not-index-this", flags=re.IGNORECASE)
        )
        == ()
    )


def test_every_inventory_entry_is_localized_in_all_three_modes():
    for spec in PREFERENCES_SETTING_SPECS:
        english = spec.localized("english")
        cantonese = spec.localized("cantonese")
        bilingual = spec.localized("bilingual")
        assert english.label != cantonese.label, spec.key
        assert english.description != cantonese.description, spec.key
        assert english.label in bilingual.label
        assert cantonese.label in bilingual.label
        assert english.description in bilingual.description
        assert cantonese.description in bilingual.description


def test_cantonese_and_bilingual_inventory_text_is_searchable():
    theme = next(spec for spec in PREFERENCES_SETTING_SPECS if spec.key == "theme")
    cantonese = SettingSearchDocument(theme, "深色", "cantonese")
    bilingual = SettingSearchDocument(theme, "Dark · 深色", "bilingual")
    assert filter_setting_documents(
        (cantonese,), RegexBuilder("作業系統", flags=re.IGNORECASE)
    ) == (cantonese,)
    assert filter_setting_documents(
        (bilingual,), RegexBuilder("operating-system", flags=re.IGNORECASE)
    ) == (bilingual,)
    assert filter_setting_documents(
        (bilingual,), RegexBuilder("作業系統", flags=re.IGNORECASE)
    ) == (bilingual,)


def test_bilingual_result_formats_each_language_once():
    theme = next(spec for spec in PREFERENCES_SETTING_SPECS if spec.key == "theme")
    result = SettingSearchDocument(theme, "Light", "bilingual").result_label
    assert result.count(theme.localized("english").label) == 1
    assert result.count(theme.localized("cantonese").label) == 1
    assert result.count("Light") == 2


def test_search_and_builder_copy_inventory_is_complete_in_every_mode():
    keys = {
        "tab",
        "section.label",
        "section.description",
        "hint",
        "regex",
        "ignorecase",
        "builder",
        "builder.help",
        "empty",
        "searching",
        "invalid",
        "timeout",
        "worker.failure",
        "count",
        "select",
        "unavailable",
        "opened",
        "open",
        "results",
        "result",
        "on",
        "off",
        "everyday",
        "nooverride",
        "builder.title",
        "builder.window.title",
        "builder.description",
        "builder.pattern",
        "builder.use.regex",
        "builder.ignore.case",
        "builder.multiline",
        "builder.dotall",
        "builder.guided",
        "builder.guided.help",
        "builder.literal",
        "builder.class",
        "builder.start",
        "builder.end",
        "builder.group",
        "builder.alternation",
        "builder.zero.or.more",
        "builder.one.or.more",
        "builder.optional",
        "builder.repeat",
        "builder.sample",
        "builder.prompt",
        "builder.checking",
        "builder.invalid",
        "builder.timeout",
        "builder.valid",
        "builder.groups",
        "builder.unmatched",
        "builder.empty",
        "builder.additional",
        "builder.nomatch",
        "builder.copy",
        "builder.copied",
        "builder.clipboard",
        "builder.apply",
        "builder.cancel",
    }
    formatted = {
        "count": {"count": 1},
        "invalid": {"error": "example"},
        "opened": {"label": "Theme", "tab": "Appearance"},
        "result": {"label": "Theme", "tab": "Appearance", "value": ""},
        "builder.invalid": {"error": "example"},
        "builder.valid": {"count": 1},
        "builder.groups": {"groups": ("one",)},
    }
    for key in keys:
        values = formatted.get(key, {})
        english = localized_copy(key, "english", **values)
        cantonese = localized_copy(key, "cantonese", **values)
        bilingual = localized_copy(key, "bilingual", **values)
        assert not english.startswith("preferences.en.search."), key
        assert not cantonese.startswith("preferences.zh.search."), key
        if key != "result":
            assert english != cantonese, key
        assert english in bilingual and cantonese in bilingual
