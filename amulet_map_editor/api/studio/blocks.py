"""Block colours and the generated placeholder tiles the Studio shows for them.

Nothing here is a game texture.  The editor must be able to show a recognisable
swatch for a block before any Minecraft install or resource pack has been
loaded, and it must do so without reaching the network, so each tile is drawn
from the block's base colour plus a diagonal highlight and a grid -- the same
recipe the design uses.  Every surface that shows one labels it as a
placeholder, so a user never mistakes it for the real texture.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

import wx

from amulet_map_editor.api.studio import minecraft, tokens

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

#: The blocks current Minecraft added after the design was transcribed, grouped
#: by family so a reviewer can see at a glance that a swatch sits in the right
#: one.  Copper is generated below rather than written out, because its
#: oxidation and waxed variants are the same colours repeated forty-eight times
#: and a hand-written wall of them is where a wrong family hides.
_MODERN_BLOCK_COLOURS: Dict[str, str] = {
    # Deepslate, and the ores that only exist in it.
    "minecraft:cobbled_deepslate": "#4C4C51",
    "minecraft:chiseled_deepslate": "#37373D",
    "minecraft:cracked_deepslate_bricks": "#43434C",
    "minecraft:cracked_deepslate_tiles": "#37373F",
    "minecraft:reinforced_deepslate": "#454A42",
    "minecraft:infested_deepslate": "#4A4A4F",
    "minecraft:deepslate_coal_ore": "#37373C",
    "minecraft:deepslate_iron_ore": "#57564F",
    "minecraft:deepslate_copper_ore": "#5B564A",
    "minecraft:deepslate_gold_ore": "#665A3C",
    "minecraft:deepslate_redstone_ore": "#573A3A",
    "minecraft:deepslate_lapis_ore": "#3B4763",
    "minecraft:deepslate_emerald_ore": "#3D5B4A",
    "minecraft:deepslate_diamond_ore": "#4C6165",
    # Tuff and its building set.
    "minecraft:tuff": "#6D6D66",
    "minecraft:polished_tuff": "#67675F",
    "minecraft:tuff_bricks": "#62625B",
    "minecraft:chiseled_tuff": "#5D5D56",
    "minecraft:chiseled_tuff_bricks": "#585851",
    # The sculk family of the deep dark.
    "minecraft:sculk_vein": "#123239",
    "minecraft:sculk_catalyst": "#17383E",
    "minecraft:sculk_shrieker": "#1F4048",
    "minecraft:sculk_sensor": "#1B4A52",
    "minecraft:calibrated_sculk_sensor": "#20525A",
    # Cherry.
    "minecraft:cherry_planks": "#E2AFA6",
    "minecraft:cherry_log": "#3B2A2E",
    "minecraft:stripped_cherry_log": "#D3897F",
    "minecraft:cherry_leaves": "#EBA7C6",
    # Pale oak and the pale garden.
    "minecraft:pale_oak_planks": "#E1D7C3",
    "minecraft:pale_oak_log": "#3C3830",
    "minecraft:pale_oak_leaves": "#6F7C5E",
    "minecraft:pale_moss_block": "#7E8471",
    "minecraft:pale_hanging_moss": "#8A9080",
    "minecraft:creaking_heart": "#574636",
    # Bamboo.
    "minecraft:bamboo_planks": "#CBB669",
    "minecraft:bamboo_mosaic": "#C2AC5E",
    "minecraft:bamboo_block": "#7E9B3F",
    "minecraft:stripped_bamboo_block": "#C8AE5C",
    # Mud, packed mud, and the mangrove set they arrived with.
    "minecraft:mud": "#3C3535",
    "minecraft:packed_mud": "#8B6349",
    "minecraft:mud_bricks": "#8A6A55",
    "minecraft:muddy_mangrove_roots": "#443A31",
    "minecraft:mangrove_planks": "#77362F",
    "minecraft:mangrove_log": "#55352E",
    "minecraft:mangrove_roots": "#57483C",
    "minecraft:mangrove_leaves": "#4E7A33",
    # Calcite, dripstone, and amethyst.
    "minecraft:calcite": "#DFDFDA",
    "minecraft:dripstone_block": "#866B5B",
    "minecraft:pointed_dripstone": "#8A6F5F",
    "minecraft:amethyst_block": "#8763CE",
    "minecraft:budding_amethyst": "#8A66CB",
    "minecraft:amethyst_cluster": "#A688DC",
    "minecraft:tinted_glass": "#383039",
    # Froglights.
    "minecraft:ochre_froglight": "#D9C87C",
    "minecraft:verdant_froglight": "#B3D190",
    "minecraft:pearlescent_froglight": "#E7C9D5",
    # Trial chambers.
    "minecraft:trial_spawner": "#3B4A50",
    "minecraft:vault": "#303F4B",
    "minecraft:heavy_core": "#4A5158",
    # The crafter.
    "minecraft:crafter": "#6B5341",
    # Resin.
    "minecraft:resin_block": "#E07C2A",
    "minecraft:resin_bricks": "#C2662B",
    "minecraft:chiseled_resin_bricks": "#B65E28",
    "minecraft:resin_clump": "#E48D3C",
    # Archaeology.
    "minecraft:suspicious_sand": "#D5C79B",
    "minecraft:suspicious_gravel": "#8D8985",
    "minecraft:decorated_pot": "#A75C3E",
    # Lush caves.
    "minecraft:moss_carpet": "#59782F",
    "minecraft:azalea": "#6E8C3D",
    "minecraft:flowering_azalea": "#7E8C56",
    "minecraft:rooted_dirt": "#96674A",
    # Modern light sources.
    "minecraft:glow_lichen": "#6E8A6C",
    "minecraft:cave_vines": "#6D7F3D",
    "minecraft:candle": "#E5DCC7",
    "minecraft:sea_pickle": "#5C7A3A",
    "minecraft:soul_torch": "#4FC3C3",
    "minecraft:soul_campfire": "#3FB7BC",
    "minecraft:light": "#F2E7B6",
}

#: The four oxidation stages, and how far each one has walked towards the
#: patina.  Waxing stops the walk rather than changing the colour, so a waxed
#: block is drawn at the colour of the stage it was waxed at.  The last stage
#: stops just short of the patina so a fully oxidised bulb and a fully oxidised
#: grate are still different swatches; a picker where every oxidised block is
#: one identical square is worse than one that is a shade off.
_OXIDATION: Tuple[Tuple[str, float], ...] = (
    ("", 0.0),
    ("exposed_", 0.34),
    ("weathered_", 0.67),
    ("oxidized_", 0.9),
)

#: The oxidised end of the scale: the blue-green every copper block walks to.
_PATINA = "#53A183"

#: The copper blocks that oxidise, with the colour each has when it is fresh.
#: A base name here becomes eight entries: four oxidation stages, each in a
#: plain and a waxed spelling.
_COPPER_BASES: Tuple[Tuple[str, str], ...] = (
    ("copper_block", "#C0714A"),
    ("cut_copper", "#C06B45"),
    ("chiseled_copper", "#BC6D46"),
    ("copper_grate", "#B4693F"),
    ("copper_bulb", "#C4823F"),
    ("copper_door", "#C0724C"),
    ("copper_trapdoor", "#BE6F48"),
    ("copper_chest", "#C0724A"),
    ("copper_golem_statue", "#B9704A"),
    ("copper_bars", "#B87049"),
    ("copper_chain", "#B06A44"),
    ("copper_lantern", "#C3853F"),
)

#: Copper blocks with no oxidation ladder of their own.
_PLAIN_COPPER: Dict[str, str] = {
    "minecraft:copper_torch": "#D08A4A",
    "minecraft:lightning_rod": "#C0724A",
}


def _mix_hex(start: str, end: str, weight: float) -> str:
    """Blend two ``#rrggbb`` strings, returning another one."""
    first = start.lstrip("#")
    second = end.lstrip("#")
    channels = []
    for index in (0, 2, 4):
        low = int(first[index : index + 2], 16)
        high = int(second[index : index + 2], 16)
        channels.append(round(low + (high - low) * weight))
    return "#" + "".join(f"{value:02X}" for value in channels)


