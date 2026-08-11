#!/usr/bin/env python3
"""Generate the example Minecraft world that every release publishes.

The world is a Java 1.12.2 Anvil save built from scratch with amulet-core.  A
template was not needed: ``AnvilFormat.create_and_open`` writes a valid
``level.dat`` and the region directory grows from ``World.put_chunk`` calls, so
``resource/worlds/java_1_12_2.zip`` is never opened here.  Building from
nothing also keeps the output deterministic, which growing a shipped save
would not.

Determinism
-----------
Everything the generator writes is a pure function of ``--seed`` and
``--size``.  Three things in the amulet write path are not, and each is
normalised before the zip is built:

* ``AnvilFormat._create`` stamps ``LastPlayed`` with the wall clock.  The final
  ``level.dat`` is rewritten here from a fully specified tag and gzipped with
  ``mtime=0``.
* The Anvil region header carries a 4096-byte timestamp table written from
  ``time.time()``.  It is rewritten to a fixed epoch for occupied slots and
  zero for empty ones.  Measured: two runs of the same seed differ in exactly
  those bytes and nowhere else.
* ``session.lock`` holds the lock time.  It is a runtime file, not world data,
  and is removed.

The zip itself is written with fixed member order, a fixed DOS timestamp and a
fixed create-system, so the same ``--seed``/``--size``/``--commit`` triple
produces byte-identical bytes on a given zlib build.

Entities
--------
amulet-core 1.9 ships with ``amulet.entity_support = False``, so
``Chunk.entities`` is discarded when a chunk is packed and the Anvil interface
writes ``Chunk._native_entities`` verbatim instead.  The mobs below therefore
go into the native list with a matching ``_native_version``, which is the path
the format actually reads and writes today.

Block entities
--------------
Universal block-entity NBT is not the Java NBT.  Each feature is described in
its Java 1.12.2 form and pushed through ``version.block.to_universal`` so
PyMCTranslate decides the universal shape.  The sign is the one exception:
round-tripping a Java sign shifts its lines by one in PyMCTranslate 1.12.2, so
its universal ``front_text/java_json`` list is built directly with four
entries.  The verification pass reads the sign back and fails if the text did
not survive.
"""

from __future__ import annotations

import argparse
import gzip
import importlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# The seed is a constant, never the clock and never `random`, so a release can
# be reproduced from its notes alone.
DEFAULT_SEED = 20260810
DEFAULT_SIZE = 500
MINIMUM_SIZE = 32
MAXIMUM_SIZE = 4096

WORLD_NAME = "Amulet Example World"
WORLD_DIRECTORY_NAME = "amulet-example-world"
PLATFORM = "java"
GAME_VERSION = (1, 12, 2)
GAME_VERSION_NAME = "1.12.2"

CHUNK_WIDTH = 16
BUILD_HEIGHT = 96
SEA_LEVEL = 62
TERRAIN_FLOOR = 44
TERRAIN_RANGE = 42
BEDROCK_ROUGH_TOP = 3

# 2015-01-01T00:00:00Z.  Any fixed instant would do; a plausible one keeps the
# region header readable by tools that print it.
FIXED_EPOCH_SECONDS = 1420070400
FIXED_EPOCH_MILLISECONDS = FIXED_EPOCH_SECONDS * 1000
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

REGION_SLOT_COUNT = 1024
REGION_HEADER_BYTES = 4096

# Layered value noise: period in blocks, amplitude.  Wide octaves make the
# continents, narrow ones make the ground uneven enough to read as terrain.
NOISE_OCTAVES: Tuple[Tuple[float, float], ...] = (
    (192.0, 1.0),
    (96.0, 0.5),
    (48.0, 0.25),
    (24.0, 0.125),
    (12.0, 0.0625),
)
# Value noise clusters around 0.5.  Spreading it before it becomes a height is
# what stops the map being one continent-wide plateau.
NOISE_CONTRAST = 1.55
# The middle of the map is held above a floor that decays to nothing halfway
# out, expressed as a fraction of the height range.  Noise above the floor
# still wins, so this shapes an island rather than stamping a plateau.
CENTRE_ISLAND_LIFT = 0.55
CENTRE_ISLAND_RADIUS = 0.55

_HASH_SEED_MIX = 0x9E3779B1
_HASH_X_MIX = 0x85EBCA77
_HASH_Z_MIX = 0xC2B2AE3D
_HASH_FINAL_MIX = 0x27D4EB2F
_UINT32_MASK = 0xFFFFFFFF

GAME_RULES: Tuple[Tuple[str, str], ...] = (
    ("announceAdvancements", "false"),
    ("commandBlockOutput", "true"),
    ("disableElytraMovementCheck", "false"),
    ("doDaylightCycle", "false"),
    ("doEntityDrops", "true"),
    ("doFireTick", "false"),
    ("doLimitedCrafting", "false"),
    ("doMobLoot", "true"),
    ("doMobSpawning", "false"),
    ("doTileDrops", "true"),
    ("doWeatherCycle", "false"),
    ("gameLoopFunction", "-"),
    ("keepInventory", "true"),
    ("logAdminCommands", "true"),
    ("maxCommandChainLength", "65536"),
    ("maxEntityCramming", "24"),
    ("mobGriefing", "false"),
    ("naturalRegeneration", "true"),
    ("randomTickSpeed", "3"),
    ("reducedDebugInfo", "false"),
    ("sendCommandFeedback", "true"),
    ("showDeathMessages", "true"),
    ("spawnRadius", "0"),
    ("spectatorsGenerateChunks", "true"),
)


class ExampleWorldError(RuntimeError):
    """A failure that must stop the run rather than leave half a world behind."""


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def load_dependencies() -> SimpleNamespace:
    """Import everything the generator needs, naming the missing piece exactly.

    ``--help`` never calls this, so the command-line interface stays usable on
    a machine that has no amulet-core installed.
    """
    required = (
        ("numpy", "numpy"),
        ("amulet_nbt", "amulet-nbt"),
        ("PyMCTranslate", "pymctranslate"),
        ("amulet", "amulet-core"),
    )
    modules: Dict[str, Any] = {}
    for module_name, distribution in required:
        try:
            modules[module_name] = importlib.import_module(module_name)
        except ImportError as error:
            raise ExampleWorldError(
                f"cannot create a level: the {module_name} module "
                f"(distribution {distribution}) is not importable in this "
                f"environment. Install it with "
                f"`{Path(sys.executable).name} -m pip install {distribution}`. "
                f"The import failed with: {error}"
            ) from error

    try:
        anvil = importlib.import_module("amulet.level.formats.anvil_world")
        block_module = importlib.import_module("amulet.api.block")
        block_entity_module = importlib.import_module("amulet.api.block_entity")
        entity_module = importlib.import_module("amulet.api.entity")
        chunk_module = importlib.import_module("amulet.api.chunk")
        selection_module = importlib.import_module("amulet.api.selection")
    except ImportError as error:
        raise ExampleWorldError(
            f"cannot create a level: amulet-core is installed but an expected "
            f"submodule is missing: {error}"
        ) from error

    missing = [
        name
        for name, owner in (
            ("AnvilFormat", anvil),
            ("Block", block_module),
            ("BlockEntity", block_entity_module),
            ("Entity", entity_module),
            ("Chunk", chunk_module),
            ("SelectionBox", selection_module),
            ("SelectionGroup", selection_module),
        )
        if not hasattr(owner, name)
    ]
    if missing:
        raise ExampleWorldError(
            "cannot create a level: amulet-core "
            f"{getattr(modules['amulet'], '__version__', 'unknown')} does not "
            f"expose {', '.join(missing)}. This generator targets the "
            "amulet-core 1.9 API."
        )
    if not hasattr(anvil.AnvilFormat, "create_and_open"):
        raise ExampleWorldError(
            "cannot create a level: amulet-core "
            f"{getattr(modules['amulet'], '__version__', 'unknown')} has no "
            "AnvilFormat.create_and_open, so a new Java world cannot be "
            "written from scratch."
        )

    nbt = modules["amulet_nbt"]
    return SimpleNamespace(
        numpy=modules["numpy"],
        amulet=modules["amulet"],
        nbt=nbt,
        AnvilFormat=anvil.AnvilFormat,
        Block=block_module.Block,
        BlockEntity=block_entity_module.BlockEntity,
        Entity=entity_module.Entity,
        Chunk=chunk_module.Chunk,
        SelectionBox=selection_module.SelectionBox,
        SelectionGroup=selection_module.SelectionGroup,
    )


