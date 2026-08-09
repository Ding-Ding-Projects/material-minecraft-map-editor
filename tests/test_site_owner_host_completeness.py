from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "site"
sys.path.insert(0, str(ROOT / "scripts"))
from generate_site_articles import (  # noqa: E402
    RELATED_ARTICLES,
    TRANSLATION_ROOT,
    _technical_contract,
)


class ContractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.references: list[tuple[str, str]] = []
        self.hrefs: list[str] = []
        self.tabs: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if values.get("id"):
            self.ids.append(values["id"])
        for attribute in ("aria-controls", "aria-labelledby"):
            if values.get(attribute):
                for target in values[attribute].split():
                    self.references.append((attribute, target))
        if values.get("href"):
            self.hrefs.append(values["href"])
        if values.get("role") == "tab":
            self.tabs.append(values)


def test_generated_catalog_covers_every_feature_article_with_valid_suggestions():
    catalog = json.loads((SITE / "articles.json").read_text(encoding="utf-8"))
    source_paths = sorted((ROOT / "docs" / "features").glob("*/README.md"))
    translation_paths = sorted((ROOT / TRANSLATION_ROOT).glob("*.md"))
    assert catalog["schemaVersion"] == 2
    assert catalog["languages"] == ["en", "zh-Hant"]
    assert catalog["articleCount"] == len(source_paths) == 18
    assert len(translation_paths) == 18
    records = {record["slug"]: record for record in catalog["articles"]}
    assert set(records) == {path.parent.name for path in source_paths}
    assert set(RELATED_ARTICLES) == set(records)
    for path in source_paths:
        record = records[path.parent.name]
        source = path.read_text(encoding="utf-8")
        translation_path = ROOT / record["translationPath"]
        translation = translation_path.read_text(encoding="utf-8")
        assert record["sourcePath"] == path.relative_to(ROOT).as_posix()
        assert record["sha256"] == hashlib.sha256(source.encode("utf-8")).hexdigest()
        assert record["translationPath"] == (
            TRANSLATION_ROOT / f"{record['slug']}.md"
        ).as_posix()
        assert record["translationSha256"] == hashlib.sha256(
            translation.encode("utf-8")
        ).hexdigest()
        assert set(record["title"]) == {"en", "zh-Hant"}
        assert set(record["summary"]) == {"en", "zh-Hant"}
        assert set(record["markdown"]) == {"en", "zh-Hant"}
        assert all(
            record[field][language].strip()
            for field in ("title", "summary", "markdown")
            for language in ("en", "zh-Hant")
        )
        assert record["title"]["en"] != record["title"]["zh-Hant"]
        assert record["markdown"]["en"] != record["markdown"]["zh-Hant"]
        source_headings = re.findall(r"^#{1,2}\s+(.+)$", source, re.MULTILINE)
        translated_headings = re.findall(
            r"^#{1,2}\s+(.+)$", translation, re.MULTILINE
        )
        assert len(source_headings) == len(translated_headings)
        assert all(
            source_heading != translated_heading
            for source_heading, translated_heading in zip(
                source_headings, translated_headings, strict=True
            )
        )
        assert len(re.findall(r"^[-*]\s+", source, re.MULTILINE)) == len(
            re.findall(r"^[-*]\s+", translation, re.MULTILINE)
        )
        assert len(translation) >= len(source) * 0.35
        assert re.search(r"[\u3400-\u9fff]", translation)
        assert _technical_contract(source) == _technical_contract(translation)
        assert 2 <= len(record["suggested"]) <= 3
        assert len(set(record["suggested"])) == len(record["suggested"])
        assert all(
            slug in records and slug != record["slug"] for slug in record["suggested"]
        )


def test_generated_catalog_is_current():
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_site_articles.py"),
            "--check",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_html_relationships_and_local_routes_are_complete():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    parser = ContractParser()
    parser.feed(html)
    assert len(parser.ids) == len(set(parser.ids)), "duplicate HTML ids"
    ids = set(parser.ids)
    assert parser.tabs
    assert all(tab.get("aria-controls") in ids for tab in parser.tabs)
    assert all(target in ids for _attribute, target in parser.references)
    app = (SITE / "app.js").read_text(encoding="utf-8")
    assert parser.ids.count("article-title") == 1
    assert "query('#article-title').replaceChildren(createArticleLocalizedCopy(article.title))" in app
    assert sum(tab.get("aria-selected") == "true" for tab in parser.tabs) == 1
    assert sum(tab.get("tabindex") == "0" for tab in parser.tabs) == 1
    assert not any(
        "/blob/" in href and "/docs/features/" in href for href in parser.hrefs
    )
    assert not any(
        "/tree/main/" in href or "/blob/main/" in href for href in parser.hrefs
    )
    assert (
        "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor#development-and-contribution"
        in parser.hrefs
    )
    assert 'type="module" src="app.js"' in html
    assert 'role="combobox"' in html
    assert 'aria-controls="palette-results"' in html
    assert "if (!control.dataset.tabLink) return;" in app
    assert "settings.accentHex.value = settings.accent.value" in app
    assert "settings.accentHex.value = savedAccent" in app


