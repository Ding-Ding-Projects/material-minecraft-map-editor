"""Tests for the generic, content-agnostic display-text overlay.

Every fixture here uses obviously synthetic strings invented for the test --
``widget``/``gadget`` and ``panel``/``board`` -- never anything that
resembles real terminology.  This module must stay usable as evidence that
the mechanism works with no bundled vocabulary of its own.
"""

from __future__ import annotations

import json

import pytest

from amulet_map_editor.api import config as config_module
from amulet_map_editor.api import text_overlay

WIDGET_DOCUMENT = {
    "version": 1,
    "replacements": {"widget": "gadget", "panel": "board"},
    "required_phrases": [],
}


def _bytes(document) -> bytes:
    return json.dumps(document).encode("utf-8")


def _overlay(**overrides) -> text_overlay.TextOverlay:
    document = {**WIDGET_DOCUMENT, **overrides}
    return text_overlay.parse_overlay_bytes(_bytes(document))


@pytest.fixture(autouse=True)
def isolated_config_store(tmp_path, monkeypatch):
    """Give every test its own application-data directory for the cache.

    The production cache is written through :mod:`config`, which resolves to
    the application's profile directory.  Pointing that module at a fresh
    temporary directory keeps one test's cached overlay from leaking into
    the next, and lets tests assert exactly where a file landed.
    """

    store_dir = tmp_path / "app-data"
    store_dir.mkdir()
    monkeypatch.setattr(config_module, "_path", str(store_dir))
    config_module._cache.clear()
    yield store_dir
    config_module._cache.clear()


# ---------------------------------------------------------------------------
# Valid load
# ---------------------------------------------------------------------------


def test_valid_overlay_loads_with_its_fields_intact():
    overlay = _overlay()
    assert overlay.version == 1
    assert dict(overlay.replacements) == {"widget": "gadget", "panel": "board"}
    assert overlay.required_phrases == ()


def test_valid_overlay_substitutes_every_configured_term():
    overlay = _overlay()
    assert (
        text_overlay.substitute_text(overlay, "Open the widget panel")
        == "Open the gadget board"
    )


def test_longest_matching_key_wins_over_a_shorter_prefix_key():
    # "units" deliberately shares no characters with "gadget" -- if the
    # shorter "widget" key matched first inside "widgets" and only its six
    # characters were replaced, the leftover "s" would still spell "gadgets"
    # by coincidence and hide the bug.  This wording cannot pass by accident.
    overlay = _overlay(replacements={"widget": "gadget", "widgets": "units"})
    assert (
        text_overlay.substitute_text(overlay, "I have widgets and a widget.")
        == "I have units and a gadget."
    )


# ---------------------------------------------------------------------------
# File-level refusals
# ---------------------------------------------------------------------------


