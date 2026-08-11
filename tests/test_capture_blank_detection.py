"""A capture whose health fields are clean can still be an empty picture.

``capture_composite`` reports ``skipped`` and ``blitted_leaves``, and both can
only ever name a window that *said* it could not draw.  A drawing route that
returns success over an empty rectangle leaves both lists empty, so a report
reading ``skipped: []`` and ``blitted_leaves: []`` says nothing whatever about
whether the file shows the interface.

That is not a hypothetical.  Compositing the viewport that hosts the 3D canvas
returns ``descendants: 37``, ``routes: {render: 12, print: 25, blit: 0}``,
``skipped: []`` and ``blitted_leaves: []`` -- every structural field healthy --
next to a PNG that is one flat grey rectangle with none of the 25 printed
controls anywhere in it.  ``uniform_fraction`` is the field that can see it, and
this module is what stops that field quietly becoming a constant.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import capture_surface  # noqa: E402

#: Off-screen, so a run on a visible desktop never throws a window at anybody.
OFFSCREEN = (-32000, -32000)


@pytest.fixture(scope="module")
def app():
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


def _frame() -> wx.Frame:
    """A frame with room to spare.

    Deliberately larger than the content needs.  A frame's client area is
    smaller than the size it is asked for by whatever its border and caption
    take, so a frame sized to fit exactly leaves the last child of a sizer with
    a height of zero -- and a child of no height does not composite, which
    reads as the capture losing it.
    """
    frame = wx.Frame(None, size=wx.Size(320, 320))
    frame.SetPosition(wx.Point(*OFFSCREEN))
    return frame


def test_a_flat_surface_reads_as_entirely_uniform(app) -> None:
    """One colour edge to edge is ``1.0``, which is the alarm value."""
    frame = _frame()
    panel = wx.Panel(frame)
    panel.SetBackgroundColour(wx.Colour(200, 200, 200))
    frame.Show()
    capture_surface.settle(frame)
    image, *_ = capture_surface._composite(panel)
    assert capture_surface._uniform_fraction(image) == pytest.approx(1.0)
    frame.Destroy()


def test_a_surface_with_real_content_is_not_uniform(app) -> None:
    """The other half, without which the measurement could be a constant.

    A check that only ever confirms ``1.0`` on a blank surface would pass just
    as happily on a function that returned ``1.0`` for everything, and would
    then report every real capture as empty.
    """
    frame = _frame()
    panel = wx.Panel(frame)
    panel.SetBackgroundColour(wx.Colour(200, 200, 200))
    sizer = wx.BoxSizer(wx.VERTICAL)
    for colour in ((220, 20, 20), (20, 220, 20), (20, 20, 220), (250, 250, 10)):
        block = wx.Panel(panel, size=wx.Size(200, 30))
        block.SetBackgroundColour(wx.Colour(*colour))
        sizer.Add(block, 1, wx.EXPAND)
    panel.SetSizer(sizer)
    panel.Layout()
    frame.Show()
    capture_surface.settle(frame)
    image, contributed, *_ = capture_surface._composite(panel)
    assert contributed >= 4, "the blocks did not composite, so nothing is proven"
    fraction = capture_surface._uniform_fraction(image)
    assert fraction < 0.5, (
        "four equal bands of four different colours read as "
        f"{fraction:.3f} of one colour, so the measurement cannot tell a full "
        "picture from an empty one"
    )
    frame.Destroy()


def test_the_report_carries_the_measurement(app, tmp_path) -> None:
    """It has to reach the report, or nobody reading a run can use it.

    The field is the whole point: the structural fields were already clean on
    the capture that started this, so a measurement that stayed inside the
    module would have changed nothing about what that run reported.
    """
    frame = _frame()
    panel = wx.Panel(frame)
    panel.SetBackgroundColour(wx.Colour(200, 200, 200))
    child = wx.Panel(panel, size=wx.Size(80, 40))
    child.SetBackgroundColour(wx.Colour(10, 90, 200))
    frame.Show()
    capture_surface.settle(frame)
    report = capture_surface.capture_composite(
        panel, tmp_path / "surface.png", require_content=False
    )
    assert (
        "uniform_fraction" in report
    ), f"the report does not carry the blankness measurement: {sorted(report)}"
    assert 0.0 <= report["uniform_fraction"] <= 1.0
    assert report["uniform_fraction"] < 1.0, (
        "a surface with a differently coloured child on it reports as one flat "
        f"colour: {report}"
    )
    frame.Destroy()
