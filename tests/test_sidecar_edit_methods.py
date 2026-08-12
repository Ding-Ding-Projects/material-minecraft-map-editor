"""Tests for the sidecar's write path -- fill, replace, undo, redo, save.

Like ``test_sidecar_world_methods.py``, these spawn the REAL child process
(``python -m amulet_map_editor.api.sidecar``) and talk to it over its actual
stdin/stdout pipes, against a genuine Java world built through amulet-core
(the same way ``scripts/make_viewport_fixture_world.py`` builds its fixture).

Verification never trusts the sidecar's own report of what it wrote. Every
test that claims a change happened (or did not happen) closes the sidecar's
handle -- which discards any unsaved in-memory change -- and reopens the
world file directly with ``amulet.load_level`` in this test process to read
the real on-disk blocks back. That is what actually proves a fill landed, an
undo restored the previous state, or a write without ``world.save`` never
reached disk at all.
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

# A region that is real stone in every column of the fixture chunk built by
# ``_build_fixture_world`` below: height = 4 + (x % 5) is always >= 4, so
# y in [0, 2) is stone for every x in [0, 4) and every z in [0, 4).
STONE_MIN = [0, 0, 0]
STONE_MAX = [4, 2, 4]
STONE_VOLUME = 4 * 2 * 4  # 32


def _build_fixture_world(world_path: str) -> None:
    """The same stepped-terrain fixture ``scripts/make_viewport_fixture_world.py``
    builds, inlined here so this test module owns its own fixture rather than
    importing a scripts/ module by path.
    """
    from amulet.api.block import Block
    from amulet.api.chunk import Chunk
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
        chunk.changed = True
        level.put_chunk(chunk, DIMENSION)
        level.save()
    finally:
        level.close()


@pytest.fixture()
def sidecar(tmp_path, monkeypatch):
    monkeypatch.setenv("AMULET_RECENTS_DIR", str(tmp_path / "recents"))
    proc = SidecarProcess()
    try:
        yield proc
    finally:
        proc.close()


@pytest.fixture()
def fixture_world_path(tmp_path) -> str:
    """A fresh, real Java world per test -- each test may write to it."""
    world_path = tmp_path / "world"
    _build_fixture_world(str(world_path))
    return str(world_path)


def _poll_open_status(sidecar: SidecarProcess, world_id: str, timeout: float = 15.0) -> Dict[str, Any]:
    deadline = time.time() + timeout
    while True:
        response = sidecar.call("world.open_status", {"world_id": world_id}, request_id="poll")
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


def _read_block_names_directly(world_path: str, coords) -> Dict[tuple, str]:
    """Bypass the sidecar entirely and read real on-disk blocks with amulet."""
    level = amulet.load_level(world_path)
    try:
        names = {}
        for x, y, z in coords:
            names[(x, y, z)] = level.get_block(x, y, z, DIMENSION).base_name
        return names
    finally:
        level.close()


def _stone_region_coords():
    for x in range(STONE_MIN[0], STONE_MAX[0]):
        for y in range(STONE_MIN[1], STONE_MAX[1]):
            for z in range(STONE_MIN[2], STONE_MAX[2]):
                yield (x, y, z)


def test_fill_is_refused_without_confirmation(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)

    response = sidecar.call(
        "world.fill",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": STONE_MIN,
            "max": STONE_MAX,
            "block": "universal_minecraft:diamond_block",
            # no 'confirm' at all
        },
        request_id=2,
    )
    assert response["error"]["code"] == "confirmation_required", response

    response = sidecar.call(
        "world.fill",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": STONE_MIN,
            "max": STONE_MAX,
            "block": "universal_minecraft:diamond_block",
            "confirm": False,
        },
        request_id=3,
    )
    assert response["error"]["code"] == "confirmation_required", response

    sidecar.call("world.close", {"world_id": world_id}, request_id=4)


def test_fill_and_save_writes_real_blocks_verified_by_rereading_them(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)

    fill_response = sidecar.call(
        "world.fill",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": STONE_MIN,
            "max": STONE_MAX,
            "block": "universal_minecraft:diamond_block",
            "confirm": True,
        },
        request_id=2,
    )
    assert "error" not in fill_response, fill_response
    assert fill_response["result"]["blocks_changed"] == STONE_VOLUME
    assert fill_response["result"]["selection_volume"] == STONE_VOLUME

    save_response = sidecar.call("world.save", {"world_id": world_id, "confirm": True}, request_id=3)
    assert "error" not in save_response, save_response
    assert save_response["result"]["status"] == "saved"
    assert save_response["result"]["chunks_saved"] >= 1

    sidecar.call("world.close", {"world_id": world_id}, request_id=4)

    names = _read_block_names_directly(fixture_world_path, _stone_region_coords())
    assert all(name == "diamond_block" for name in names.values()), names


def test_fill_without_save_never_reaches_disk(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    """The important one: an unconfirmed-to-disk write must stay in memory.

    A fill without a following ``world.save`` must be invisible to a fresh
    read of the world file -- closing the handle here discards the in-memory
    change exactly as a crash or a user simply not saving would.
    """
    world_id = _open_world(sidecar, fixture_world_path)

    fill_response = sidecar.call(
        "world.fill",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": STONE_MIN,
            "max": STONE_MAX,
            "block": "universal_minecraft:diamond_block",
            "confirm": True,
        },
        request_id=2,
    )
    assert "error" not in fill_response, fill_response
    assert fill_response["result"]["blocks_changed"] == STONE_VOLUME

    # No world.save call here -- this is the point of the test.
    sidecar.call("world.close", {"world_id": world_id}, request_id=3)

    names = _read_block_names_directly(fixture_world_path, _stone_region_coords())
    assert all(name == "stone" for name in names.values()), names


def test_undo_restores_the_previous_state_and_redo_reapplies_it(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)

    fill_response = sidecar.call(
        "world.fill",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": STONE_MIN,
            "max": STONE_MAX,
            "block": "universal_minecraft:diamond_block",
            "confirm": True,
        },
        request_id=2,
    )
    assert "error" not in fill_response, fill_response

    undo_response = sidecar.call("world.undo", {"world_id": world_id}, request_id=3)
    assert "error" not in undo_response, undo_response
    assert undo_response["result"]["status"] == "undone"

    save_response = sidecar.call("world.save", {"world_id": world_id, "confirm": True}, request_id=4)
    assert "error" not in save_response, save_response

    sidecar.call("world.close", {"world_id": world_id}, request_id=5)
    names_after_undo = _read_block_names_directly(fixture_world_path, _stone_region_coords())
    assert all(name == "stone" for name in names_after_undo.values()), names_after_undo

    # Reopen and prove redo reapplies the fill.
    world_id_2 = _open_world(sidecar, fixture_world_path)
    # Redo only has something to redo within the same handle's history, so
    # repeat the fill/undo/redo sequence on this fresh handle rather than
    # assuming history survives a close/reopen (it must not -- a reopened
    # world starts with a clean history, exactly like the wx app).
    sidecar.call(
        "world.fill",
        {
            "world_id": world_id_2,
            "dimension": DIMENSION,
            "min": STONE_MIN,
            "max": STONE_MAX,
            "block": "universal_minecraft:diamond_block",
            "confirm": True,
        },
        request_id=2,
    )
    sidecar.call("world.undo", {"world_id": world_id_2}, request_id=3)
    redo_response = sidecar.call("world.redo", {"world_id": world_id_2}, request_id=4)
    assert "error" not in redo_response, redo_response
    assert redo_response["result"]["status"] == "redone"

    sidecar.call("world.save", {"world_id": world_id_2, "confirm": True}, request_id=5)
    sidecar.call("world.close", {"world_id": world_id_2}, request_id=6)

    names_after_redo = _read_block_names_directly(fixture_world_path, _stone_region_coords())
    assert all(name == "diamond_block" for name in names_after_redo.values()), names_after_redo


def test_undo_with_nothing_to_undo_is_a_structured_error(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call("world.undo", {"world_id": world_id}, request_id=2)
    assert response["error"]["code"] == "nothing_to_undo", response
    sidecar.call("world.close", {"world_id": world_id}, request_id=3)


def test_redo_with_nothing_to_redo_is_a_structured_error(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call("world.redo", {"world_id": world_id}, request_id=2)
    assert response["error"]["code"] == "nothing_to_redo", response
    sidecar.call("world.close", {"world_id": world_id}, request_id=3)


def test_replace_only_touches_the_matched_block(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)

    # x=0 column: height = 4 + (0 % 5) = 4, so y in [0,4) is stone and
    # y=4..5 is dirt. Selecting y in [0,6) over that one column captures
    # both, so replacing stone -> diamond_block must leave the dirt alone.
    response = sidecar.call(
        "world.replace",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            "max": [1, 6, 1],
            "original_block": "universal_minecraft:stone",
            "replacement_block": "universal_minecraft:diamond_block",
            "confirm": True,
        },
        request_id=2,
    )
    assert "error" not in response, response
    assert response["result"]["blocks_changed"] == 4  # y=0,1,2,3 were stone

    sidecar.call("world.save", {"world_id": world_id, "confirm": True}, request_id=3)
    sidecar.call("world.close", {"world_id": world_id}, request_id=4)

    names = _read_block_names_directly(
        fixture_world_path, [(0, y, 0) for y in range(6)]
    )
    assert names[(0, 0, 0)] == "diamond_block"
    assert names[(0, 1, 0)] == "diamond_block"
    assert names[(0, 2, 0)] == "diamond_block"
    assert names[(0, 3, 0)] == "diamond_block"
    assert names[(0, 4, 0)] == "dirt"
    assert names[(0, 5, 0)] == "dirt"


def test_fill_refuses_an_oversized_selection(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)

    response = sidecar.call(
        "world.fill",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            "max": [100, 100, 100],  # 1,000,000 blocks, over the limit
            "block": "universal_minecraft:diamond_block",
            "confirm": True,
        },
        request_id=2,
    )
    assert response["error"]["code"] == "selection_too_large", response
    assert "262144" in response["error"]["message"] or "262,144" in response["error"]["message"]

    sidecar.call("world.close", {"world_id": world_id}, request_id=3)


def test_fill_rejects_an_unresolvable_block_string(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)

    response = sidecar.call(
        "world.fill",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": STONE_MIN,
            "max": STONE_MAX,
            "block": "Not A Valid Block!!!",
            "confirm": True,
        },
        request_id=2,
    )
    assert response["error"]["code"] == "block_unresolved", response

    # The sidecar must recover and keep serving subsequent requests, and the
    # world must be untouched by the refused fill.
    ping = sidecar.call("protocol.ping", request_id=3)
    assert ping["result"] == {"ok": True}

    sidecar.call("world.close", {"world_id": world_id}, request_id=4)
    names = _read_block_names_directly(fixture_world_path, _stone_region_coords())
    assert all(name == "stone" for name in names.values()), names


def test_edit_methods_require_a_known_world_id(sidecar: SidecarProcess) -> None:
    for method, params in [
        ("world.fill", {"dimension": DIMENSION, "min": [0, 0, 0], "max": [1, 1, 1], "block": "universal_minecraft:stone", "confirm": True}),
        ("world.replace", {"dimension": DIMENSION, "min": [0, 0, 0], "max": [1, 1, 1], "original_block": "universal_minecraft:stone", "replacement_block": "universal_minecraft:dirt", "confirm": True}),
        ("world.undo", {}),
        ("world.redo", {}),
        ("world.save", {"confirm": True}),
    ]:
        params = {"world_id": "does-not-exist", **params}
        response = sidecar.call(method, params)
        assert response["error"]["code"] == "world_not_found", (method, response)
