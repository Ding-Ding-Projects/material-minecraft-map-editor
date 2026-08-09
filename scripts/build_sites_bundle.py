"""Build deterministic Cloudflare Worker/static output for Sites packaging."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from generate_site_articles import encoded_catalog
from verify_site_release_manifest import validate_bundle

WORKER = """const SECURITY_HEADERS = {
  'Content-Security-Policy': \"default-src 'self'; base-uri 'self'; connect-src 'self'; font-src 'self'; form-action 'self'; frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; worker-src 'self'\",
  'Permissions-Policy': 'camera=(), geolocation=(), microphone=(), payment=(), usb=()',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
};

function secured(response) {
  const headers = new Headers(response.headers);
  Object.entries(SECURITY_HEADERS).forEach(([name, value]) => headers.set(name, value));
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/healthz') {
      return secured(Response.json({ status: 'ok', service: 'amulet-owner-site' }));
    }
    if (!env?.ASSETS || typeof env.ASSETS.fetch !== 'function') {
      return secured(new Response('Static asset binding unavailable', { status: 503 }));
    }
    return secured(await env.ASSETS.fetch(request));
  },
};
"""
OUTPUT_MARKER = "Amulet Sites bundle v1\n"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--site",
        type=Path,
        help="validated static-site source (defaults to docs/site)",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    site = (args.site or root / "docs" / "site").resolve()
    output = (args.output or root / "dist").resolve()
    if output == root or output == site or site in output.parents:
        raise SystemExit("output must not replace the repository or site source")
    expected_articles = encoded_catalog(root)
    articles = site / "articles.json"
    if (
        not articles.is_file()
        or articles.read_text(encoding="utf-8") != expected_articles
    ):
        raise SystemExit(
            "docs/site/articles.json is stale; run scripts/generate_site_articles.py"
        )
    validate_bundle(site)

    marker = output / ".amulet-sites-bundle"
    if output.exists() and (
        not marker.is_file() or marker.read_text(encoding="utf-8") != OUTPUT_MARKER
    ):
        raise SystemExit(
            f"refusing to replace unowned output directory: {output}; choose an empty path"
        )
    if output.exists():
        shutil.rmtree(output)
    client = output / "client"
    server = output / "server"
    shutil.copytree(
        site,
        client,
        ignore=shutil.ignore_patterns(
            "README.md",
            "Dockerfile",
            "docker-compose.yml",
            "nginx.conf",
            ".dockerignore",
        ),
    )
    server.mkdir(parents=True)
    marker.write_text(OUTPUT_MARKER, encoding="utf-8", newline="\n")
    (server / "index.js").write_text(WORKER, encoding="utf-8", newline="\n")

    files = sorted(path for path in output.rglob("*") if path.is_file())
    manifest = {
        "schemaVersion": 1,
        "files": [
            {
                "path": path.relative_to(output).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in files
        ],
    }
    (output / "build-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Built Sites bundle with {len(files)} payload files at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
