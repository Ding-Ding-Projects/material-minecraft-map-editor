from pathlib import Path
import unittest


WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "build-windows.yml"
).read_text(encoding="utf-8")


class WindowsWorkflowContractTests(unittest.TestCase):
    def test_publish_requires_successful_deploy_and_gate(self):
        self.assertIn("needs.deploy.result == 'success'", WORKFLOW)
        self.assertIn("needs.deploy.outputs.tests_passed == 'true'", WORKFLOW)
        self.assertIn("id: release-gating-tests", WORKFLOW)

    def test_duration_is_zero_padded_hh_mm_ss(self):
        self.assertIn('{elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d}', WORKFLOW)

    def test_release_tag_is_environment_backed_and_normalized(self):
        self.assertIn("RELEASE_TAG_INPUT: ${{ github.event.release.tag_name || '' }}", WORKFLOW)
        self.assertIn("tag=\"$(python3 scripts/normalize_release_tag.py)\"", WORKFLOW)
        self.assertNotIn('tag="${{ github.event.release.tag_name', WORKFLOW)

    def test_squirrel_assets_remain_required(self):
        for asset in ("Setup.exe", "RELEASES", "-full.nupkg"):
            self.assertIn(asset, WORKFLOW)


if __name__ == "__main__":
    unittest.main()
