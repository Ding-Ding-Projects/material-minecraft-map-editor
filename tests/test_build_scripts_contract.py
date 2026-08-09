from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_root_build_scripts_are_touchless_and_use_supported_paths():
    build = (ROOT / "build.bat").read_text(encoding="utf-8")
    installer = (ROOT / "build-installer.bat").read_text(encoding="utf-8")
    assert "SILENT_MODE" in build and "pip install --user" in build
    assert '"numpy~=1.26"' in build and "--no-build-isolation" in build
    assert "PYTHON_ARGS=-3.11" in build and "PYTHON_ARGS=-3.11" in installer
    assert "Python311\\python.exe" in build and "Python311\\python.exe" in installer
    assert 'py -3.11 -c "import sys"' in build
    assert "bootstrap-python.ps1" in build and "ExecutionPolicy Bypass" in build
    assert "assert sys.version_info[:2] == (3, 11)" in build
    assert "assert sys.version_info[:2] == (3, 11)" in installer
    assert "build.bat" in installer and "PyInstaller" in installer
    assert 'choice /M "Launch Amulet now"' in build
    assert "if errorlevel 2 goto :build_done" in build
    assert "build-squirrel.ps1" in installer
    assert "-InputDirectory" in installer and "-OutputDirectory" in installer
    assert "RELEASE_DIR" in installer
    assert "Setup.exe was not produced" in installer
    assert "certutil -hashfile" in installer
    assert installer.count("certutil -hashfile") == 3
    squirrel = (ROOT / "installer/build-squirrel.ps1").read_text(encoding="utf-8")
    assert "Windows PowerShell 5.1" in squirrel
    assert "ArgumentList" in squirrel and "Arguments" in squirrel
    assert "function Get-Sha256" in squirrel
    assert "function Get-Sha1" in squirrel
    assert "Get-FileHash" not in squirrel
    assert (
        "PreviousPackagePath and PreviousReleasesPath must be supplied together"
        in squirrel
    )
    assert "--output-releases" in squirrel
    assert "--package-sha256" in squirrel and "--releases-sha256" in squirrel
    assert "--expected-source" in squirrel and "--channel" in squirrel
    assert '"Amulet-$Version-delta.nupkg"' in squirrel
    assert "publishableEntries" in squirrel
    assert "unpublished previous full package" in squirrel
    assert "$publishableEntries = @($validatedEntries[$fullPackageName])" in squirrel
    assert "RELEASES must remain full-only" in squirrel
    smoke = (ROOT / "scripts/smoke_squirrel_delta.ps1").read_text(encoding="utf-8")
    assert "Amulet-0.10.100427-delta.nupkg" in smoke
    assert "Expected one full-only RELEASES row" in smoke
    for prohibited in ("signtool", "azuresigntool", "codesign"):
        assert prohibited not in installer.lower()
    bootstrap = (ROOT / "scripts/bootstrap-python.ps1").read_text(encoding="utf-8")
    assert "Python.Python.3.11" in bootstrap
    assert "--scope user" in bootstrap and "--accept-package-agreements" in bootstrap
    assert "python.org/ftp/python/3.11.9" in bootstrap
    assert "winget unavailable" in bootstrap