def test_computed_theme_roles_meet_normal_text_contrast_for_varied_seeds():
    node = shutil.which("node")
    assert node, "Node is required for the committed site contrast contract"
    module_url = (SITE / "theme.mjs").as_uri()
    program = f"""
import {{ deriveThemeRoles, contrastRatio }} from {json.dumps(module_url)};
const seeds = ['#4d5f92','#ffff00','#00ff00','#0000ff','#ff00ff','#808080','#000000','#ffffff'];
for (const theme of ['light','dark']) {{
  for (const seed of seeds) {{
    const roles = deriveThemeRoles(seed, theme);
    const pairs = [
      ['primary/surface', roles.primary, roles.surface],
      ['on-primary/primary', roles.onPrimary, roles.primary],
      ['on-primary-container/primary-container', roles.onPrimaryContainer, roles.primaryContainer],
      ['on-surface-variant/surface', roles.onSurfaceVariant, roles.surface],
    ];
    for (const [name, foreground, background] of pairs) {{
      const ratio = contrastRatio(foreground, background);
      if (ratio < 4.5) throw new Error(`${{theme}} ${{seed}} ${{name}} = ${{ratio}}`);
    }}
  }}
}}
"""
    subprocess.run(
        [node, "--input-type=module", "--eval", program],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_sites_output_is_deterministic_and_package_ready():
    hosting = json.loads(
        (ROOT / ".openai" / "hosting.json").read_text(encoding="utf-8")
    )
    assert hosting == {"d1": None, "r2": None}
    with tempfile.TemporaryDirectory() as temp:
        first = Path(temp) / "first"
        second = Path(temp) / "second"
        command = [sys.executable, str(ROOT / "scripts" / "build_sites_bundle.py")]
        subprocess.run(command + ["--output", str(first)], cwd=ROOT, check=True)
        subprocess.run(command + ["--output", str(second)], cwd=ROOT, check=True)
        assert (first / "server" / "index.js").is_file()
        assert (first / "client" / "articles.json").is_file()
        assert (first / ".amulet-sites-bundle").read_text(encoding="utf-8") == (
            "Amulet Sites bundle v1\n"
        )
        assert (first / "build-manifest.json").read_bytes() == (
            second / "build-manifest.json"
        ).read_bytes()
        worker = (first / "server" / "index.js").read_text(encoding="utf-8")
        assert "env?.ASSETS" in worker
        assert "'/healthz'" in worker


def test_sites_builder_refuses_to_delete_an_unowned_output_directory():
    with tempfile.TemporaryDirectory() as temp:
        output = Path(temp) / "existing"
        output.mkdir()
        sentinel = output / "keep.txt"
        sentinel.write_text("user data", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "build_sites_bundle.py"),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "refusing to replace unowned output directory" in result.stderr
        assert sentinel.read_text(encoding="utf-8") == "user data"


def test_static_builder_refuses_to_delete_an_unowned_output_directory():
    with tempfile.TemporaryDirectory() as temp:
        output = Path(temp) / "existing"
        output.mkdir()
        sentinel = output / "keep.txt"
        sentinel.write_text("user data", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "prepare_site_bundle.py"),
                "--source",
                str(SITE),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "refusing to replace unowned output directory" in result.stderr
        assert sentinel.read_text(encoding="utf-8") == "user data"


def test_owner_host_container_is_bounded_and_health_checked():
    dockerfile = (SITE / "Dockerfile").read_text(encoding="utf-8")
    compose = (SITE / "docker-compose.yml").read_text(encoding="utf-8")
    nginx = (SITE / "nginx.conf").read_text(encoding="utf-8")
    assert (
        "nginx:1.27.4-alpine@sha256:4ff102c5d78d254a6f0da062b3cf39eaf07f01eec0927fd21e219d0af8bc0591"
        in dockerfile
    )
    assert "USER nginx" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "127.0.0.1:8080/healthz" in dockerfile
    assert "${AMULET_SITE_BIND:-127.0.0.1}" in compose
    assert "${AMULET_SITE_PORT:-8095}" in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose and "- ALL" in compose
    assert "location = /healthz" in nginx
    assert "Content-Security-Policy" in nginx