# ---------------------------------------------------------------------------
# Value noise
# ---------------------------------------------------------------------------


def _lattice_values(deps: SimpleNamespace, seed: int, salt: int, grid_x, grid_z):
    """A deterministic value in [0, 1) at every integer lattice point.

    An integer avalanche hash rather than a seeded PRNG: the value at a lattice
    point depends only on the point, so the same seed gives the same terrain
    whatever order the chunks are visited in.
    """
    numpy = deps.numpy
    uint32 = numpy.uint32
    with numpy.errstate(over="ignore"):
        value = numpy.full(
            grid_x.shape, uint32(seed & _UINT32_MASK), dtype=numpy.uint32
        )
        value ^= grid_x.astype(numpy.int64).astype(numpy.uint32) * uint32(
            _HASH_SEED_MIX
        )
        value ^= grid_z.astype(numpy.int64).astype(numpy.uint32) * uint32(_HASH_X_MIX)
        value ^= uint32((salt * _HASH_Z_MIX) & _UINT32_MASK)
        value ^= value >> uint32(15)
        value *= uint32(_HASH_FINAL_MIX)
        value ^= value >> uint32(13)
        value *= uint32(_HASH_SEED_MIX)
        value ^= value >> uint32(16)
    return value.astype(numpy.float64) / float(_UINT32_MASK + 1)


def _value_noise(
    deps: SimpleNamespace, seed: int, salt: int, world_x, world_z, period: float
):
    """One octave of smoothed value noise over the given world coordinates."""
    numpy = deps.numpy
    scaled_x = world_x / period
    scaled_z = world_z / period
    grid_x = numpy.floor(scaled_x).astype(numpy.int64)
    grid_z = numpy.floor(scaled_z).astype(numpy.int64)
    fraction_x = scaled_x - grid_x
    fraction_z = scaled_z - grid_z
    # Smoothstep, so octave boundaries do not show as a lattice of creases.
    weight_x = fraction_x * fraction_x * (3.0 - 2.0 * fraction_x)
    weight_z = fraction_z * fraction_z * (3.0 - 2.0 * fraction_z)

    corner_00 = _lattice_values(deps, seed, salt, grid_x, grid_z)
    corner_10 = _lattice_values(deps, seed, salt, grid_x + 1, grid_z)
    corner_01 = _lattice_values(deps, seed, salt, grid_x, grid_z + 1)
    corner_11 = _lattice_values(deps, seed, salt, grid_x + 1, grid_z + 1)

    low = corner_00 + (corner_10 - corner_00) * weight_x
    high = corner_01 + (corner_11 - corner_01) * weight_x
    return low + (high - low) * weight_z


def build_height_field(deps: SimpleNamespace, seed: int, origin: int, span: int):
    """The surface height of every column in the world, as one array."""
    numpy = deps.numpy
    axis = numpy.arange(origin, origin + span, dtype=numpy.float64)
    world_x, world_z = numpy.meshgrid(axis, axis, indexing="ij")

    total = numpy.zeros(world_x.shape, dtype=numpy.float64)
    amplitude_sum = 0.0
    for index, (period, amplitude) in enumerate(NOISE_OCTAVES):
        total += amplitude * _value_noise(
            deps, seed, index + 1, world_x, world_z, period
        )
        amplitude_sum += amplitude
    shaped = total / amplitude_sum

    shaped = 0.5 + (shaped - 0.5) * NOISE_CONTRAST

    # Hold the middle of the map above water.  Pure noise puts land wherever it
    # likes, so the centre -- where the spawn and the landmarks go -- is as
    # likely to be open sea as meadow, and a small --size can produce a map
    # with no land in it at all.  Taking the maximum against a smooth radial
    # floor guarantees an island in the middle without capping the hills the
    # noise builds elsewhere.
    centre = (span - 1) / 2.0
    radius = numpy.maximum(
        numpy.abs(world_x - (origin + centre)), numpy.abs(world_z - (origin + centre))
    )
    radius = numpy.clip(radius / max(centre * CENTRE_ISLAND_RADIUS, 1.0), 0.0, 1.0)
    falloff = radius * radius * (3.0 - 2.0 * radius)
    shaped = numpy.maximum(shaped, CENTRE_ISLAND_LIFT * (1.0 - falloff))
    numpy.clip(shaped, 0.0, 1.0, out=shaped)

    heights = numpy.rint(TERRAIN_FLOOR + TERRAIN_RANGE * shaped).astype(numpy.int32)
    return numpy.clip(heights, 1, BUILD_HEIGHT - 2)


# The landmark cluster spans spawn_x-4..spawn_x+6 by spawn_z-4..spawn_z+2.
# A margin of six columns keeps all of it, and the mobs, on the same dry ground.
SPAWN_CLEARANCE = 6


def choose_spawn(
    deps: SimpleNamespace, heights, origin_block: int
) -> Tuple[int, int, int]:
    """Pick the dry, level-enough column nearest the middle of the map.

    The middle of a noise field is as likely to be seabed as meadow.  Spawning
    there leaves the landmarks standing on pillars in open water and the mobs
    on the bottom of it, which is not an example of anything.
    """
    numpy = deps.numpy
    span = heights.shape[0]
    dry = heights > SEA_LEVEL + 1

    # Every column within the clearance must also be dry, or a chest ends up
    # half in the sea even though its own column was fine.
    buildable = dry.copy()
    for offset_x in range(-SPAWN_CLEARANCE, SPAWN_CLEARANCE + 1):
        for offset_z in range(-SPAWN_CLEARANCE, SPAWN_CLEARANCE + 1):
            if offset_x == 0 and offset_z == 0:
                continue
            shifted = numpy.zeros_like(dry)
            source_x = slice(max(0, offset_x), span + min(0, offset_x))
            target_x = slice(max(0, -offset_x), span + min(0, -offset_x))
            source_z = slice(max(0, offset_z), span + min(0, offset_z))
            target_z = slice(max(0, -offset_z), span + min(0, -offset_z))
            shifted[target_x, target_z] = dry[source_x, source_z]
            buildable &= shifted

    candidates = buildable if buildable.any() else dry
    if not candidates.any():
        raise ExampleWorldError(
            f"no column in the {span} x {span} height field rises above sea "
            f"level {SEA_LEVEL}; there is nowhere to put a world spawn"
        )

    centre = span // 2
    index_x, index_z = numpy.indices(heights.shape)
    distance = numpy.abs(index_x - centre) + numpy.abs(index_z - centre)
    # argmin resolves ties in row-major order, so the choice is deterministic.
    masked = numpy.where(candidates, distance, distance.max() + 1)
    flat = int(numpy.argmin(masked))
    local_x, local_z = divmod(flat, span)
    return (
        origin_block + local_x,
        int(heights[local_x, local_z]) + 1,
        origin_block + local_z,
    )


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------


