from pathlib import Path

CSS = Path("docs/site/styles.css").read_text(encoding="utf-8")
THEME = Path("docs/site/theme.mjs").read_text(encoding="utf-8")


def test_site_surfaces_use_material_role_tokens_in_both_themes():
    for role in (
        "--surface-container-lowest",
        "--surface-container-low",
        "--surface-container",
        "--surface-container-high",
        "--surface-container-highest",
        "--on-surface",
        "--on-surface-variant",
        "--outline-variant",
    ):
        assert role in CSS
    assert "color-scheme: light" in CSS
    assert "color-scheme: dark" in CSS
    assert "background: var(--surface-container-low);" in CSS
    assert ".article-shell" in CSS
    assert ".palette-card" in CSS


def test_accent_is_a_seed_for_computed_roles_not_a_raw_primary_override():
    assert "export function deriveThemeRoles" in THEME
    assert "accessiblePrimary" in THEME
    assert "contrastRatio(candidate, surface) >= 4.5" in THEME
    assert "contrastRatio(foreground, candidate) >= 4.5" in THEME
