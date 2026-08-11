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
        """
        workflow = (ROOT / ".github" / "workflows" / "build-windows.yml").read_text(
            encoding="utf-8"
        )
        for marker in ("release-gating", "tests_passed", "python -m pytest tests"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, workflow)

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
