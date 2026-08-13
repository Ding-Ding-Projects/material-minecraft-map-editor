"""Build a small, real Java world on disk with actual varied terrain in
chunk (0, 0), for the WebGL2 viewport capture script to open.

Not a shipped runtime module -- a one-shot fixture generator, the same way
tests/test_studio_live_world_contract.py builds its own fixture worlds
through amulet-core directly rather than shipping a binary save file.

Usage: py -3.11 scripts/make_viewport_fixture_world.py <destination-dir>
"""

from __future__ import annotations

import sys

from amulet.api.block import Block
from amulet.api.chunk import Chunk
from amulet.level.formats.anvil_world import AnvilFormat
import amulet


def build(world_path: str) -> None:
    fmt = AnvilFormat(world_path)
    fmt.create_and_open("java", (1, 20, 4), overwrite=True)
    fmt.close()

    level = amulet.load_level(world_path)
    try:
        chunk = Chunk(0, 0)
        air = chunk.block_palette.get_add_block(Block("universal_minecraft", "air"))
        stone = chunk.block_palette.get_add_block(Block("universal_minecraft", "stone"))
        dirt = chunk.block_palette.get_add_block(Block("universal_minecraft", "dirt"))
        grass = chunk.block_palette.get_add_block(
            Block("universal_minecraft", "grass_block")
        )

        chunk.blocks[:, :, :] = air
        # A simple stepped landscape so the render has real silhouette, not
        # a flat slab: stone core, dirt layer, grass on top, height varying
        # across x so the camera sees more than one flat plane.
        for x in range(16):
            height = 4 + (x % 5)
            chunk.blocks[x, 0:height, :] = stone
            chunk.blocks[x, height : height + 2, :] = dirt
            chunk.blocks[x, height + 2, :] = grass
        chunk.changed = True
        level.put_chunk(chunk, "minecraft:overworld")
        level.save()
    finally:
        level.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "usage: make_viewport_fixture_world.py <destination-dir>", file=sys.stderr
        )
        raise SystemExit(2)
    build(sys.argv[1])
    print(sys.argv[1])
