"""Build the deterministic offline feature-documentation resource."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    # Import from the checkout without importing wx; docs_browser is explicitly
    # wx-independent and only uses the standard library plus RegexBuilder.
    sys.path.insert(0, str(root))
    from amulet_map_editor.api.docs_browser import discover_feature_articles

    articles = discover_feature_articles(root)
    output = root / "amulet_map_editor" / "api" / "docs_articles.json"
    payload = {
        "schema_version": 1,
        "articles": [
            {
                "slug": article.slug,
                "title": article.title,
                "markdown": article.markdown,
                "source_path": article.source_path,
                "sha256": article.sha256,
                "links": list(article.links),
            }
            for article in articles
        ],
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(articles)} articles to {output.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
