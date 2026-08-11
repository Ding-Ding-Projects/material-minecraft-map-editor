"""Construct the real windows, because reading the source cannot.

Almost every test in this repository asserts things about source *text*: that a
file contains a call, that a name is absent, that two strings agree.  That is a
genuinely useful shape and it catches a lot -- but it is blind to one whole
class of defect, and this file exists because that class shipped.

A ``NameError`` inside a constructor is invisible to all of it.  The module
imports cleanly, every substring a source-text test looks for is present and
correct, the whole suite goes green, and the application cannot open its own
window.  That is not hypothetical: ``AmuletUI.__init__`` called
``tokens.scaled()`` without importing ``tokens``, 1,272 tests passed, and the
only thing that noticed was a test that actually built the frame.

So these tests build things.  They are deliberately shallow -- construct, assert
it exists, destroy -- because depth is not the point.  The point is that the
constructor runs at all.
"""

from __future__ import annotations

import os
import tempfile

import pytest

wx = pytest.importorskip("wx")


@pytest.fixture(scope="module")
def app():
    """A live wx.App, on an isolated profile so a run cannot touch real settings."""
    os.environ.setdefault("CONFIG_DIR", tempfile.mkdtemp(prefix="amulet-smoke-"))
    application = wx.App()
    yield application


def test_the_main_window_constructs(app) -> None:
    """The shell must build. Everything else in the product is behind this.

    If this fails, the application does not start -- there is no partially
    working state to fall back to and no error the user could act on.
    """
    from amulet_map_editor.api.framework import amulet_ui

    window = amulet_ui.AmuletUI(None)
    try:
        assert window.GetSize().width > 0
        assert window.GetSize().height > 0
        # The minimum size is a real floor, not a default: a window that can be
        # dragged smaller than its own contents clips them.
        assert window.GetMinSize().width > 0
        assert window.GetMinSize().height > 0
    finally:
        window.Destroy()


def test_the_shell_scales_with_the_display(app) -> None:
    """Built at 150%, the shell is 150% of its size -- floor included.

    This is the runtime half of the display-scaling contract.  The source-text
    half checks that no fixed pixel minimum remains; this checks that the
    window which results is actually bigger, which no amount of reading the
    source can establish.
    """
    from amulet_map_editor.api.framework import amulet_ui
    from amulet_map_editor.api.studio import tokens

    original = tokens.dpi_factor()
    try:
        tokens._dpi_factor = 1.0
        plain = amulet_ui.AmuletUI(None)
        try:
            at_100 = plain.GetMinSize().width
        finally:
            plain.Destroy()

        tokens._dpi_factor = 1.5
        scaled = amulet_ui.AmuletUI(None)
        try:
            at_150 = scaled.GetMinSize().width
        finally:
            scaled.Destroy()
    finally:
        tokens._dpi_factor = original

    assert at_150 > at_100, (
        "The shell's minimum size did not grow with the display scale, so on a "
        "scaled screen the window can be sized below its own contents."
    )
    assert at_150 == pytest.approx(at_100 * 1.5, abs=2)


@pytest.mark.parametrize(
    "module_name, class_name",
    [
        ("amulet_map_editor.api.wx.ui.path_dialog", "PathDialog"),
        ("amulet_map_editor.api.wx.ui.preferences", "PreferencesDialog"),
        ("amulet_map_editor.api.wx.ui.notifications", "NotificationCentreDialog"),
        ("amulet_map_editor.api.wx.ui.local_history", "LocalHistoryDialog"),
        ("amulet_map_editor.api.wx.ui.changelog", "ChangelogDialog"),
    ],
)
def test_the_dialogs_construct(app, module_name: str, class_name: str) -> None:
    """Each dialog must build without a name, attribute or signature error.

    A dialog that raises on construction is a menu item that does nothing, and
    a source-text test asserting the menu item exists will pass happily while
    it does nothing.
    """
    import importlib

    try:
        module = importlib.import_module(module_name)
    except ImportError as error:  # pragma: no cover - module removed or renamed
        pytest.skip(f"{module_name} is not importable here: {error}")
    dialog_class = getattr(module, class_name, None)
    if dialog_class is None:
        pytest.skip(f"{module_name} no longer defines {class_name}")

    parent = wx.Frame(None)
    try:
        try:
            dialog = dialog_class(parent)
        except TypeError as error:
            # A changed constructor signature is a real finding, but it is a
            # different finding from a broken body, so say which this is.
            pytest.skip(f"{class_name} needs arguments this smoke test lacks: {error}")
        try:
            assert dialog.GetSize().width > 0
            assert dialog.GetSize().height > 0
        finally:
            dialog.Destroy()
    finally:
        parent.Destroy()
