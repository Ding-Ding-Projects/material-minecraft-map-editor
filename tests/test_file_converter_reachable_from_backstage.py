"""The file converter must actually be reachable from the application shell.

A converter package and a fully built panel are not a delivered feature if
nothing in the running application ever routes to them. This constructs the
real :class:`BackstageView`, drives its rail exactly as a user's click would
(``set_tab``), and asserts the real :class:`ConverterPanel` is present in the
built page -- not a stub, not a placeholder card describing it.
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import amulet_map_editor  # noqa: E402

assert amulet_map_editor.__file__.startswith(REPO)

from amulet_map_editor.api.studio.backstage import BackstageView  # noqa: E402
from amulet_map_editor.api.studio.converter_panel import ConverterPanel  # noqa: E402
from scripts.capture_surface import capture_composite  # noqa: E402


@pytest.fixture(scope="module")
def app():
    existing = wx.App.Get()
    created = existing is None and wx.App()
    yield existing or created
    if created:
        created.Destroy()


@pytest.fixture
def frame(app):
    os.environ.setdefault(
        "CONFIG_DIR", tempfile.mkdtemp(prefix="amulet-file-convert-reach-")
    )
    win = wx.Frame(None, size=(1100, 900))
    win.Show()
    yield win
    win.Destroy()


def _find_converter_panel(window: wx.Window):
    if isinstance(window, ConverterPanel):
        return window
    for child in window.GetChildren():
        found = _find_converter_panel(child)
        if found is not None:
            return found
    return None


def test_rail_offers_a_file_converter_destination(frame):
    view = BackstageView(frame)
    frame.Layout()
    wx.SafeYield()
    assert "file_convert" in view._rail_buttons


def test_selecting_the_rail_item_builds_the_real_converter_panel(frame, tmp_path):
    view = BackstageView(frame)
    frame.Layout()
    wx.SafeYield()

    view.set_tab("file_convert")
    frame.Layout()
    wx.SafeYield()

    assert view.tab == "file_convert"
    panel = _find_converter_panel(view)
    assert panel is not None, "the rail's File converter destination built no real ConverterPanel"

    out_path = tmp_path / "backstage_file_convert.png"
    report = capture_composite(view, str(out_path))
    assert out_path.exists()
    assert out_path.stat().st_size > 0
    assert report["descendants"] > 10
    assert report["uniform_fraction"] < 0.98
