"""Runtime evidence for every Amulet Studio surface.

Every other UI test in this suite reads source files as text. That is a real
guard against a specific line regressing, but it observes nothing: with wxPython
made unimportable the entire suite returns byte-identical results, so no test
here has ever seen the application render. This file is the exception. It builds
each surface for real and asks the constructed objects four questions that no
grep over source can answer:

    1. does it draw anything at all, or is it a blank panel
    2. is anything laid out outside the window that is supposed to contain it
    3. does every interactive control carry an accessible name
    4. is every control actually parented and given a size, rather than
       constructed and then never added to a sizer

A control that is built and never added to a sizer greps perfectly and renders
as an invisible or stacked widget, which is exactly the failure the source tests
cannot see.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys


import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.api.studio import specs as spec_registry  # noqa: E402
from amulet_map_editor.api.studio.spec_dialog import SpecDialog  # noqa: E402

#: Controls a user can operate. Static text and bare panels are excluded: they
#: are structure, and demanding an accessible name from every one of them would
#: produce noise rather than findings.
INTERACTIVE = (
    wx.Button,
    wx.BitmapButton,
    wx.CheckBox,
    wx.Choice,
    wx.ComboBox,
    wx.ListBox,
    wx.RadioButton,
    wx.Slider,
    wx.SpinCtrl,
    wx.TextCtrl,
    wx.ToggleButton,
    wx.SearchCtrl,
)

#: wx hands out these as default names, so finding one means nobody set a real
#: accessible name -- it is the same as having none.
GENERIC_NAMES = frozenset(
    {
        "",
        "panel",
        "button",
        "check",
        "checkbox",
        "choice",
        "combobox",
        "control",
        "dialog",
        "frame",
        "listbox",
        "radiobutton",
        "searchctrl",
        "slider",
        "spinctrl",
        "text",
        "textctrl",
        "togglebutton",
        "staticbox",
        "window",
    }
)

#: The offscreen corner the host frame lives at, so a developer who runs this on
#: a visible desktop never gets 111 dialogs flashing across their screen.
OFFSCREEN = (-32000, -32000)

ROOT = pathlib.Path(__file__).resolve().parents[1]

SURFACE_KEYS = spec_registry.keys()


def test_the_registry_actually_loaded_every_family():
    """A silently empty registry would make every parametrised case vacuous."""
    assert spec_registry.UNAVAILABLE_MODULES == (), (
        "spec families failed to import: " f"{spec_registry.UNAVAILABLE_MODULES}"
    )
    assert len(SURFACE_KEYS) > 100, f"only {len(SURFACE_KEYS)} surfaces registered"


@pytest.fixture(scope="module")
def app():
    try:
        instance = wx.App(False)
    except Exception as error:  # pragma: no cover - depends on the host
        pytest.skip(f"wx.App could not start on this host: {error!r}")
    yield instance
    instance.Destroy()


@pytest.fixture(scope="module")
def host(app):
    frame = wx.Frame(None, title="studio runtime contract", pos=OFFSCREEN)
    frame.Show()
    wx.Yield()
    yield frame
    frame.Destroy()
    wx.Yield()


def _descendants(window):
    for child in window.GetChildren():
        yield child
        for deeper in _descendants(child):
            yield deeper


def _accessible_name(control):
    name = (control.GetName() or "").strip()
    if name and name.lower() not in GENERIC_NAMES:
        return name
    label = ""
    if hasattr(control, "GetLabel"):
        label = (control.GetLabel() or "").strip()
    if label:
        return label
    hint = ""
    if hasattr(control, "GetHint"):
        try:
            hint = (control.GetHint() or "").strip()
        except Exception:
            hint = ""
    return hint


def _uniform(bitmap):
    """Return True when every pixel is the same colour, i.e. nothing drew."""
    image = bitmap.ConvertToImage()
    data = image.GetData()
    if not data:
        return True
    first = data[0:3]
    # Comparing the whole buffer against a repeat of its first pixel is far
    # faster than walking it, and a surface that drew anything at all fails it.
    return data == first * (len(data) // 3)


def _grab(window):
    """Return a bitmap of the window, or None when this host cannot grab one."""
    size = window.GetClientSize()
    if size.width <= 0 or size.height <= 0:
        return None
    try:
        bitmap = wx.Bitmap(size.width, size.height)
        source = wx.ClientDC(window)
        memory = wx.MemoryDC(bitmap)
        memory.Blit(0, 0, size.width, size.height, source, 0, 0)
        memory.SelectObject(wx.NullBitmap)
        return bitmap if bitmap.IsOk() else None
    except Exception:
        return None


_GRABBED = {"count": 0}


@pytest.fixture
def surface(host, request):
    key = request.param
    spec = spec_registry.get(key)
    assert spec is not None, f"surface {key!r} vanished from the registry"
    dialog = SpecDialog(host, spec)
    dialog.Layout()
    dialog.Show()
    wx.Yield()
    try:
        yield key, dialog
    finally:
        dialog.Hide()
        dialog.Destroy()
        wx.Yield()


def _parametrise(func):
    return pytest.mark.parametrize("surface", SURFACE_KEYS, indirect=True)(func)


@_parametrise
def test_surface_renders_something(surface):
    key, dialog = surface
    size = dialog.GetClientSize()
    assert size.width > 0 and size.height > 0, f"{key}: client area is {size}"

    shown = [c for c in _descendants(dialog) if c.IsShown()]
    assert shown, f"{key}: the window contains no visible child at all"

    bitmap = _grab(dialog)
    if bitmap is None:
        pytest.skip(f"{key}: this host cannot grab a client bitmap")
    _GRABBED["count"] += 1
    assert not _uniform(
        bitmap
    ), f"{key}: every pixel is the same colour -- the surface rendered blank"


def _containing_area(parent):
    """The box a child must fit inside, which is not always the viewport.

    A scrolling parent is supposed to hold content larger than its client area
    -- that is what scrolling is. Measuring against the client size instead of
    the virtual size reports every scrolled surface as clipped, which is a
    false alarm on a scale that would bury a real one.
    """
    if isinstance(parent, wx.ScrolledWindow):
        virtual = parent.GetVirtualSize()
        client = parent.GetClientSize()
        return wx.Size(
            max(virtual.width, client.width), max(virtual.height, client.height)
        )
    return parent.GetClientSize()


@_parametrise
def test_surface_lays_every_control_inside_its_parent(surface):
    key, dialog = surface
    clipped = []
    for child in _descendants(dialog):
        if not child.IsShown():
            continue
        parent = child.GetParent()
        if parent is None:
            continue
        area = _containing_area(parent)
        rect = child.GetRect()
        if area.width <= 0 or area.height <= 0:
            continue
        # One pixel of tolerance: a border drawn on the boundary is not clipping.
        if (
            rect.x < -1
            or rect.y < -1
            or rect.right > area.width + 1
            or rect.bottom > area.height + 1
        ):
            clipped.append(
                f"{type(child).__name__}({_accessible_name(child) or '?'}) "
                f"at {tuple(rect)} outside parent client {tuple(area)}"
            )
    assert not clipped, (
        f"{key}: {len(clipped)} control(s) laid out outside their parent:\n"
        + "\n".join("  " + line for line in clipped[:12])
    )


@_parametrise
def test_every_interactive_control_has_an_accessible_name(surface):
    key, dialog = surface
    unnamed = [
        type(child).__name__
        for child in _descendants(dialog)
        if isinstance(child, INTERACTIVE)
        and child.IsShown()
        and not _accessible_name(child)
    ]
    assert not unnamed, (
        f"{key}: {len(unnamed)} interactive control(s) carry no accessible name: "
        f"{sorted(set(unnamed))}"
    )


@_parametrise
def test_no_control_is_built_and_then_never_laid_out(surface):
    key, dialog = surface
    stranded = []
    stacked = {}
    for child in _descendants(dialog):
        if not child.IsShown():
            continue
        rect = child.GetRect()
        if rect.width <= 0 or rect.height <= 0:
            stranded.append(
                f"{type(child).__name__} has size {rect.width}x{rect.height}"
            )
            continue
        # Several visible siblings pinned at the same origin is the signature of
        # controls that were constructed but never added to a sizer.
        origin = (id(child.GetParent()), rect.x, rect.y)
        stacked.setdefault(origin, []).append(type(child).__name__)

    piles = [names for names in stacked.values() if len(names) > 1]
    assert not stranded, f"{key}: control(s) with no allocated size:\n" + "\n".join(
        "  " + line for line in stranded[:12]
    )
    assert not piles, (
        f"{key}: {len(piles)} group(s) of visible siblings share an exact origin, "
        f"which is what an un-sized control looks like: {piles[:6]}"
    )


#: Run in a child interpreter, one pass over every surface, reporting which ones
#: raised while painting. It has to be a child for two reasons that each make an
#: in-process version silently useless: under pytest ``sys.stderr`` is already
#: pytest's own buffer, so wx's traceback never reaches file descriptor 2 and a
#: dup2 capture returns empty no matter how broken the paint path is -- verified
#: by reinstating the real defect and watching the in-process check still pass.
#: And a paint handler that fails can destabilise GDI badly enough to take the
#: interpreter down, which in a child fails one test instead of the whole run.
_PAINT_CHILD = r"""
import json, os, sys, tempfile
import wx
from amulet_map_editor.api.studio import specs as registry
from amulet_map_editor.api.studio.spec_dialog import SpecDialog

