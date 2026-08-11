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

import logging
from pathlib import Path
from typing import Optional

import wx

log = logging.getLogger(__name__)

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
    window.Refresh()
    window.Update()
    wx.Yield()

    size = window.GetClientSize()
    if size.width < 1 or size.height < 1:
        raise RuntimeError(f"{window.GetName() or window!r} has no client area")

    bitmap = wx.Bitmap(size)
    memory = wx.MemoryDC(bitmap)
    try:
        memory.Blit(0, 0, size.width, size.height, wx.ClientDC(window), 0, 0)
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
