from pathlib import Path
import unittest

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "build-windows.yml"
).read_text(encoding="utf-8")
PUBLISH_HELPER = (
    Path(__file__).resolve().parents[1] / "scripts" / "publish_release.sh"
).read_text(encoding="utf-8")
SELECTOR = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "select_squirrel_delta_candidates.py"
).read_text(encoding="utf-8")
INSTALLER_SCRIPT = (
    Path(__file__).resolve().parents[1] / "build-installer.bat"
).read_text(encoding="utf-8")


class WindowsWorkflowContractTests(unittest.TestCase):
    def test_publish_requires_successful_deploy_and_gate(self):
        self.assertIn("needs.deploy.result == 'success'", WORKFLOW)
        self.assertIn("needs.deploy.outputs.tests_passed == 'true'", WORKFLOW)
        self.assertIn("id: release-gating-tests", WORKFLOW)

    def test_duration_is_zero_padded_hh_mm_ss(self):
        self.assertIn("scripts/release_timing.py --started", PUBLISH_HELPER)
        self.assertIn('--completed "$completed"', PUBLISH_HELPER)

    def test_new_release_timing_is_sampled_after_actual_publication(self):
        draft = PUBLISH_HELPER.index('test "$release_is_draft" = \'true\'')
        hosted_verification = PUBLISH_HELPER.index("verify_hosted_assets", draft)
        publish = PUBLISH_HELPER.index("-F draft=false --jq '.published_at'", draft)
        duration = PUBLISH_HELPER.index("scripts/release_timing.py", publish)
        self.assertLess(draft, hosted_verification)
        self.assertLess(hosted_verification, publish)
        self.assertLess(publish, duration)
        self.assertIn("Release remained a draft after publication", PUBLISH_HELPER)

    def test_workflow_invokes_the_executable_publication_helper_once(self):
        invocation = "run: bash scripts/publish_release.sh release-assets"
        self.assertEqual(WORKFLOW.count(invocation), 1)

    def test_push_and_dispatch_search_for_a_safe_delta_base(self):
        step = WORKFLOW[
            WORKFLOW.index("- name: Fetch previous Squirrel feed for delta") :
        ]
        step = step[
            : step.index("- name: Windows - Create unsigned Squirrel.Windows release")
        ]
        self.assertNotIn("if: github.event_name == 'release'", step)
        self.assertNotIn("github.event_name", step)
        for event in ("push:", "workflow_dispatch:"):
            self.assertIn(event, WORKFLOW[: WORKFLOW.index("jobs:")])
        self.assertNotIn("\n  release:", WORKFLOW[: WORKFLOW.index("jobs:")])
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
        verify = verify[: verify.index("- name: Upload Release Asset")]
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
        self.assertIn("repository-grand-total", PUBLISH_HELPER)
        self.assertIn("surviving git-blame lines", PUBLISH_HELPER)
        self.assertIn("Binary assets are not line-counted", PUBLISH_HELPER)
        publish = WORKFLOW[WORKFLOW.index("publish:") :]
        checkout = publish[
            publish.index("- name: Checkout release commit") : publish.index(
                "- name: Download x64 Squirrel artifacts"
            )
        ]
        self.assertIn("fetch-depth: 0", checkout)

    def test_release_notes_publish_and_verify_every_asset_sha256(self):
        publish = PUBLISH_HELPER
        self.assertIn("Release assets (SHA-256):", publish)
        self.assertIn("asset,sha256", publish)
        self.assertIn('sha256sum -- "$path"', publish)
        self.assertIn("LC_ALL=C sort", publish)
        self.assertIn('grep -Fqx "$asset_name,$asset_sha256"', publish)
        self.assertIn('test "$hosted_digest" = "sha256:$asset_sha256"', publish)
        self.assertIn('-F "body=@$notes_file"', publish)
        self.assertNotIn('-f "body=@$notes_file"', publish)
        self.assertIn(
            'final_body="$(gh api "/repos/$GITHUB_REPOSITORY/releases/$release_id" --jq \'.body\')"',
            publish,
        )

    def test_release_is_bound_to_the_exact_commit_and_asset_set(self):
        publish = PUBLISH_HELPER
        self.assertIn('printf \'%s\\n\' "Release commit: $RUN_SHA"', publish)
        self.assertIn("verify_tag_target()", publish)
        self.assertIn('git ls-remote --tags origin "refs/tags/$tag"', publish)
        self.assertIn(
            'gh api --method POST "/repos/$GITHUB_REPOSITORY/git/refs"', publish
        )
        self.assertIn('-f ref="refs/tags/$tag" -f sha="$RUN_SHA"', publish)
        self.assertIn('git rev-parse "$tag^{commit}"', publish)
        self.assertIn('test "$tag_commit" = "$RUN_SHA"', publish)
        self.assertGreaterEqual(publish.count("verify_tag_target"), 4)
        self.assertGreaterEqual(publish.count("verify_hosted_assets"), 3)
        self.assertIn("Refusing to mutate existing release", publish)
        self.assertIn("Duplicate release asset basename", publish)
        self.assertIn('test "$hosted_asset_count" -eq "$expected_asset_count"', publish)

    def test_release_artifact_input_is_an_exact_allowlist(self):
        publish = PUBLISH_HELPER
        self.assertNotIn("-name 'Setup.exe' -print -quit", publish)
        self.assertIn("Expected exactly one Setup.exe", publish)
        self.assertIn("Expected exactly one RELEASES index", publish)
        self.assertIn("Expected exactly one full Squirrel package", publish)
        self.assertIn('delta_name="Amulet-$RELEASE_TAG_EXPECTED_VERSION-delta.nupkg"', publish)
        self.assertIn('upload_paths+=("${delta_matches[0]}")', publish)
        self.assertIn("Unexpected release artifact", publish)

    def test_local_installer_always_reports_unsigned_sha_and_timing_evidence(self):
        self.assertIn("intended Git commit", INSTALLER_SCRIPT)
        self.assertIn("FINISHED_SOURCE_SHA", INSTALLER_SCRIPT)
        self.assertIn("BUILD_STARTED_AT", INSTALLER_SCRIPT)
        self.assertIn("BUILD_COMPLETED_AT", INSTALLER_SCRIPT)
        self.assertIn("[installer] duration:", INSTALLER_SCRIPT)
        self.assertIn("Expected exactly one SHA-256 digest", INSTALLER_SCRIPT)
        self.assertIn("unsigned Squirrel artifacts", INSTALLER_SCRIPT)
        self.assertNotIn(
            'if "%SILENT_MODE%"=="0" echo [installer] unsigned',
            INSTALLER_SCRIPT,
        )

    def test_unsigned_verification_enumerates_and_requires_real_targets(self):
        verify = WORKFLOW[
            WORKFLOW.index("- name: Verify unsigned installer contract") :
        ]
        verify = verify[: verify.index("- name: Upload Release Asset")]
        self.assertNotIn("Get-ChildItem $releaseDir -File -Include", verify)
        self.assertIn("$signatureTargets = @(", verify)
        self.assertIn("Get-ChildItem -LiteralPath $releaseDir -File", verify)
        self.assertIn("if ($signatureTargets.Count -eq 0)", verify)
        self.assertIn("$signatureTargets | ForEach-Object", verify)

    def test_release_tag_is_environment_backed_and_normalized(self):
        self.assertIn(
            "RELEASE_TAG_INPUT: ${{ inputs.release_tag || '' }}",
            WORKFLOW,
        )
        self.assertIn(
            'tag="$(python3 scripts/normalize_release_tag.py)"', PUBLISH_HELPER
        )
        self.assertNotIn('tag="${{ github.event.release.tag_name', PUBLISH_HELPER)

    def test_manual_publication_uses_the_built_canonical_identity(self):
        self.assertIn("release_tag:", WORKFLOW)
        self.assertIn(
            "Optional canonical major.minor.patch or major.minor.0-dev.run tag",
            WORKFLOW,
        )
        self.assertIn(
            "RELEASE_TAG: ${{ inputs.release_tag || '' }}",
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
