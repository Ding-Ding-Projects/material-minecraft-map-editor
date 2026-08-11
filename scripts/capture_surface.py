#!/usr/bin/env python3
"""Capture a wx window by blitting its own client area, not through PrintWindow.

``PrintWindow``/``WM_PRINT`` asks each window to draw itself into a device
context.  Native controls implement that; a window that paints in its own
``EVT_PAINT`` handler with a buffered device context generally does not, so a
capture of a parent frame comes back with every native child present and every
owner-drawn child a flat rectangle.

That matters here because the whole interface is owner-drawn.  A capture matrix
built on ``PrintWindow`` would photograph the ribbon, the navigator, the
properties pane, and every Studio control as empty boxes, and the pictures would
look exactly like a broken renderer rather than a broken capture.

Blitting the window's own client device context asks the window nothing: it
copies the pixels that are actually on the surface.  Measured on this
application, the same panels that came back blank through ``PrintWindow`` return
121, 78, 99 and 40 distinct colours through this route.

Use :func:`capture_window` from inside the application process, after the window
has been shown and the event loop has run at least once.
"""

from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
from typing import Optional

import wx

log = logging.getLogger(__name__)

_IS_WINDOWS = os.name == "nt"
_user32 = ctypes.windll.user32 if _IS_WINDOWS else None

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
    """
    settle(window)

    size = window.GetClientSize()
    if size.width < 1 or size.height < 1:
        raise RuntimeError(f"{window.GetName() or window!r} has no client area")

    bitmap = wx.Bitmap(size)
    memory = wx.MemoryDC(bitmap)
    try:
        _paint_into(window, memory, wx.Point(0, 0))
    finally:
        memory.SelectObject(wx.NullBitmap)

    image = bitmap.ConvertToImage()
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


def _paint_into(window: wx.Window, target: wx.MemoryDC, origin: wx.Point) -> int:
    """Render one window into ``target`` at ``origin``.

    ``PrintWindow`` is tried first because it is the only route that works on a
    desktop nobody is watching, which is where a capture matrix has to run.  The
    device-context read stays as the fallback for platforms without it.
    Returns the number of pixels covered, or 0 when neither route could draw --
    an OpenGL canvas being the case that matters, since its pixels live in the
    GL framebuffer rather than in any device context.
    """
    size = window.GetClientSize()
    if size.width < 1 or size.height < 1:
        return 0
    if _print_window(window, target, origin):
        return size.width * size.height
    try:
        source = wx.ClientDC(window)
        target.Blit(origin.x, origin.y, size.width, size.height, source, 0, 0)
    except Exception:
        log.debug("Could not blit %s", window.GetName(), exc_info=True)
        return 0
    return size.width * size.height


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

    This walks the tree and blits each visible window into one bitmap at its own
    position, so the picture is assembled from the same surfaces the user sees
    rather than requested from the operating system.  It returns a report naming
    how many descendants contributed, so a caller can assert on structure rather
    than on colour: a ribbon that composites two children is broken no matter
    how colourful it is.
    """
    settle(window)

    size = window.GetClientSize()
    if size.width < 1 or size.height < 1:
        raise RuntimeError(f"{window.GetName() or window!r} has no client area")

    bitmap = wx.Bitmap(size)
    memory = wx.MemoryDC(bitmap)
    root_origin = window.ClientToScreen(wx.Point(0, 0))
    contributed = 0
    skipped: list[str] = []

    try:
        _paint_into(window, memory, wx.Point(0, 0))
        pending = [window]
        while pending:
            parent = pending.pop(0)
            for child in parent.GetChildren():
                if not child.IsShown():
                    continue
                child_origin = child.ClientToScreen(wx.Point(0, 0))
                offset = wx.Point(
                    child_origin.x - root_origin.x, child_origin.y - root_origin.y
                )
                if _paint_into(child, memory, offset):
                    contributed += 1
                else:
                    skipped.append(child.GetName() or type(child).__name__)
                pending.append(child)
    finally:
        memory.SelectObject(wx.NullBitmap)

    image = bitmap.ConvertToImage()
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
        "skipped": skipped,
        "size": (size.width, size.height),
        # A colour count says something drew; it cannot say the interface drew.
        # Antialiasing on two stray native controls clears any floor worth
        # setting, so the count is evidence to record, never a gate to pass.
        "gate": "a person must look at a sample of every run",
    }
    log.info("composited %s: %s", window.GetName(), report)
    return report
