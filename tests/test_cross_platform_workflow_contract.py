from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CrossPlatformWorkflowContractTests(unittest.TestCase):
    def test_macos_release_lane_is_explicitly_unsigned(self):
        workflow = (ROOT / ".github" / "workflows" / "build-macos.yml").read_text(
            encoding="utf-8"
        )
        spec = (ROOT / "installer" / "Amulet.spec").read_text(encoding="utf-8")
        self.assertNotIn("xcrun notarytool", workflow)
        self.assertNotIn("codesign --verify", workflow)
        self.assertNotIn("MacOS - Store Credentials", workflow)
        self.assertNotIn("APPLE_CODESIGN_IDENTITY", spec)
        self.assertIn("codesign_identity=None", spec)
        self.assertIn("Unsigned macOS DMG created", workflow)

    def test_linux_wayland_dependency_is_optional(self):
        setup = (ROOT / "setup.cfg").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "build-debian.yml").read_text(
            encoding="utf-8"
        )
        install_requires = setup.split("[options.extras_require]", 1)[0]
        self.assertNotIn("wayland-lock-pointer", install_requires)
        self.assertIn("wayland =", setup)
        self.assertIn("Optional Wayland pointer support", workflow)
        self.assertIn("pointer fallback", workflow)

    def test_windows_release_gate_bootstraps_pytest(self):
        workflow = (ROOT / ".github" / "workflows" / "build-windows.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("build pytest", workflow)
        self.assertIn("python -m unittest discover", workflow)


if __name__ == "__main__":
    unittest.main()
