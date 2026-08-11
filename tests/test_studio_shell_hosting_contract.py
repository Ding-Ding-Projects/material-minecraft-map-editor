"""The application frame's content is the Studio shell, not the old start page.

The rewrite replaced a single start card plus tool strip with two views: a
backstage for starting and opening projects, and a ribbon workspace for editing
one.  The world notebook still exists -- it owns world loading and per-page
unsaved-work protection, and the workspace viewport hosts it once a world is
open -- but it is no longer what the user sees on startup, and a test that still
described it as the interface would be describing a build that has shipped.

The frame is checked as source: constructing ``AmuletUI`` needs a display, and
what is asserted here is the wiring rather than the pixels.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from amulet_map_editor.api import studio

ROOT = Path(__file__).resolve().parents[1]
FRAME = (ROOT / "amulet_map_editor/api/framework/amulet_ui.py").read_text(
    encoding="utf-8"
)
SHELL = (ROOT / "amulet_map_editor/api/studio/shell.py").read_text(encoding="utf-8")


def test_the_package_exposes_the_shell_and_its_registries():
    for name in (
        "StudioShell",
        "SPECS",
        "SURFACES",
        "SURFACE_GROUPS",
        "COMMANDS",
        "SearchState",
        "Spec",
        "Section",
        "open_surface",
    ):
        assert name in studio.__all__, name
        assert name in dir(studio), name


def test_reading_the_registries_never_needs_a_display():
    """A build step or a documentation pass must not have to import a window.

    The two names that genuinely need wxPython stay behind the module's
    ``__getattr__``, so importing the package cannot pull a window class in.
    The check runs in a child process with ``wx`` poisoned, because this one
    would pass on a machine that simply happens to have wxPython installed.
    """
    assert set(studio._LAZY) == {"StudioShell", "open_surface"}
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['wx'] = None; "
            "from amulet_map_editor.api import studio; "
            "assert studio.SPECS and studio.SURFACES and studio.COMMANDS; "
            "assert 'amulet_map_editor.api.studio.shell' not in sys.modules",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.stderr == ""


def test_the_frame_builds_the_studio_shell_as_its_content():
    assert "from amulet_map_editor.api.studio.shell import StudioShell" in FRAME
    assert "return StudioShell(self._shell, self)" in FRAME
    assert "self._shell_sizer.Add(self._studio, 1, wx.EXPAND)" in FRAME


def test_the_old_chrome_is_hidden_rather_than_shown_beside_the_new_shell():
    """Two title bars and two command surfaces would be the visible symptom."""
    creation = FRAME.split("self._studio = self._create_studio()", 1)[1].split(
        "self._shell.SetSizer", 1
    )[0]
    for hidden in (
        "self._title_bar.Hide()",
        "self._command_bar.Hide()",
        "self._tab_content.Hide()",
    ):
        assert hidden in creation, hidden


def test_a_build_whose_shell_cannot_be_constructed_still_starts():
    """Degrading to the previous shell beats refusing to open a window."""
    creator = FRAME.split("def _create_studio", 1)[1].split("\n    def ", 1)[0]
    assert "except Exception:" in creator
    assert "log.exception" in creator
    assert "return None" in creator
    assert "if self._studio is None:" in FRAME
    assert "self._shell_sizer.Add(self._tab_content, 1, wx.EXPAND)" in FRAME


def test_the_notebook_is_kept_because_it_owns_world_loading_and_protection():
    assert "self._level_notebook.open_level(path)" in FRAME
    assert "self.sync_studio_project()" in FRAME
    assert "def active_world_page" in FRAME


def test_the_frame_still_offers_the_call_sites_the_surface_index_asks_it_for():
    for method in (
        "def open_project_dialog",
        "def open_preferences",
        "def open_local_history",
        "def open_tab_manager",
        "def select_language",
    ):
        assert method in FRAME, method


def test_the_shell_owns_two_views_and_swaps_between_them():
    assert 'self.view = "backstage"' in SHELL
    assert "def show_backstage" in SHELL
    assert "def show_workspace" in SHELL
    assert 'self.view = "workspace"' in SHELL


def test_the_shell_exposes_the_contracted_public_surface():
    for method in (
        "def open_project",
        "def close_project",
        "def open_surface",
        "def run_command",
        "def open_palette",
        "def refresh_theme",
        "def set_saved",
        "def install_accelerators",
    ):
        assert method in SHELL, method


def test_the_command_palette_keeps_its_one_global_shortcut():
    assert 'wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("F")' in FRAME
    assert "self._studio.install_accelerators()" in FRAME


def test_the_update_banner_notifications_and_surprise_stay_wired_to_the_frame():
    """The rewrite replaced the interface, not the operational surfaces."""
    for marker in (
        "def _render_update_banner",
        "def show_notification",
        "begin_startup_dim_sum_surprise",
        "self._narrator",
        "self._scheduled_runtime",
    ):
        assert marker in FRAME, marker


def test_the_shell_records_state_changes_in_the_local_history():
    assert "local_history" in SHELL


def test_informational_results_are_non_blocking_rather_than_modal():
    assert "nonblocking" in SHELL
    assert "ShowModal" not in SHELL
