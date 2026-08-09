from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_build_scripts_are_touchless_and_use_supported_paths():
    build = (ROOT / "build.bat").read_text(encoding="utf-8")
    installer = (ROOT / "build-installer.bat").read_text(encoding="utf-8")
    assert "SILENT_MODE" in build and "pip install --user" in build
    assert "build.bat" in installer and "PyInstaller" in installer
    assert "build-squirrel.ps1" in installer
    for prohibited in ("signtool", "azuresigntool", "codesign"):
        assert prohibited not in installer.lower()
