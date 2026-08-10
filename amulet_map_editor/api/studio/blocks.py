"""Block colours and the generated placeholder tiles the Studio shows for them.

Nothing here is a game texture.  The editor must be able to show a recognisable
swatch for a block before any Minecraft install or resource pack has been
loaded, and it must do so without reaching the network, so each tile is drawn
from the block's base colour plus a diagonal highlight and a grid -- the same
recipe the design uses.  Every surface that shows one labels it as a
placeholder, so a user never mistakes it for the real texture.
"""

from __future__ import annotations

from typing import Dict, Tuple

import wx

from amulet_map_editor.api.studio import tokens

#: Base colour for every block, item, and material the design names.  An
#: identifier that is absent falls back to :data:`DEFAULT_BLOCK_COLOUR` rather
#: than failing, so a new spec can reference a block before its colour lands.
BLOCK_COLOURS: Dict[str, str] = {
    "minecraft:stone": "#7E7E7E",
    "minecraft:cobblestone": "#8A8A8A",
    "minecraft:andesite": "#8C8C8E",
    "minecraft:deepslate": "#4A4A4F",
    "minecraft:polished_deepslate": "#3F3F45",
    "minecraft:deepslate_bricks": "#474751",
    "minecraft:deepslate_tiles": "#3B3B43",
    "minecraft:stone_bricks": "#7A7A75",
    "minecraft:chiselled_stone_bricks": "#6F6F6A",
    "minecraft:smooth_stone": "#9C9C9C",
    "minecraft:polished_andesite": "#84868A",
    "minecraft:blackstone": "#2C2530",
    "minecraft:polished_blackstone": "#332C38",
    "minecraft:dirt": "#8B5A2B",
    "minecraft:grass_block": "#5D9A3C",
    "minecraft:snow_block": "#F0F5F7",
    "minecraft:sand": "#DBCE9A",
    "minecraft:sandstone": "#D8CB92",
    "minecraft:water": "#3E5CB8",
    "minecraft:oak_log": "#9A7B4F",
    "minecraft:dark_oak_log": "#4A3521",
    "minecraft:oak_planks": "#B08B54",
    "minecraft:spruce_planks": "#7A5A34",
    "minecraft:glass": "#C7E4EC",
    "minecraft:iron_bars": "#B0B4B8",
    "minecraft:copper_block": "#C07248",
    "minecraft:stone_brick_wall": "#77776F",
    "minecraft:lantern": "#D9A548",
    "minecraft:sea_lantern": "#9FD3C4",
    "minecraft:glowstone": "#D8B366",
    "minecraft:shroomlight": "#E08B4A",
    "minecraft:redstone_lamp": "#9A5A34",
    "minecraft:torch": "#D4A017",
    "minecraft:soul_lantern": "#5FC7C7",
    "minecraft:obsidian": "#150E22",
    "minecraft:crying_obsidian": "#25134A",
    "minecraft:oak_fence": "#A9884F",
    "minecraft:rail": "#9B8A6A",
    "minecraft:powered_rail": "#B9863F",
    "minecraft:redstone_block": "#8E1B12",
    "minecraft:oak_sign": "#B08B54",
    "minecraft:diamond_ore": "#6E8E92",
    "minecraft:iron_ore": "#9C8A78",
    "minecraft:copper_ore": "#9C8060",
    "minecraft:redstone_ore": "#8A6A6A",
    "minecraft:ancient_debris": "#5A4038",
    "minecraft:cave_air": "#1B1B20",
    "minecraft:air": "#C9D4D2",
    "minecraft:gravel": "#8F8B87",
    "minecraft:clay": "#A0A6B0",
    "minecraft:netherrack": "#6B3234",
    "minecraft:end_stone": "#DCE0A2",
    "minecraft:sculk": "#0F2A2E",
    "minecraft:moss_block": "#5A7A32",
    "minecraft:chest": "#9A7B4F",
    "minecraft:diamond_pickaxe": "#5FC7C7",
    "minecraft:bread": "#C79A5B",
    "minecraft:filled_map": "#D8CFB4",
    "minecraft:coal": "#2A2A2E",
    "minecraft:iron_ingot": "#C6C6C6",
    "minecraft:gold_ingot": "#D4A017",
    "minecraft:concrete": "#A0A6B0",
    "minecraft:wool": "#D8D8D8",
}

#: Colour used for an identifier with no entry above.
DEFAULT_BLOCK_COLOUR = "#8A8A8A"

#: Every known identifier, sorted, for pickers and search surfaces.
BLOCK_IDS: Tuple[str, ...] = tuple(sorted(BLOCK_COLOURS))

#: The words every surface uses for these tiles.  Sharing one string keeps the
#: honesty of the label from drifting between surfaces.
PLACEHOLDER_LABEL = "placeholder swatch"

#: The three faces of a block preview, with the brightness each is drawn at.
FACE_BRIGHTNESS: Tuple[Tuple[str, float], ...] = (
    ("top", 1.0),
    ("side", 0.9),
    ("bottom", 0.78),
)

# Pattern geometry, in pixels, transcribed from the design's tile background.
_STRIPE_PERIOD = 8
_STRIPE_WIDTH = 4
_STRIPE_WEIGHT = 0.10
_GRID_STEP = 16
_GRID_ALPHA = 31  # 12% of 255, rounded.