class Palette:
    """Java 1.12.2 blocks, translated to the universal ids a chunk stores.

    Blocks are named in the form the world actually saves -- ``minecraft:stone``
    with a numeric ``block_data`` -- and PyMCTranslate decides the universal
    name.  Naming universal blocks directly means guessing at property sets
    that differ per block, and a wrong guess silently becomes a different
    block.
    """

    def __init__(self, deps: SimpleNamespace, level) -> None:
        self._deps = deps
        self._level = level
        self._version = level.translation_manager.get_version(PLATFORM, GAME_VERSION)

    def universal_block(self, name: str, block_data: int = 0):
        deps = self._deps
        java_block = deps.Block(
            "minecraft", name, {"block_data": deps.nbt.IntTag(block_data)}
        )
        universal_block, _, _ = self._version.block.to_universal(java_block)
        return universal_block

    def block_id(self, name: str, block_data: int = 0) -> int:
        return self._level.block_palette.get_add_block(
            self.universal_block(name, block_data)
        )

    def universal_pair(
        self,
        name: str,
        block_data: int,
        block_entity_id: str,
        block_entity_nbt,
    ):
        """Translate a Java block plus its Java block-entity NBT to universal."""
        deps = self._deps
        java_block = deps.Block(
            "minecraft", name, {"block_data": deps.nbt.IntTag(block_data)}
        )
        java_block_entity = deps.BlockEntity(
            "minecraft",
            block_entity_id,
            0,
            0,
            0,
            deps.nbt.NamedTag(block_entity_nbt),
        )
        universal_block, universal_block_entity, _ = self._version.block.to_universal(
            java_block, java_block_entity
        )
        if universal_block_entity is None:
            raise ExampleWorldError(
                f"PyMCTranslate produced no universal block entity for "
                f"minecraft:{name}[block_data={block_data}]"
            )
        return universal_block, universal_block_entity

    def biome_id(self, java_biome: str) -> int:
        """Register a Java biome under the universal name PyMCTranslate gives it.

        Universal biome names are not the Java ones and not always the obvious
        pluralisation -- ``minecraft:beaches`` is ``universal_minecraft:beach``.
        An unknown name is not an error at write time: amulet logs a warning
        and silently substitutes plains, so guessing costs the biome without
        costing the build.
        """
        universal_biome = self._version.biome.to_universal(java_biome)
        if not universal_biome.startswith("universal_minecraft:"):
            raise ExampleWorldError(
                f"PyMCTranslate did not translate the biome {java_biome} to a "
                f"universal name; it returned {universal_biome!r}"
            )
        return self._level.biome_palette.get_add_biome(universal_biome)


# ---------------------------------------------------------------------------
# Terrain
# ---------------------------------------------------------------------------


class TerrainBuilder:
    """Turns the height field into chunks of blocks."""

    def __init__(self, deps: SimpleNamespace, palette: Palette, seed: int) -> None:
        self._deps = deps
        self._seed = seed
        self.air = palette.block_id("air")
        self.stone = palette.block_id("stone")
        self.dirt = palette.block_id("dirt")
        self.grass = palette.block_id("grass")
        self.sand = palette.block_id("sand")
        self.gravel = palette.block_id("gravel")
        self.water = palette.block_id("water")
        self.bedrock = palette.block_id("bedrock")
        self.log = palette.block_id("log")
        self.leaves = palette.block_id("leaves", 4)
        self.tall_grass = palette.block_id("tallgrass", 1)
        self.poppy = palette.block_id("red_flower")
        self.dandelion = palette.block_id("yellow_flower")
        self.plains_biome = palette.biome_id("minecraft:plains")
        self.beach_biome = palette.biome_id("minecraft:beaches")
        self.ocean_biome = palette.biome_id("minecraft:ocean")

    def build_chunk_blocks(self, heights, chunk_x: int, chunk_z: int):
        """Return the (16, BUILD_HEIGHT, 16) block array for one chunk."""
        numpy = self._deps.numpy
        blocks = numpy.full(
            (CHUNK_WIDTH, BUILD_HEIGHT, CHUNK_WIDTH), self.air, dtype=numpy.uint32
        )
        levels = numpy.arange(BUILD_HEIGHT, dtype=numpy.int32)[None, :, None]
        column = heights[:, None, :].astype(numpy.int32)
        beach = column <= SEA_LEVEL + 1
        underwater = column < SEA_LEVEL - 2

        blocks = numpy.where(levels < column - 4, self.stone, blocks)
        band = numpy.where(beach, self.sand, self.dirt)
        band = numpy.where(underwater, self.gravel, band)
        blocks = numpy.where((levels >= column - 4) & (levels < column), band, blocks)
        surface = numpy.where(beach, self.sand, self.grass)
        surface = numpy.where(underwater, self.gravel, surface)
        blocks = numpy.where(levels == column, surface, blocks)
        blocks = numpy.where(
            (levels > column) & (levels <= SEA_LEVEL), self.water, blocks
        )

        # A jagged bedrock floor, the way the game writes one.
        blocks[:, 0, :] = self.bedrock
        world_x = (
            numpy.arange(CHUNK_WIDTH, dtype=numpy.int64)[:, None]
            + chunk_x * CHUNK_WIDTH
        )
        world_z = (
            numpy.arange(CHUNK_WIDTH, dtype=numpy.int64)[None, :]
            + chunk_z * CHUNK_WIDTH
        )
        world_x, world_z = numpy.broadcast_arrays(world_x, world_z)
        for level in range(1, BEDROCK_ROUGH_TOP + 1):
            roughness = _lattice_values(
                self._deps, self._seed, 100 + level, world_x, world_z
            )
            blocks[:, level, :] = numpy.where(
                roughness < (1.0 - level / (BEDROCK_ROUGH_TOP + 1.0)),
                self.bedrock,
                blocks[:, level, :],
            )
        return blocks.astype(numpy.uint32, copy=False)

    def decorate_chunk(self, blocks, heights, chunk_x: int, chunk_z: int) -> None:
        """Scatter plants and small oaks so the surface is not bare."""
        numpy = self._deps.numpy
        world_x = (
            numpy.arange(CHUNK_WIDTH, dtype=numpy.int64)[:, None]
            + chunk_x * CHUNK_WIDTH
        )
        world_z = (
            numpy.arange(CHUNK_WIDTH, dtype=numpy.int64)[None, :]
            + chunk_z * CHUNK_WIDTH
        )
        world_x, world_z = numpy.broadcast_arrays(world_x, world_z)
        draw = _lattice_values(self._deps, self._seed, 7, world_x, world_z)

        for local_x in range(CHUNK_WIDTH):
            for local_z in range(CHUNK_WIDTH):
                height = int(heights[local_x, local_z])
                if height <= SEA_LEVEL + 1 or height + 8 >= BUILD_HEIGHT:
                    continue
                roll = float(draw[local_x, local_z])
                if roll > 0.986 and 2 <= local_x <= 13 and 2 <= local_z <= 13:
                    self._place_oak(blocks, local_x, local_z, height)
                elif roll > 0.90:
                    blocks[local_x, height + 1, local_z] = self.tall_grass
                elif roll > 0.885:
                    blocks[local_x, height + 1, local_z] = self.poppy
                elif roll > 0.870:
                    blocks[local_x, height + 1, local_z] = self.dandelion

    def _place_oak(self, blocks, local_x: int, local_z: int, height: int) -> None:
        trunk_height = 5
        top = height + trunk_height
        for offset_x in range(-2, 3):
            for offset_z in range(-2, 3):
                if abs(offset_x) == 2 and abs(offset_z) == 2:
                    continue
                for level in (top - 2, top - 1):
                    blocks[local_x + offset_x, level, local_z + offset_z] = self.leaves
        for offset_x in range(-1, 2):
            for offset_z in range(-1, 2):
                if abs(offset_x) == 1 and abs(offset_z) == 1:
                    continue
                blocks[local_x + offset_x, top, local_z + offset_z] = self.leaves
        for level in range(height + 1, top):
            blocks[local_x, level, local_z] = self.log

    def biome_map(self, heights):
        numpy = self._deps.numpy
        biomes = numpy.full(heights.shape, self.plains_biome, dtype=numpy.uint32)
        biomes = numpy.where(heights <= SEA_LEVEL + 1, self.beach_biome, biomes)
        return numpy.where(heights < SEA_LEVEL - 2, self.ocean_biome, biomes)


