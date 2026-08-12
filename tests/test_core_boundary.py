"""Enforce the core/wx boundary.

Every module named in ``amulet_map_editor.api.core_boundary.PORTABLE_CORE_MODULES``
must import successfully in a fresh subprocess with ``wx`` blocked -- not just
absent, but actively refused, so a module that imports wx lazily inside a
function body would still need that function to run before this test would
catch it (it will not; see the note in the boundary module about the split
being real but partial). The point of running in a subprocess per module is
isolation: importing module A must not leave sys.modules polluted in a way
that makes module B's import look clean when it would not be on its own.

Watch this test fail before trusting it: temporarily add ``import wx`` to one
of the listed modules, confirm this test goes red, then remove it and confirm
green again. That check was performed while writing this test (see the task
report); it is not just an assertion left to future faith.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from amulet_map_editor.api.core_boundary import KNOWN_NOT_PORTABLE, PORTABLE_CORE_MODULES

_CHECK_SCRIPT = textwrap.dedent(
    """
    import importlib
    import sys

    class _WxBlocker:
        def find_module(self, name, path=None):
            if name == "wx" or name.startswith("wx."):
                return self
            return None

        def load_module(self, name):
            raise ImportError(
                "wx is blocked by the core-boundary test: %s" % name
            )

    # Make absolutely sure wx is not already imported by test collection
    # machinery before we try to block it.
    for _name in list(sys.modules):
        if _name == "wx" or _name.startswith("wx."):
            del sys.modules[_name]

    sys.meta_path.insert(0, _WxBlocker())

    importlib.import_module(sys.argv[1])
    print("BOUNDARY_OK")
    """
)


def _import_without_wx(module_name: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _CHECK_SCRIPT, module_name],
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("module_name", PORTABLE_CORE_MODULES)
def test_portable_core_module_does_not_import_wx(module_name: str) -> None:
    result = _import_without_wx(module_name)
    assert result.returncode == 0 and "BOUNDARY_OK" in result.stdout, (
        f"{module_name} is listed as portable in core_boundary.py but "
        f"importing it while wx is blocked failed.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_known_not_portable_modules_actually_fail_without_wx() -> None:
    """Guard against the not-portable list going stale.

    If one of these modules were fixed to no longer need wx, this test would
    fail -- which is the prompt to move it up into PORTABLE_CORE_MODULES
    instead of leaving it stranded in the "known not portable" list.
    """

    for module_name in KNOWN_NOT_PORTABLE:
        result = _import_without_wx(module_name)
        assert result.returncode != 0, (
            f"{module_name} is recorded as NOT portable, but it imported "
            f"cleanly with wx blocked. Move it into PORTABLE_CORE_MODULES "
            f"in amulet_map_editor/api/core_boundary.py."
        )


def test_boundary_lists_do_not_overlap() -> None:
    overlap = set(PORTABLE_CORE_MODULES) & set(KNOWN_NOT_PORTABLE)
    assert not overlap, f"modules listed as both portable and not: {overlap}"


def test_portable_core_modules_have_no_duplicates() -> None:
    assert len(PORTABLE_CORE_MODULES) == len(set(PORTABLE_CORE_MODULES))
