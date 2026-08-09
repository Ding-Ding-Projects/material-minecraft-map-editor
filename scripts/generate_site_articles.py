"""Generate the owner-hosted site's complete feature-article catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
SUGGESTED_HEADING = re.compile(r"^##\s+Suggested articles\s*$", re.IGNORECASE)
RELATED_ARTICLES = {
    "appearance": ("appearance-presets", "scheduled-settings", "material-shell"),
    "appearance-presets": ("appearance", "scheduled-settings", "local-history"),
    "build-scripts": ("release-delivery", "updater", "material-shell"),
    "changelog": ("offline-documentation", "release-delivery", "command-palette"),
    "command-palette": ("tab-groups", "offline-documentation", "appearance"),
    "dim-sum-surprise": ("release-code-name", "school-mode", "tts-narrator"),
    "external-editor": ("local-history", "offline-documentation", "material-shell"),
    "local-history": ("scheduled-settings", "appearance-presets", "external-editor"),
    "material-shell": ("tab-groups", "appearance", "command-palette"),
    "notification-centre": ("tts-narrator", "local-history", "command-palette"),
    "offline-documentation": ("changelog", "command-palette", "external-editor"),
    "release-code-name": ("dim-sum-surprise", "release-delivery", "changelog"),
    "release-delivery": ("build-scripts", "updater", "release-code-name"),
    "scheduled-settings": ("appearance", "school-mode", "local-history"),
    "school-mode": ("scheduled-settings", "dim-sum-surprise", "tts-narrator"),
    "tab-groups": ("command-palette", "material-shell", "appearance"),
    "tts-narrator": ("notification-centre", "school-mode", "dim-sum-surprise"),
    "updater": ("release-delivery", "build-scripts", "changelog"),
}


@dataclass(frozen=True)
class SourceArticle:
    slug: str
    title: str
    summary: str
    markdown: str
    source_path: str
    sha256: str
    linked_slugs: tuple[str, ...]


def _summary(markdown: str) -> str:
    paragraphs: list[str] = []
    current: list[str] = []
    in_fence = False
    for raw in markdown.splitlines()[1:]:
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or line.startswith("#") or line.startswith(("-", "*", ">")):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            if paragraphs:
                break
            continue
        current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    value = re.sub(r"[`*_\[\]]", "", paragraphs[0] if paragraphs else "")
    value = re.sub(r"\((?:\.\.?/)?[^)]+\)", "", value)
    return value[:237].rstrip() + ("..." if len(value) > 237 else "")


def _strip_suggested_section(markdown: str) -> str:
    lines = markdown.rstrip().splitlines()
    for index, line in enumerate(lines):
        if SUGGESTED_HEADING.fullmatch(line.strip()):
            return "\n".join(lines[:index]).rstrip() + "\n"
    return markdown.rstrip() + "\n"


def _linked_slugs(path: Path, markdown: str, known_slugs: set[str]) -> tuple[str, ...]:
    linked: list[str] = []
    for href in MARKDOWN_LINK.findall(markdown):
        target = href.split("#", 1)[0]
        if not target or "://" in target:
            continue
        resolved = (path.parent / target).resolve()
        candidate = resolved.parent.name if resolved.name.lower() == "readme.md" else ""
        if (
            candidate in known_slugs
            and candidate != path.parent.name
            and candidate not in linked
        ):
            linked.append(candidate)
    return tuple(linked)


def discover_articles(root: Path) -> list[SourceArticle]:
    feature_root = root / "docs" / "features"
    paths = sorted(
        feature_root.glob("*/README.md"), key=lambda value: value.parent.name
    )
    known_slugs = {path.parent.name for path in paths}
    articles: list[SourceArticle] = []
    for path in paths:
        markdown = path.read_text(encoding="utf-8")
        match = HEADING.search(markdown)
        if not match:
            raise ValueError(f"{path.relative_to(root)} has no level-one title")
        articles.append(
            SourceArticle(
                slug=path.parent.name,
                title=match.group(1).strip(),
                summary=_summary(markdown),
                markdown=_strip_suggested_section(markdown),
                source_path=path.relative_to(root).as_posix(),
                sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
                linked_slugs=_linked_slugs(path, markdown, known_slugs),
            )
        )
    return articles


def build_catalog(root: Path) -> dict:
    articles = discover_articles(root)
    slugs = {article.slug for article in articles}
    if set(RELATED_ARTICLES) != slugs:
        missing = sorted(slugs - set(RELATED_ARTICLES))
        stale = sorted(set(RELATED_ARTICLES) - slugs)
        raise ValueError(
            f"review the suggested-article map (missing={missing}, stale={stale})"
        )
    payload: list[dict] = []
    for article in articles:
        suggested = list(article.linked_slugs)
        for candidate in RELATED_ARTICLES[article.slug]:
            if len(suggested) >= 3:
                break
            if candidate != article.slug and candidate not in suggested:
                suggested.append(candidate)
        payload.append(
            {
                "slug": article.slug,
                "title": article.title,
                "summary": article.summary,
                "markdown": article.markdown,
                "sourcePath": article.source_path,
                "sha256": article.sha256,
                "suggested": suggested[:3],
            }
        )
    return {
        "schemaVersion": 1,
        "sourceRoot": "docs/features",
        "articleCount": len(payload),
        "articles": payload,
    }


def encoded_catalog(root: Path) -> str:
    return json.dumps(build_catalog(root), ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    output = (args.output or root / "docs" / "site" / "articles.json").resolve()
    expected = encoded_catalog(root)
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != expected:
            raise SystemExit(
                f"{output} is stale; run scripts/generate_site_articles.py"
            )
        print(f"Verified {build_catalog(root)['articleCount']} generated site articles")
        return 0
    output.write_text(expected, encoding="utf-8")
    print(f"Wrote {build_catalog(root)['articleCount']} site articles to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
