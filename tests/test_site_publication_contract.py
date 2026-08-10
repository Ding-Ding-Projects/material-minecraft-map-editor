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
from verify_site_release_manifest import ASSET_KEYS, validate_bundle  # noqa: E402

#: Hand-written on purpose. A rule that only checks the settings which happen to
#: be present passes on a page that renders none of them, so the list is what
#: makes a missing setting fail rather than quietly disappear. Add to it when a
#: setting is added; deleting an entry to make the suite pass is the one edit
#: that defeats the point.
REQUIRED_SETTINGS = (
    "language",
    "funnyEn",
    "funnyYue",
    "theme",
    "density",
    "accent",
    "font",
    "scale",
    "emoji",
    "narrator",
    "reducedMotion",
    "brand",
)


class SitePublicationContractTests(unittest.TestCase):
    def _assert_every_required_setting_is_rendered(self):
        """Every setting exists, and every card explains itself.

        This replaced a bare ``count(...) == 9`` over the HTML. That number was
        satisfied by any page rendering nine cards, said nothing about *which*
        nine, and became meaningless the moment the grid started rendering from
        data. The settings now live in a module, so the contract is checked
        where it is actually expressed.
        """
        source = (SITE / "settings-panel.js").read_text(encoding="utf-8")
        for key in REQUIRED_SETTINGS:
            with self.subTest(setting=key):
                self.assertIn(
                    f'key: "{key}"',
                    source,
                    f"the {key!r} setting is no longer registered",
                )
        # A card without an explanation, or without an honest statement of where
        # its value came from, is exactly what the old count was meant to stop.
        self.assertIn("setting-help", source)
        self.assertIn("setting-provenance", source)
        self.assertIn(
            "provenance(",
            source,
            "provenance lines must come from AmuletSite.settings.provenance so "
            "they cannot drift from the value they describe",
        )

    def test_site_manifest_is_unverified_or_backed_by_a_real_commit(self):
        # The point of this guard is that the page never offers a download the
        # repository cannot prove. It used to say so by refusing any verified
        # manifest at all, which stopped being true once a release shipped; the
        # protection now travels with the claim instead of forbidding it.
        validate_bundle(SITE)
        manifest = json.loads(
            (SITE / "release-manifest.json").read_text(encoding="utf-8")
        )
        if not manifest["verified"]:
            # Nothing proven yet, so nothing may be offered. validate_bundle has
            # already refused a releaseTag or commit on an unverified manifest.
            self.assertEqual(manifest["assets"], {})
            return

        release_tag = manifest["releaseTag"]
        self.assertEqual(set(manifest["assets"]), set(ASSET_KEYS))
        for key, asset in manifest["assets"].items():
            with self.subTest(asset=key):
                self.assertRegex(asset["sha256"], r"\A[0-9a-f]{64}\Z")
                self.assertTrue(asset["url"].startswith("https://"))
                self.assertIn(f"/download/{release_tag}/", asset["url"])
                self.assertTrue(asset["url"].endswith("/" + asset["name"]))

        commit = manifest["commit"]
        self.assertRegex(commit, r"\A[0-9a-f]{40}\Z")
        # A well-formed but invented SHA is the failure the old assertion could
        # never catch, because it rejected every verified manifest on sight.
        # Unittests checks out with fetch-depth 0, so the object is really here.
        resolved = subprocess.run(
            ["git", "cat-file", "-t", commit],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            resolved.returncode,
            0,
            f"manifest commit {commit} is not an object in this repository",
        )
        self.assertEqual(resolved.stdout.strip(), "commit")

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
        self._assert_every_required_setting_is_rendered()
        self._assert_the_accent_picker_is_still_continuous()
        # Windows is the delivery scope, and the page must not quietly regrow
        # the platforms this project deliberately stopped claiming.
        self.assertIn("Unsigned Squirrel.Windows installer", html)
        self.assertIn("verified Windows release", html)
        self.assertNotIn("macOS, Debian, Flatpak, and Docker workflows", html)

    def _assert_the_accent_picker_is_still_continuous(self):
        """The colour control must stay a picker, not a list of swatches.

        These used to be element ids in the static HTML. The settings grid now
        renders from data, so asserting the ids against index.html checks a file
        that no longer contains them -- it would fail on a perfectly good page
        and pass on one that shipped a fixed palette. The contract itself has
        not changed: a continuous hue control, three synchronised text
        representations that round-trip, and a live contrast readout.
        """
        settings_source = (SITE / "settings-panel.js").read_text(encoding="utf-8")
        for marker in ("HEX", "RGB", "HSL", "hue", "contrast"):
            with self.subTest(control=marker):
                self.assertIn(marker, settings_source)

        # The colour maths has to live somewhere in the bundle; which file owns
        # it is an implementation detail, its absence is not. Round-tripping in
        # both directions is the part that makes the three text fields agree.
        bundle = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(SITE.glob("*.js"))
        )
        for function in (
            "contrastRatio",
            "rgbToHsl",
            "hslToRgb",
            "hexToRgb",
            "rgbToHex",
        ):
            with self.subTest(function=function):
                self.assertIn(function, bundle)


if __name__ == "__main__":
    unittest.main()
