from pathlib import Path
import unittest

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "build-windows.yml"
).read_text(encoding="utf-8")
SELECTOR = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "select_squirrel_delta_candidates.py"
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

    def test_only_release_builds_search_for_a_safe_delta_base(self):
        step = WORKFLOW[
            WORKFLOW.index("- name: Fetch previous Squirrel feed for delta") :
        ]
        step = step[
            : step.index("- name: Windows - Create unsigned Squirrel.Windows release")
        ]
        self.assertIn("if: github.event_name == 'release'", step)
        self.assertIn("scripts/validate_squirrel_delta_base.py", step)
        self.assertIn("CURRENT_VERSION", step)

    def test_delta_base_is_a_matched_releases_and_package_pair(self):
        fetch = WORKFLOW[
            WORKFLOW.index("- name: Fetch previous Squirrel feed for delta") :
        ]
        fetch = fetch[
            : fetch.index("- name: Windows - Create unsigned Squirrel.Windows release")
        ]
        self.assertIn("scripts/select_squirrel_delta_candidates.py", fetch)
        self.assertIn("--channel $env:CURRENT_CHANNEL --limit 8", fetch)
        self.assertIn("--pattern $asset.name", fetch)
        self.assertIn("'--releases', $releaseIndex.FullName", fetch)
        self.assertIn("'--expected-source', $candidateTag", fetch)
        self.assertIn("assets.Count -gt 32", fetch)
        self.assertIn("134217728", fetch)
        self.assertIn("262144", fetch)
        self.assertIn("package-sha256", fetch)
        self.assertIn("releases-sha256", fetch)
        self.assertIn("PREVIOUS_PACKAGE=", fetch)
        self.assertIn("PREVIOUS_RELEASES=", fetch)

    def test_delta_inventory_paginates_with_a_bounded_truncation_sentinel(self):
        fetch = WORKFLOW[
            WORKFLOW.index("- name: Fetch previous Squirrel feed for delta") :
        ]
        fetch = fetch[
            : fetch.index("- name: Windows - Create unsigned Squirrel.Windows release")
        ]
        self.assertIn("--limit 501", fetch)
        self.assertIn("selector's 500-entry ceiling", fetch)
        self.assertIn("_MAX_RELEASES = 500", SELECTOR)
        self.assertIn("_MAX_INVENTORY_BYTES = 1024 * 1024", SELECTOR)

        build = WORKFLOW[
            WORKFLOW.index(
                "- name: Windows - Create unsigned Squirrel.Windows release"
            ) :
        ]
        build = build[: build.index("- name: Verify unsigned installer contract")]
        self.assertIn('-PreviousPackagePath "$env:PREVIOUS_PACKAGE"', build)
        self.assertIn('-PreviousReleasesPath "$env:PREVIOUS_RELEASES"', build)
        self.assertIn('-PreviousPackageSha256 "$env:PREVIOUS_PACKAGE_SHA256"', build)
        self.assertIn('-PreviousReleasesSha256 "$env:PREVIOUS_RELEASES_SHA256"', build)
        self.assertIn('-PreviousSourceTag "$env:PREVIOUS_SOURCE_TAG"', build)
        self.assertIn('-PreviousChannel "$env:PREVIOUS_CHANNEL"', build)

    def test_selected_delta_base_requires_delta_but_feed_remains_full_only(self):
        verify = WORKFLOW[
            WORKFLOW.index("- name: Verify unsigned installer contract") :
        ]
        verify = verify[: verify.index("- name: Publish to PyPi")]
        self.assertIn('"Amulet-$env:BUILD_VERSION-delta.nupkg"', verify)
        self.assertIn("Compare-Object", verify)
        self.assertIn("must advertise only the current full package", verify)
        self.assertNotIn("$expectedReleaseNames +=", verify)

    def test_version_resolution_carries_an_explicit_release_channel(self):
        resolve = WORKFLOW[
            WORKFLOW.index("- name: Resolve build version") : WORKFLOW.index(
                "- name: Fetch previous Squirrel feed for delta"
            )
        ]
        self.assertIn("--json", resolve)
        self.assertIn("BUILD_CHANNEL=", resolve)
        self.assertIn("BUILD_SOURCE_TAG=", resolve)
        self.assertIn("build_channel=$channel", resolve)
        self.assertIn("source_tag=$source", resolve)

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
            "RELEASE_TAG_INPUT: ${{ github.event.release.tag_name || inputs.release_tag || '' }}",
            WORKFLOW,
        )
        self.assertIn('tag="$(python3 scripts/normalize_release_tag.py)"', WORKFLOW)
        self.assertNotIn('tag="${{ github.event.release.tag_name', WORKFLOW)

    def test_manual_and_release_publication_share_the_built_canonical_identity(self):
        self.assertIn("release_tag:", WORKFLOW)
        self.assertIn(
            "Optional canonical major.minor.patch or major.minor.0-dev.run tag",
            WORKFLOW,
        )
        self.assertIn(
            "RELEASE_TAG: ${{ github.event.release.tag_name || inputs.release_tag || '' }}",
            WORKFLOW,
        )
        self.assertIn(
            "RELEASE_TAG_FALLBACK: ${{ needs.deploy.outputs.source_tag }}", WORKFLOW
        )
        self.assertIn(
            "RELEASE_TAG_EXPECTED_SOURCE: ${{ needs.deploy.outputs.source_tag }}",
            WORKFLOW,
        )
        self.assertIn(
            "RELEASE_TAG_EXPECTED_VERSION: ${{ needs.deploy.outputs.build_version }}",
            WORKFLOW,
        )

    def test_squirrel_assets_remain_required(self):
        for asset in ("Setup.exe", "RELEASES", "-full.nupkg"):
            self.assertIn(asset, WORKFLOW)

    def test_failed_packaging_still_collects_bounded_diagnostics(self):
        self.assertIn("if: ${{ always() }}", WORKFLOW)
        self.assertIn("continue-on-error: true", WORKFLOW)
        self.assertIn("if-no-files-found: warn", WORKFLOW)
        self.assertIn("retention-days: 7", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
