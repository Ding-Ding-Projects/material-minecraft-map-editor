"""Hand-written localization guard for visible native Preferences chrome."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCE = (ROOT / "amulet_map_editor/api/wx/ui/preferences.py").read_text(
    encoding="utf-8"
)

REQUIRED_CHROME_KEYS = (
    "window.title",
    "window.reset",
    "window.ok",
    "window.cancel",
    "tab.appearance",
    "choice.language.english",
    "choice.language.cantonese",
    "choice.language.bilingual",
    "choice.theme.light",
    "choice.theme.dark",
    "choice.theme.system",
    "choice.density.compact",
    "choice.density.comfortable",
    "choice.density.spacious",
    "appearance.font.search.label",
    "appearance.font.search.hint",
    "appearance.font.regex.help",
    "appearance.presets.label",
    "appearance.presets.name.hint",
    "appearance.presets.search.hint",
    "appearance.presets.regex.help",
    "appearance.presets.load",
    "appearance.presets.save",
    "appearance.presets.update",
    "appearance.presets.export",
    "appearance.presets.open",
    "appearance.presets.import",
    "appearance.presets.delete",
    "appearance.reset.theme",
    "appearance.reset.density",
    "appearance.reset.accent",
    "appearance.reset.font",
    "appearance.reset.scale",
    "appearance.reset.selected",
    "appearance.reset.all",
    "sample.font",
    "sample.preset",
    "sample.settings",
    "sample.command",
    "sample.changelog",
)


def _resource_keys(path: Path) -> set[str]:
    return {
        line.split("=", 1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    }


def test_every_preferences_chrome_key_has_english_and_cantonese_resources():
    required = {
        f"preferences.{language}.{key}"
        for language in ("en", "zh")
        for key in REQUIRED_CHROME_KEYS
    }
    for filename in ("en.lang", "zh_TW.lang"):
        keys = _resource_keys(ROOT / "amulet_map_editor/lang" / filename)
        assert required <= keys


def test_preferences_uses_resources_instead_of_english_only_proof_values():
    assert "self._material_title_text = _chrome_copy(" in SOURCE
    assert '"window.title", mode, compact=True' in SOURCE
    for key in REQUIRED_CHROME_KEYS:
        assert f'"{key}"' in SOURCE
    for hardcoded in (
        'title="Preferences"',
        'label="Reset to shipped values"',
        'label="Cancel"',
        'choices=["Light", "Dark", "System"]',
        'sample="Installed font family"',
        'sample="Appearance preset name"',
        'sample="Command, feature, or setting name"',
        'sample="Version, release note, or commit SHA"',
        'name="External editor executable"',
        'SetName("Installed font choices")',
        'SetName("Live typography preview")',
        'SetName("Appearance preset status")',
    ):
        assert hardcoded not in SOURCE

    assert "field.text.SetName(accessible_name)" in SOURCE
    assert "field.picker.SetName(accessible_name)" in SOURCE
    schedule_start = SOURCE.index("def _build_schedule_tab")
    schedule_end = SOURCE.index("def _mark_schedule_dirty", schedule_start)
    assert "mode = self._prefs.language_mode" in SOURCE[schedule_start:schedule_end]