# ---------------------------------------------------------------------------
# Features the editor's surfaces actually read
# ---------------------------------------------------------------------------


def _item(deps: SimpleNamespace, item_id: str, count: int, slot: int):
    return deps.nbt.CompoundTag(
        {
            "id": deps.nbt.StringTag(item_id),
            "Count": deps.nbt.ByteTag(count),
            "Damage": deps.nbt.ShortTag(0),
            "Slot": deps.nbt.ByteTag(slot),
        }
    )


def _chest_nbt(deps: SimpleNamespace, name: str, contents: Sequence[Tuple[str, int]]):
    return deps.nbt.CompoundTag(
        {
            "CustomName": deps.nbt.StringTag(name),
            "Items": deps.nbt.ListTag(
                [
                    _item(deps, item_id, count, slot)
                    for slot, (item_id, count) in enumerate(contents)
                ]
            ),
        }
    )


def _sign_block_entity(
    deps: SimpleNamespace, lines: Sequence[str], x: int, y: int, z: int
):
    """Build the universal sign block entity directly.

    ``to_universal`` on a Java 1.12.2 sign returns a five-entry ``java_json``
    list whose first entry is blank, and ``from_universal`` then reads entries
    0..3 -- so a sign that goes through the round trip loses its last line and
    gains an empty first one.  Writing the four entries here puts the four
    lines in Text1..Text4, which the verification pass checks.
    """
    return deps.BlockEntity(
        "universal_minecraft",
        "sign",
        x,
        y,
        z,
        deps.nbt.NamedTag(
            deps.nbt.CompoundTag(
                {
                    "utags": deps.nbt.CompoundTag(
                        {
                            "front_text": deps.nbt.CompoundTag(
                                {
                                    "java_json": deps.nbt.ListTag(
                                        [
                                            deps.nbt.StringTag(
                                                json.dumps({"text": line})
                                            )
                                            for line in lines
                                        ]
                                    )
                                }
                            )
                        }
                    )
                }
            )
        ),
    )


def _entity(
    deps: SimpleNamespace,
    entity_id: str,
    x: float,
    y: float,
    z: float,
    extra: Optional[Dict[str, Any]] = None,
):
    """A mob for the chunk's native entity list.

    Motion, Rotation and a fixed UUID pair are written explicitly: the encoder
    does not invent them, and a mob without them is a mob the game refuses to
    load.  The UUID is derived from the position so it stays deterministic.
    """
    nbt = deps.nbt
    uuid_most = (int(x) * 0x9E3779B97F4A7C15 + int(z)) & 0x7FFFFFFFFFFFFFFF
    uuid_least = (int(y) * 0xC2B2AE3D27D4EB4F + int(x)) & 0x7FFFFFFFFFFFFFFF
    payload: Dict[str, Any] = {
        "id": nbt.StringTag(entity_id),
        "Motion": nbt.ListTag(
            [nbt.DoubleTag(0.0), nbt.DoubleTag(0.0), nbt.DoubleTag(0.0)]
        ),
        "Rotation": nbt.ListTag([nbt.FloatTag(0.0), nbt.FloatTag(0.0)]),
        "FallDistance": nbt.FloatTag(0.0),
        "Fire": nbt.ShortTag(-1),
        "Air": nbt.ShortTag(300),
        "OnGround": nbt.ByteTag(1),
        "Invulnerable": nbt.ByteTag(0),
        "PersistenceRequired": nbt.ByteTag(1),
        "UUIDMost": nbt.LongTag(uuid_most),
        "UUIDLeast": nbt.LongTag(uuid_least),
    }
    if extra:
        payload.update(extra)
    namespace, _, base_name = entity_id.partition(":")
    return deps.Entity(
        namespace, base_name, x, y, z, nbt.NamedTag(nbt.CompoundTag(payload))
    )