def test_missing_file_raises_a_clear_error(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(text_overlay.OverlayFileError) as excinfo:
        text_overlay.load_overlay_file(missing)
    assert "not found" in str(excinfo.value)


def test_corrupt_json_raises_a_clear_error():
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        text_overlay.parse_overlay_bytes(b"{not valid json")
    assert "not valid JSON" in str(excinfo.value)


def test_oversize_file_is_refused_before_parsing():
    raw = b"{" + b" " * (text_overlay.MAX_OVERLAY_FILE_BYTES + 10) + b"}"
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        text_overlay.parse_overlay_bytes(raw)
    message = str(excinfo.value)
    assert "bytes" in message
    assert str(text_overlay.MAX_OVERLAY_FILE_BYTES) in message


def test_non_utf8_bytes_are_refused():
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        text_overlay.parse_overlay_bytes(b"\xff\xfe\x00\x01")
    assert "UTF-8" in str(excinfo.value)


def test_top_level_json_array_is_refused():
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        text_overlay.parse_overlay_bytes(_bytes([1, 2, 3]))
    assert "JSON object" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Schema shape refusals
# ---------------------------------------------------------------------------


def test_unknown_top_level_key_is_refused_not_ignored():
    document = {**WIDGET_DOCUMENT, "note": "extra"}
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        text_overlay.parse_overlay_bytes(_bytes(document))
    assert "unexpected" in str(excinfo.value)
    assert "'note'" in str(excinfo.value)


def test_missing_top_level_key_is_refused():
    document = {"version": 1, "replacements": {}}
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        text_overlay.parse_overlay_bytes(_bytes(document))
    assert "missing" in str(excinfo.value)
    assert "'required_phrases'" in str(excinfo.value)


def test_version_wrong_type_is_refused():
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        _overlay(version="1")
    assert "whole number" in str(excinfo.value)


def test_version_boolean_is_refused():
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        _overlay(version=True)
    assert "whole number" in str(excinfo.value)


def test_unsupported_version_is_refused():
    with pytest.raises(text_overlay.UnsupportedOverlayVersion) as excinfo:
        _overlay(version=2)
    assert "not supported" in str(excinfo.value)


def test_replacements_wrong_type_is_refused():
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        _overlay(replacements=["widget", "gadget"])
    assert "JSON object" in str(excinfo.value)


def test_required_phrases_wrong_type_is_refused():
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        _overlay(required_phrases={"widget": "gadget"})
    assert "list of strings" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------


def test_too_many_replacement_entries_is_refused():
    huge = {
        f"term{i}": f"value{i}" for i in range(text_overlay.MAX_REPLACEMENT_ENTRIES + 1)
    }
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        _overlay(replacements=huge)
    message = str(excinfo.value)
    assert str(text_overlay.MAX_REPLACEMENT_ENTRIES) in message


def test_too_many_required_phrases_is_refused():
    huge = [f"phrase{i}" for i in range(text_overlay.MAX_REQUIRED_PHRASES + 1)]
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        _overlay(required_phrases=huge)
    message = str(excinfo.value)
    assert str(text_overlay.MAX_REQUIRED_PHRASES) in message


def test_overlong_replacement_key_is_refused():
    document = {
        "version": 1,
        "replacements": {"w" * (text_overlay.MAX_KEY_LENGTH + 1): "gadget"},
        "required_phrases": [],
    }
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        text_overlay.parse_overlay_bytes(_bytes(document))
    message = str(excinfo.value)
    assert "replacement key" in message
    assert str(text_overlay.MAX_KEY_LENGTH) in message


def test_overlong_replacement_value_is_refused():
    document = {
        "version": 1,
        "replacements": {"widget": "g" * (text_overlay.MAX_VALUE_LENGTH + 1)},
        "required_phrases": [],
    }
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        text_overlay.parse_overlay_bytes(_bytes(document))
    message = str(excinfo.value)
    assert "replacement value" in message
    assert str(text_overlay.MAX_VALUE_LENGTH) in message


def test_overlong_required_phrase_is_refused():
    document = {
        "version": 1,
        "replacements": {},
        "required_phrases": ["p" * (text_overlay.MAX_KEY_LENGTH + 1)],
    }
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        text_overlay.parse_overlay_bytes(_bytes(document))
    message = str(excinfo.value)
    assert "required phrase" in message
    assert str(text_overlay.MAX_KEY_LENGTH) in message


def test_empty_replacement_key_is_refused():
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        _overlay(replacements={"": "gadget"})
    assert "cannot be empty" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Non-string / malformed values
# ---------------------------------------------------------------------------


def test_non_string_replacement_value_is_refused():
    document = {
        "version": 1,
        "replacements": {"widget": 42},
        "required_phrases": [],
    }
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        text_overlay.parse_overlay_bytes(_bytes(document))
    assert "replacement value" in str(excinfo.value)
    assert "must be a string" in str(excinfo.value)


def test_non_string_required_phrase_is_refused():
    document = {
        "version": 1,
        "replacements": {},
        "required_phrases": [42],
    }
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        text_overlay.parse_overlay_bytes(_bytes(document))
    assert "required phrase" in str(excinfo.value)
    assert "must be a string" in str(excinfo.value)


def test_control_character_in_replacement_value_is_refused():
    document = {
        "version": 1,
        "replacements": {"widget": "gad\x07get"},
        "required_phrases": [],
    }
    with pytest.raises(text_overlay.OverlayValidationError) as excinfo:
        text_overlay.parse_overlay_bytes(_bytes(document))
    assert "control character" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Absent overlay behaviour
# ---------------------------------------------------------------------------


def test_absent_overlay_leaves_display_text_completely_unchanged():
    assert (
        text_overlay.substitute_text(None, "Open widget panel") == "Open widget panel"
    )


def test_absent_overlay_leaves_accessible_names_completely_unchanged():
    assert (
        text_overlay.substitute_accessible_name(None, "Open widget panel")
        == "Open widget panel"
    )


def test_no_cached_overlay_by_default():
    assert text_overlay.load_cached_overlay() is None


# ---------------------------------------------------------------------------
# Accessible names
# ---------------------------------------------------------------------------


def test_accessible_name_uses_the_same_substitution_boundary():
    overlay = _overlay()
    assert (
        text_overlay.substitute_accessible_name(overlay, "Open widget panel")
        == "Open gadget board"
    )


# ---------------------------------------------------------------------------
# required_phrases protection -- including realistic technical fragments
# ---------------------------------------------------------------------------


def test_required_phrase_is_protected_while_the_rest_of_the_sentence_substitutes():
    overlay = _overlay(required_phrases=["order widget-9000"])
    text = "Buy a widget or order widget-9000 today."
    assert (
        text_overlay.substitute_text(overlay, text)
        == "Buy a gadget or order widget-9000 today."
    )


def test_required_phrase_protects_a_url_embedded_in_display_text():
    overlay = _overlay(required_phrases=["https://example.com/widget-guide"])
    text = "See https://example.com/widget-guide for the widget manual."
    assert (
        text_overlay.substitute_text(overlay, text)
        == "See https://example.com/widget-guide for the gadget manual."
    )


def test_required_phrase_protects_a_commit_sha_like_token_embedded_in_display_text():
    overlay = _overlay(required_phrases=["deadwidgetbeef1234567"])
    text = "Commit deadwidgetbeef1234567 fixed the widget."
    assert (
        text_overlay.substitute_text(overlay, text)
        == "Commit deadwidgetbeef1234567 fixed the gadget."
    )


def test_required_phrase_protects_a_file_path_embedded_in_display_text():
    overlay = _overlay(required_phrases=["C:\\Users\\widget\\file.txt"])
    text = "Saved to C:\\Users\\widget\\file.txt after editing the widget."
    assert (
        text_overlay.substitute_text(overlay, text)
        == "Saved to C:\\Users\\widget\\file.txt after editing the gadget."
    )


def test_required_phrase_protects_a_version_string_embedded_in_display_text():
    overlay = _overlay(required_phrases=["v1.2.3-widget"])
    text = "Release v1.2.3-widget ships a new widget."
    assert (
        text_overlay.substitute_text(overlay, text)
        == "Release v1.2.3-widget ships a new gadget."
    )


# ---------------------------------------------------------------------------
# Cache: written to the application's own data directory, never the project
# ---------------------------------------------------------------------------


def test_cache_is_written_to_the_app_data_directory_not_the_project(
    tmp_path, isolated_config_store
):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    overlay_path = project_dir / "overlay.json"
    overlay_path.write_text(json.dumps(WIDGET_DOCUMENT), encoding="utf-8")

    text_overlay.load_overlay_file(overlay_path)

    cache_file = isolated_config_store / f"{text_overlay.OVERLAY_CACHE_ID}.config"
    assert cache_file.is_file()
    # Nothing was written into the user's project besides the file they
    # explicitly supplied.
    assert list(project_dir.iterdir()) == [overlay_path]


def test_cached_overlay_round_trips_after_a_simulated_restart(tmp_path):
    overlay_path = tmp_path / "overlay.json"
    overlay_path.write_text(json.dumps(WIDGET_DOCUMENT), encoding="utf-8")

    loaded = text_overlay.load_overlay_file(overlay_path)
    # A restart starts a new process with an empty in-memory cache; clearing
    # config's own read-through cache stands in for that here.
    config_module.invalidate()

    restored = text_overlay.load_cached_overlay()
    assert restored == loaded


def test_failed_load_does_not_disturb_a_previously_cached_overlay(tmp_path):
    good_path = tmp_path / "good.json"
    good_path.write_text(json.dumps(WIDGET_DOCUMENT), encoding="utf-8")
    text_overlay.load_overlay_file(good_path)

    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(text_overlay.OverlayValidationError):
        text_overlay.load_overlay_file(bad_path)

    assert text_overlay.load_cached_overlay() == _overlay()


def test_corrupted_cache_behaves_like_no_overlay_at_all():
    config_module.put(
        text_overlay.OVERLAY_CACHE_ID,
        {"version": 1, "replacements": "not-a-mapping", "required_phrases": []},
    )
    assert text_overlay.load_cached_overlay() is None


def test_clear_cached_overlay_returns_to_the_shipped_wording(tmp_path):
    overlay_path = tmp_path / "overlay.json"
    overlay_path.write_text(json.dumps(WIDGET_DOCUMENT), encoding="utf-8")
    text_overlay.load_overlay_file(overlay_path)
    assert text_overlay.load_cached_overlay() is not None

    text_overlay.clear_cached_overlay()

    assert text_overlay.load_cached_overlay() is None
