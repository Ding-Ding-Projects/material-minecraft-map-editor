from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys

_MODULE_PATH = (
    Path(__file__).parents[3] / "amulet_map_editor/api/framework/update_copy.py"
)
_SPEC = importlib.util.spec_from_file_location("update_copy", _MODULE_PATH)
assert _SPEC and _SPEC.loader
update_copy = importlib.util.module_from_spec(_SPEC)
sys.modules["update_copy"] = update_copy
_SPEC.loader.exec_module(update_copy)


@dataclass
class _Prefs:
    language_mode: str = "english"
    funny_level_english: int = 1
    funny_level_cantonese: int = 1


def test_update_copy_respects_each_language_funny_level(monkeypatch):
    prefs = _Prefs(language_mode="english", funny_level_english=3)
    monkeypatch.setattr(update_copy.preferences, "load", lambda: prefs)
    monkeypatch.setattr(
        update_copy.school_mode, "presentation_preferences", lambda value: value
    )

    title, body = update_copy.update_copy("ready_to_restart", version="1.2.3")

    assert title == "Update ready"
    assert (
        "1.2.3" not in body
    )  # staging copy states the actual action, not a guessed version
    assert "waiting politely" in body


def test_update_copy_bilingual_contains_factual_actions(monkeypatch):
    prefs = _Prefs(
        language_mode="bilingual", funny_level_english=1, funny_level_cantonese=1
    )
    monkeypatch.setattr(update_copy.preferences, "load", lambda: prefs)
    monkeypatch.setattr(
        update_copy.school_mode, "presentation_preferences", lambda value: value
    )

    title, body = update_copy.update_copy("available", version="2.0.0")

    assert title == "Update available · 有更新"
    assert "2.0.0" in body
    assert "撳「Stage available update」" in body


def test_update_copy_school_projection_is_english_and_serious(monkeypatch):
    prefs = _Prefs(language_mode="cantonese", funny_level_cantonese=5)
    school_prefs = _Prefs(language_mode="english", funny_level_english=1)
    monkeypatch.setattr(update_copy.preferences, "load", lambda: prefs)
    monkeypatch.setattr(
        update_copy.school_mode,
        "presentation_preferences",
        lambda _value: school_prefs,
    )

    title, body = update_copy.update_copy("failed", detail="offline")

    assert title == "Update check failed"
    assert "offline" in body
    assert "snacks" not in body
