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
from verify_site_release_manifest import (  # noqa: E402
    validate_bundle,
    validate_github_release_api,
)


class SitePublicationContractTests(unittest.TestCase):
    def test_site_config_and_verified_manifest_are_truthful(self):
        validate_bundle(SITE)
        manifest = json.loads(
            (SITE / "release-manifest.json").read_text(encoding="utf-8")
        )
        self.assertTrue(manifest["verified"])
        self.assertEqual(manifest["releaseTag"], "0.10.0-dev.426")
        self.assertEqual(manifest["commit"], "d47031726b5b1de67ebb9987f211c7d28e6f94c8")
        self.assertEqual(manifest["workflowTiming"]["duration"], "00:04:01")
        self.assertEqual(manifest["codeName"]["en"], "Black Sesame Bao")
        self.assertFalse(manifest["delta"]["emitted"])
        self.assertEqual(
            set(manifest["assets"]), {"Setup.exe", "RELEASES", "full.nupkg"}
        )
        self.assertEqual(manifest["assets"]["Setup.exe"]["bytes"], 87019520)
        self.assertEqual(manifest["assets"]["RELEASES"]["bytes"], 84)
        self.assertEqual(manifest["assets"]["full.nupkg"]["bytes"], 86880504)

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
            original_url = manifest["assets"]["Setup.exe"]["url"]
            invalid_urls = (
                original_url.replace("github.com", "downloads.example.test"),
                original_url.replace(
                    "Ding-Ding-Projects/material-minecraft-map-editor",
                    "Ding-Ding-Projects/wrong-repository",
                ),
                original_url + "?candidate=true",
                original_url.replace("https://", "https://user:secret@"),
            )
            for invalid_url in invalid_urls:
                manifest["assets"]["Setup.exe"]["url"] = invalid_url
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.subTest(invalid_url=invalid_url), self.assertRaises(ValueError):
                    validate_bundle(copy)
            manifest["assets"]["Setup.exe"]["url"] = original_url
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            validate_bundle(copy)

    def test_github_api_sizes_digests_and_urls_must_match(self):
        manifest = validate_bundle(SITE)
        release = {
            "draft": False,
            "prerelease": False,
            "tag_name": manifest["releaseTag"],
            "target_commitish": manifest["commit"],
            "html_url": manifest["releaseUrl"],
            "published_at": manifest["publishedAt"],
            "assets": [
                {
                    "name": asset["name"],
                    "size": asset["bytes"],
                    "digest": f"sha256:{asset['sha256']}",
                    "browser_download_url": asset["url"],
                }
                for asset in manifest["assets"].values()
            ],
        }
        validate_github_release_api(manifest, release)
        release["assets"][0]["size"] += 1
        with self.assertRaisesRegex(ValueError, "size differs"):
            validate_github_release_api(manifest, release)
        release["assets"][0]["size"] -= 1
        release["assets"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "digest differs"):
            validate_github_release_api(manifest, release)

    def test_bundle_paths_and_workflow_timing_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            copy = Path(temp) / "site"
            shutil.copytree(SITE, copy)
            config_path = copy / "site-config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["articles"] = "../features.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_bundle(copy)

            shutil.rmtree(copy)
            shutil.copytree(SITE, copy)
            manifest_path = copy / "release-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["workflowTiming"]["duration"] = "00:04:05"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_bundle(copy)

    def test_accessibility_and_each_search_has_a_regex_builder(self):
        html = (SITE / "index.html").read_text(encoding="utf-8")
        app = (SITE / "app.js").read_text(encoding="utf-8")
        theme = (SITE / "theme.mjs").read_text(encoding="utf-8")
        self.assertIn('<html lang="en">', html)
        self.assertIn('role="tablist"', html)
        self.assertIn('aria-orientation="horizontal"', html)
        self.assertIn('aria-label="Primary navigation"', html)
        self.assertIn('aria-label="Search features"', html)
        self.assertIn('aria-label="Search settings"', html)
        self.assertIn(
            'aria-label="Search commands, features, documentation, and settings"',
            html,
        )
        self.assertIn('aria-label="Search documentation"', html)
        self.assertGreaterEqual(html.count('class="regex-builder"'), 4)
        self.assertIn('id="settings-grid"', html)
        self.assertIn('id="release-download"', html)
        self.assertNotIn("releases/download/0.10.55/Setup.exe", html)
        self.assertIn("function verifiedManifest(manifest)", app)
        self.assertIn("function safePhotoUrl(value)", app)
        self.assertIn("EXPECTED_PHOTO_REPOSITORY", app)
        self.assertIn("['Setup.exe', 'RELEASES', 'full.nupkg']", app)
        self.assertIn('id="release-code-name-link"', html)
        self.assertEqual(html.count('class="setting-provenance"'), 9)
        self.assertEqual(html.count('class="setting-help"'), 9)
        self.assertIn('id="site-accent-hex"', html)
        self.assertIn('id="site-accent-rgb"', html)
        self.assertIn('id="site-accent-hsl"', html)
        self.assertIn('id="site-accent-hue"', html)
        self.assertIn('id="accent-contrast"', html)
        self.assertIn('id="site-font"', html)
        self.assertIn('id="site-scale"', html)
        self.assertIn("applyThemeRoles", app)
        self.assertIn("function rgbHsl", theme)
        self.assertIn("function hslRgb", theme)
        self.assertIn('id="reset-site-settings"', html)
        self.assertIn("Windows one-click builds", html)
        self.assertNotIn("macOS, Debian, Flatpak, and Docker workflows", html)
        self.assertIn("verified Windows release", html)


if __name__ == "__main__":
    unittest.main()
