#!/usr/bin/env python3
"""Capture a wx window by asking each widget to draw, on a desktop or without one.

A screenshot matrix for this interface has to run on a hidden desktop, and the
two obvious routes both fail there for owner-drawn controls:

``wx.ClientDC`` *reads* a window's on-screen surface.  On a named off-screen
desktop nothing is ever composited, so there is nothing to read and the copy
comes back as whatever was in the buffer -- which is how two separate runs
produced about 130 files each that passed every numeric check and were entirely
blank.  A colour count cannot tell you the interface drew.

``PrintWindow`` with ``PW_RENDERFULLCONTENT`` does the opposite: it *asks* the
window to draw, which works whether or not anyone is looking.  Native controls
answer it, so search fields, checkboxes and table headers come back.  A widget
that paints in its own ``EVT_PAINT`` handler does not answer ``WM_PRINT``, so
every Studio button, chip, card, ribbon tile and section label stayed missing --
and the whole of this interface is owner-drawn.

The route that works asks neither the desktop nor the operating system.  Every
painted Studio widget exposes ``render_to(dc, rect)``, which is its ``EVT_PAINT``
drawing made callable, so a capture invokes it against its own bitmap and
depends on no compositor and no Win32 message at all.  It is tried first here;
``PrintWindow`` stays for the native controls that genuinely have no
``render_to``, and the device-context read stays last for platforms without
either.

Use :func:`capture_window` or :func:`capture_composite` from inside the
application process, after the window has been shown and the event loop has run
at least once.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
from pathlib import Path
from typing import Optional

import wx

log = logging.getLogger(__name__)

_IS_WINDOWS = os.name == "nt"
_user32 = ctypes.windll.user32 if _IS_WINDOWS else None

if _IS_WINDOWS:
    # Declare the handle types. Without this ctypes marshals a Python int as a
    # 32-bit C int, and an HWND or HDC on 64-bit Windows does not fit in one --
    # so the call arrives at a truncated handle, addresses nothing, and fails
    # in the one way that looks exactly like "this control cannot draw itself".
    # It is intermittent by nature: a handle whose value happens to fit works
    # fine, which is why some controls captured and others did not, in the same
    # run, with no pattern anyone could see.
    _user32.PrintWindow.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.wintypes.HDC,
        ctypes.wintypes.UINT,
    ]
    _user32.PrintWindow.restype = ctypes.wintypes.BOOL
    _user32.SendMessageW.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.wintypes.UINT,
        ctypes.wintypes.WPARAM,
        ctypes.wintypes.LPARAM,
    ]
    _user32.SendMessageW.restype = ctypes.c_void_p

#: A capture with fewer distinct colours than this is almost certainly blank.
#: It is a smoke threshold, not a quality bar: a real surface in this interface
#: returns dozens.
MIN_DISTINCT_COLOURS = 8


def _distinct_colours(image: wx.Image, step: int = 7) -> int:
    """Return how many distinct colours a coarse grid sample finds."""
    seen = set()
    for x in range(0, image.GetWidth(), step):
        for y in range(0, image.GetHeight(), step):
            seen.add((image.GetRed(x, y), image.GetGreen(x, y), image.GetBlue(x, y)))
    return len(seen)


def capture_window(
    window: wx.Window,
    path: str | Path,
    *,
    require_content: bool = True,
) -> int:
    """Write ``window``'s rendered client area to ``path`` as a PNG.

    Returns the number of distinct colours sampled, so a caller can record in
    its manifest that the capture had real content rather than asserting it did.
    Raises ``RuntimeError`` when ``require_content`` is set and the surface came
    back effectively blank, because a blank capture is worse than none: it looks
    like evidence.

    The window is composited with its descendants rather than drawn alone.  On
    Windows a child window is its own surface, so a container drawn by itself
    is only ever its own background -- ``PrintWindow`` used to paper over that
    by rendering a whole subtree at once, and ``render_to`` deliberately does
    not, because a widget's appearance is its own and not its children's.
    Compositing is what keeps a container capture meaning what its caller
    expects.
    """
    settle(window)
    image, _contributed, _routes, _skipped, _size, _blitted = _composite(window)
    colours = _distinct_colours(image)
    if require_content and colours < MIN_DISTINCT_COLOURS:
        raise RuntimeError(
            f"{window.GetName() or window!r} rendered {colours} distinct colours; "
            "the capture is blank and would misrepresent the interface"
        )

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not image.SaveFile(str(target), wx.BITMAP_TYPE_PNG):
        raise RuntimeError(f"Could not write the capture to {target}")
    log.info("captured %s (%d colours) to %s", window.GetName(), colours, target)
    return colours


def capture_top_level(
    window: wx.Window,
    path: str | Path,
    *,
    require_content: bool = True,
) -> int:
    """Capture the frame that owns ``window``, including its chrome."""
    top: Optional[wx.Window] = window.GetTopLevelParent()
    return capture_window(top or window, path, require_content=require_content)


def settle(window: wx.Window, *, passes: int = 6) -> None:
    """Lay out and repaint ``window`` until its tree has stopped moving.

    A capture taken one event-loop turn after a view is shown photographs a
    half-built tree: children exist and report their sizes, but nothing has
    painted yet, so the picture comes back as the container's background alone.
    That is not a rendering defect and it looks exactly like one -- it cost this
    project an afternoon of chasing a ribbon that was drawing perfectly.

    Several layout-and-paint passes are cheap and remove the whole class.
    """
    for _ in range(max(1, passes)):
        window.Layout()
        window.Refresh()
        window.Update()
        wx.Yield()
        wx.SafeYield()


#: ``PrintWindow`` flag that renders the window's full content, including
#: anything the desktop compositor would normally own.
PW_RENDERFULLCONTENT = 0x00000002


def _print_window(window: wx.Window, target: wx.MemoryDC, origin: wx.Point) -> bool:
    """Ask ``window`` to draw itself into ``target`` at ``origin``.

    ``wx.ClientDC`` *reads* a window's on-screen surface.  On a named off-screen
    desktop nothing is ever composited, so there is no surface to read and the
    copy comes back as whatever happened to be in the buffer -- which is how a
    capture run produced 139 files that passed every numeric check and were all
    blank.  ``PrintWindow`` does the opposite: it asks the window to render into
    a device context, which works whether or not anyone is looking at it.

    Returns whether the request succeeded, so the caller can fall back.
    """
    if not _IS_WINDOWS:
        return False
    size = window.GetClientSize()
    if size.width < 1 or size.height < 1:
        return False
    try:
        scratch = wx.Bitmap(size)
        scratch_dc = wx.MemoryDC(scratch)
        try:
            handle = window.GetHandle()
            printed = _user32.PrintWindow(
                handle, scratch_dc.GetHandle(), PW_RENDERFULLCONTENT
            )
        finally:
            scratch_dc.SelectObject(wx.NullBitmap)
        if not printed:
            return False
        target.DrawBitmap(scratch, origin.x, origin.y, True)
        return True
    except Exception:
        log.debug("PrintWindow failed for %s", window.GetName(), exc_info=True)
        return False


#: ``WM_PRINTCLIENT`` and the parts of itself a control should draw.
WM_PRINTCLIENT = 0x0318
PRF_CLIENT = 0x00000004
PRF_ERASEBKGND = 0x00000008
PRF_CHILDREN = 0x00000010


def _print_client(window: wx.Window, target: wx.MemoryDC, origin: wx.Point) -> bool:
    """Ask a native child control to draw itself with ``WM_PRINTCLIENT``.

    ``PrintWindow`` is documented for top-level windows and routinely returns
    zero for a child control, which is why every native ``StaticText``,
    ``TextCtrl``, ``CheckBox`` and ``Slider`` in this interface fell past it to
    the surface read and arrived blank.  Sending ``WM_PRINTCLIENT`` directly is
    the route that works on children: the control draws into the device context
    it is handed, with no compositor and no window ever being visible.

    This is the last route that asks the control anything.  Whatever is left
    after it genuinely cannot be photographed without putting the window on a
    screen.
    """
    if not _IS_WINDOWS:
        return False
    size = window.GetClientSize()
    if size.width < 1 or size.height < 1:
        return False
    try:
        scratch = wx.Bitmap(size)
        scratch_dc = wx.MemoryDC(scratch)
        try:
            # Fill first: a control that honours PRF_CLIENT but not
            # PRF_ERASEBKGND draws its text onto whatever the bitmap held,
            # which is uninitialised memory rather than a background.
            scratch_dc.SetBackground(wx.Brush(window.GetBackgroundColour()))
            scratch_dc.Clear()
            _user32.SendMessageW(
                window.GetHandle(),
                WM_PRINTCLIENT,
                scratch_dc.GetHandle(),
                PRF_CLIENT | PRF_ERASEBKGND | PRF_CHILDREN,
            )
        finally:
            scratch_dc.SelectObject(wx.NullBitmap)
        target.DrawBitmap(scratch, origin.x, origin.y, True)
        return True
    except Exception:
        log.debug("WM_PRINTCLIENT failed for %s", window.GetName(), exc_info=True)
        return False


def _render_to(window: wx.Window, target: wx.MemoryDC, origin: wx.Point) -> bool:
    """Ask ``window`` to draw its own appearance into ``target`` at ``origin``.

    Every owner-drawn Studio widget exposes ``render_to(dc, rect)``: the whole
    of its ``EVT_PAINT`` drawing, callable directly.  That is the only route
    here that depends on nothing outside this process -- no desktop, no
    compositor, no ``WM_PRINT``, no window handle -- which is exactly what a
    capture on a hidden desktop needs, and it is why it is tried first.

    The device context is wrapped in a ``wx.GCDC`` because that is what a paint
    handler hands the same code: unwrapped, every rounded corner, focus ring
    and elevation shadow would render stepped, and the capture would show a
    worse interface than the one that ships.

    Returns whether the widget drew, so a native control -- which has no
    ``render_to`` and needs one of the routes below -- falls through.
    """
    render = getattr(window, "render_to", None)
    if not callable(render):
        return False
    size = window.GetClientSize()
    if size.width < 1 or size.height < 1:
        return False
    try:
        wrapper: wx.DC = wx.GCDC(target)
    except TypeError:
        # Without the wrapper the drawing is still correct, only unantialiased.
        wrapper = target
    try:
        render(wrapper, wx.Rect(origin.x, origin.y, size.width, size.height))
    except Exception:
        log.debug("render_to failed for %s", window.GetName(), exc_info=True)
        return False
    finally:
        if wrapper is not target:
            del wrapper
    return True


def _render_via_paint(window: wx.Window, target: wx.MemoryDC, origin: wx.Point) -> bool:
    """Drive a widget's own ``EVT_PAINT`` handler into ``target``.

    The route above needs a widget to expose ``render_to``.  Most of this
    interface does not: it draws in an ``EVT_PAINT`` handler and has no second,
    callable copy of that drawing code.  Those widgets used to fall all the way
    through to the device-context read, which off-screen returns nothing, so
    they arrived in the file as white rectangles -- correct-looking captures
    with holes in them, and nothing in the report saying where.

    ``render_via_paint`` redirects the shared ``paint_context`` helper for the
    duration of one handler call, so the widget draws into the capture bitmap
    using the code it already has.  It is preferred over ``PrintWindow``
    because it depends on nothing outside this process.
    """
    size = window.GetClientSize()
    if size.width < 1 or size.height < 1:
        return False
    try:
        from amulet_map_editor.api.studio.widgets import render_via_paint
    except ImportError:
        return False
    return bool(
        render_via_paint(
            window, target, wx.Rect(origin.x, origin.y, size.width, size.height)
        )
    )


def _paint_into(window: wx.Window, target: wx.MemoryDC, origin: wx.Point) -> str:
    """Render one window into ``target`` at ``origin``.

    Three routes, in descending order of how much they have to trust the
    platform.  ``render_to`` asks the widget's own drawing code and trusts
    nothing else, so it is tried first and it is the one that works for every
    owner-drawn control.  ``PrintWindow`` asks the window to draw itself, which
    is what recovers the native controls -- search fields, checkboxes, table
    headers -- that have no ``render_to`` of their own.  The device-context
    read is last: it copies what is on screen, so on a hidden desktop, where
    nothing is composited, it returns the container's background and produces a
    file that passes every numeric check while showing nothing.

    Returns the name of the route that drew -- ``render``, ``print``, or
    ``blit`` -- or an empty string when none could, an OpenGL canvas being the
    case that matters, since its pixels live in the GL framebuffer rather than
    in any device context.  Naming the route rather than counting pixels is
    what lets a report distinguish a surface that drew from one that was
    copied off a desktop nobody composited.
    """
    size = window.GetClientSize()
    if size.width < 1 or size.height < 1:
        return ""
    if _render_to(window, target, origin):
        return "render"
    if _render_via_paint(window, target, origin):
        return "render"
    if _print_window(window, target, origin):
        return "print"
    if _print_client(window, target, origin):
        return "print"
    try:
        source = wx.ClientDC(window)
        target.Blit(origin.x, origin.y, size.width, size.height, source, 0, 0)
    except Exception:
        log.debug("Could not blit %s", window.GetName(), exc_info=True)
        return ""
    return "blit"


def _composite(
    window: wx.Window,
) -> tuple[wx.Image, int, dict, list, wx.Size, list]:
    """Draw ``window`` and every visible descendant into one image.

    Returns the image, how many descendants drew, how many took each route,
    which ones drew by no route at all, and the size everything was drawn at.
    Both public capture functions go through here so a container and a leaf are
    photographed by exactly the same code.
    """
    size = window.GetClientSize()
    if size.width < 1 or size.height < 1:
        raise RuntimeError(f"{window.GetName() or window!r} has no client area")

    bitmap = wx.Bitmap(size)
    memory = wx.MemoryDC(bitmap)
    root_origin = window.ClientToScreen(wx.Point(0, 0))
    contributed = 0
    routes: dict[str, int] = {"render": 0, "print": 0, "blit": 0}
    skipped: list[str] = []
    blitted_leaves: list[str] = []

    try:
        _paint_into(window, memory, wx.Point(0, 0))
        pending = [window]
        while pending:
            parent = pending.pop(0)
            for child in parent.GetChildren():
                # IsShown() is relative: it reports the flag on this window
                # alone, so a control inside a hidden tab still answers True
                # and gets drawn. Compositing on that basis painted every
                # backstage tab's body on top of every other one, producing a
                # legible-looking capture with three headings overlapping in
                # the same twenty pixels. IsShownOnScreen() walks the ancestor
                # chain, which is the question actually being asked here.
                if not child.IsShownOnScreen():
                    continue
                child_origin = child.ClientToScreen(wx.Point(0, 0))
                offset = wx.Point(
                    child_origin.x - root_origin.x, child_origin.y - root_origin.y
                )
                route = _paint_into(child, memory, offset)
                if route:
                    contributed += 1
                    routes[route] = routes.get(route, 0) + 1
                    if route == "blit" and not child.GetChildren():
                        # A blitted LEAF is the one that actually goes missing.
                        # Off-screen there is no composited surface to copy, so
                        # a leaf control read this way is a blank rectangle. A
                        # blitted container is harmless by comparison: its own
                        # visual is a background, and its children are drawn
                        # separately by this same walk.
                        blitted_leaves.append(
                            f"{child.GetName() or ''} ({type(child).__name__})".strip()
                        )
                else:
                    name = child.GetName() or ""
                    skipped.append(
                        f"{name} ({type(child).__name__})"
                        if name
                        else type(child).__name__
                    )
                pending.append(child)
    finally:
        memory.SelectObject(wx.NullBitmap)

    return bitmap.ConvertToImage(), contributed, routes, skipped, size, blitted_leaves


def capture_composite(
    window: wx.Window,
    path: str | Path,
    *,
    require_content: bool = True,
) -> dict:
    """Capture a container by compositing it and every visible descendant.

    A client-device-context blit of a *container* returns only what the
    container itself painted: on Windows its child windows are separate surfaces
    and do not appear.  That is why a capture of the ribbon can come back with
    a hundred distinct colours from its own background gradient while every
    button on it is missing, and why a colour count is not a usable gate --
    antialiasing on two stray native controls clears any floor worth setting.

    This walks the tree and draws each visible window into one bitmap at its own
    position, so the picture is assembled from the same drawing code the user
    sees rather than requested from the operating system.  It returns a report
    naming how many descendants contributed and by which route, so a caller can
    assert on structure rather than on colour: a ribbon that composites two
    children is broken no matter how colourful it is.

    ``skipped`` is the field worth watching.  A window lands there only when it
    has no ``render_to``, would not answer ``PrintWindow``, and could not be
    blitted either -- so it is genuinely absent from the picture rather than
    drawn by a route the report does not mention.  An empty list is the healthy
    state; a name in it is a hole in the capture, at the place that name says.
    """
    settle(window)
    image, contributed, routes, skipped, size, blitted_leaves = _composite(window)
    colours = _distinct_colours(image)
    if require_content and contributed < 1:
        raise RuntimeError(
            f"{window.GetName() or window!r} composited no descendants; the "
            "capture shows only the container's own background"
        )

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not image.SaveFile(str(target), wx.BITMAP_TYPE_PNG):
        raise RuntimeError(f"Could not write the capture to {target}")
    report = {
        "path": str(target),
        "colours": colours,
        "descendants": contributed,
        # How each descendant was drawn.  ``render`` is the owner-drawn widgets
        # answering directly; ``print`` is the native controls; ``blit`` is a
        # surface read, which on a hidden desktop reads nothing, so a run with
        # blits in it deserves a second look at the pictures.
        "routes": routes,
        "skipped": skipped,
        # Leaf controls that could only be read off a surface nobody
        # composited, so they are blank rectangles in the file. A blitted
        # CONTAINER is not listed: its visual is a background and its
        # children are drawn separately by the same walk.
        "blitted_leaves": blitted_leaves,
        "size": (size.width, size.height),
        # A colour count says something drew; it cannot say the interface drew.
        # Antialiasing on two stray native controls clears any floor worth
        # setting, so the count is evidence to record, never a gate to pass.
        "gate": "a person must look at a sample of every run",
    }
    log.info("composited %s: %s", window.GetName(), report)
    return report
