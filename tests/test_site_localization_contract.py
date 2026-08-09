from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "site"


class VisibleCopyInventory(HTMLParser):
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
    _SOURCE_ONLY = {"code", "kbd", "script", "style"}

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, bool]] = []
        self.copy: list[str] = []
        self.attributes: list[str] = []

    @property
    def excluded(self) -> bool:
        return bool(self.stack and self.stack[-1][1])

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        excluded = (
            self.excluded
            or tag in self._SOURCE_ONLY
            or values.get("aria-hidden") == "true"
        )
        if not excluded:
            for attribute in ("aria-label", "placeholder", "title"):
                if values.get(attribute):
                    self.attributes.append(values[attribute])
            if tag == "meta" and values.get("name") == "description":
                self.attributes.append(values.get("content", ""))
        if tag not in self._VOID:
            self.stack.append((tag, excluded))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value and not self.excluded:
            self.copy.append(value)


def _resources() -> dict:
    return json.loads((SITE / "i18n.json").read_text(encoding="utf-8"))


def test_every_static_heading_control_message_and_accessible_name_is_inventoried():
    resources = _resources()
    assert resources["schemaVersion"] == 1
    assert resources["languages"] == ["en", "zh-Hant"]
    parser = VisibleCopyInventory()
    parser.feed((SITE / "index.html").read_text(encoding="utf-8"))
    messages = resources["messages"]
    allowlist = set(resources["staticAllowlist"])
    missing_copy = sorted(set(parser.copy) - set(messages) - allowlist)
    missing_attributes = sorted(set(parser.attributes) - set(messages) - allowlist)
    assert not missing_copy, f"visible English copy missing from i18n.json: {missing_copy}"
    assert not missing_attributes, (
        f"accessible English copy missing from i18n.json: {missing_attributes}"
    )


def test_cantonese_resources_are_complete_and_bilingual_nodes_are_semantic():
    resources = _resources()
    messages = resources["messages"]
    allowed_same = {
        "Amulet",
        "GitHub ↗",
        "Python API",
        "香港粵語",
        "獨立調校粵語語氣，唔會改變實際資料。",
        "儲存喺此瀏覽器；未設定時使用第 1 級。",
    }
    assert all(isinstance(value, str) and value.strip() for value in messages.values())
    assert not {
        key for key, value in messages.items() if key == value and key not in allowed_same
    }
    app = (SITE / "app.js").read_text(encoding="utf-8")
    assert "english.lang = 'en'" in app
    assert "cantonese.lang = 'zh-Hant'" in app
    assert "wrapper.append(english, cantonese)" in app
    assert "document.documentElement.dataset.language = mode" in app
    assert ':root[data-language="bilingual"] .localized-copy' in (
        SITE / "styles.css"
    ).read_text(encoding="utf-8")
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert html.count('id="article-title"') == 1
    assert 'id="article-content" lang="en"' not in html
    assert "reviewed English and Hong Kong Cantonese" in html
    assert "without claiming the source articles were translated" not in html


def test_every_article_route_has_complete_semantic_bilingual_resources():
    catalog = json.loads((SITE / "articles.json").read_text(encoding="utf-8"))
    assert catalog["schemaVersion"] == 2
    assert catalog["languages"] == ["en", "zh-Hant"]
    assert catalog["articleCount"] == 18
    for article in catalog["articles"]:
        with_title = article["title"]
        assert set(with_title) == {"en", "zh-Hant"}
        for field in ("title", "summary", "markdown"):
            assert set(article[field]) == {"en", "zh-Hant"}
            assert all(article[field][language].strip() for language in ("en", "zh-Hant"))
        assert article["markdown"]["en"].startswith(f"# {with_title['en']}")
        assert article["markdown"]["zh-Hant"].startswith(f"# {with_title['zh-Hant']}")
        assert article["translationPath"].endswith(f"/{article['slug']}.md")
        assert len(article["translationSha256"]) == 64

    app = (SITE / "app.js").read_text(encoding="utf-8")
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    assert "englishBody.lang = 'en'" in app
    assert "cantoneseBody.lang = 'zh-Hant'" in app
    assert "articleContent.replaceChildren(englishBody, cantoneseBody)" in app
    assert "button.append(createArticleLocalizedCopy(suggested.title))" in app
    assert "button.lang = 'en'" not in app
    assert ':root[data-language="english"] .article-language-copy[lang="zh-Hant"]' in css
    assert ':root[data-language="cantonese"] .article-language-copy[lang="en"]' in css


def test_dynamic_release_search_article_setting_and_palette_copy_is_inventoried():
    messages = _resources()["messages"]
    required = {
        "VERIFIED WINDOWS BUILD · {tag}",
        "Install the verified unsigned Squirrel package",
        "Download Setup.exe · {tag} · Windows x64 ↗",
        "Release code name: {codeName}",
        "Plain-text mode",
        "Invalid pattern: {message}",
        "Captures: {captures}",
        "Sample match at {index}: {match}",
        "Sample matched with zero-width result at {index}",
        "Regex evaluation timed out; the worker was stopped and no stale result was applied.",
        "Derived primary/surface: {primary}:1 · On-primary/primary: {onPrimary}:1",
        "FEATURE ARTICLE",
        "Read on this site →",
        "Reviewed English and Cantonese sources · {source} · SHA-256 {digest}…",
        "The bundled article catalog could not be loaded. The rest of the site remains available.",
        "Site configuration could not be loaded. The static shell remains available.",
        "Open article: {title}",
        "Open page: {title}",
        "Open feature: {title}",
        "Open setting: {title}",
    }
    assert required <= set(messages)
    app = (SITE / "app.js").read_text(encoding="utf-8")
    for key in required:
        assert repr(key) in app or f"'{key}'" in app


def test_each_funny_level_changes_complete_sentence_shell_copy_without_emoji():
    suffixes = _resources()["toneSuffixes"]
    assert set(suffixes) == {"en", "zh-Hant"}
    for language in ("en", "zh-Hant"):
        values = suffixes[language]
        assert len(values) == 5
        assert len(set(values)) == 5
        assert values[0] == ""
        assert all(not any(ord(char) > 0xFFFF for char in value) for value in values)
    app = (SITE / "app.js").read_text(encoding="utf-8")
    assert "toneMessage(messageFor(binding.key, 'en'" in app
    assert "toneMessage(messageFor(binding.key, 'zh-Hant'" in app
