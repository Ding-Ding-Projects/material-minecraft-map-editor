import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _extract_powershell_function(source: str, name: str) -> str:
    start = source.index(f"function {name}")
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"PowerShell function {name} has no closing brace")


def _assert_build_contract(
    build: str,
    installer: str,
    bootstrap_git: str,
    squirrel: str,
) -> None:
    assert "SILENT_MODE" in build and "pip install --user" in build
    assert '"numpy~=1.26"' in build and "--no-build-isolation" in build
    assert "PYTHON_ARGS=-3.11" in build and "PYTHON_ARGS=-3.11" in installer
    assert "%PYTHON_CMD%" not in build and "%PYTHON_CMD%" not in installer
    assert build.count('"%PYTHON_EXE%" %PYTHON_ARGS%') >= 4
    assert installer.count('"%PYTHON_EXE%" %PYTHON_ARGS%') >= 3
    assert "Python311\\python.exe" in build and "Python311\\python.exe" in installer
    assert 'set "REPO_DIR=%%~fI"' in build
    assert '--editable "%REPO_DIR%" --no-build-isolation' in build
    assert 'py -3.11 -c "import sys"' in build
    assert "bootstrap-python.ps1" in build and "ExecutionPolicy Bypass" in build
    assert "assert sys.version_info[:2] == (3, 11)" in build
    assert "assert sys.version_info[:2] == (3, 11)" in installer

    # Silent mode may never reach an interactive primitive.  Keep exactly one
    # launch choice, nested in the explicit non-silent block, and no pause.
    assert not re.search(r"(?im)^\s*pause(?:\s|$)", build + "\n" + installer)
    assert len(re.findall(r"(?im)^\s*choice(?:\s|$)", build)) == 1
    interactive = re.search(
        r'(?ms)^if "%SILENT_MODE%"=="0" \(\s*$' r"(?P<body>.*?)" r"^\)\s*$",
        build,
    )
    assert interactive is not None
    assert 'choice /M "Launch Amulet now"' in interactive.group("body")
    assert "if errorlevel 2 goto :build_done" in interactive.group("body")
    assert not re.search(r"(?im)^\s*choice(?:\s|$)", installer)

    # A literal early success is forbidden.  build.bat has exactly one final
    # success exit; build-installer.bat exits only through its result variable.
    build_commands = [
        line.strip()
        for line in build.splitlines()
        if line.strip() and not line.lstrip().lower().startswith("rem ")
    ]
    assert build_commands[-1].lower() == "exit /b 0"
    assert sum(line.lower() == "exit /b 0" for line in build_commands) == 1
    assert not re.search(r"(?im)^\s*exit\s+/b\s+0\s*$", installer)
    installer_commands = [
        line.strip()
        for line in installer.splitlines()
        if line.strip() and not line.lstrip().lower().startswith("rem ")
    ]
    assert installer_commands[-1] == "exit /b %BUILD_EXIT_CODE%"

    # Git bootstrap must precede every repository command and return a verified
    # absolute executable path.  No bare PATH-resolved `git` call is allowed.
    bootstrap_position = installer.index("bootstrap-git.ps1")
    first_repository_git = installer.index('"%GIT_EXE%" -C "%REPO_DIR%"')
    assert bootstrap_position < first_repository_git
    assert installer.count("bootstrap-git.ps1") == 1
    assert not re.search(r"(?im)^\s*git(?:\.exe)?\s", installer)
    assert "GIT_PATH_FILE" in installer and 'if not exist "%GIT_EXE%"' in installer
    assert "Git.Git" in bootstrap_git and "--scope user" in bootstrap_git
    assert "git-for-windows/git/releases/download" in bootstrap_git
    assert "PortableGit-2.55.0.3-64-bit.7z.exe" in bootstrap_git
    assert "58919776L" in bootstrap_git
    assert (
        "ab00566336b5472120f9a52d34f2e79c5406535792acb0548001ffd0bd090e5d"
        in bootstrap_git
    )
    assert "PortableGit size mismatch" in bootstrap_git
    assert "PortableGit SHA-256 mismatch" in bootstrap_git
    assert "if ($download.Length -ne $portableSize)" in bootstrap_git
    assert "if ($actualHash -ne $portableSha256)" in bootstrap_git
    assert "ExistingOnly" in bootstrap_git

    # Provenance is an immutable archive of SOURCE_SHA, not a build from the
    # mutable checkout.  Start/end SHA and tree/index checks remain independent.
    assert (
        'archive --format=zip --output="%SOURCE_ARCHIVE%" "%SOURCE_SHA%"' in installer
    )
    assert 'call "%STAGE_DIR%\\build.bat" /s' in installer
    assert '"%STAGE_DIR%\\installer\\Amulet.spec"' in installer
    assert '-File "%STAGE_DIR%\\installer\\build-squirrel.ps1"' in installer
    assert "staging exact commit: %SOURCE_SHA%" in installer
    assert 'if /I not "%FINISHED_SOURCE_SHA%"=="%SOURCE_SHA%"' in installer
    assert "FINISHED_SOURCE_SHA" in installer and "intended Git commit" in installer
    assert installer.count('ls-files -v >"%INDEX_OUTPUT%"') == 2
    assert installer.count("status --porcelain --untracked-files=all") == 2
    assert (
        installer.count('findstr /R /C:"^[abcdefghijklmnopqrstuvwxyz] " /C:"^S "') == 2
    )
    assert re.findall(r'(?im)^set "FINDSTR_EXIT=([^"]*)"', installer) == [
        "%ERRORLEVEL%",
        "%ERRORLEVEL%",
    ]
    assert installer.count('if not "%FINDSTR_EXIT%"=="1"') == 2
    assert "assume-unchanged or skip-worktree entries are not allowed" in installer
    assert "assume-unchanged or skip-worktree entries appeared" in installer
    assert "working tree must be clean before packaging" in installer
    assert "working tree changed during packaging" in installer

    assert "build-squirrel.ps1" in installer and "PyInstaller" in installer
    assert 'set "BUILD_VERSION=0.10.0-dev-local"' in installer
    assert "normalize_squirrel_version.py" not in installer
    assert "-InputDirectory" in installer and "-OutputDirectory" in installer
    assert "Setup.exe was not produced" in installer

    # Hash each required final artifact exactly once.  Parsing command operands
    # prevents three Setup.exe hashes from masquerading under three labels.
    hash_operands = re.findall(r'(?im)^certutil -hashfile "([^"]+)" SHA256', installer)
    assert hash_operands == [
        "%FINAL_RELEASE_DIR%\\Setup.exe",
        "%FINAL_RELEASE_DIR%\\RELEASES",
        "%FINAL_RELEASE_DIR%\\Amulet-%BUILD_VERSION%-full.nupkg",
    ]
    artifact_reports = re.findall(
        r"(?im)^echo \[installer\] artifact path: (.+)$", installer
    )
    assert artifact_reports == hash_operands
    assert installer.count("SHA-256 command failed") == 3
    assert installer.count("Expected exactly one SHA-256 digest") == 3
    assert installer.count("Write-Output ('[installer] SHA-256: '") == 3
    assert "BUILD_STARTED_AT" in installer and "BUILD_COMPLETED_AT" in installer
    assert "[installer] duration:" in installer
    assert 'if "%SILENT_MODE%"=="0" echo [installer] unsigned' not in installer
    assert "unsigned Squirrel artifacts: %FINAL_RELEASE_DIR%" in installer

    assert "Windows PowerShell 5.1" in squirrel
    assert "ArgumentList" in squirrel and "Arguments" in squirrel
    assert "function Get-Sha256" in squirrel
    assert "function Get-Sha1" in squirrel
    assert "function Assert-PeFile" in squirrel
    assert "Invalid DOS signature" in squirrel
    assert "Invalid PE signature" in squirrel
    assert "Unsupported PE machine" in squirrel
    assert "Invalid PE section count" in squirrel
    assert "PE executable characteristic is missing" in squirrel
    assert "Invalid PE optional-header size" in squirrel
    assert "PE headers extend beyond the file" in squirrel
    assert "Unsupported PE optional-header magic" in squirrel
    assert "PE optional header is truncated" in squirrel
    assert "Assert-PeFile $file.FullName" in squirrel
    assert re.search(
        r"if \(Test-Path -LiteralPath \$releaseDir\) \{\s*"
        r"Remove-Item -LiteralPath \$releaseDir -Recurse -Force\s*\}",
        squirrel,
    )
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


