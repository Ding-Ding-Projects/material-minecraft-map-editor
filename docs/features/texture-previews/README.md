# Texture previews

Wherever Amulet Studio asks you to pick a block, an item, or a texture, it shows
a tile with the top, side, and bottom faces. **That tile is a generated
placeholder swatch, and it says so.**

## Behaviour

`block_tile_bitmap` (`amulet_map_editor/api/studio/blocks.py`) draws the tile
from the block's base colour, with a diagonal highlight and a grid, at whatever
size the surface asks for. `BLOCK_COLOURS` maps every block identifier the
design uses to a base colour; an identifier not in the table falls back to a
neutral grey rather than to nothing.

`TextureTile` carries the label `placeholder swatch` in the picture itself
rather than in a footnote somebody might not read, and repeats it in the tile's
accessible name and tooltip. `FaceRow` shows the three faces beside it.

A **real** texture arrives from one of three places, none of which is the
network:

1. a loaded Minecraft installation;
2. a resource pack the user has loaded;
3. a PNG or JPEG dropped onto the slot, or chosen through its click-to-browse
   path.

`ImageSlot` is the drop target. It accepts a dropped image, validates it, and
shows what it loaded. The same validation runs whether the file was dropped or
browsed to.

In the spec renderer this is one section kind — `texture` — built by
`tex_section(block_id, slot_id, hint)`. The standard hint states plainly that
the tile is generated and how to replace it; a surface that gives its own hint
still gets the tile's own label, so the disclaimer travels with the picture
regardless.

## Configuration

Adding a block to a preview means adding its base colour to `BLOCK_COLOURS`, so
the generated swatch lands in the right family. Tile size is per surface;
brightness is per face, which is what makes the three faces distinguishable.

## Failure modes

A dropped file that is not a readable image is refused with the reason, and the
slot keeps showing the placeholder rather than a blank rectangle. Images are
bounded in size, so a very large file is refused rather than consuming memory.

An unknown block identifier gets the neutral fallback and keeps its identifier
visible, so the surface still says exactly which block it means.

**The one failure this feature exists to prevent** is a generated swatch being
mistaken for the game's own texture. That is why the label is in the picture,
in the accessible name, and in the tooltip, and why the suite checks the
disclaimer is still there.

## Security and accessibility

Nothing is downloaded, ever — there is no texture fetch, no CDN, and no
telemetry about which blocks were previewed. A dropped file is read locally and
is not copied anywhere outside the application's own data area.

The tile's accessible name is the block identifier followed by the label, so a
screen-reader user learns both which block it is and that the picture is a
placeholder. The tiles never carry meaning through colour alone: the identifier
is always shown beside them.

## Verification

```powershell
py -3 -m pytest tests/test_studio_spec_registry.py -q
```

That proves every texture section names a block, a drop-target slot, and its
faces, that the shared hint still admits the tile is generated and names the
resource-pack route, and that the renderer still draws the labelled tile rather
than a bare image.

Suggested articles: [spec renderer](../spec-renderer/README.md),
[editing tools](../editing-tools/README.md),
[build tools](../build/README.md), and
[viewport](../viewport/README.md).
