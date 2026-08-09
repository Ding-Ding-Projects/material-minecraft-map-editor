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
        self.assertIn("scripts/release_timing.py --started", WORKFLOW)
        self.assertIn('--completed "$completed"', WORKFLOW)

    def test_new_release_timing_is_sampled_after_actual_publication(self):
        publish = WORKFLOW.index(
            'gh release edit "$tag" --repo "$GITHUB_REPOSITORY" --draft=false'
        )
        completion = WORKFLOW.index("--json publishedAt", publish)
        duration = WORKFLOW.index("scripts/release_timing.py", completion)
        self.assertLess(publish, completion)
        self.assertLess(completion, duration)
        self.assertIn("Release remained a draft after publication", WORKFLOW)

    def test_push_builds_also_search_for_a_safe_delta_base(self):
        step = WORKFLOW[
            WORKFLOW.index("- name: Fetch previous full package for delta") :
        ]
        step = step[
            : step.index("- name: Windows - Create unsigned Squirrel.Windows release")
        ]
        self.assertNotIn("if: github.event_name == 'release'", step)
        self.assertIn("scripts/validate_squirrel_delta_base.py", step)
        self.assertIn("CURRENT_VERSION", step)

    def test_release_notes_explain_line_scope_and_surviving_attribution(self):
        self.assertIn("repository-grand-total", WORKFLOW)
        self.assertIn("surviving git-blame lines", WORKFLOW)
        self.assertIn("Binary assets are not line-counted", WORKFLOW)
        publish = WORKFLOW[WORKFLOW.index("publish:") :]
        checkout = publish[
            publish.index("- name: Checkout release commit") : publish.index(
                "- name: Download x64 Squirrel artifacts"
            )
        ]
        self.assertIn("fetch-depth: 0", checkout)

    def test_release_tag_is_environment_backed_and_normalized(self):
        self.assertIn(
            "RELEASE_TAG_INPUT: ${{ github.event.release.tag_name || '' }}", WORKFLOW
        )
        self.assertIn('tag="$(python3 scripts/normalize_release_tag.py)"', WORKFLOW)
        self.assertNotIn('tag="${{ github.event.release.tag_name', WORKFLOW)

    def test_squirrel_assets_remain_required(self):
        for asset in ("Setup.exe", "RELEASES", "-full.nupkg"):
            self.assertIn(asset, WORKFLOW)

    def test_published_release_emits_exact_api_verified_site_handoff(self):
        publish = WORKFLOW[WORKFLOW.index("publish:") :]
        self.assertIn("scripts/create_site_release_handoff.py", publish)
        self.assertIn('gh api "/repos/$GITHUB_REPOSITORY/releases/tags/$tag"', publish)
        self.assertIn('--workflow-run-id "$RUN_ID"', publish)
        self.assertIn('--workflow-run-number "$RUN_NUMBER"', publish)
        self.assertIn('--head-sha "$RUN_SHA"', publish)
        self.assertIn("name: amulet-release-handoff-${{ github.run_id }}", publish)
        self.assertIn("path: release-handoff/site-release-handoff.json", publish)
        self.assertIn("if-no-files-found: error", publish)

    def test_failed_packaging_still_collects_bounded_diagnostics(self):
        self.assertIn("if: ${{ always() }}", WORKFLOW)
        self.assertIn("continue-on-error: true", WORKFLOW)
        self.assertIn("if-no-files-found: warn", WORKFLOW)
        self.assertIn("retention-days: 7", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