class FeaturePlacer:
    """Places the hand-authored landmarks near spawn.

    These exist so the world is a fixture as well as a demonstration: the
    Studio's inventory, NBT, entity and properties surfaces all have something
    real to read.
    """

    def __init__(self, deps: SimpleNamespace, palette: Palette, seed: int, size: int):
        self._deps = deps
        self._palette = palette
        self._seed = seed
        self._size = size
        self._level_palette = None
        self._pad_block_id = 0
        self._cached_blocks: Optional[List[dict]] = None
        self._cached_entities: Optional[List[dict]] = None
        self.placed_block_entities: List[Tuple[int, int, int, str]] = []
        self.placed_entities: List[Tuple[int, int, int, str]] = []

    def prepare(self, level, spawn: Tuple[int, int, int]) -> None:
        """Resolve every landmark once.

        Each definition costs a PyMCTranslate translation, and ``apply`` runs
        per chunk: resolving them inside the loop would repeat that work a
        thousand times to place five blocks.
        """
        self._level_palette = level.block_palette
        self._pad_block_id = self._palette.block_id("stone")
        self._cached_blocks = list(self._definitions(*spawn))
        self._cached_entities = list(self._entity_definitions(*spawn))

    def apply(
        self,
        blocks,
        heights,
        chunk_x: int,
        chunk_z: int,
    ) -> Tuple[List[Any], List[Any]]:
        """Return the block entities and entities that belong to this chunk."""
        deps = self._deps
        block_entities: List[Any] = []
        entities: List[Any] = []
        if self._cached_blocks is None or self._cached_entities is None:
            raise ExampleWorldError(
                "the feature placer was used before prepare() resolved its " "landmarks"
            )

        for definition in self._cached_blocks:
            world_x, world_y, world_z = definition["position"]
            if world_x // CHUNK_WIDTH != chunk_x or world_z // CHUNK_WIDTH != chunk_z:
                continue
            local_x = world_x - chunk_x * CHUNK_WIDTH
            local_z = world_z - chunk_z * CHUNK_WIDTH
            ground = int(heights[local_x, local_z])
            level = max(ground + 1, world_y)
            if level + 1 >= BUILD_HEIGHT:
                continue
            # Every landmark stands on a stone pad so a sloping surface cannot
            # leave it floating or buried.
            blocks[local_x, level - 1, local_z] = self._pad_block_id
            blocks[local_x, level, local_z] = definition["block_id"]
            if definition["block_entity"] is not None:
                # Absolute coordinates, not chunk-local ones.  The packer looks
                # a block entity up by the block's world position, and a
                # mismatch does not raise: PyMCTranslate quietly substitutes an
                # empty default, so the chest arrives with no items in it.
                block_entities.append(
                    definition["block_entity"](world_x, level, world_z)
                )
                self.placed_block_entities.append(
                    (world_x, level, world_z, definition["label"])
                )

        for definition in self._cached_entities:
            world_x, world_y, world_z = definition["position"]
            if int(world_x) // CHUNK_WIDTH != chunk_x:
                continue
            if int(world_z) // CHUNK_WIDTH != chunk_z:
                continue
            local_x = int(world_x) - chunk_x * CHUNK_WIDTH
            local_z = int(world_z) - chunk_z * CHUNK_WIDTH
            level = int(heights[local_x, local_z]) + 1
            entities.append(
                _entity(
                    deps,
                    definition["id"],
                    world_x + 0.5,
                    float(level),
                    world_z + 0.5,
                    definition.get("extra"),
                )
            )
            self.placed_entities.append(
                (int(world_x), level, int(world_z), definition["id"])
            )

        return block_entities, entities

    def bind_palette(self) -> None:
        self._palette_stone = self._palette.block_id("stone")

    def _definitions(self, spawn_x: int, spawn_y: int, spawn_z: int) -> Iterable[dict]:
        deps = self._deps
        palette = self._palette

        chest_contents = (
            (
                "Amulet starter kit",
                (
                    ("minecraft:diamond_pickaxe", 1),
                    ("minecraft:torch", 64),
                    ("minecraft:bread", 16),
                ),
            ),
            (
                "Amulet building blocks",
                (
                    ("minecraft:stone", 64),
                    ("minecraft:oak_stairs", 32),
                    ("minecraft:glass", 48),
                ),
            ),
            (
                "Amulet test fixture",
                (
                    ("minecraft:written_book", 1),
                    ("minecraft:golden_apple", 3),
                    ("minecraft:redstone", 24),
                ),
            ),
        )
        for index, (name, contents) in enumerate(chest_contents):
            block, block_entity = palette.universal_pair(
                "chest", 2, "chest", _chest_nbt(deps, name, contents)
            )
            yield {
                "label": f"chest:{name}",
                "position": (spawn_x + 2 + index * 2, spawn_y, spawn_z + 2),
                "block_id": self._palette_block_id(block),
                "block_entity": (
                    lambda x, y, z, source=block_entity: source.new_at_location(x, y, z)
                ),
            }

        furnace_block, furnace_entity = palette.universal_pair(
            "furnace",
            2,
            "furnace",
            deps.nbt.CompoundTag(
                {
                    "CustomName": deps.nbt.StringTag("Amulet furnace"),
                    "BurnTime": deps.nbt.ShortTag(0),
                    "CookTime": deps.nbt.ShortTag(0),
                    "CookTimeTotal": deps.nbt.ShortTag(200),
                    "Items": deps.nbt.ListTag(
                        [
                            _item(deps, "minecraft:iron_ore", 8, 0),
                            _item(deps, "minecraft:coal", 16, 1),
                        ]
                    ),
                }
            ),
        )
        yield {
            "label": "furnace",
            "position": (spawn_x - 2, spawn_y, spawn_z + 2),
            "block_id": self._palette_block_id(furnace_block),
            "block_entity": (
                lambda x, y, z, source=furnace_entity: source.new_at_location(x, y, z)
            ),
        }

        spawner_block, spawner_entity = palette.universal_pair(
            "mob_spawner",
            0,
            "mob_spawner",
            deps.nbt.CompoundTag(
                {
                    "SpawnData": deps.nbt.CompoundTag(
                        {"id": deps.nbt.StringTag("minecraft:pig")}
                    ),
                    "Delay": deps.nbt.ShortTag(20),
                    "MinSpawnDelay": deps.nbt.ShortTag(200),
                    "MaxSpawnDelay": deps.nbt.ShortTag(800),
                    "MaxNearbyEntities": deps.nbt.ShortTag(6),
                    "RequiredPlayerRange": deps.nbt.ShortTag(16),
                    "SpawnCount": deps.nbt.ShortTag(4),
                    "SpawnRange": deps.nbt.ShortTag(4),
                }
            ),
        )
        yield {
            "label": "mob_spawner",
            "position": (spawn_x - 4, spawn_y, spawn_z + 2),
            "block_id": self._palette_block_id(spawner_block),
            "block_entity": (
                lambda x, y, z, source=spawner_entity: source.new_at_location(x, y, z)
            ),
        }

        sign_lines = (
            "Amulet example",
            f"seed {self._seed}",
            f"{self._size} x {self._size}",
            GAME_VERSION_NAME,
        )
        yield {
            "label": "sign",
            "position": (spawn_x, spawn_y, spawn_z + 2),
            "block_id": palette.block_id("standing_sign", 0),
            "block_entity": (
                lambda x, y, z, lines=sign_lines: _sign_block_entity(
                    self._deps, lines, x, y, z
                )
            ),
        }

    def _entity_definitions(
        self, spawn_x: int, spawn_y: int, spawn_z: int
    ) -> Iterable[dict]:
        deps = self._deps
        yield {
            "id": "minecraft:cow",
            "position": (spawn_x + 3, spawn_y, spawn_z - 3),
            "extra": {
                "CustomName": deps.nbt.StringTag("Amulet cow"),
                "CustomNameVisible": deps.nbt.ByteTag(1),
                "Health": deps.nbt.FloatTag(10.0),
            },
        }
        yield {
            "id": "minecraft:sheep",
            "position": (spawn_x - 3, spawn_y, spawn_z - 3),
            "extra": {
                "CustomName": deps.nbt.StringTag("Amulet sheep"),
                "CustomNameVisible": deps.nbt.ByteTag(1),
                "Color": deps.nbt.ByteTag(14),
                "Health": deps.nbt.FloatTag(8.0),
            },
        }
        yield {
            "id": "minecraft:armor_stand",
            "position": (spawn_x, spawn_y, spawn_z - 4),
            "extra": {
                "CustomName": deps.nbt.StringTag("Amulet marker"),
                "CustomNameVisible": deps.nbt.ByteTag(1),
                "NoGravity": deps.nbt.ByteTag(1),
                "Invulnerable": deps.nbt.ByteTag(1),
            },
        }

    def _palette_block_id(self, universal_block) -> int:
        return self._level_palette.get_add_block(universal_block)


# ---------------------------------------------------------------------------
# level.dat
# ---------------------------------------------------------------------------


