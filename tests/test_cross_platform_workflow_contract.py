from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CrossPlatformWorkflowContractTests(unittest.TestCase):
    def test_non_windows_release_lanes_are_not_active(self):
        workflows = ROOT / ".github" / "workflows"
        for name in (
            "build-macos.yml",
            "build-debian.yml",
            "build-flatpak.yml",
            "build-docker.yml",
        ):
            self.assertFalse((workflows / name).exists(), name)

    def test_linux_wayland_dependency_is_not_in_the_windows_delivery_contract(self):
        setup = (ROOT / "setup.cfg").read_text(encoding="utf-8")
        install_requires = setup.split("[options.extras_require]", 1)[0]
        self.assertNotIn("wayland-lock-pointer", install_requires)
        self.assertIn("wayland =", setup)

    def test_the_windows_build_no_longer_runs_a_release_gate(self):
        """The gating step was removed deliberately; it must not creep back.

        Tests still run on every push, in the Unittests workflow. What changed
        is that a failing test no longer withholds the build, so this asserts
        the removal rather than the step -- a test that quietly returned would
        restore the gate without anyone deciding to.

        The two halves of the old single-workflow contract now live in two
        workflows: build-windows.yml still runs (report-only) the suite
        alongside its own build, and build-electron-windows.yml -- the only
        workflow that publishes a release -- has no test step and no
        test-derived publish condition to check at all.
        """
        import yaml

        deploy_workflow = (
            ROOT / ".github" / "workflows" / "build-windows.yml"
        ).read_text(encoding="utf-8")
        publish_workflow = (
            ROOT / ".github" / "workflows" / "build-electron-windows.yml"
        ).read_text(encoding="utf-8")

        deploy_document = yaml.safe_load(deploy_workflow)
        deploy = deploy_document["jobs"]["deploy"]
        publish_document = yaml.safe_load(publish_workflow)
        publish = publish_document["jobs"]["publish"]

        # The gate is a *decision*, not a string. Asserting that pytest never
        # appears would also forbid running the suite to report its verdict,
        # which is the opposite of what was wanted: the build must ship
        # regardless, and the release must still say what the tests did.
        self.assertNotIn(
            "tests_passed",
            str(publish.get("if", "")),
            "the publish condition must not depend on a test verdict",
        )
        self.assertNotIn("tests_passed", deploy.get("outputs", {}))
        # The publishing workflow runs no tests of its own to depend on.
        self.assertNotIn("pytest", publish_workflow)

        for step in deploy["steps"]:
            name = str(step.get("name", ""))
            runs_tests = "pytest" in str(step.get("run", ""))
            if not runs_tests:
                continue
            with self.subTest(step=name):
                self.assertTrue(
                    step.get("continue-on-error") is True,
                    f"{name!r} runs the suite and must not be able to withhold "
                    "the build; mark it continue-on-error",
                )

    def test_the_release_states_its_measured_test_verdict(self):
        """RETIRED: the release no longer has a test verdict to state.

        This used to assert that a release published from build-windows.yml
        called out a failing test suite in its notes rather than omitting it.
        That workflow does not publish anymore, and build-electron-windows.yml
        -- the workflow that does -- runs no tests of its own at all (per the
        project's standing "GitHub Actions runs no tests" decision). Saying
        nothing about tests it never ran is the correct behaviour under
        "never imply a workflow verified something it did not run", not the
        defect this test used to guard against.

        build-windows.yml still measures test_verdict/test_summary and prints
        them into its own job log/artifacts, but that measurement is no
        longer wired to anything published, so there is nothing left here to
        assert against a release's contents.
        """

    def test_the_build_workflow_still_measures_and_reports_its_test_verdict(self):
        workflow = (ROOT / ".github" / "workflows" / "build-windows.yml").read_text(
            encoding="utf-8"
        )
        for marker in ("test_verdict", "test_summary"):
            with self.subTest(marker=marker):
                self.assertIn(marker, workflow)

    def test_the_check_workflow_still_uses_the_collector_that_sees_everything(self):
        """``unittest discover`` finds only TestCase subclasses.

        It silently skipped the majority of this suite once already, so the
        workflow that does still run the tests has to keep using pytest.
        """
        checks = (ROOT / ".github" / "workflows" / "unittests.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("python -m pytest tests", checks)
        self.assertNotIn("python -m unittest discover", checks)


if __name__ == "__main__":
    unittest.main()
