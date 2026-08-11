"""A declarative surface must open big enough to read.

Every Studio surface is a header, a scrolling body and a footer, and the window
sized itself by asking *itself* for a best size.  A ``wx.ScrolledWindow``
answers that question with the size of the hole, not of what is inside it: the
body of the Key Select window measured **16 pixels** while holding **790**.  So
the sum came to less than the 280-pixel floor every time, and every surface in
the application opened at that floor no matter how much it had to show -- the
Key Select window arrived with a 113-pixel viewport over nineteen key rows, one
of which fitted.  Nothing was lost, because the body scrolls; it just could not
be read without scrolling it, in a window three quarters chrome.

This is a runtime test on purpose.  The defect is arithmetic over measurements
that only exist once wx has laid the window out, and no reading of the source
can see it: the code that produced a 113-pixel viewport is a plausible three
lines that mention both a floor and a ceiling.
"""

from __future__ import annotations

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.api.studio import specs as spec_registry  # noqa: E402
from amulet_map_editor.api.studio import tokens  # noqa: E402
from amulet_map_editor.api.studio.spec_dialog import (  # noqa: E402
    MAX_DIALOG_HEIGHT,
    SpecDialog,
)

#: Surfaces that carry enough content to have something to be too small for.
#: Named rather than discovered: a rule that measured "every surface with more
#: content than viewport" would be satisfied by a registry that had lost them.
TALL_SURFACES = ("controls", "history", "docs")


@pytest.fixture(scope="module")
def host():
    app = wx.App.Get() or wx.App()
    frame = wx.Frame(None, size=(1400, 1000))
    frame.Show()
    try:
        yield frame
    finally:
        frame.Destroy()
        wx.Yield()
        del app


def _open(host, key: str) -> SpecDialog:
    spec = spec_registry.get(key)
    assert spec is not None, f"the {key!r} surface is no longer registered"
    dialog = SpecDialog(host, spec)
    dialog.Show()
    wx.Yield()
    return dialog


def _allowed_height(dialog: SpecDialog) -> int:
    """The tallest this window may open: its own ceiling, or the display's."""
    ceiling = tokens.scaled(MAX_DIALOG_HEIGHT)
    try:
        index = wx.Display.GetFromWindow(dialog)
        area = wx.Display(index if index != wx.NOT_FOUND else 0).GetClientArea()
        return min(ceiling, area.height - tokens.scaled(48))
    except Exception:  # pragma: no cover - platform boundary
        return ceiling


@pytest.mark.parametrize("key", TALL_SURFACES)
def test_a_surface_opens_showing_most_of_what_it_has(host, key: str) -> None:
    """Either the body fits, or the window is as tall as it is allowed to be.

    Stated that way rather than as a pixel count, because the honest complaint
    is not "the viewport is small" -- a surface with more content than any
    window may show has to scroll -- it is that the window did not even try.
    """
    dialog = _open(host, key)
    try:
        content = dialog.body.GetVirtualSize().height
        viewport = dialog.body.GetSize().height
        assert content > 0, f"{key}: the body reports no content to measure"
        allowed = _allowed_height(dialog)
        height = dialog.GetClientSize().height
        assert viewport >= content or height >= allowed, (
            f"{key}: the window opened {height}px tall with a {viewport}px "
            f"viewport over {content}px of content, while it was allowed "
            f"{allowed}px -- the floor-sized window the scrolling body used "
            "to hide behind"
        )
    finally:
        dialog.Destroy()
        wx.Yield()


def test_the_measurement_the_window_used_to_believe_is_still_wrong(host) -> None:
    """The precondition, without which the rule above proves nothing.

    If a dialog's own ``GetBestSize`` ever started accounting for its scrolled
    content, the assertion above would pass on the original code and stop
    guarding anything.  This states the fact the fix rests on, so the day it
    stops being true this file says so rather than going quietly green.
    """
    dialog = _open(host, "controls")
    try:
        content = dialog._body_content_height()
        best = dialog.GetBestSize().height
        assert content > 0, "the Key Select body measured no content at all"
        assert best < content, (
            "a dialog's own best size now accounts for its scrolled body "
            f"({best} against {content} of content), so the sizing rule above "
            "no longer proves anything"
        )
    finally:
        dialog.Destroy()
        wx.Yield()


def test_the_eyebrow_is_wide_enough_for_the_text_it_draws(host) -> None:
    """The same defect one control down: measured one way, drawn another.

    The category caption above every surface title is measured with a plain
    ``wx.ClientDC`` and painted through a ``wx.GCDC``, which lays glyphs out on
    fractional advances and comes out wider.  "KEY CONFIGURATION" measured 129
    pixels, drew 134, and was given 131 -- so the final N was drawn with its
    right-hand stroke sliced off, on every surface whose category was long
    enough for two pixels of padding not to cover it.

    Measured here against the drawing path rather than against a number, so it
    keeps meaning the same thing on a host with different fonts.
    """
    from amulet_map_editor.api.studio import widgets

    narrow = []
    for key in TALL_SURFACES:
        dialog = _open(host, key)
        try:
            eyebrow = dialog.eyebrow
            text = eyebrow.text.upper()
            if not text:
                continue
            dc = wx.ClientDC(eyebrow)
            gauge = wx.GCDC(dc)
            gauge.SetFont(eyebrow._font())
            needed = widgets.tracked_width(gauge, text, tokens.scaled(eyebrow.TRACKING))
            del gauge
            if eyebrow.GetSize().width < needed:
                narrow.append(
                    f"{key}: {eyebrow.GetSize().width}px for {needed}px " f"of {text!r}"
                )
        finally:
            dialog.Destroy()
            wx.Yield()
    assert not narrow, (
        "these surface captions are drawn wider than the control they are "
        f"drawn in, so their last letter is clipped: {narrow}"
    )


def test_a_small_surface_still_gets_the_floor(host) -> None:
    """Growing to fit content must not shrink a window with little of it."""
    dialog = _open(host, "controls")
    try:
        floor = tokens.scaled(280)
        assert dialog.GetClientSize().height >= floor, (
            "the window opened smaller than the floor every surface is "
            f"guaranteed: {dialog.GetClientSize().height} < {floor}"
        )
        assert dialog.GetClientSize().height <= tokens.scaled(MAX_DIALOG_HEIGHT), (
            "the window grew past the ceiling its body is supposed to start "
            f"scrolling at: {dialog.GetClientSize().height}"
        )
    finally:
        dialog.Destroy()
        wx.Yield()
