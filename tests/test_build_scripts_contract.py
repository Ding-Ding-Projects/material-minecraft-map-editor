from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_build_scripts_are_touchless_and_use_supported_paths():
    build = (ROOT / "build.bat").read_text(encoding="utf-8")
    installer = (ROOT / "build-installer.bat").read_text(encoding="utf-8")
    assert "SILENT_MODE" in build and "pip install --user" in build
    assert '"numpy~=1.26"' in build and "--no-build-isolation" in build
    assert "PYTHON_CMD=py -3.11" in build and "PYTHON_CMD=py -3.11" in installer
    assert "bootstrap-python.ps1" in build and "ExecutionPolicy Bypass" in build
    assert "build.bat" in installer and "PyInstaller" in installer
    assert "build-squirrel.ps1" in installer
    assert "-InputDirectory" in installer and "-OutputDirectory" in installer
    assert "RELEASE_DIR" in installer
    assert "Setup.exe was not produced" in installer
    assert "certutil -hashfile" in installer
    squirrel = (ROOT / "installer/build-squirrel.ps1").read_text(encoding="utf-8")
    assert "Windows PowerShell 5.1" in squirrel
    assert "ArgumentList" in squirrel and "Arguments" in squirrel
    assert "function Get-Sha256" in squirrel
    assert "Get-FileHash" not in squirrel
    for prohibited in ("signtool", "azuresigntool", "codesign"):
        assert prohibited not in installer.lower()
    bootstrap = (ROOT / "scripts/bootstrap-python.ps1").read_text(encoding="utf-8")
    assert "Python.Python.3.11" in bootstrap
    assert "--scope user" in bootstrap and "--accept-package-agreements" in bootstrap
