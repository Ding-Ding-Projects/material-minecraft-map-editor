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

    def test_windows_release_gate_bootstraps_pytest(self):
        workflow = (ROOT / ".github" / "workflows" / "build-windows.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("build pytest", workflow)
        # The gate runs pytest, which collects both TestCase subclasses and
        # module-level test functions.  ``unittest discover`` only finds the
        # former, and silently skipped the majority of this suite.
        self.assertIn("python -m pytest tests", workflow)
        self.assertNotIn(
            "python -m unittest discover",
            workflow,
            "the release gate must not fall back to a collector that skips "
            "every module-level test function",
        )

    def test_check_workflow_uses_the_same_collector_as_the_release_gate(self):
        """A gate that runs different tests from CI proves the wrong thing."""
        checks = (ROOT / ".github" / "workflows" / "unittests.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("python -m pytest tests", checks)
        self.assertNotIn("python -m unittest discover", checks)


if __name__ == "__main__":
    unittest.main()
