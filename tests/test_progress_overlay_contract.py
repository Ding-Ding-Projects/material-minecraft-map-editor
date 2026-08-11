"""Progress belongs on the shell, never in a modal dialog.

Informational, success and progress messages are non-blocking surfaces in this
project, and a modal dialog is reserved strictly for a decision the user has to
make before anything else can happen.  Saving is not a decision.  Neither is
closing a world, extracting one, or running an operation over one -- and every
one of those used to open a ``wx.ProgressDialog``, which takes focus and
disables the window behind it for the length of the work.

Two halves are needed here and only one of them is obvious.  Banning the call
catches it coming back.  It does **not** catch a long operation that reports
nothing at all: a file with no progress reporting in it passes a rule about how
progress must be reported, because the rule never found anything to look at.
So the second half is a hand-written list of the operations that must report,
and it fails when one of them stops.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "amulet_map_editor"

#: Every long-running operation that must report on the shell's overlay, with
#: the function that runs it.  Hand-written, and deliberately not derived by
#: searching for ``begin_progress``: a list built that way can only ever contain
#: the call sites that already exist, so it would go on passing after one of
#: them was deleted.
MUST_REPORT_PROGRESS = (
    ("amulet_map_editor/api/framework/pages/world_page.py", "WorldPageUI.close"),
    (
        "amulet_map_editor/api/wx/ui/select_world.py",
        "WorldSelectUI._extract_archive",
    ),
    (
        "amulet_map_editor/programs/edit/api/canvas/edit_canvas.py",
        "show_loading_dialog",
    ),
    (
        "amulet_map_editor/programs/edit/api/canvas/edit_canvas.py",
        "EditCanvas._run_operation",
    ),
)


def _qualified_functions(path: Path) -> dict:
    """Return every function in ``path`` by ``Class.method`` or bare name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict = {}

    def walk(node, prefix: str = "") -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[f"{prefix}{child.name}"] = child

    walk(tree)
    return found


def _calls_in(node) -> set:
    names = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        target = child.func
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


#: The blocking progress surfaces this change removed.  ``wx.ProgressDialog``
#: is application-modal; ``wx.BusyInfo`` is a borderless banner that blocks
#: input and reports nothing at all.
BANNED_SURFACES = frozenset({"ProgressDialog", "BusyInfo"})

#: Style flags that disable the window behind a dialog.
BANNED_STYLES = frozenset({"PD_APP_MODAL", "PD_CAN_ABORT", "PD_AUTO_HIDE"})


def _blocking_uses(path: Path) -> set:
    """Return the banned wx names this file actually *uses*, ignoring prose.

    Reading the source as text finds the words in the comments that explain why
    the call is gone, which would make the rule impossible to satisfy while
    documenting it.  Reading the parsed tree finds the call.
    """
    used = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Attribute) and node.attr in (
            BANNED_SURFACES | BANNED_STYLES
        ):
            used.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in (
            BANNED_SURFACES | BANNED_STYLES
        ):
            used.add(node.id)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in (BANNED_SURFACES | BANNED_STYLES):
                    used.add(alias.name)
    return used


def test_no_surface_in_the_application_blocks_to_report_progress():
    """The modal progress dialog is gone and may not come back.

    ``PD_APP_MODAL`` is in the same list as the dialog itself, because a
    ProgressDialog reintroduced without that flag would still be a second
    window in front of the interface -- and one asked for with it is the exact
    surface this replaced.
    """
    offenders = {}
    for path in PACKAGE.rglob("*.py"):
        used = _blocking_uses(path)
        if used:
            offenders[str(path.relative_to(ROOT))] = sorted(used)
    assert offenders == {}, (
        "these files still block the application to report progress: "
        f"{offenders}; report it on the shell overlay with begin_progress instead"
    )


@pytest.mark.parametrize("relative,function", MUST_REPORT_PROGRESS)
def test_every_long_operation_still_reports_its_progress(relative, function):
    """A named long operation that reports nothing is a silent wait.

    This is the half of the contract that a ban cannot express.  Deleting the
    reporting from any of these leaves the file passing every rule about how
    progress must be drawn, because there is no longer any progress in it.
    """
    path = ROOT / relative
    functions = _qualified_functions(path)
    assert function in functions, f"{function} is gone from {relative}"
    calls = _calls_in(functions[function])
    assert "begin_progress" in calls or "update" in calls, (
        f"{relative}::{function} runs a long operation and reports nothing; "
        "open a row with begin_progress"
    )


def test_the_shell_exposes_the_two_methods_the_reporter_calls():
    """The bridge finds a shell by duck-typing, so the duck has to have feet."""
    shell = (ROOT / "amulet_map_editor/api/framework/amulet_ui.py").read_text(
        encoding="utf-8"
    )
    assert "def update_progress(self, task: ProgressTask) -> None:" in shell
    assert "def clear_progress(self, key: str) -> None:" in shell
    # Positioned, never laid out: a progress row must not take space from the
    # interface it is reporting about, exactly as a notification toast must not.
    assert "self._shell_sizer.Add(self._progress_overlay" not in shell
    assert "_position_progress_overlay" in shell


def test_the_overlay_reuses_the_loading_screen_s_two_bar_appearances():
    """One definition of "cannot say", so two surfaces cannot disagree."""
    overlay = (ROOT / "amulet_map_editor/api/studio/progress_overlay.py").read_text(
        encoding="utf-8"
    )
    loading = (ROOT / "amulet_map_editor/api/studio/loading.py").read_text(
        encoding="utf-8"
    )
    assert "from amulet_map_editor.api.studio.loading import (" in overlay
    assert "draw_determinate_bar" in overlay and "draw_indeterminate_band" in overlay
    # And the loading screen must be a caller rather than keeping a second copy.
    assert loading.count("def draw_determinate_bar") == 1
    assert loading.count("def draw_indeterminate_band") == 1
    assert "draw_determinate_bar(dc, rect, fraction, palette)" in loading
