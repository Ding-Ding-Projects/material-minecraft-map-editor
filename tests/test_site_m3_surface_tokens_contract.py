from pathlib import Path


def test_site_cards_and_search_fields_use_semantic_surface_tokens():
    css = Path("docs/site/styles.css").read_text(encoding="utf-8")
    assert ":root{--surface-card:#f7f5fc}" in css
    assert ".search-field,.feature-card,.community-card{background:var(--surface-card)}" in css
    assert ".setting-card{display:grid;gap:10px;background:var(--surface-card)" in css
    assert ".dark .top-app-bar,.dark .search-field,.dark .feature-card,.dark .community-card,.dark .setting-card{background:var(--surface-card)}" in css