app = wx.App(False)
host = wx.Frame(None, pos=(-32000, -32000))
host.Show()
wx.Yield()

noisy = {}
for key in registry.keys():
    stream = tempfile.TemporaryFile(mode="w+")
    saved = os.dup(2)
    os.dup2(stream.fileno(), 2)
    dialog = None
    try:
        dialog = SpecDialog(host, registry.get(key))
        dialog.Layout()
        dialog.Show()
        wx.Yield()
        dialog.Refresh()
        dialog.Update()
        wx.Yield()
    finally:
        if dialog is not None:
            dialog.Hide()
            dialog.Destroy()
            wx.Yield()
        os.dup2(saved, 2)
        os.close(saved)
    stream.seek(0)
    text = stream.read()
    stream.close()
    if "Traceback" in text:
        noisy[key] = text[:1500]

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(noisy, handle)
"""


@pytest.fixture(scope="module")
def paint_report(app, tmp_path_factory):
    """Map of surface key -> captured traceback, for surfaces that failed to paint."""
    report = tmp_path_factory.mktemp("paint") / "report.json"
    completed = subprocess.run(
        [sys.executable, "-c", _PAINT_CHILD, str(report)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if not report.exists():
        pytest.fail(
            "the paint probe produced no report, so this check ran on nothing.\n"
            f"exit={completed.returncode}\nstderr:\n{completed.stderr[-2000:]}"
        )
    return json.loads(report.read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", SURFACE_KEYS)
def test_no_paint_handler_raises(paint_report, key):
    """A paint handler that throws leaves a blank control and a green suite.

    wx catches the exception, prints the traceback, and carries on drawing
    nothing -- so the window keeps a non-uniform bitmap from its native children
    and every structural assertion above still passes. This is the check that
    caught an entire interface rendering as flat grey rectangles while 387 other
    tests stayed green, and it is worth its awkwardness.
    """
    noise = paint_report.get(key)
    assert not noise, (
        f"{key}: a handler raised while the surface was painting -- the control "
        f"draws nothing and no source-reading test can see it:\n{noise}"
    )


def test_the_bitmap_check_was_not_inert():
    """A skipped grab on every surface would make the blank-panel test a no-op."""
    if not SURFACE_KEYS:
        pytest.skip("no surfaces registered")
    assert _GRABBED["count"] > 0, (
        "no surface produced a client bitmap, so the blank-render assertion "
        "never actually ran on this host"
    )
