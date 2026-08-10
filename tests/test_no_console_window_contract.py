"""Amulet is a windowed application and must never flash a terminal window.

Three separate things can put a console on screen, and each one is checked
here because each fails in a way the others do not catch:

1. The packaged executable being built for the console subsystem, which shows a
   terminal for the whole session.
2. A child process started from the GUI without ``CREATE_NO_WINDOW``, which
   flashes a terminal for a fraction of a second on every background git call,
   update probe, or editor launch — often enough to be constant.
3. An entry point declared as a ``console_script``, which wraps the application
   in a console host even though the code itself is windowed.
"""

from __future__ import annotations

import ast
import configparser
import os
import re
import subprocess
from pathlib import Path

import pytest

from amulet_map_editor.api import process

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "amulet_map_editor"

#: Modules allowed to call ``subprocess`` directly.
#:
#: ``process`` is the helper every other call site routes through, and
#: ``_version`` is vendored versioneer output that only runs from a source
#: checkout during packaging, never from the running application.
DIRECT_SUBPROCESS_ALLOWED = {
    PACKAGE_ROOT / "api" / "process.py",
    PACKAGE_ROOT / "_version.py",
}

#: Call sites that legitimately pass the flags through explicitly rather than
#: using the ``process`` wrappers, because they also need bounded pipes.
EXPLICIT_FLAG_CALLERS = {
    PACKAGE_ROOT / "api" / "local_history.py",
    PACKAGE_ROOT / "api" / "framework" / "squirrel_update.py",
}


def _python_sources() -> list[Path]:
    return [
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if "amulet_resource_pack" not in path.parts
    ]


def test_no_window_kwargs_suppresses_the_console_on_windows() -> None:
    """The helper must actually set the flag, not merely exist."""
    kwargs = process.no_window_kwargs()
    if os.name == "nt":
        assert kwargs["creationflags"] & process.CREATE_NO_WINDOW
        assert kwargs["startupinfo"] is not None
    else:
        assert kwargs == {}


def test_no_window_kwargs_preserves_caller_flags() -> None:
    """Adding console suppression must not drop a caller's own flags."""
    kwargs = process.no_window_kwargs(creationflags=process.DETACHED_PROCESS)
    if os.name == "nt":
        assert kwargs["creationflags"] & process.DETACHED_PROCESS
        assert kwargs["creationflags"] & process.CREATE_NO_WINDOW
    else:
        assert kwargs["creationflags"] == process.DETACHED_PROCESS


def test_process_helpers_wrap_the_real_subprocess_api() -> None:
    """``run`` must behave like ``subprocess.run`` for an ordinary command."""
    result = process.run(
        ["python", "-c", "print('windowless')"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "windowless" in result.stdout


def test_every_module_routes_child_processes_through_the_helper() -> None:
    """No module may start a child process without console suppression.

    A single missed call site is enough to reintroduce the flashing terminal,
    so this walks the whole package rather than checking the known offenders.
    """
    offenders: list[str] = []
    for path in _python_sources():
        if path in DIRECT_SUBPROCESS_ALLOWED:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if not isinstance(func.value, ast.Name) or func.value.id != "subprocess":
                continue
            if func.attr not in ("run", "Popen", "call", "check_call", "check_output"):
                continue
            # ``**process.no_window_kwargs()`` arrives as a keyword with no
            # name; an explicit ``creationflags=`` is equally acceptable.
            suppressed = any(
                keyword.arg is None or keyword.arg in ("creationflags", "startupinfo")
                for keyword in node.keywords
            )
            if suppressed:
                continue
            offenders.append(
                f"{path.relative_to(REPO_ROOT)}:{node.lineno} subprocess.{func.attr}"
            )
    assert not offenders, (
        "these call sites would open a console window on Windows; use "
        "amulet_map_editor.api.process instead:\n  " + "\n  ".join(offenders)
    )


def test_explicit_flag_callers_pass_the_suppression_kwargs() -> None:
    """The two bounded-pipe call sites must still suppress the console."""
    for path in sorted(EXPLICIT_FLAG_CALLERS):
        source = path.read_text(encoding="utf-8")
        assert "no_window_kwargs()" in source, (
            f"{path.relative_to(REPO_ROOT)} starts a child process and must "
            "spread process.no_window_kwargs() into it"
        )


def test_packaged_executable_is_windowed() -> None:
    """The shipped PyInstaller executable must not allocate a console."""
    spec = (REPO_ROOT / "installer" / "Amulet.spec").read_text(encoding="utf-8")
    console_flags = re.findall(r"console=(\w+)", spec)
    assert console_flags, "the PyInstaller spec declares no console setting"
    # The first EXE block is the shipped application; the second is the opt-in
    # debug bundle, which exists precisely to show diagnostics.
    assert (
        console_flags[0] == "False"
    ), "the shipped amulet executable must be built for the GUI subsystem"
    assert "is_windows" not in " ".join(
        console_flags
    ), "console must not be conditional on the platform"


def test_default_entry_point_is_a_gui_script() -> None:
    """``amulet_map_editor`` must install as a windowed launcher."""
    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "setup.cfg", encoding="utf-8")
    entry_points = parser["options.entry_points"]
    gui_scripts = entry_points.get("gui_scripts", "")
    console_scripts = entry_points.get("console_scripts", "")
    assert "amulet_map_editor =" in gui_scripts
    assert (
        "amulet_map_editor =" not in console_scripts
    ), "the default command must not be wrapped in a console host"


def test_squirrel_package_ships_one_windowed_launcher() -> None:
    """The installer must not put a console shortcut in the Start menu."""
    script = (REPO_ROOT / "installer" / "build-squirrel.ps1").read_text(
        encoding="utf-8"
    )
    assert (
        "amulet_debug.exe" in script and "Remove-Item" in script
    ), "the console debug build must be excluded from the Squirrel package"
    assert (
        "GUI subsystem" in script
    ), "the packaging step must verify the shipped executable's subsystem"


def test_build_script_launches_without_a_terminal() -> None:
    """``build.bat`` must not leave a console attached to the running editor."""
    script = (REPO_ROOT / "build.bat").read_text(encoding="utf-8")
    assert "pyw" in script, "build.bat must launch through the windowed interpreter"
    assert 'start ""' in script, "build.bat must detach the launched application"


def test_crash_reporting_survives_a_missing_console() -> None:
    """A windowed build has no streams; the reporter must not raise."""
    assert process.write_console("diagnostic") is None
    assert isinstance(process.has_console(), bool)


@pytest.mark.skipif(os.name != "nt", reason="console allocation is Windows-specific")
def test_helper_runs_a_console_program_without_a_window() -> None:
    """A real console program must still run correctly while hidden."""
    result = process.run(
        ["cmd", "/c", "echo hidden"], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0
    assert "hidden" in result.stdout


def test_process_module_has_no_import_side_effects() -> None:
    """Importing the helper must never start anything."""
    result = subprocess.run(
        [
            "python",
            "-c",
            "import amulet_map_editor.api.process as p; print(p.is_windows())",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        **process.no_window_kwargs(),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() in ("True", "False")
