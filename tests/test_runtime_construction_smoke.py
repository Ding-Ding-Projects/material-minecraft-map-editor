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


# --------------------------------------------------------------------------
# Every dialog, discovered rather than listed.
#
# The first version of this file listed the dialogs by hand and got three of
# the five names wrong.  Each wrong name skipped, the run reported "4 passed,
# 3 skipped", and three dialogs went unchecked while the file looked like it
# was checking them.  A hand-written list is the right tool when the risk is a
# surface being MISSING; here the risk is a surface being missed, so the list
# is discovered and it is the discovery that gets guarded.
# --------------------------------------------------------------------------

#: Below this, discovery has broken rather than the product having shrunk.
#: A sweep that silently finds nothing passes every assertion in this file.
MINIMUM_DISCOVERED_DIALOGS = 14

#: Modules that genuinely cannot be imported in a bare test environment, with
#: the reason.  Anything NOT listed here that fails to import is a finding.
EXPECTED_UNIMPORTABLE = {
    # Needs the Minecraft world-format libraries and their data files, which a
    # source checkout has only after the optional data install.
    "select_world",
}


def _argument_for(name: str, parent, made):
    """Return a plausible real argument for a dialog's extra parameter."""
    if name in ("message", "title", "label", "text"):
        return "Smoke test"
    if name == "style":
        return wx.OK | wx.CANCEL
    if name == "control":
        widget = wx.Panel(parent)
        made.append(widget)
        return widget
    if name == "notebook":
        book = wx.Notebook(parent)
        made.append(book)
        return book
    if name in ("commands", "items", "entries"):
        return []
    if name.endswith(("_callback", "_handler")) or name.startswith("on_"):
        # A no-op that accepts anything. Construction must not invoke it, and
        # if some dialog does call its callback during __init__, this returning
        # quietly is still the right answer -- the test is about the
        # constructor running, not about what the callback would have done.
        return lambda *args, **kwargs: None
    return None


def _discover_dialogs():
    """Return every wx.Dialog subclass defined under the UI package."""
    import importlib
    import inspect
    import pkgutil

    import amulet_map_editor.api.wx.ui as ui_package

    discovered = []
    unimportable = {}
    for module_info in pkgutil.iter_modules(ui_package.__path__):
        try:
            module = importlib.import_module(
                f"amulet_map_editor.api.wx.ui.{module_info.name}"
            )
        except Exception as error:  # noqa: BLE001 - the reason is the finding
            unimportable[module_info.name] = f"{type(error).__name__}: {error}"
            continue
        for attribute, value in vars(module).items():
            if (
                inspect.isclass(value)
                and issubclass(value, wx.Dialog)
                and value.__module__ == module.__name__
            ):
                discovered.append((module_info.name, attribute, value))
    return sorted(discovered), unimportable


def test_discovery_still_finds_the_dialogs(app) -> None:
    """Guard the sweep itself, so it cannot quietly cover nothing."""
    discovered, unimportable = _discover_dialogs()
    assert len(discovered) >= MINIMUM_DISCOVERED_DIALOGS, (
        f"Only {len(discovered)} dialogs were discovered. Either the product "
        "lost some, or -- far more likely -- this sweep stopped working and "
        "every construction test below is now passing on an empty list."
    )
    unexpected = set(unimportable) - EXPECTED_UNIMPORTABLE
    assert not unexpected, (
        "These UI modules could not be imported at all, which no source-text "
        "test would notice:\n  "
        + "\n  ".join(f"{name}: {unimportable[name]}" for name in sorted(unexpected))
    )


def test_every_discovered_dialog_constructs(app) -> None:
    """Build each one. A dialog that raises here is a dead menu item.

    Reported together rather than one assertion per dialog, so a run names
    every broken dialog at once instead of stopping at the first.
    """
    discovered, _ = _discover_dialogs()
    failures = []
    for module_name, class_name, dialog_class in discovered:
        import inspect

        parent = wx.Frame(None)
        made = []
        try:
            parameters = list(
                inspect.signature(dialog_class.__init__).parameters.values()
            )
            arguments = []
            unsupported = None
            for parameter in parameters[2:]:
                if parameter.default is not parameter.empty:
                    break
                if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
                    continue
                value = _argument_for(parameter.name, parent, made)
                if value is None:
                    unsupported = parameter.name
                    break
                arguments.append(value)
            if unsupported is not None:
                # Not a skip in disguise: an argument this test cannot invent
                # is a real gap, and it is reported as one.
                failures.append(
                    f"{module_name}.{class_name}: needs an argument this smoke "
                    f"test cannot supply ({unsupported!r}); give it a default "
                    "or teach _argument_for about it"
                )
                continue
            dialog = dialog_class(parent, *arguments)
            try:
                assert dialog.GetSize().width > 0
                assert dialog.GetSize().height > 0
            finally:
                dialog.Destroy()
        except Exception as error:  # noqa: BLE001 - the error IS the finding
            failures.append(
                f"{module_name}.{class_name}: {type(error).__name__}: {error}"
            )
        finally:
            for widget in made:
                try:
                    widget.Destroy()
                except RuntimeError:
                    pass
            parent.Destroy()

    assert not failures, "Dialogs that do not construct:\n  " + "\n  ".join(failures)