def test_root_build_scripts_are_touchless_and_use_supported_paths():
    build = _read("build.bat")
    installer = _read("build-installer.bat")
    bootstrap_git = _read("scripts/bootstrap-git.ps1")
    squirrel = _read("installer/build-squirrel.ps1")
    _assert_build_contract(build, installer, bootstrap_git, squirrel)

    smoke = _read("scripts/smoke_squirrel_delta.ps1")
    assert "Amulet-0.10.100427-delta.nupkg" in smoke
    assert "Expected one full-only RELEASES row" in smoke
    for prohibited in ("signtool", "azuresigntool", "codesign"):
        assert prohibited not in installer.lower()
    bootstrap_python = _read("scripts/bootstrap-python.ps1")
    assert "Python.Python.3.11" in bootstrap_python
    assert "--scope user" in bootstrap_python
    assert "--accept-package-agreements" in bootstrap_python
    assert "python.org/ftp/python/3.11.9" in bootstrap_python
    assert "winget unavailable" in bootstrap_python


def test_build_contract_rejects_behavioral_mutations():
    originals = {
        "build": _read("build.bat"),
        "installer": _read("build-installer.bat"),
        "bootstrap": _read("scripts/bootstrap-git.ps1"),
        "squirrel": _read("installer/build-squirrel.ps1"),
    }
    mutations = {
        "early installer success": {
            "installer": originals["installer"].replace(
                "@echo off", "@echo off\nexit /b 0", 1
            )
        },
        "early build success": {
            "build": originals["build"].replace("@echo off", "@echo off\nexit /b 0", 1)
        },
        "silent pause": {
            "installer": originals["installer"].replace(
                "setlocal EnableExtensions", "pause\nsetlocal EnableExtensions", 1
            )
        },
        "choice moved outside silent guard": {
            "build": originals["build"]
            .replace('  choice /M "Launch Amulet now"\n', "", 1)
            .replace(
                'if "%SILENT_MODE%"=="0" (',
                'choice /M "Launch Amulet now"\nif "%SILENT_MODE%"=="0" (',
                1,
            )
        },
        "source SHA self-comparison": {
            "installer": originals["installer"].replace(
                'if /I not "%FINISHED_SOURCE_SHA%"=="%SOURCE_SHA%"',
                'if /I not "%SOURCE_SHA%"=="%SOURCE_SHA%"',
                1,
            )
        },
        "three Setup hashes": {
            "installer": originals["installer"]
            .replace(
                'certutil -hashfile "%FINAL_RELEASE_DIR%\\RELEASES" SHA256',
                'certutil -hashfile "%FINAL_RELEASE_DIR%\\Setup.exe" SHA256',
                1,
            )
            .replace(
                'certutil -hashfile "%FINAL_RELEASE_DIR%\\Amulet-%BUILD_VERSION%-full.nupkg" SHA256',
                'certutil -hashfile "%FINAL_RELEASE_DIR%\\Setup.exe" SHA256',
                1,
            )
        },
        "missing artifact path report": {
            "installer": originals["installer"].replace(
                "echo [installer] artifact path: %FINAL_RELEASE_DIR%\\Setup.exe\n",
                "",
                1,
            )
        },
        "Git before bootstrap": {
            "installer": originals["installer"].replace(
                "@echo off",
                '@echo off\n"%GIT_EXE%" -C "%REPO_DIR%" status --short',
                1,
            )
        },
        "removed hidden-index Chut": {
            "installer": originals["installer"].replace("ls-files -v", "ls-files", 1)
        },
        "findstr error accepted": {
            "installer": originals["installer"].replace(
                'if not "%FINDSTR_EXIT%"=="1"',
                'if "%FINDSTR_EXIT%"=="1"',
                1,
            )
        },
        "findstr result overridden": {
            "installer": originals["installer"].replace(
                'set "FINDSTR_EXIT=%ERRORLEVEL%"',
                'set "FINDSTR_EXIT=%ERRORLEVEL%"\nset "FINDSTR_EXIT=1"',
                1,
            )
        },
        "mutable checkout build": {
            "installer": originals["installer"].replace(
                'call "%STAGE_DIR%\\build.bat" /s',
                'call "%REPO_DIR%\\build.bat" /s',
                1,
            )
        },
        "caller working-directory build": {
            "build": originals["build"].replace(
                '--editable "%REPO_DIR%" --no-build-isolation',
                "--editable . --no-build-isolation",
                1,
            )
        },
        "weak portable size": {
            "bootstrap": originals["bootstrap"].replace(
                "$portableSize = 58919776L", "$portableSize = 1L", 1
            )
        },
        "portable size self-comparison": {
            "bootstrap": originals["bootstrap"].replace(
                "if ($download.Length -ne $portableSize)",
                "if ($download.Length -ne $download.Length)",
                1,
            )
        },
        "weak portable hash": {
            "bootstrap": originals["bootstrap"].replace(
                "ab00566336b5472120f9a52d34f2e79c5406535792acb0548001ffd0bd090e5d",
                "0" * 64,
                1,
            )
        },
        "portable hash self-comparison": {
            "bootstrap": originals["bootstrap"].replace(
                "if ($actualHash -ne $portableSha256)",
                "if ($actualHash -ne $actualHash)",
                1,
            )
        },
        "removed PE invocation": {
            "squirrel": originals["squirrel"].replace(
                "        Assert-PeFile $file.FullName\n", "", 1
            )
        },
        "removed stale-output cleanup": {
            "squirrel": originals["squirrel"].replace(
                """    if (Test-Path -LiteralPath $releaseDir) {
        Remove-Item -LiteralPath $releaseDir -Recurse -Force
    }
""",
                "",
                1,
            )
        },
    }

    for name, changed in mutations.items():
        candidate = originals | changed
        with pytest.raises(AssertionError, match=".*"):
            _assert_build_contract(
                candidate["build"],
                candidate["installer"],
                candidate["bootstrap"],
                candidate["squirrel"],
            )


