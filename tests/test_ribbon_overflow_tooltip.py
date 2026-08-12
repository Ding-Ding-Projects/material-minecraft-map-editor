"""The overflow "More" tab and any tab pulled into it must not leave a
stranded native tooltip behind.

Hiding a control does not ask Windows to close its tooltip popup -- that only
happens on a real mouse-leave, which never fires when the control disappears
out from under a stationary pointer.  A window resize that makes the ribbon
wide enough for every tab to fit again hides the "More" button exactly like
that: hover it, then widen the window, and the "Show the ribbon tabs that do
not fit at this width" tooltip has nothing left to explain and no control
left to belong to.

This drives the real ``_TabStrip.relayout`` and asserts on the actual escape
hatch it now reaches for -- ``wx.ToolTip.Enable`` toggled off and back on --
rather than reading source text: a relayout that merely calls ``Hide()``
looks identical in a diff to one that also dismisses the popup.
"""

from __future__ import annotations

import os
import tempfile
from typing import List

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.api.studio import ribbon  # noqa: E402

OFFSCREEN = wx.Point(-32000, -32000)


@pytest.fixture(scope="module")
def app():
    os.environ["CONFIG_DIR"] = tempfile.mkdtemp(prefix="amulet-ribbon-tooltip-")
    existing = wx.App.Get()
    created = existing is None and wx.App()
    yield existing or created
    if created:
        created.Destroy()


@pytest.fixture
def profile(app, tmp_path):
    previous = os.environ.get("CONFIG_DIR")
    os.environ["CONFIG_DIR"] = str(tmp_path)
    try:
        yield str(tmp_path)
    finally:
        if previous is None:
            os.environ.pop("CONFIG_DIR", None)
        else:
            os.environ["CONFIG_DIR"] = previous


def build_bar(width: int) -> "tuple[wx.Frame, ribbon.RibbonBar]":
    frame = wx.Frame(None, pos=OFFSCREEN, size=wx.Size(width, 140))
    bar = ribbon.RibbonBar(frame)
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(bar, 0, wx.EXPAND)
    frame.SetSizer(sizer)
    frame.Show()
    frame.Layout()
    wx.Yield()
    return frame, bar


def test_widening_past_overflow_dismisses_the_stray_tooltip(profile) -> None:
    """Hover the More button, widen the window until it hides, and watch the
    fix reach for the native-tooltip escape hatch rather than only Hide()."""
    frame, bar = build_bar(520)
    try:
        strip = bar.strip
        assert strip.overflow.IsShownOnScreen(), (
            "The narrow window did not overflow any tabs, so hiding the "
            "'More' button below would prove nothing."
        )

        calls: List[bool] = []
        original = ribbon._TabStrip.__dict__["_dismiss_stray_tooltip"].__func__
        ribbon._TabStrip._dismiss_stray_tooltip = staticmethod(
            lambda: calls.append(True) or original()
        )
        try:
            frame.SetSize(wx.Size(2200, 140))
            frame.Layout()
            wx.Yield()

            assert not strip.overflow.IsShownOnScreen(), (
                "The window is now wide enough for every tab, so the 'More' "
                "button should have hidden itself."
            )
            assert calls, (
                "The 'More' button was hidden while it could plausibly still "
                "be under the pointer, but nothing dismissed its stray "
                "native tooltip."
            )
        finally:
            ribbon._TabStrip._dismiss_stray_tooltip = staticmethod(original)
    finally:
        frame.Destroy()


def test_a_relayout_that_changes_nothing_does_not_touch_the_tooltip(profile) -> None:
    """The fix must not fire on every resize, only on an actual hide."""
    frame, bar = build_bar(2200)
    try:
        strip = bar.strip
        assert not strip.overflow.IsShownOnScreen(), (
            "The wide window already overflowed a tab, so the steady-state "
            "resize below would prove nothing."
        )

        calls: List[bool] = []
        original = ribbon._TabStrip.__dict__["_dismiss_stray_tooltip"].__func__
        ribbon._TabStrip._dismiss_stray_tooltip = staticmethod(
            lambda: calls.append(True) or original()
        )
        try:
            frame.SetSize(wx.Size(2210, 140))
            frame.Layout()
            wx.Yield()
            assert not calls, (
                "A resize that changed nothing about what is shown still "
                "reached for the tooltip-dismissal escape hatch."
            )
        finally:
            ribbon._TabStrip._dismiss_stray_tooltip = staticmethod(original)
    finally:
        frame.Destroy()


def test_pulling_a_visible_tab_into_overflow_also_dismisses_the_tooltip(
    profile,
) -> None:
    """Shrinking the window can hide the exact tab the pointer sits on."""
    frame, bar = build_bar(2200)
    try:
        strip = bar.strip
        assert not strip._overflowed, (
            "Every tab already fits at this width, so shrinking below would "
            "not pull anything new into overflow."
        )

        calls: List[bool] = []
        original = ribbon._TabStrip.__dict__["_dismiss_stray_tooltip"].__func__
        ribbon._TabStrip._dismiss_stray_tooltip = staticmethod(
            lambda: calls.append(True) or original()
        )
        try:
            frame.SetSize(wx.Size(520, 140))
            frame.Layout()
            wx.Yield()

            assert strip._overflowed, (
                "The narrow window did not push any tab into overflow, so "
                "this proves nothing about a tab disappearing."
            )
            assert calls, (
                "A tab was hidden into overflow but nothing dismissed a "
                "tooltip that could have been showing for it."
            )
        finally:
            ribbon._TabStrip._dismiss_stray_tooltip = staticmethod(original)
    finally:
        frame.Destroy()
