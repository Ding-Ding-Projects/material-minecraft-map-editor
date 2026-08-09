from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from create_site_release_handoff import create_handoff  # noqa: E402
from stage_site_release_handoff import (  # noqa: E402
    OutOfOrderHandoff,
    stage_handoff,
)

REPOSITORY = "Ding-Ding-Projects/material-minecraft-map-editor"
HEAD_SHA = "d47031726b5b1de67ebb9987f211c7d28e6f94c8"
TAG = "0.10.0-dev.426"
RUN_ID = 123456789
RUN_NUMBER = 426


class SiteReleaseHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.assets = self.root / "assets"
        self.assets.mkdir()
        payloads = {
            "Setup.exe": b"unsigned setup fixture",
            "RELEASES": b"release index fixture",
            "Amulet-0.10.0-dev426-full.nupkg": b"full package fixture",
        }
        for name, payload in payloads.items():
            (self.assets / name).write_bytes(payload)
        self.release = {
            "id": 987654321,
            "draft": False,
            "prerelease": False,
            "tag_name": TAG,
            "target_commitish": HEAD_SHA,
            "html_url": (
                "https://github.com/Ding-Ding-Projects/"
                f"material-minecraft-map-editor/releases/tag/{TAG}"
            ),
            "published_at": "2026-08-09T16:42:50Z",
            "assets": [],
        }
        for path in sorted(self.assets.iterdir()):
            self.release["assets"].append(
                {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "digest": f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
                    "browser_download_url": (
                        "https://github.com/Ding-Ding-Projects/"
                        "material-minecraft-map-editor/releases/download/"
                        f"{TAG}/{path.name}"
                    ),
                }
            )
        self.handoff = self._create()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _create(self, *, release: dict | None = None, repository: str = REPOSITORY) -> dict:
        return create_handoff(
            release=self.release if release is None else release,
            assets_dir=self.assets,
            repository=repository,
            workflow_run_id=RUN_ID,
            workflow_run_number=RUN_NUMBER,
            head_sha=HEAD_SHA,
            tag=TAG,
            started="2026-08-09T16:38:49Z",
            completed="2026-08-09T16:42:50Z",
            duration="00:04:01",
            code_name="Black Sesame Bao · 芝麻包",
            photo_url=(
                "https://github.com/Ding-Ding-Projects/dim-sum-photos/releases/"
                "download/catalog-v1/hk-dish-0059-black-sesame-bao.png"
            ),
        )

    def _stage(self, *, handoff: dict | None = None, release: dict | None = None):
        return stage_handoff(
            handoff=self.handoff if handoff is None else handoff,
            release=self.release if release is None else release,
            expected_repository=REPOSITORY,
            expected_workflow_run_id=RUN_ID,
            expected_workflow_run_number=RUN_NUMBER,
            expected_head_sha=HEAD_SHA,
            expected_tag=TAG,
            latest_successful_run_id=RUN_ID,
        )

    def test_exact_handoff_stages_manifest_and_source_sha(self):
        manifest, staging = self._stage()
        self.assertEqual(manifest["commit"], HEAD_SHA)
        self.assertEqual(manifest["releaseTag"], TAG)
        self.assertEqual(staging["sourceSha"], HEAD_SHA)
        self.assertEqual(staging["sourceWorkflowRunId"], RUN_ID)
        self.assertEqual(len(self.handoff["publishedAssets"]), 3)

    def test_create_rejects_wrong_repository_sha_tag_draft_size_and_digest(self):
        with self.assertRaisesRegex(ValueError, "owner/repository"):
            self._create(repository="Ding-Ding-Projects/not-this-project")
        changes = (
            ("target_commitish", "0" * 40, "target"),
            ("tag_name", "0.10.0-dev.999", "tag"),
            ("draft", True, "published"),
        )
        for key, value, message in changes:
            release = copy.deepcopy(self.release)
            release[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, message):
                self._create(release=release)
        for key, value, message in (
            ("size", self.release["assets"][0]["size"] + 1, "size mismatch"),
            ("digest", "sha256:" + "0" * 64, "digest mismatch"),
        ):
            release = copy.deepcopy(self.release)
            release["assets"][0][key] = value
            with self.subTest(asset_key=key), self.assertRaisesRegex(ValueError, message):
                self._create(release=release)

    def test_stage_rejects_missing_or_wrong_artifact_facts(self):
        for key, value in (
            ("repository", "Ding-Ding-Projects/wrong"),
            ("workflowRunId", RUN_ID + 1),
            ("workflowRunNumber", RUN_NUMBER + 1),
            ("headSha", "0" * 40),
            ("releaseTag", "0.10.0-dev.999"),
        ):
            handoff = copy.deepcopy(self.handoff)
            handoff[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                self._stage(handoff=handoff)
        with self.assertRaisesRegex(ValueError, "exact schema"):
            self._stage(handoff={"schemaVersion": 0})
        extra = copy.deepcopy(self.handoff)
        extra["unreviewed"] = True
        with self.assertRaisesRegex(ValueError, "exact schema"):
            self._stage(handoff=extra)
        duplicate = copy.deepcopy(self.handoff)
        duplicate["publishedAssets"].append(duplicate["publishedAssets"][0])
        with self.assertRaisesRegex(ValueError, "duplicates"):
            self._stage(handoff=duplicate)

    def test_live_draft_and_digest_drift_are_rejected(self):
        draft = copy.deepcopy(self.release)
        draft["draft"] = True
        with self.assertRaisesRegex(ValueError, "published release"):
            self._stage(release=draft)
        digest = copy.deepcopy(self.release)
        digest["assets"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "digest differs"):
            self._stage(release=digest)

    def test_out_of_order_run_is_an_explicit_no_op(self):
        with self.assertRaisesRegex(OutOfOrderHandoff, "older than successful run"):
            stage_handoff(
                handoff=self.handoff,
                release=self.release,
                expected_repository=REPOSITORY,
                expected_workflow_run_id=RUN_ID,
                expected_workflow_run_number=RUN_NUMBER,
                expected_head_sha=HEAD_SHA,
                expected_tag=TAG,
                latest_successful_run_id=RUN_ID + 1,
            )

    def test_failed_or_out_of_order_cli_preserves_prior_staging_files(self):
        handoff_path = self.root / "handoff.json"
        release_path = self.root / "release.json"
        manifest_output = self.root / "release-manifest.json"
        staging_output = self.root / "site-staging.json"
        prior_manifest = '{"prior":"manifest"}\n'
        prior_staging = '{"prior":"staging"}\n'
        handoff_path.write_text(json.dumps(self.handoff), encoding="utf-8")
        release_path.write_text(json.dumps(self.release), encoding="utf-8")
        manifest_output.write_text(prior_manifest, encoding="utf-8")
        staging_output.write_text(prior_staging, encoding="utf-8")
        base = [
            sys.executable,
            str(ROOT / "scripts" / "stage_site_release_handoff.py"),
            "--handoff",
            str(handoff_path),
            "--release-api",
            str(release_path),
            "--expected-repository",
            REPOSITORY,
            "--expected-workflow-run-id",
            str(RUN_ID),
            "--expected-workflow-run-number",
            str(RUN_NUMBER),
            "--expected-head-sha",
            HEAD_SHA,
            "--expected-tag",
            TAG,
            "--manifest-output",
            str(manifest_output),
            "--staging-output",
            str(staging_output),
        ]
        missing = list(base)
        missing[missing.index(str(handoff_path))] = str(self.root / "missing-handoff.json")
        absent = subprocess.run(
            missing + ["--latest-successful-run-id", str(RUN_ID)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(absent.returncode, 0)
        self.assertEqual(manifest_output.read_text(encoding="utf-8"), prior_manifest)
        self.assertEqual(staging_output.read_text(encoding="utf-8"), prior_staging)

        stale = subprocess.run(
            base + ["--latest-successful-run-id", str(RUN_ID + 1)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(stale.returncode, 20)
        self.assertEqual(manifest_output.read_text(encoding="utf-8"), prior_manifest)
        self.assertEqual(staging_output.read_text(encoding="utf-8"), prior_staging)

        bad_release = copy.deepcopy(self.release)
        bad_release["draft"] = True
        release_path.write_text(json.dumps(bad_release), encoding="utf-8")
        failed = subprocess.run(
            base + ["--latest-successful-run-id", str(RUN_ID)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(manifest_output.read_text(encoding="utf-8"), prior_manifest)
        self.assertEqual(staging_output.read_text(encoding="utf-8"), prior_staging)


if __name__ == "__main__":
    unittest.main()
