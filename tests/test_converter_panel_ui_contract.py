"""Drive the converter panel for real, and read the captured PNG.

Source text can prove the widgets exist; it proves nothing about whether the
source picker actually detects a real file's bytes, whether the target list
is actually populated from the registry, or whether the panel paints
anything at all. This builds the real panel in a real ``wx.Frame``, feeds it
genuinely crafted files (a real gzip-NBT structure, a real PNG, and a file
whose extension lies about its bytes), and captures the composited result.
"""

from __future__ import annotations

import gzip
import io
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

import amulet_nbt as nbt  # noqa: E402

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
    os.environ.setdefault("CONFIG_DIR", tempfile.mkdtemp(prefix="amulet-converter-ui-"))
    win = wx.Frame(None, size=(720, 900))
    win.Show()
    yield win
    win.Destroy()


def _write_gzip_nbt(path: str) -> None:
    tag = nbt.CompoundTag(
        {"Name": nbt.StringTag("Andyville"), "Height": nbt.IntTag(64)}
    )
    named = nbt.NamedTag(tag, "root")
    buf = io.BytesIO()
    named.save_to(buf, compressed=True)
    with open(path, "wb") as fp:
        fp.write(buf.getvalue())


def _write_png(path: str) -> None:
    from PIL import Image

    Image.new("RGBA", (4, 4), (5, 10, 15, 255)).save(path, format="PNG")


def test_panel_constructs_and_paints(frame, tmp_path):
    panel = ConverterPanel(frame)
    frame.Layout()
    wx.SafeYield()

    out_path = tmp_path / "converter_panel.png"
    report = capture_composite(panel, str(out_path))
    assert out_path.exists()
    assert out_path.stat().st_size > 0
    assert report["descendants"] > 5
    assert report["uniform_fraction"] < 0.98


def test_choosing_a_real_structure_file_detects_it_and_offers_only_real_targets(
    frame, tmp_path
):
    panel = ConverterPanel(frame)
    source = tmp_path / "hub.mcstructure"
    _write_gzip_nbt(str(source))

    panel.source_field.field.set_value(str(source), notify=True)
    wx.SafeYield()

    assert panel._detected_format == "gzip_nbt"
    assert "Compressed NBT" in panel.detected_label.GetLabel()
    offered = set(panel.target_choice.options)
    assert offered  # a real adapter exists for gzip_nbt
    assert all("json" in name.lower() for name in offered)


def test_extension_lying_about_bytes_offers_no_json_target(frame, tmp_path):
    panel = ConverterPanel(frame)
    lying = tmp_path / "not_really.json"
    _write_png(str(lying))

    panel.source_field.field.set_value(str(lying), notify=True)
    wx.SafeYield()

    assert panel._detected_format == "png"
    offered = panel.target_choice.options
    assert offered
    assert all("json" not in name.lower() for name in offered)
    assert all("→" in name for name in offered)


def test_end_to_end_conversion_through_the_panel_writes_real_output(frame, tmp_path):
    panel = ConverterPanel(frame)
    source = tmp_path / "hub.mcstructure"
    _write_gzip_nbt(str(source))
    dest = tmp_path / "hub.json"

    panel.source_field.field.set_value(str(source), notify=True)
    wx.SafeYield()
    panel.destination_field.field.set_value(str(dest), notify=True)
    panel._on_convert_now()

    assert dest.exists()
    assert b"Andyville" in dest.read_bytes()
    assert len(panel._results) == 1
    assert panel._results[0].outcome.value == "converted"


def test_unsupported_pairing_leaves_no_targets_and_no_crash(frame, tmp_path):
    panel = ConverterPanel(frame)
    mystery = tmp_path / "mystery.bin"
    mystery.write_bytes(b"\x00\x01\x02 not a recognised format")

    panel.source_field.field.set_value(str(mystery), notify=True)
    wx.SafeYield()

    assert panel._detected_format is None
    assert panel.target_choice.options == []
    assert "unrecognised" in panel.detected_label.GetLabel().lower()
