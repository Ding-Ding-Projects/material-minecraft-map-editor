"""Offline, wx-independent documentation browser data model.

The desktop UI can project this model into a native Material surface without
giving the renderer network access.  Articles are generated from the
repository's ``docs/features/*/README.md`` files by
``scripts/build_docs_bundle.py`` and shipped as a strict JSON resource.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import unquote, urlparse

from .regex_builder import MAX_PATTERN_LENGTH, RegexBuilder

_BUNDLE_NAME = "docs_articles.json"
_SCHEMA_VERSION = 1
_ARTICLE_RE = re.compile(r"^docs/features/(?P<slug>[^/]+)/README\.md$")
_LINK_RE = re.compile(r"!??\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")
_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


class DocumentationBundleError(ValueError):
    """Raised when an article bundle is malformed or incomplete."""


@dataclass(frozen=True)
class DocumentationArticle:
    slug: str
    title: str
    markdown: str
    source_path: str
    sha256: str
    links: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        """Searchable article text, retaining Markdown for faithful rendering."""

        return f"{self.title}\n{self.markdown}"


@dataclass(frozen=True)
class DocumentationSearchResult:
    article: DocumentationArticle
    scope: str = "articles"


class DocumentationIndex:
    """Deterministic article lookup, search, and internal-link resolution."""

    def __init__(self, articles: Iterable[DocumentationArticle]):
        ordered = tuple(sorted(articles, key=lambda article: article.slug))
        slugs = [article.slug for article in ordered]
        if len(slugs) != len(set(slugs)):
            raise DocumentationBundleError("duplicate documentation article slug")
        self._articles = ordered
        self._by_slug = {article.slug: article for article in ordered}

    @property
    def articles(self) -> tuple[DocumentationArticle, ...]:
        return self._articles

    def get(self, slug: str) -> DocumentationArticle:
        try:
            return self._by_slug[slug]
        except KeyError as exc:
            raise DocumentationBundleError(
                f"unknown documentation article: {slug}"
            ) from exc

    def resolve(self, current_slug: str, target: str) -> DocumentationArticle | None:
        """Resolve a local Markdown link without touching the network.

        External URLs, fragments, and paths outside ``docs/features`` are
        intentionally not article links and return ``None``.
        """

        if not target or target.startswith(("#", "mailto:", "data:")):
            return None
        parsed = urlparse(target)
        if parsed.scheme or parsed.netloc:
            return None
        path = unquote(parsed.path).replace("\\", "/")
        if path.startswith("/"):
            return None
        base = Path("docs/features") / current_slug / "README.md"
        candidate = posixpath.normpath((base.parent / path).as_posix())
        if candidate.endswith("/"):
            candidate += "README.md"
        if candidate.endswith("README.md"):
            match = _ARTICLE_RE.match(candidate)
            if match:
                return self._by_slug.get(match.group("slug"))
        return None

    def links_for(
        self, article: DocumentationArticle
    ) -> tuple[DocumentationArticle, ...]:
        return tuple(
            target
            for link in article.links
            if (target := self.resolve(article.slug, link)) is not None
        )

    def search(
        self,
        query: str,
        *,
        regex: bool = False,
        flags: int = 0,
    ) -> tuple[DocumentationSearchResult, ...]:
        if len(query) > MAX_PATTERN_LENGTH:
            raise DocumentationBundleError(
                f"Documentation query is limited to {MAX_PATTERN_LENGTH} characters"
            )
        builder = RegexBuilder(query, flags=flags, regex_enabled=regex)
        try:
            compiled = builder.compile()
        except (re.error, ValueError) as exc:
            raise DocumentationBundleError(str(exc)) from exc
        return tuple(
            DocumentationSearchResult(article)
            for article in self._articles
            if compiled.search(article.text)
        )


def _article_from_mapping(item: Mapping[str, object]) -> DocumentationArticle:
    required = {"slug", "title", "markdown", "source_path", "sha256", "links"}
    if set(item) != required:
        raise DocumentationBundleError(
            "documentation article has unknown or missing fields"
        )
    slug = item["slug"]
    title = item["title"]
    markdown = item["markdown"]
    source_path = item["source_path"]
    sha256 = item["sha256"]
    links = item["links"]
    if not all(
        isinstance(value, str) for value in (slug, title, markdown, source_path, sha256)
    ):
        raise DocumentationBundleError("documentation article fields must be strings")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", slug):
        raise DocumentationBundleError(f"invalid documentation slug: {slug!r}")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise DocumentationBundleError(f"invalid documentation digest for {slug!r}")
    if hashlib.sha256(markdown.encode("utf-8")).hexdigest() != sha256:
        raise DocumentationBundleError(f"documentation digest mismatch for {slug!r}")
    if not isinstance(links, list) or not all(isinstance(link, str) for link in links):
        raise DocumentationBundleError(f"invalid documentation links for {slug!r}")
    return DocumentationArticle(
        slug, title, markdown, source_path, sha256, tuple(links)
    )


def load_bundled_articles() -> DocumentationIndex:
    """Load and validate the bundled article resource without importing wx."""

    payload = json.loads(
        files("amulet_map_editor.api")
        .joinpath(_BUNDLE_NAME)
        .read_text(encoding="utf-8")
    )
    if (
        set(payload) != {"schema_version", "articles"}
        or payload["schema_version"] != _SCHEMA_VERSION
    ):
        raise DocumentationBundleError("unsupported documentation bundle schema")
    articles = payload["articles"]
    if not isinstance(articles, list):
        raise DocumentationBundleError("documentation bundle articles must be a list")
    index = DocumentationIndex(_article_from_mapping(item) for item in articles)
    return index


def discover_feature_articles(source_root: Path) -> tuple[DocumentationArticle, ...]:
    """Discover source articles in stable order for the bundle generator/guard."""

    root = Path(source_root).resolve()
    feature_root = root / "docs" / "features"
    if not feature_root.is_dir():
        raise DocumentationBundleError(
            f"feature documentation directory is missing: {feature_root}"
        )
    result: list[DocumentationArticle] = []
    for path in sorted(
        feature_root.glob("*/README.md"), key=lambda item: item.as_posix()
    ):
        slug = path.parent.name
        markdown = path.read_text(encoding="utf-8")
        title_match = _HEADING_RE.search(markdown)
        title = (
            title_match.group(1).strip()
            if title_match
            else slug.replace("-", " ").title()
        )
        links = tuple(match.group(1) for match in _LINK_RE.finditer(markdown))
        relative = path.relative_to(root).as_posix()
        result.append(
            DocumentationArticle(
                slug=slug,
                title=title,
                markdown=markdown,
                source_path=relative,
                sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
                links=links,
            )
        )
    if not result:
        raise DocumentationBundleError("no feature documentation articles discovered")
    return tuple(result)


def assert_bundle_complete(
    source_root: Path,
    *,
    bundled: DocumentationIndex | None = None,
) -> None:
    """Fail closed if an article is missing or stale in the shipped bundle."""

    source = discover_feature_articles(source_root)
    index = bundled or load_bundled_articles()
    expected = {(article.slug, article.sha256) for article in source}
    actual = {(article.slug, article.sha256) for article in index.articles}
    if expected != actual:
        missing = sorted(expected - actual)
        stale = sorted(actual - expected)
        raise DocumentationBundleError(
            f"documentation bundle is incomplete; missing/stale entries: missing={missing!r}, stale={stale!r}"
        )


__all__ = [
    "DocumentationArticle",
    "DocumentationBundleError",
    "DocumentationIndex",
    "DocumentationSearchResult",
    "assert_bundle_complete",
    "discover_feature_articles",
    "load_bundled_articles",
]
