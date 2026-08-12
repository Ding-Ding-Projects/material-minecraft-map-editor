"""The personal-vocabulary contract: an uploaded overlay reaches real UI text.

The mechanism (:mod:`amulet_map_editor.api.text_overlay`) and its upload
surface (the Preferences "Display-text overlay" row) already have their own
tests.  What this file proves is the missing link: that
:func:`amulet_map_editor.api.lang.get` -- the one function every localised,
user-facing string in this application passes through on its way to the
screen -- actually applies a loaded overlay, and that with nothing loaded it
is a complete no-op.

Every fixture here uses an obviously synthetic replacement, invented for the
test, never anything resembling real terminology.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def isolated_config_store(tmp_path, monkeypatch):
    """Give every test its own application-data directory for the cache."""
    from amulet_map_editor.api import config as config_module

    store_dir = tmp_path / "app-data"
    store_dir.mkdir()
    monkeypatch.setattr(config_module, "_path", str(store_dir))
    config_module._cache.clear()
    yield
    config_module._cache.clear()


def _write_overlay(tmp_path, replacements) -> str:
    path = tmp_path / "overlay.json"
    path.write_text(
        json.dumps(
            {"version": 1, "replacements": replacements, "required_phrases": []}
        ),
        encoding="utf-8",
    )
    return str(path)


def test_with_nothing_loaded_lang_get_is_a_complete_no_op():
    from amulet_map_editor.api import lang

    assert lang.get("some.unknown.key") == "some.unknown.key"


def test_a_loaded_overlay_substitutes_a_translated_strings_display_text(tmp_path):
    from amulet_map_editor.api import lang, text_overlay

    # "program_3d_edit.menu_bar.edit.undo" ships as "Undo" in en.lang -- pick a real shipped
    # value rather than inventing a key, so this proves the overlay reaches
    # a translation that actually exists.
    shipped = lang.get("program_3d_edit.menu_bar.edit.undo")
    assert shipped and shipped != "program_3d_edit.menu_bar.edit.undo"

    overlay_path = _write_overlay(tmp_path, {shipped: "Zorptastic"})
    text_overlay.load_overlay_file(overlay_path)
    try:
        assert lang.get("program_3d_edit.menu_bar.edit.undo") == "Zorptastic"
    finally:
        text_overlay.clear_cached_overlay()


def test_removing_the_overlay_returns_lang_get_to_shipped_wording(tmp_path):
    from amulet_map_editor.api import lang, text_overlay

    shipped = lang.get("program_3d_edit.menu_bar.edit.undo")
    overlay_path = _write_overlay(tmp_path, {shipped: "Zorptastic"})
    text_overlay.load_overlay_file(overlay_path)
    assert lang.get("program_3d_edit.menu_bar.edit.undo") == "Zorptastic"

    text_overlay.clear_cached_overlay()
    assert lang.get("program_3d_edit.menu_bar.edit.undo") == shipped


def test_an_unmatched_key_still_passes_through_the_overlay_unchanged(tmp_path):
    from amulet_map_editor.api import lang, text_overlay

    overlay_path = _write_overlay(tmp_path, {"Unrelated": "Whatever"})
    text_overlay.load_overlay_file(overlay_path)
    try:
        assert lang.get("nothing.matches.this") == "nothing.matches.this"
    finally:
        text_overlay.clear_cached_overlay()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
