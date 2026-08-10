from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "site"
sys.path.insert(0, str(ROOT / "scripts"))
from verify_site_release_manifest import validate_bundle  # noqa: E402


class SitePublicationContractTests(unittest.TestCase):
    def test_site_config_and_unverified_manifest_are_truthful(self):
        validate_bundle(SITE)
        manifest = json.loads(
            (SITE / "release-manifest.json").read_text(encoding="utf-8")
        )
        self.assertFalse(manifest["verified"])
        self.assertEqual(manifest["assets"], {})

    def test_site_bundle_can_use_an_explicit_https_base_url(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "site"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "prepare_site_bundle.py"),
                    "--source",
                    str(SITE),
                    "--output",
                    str(output),
                    "--base-url",
                    "https://docs.example.test/amulet/",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            config = json.loads(
                (output / "site-config.json").read_text(encoding="utf-8")
            )
            self.assertEqual(config["baseUrl"], "https://docs.example.test/amulet/")
            validate_bundle(output)

    def test_verified_manifest_requires_immutable_release_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            copy = Path(temp) / "site"
            shutil.copytree(SITE, copy)
            manifest_path = copy / "release-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.update(
                {"verified": True, "releaseTag": "0.10.99", "commit": "a" * 40}
            )
            manifest["assets"] = {
                name: {
                    "name": (
                        "Amulet-0.10.99-full.nupkg" if name == "full.nupkg" else name
                    ),
                    "url": (
                        f"https://downloads.example.test/releases/download/0.10.99/Amulet-0.10.99-full.nupkg"
                        if name == "full.nupkg"
                        else f"https://downloads.example.test/releases/download/0.10.99/{name}"
                    ),
                    "sha256": "b" * 64,
                }
                for name in ("Setup.exe", "RELEASES", "full.nupkg")
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            validate_bundle(copy)
            manifest["assets"]["Setup.exe"]["url"] += "?candidate=true"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_bundle(copy)

    def test_accessibility_and_each_search_has_a_regex_builder(self):
        html = (SITE / "index.html").read_text(encoding="utf-8")
        app = (SITE / "app.js").read_text(encoding="utf-8")
        self.assertIn('<html lang="en">', html)
        self.assertIn('role="tablist"', html)
        self.assertIn('aria-orientation="horizontal"', html)
        self.assertIn('aria-label="Primary navigation"', html)
        self.assertIn('aria-label="Search features"', html)
        self.assertIn('aria-label="Search settings"', html)
        self.assertIn('aria-label="Search commands, features, and settings"', html)
        self.assertGreaterEqual(html.count('class="regex-builder"'), 3)
        self.assertIn('id="settings-grid"', html)
        self.assertIn('id="release-download"', html)
        self.assertNotIn("releases/download/0.10.55/Setup.exe", html)
        self.assertIn("function verifiedManifest(manifest)", app)
        self.assertIn("['Setup.exe','RELEASES','full.nupkg']", app)
        self.assertEqual(html.count('class="setting-provenance"'), 9)
        self.assertEqual(html.count('class="setting-help"'), 9)
        self.assertIn('id="site-accent-hex"', html)
        self.assertIn('id="site-accent-rgb"', html)
        self.assertIn('id="site-accent-hsl"', html)
        self.assertIn('id="site-accent-hue"', html)
        self.assertIn('id="accent-contrast"', html)
        self.assertIn('id="site-font"', html)
        self.assertIn('id="site-scale"', html)
        self.assertIn("function contrastRatio", app)
        self.assertIn("function rgbHsl", app)
        self.assertIn("function hslRgb", app)
        self.assertIn('id="reset-site-settings"', html)
        self.assertIn("Windows one-click builds", html)
        self.assertNotIn("macOS, Debian, Flatpak, and Docker workflows", html)
        self.assertIn("verified Windows release", html)


if __name__ == "__main__":
    unittest.main()
