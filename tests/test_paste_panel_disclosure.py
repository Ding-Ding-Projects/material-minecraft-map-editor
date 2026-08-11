"""The editor's own paste panel says what its coordinate means, and still builds.

The Studio properties pane is not the only place a paste coordinate is typed.
``PasteTool`` builds its own panel with its own ``x``, ``y`` and ``z`` boxes,
``enable()`` shows it, and ``AmuletUI._host_editor_overlays`` reparents it onto
the viewport so it stays visible beside the pane.  Its only statement of the
centre rule was a hover tooltip, which discloses it to somebody who already
suspects it -- and the reader who types a coordinate, confirms, walks over and
finds bare stone is precisely the reader who never hovered.

**Why this module exists separately from the runtime one.**
``tests/test_editor_clone_runtime.py`` checks the finished article: it opens a
real world and reads what the real panel is showing.  That is the right check
and it is also a slow one that skips on a host without a canvas, so the seam
underneath gets a fast test of its own here.

That seam is worth testing because it has already broken once.  The wrap width
was first taken with ``self._location.GetBestSize()``, and ``TupleIntInput`` is
a ``wx.FlexGridSizer`` rather than a window: sizers have ``CalcMin`` and no
``GetBestSize``, so the line raised ``AttributeError`` at construction and took
the entire paste tool down with it.  Nothing about the source said so, and the
suite stayed green because nothing in it built that panel.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor import lang  # noqa: E402

paste_module = pytest.importorskip(
    "amulet_map_editor.programs.edit.plugins.tools.paste",
    reason="the editor's paste tool needs OpenGL and amulet-core",
)

NOTE_KEY = "program_3d_edit.paste_tool.location_note"


@pytest.fixture(scope="module")
def app() -> Iterator[Any]:
    existing = wx.App.Get()
    created = None
    if existing is None:
        try:
            created = wx.App(False)
        except Exception as error:  # pragma: no cover - depends on the host
            pytest.skip(f"wx.App could not start on this host: {error!r}")
    yield existing or created
    if created is not None:
        created.Destroy()


@pytest.fixture()
def panel(app) -> Iterator[Any]:
    """A real panel inside a real frame, laid out by the frame's own sizer.

    The frame sizer matters.  A panel parented to a frame with nothing driving
    its size keeps a default one, and a ``wx.StaticText`` laid out inside it
    measures zero high -- which looks exactly like a note that was never added
    and would make the assertions below fail against correct code.
    """
    frame = wx.Frame(None, size=(400, 400), pos=(-32000, -32000))
    built = wx.Panel(frame)
    built.SetSizer(wx.BoxSizer(wx.VERTICAL))
    holder = wx.BoxSizer(wx.VERTICAL)
    holder.Add(built, 1, wx.EXPAND)
    frame.SetSizer(holder)
    frame.Layout()
    wx.Yield()
    try:
        yield built
    finally:
        frame.Destroy()
        wx.Yield()


def test_the_disclosure_string_exists_and_says_centre() -> None:
    """The panel has something to show, and it is the rule rather than a key."""
    text = lang.get(NOTE_KEY)
    assert text != NOTE_KEY, (
        f"{NOTE_KEY} is missing from the language files, so the panel would "
        "render its own translation key as the disclosure"
    )
    assert (
        "CENTRE" in text.upper()
    ), f"the paste panel's location note does not mention the centre: {text!r}"


def test_the_wrap_width_survives_the_coordinate_control_being_a_sizer(
    panel,
) -> None:
    """The width helper answers for the control the panel actually passes it.

    This is the regression.  ``TupleIntInput`` is a sizer, and asking a sizer
    for ``GetBestSize`` raises rather than returning a poor answer -- so the
    failure is not a badly wrapped caption, it is a paste tool that does not
    build.
    """
    location = paste_module.TupleIntInput(panel, "x", "y", "z")
    panel.GetSizer().Add(location, 0, wx.EXPAND)

    assert isinstance(location, wx.Sizer), (
        "TupleIntInput is no longer a sizer, so this test is guarding a seam "
        "that has moved and should be rewritten rather than deleted"
    )
    assert not hasattr(location, "GetBestSize"), (
        "a sizer now answers GetBestSize, which means the original failure "
        "this guards can no longer be reproduced -- check the helper is still "
        "needed before trusting this test"
    )

    width = paste_module._control_width(location)
    assert width > 0, (
        f"the wrap width came back {width}; wx.StaticText.Wrap treats zero or "
        "less as 'do not wrap', so the panel would grow to the width of the "
        "whole sentence"
    )


def test_a_control_that_measures_nothing_still_wraps() -> None:
    """The floor is real, and it is what makes a zero measurement safe.

    Written against stand-ins rather than the real coordinate control, because
    the real one happens to measure something once its panel is laid out -- so
    a test that only ever asks the real one cannot tell a live floor from a
    dead one.  Deleting the floor left the earlier assertion green, which is
    exactly the shape of guard this repository has been bitten by before.
    """
    assert paste_module.MIN_NOTE_WRAP > 0, (
        "the wrap floor is not positive, so a control that measures nothing "
        "produces a width wx.StaticText reads as 'do not wrap'"
    )

    class MeasuresNothing:
        def CalcMin(self) -> Any:  # noqa: N802 - wx API spelling
            return wx.Size(0, 0)

    class RefusesToMeasure:
        def CalcMin(self) -> Any:  # noqa: N802 - wx API spelling
            raise RuntimeError("this control cannot measure itself yet")

    class MeasuresNothingAtAll:
        pass

    for control in (MeasuresNothing(), RefusesToMeasure(), MeasuresNothingAtAll()):
        width = paste_module._control_width(control)
        assert width >= paste_module.MIN_NOTE_WRAP, (
            f"{type(control).__name__} produced a wrap width of {width}, below "
            f"the {paste_module.MIN_NOTE_WRAP}px floor"
        )
        assert width > 0, (
            f"{type(control).__name__} produced a wrap width of {width}, which "
            "wx.StaticText reads as 'do not wrap'"
        )


def test_the_note_wraps_instead_of_widening_the_panel(panel) -> None:
    """A built note stays inside the width it was given.

    ``PasteTool._resize`` sizes that panel to its own best size, so an
    unwrapped sentence would not be a caption under the boxes -- it would make
    the whole panel as wide as the sentence and push the viewport's own
    controls off the edge of the canvas.
    """
    location = paste_module.TupleIntInput(panel, "x", "y", "z")
    panel.GetSizer().Add(location, 0, wx.EXPAND)
    width = paste_module._control_width(location)

    note = wx.StaticText(panel, label=lang.get(NOTE_KEY))
    note.Wrap(width)
    panel.GetSizer().Add(note, 0, wx.ALL, 5)
    panel.GetParent().Layout()
    wx.Yield()

    size = note.GetSize()
    assert (
        size.GetHeight() > 0 and size.GetWidth() > 0
    ), "the note measured as nothing, so it is not on the panel at all"
    assert size.GetWidth() <= width + 40, (
        f"the note is {size.GetWidth()}px wide against a wrap width of "
        f"{width}px, so it did not wrap and the panel will be as wide as the "
        "sentence"
    )
    assert size.GetHeight() > note.GetCharHeight(), (
        "the note is a single line, so it was not wrapped; on the real panel "
        "that is what widens the whole thing"
    )
