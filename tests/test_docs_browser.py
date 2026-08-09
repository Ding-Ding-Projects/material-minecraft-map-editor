"""Offline documentation bundle and search contract tests."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from amulet_map_editor.api.docs_browser import (
    DocumentationBundleError,
    assert_bundle_complete,
    load_bundled_articles,
)

ROOT = Path(__file__).resolve().parents[1]


def test_bundled_articles_are_complete_and_deterministic():
    index = load_bundled_articles()
    assert len(index.articles) >= 1
    assert [article.slug for article in index.articles] == sorted(
        article.slug for article in index.articles
    )
    assert_bundle_complete(ROOT, bundled=index)


def test_plain_text_search_is_literal_and_regex_is_explicit():
    index = load_bundled_articles()
    assert index.search("[not-a-real-article-literal") == ()
    result = index.search("offline|regex", regex=True, flags=re.IGNORECASE)
    assert result
    assert all(item.scope == "articles" for item in result)
    with pytest.raises(DocumentationBundleError):
        index.search("(" * 4097)


def test_internal_article_links_resolve_without_network():
    index = load_bundled_articles()
    tab_groups = index.get("tab-groups")
    linked_slugs = {article.slug for article in index.links_for(tab_groups)}
    assert {"appearance-presets", "local-history", "scheduled-settings"} <= linked_slugs
    assert index.resolve("tab-groups", "https://example.test/docs") is None
    assert index.resolve("tab-groups", "#behaviour") is None


def test_bundle_load_does_not_import_wx():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['wx'] = None; "
            "from amulet_map_editor.api.docs_browser import load_bundled_articles; "
            "assert load_bundled_articles().articles",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.stderr == ""