def _copper_colours() -> Dict[str, str]:
    """Return every copper identifier and its colour, oxidised and waxed.

    Minecraft names the plain block's stages ``exposed_copper`` rather than
    ``exposed_copper_block``, which is the one irregularity in an otherwise
    mechanical set of names, so it is handled here rather than by writing all
    ninety-six identifiers out by hand.
    """
    colours: Dict[str, str] = {}
    for base, fresh in _COPPER_BASES:
        for prefix, weight in _OXIDATION:
            if base == "copper_block" and prefix:
                name = f"{prefix}copper"
            else:
                name = f"{prefix}{base}"
            colour = _mix_hex(fresh, _PATINA, weight)
            colours[f"minecraft:{name}"] = colour
            colours[f"minecraft:waxed_{name}"] = colour
    colours.update(_PLAIN_COPPER)
    return colours


_COPPER_BLOCK_COLOURS: Dict[str, str] = _copper_colours()

BLOCK_COLOURS.update(_MODERN_BLOCK_COLOURS)
BLOCK_COLOURS.update(_COPPER_BLOCK_COLOURS)

#: Every identifier this module added for current Minecraft, sorted.  Surfaces
#: use it to ask :func:`unsupported_block_ids` which of them the installed
#: translation data can actually place, rather than offering a swatch for a
#: block nothing on this machine could write.
MODERN_BLOCK_IDS: Tuple[str, ...] = tuple(
    sorted(set(_MODERN_BLOCK_COLOURS) | set(_COPPER_BLOCK_COLOURS))
)

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


def unsupported_block_ids(block_ids: Optional[Iterable[str]] = None) -> Tuple[str, ...]:
    """Return the identifiers the installed translation data cannot place.

    A swatch can be drawn for anything, because it is generated from a colour;
    writing the block into a world needs the installed ``amulet-core`` and
    ``PyMCTranslate`` to know it.  Those are two different questions, and a
    picker that answers the first while implying the second is how a user ends
    up choosing a block the editor will refuse.  Defaults to the modern
    identifiers, which are the ones an older install is likely to be missing.
    """
    candidates = MODERN_BLOCK_IDS if block_ids is None else tuple(block_ids)
    return minecraft.unsupported_blocks(candidates)


def support_note() -> str:
    """Return the sentence a block picker shows about what this install supports."""
    return minecraft.support_report()


__all__ = [
    "BLOCK_COLOURS",
    "BLOCK_IDS",
    "DEFAULT_BLOCK_COLOUR",
    "FACE_BRIGHTNESS",
    "MODERN_BLOCK_IDS",
    "PLACEHOLDER_LABEL",
    "block_colour",
    "block_face_bitmaps",
    "block_tile_bitmap",
    "cached_tile_count",
    "clear_bitmap_cache",
    "support_note",
    "unsupported_block_ids",
]