def build_level_dat(
    deps: SimpleNamespace,
    seed: int,
    size: int,
    data_version: int,
    spawn: Tuple[int, int, int],
):
    """Assemble the whole ``level.dat`` deterministically.

    ``AnvilFormat._create`` writes four keys and a wall-clock ``LastPlayed``.
    A world with no spawn and no game rules is not the example this release
    promises, so the tag is rebuilt in full here.
    """
    nbt = deps.nbt
    spawn_x, spawn_y, spawn_z = spawn
    data = {
        "BorderCenterX": nbt.DoubleTag(0.0),
        "BorderCenterZ": nbt.DoubleTag(0.0),
        "BorderDamagePerBlock": nbt.DoubleTag(0.2),
        "BorderSafeZone": nbt.DoubleTag(5.0),
        "BorderSize": nbt.DoubleTag(60000000.0),
        "BorderSizeLerpTarget": nbt.DoubleTag(60000000.0),
        "BorderSizeLerpTime": nbt.LongTag(0),
        "BorderWarningBlocks": nbt.DoubleTag(5.0),
        "BorderWarningTime": nbt.DoubleTag(15.0),
        "DataVersion": nbt.IntTag(data_version),
        "DayTime": nbt.LongTag(6000),
        "Difficulty": nbt.ByteTag(2),
        "DifficultyLocked": nbt.ByteTag(0),
        "GameRules": nbt.CompoundTag(
            {key: nbt.StringTag(value) for key, value in GAME_RULES}
        ),
        "GameType": nbt.IntTag(1),
        "LastPlayed": nbt.LongTag(FIXED_EPOCH_MILLISECONDS),
        "LevelName": nbt.StringTag(WORLD_NAME),
        "MapFeatures": nbt.ByteTag(0),
        "RandomSeed": nbt.LongTag(seed),
        "SizeOnDisk": nbt.LongTag(0),
        "SpawnX": nbt.IntTag(spawn_x),
        "SpawnY": nbt.IntTag(spawn_y),
        "SpawnZ": nbt.IntTag(spawn_z),
        "Time": nbt.LongTag(0),
        "Version": nbt.CompoundTag(
            {
                "Id": nbt.IntTag(data_version),
                "Name": nbt.StringTag(GAME_VERSION_NAME),
                "Snapshot": nbt.ByteTag(0),
            }
        ),
        "allowCommands": nbt.ByteTag(1),
        "clearWeatherTime": nbt.IntTag(0),
        "generatorName": nbt.StringTag("default"),
        "generatorOptions": nbt.StringTag(""),
        "generatorVersion": nbt.IntTag(1),
        "hardcore": nbt.ByteTag(0),
        "initialized": nbt.ByteTag(1),
        "raining": nbt.ByteTag(0),
        "rainTime": nbt.IntTag(0),
        "thundering": nbt.ByteTag(0),
        "thunderTime": nbt.IntTag(0),
        "version": nbt.IntTag(19133),
    }
    # Sorted keys so serialisation cannot depend on insertion order.
    ordered = nbt.CompoundTag({key: data[key] for key in sorted(data)})
    return nbt.NamedTag(nbt.CompoundTag({"Data": ordered}))


def write_level_dat(deps: SimpleNamespace, world_directory: Path, tag) -> None:
    """Write ``level.dat`` gzipped with a zero mtime, so the bytes are stable."""
    raw = tag.save_to(compressed=False)
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=9, mtime=0) as handle:
        handle.write(raw)
    (world_directory / "level.dat").write_bytes(buffer.getvalue())


# ---------------------------------------------------------------------------
# Determinism normalisation
# ---------------------------------------------------------------------------


def normalise_region_timestamps(world_directory: Path) -> int:
    """Replace the wall-clock region timestamp table with a fixed epoch."""
    region_directory = world_directory / "region"
    if not region_directory.is_dir():
        raise ExampleWorldError(
            f"no region directory was written at {region_directory}; the world "
            "is incomplete"
        )
    normalised = 0
    for region_path in sorted(region_directory.glob("*.mca")):
        data = bytearray(region_path.read_bytes())
        if len(data) < REGION_HEADER_BYTES * 2:
            raise ExampleWorldError(
                f"region file {region_path.name} is {len(data)} bytes, which is "
                "shorter than an Anvil header; the world is incomplete"
            )
        for slot in range(REGION_SLOT_COUNT):
            location_offset = slot * 4
            location = data[location_offset : location_offset + 4]
            occupied = any(location)
            timestamp_offset = REGION_HEADER_BYTES + slot * 4
            data[timestamp_offset : timestamp_offset + 4] = struct.pack(
                ">I", FIXED_EPOCH_SECONDS if occupied else 0
            )
        region_path.write_bytes(bytes(data))
        normalised += 1
    if not normalised:
        raise ExampleWorldError(
            f"no .mca region files were written under {region_directory}; the "
            "world is incomplete"
        )
    return normalised


def strip_runtime_files(world_directory: Path) -> None:
    """Drop files that hold a lock time rather than world data."""
    for name in ("session.lock", "level.dat_old"):
        candidate = world_directory / name
        if candidate.exists():
            candidate.unlink()


def write_zip(world_directory: Path, destination: Path, readme: str) -> int:
    """Write the world into a byte-stable zip.

    Fixed member order, a fixed DOS timestamp and a fixed create-system: the
    defaults for all three vary with the run and the host operating system.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    members: List[Tuple[str, bytes]] = [
        (f"{WORLD_DIRECTORY_NAME}/README.md", readme.encode("utf-8"))
    ]
    for path in sorted(world_directory.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(world_directory).as_posix()
        members.append((f"{WORLD_DIRECTORY_NAME}/{relative}", path.read_bytes()))

    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name, payload in sorted(members, key=lambda member: member[0]):
            info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archive.writestr(info, payload)
    return destination.stat().st_size


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------


def resolve_commit(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    for variable in ("GITHUB_SHA", "AMULET_EXAMPLE_WORLD_COMMIT"):
        value = os.environ.get(variable)
        if value:
            return value
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def build_readme(summary: dict) -> str:
    command = summary["command"]
    return f"""# {WORLD_NAME}

The example world published with every Amulet Map Editor release. It is
generated, not hand-built, so the same seed always produces the same world.

| Fact | Value |
| --- | --- |
| Seed | `{summary["seed"]}` |
| Requested size | {summary["size"]} x {summary["size"]} blocks |
| Generated size | {summary["generated_size"]} x {summary["generated_size"]} blocks |
| Chunks | {summary["chunk_count"]} ({summary["chunk_span"]} x {summary["chunk_span"]}) |
| Non-air blocks | {summary["block_count"]} |
| Blocks in bounds | {summary["volume"]} |
| Minecraft format | Java Edition {GAME_VERSION_NAME} (Anvil, DataVersion {summary["data_version"]}, level format 19133) |
| World spawn | {summary["spawn"][0]}, {summary["spawn"][1]}, {summary["spawn"][2]} |
| Sea level | {SEA_LEVEL} |
| Generator commit | `{summary["commit"]}` |

## Regenerating it

```
{command}
```

On Windows, run it as `py -3.11 scripts/generate_example_world.py ...`; the
generator needs the interpreter that has amulet-core installed. The archive's
name does not affect its contents.