def test_git_bootstrap_existing_only_returns_a_working_absolute_path(tmp_path):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    assert powershell is not None
    path_file = tmp_path / "git-path.txt"
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts/bootstrap-git.ps1"),
            "-PathFile",
            str(path_file),
            "-ExistingOnly",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    git_path = Path(path_file.read_text(encoding="utf-8").strip())
    assert git_path.is_absolute() and git_path.is_file()
    version = subprocess.run(
        [str(git_path), "--version"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert version.returncode == 0
    assert version.stdout.startswith("git version ")


def test_pe_header_chut_rejects_non_pe_and_accepts_minimal_pe(tmp_path):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    assert powershell is not None
    squirrel = _read("installer/build-squirrel.ps1")
    function_source = _extract_powershell_function(squirrel, "Assert-PeFile")

    invalid = tmp_path / "invalid.exe"
    invalid.write_bytes(b"not a PE file")

    pseudo = bytearray(512)
    pseudo[0:2] = b"MZ"
    pseudo[0x3C:0x40] = (0x80).to_bytes(4, "little")
    pseudo[0x80:0x84] = b"PE\0\0"
    pseudo_path = tmp_path / "header-shaped-zero-blob.exe"
    pseudo_path.write_bytes(pseudo)

    short_optional = bytearray(512)
    short_optional[0:2] = b"MZ"
    short_optional[0x3C:0x40] = (0x80).to_bytes(4, "little")
    short_optional[0x80:0x84] = b"PE\0\0"
    short_optional[0x84:0x86] = (0x8664).to_bytes(2, "little")
    short_optional[0x86:0x88] = (1).to_bytes(2, "little")
    short_optional[0x94:0x96] = (2).to_bytes(2, "little")
    short_optional[0x96:0x98] = (0x0002).to_bytes(2, "little")
    short_optional[0x98:0x9A] = (0x020B).to_bytes(2, "little")
    short_optional_path = tmp_path / "two-byte-optional-header.exe"
    short_optional_path.write_bytes(short_optional)

    minimal = bytearray(512)
    pe_offset = 0x80
    coff_offset = pe_offset + 4
    minimal[0:2] = b"MZ"
    minimal[0x3C:0x40] = pe_offset.to_bytes(4, "little")
    minimal[pe_offset : pe_offset + 4] = b"PE\0\0"
    minimal[coff_offset : coff_offset + 2] = (0x8664).to_bytes(2, "little")
    minimal[coff_offset + 2 : coff_offset + 4] = (1).to_bytes(2, "little")
    minimal[coff_offset + 16 : coff_offset + 18] = (0xF0).to_bytes(2, "little")
    minimal[coff_offset + 18 : coff_offset + 20] = (0x0002).to_bytes(2, "little")
    minimal[coff_offset + 20 : coff_offset + 22] = (0x020B).to_bytes(2, "little")
    valid = tmp_path / "minimal.exe"
    valid.write_bytes(minimal)

    invalid_script = tmp_path / "invalid-check.ps1"
    invalid_script.write_text(
        function_source + f"\nAssert-PeFile '{invalid.as_posix()}'\n",
        encoding="utf-8",
    )
    invalid_result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(invalid_script)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert invalid_result.returncode != 0
    assert "PE file is too small" in invalid_result.stderr

    pseudo_script = tmp_path / "pseudo-check.ps1"
    pseudo_script.write_text(
        function_source + f"\nAssert-PeFile '{pseudo_path.as_posix()}'\n",
        encoding="utf-8",
    )
    pseudo_result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(pseudo_script)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert pseudo_result.returncode != 0
    assert "Unsupported PE machine" in pseudo_result.stderr

    short_optional_script = tmp_path / "short-optional-check.ps1"
    short_optional_script.write_text(
        function_source + f"\nAssert-PeFile '{short_optional_path.as_posix()}'\n",
        encoding="utf-8",
    )
    short_optional_result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(short_optional_script)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert short_optional_result.returncode != 0
    assert "PE optional header is truncated" in short_optional_result.stderr

    valid_script = tmp_path / "valid-check.ps1"
    valid_script.write_text(
        function_source + f"\nAssert-PeFile '{valid.as_posix()}'\n",
        encoding="utf-8",
    )
    valid_result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(valid_script)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert valid_result.returncode == 0, valid_result.stdout + valid_result.stderr
