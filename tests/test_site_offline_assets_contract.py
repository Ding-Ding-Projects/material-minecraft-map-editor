from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "site"
sys.path.insert(0, str(ROOT / "scripts"))
from verify_site_offline_assets import (  # noqa: E402
    find_remote_assets,
    verify_offline_assets,
)


class SiteOfflineAssetContractTests(unittest.TestCase):
    def test_the_shipped_site_fetches_nothing_from_another_origin(self):
        self.assertEqual(find_remote_assets(SITE), [])
        verify_offline_assets(SITE)

    def test_a_cdn_font_stylesheet_is_refused(self):
        # This is the exact reference an imported design carries, and the exact
        # one that must never reach the bundle.
        with tempfile.TemporaryDirectory() as temp:
            site = Path(temp)
            (site / "index.html").write_text(
                '<link href="https://fonts.googleapis.com/css2?family=Outfit"'
                ' rel="stylesheet">',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as caught:
                verify_offline_assets(site)
            self.assertIn("fonts.googleapis.com", str(caught.exception))

    def test_protocol_relative_and_css_references_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            site = Path(temp)
            (site / "index.html").write_text(
                '<script src="//cdn.example.test/x.js"></script>', encoding="utf-8"
            )
            (site / "styles.css").write_text(
                "@font-face{src:url(https://fonts.gstatic.com/s/outfit.woff2)}",
                encoding="utf-8",
            )
            found = {reference for _path, _kind, reference in find_remote_assets(site)}
            self.assertIn("//cdn.example.test/x.js", found)
            self.assertIn("https://fonts.gstatic.com/s/outfit.woff2", found)

    def test_navigation_links_and_local_assets_stay_allowed(self):
        # A link the user clicks is not an asset the browser fetches, and the
        # site legitimately points at GitHub for source, issues, and releases.
        with tempfile.TemporaryDirectory() as temp:
            site = Path(temp)
            (site / "index.html").write_text(
                '<a href="https://github.com/example/repo">source</a>'
                '<link rel="stylesheet" href="styles.css">'
                '<img src="assets/shell.png" alt="">'
                '<img src="data:image/gif;base64,R0lGOD">'
                '<a href="#home">home</a>',
                encoding="utf-8",
            )
            self.assertEqual(find_remote_assets(site), [])


if __name__ == "__main__":
    unittest.main()