That command reproduces this world exactly. The seed is a fixed constant, the
noise is hashed from block coordinates rather than drawn from a stream, and the
two wall-clock values the Anvil writer stamps into a save -- `LastPlayed` and
the region timestamp table -- are normalised before the archive is written.
`session.lock` is removed for the same reason. The archive bytes are therefore
stable for a given seed, size and generator commit on a given zlib build.

## What is in it

Terrain comes from five octaves of value noise: bedrock at the floor, stone
below a four-block dirt band, grass on the surface, sand along the shoreline,
gravel under the deeper water, and water filled to y={SEA_LEVEL}. Oaks, tall grass and
flowers are scattered on the land.

Near spawn there are landmarks the editor's own surfaces read:

* three chests with named inventories,
* a furnace with contents,
* a mob spawner,
* a sign whose four lines record the seed and size,
* three entities -- a cow, a sheep and an armour stand, each with a custom name,
* a set of game rules in `level.dat`,
* a world spawn at {summary["spawn"][0]}, {summary["spawn"][1]}, {summary["spawn"][2]}.

## Opening it

Unzip it and open the `{WORLD_DIRECTORY_NAME}` folder with Amulet Map Editor, or
drop that folder into the Minecraft `saves` directory. It is an ordinary Java
1.12.2 save with nothing unusual in it.
"""


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _log(message: str) -> None:
    print(message, flush=True)


def generate_world(
    deps: SimpleNamespace,
    world_directory: Path,
    seed: int,
    size: int,
) -> dict:
    """Build the world on disk and return the facts the README needs."""
    numpy = deps.numpy
    amulet = deps.amulet

    chunk_span = -(-size // CHUNK_WIDTH)
    generated_size = chunk_span * CHUNK_WIDTH
    origin_chunk = -(chunk_span // 2)
    origin_block = origin_chunk * CHUNK_WIDTH
    chunk_count = chunk_span * chunk_span

    bounds = deps.SelectionGroup(
        deps.SelectionBox(
            (origin_block, 0, origin_block),
            (origin_block + generated_size, 256, origin_block + generated_size),
        )
    )

    if world_directory.exists():
        shutil.rmtree(world_directory)
    world_directory.parent.mkdir(parents=True, exist_ok=True)

    wrapper = deps.AnvilFormat(str(world_directory))
    try:
        wrapper.create_and_open(PLATFORM, GAME_VERSION, bounds, True)
    except Exception as error:  # noqa: BLE001 - reported verbatim below
        raise ExampleWorldError(
            f"cannot create a level: amulet-core refused to create a "
            f"{PLATFORM} {GAME_VERSION_NAME} world at {world_directory}: "
            f"{type(error).__name__}: {error}"
        ) from error
    data_version = int(
        wrapper.root_tag.compound.get_compound("Data").get_int("DataVersion").py_int
    )
    wrapper.close()

    if not (world_directory / "level.dat").is_file():
        raise ExampleWorldError(
            f"cannot create a level: amulet-core reported success but wrote no "
            f"level.dat at {world_directory / 'level.dat'}"
        )

    level = amulet.load_level(str(world_directory))
    dimension = "minecraft:overworld"
    try:
        palette = Palette(deps, level)
        terrain = TerrainBuilder(deps, palette, seed)
        features = FeaturePlacer(deps, palette, seed, size)

        _log(f"Height field: {generated_size} x {generated_size} columns")
        heights = build_height_field(deps, seed, origin_block, generated_size)

        spawn = choose_spawn(deps, heights, origin_block)
        _log(f"World spawn: {spawn[0]}, {spawn[1]}, {spawn[2]}")
        features.prepare(level, spawn)

        block_count = 0
        block_entity_count = 0
        container_count = 0
        entity_count = 0
        report_every = max(1, chunk_count // 20)
        started = time.perf_counter()

        for index in range(chunk_count):
            chunk_x = origin_chunk + index // chunk_span
            chunk_z = origin_chunk + index % chunk_span
            slice_x = slice(
                (chunk_x - origin_chunk) * CHUNK_WIDTH,
                (chunk_x - origin_chunk + 1) * CHUNK_WIDTH,
            )
            slice_z = slice(
                (chunk_z - origin_chunk) * CHUNK_WIDTH,
                (chunk_z - origin_chunk + 1) * CHUNK_WIDTH,
            )
            chunk_heights = heights[slice_x, slice_z]

            blocks = terrain.build_chunk_blocks(chunk_heights, chunk_x, chunk_z)
            terrain.decorate_chunk(blocks, chunk_heights, chunk_x, chunk_z)
            block_entities, entities = features.apply(
                blocks, chunk_heights, chunk_x, chunk_z
            )

            chunk = deps.Chunk(chunk_x, chunk_z)
            chunk.biomes.convert_to_2d()
            chunk.blocks[:, 0:BUILD_HEIGHT, :] = blocks
            chunk.biomes[:, :] = terrain.biome_map(chunk_heights)
            chunk.status = "full"
            for block_entity in block_entities:
                chunk.block_entities.insert(block_entity)
                block_entity_count += 1
                if block_entity.base_name in ("chest", "furnace"):
                    container_count += 1
            if entities:
                chunk._native_version = (PLATFORM, data_version)
                for entity in entities:
                    chunk._native_entities.append(entity)
                    entity_count += 1
            chunk.changed = True
            level.put_chunk(chunk, dimension)

            block_count += int(numpy.count_nonzero(blocks != terrain.air))
            if (index + 1) % report_every == 0 or index + 1 == chunk_count:
                elapsed = time.perf_counter() - started
                _log(
                    f"Built {index + 1}/{chunk_count} chunks "
                    f"({100 * (index + 1) // chunk_count}%) in {elapsed:.1f}s"
                )

        if block_entity_count == 0 or entity_count == 0:
            raise ExampleWorldError(
                "the feature pass placed "
                f"{block_entity_count} block entities and {entity_count} "
                "entities; an example world must carry both"
            )

        _log("Saving chunks")
        save_started = time.perf_counter()
        last_reported = [0]

        def report(chunk_index: int, total: int) -> None:
            step = max(1, total // 10)
            if chunk_index - last_reported[0] < step and chunk_index != total:
                return
            last_reported[0] = chunk_index
            elapsed = time.perf_counter() - save_started
            _log(f"Saved {chunk_index}/{total} chunks in {elapsed:.1f}s")

        level.save(progress_callback=report)
    finally:
        level.close()

    return {
        "seed": seed,
        "size": size,
        "generated_size": generated_size,
        "chunk_span": chunk_span,
        "chunk_count": chunk_count,
        "origin_block": origin_block,
        "block_count": block_count,
        "block_entity_count": block_entity_count,
        "container_count": container_count,
        "entity_count": entity_count,
        "volume": generated_size * generated_size * BUILD_HEIGHT,
        "data_version": data_version,
        "spawn": spawn,
        "dimension": dimension,
    }


def verify_world(deps: SimpleNamespace, world_directory: Path, summary: dict) -> dict:
    """Reopen the world and prove it is readable before it is packaged."""
    amulet = deps.amulet
    dimension = summary["dimension"]
    level = amulet.load_level(str(world_directory))
    try:
        coordinates = level.all_chunk_coords(dimension)
        if len(coordinates) != summary["chunk_count"]:
            raise ExampleWorldError(
                f"the saved world holds {len(coordinates)} chunks in "
                f"{dimension} but {summary['chunk_count']} were generated; the "
                "world is incomplete"
            )
        spawn_x, spawn_y, spawn_z = summary["spawn"]
        samples = []
        for label, (x, y, z) in (
            ("bedrock floor", (spawn_x, 0, spawn_z)),
            ("underground", (spawn_x, 20, spawn_z)),
            ("ground under spawn", (spawn_x, spawn_y - 1, spawn_z)),
            ("world spawn", (spawn_x, spawn_y, spawn_z)),
            ("first chest", (spawn_x + 2, spawn_y, spawn_z + 2)),
            ("sign", (spawn_x, spawn_y, spawn_z + 2)),
            (
                "map corner",
                (summary["origin_block"], SEA_LEVEL, summary["origin_block"]),
            ),
        ):
            block, _ = level.get_version_block(
                x, y, z, dimension, (PLATFORM, GAME_VERSION)
            )
            samples.append((label, (x, y, z), str(block)))

        # Read every landmark back.  A block entity whose coordinates do not
        # match its block is not an error at write time -- the packer swaps in
        # an empty default -- so the only way to know the payload survived is
        # to look at it.
        sign_text: Optional[List[str]] = None
        containers: List[Tuple[str, int, int, int, int]] = []
        entities_found = 0
        for chunk_x, chunk_z in sorted(coordinates):
            chunk = level.get_chunk(chunk_x, chunk_z, dimension)
            entities_found += len(chunk._native_entities)
            for block_entity in chunk.block_entities:
                tags = block_entity.nbt.compound.get_compound("utags")
                if block_entity.base_name == "sign":
                    lines = tags.get_compound("front_text").get_list("java_json")
                    sign_text = [str(line.py_str) for line in lines]
                elif block_entity.base_name in ("chest", "furnace"):
                    containers.append(
                        (
                            block_entity.base_name,
                            block_entity.x,
                            block_entity.y,
                            block_entity.z,
                            len(tags.get_list("Items")),
                        )
                    )

        if not sign_text or f"seed {summary['seed']}" not in " ".join(sign_text):
            raise ExampleWorldError(
                f"the sign did not survive the save: read back {sign_text!r}"
            )
        if len(containers) != summary["container_count"]:
            raise ExampleWorldError(
                f"{len(containers)} containers survived the save but "
                f"{summary['container_count']} were placed"
            )
        empty = [entry for entry in containers if entry[4] == 0]
        if empty:
            raise ExampleWorldError(
                "these containers came back empty, so their block entity NBT "
                f"did not survive the save: {empty}"
            )
        if entities_found != summary["entity_count"]:
            raise ExampleWorldError(
                f"{entities_found} entities survived the save but "
                f"{summary['entity_count']} were placed"
            )

        bounds = level.bounds(dimension)
    finally:
        level.close()
    return {
        "samples": samples,
        "sign_text": sign_text,
        "containers": containers,
        "bounds": str(bounds),
    }


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def positive_size(raw: str) -> int:
    try:
        value = int(raw, 10)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--size must be a whole number of blocks, not {raw!r}"
        ) from None
    if not MINIMUM_SIZE <= value <= MAXIMUM_SIZE:
        raise argparse.ArgumentTypeError(
            f"--size must be between {MINIMUM_SIZE} and {MAXIMUM_SIZE} blocks; "
            f"{value} is outside that range"
        )
    return value


def seed_value(raw: str) -> int:
    try:
        return int(raw, 10)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--seed must be a whole number, not {raw!r}"
        ) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate_example_world.py",
        description=(
            "Generate the deterministic example Minecraft world published with "
            "every release."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "The same --seed and --size always produce the same world, so a "
            "release can be reproduced from its notes."
        ),
    )
    parser.add_argument(
        "--seed",
        type=seed_value,
        default=DEFAULT_SEED,
        help=f"world seed; a fixed constant by default ({DEFAULT_SEED})",
    )
    parser.add_argument(
        "--size",
        type=positive_size,
        default=DEFAULT_SIZE,
        help=(
            f"width and depth in blocks, rounded up to whole chunks "
            f"(default {DEFAULT_SIZE}, allowed {MINIMUM_SIZE}-{MAXIMUM_SIZE})"
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("dist") / "example-world.zip",
        help="path of the zip to write (default dist/example-world.zip)",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="directory to build the world in; a temporary one by default",
    )
    parser.add_argument(
        "--commit",
        default=None,
        help="generator commit recorded in the README; detected from git by default",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="also write the run's facts to this JSON file",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    try:
        deps = load_dependencies()
    except ExampleWorldError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    destination = arguments.out.expanduser().resolve()
    commit = resolve_commit(arguments.commit)
    # A canonical output name, not the caller's path: the archive's name has no
    # effect on its contents, and embedding a temporary directory here would
    # make two runs of the same seed differ in the README alone.
    command = (
        f"python scripts/generate_example_world.py "
        f"--seed {arguments.seed} --size {arguments.size} "
        f"--out example-world.zip"
    )

    temporary: Optional[tempfile.TemporaryDirectory] = None
    if arguments.work_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="amulet-example-world-")
        work_root = Path(temporary.name)
    else:
        work_root = arguments.work_dir.expanduser().resolve()
        work_root.mkdir(parents=True, exist_ok=True)
    world_directory = work_root / WORLD_DIRECTORY_NAME

    started = time.perf_counter()
    try:
        _log(
            f"Generating {arguments.size} x {arguments.size} blocks, seed "
            f"{arguments.seed}, into {world_directory}"
        )
        summary = generate_world(deps, world_directory, arguments.seed, arguments.size)
        verification = verify_world(deps, world_directory, summary)
        for label, position, block in verification["samples"]:
            _log(f"  {label} at {position}: {block}")
        for kind, x, y, z, item_count in verification["containers"]:
            _log(f"  {kind} at {x},{y},{z} kept {item_count} item stack(s)")
        _log(f"  sign reads: {verification['sign_text']}")
        _log(f"  bounds: {verification['bounds']}")

        summary["commit"] = commit
        summary["command"] = command
        write_level_dat(
            deps,
            world_directory,
            build_level_dat(
                deps,
                arguments.seed,
                arguments.size,
                summary["data_version"],
                summary["spawn"],
            ),
        )
        regions = normalise_region_timestamps(world_directory)
        strip_runtime_files(world_directory)
        _log(f"Normalised {regions} region file(s) for reproducibility")

        zip_bytes = write_zip(world_directory, destination, build_readme(summary))
    except ExampleWorldError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001 - never exit zero on a half world
        print(
            f"error: the example world was not completed: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1
    finally:
        if temporary is not None:
            temporary.cleanup()

    elapsed = time.perf_counter() - started
    summary["zip_bytes"] = zip_bytes
    summary["zip_path"] = str(destination)
    summary["elapsed_seconds"] = round(elapsed, 3)
    summary["sign_text"] = verification["sign_text"]

    _log(
        f"Wrote {destination} ({zip_bytes} bytes) -- {summary['chunk_count']} "
        f"chunks, {summary['block_count']} non-air blocks, "
        f"{summary['block_entity_count']} block entities, "
        f"{summary['entity_count']} entities, in {elapsed:.1f}s"
    )

    if arguments.summary_json is not None:
        arguments.summary_json.parent.mkdir(parents=True, exist_ok=True)
        arguments.summary_json.write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