_MAX_TILE_SIZE = 1024
_CACHE_LIMIT = 512
_tile_cache: Dict[Tuple[str, int, float], wx.Bitmap] = {}


def block_colour(block_id: str) -> wx.Colour:
    """Return the base colour for a block identifier."""
    hex_value = BLOCK_COLOURS.get(str(block_id), DEFAULT_BLOCK_COLOUR)
    value = hex_value.lstrip("#")
    return wx.Colour(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


def _scaled_colour(colour: wx.Colour, brightness: float) -> wx.Colour:
    """Multiply a colour's channels, the way the design's brightness filter does."""
    return wx.Colour(
        min(255, max(0, round(colour.Red() * brightness))),
        min(255, max(0, round(colour.Green() * brightness))),
        min(255, max(0, round(colour.Blue() * brightness))),
        colour.Alpha(),
    )


def _render_tile(base: wx.Colour, size: int, brightness: float) -> wx.Bitmap:
    """Draw one placeholder tile at a given size and brightness.

    The highlight is pre-blended into an opaque colour rather than drawn with
    an alpha pen: a plain memory device context exists on every backend, while
    an alpha-capable one does not, and pre-blending gives the identical result
    over a known flat base.  Scaling each colour before it is drawn is exactly
    equivalent to scaling the finished image, because the only translucent ink
    left is black, which scales to itself.
    """
    fill = _scaled_colour(base, brightness)
    highlight = _scaled_colour(
        tokens.blend(base, wx.Colour(255, 255, 255, 255), _STRIPE_WEIGHT), brightness
    )
    bitmap = wx.Bitmap(size, size, 24)
    dc = wx.MemoryDC(bitmap)
    try:
        dc.SetBackground(wx.Brush(fill))
        dc.Clear()
        # A 45-degree stripe is the set of points where x - y is constant, so
        # stepping that intercept in single pixels paints crisp diagonal bands
        # without asking the backend for an antialiased diagonal.
        dc.SetPen(wx.Pen(highlight, 1))
        for intercept in range(-size, size + 1):
            if intercept % _STRIPE_PERIOD < _STRIPE_WIDTH:
                dc.DrawLine(0, -intercept, size, size - intercept)
        dc.SetPen(wx.NullPen)
        _draw_grid(dc, size, fill)
    finally:
        dc.SelectObject(wx.NullBitmap)
    return bitmap


def _draw_grid(dc: wx.MemoryDC, size: int, fill: wx.Colour) -> None:
    """Draw the 16-pixel grid over a tile that has already been striped.

    The grid is translucent black in the design, which needs an alpha-capable
    context.  Where one is unavailable the same colour is pre-blended over the
    base instead; the crossings over a highlight stripe are then a shade off,
    which is invisible at tile sizes and better than no grid at all.
    """
    grid = wx.Colour(0, 0, 0, _GRID_ALPHA)
    context = None
    try:
        context = wx.GCDC(dc)
    except Exception:  # pragma: no cover - platform boundary
        context = None
    target = context if context is not None else dc
    if context is None:
        grid = tokens.blend(fill, wx.Colour(0, 0, 0, 255), _GRID_ALPHA / 255.0)
    target.SetPen(wx.Pen(grid, 1))
    for position in range(0, size, _GRID_STEP):
        target.DrawLine(0, position, size, position)
        target.DrawLine(position, 0, position, size)
    target.SetPen(wx.NullPen)
    # The wrapping context has to be released before the memory device context
    # is, or the last drawing operations may never reach the bitmap.
    del context


def block_tile_bitmap(block_id: str, size: int, brightness: float = 1.0) -> wx.Bitmap:
    """Return the generated placeholder tile for a block, cached by appearance.

    Tiles are theme-independent, so the cache survives a theme change; it is
    keyed by identifier, size, and brightness because those are the only things
    that alter the image.
    """
    tile_size = max(1, min(_MAX_TILE_SIZE, int(size)))
    level = max(0.0, min(4.0, float(brightness)))
    key = (str(block_id), tile_size, round(level, 3))
    cached = _tile_cache.get(key)
    if cached is not None and cached.IsOk():
        return cached
    bitmap = _render_tile(block_colour(block_id), tile_size, level)
    if len(_tile_cache) >= _CACHE_LIMIT:
        _tile_cache.clear()
    _tile_cache[key] = bitmap
    return bitmap


def block_face_bitmaps(block_id: str, size: int) -> Tuple[Tuple[str, wx.Bitmap], ...]:
    """Return the named top, side, and bottom tiles for a block preview.

    The three brightnesses are what makes a flat swatch read as a cube face;
    the names travel with the bitmaps so the caller can label them for screen
    readers instead of relying on their order.
    """
    return tuple(
        (name, block_tile_bitmap(block_id, size, brightness))
        for name, brightness in FACE_BRIGHTNESS
    )


def clear_bitmap_cache() -> None:
    """Drop every cached tile, releasing their platform bitmap handles."""
    _tile_cache.clear()


def cached_tile_count() -> int:
    """Return how many tiles are currently cached (used by tests)."""
    return len(_tile_cache)


__all__ = [
    "BLOCK_COLOURS",
    "BLOCK_IDS",
    "DEFAULT_BLOCK_COLOUR",
    "FACE_BRIGHTNESS",
    "PLACEHOLDER_LABEL",
    "block_colour",
    "block_face_bitmaps",
    "block_tile_bitmap",
    "cached_tile_count",
    "clear_bitmap_cache",
]
