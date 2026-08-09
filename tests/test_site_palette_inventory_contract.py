from pathlib import Path

APP = Path("docs/site/app.js").read_text(encoding="utf-8")


def test_site_palette_indexes_every_feature_and_setting_card():
    assert "queryAll('#feature-grid .feature-card')" in APP
    assert "queryAll('#settings-grid .setting-card')" in APP
    assert "addArticlesToPalette" in APP
    assert "scrollIntoView({ block: 'center' })" in APP
    assert "target?.focus?.({ preventScroll: true })" in APP
