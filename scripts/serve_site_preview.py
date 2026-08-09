"""Serve the dependency-free site with production-equivalent MIME and headers."""

from __future__ import annotations

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


class SitePreviewHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".json": "application/json",
        ".css": "text/css",
        ".html": "text/html",
    }

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'self'; connect-src 'self'; "
            "font-src 'self'; form-action 'self'; frame-ancestors 'none'; "
            "img-src 'self' data:; object-src 'none'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; worker-src 'self'",
        )
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if urlsplit(self.path).path == "/healthz":
            body = json.dumps(
                {"status": "ok", "service": "amulet-owner-site"},
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def send_head(self):  # type: ignore[no-untyped-def]
        path = urlsplit(self.path).path
        translated = Path(self.translate_path(path))
        if self.command == "GET" and not translated.exists() and "." not in Path(path).name:
            original = self.path
            self.path = "/index.html"
            try:
                return super().send_head()
            finally:
                self.path = original
        return super().send_head()

    def log_message(self, format: str, *args: object) -> None:
        print(f"site-preview: {self.address_string()} {format % args}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "site",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / "index.html").is_file():
        raise SystemExit(f"site root has no index.html: {root}")
    handler = lambda *values, **kwargs: SitePreviewHandler(  # noqa: E731
        *values, directory=str(root), **kwargs
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving {root} at http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
