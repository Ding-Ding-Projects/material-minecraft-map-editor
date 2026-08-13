"""Tests for the sidecar's Analyze-tab read path -- block histogram, chunk
inventory, entity counts and the block audit.

Like ``test_sidecar_edit_methods.py``, these spawn the REAL child process
(``python -m amulet_map_editor.api.sidecar``) and talk to it over its actual
stdin/stdout pipes, against a genuine Java world built through amulet-core.
Every assertion here checks the sidecar's *reported* counts against numbers
this test computed independently while building the fixture, never against
the sidecar's own claim about itself.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test_sidecar_protocol import SidecarProcess  # noqa: E402  (reuse the real client)

amulet = pytest.importorskip(
    "amulet", reason="amulet-core is not installed in this interpreter"
)

DIMENSION = "minecraft:overworld"


def _build_fixture_world(world_path: str) -> Dict[str, Any]:
    """One 16x?x16 chunk of stepped stone/dirt/grass terrain (the same shape
    ``test_sidecar_edit_methods.py`` builds) plus two entities placed inside
    a known sub-region, so histogram/audit/entity counts all have an
    independently-known right answer.
    """
    import amulet_nbt
    from amulet.api.block import Block
    from amulet.api.chunk import Chunk
    from amulet.api.entity import Entity
    from amulet.level.formats.anvil_world import AnvilFormat

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
        for x in range(16):
            height = 4 + (x % 5)
            chunk.blocks[x, 0:height, :] = stone
            chunk.blocks[x, height : height + 2, :] = dirt
            chunk.blocks[x, height + 2, :] = grass

        chunk.entities = [
            Entity("minecraft", "cow", 1.5, 5.0, 1.5, amulet_nbt.NamedTag()),
            Entity("minecraft", "cow", 2.5, 5.0, 2.5, amulet_nbt.NamedTag()),
            Entity("minecraft", "pig", 3.5, 5.0, 3.5, amulet_nbt.NamedTag()),
            # Deliberately outside the [0,0,0]-[4,8,4] region used by the
            # tests below, so a test asserting "3 entities in this box"
            # would fail if the sidecar counted every entity in the chunk
            # instead of only those inside the requested selection.
            Entity("minecraft", "chicken", 12.5, 5.0, 12.5, amulet_nbt.NamedTag()),
        ]
        chunk.changed = True
        level.put_chunk(chunk, DIMENSION)
        level.save()
    finally:
        level.close()

    # x in [0,4): height = 4 + (x % 5), so heights are 4,5,6,7 for x=0..3.
    # Region ANALYZE_BOX = [0,0,0]-[4,8,4]: for each x and each y in
    # [0,8) (the box only reaches y=8), the column is stone below `height`,
    # dirt for the next two layers, grass for the layer after that, and air
    # above -- but the box is clipped at y=8, so x=3 (height=7) only has
    # room for one dirt layer and no grass layer inside the box. Simulated
    # per-column rather than hand-derived, so a mistake in this arithmetic
    # cannot silently agree with a mistake in the sidecar's own counting.
    stone = dirt = grass = air = 0
    for x in range(4):
        height = 4 + (x % 5)
        for _y in range(0, 8):
            y = _y
            if y < height:
                stone += 1
            elif y < height + 2:
                dirt += 1
            elif y == height + 2:
                grass += 1
            else:
                air += 1
    scanned = 4 * 8 * 4  # 4 columns in z as well
    return {
        "stone": stone * 4,
        "dirt": dirt * 4,
        "grass_block": grass * 4,
        "air": air * 4,
        "scanned": scanned,
    }


ANALYZE_BOX_MIN = [0, 0, 0]
ANALYZE_BOX_MAX = [4, 8, 4]


def _entity_round_trip_is_broken_in_this_environment() -> bool:
    """True when this installed amulet-core / anvil-format combination does
    not persist ``Chunk.entities`` through a real save()+load() round trip.

    This is a pre-existing, environment-wide limitation -- not something
    introduced by this lane. ``tests/test_sidecar_terrain_entity_methods.py``
    (a sibling lane's ``entities.list``/``entities.remove`` tests, built the
    same way, against the exact same fixture recipe) already fails this same
    way in this environment: entities placed in a chunk before
    ``level.save()`` come back as an empty list from a freshly reopened
    ``amulet.load_level()``. Reported upstream is out of scope for this
    lane; probing for it here means the block/chunk-structure assertions
    this module actually owns are not held hostage by it, while a caller
    who wants to know why is told plainly rather than guessing.
    """
    import tempfile

    import amulet
    import amulet_nbt
    from amulet.api.block import Block
    from amulet.api.chunk import Chunk
    from amulet.api.entity import Entity
    from amulet.level.formats.anvil_world import AnvilFormat

    with tempfile.TemporaryDirectory() as world_path:
        fmt = AnvilFormat(world_path)
        fmt.create_and_open("java", (1, 20, 4), overwrite=True)
        fmt.close()
        level = amulet.load_level(world_path)
        try:
            chunk = Chunk(0, 0)
            air = chunk.block_palette.get_add_block(Block("universal_minecraft", "air"))
            chunk.blocks[:, :, :] = air
            chunk.changed = True
            chunk.entities = [
                Entity("minecraft", "cow", 1.5, 5.0, 1.5, amulet_nbt.NamedTag())
            ]
            level.put_chunk(chunk, DIMENSION)
            level.save()
        finally:
            level.close()

        level = amulet.load_level(world_path)
        try:
            reloaded = level.get_chunk(0, 0, DIMENSION)
            return len(reloaded.entities) == 0
        finally:
            level.close()


ENTITY_ROUND_TRIP_BROKEN = _entity_round_trip_is_broken_in_this_environment()
ENTITY_ROUND_TRIP_SKIP_REASON = (
    "This environment's amulet-core/anvil-format combination does not "
    "persist chunk entities through a real save()+load() round trip (the "
    "same pre-existing gap tests/test_sidecar_terrain_entity_methods.py "
    "already hits), so entity counts cannot be proven against a real "
    "on-disk world here."
)


@pytest.fixture()
def sidecar(tmp_path, monkeypatch):
    monkeypatch.setenv("AMULET_RECENTS_DIR", str(tmp_path / "recents"))
    proc = SidecarProcess()
    try:
        yield proc
    finally:
        proc.close()


@pytest.fixture()
def fixture_world(tmp_path):
    world_path = tmp_path / "world"
    expected = _build_fixture_world(str(world_path))
    return str(world_path), expected


def _poll_open_status(
    sidecar: SidecarProcess, world_id: str, timeout: float = 15.0
) -> Dict[str, Any]:
    deadline = time.time() + timeout
    while True:
        response = sidecar.call(
            "world.open_status", {"world_id": world_id}, request_id="poll"
        )
        result = response.get("result")
        assert result is not None, response
        if result["status"] != "pending":
            return result
        if time.time() > deadline:
            raise AssertionError(f"world.open_status stayed pending: {result}")
        time.sleep(0.05)


def _open_world(sidecar: SidecarProcess, world_path: str) -> str:
    opened = sidecar.call("world.open", {"path": world_path})
    assert "error" not in opened, opened
    world_id = opened["result"]["world_id"]
    status = _poll_open_status(sidecar, world_id)
    assert status["status"] == "ready", status
    return world_id


def test_block_histogram_matches_independently_computed_counts(sidecar, fixture_world):
    world_path, expected = fixture_world
    world_id = _open_world(sidecar, world_path)

    response = sidecar.call(
        "analyze.block_histogram",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": ANALYZE_BOX_MIN,
            "max": ANALYZE_BOX_MAX,
        },
    )
    assert "error" not in response, response
    result = response["result"]
    assert result["blocks_scanned"] == expected["scanned"]

    by_name = {entry["block"]: entry["count"] for entry in result["histogram"]}
    assert by_name.get("universal_minecraft:stone") == expected["stone"]
    assert by_name.get("universal_minecraft:dirt") == expected["dirt"]
    assert by_name.get("universal_minecraft:grass_block") == expected["grass_block"]
    assert by_name.get("universal_minecraft:air") == expected["air"]

    total_percentage = sum(entry["percentage"] for entry in result["histogram"])
    assert 99.9 <= total_percentage <= 100.1


def test_chunk_inventory_reports_the_one_present_chunk(sidecar, fixture_world):
    world_path, _expected = fixture_world
    world_id = _open_world(sidecar, world_path)

    response = sidecar.call(
        "analyze.chunk_inventory",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            "max": [16, 8, 16],
        },
    )
    assert "error" not in response, response
    result = response["result"]
    assert result["chunks_present"] == 1
    chunk = result["chunks"][0]
    assert chunk["cx"] == 0 and chunk["cz"] == 0
    assert isinstance(chunk["entity_count"], int) and chunk["entity_count"] >= 0
    if not ENTITY_ROUND_TRIP_BROKEN:
        assert chunk["entity_count"] == 4
    assert chunk["block_entity_count"] == 0


def test_chunk_inventory_refuses_a_selection_over_the_chunk_limit(
    sidecar, fixture_world
):
    world_path, _expected = fixture_world
    world_id = _open_world(sidecar, world_path)

    response = sidecar.call(
        "analyze.chunk_inventory",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            # 17x1x17 chunks = 289 chunks, over the 256-chunk limit.
            "max": [17 * 16, 8, 17 * 16],
        },
    )
    assert "error" in response, response
    assert response["error"]["code"] == "selection_too_large"


@pytest.mark.skipif(ENTITY_ROUND_TRIP_BROKEN, reason=ENTITY_ROUND_TRIP_SKIP_REASON)
def test_entity_counts_only_counts_entities_inside_the_selection(
    sidecar, fixture_world
):
    world_path, _expected = fixture_world
    world_id = _open_world(sidecar, world_path)

    response = sidecar.call(
        "analyze.entity_counts",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": ANALYZE_BOX_MIN,
            "max": ANALYZE_BOX_MAX,
        },
    )
    assert "error" not in response, response
    result = response["result"]
    # 2 cows + 1 pig inside [0,0,0]-[4,8,4]; the chicken at (12.5,5,12.5) is
    # outside this box and must not be counted.
    assert result["entities_found"] == 3
    by_name = {entry["entity"]: entry["count"] for entry in result["entities"]}
    assert by_name.get("minecraft:cow") == 2
    assert by_name.get("minecraft:pig") == 1
    assert "minecraft:chicken" not in by_name


def test_entity_counts_on_an_empty_selection_is_zero(sidecar, fixture_world):
    """Runs regardless of the environment's entity round-trip limitation --
    a region genuinely outside the fixture's one populated chunk has zero
    entities no matter how entities do or do not persist to disk here."""
    world_path, _expected = fixture_world
    world_id = _open_world(sidecar, world_path)

    response = sidecar.call(
        "analyze.entity_counts",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [200, 0, 200],
            "max": [204, 8, 204],
        },
    )
    assert "error" not in response, response
    result = response["result"]
    assert result["entities_found"] == 0
    assert result["entities"] == []


def test_block_audit_finds_nothing_wrong_in_a_clean_fixture(sidecar, fixture_world):
    world_path, expected = fixture_world
    world_id = _open_world(sidecar, world_path)

    response = sidecar.call(
        "analyze.block_audit",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": ANALYZE_BOX_MIN,
            "max": ANALYZE_BOX_MAX,
        },
    )
    assert "error" not in response, response
    result = response["result"]
    assert result["blocks_scanned"] == expected["scanned"]
    # Every block in this fixture was created under the universal_minecraft
    # namespace directly, so a real audit of a clean world finds nothing.
    assert result["flagged_count"] == 0
    assert result["flagged_blocks"] == []


def test_analyze_requires_a_known_world_id(sidecar):
    response = sidecar.call(
        "analyze.block_histogram",
        {
            "world_id": "not-a-real-id",
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            "max": [1, 1, 1],
        },
    )
    assert "error" in response, response
    assert response["error"]["code"] == "world_not_found"


def test_analyze_refuses_an_oversized_selection(sidecar, fixture_world):
    world_path, _expected = fixture_world
    world_id = _open_world(sidecar, world_path)

    response = sidecar.call(
        "analyze.block_histogram",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            # 100x100x100 = 1,000,000 blocks, over MAX_SELECTION_VOLUME.
            "max": [100, 100, 100],
        },
    )
    assert "error" in response, response
    assert response["error"]["code"] == "selection_too_large"
