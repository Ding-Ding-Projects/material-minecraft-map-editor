"""Tests for the Terrain/Build/Entities/Data ribbon lane's sidecar methods.

Like ``test_sidecar_edit_methods.py``, these spawn the REAL child process
(``python -m amulet_map_editor.api.sidecar``) and talk to it over its actual
stdin/stdout pipes, against a genuine Java world built through amulet-core.
Every claim of a real on-disk change closes the sidecar handle (discarding
any unsaved in-memory change) and reopens the world file directly with
``amulet.load_level`` in this test process to read the real result back.
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


def _build_fixture_world(world_path: str) -> None:
    """The same stepped-terrain fixture ``test_sidecar_edit_methods.py`` uses.

    x=0..15, height = 4 + (x % 5): y < height is stone, the next two layers
    are dirt, the layer above that is grass, and everything above is air --
    every column has real terrain and a real air/surface boundary to shape.

    Deliberately no entities here. The Java entity NBT<->universal
    translation this dev environment ships with is missing its entity ID
    table (``PyMCTranslate``'s ``min_json`` submodule is unpopulated in this
    checkout), so an entity written to disk and reopened in a fresh process
    silently reads back empty -- a real environment gap, not a sidecar bug.
    The entity tests below place their entities through the sidecar's own
    ``entities.place`` in the same open session instead, which never goes
    through that translation and is exactly what a caller placing an entity
    from the ribbon does too.
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
    world_path = tmp_path / "world"
    _build_fixture_world(str(world_path))
    return str(world_path)


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


def _read_block_names_directly(world_path: str, coords) -> Dict[tuple, str]:
    level = amulet.load_level(world_path)
    try:
        names = {}
        for x, y, z in coords:
            names[(x, y, z)] = level.get_block(x, y, z, DIMENSION).base_name
        return names
    finally:
        level.close()


# ------------------------------------------------------------- terrain.*


def test_flatten_requires_confirmation(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call(
        "terrain.flatten",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            "max": [4, 8, 4],
            "height": 5,
            "block": "universal_minecraft:stone",
        },
        request_id=2,
    )
    assert response["error"]["code"] == "confirmation_required", response
    sidecar.call("world.close", {"world_id": world_id}, request_id=3)


def test_flatten_sets_below_to_block_and_above_to_air(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)

    response = sidecar.call(
        "terrain.flatten",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            "max": [1, 8, 1],
            "height": 5,
            "block": "universal_minecraft:cobblestone",
            "confirm": True,
        },
        request_id=2,
    )
    assert "error" not in response, response
    assert response["result"]["blocks_changed"] == 8
    assert response["result"]["height"] == 5

    sidecar.call("world.save", {"world_id": world_id, "confirm": True}, request_id=3)
    sidecar.call("world.close", {"world_id": world_id}, request_id=4)

    names = _read_block_names_directly(
        fixture_world_path, [(0, y, 0) for y in range(8)]
    )
    for y in range(5):
        assert names[(0, y, 0)] == "cobblestone", (y, names)
    for y in range(5, 8):
        assert names[(0, y, 0)] == "air", (y, names)


def test_sea_level_raise_fills_air_with_water_up_to_the_level(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)

    # x=10 column: height = 4 + (10 % 5) = 4, so y=6 (grass) and y=7+ (air)
    # exist. Selecting y in [0, 10) and raising sea level to 8 must turn the
    # air at y=7,8 into water but leave y=6 (grass) untouched.
    response = sidecar.call(
        "terrain.sea_level",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [10, 0, 10],
            "max": [11, 10, 11],
            "sea_level": 8,
            "mode": "raise",
            "confirm": True,
        },
        request_id=2,
    )
    assert "error" not in response, response
    assert response["result"]["blocks_changed"] == 2  # y=7,8

    sidecar.call("world.save", {"world_id": world_id, "confirm": True}, request_id=3)
    sidecar.call("world.close", {"world_id": world_id}, request_id=4)

    names = _read_block_names_directly(
        fixture_world_path, [(10, y, 10) for y in range(10)]
    )
    assert names[(10, 6, 10)] == "grass_block"
    assert names[(10, 7, 10)] == "water"
    assert names[(10, 8, 10)] == "water"
    assert names[(10, 9, 10)] == "air"


def test_sea_level_drain_turns_water_back_to_air(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    sidecar.call(
        "terrain.sea_level",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [10, 0, 10],
            "max": [11, 10, 11],
            "sea_level": 8,
            "mode": "raise",
            "confirm": True,
        },
        request_id=2,
    )
    drain_response = sidecar.call(
        "terrain.sea_level",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [10, 0, 10],
            "max": [11, 10, 11],
            "sea_level": 8,
            "mode": "drain",
            "confirm": True,
        },
        request_id=3,
    )
    assert "error" not in drain_response, drain_response
    assert drain_response["result"]["blocks_changed"] == 2

    sidecar.call("world.save", {"world_id": world_id, "confirm": True}, request_id=4)
    sidecar.call("world.close", {"world_id": world_id}, request_id=5)

    names = _read_block_names_directly(fixture_world_path, [(10, 7, 10), (10, 8, 10)])
    assert names[(10, 7, 10)] == "air"
    assert names[(10, 8, 10)] == "air"


def test_sea_level_rejects_an_unknown_mode(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call(
        "terrain.sea_level",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            "max": [1, 1, 1],
            "sea_level": 4,
            "mode": "flood-it",
            "confirm": True,
        },
        request_id=2,
    )
    assert response["error"]["code"] == "sea_level_mode_unknown", response
    sidecar.call("world.close", {"world_id": world_id}, request_id=3)


def test_repaint_changes_only_the_topmost_block_of_each_column(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)

    # x=0 column: height=4, surface (grass) is at y=6. Select y in [0,8).
    response = sidecar.call(
        "terrain.repaint",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            "max": [1, 8, 1],
            "block": "universal_minecraft:sand",
            "confirm": True,
        },
        request_id=2,
    )
    assert "error" not in response, response
    assert response["result"]["blocks_changed"] == 1

    sidecar.call("world.save", {"world_id": world_id, "confirm": True}, request_id=3)
    sidecar.call("world.close", {"world_id": world_id}, request_id=4)

    names = _read_block_names_directly(
        fixture_world_path, [(0, y, 0) for y in range(8)]
    )
    assert names[(0, 6, 0)] == "sand"  # was grass_block, now repainted
    assert names[(0, 5, 0)] == "dirt"  # untouched, one below the surface
    assert names[(0, 3, 0)] == "stone"  # untouched, deep in the column


# ------------------------------------------------------------ entities.*


def _place_entity(
    sidecar: SidecarProcess, world_id: str, x, y, z, base_name: str, request_id
) -> None:
    response = sidecar.call(
        "entities.place",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "position": [x, y, z],
            "namespace": "minecraft",
            "base_name": base_name,
            "confirm": True,
        },
        request_id=request_id,
    )
    assert "error" not in response, response


def test_entities_place_requires_confirmation(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call(
        "entities.place",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "position": [1.5, 5.0, 1.5],
            "namespace": "minecraft",
            "base_name": "cow",
        },
        request_id=2,
    )
    assert response["error"]["code"] == "confirmation_required", response
    sidecar.call("world.close", {"world_id": world_id}, request_id=3)


def test_entities_list_returns_only_entities_inside_the_box(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    _place_entity(sidecar, world_id, 1.5, 5.0, 1.5, "cow", 2)
    _place_entity(sidecar, world_id, 2.5, 5.0, 2.5, "pig", 3)
    _place_entity(
        sidecar, world_id, 40.0, 5.0, 40.0, "cow", 4
    )  # outside the test box below

    response = sidecar.call(
        "entities.list",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            "max": [16, 16, 16],
        },
        request_id=5,
    )
    assert "error" not in response, response
    names = sorted(e["base_name"] for e in response["result"]["entities"])
    assert names == ["cow", "pig"]  # the far cow at (40, 5, 40) is out of range
    assert response["result"]["count"] == 2
    sidecar.call("world.close", {"world_id": world_id}, request_id=6)


def test_entities_remove_requires_a_filter(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call(
        "entities.remove",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            "max": [16, 16, 16],
            "confirm": True,
        },
        request_id=2,
    )
    assert response["error"]["code"] == "invalid_params", response
    sidecar.call("world.close", {"world_id": world_id}, request_id=3)


def test_entities_remove_deletes_only_matching_entities_in_the_box(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    _place_entity(sidecar, world_id, 1.5, 5.0, 1.5, "cow", 2)
    _place_entity(sidecar, world_id, 2.5, 5.0, 2.5, "pig", 3)
    _place_entity(
        sidecar, world_id, 40.0, 5.0, 40.0, "cow", 4
    )  # in a wider box, out of the removal box

    remove_response = sidecar.call(
        "entities.remove",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            "max": [16, 16, 16],
            "base_name": "cow",
            "confirm": True,
        },
        request_id=5,
    )
    assert "error" not in remove_response, remove_response
    assert (
        remove_response["result"]["removed"] == 1
    )  # the in-box cow, not the pig or the far cow

    list_response = sidecar.call(
        "entities.list",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            "max": [50, 16, 50],
        },
        request_id=6,
    )
    remaining = sorted(e["base_name"] for e in list_response["result"]["entities"])
    assert remaining == [
        "cow",
        "pig",
    ]  # the far cow (still in this wider box) + the pig

    sidecar.call("world.close", {"world_id": world_id}, request_id=7)


# ----------------------------------------------------------------- data.*


def test_level_read_reports_the_real_level_name(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call("data.level_read", {"world_id": world_id}, request_id=2)
    assert "error" not in response, response
    assert isinstance(response["result"]["level_name"], str)
    sidecar.call("world.close", {"world_id": world_id}, request_id=3)


def test_level_write_requires_confirmation(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call(
        "data.level_write",
        {"world_id": world_id, "fields": {"level_name": "Renamed"}},
        request_id=2,
    )
    assert response["error"]["code"] == "confirmation_required", response
    sidecar.call("world.close", {"world_id": world_id}, request_id=3)


def test_level_write_changes_the_level_name_and_persists_on_save(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    write_response = sidecar.call(
        "data.level_write",
        {
            "world_id": world_id,
            "fields": {"level_name": "Renamed World", "hardcore": True},
            "confirm": True,
        },
        request_id=2,
    )
    assert "error" not in write_response, write_response
    assert sorted(write_response["result"]["updated"]) == ["hardcore", "level_name"]

    read_back = sidecar.call("data.level_read", {"world_id": world_id}, request_id=3)
    assert read_back["result"]["level_name"] == "Renamed World"
    assert read_back["result"]["hardcore"] is True

    sidecar.call("world.save", {"world_id": world_id, "confirm": True}, request_id=4)
    sidecar.call("world.close", {"world_id": world_id}, request_id=5)

    level = amulet.load_level(fixture_world_path)
    try:
        name_tag = level.level_wrapper.root_tag.tag["Data"]["LevelName"]
        assert name_tag.py_str == "Renamed World"
    finally:
        level.close()


def test_level_write_rejects_unknown_fields(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call(
        "data.level_write",
        {"world_id": world_id, "fields": {"seed": 12345}, "confirm": True},
        request_id=2,
    )
    assert response["error"]["code"] == "invalid_params", response
    sidecar.call("world.close", {"world_id": world_id}, request_id=3)


def test_game_rules_round_trip_write_then_read_then_persist(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)

    empty_read = sidecar.call(
        "data.game_rules_read", {"world_id": world_id}, request_id=2
    )
    assert "error" not in empty_read, empty_read
    assert (
        empty_read["result"]["game_rules"] == {}
    )  # the fixture world has no GameRules yet

    write_response = sidecar.call(
        "data.game_rules_write",
        {
            "world_id": world_id,
            "rules": {"doDaylightCycle": "false", "keepInventory": "true"},
            "confirm": True,
        },
        request_id=3,
    )
    assert "error" not in write_response, write_response
    assert sorted(write_response["result"]["updated"]) == [
        "doDaylightCycle",
        "keepInventory",
    ]

    read_back = sidecar.call(
        "data.game_rules_read", {"world_id": world_id}, request_id=4
    )
    assert read_back["result"]["game_rules"] == {
        "doDaylightCycle": "false",
        "keepInventory": "true",
    }

    sidecar.call("world.save", {"world_id": world_id, "confirm": True}, request_id=5)
    sidecar.call("world.close", {"world_id": world_id}, request_id=6)

    level = amulet.load_level(fixture_world_path)
    try:
        game_rules = level.level_wrapper.root_tag.tag["Data"]["GameRules"]
        assert game_rules["doDaylightCycle"].py_str == "false"
        assert game_rules["keepInventory"].py_str == "true"
    finally:
        level.close()


def test_game_rules_write_requires_confirmation(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call(
        "data.game_rules_write",
        {"world_id": world_id, "rules": {"doFire": "false"}},
        request_id=2,
    )
    assert response["error"]["code"] == "confirmation_required", response
    sidecar.call("world.close", {"world_id": world_id}, request_id=3)


def test_terrain_and_data_methods_require_a_known_world_id(
    sidecar: SidecarProcess,
) -> None:
    common_box = {"dimension": DIMENSION, "min": [0, 0, 0], "max": [1, 1, 1]}
    for method, params in [
        (
            "terrain.flatten",
            {
                **common_box,
                "height": 4,
                "block": "universal_minecraft:stone",
                "confirm": True,
            },
        ),
        (
            "terrain.sea_level",
            {**common_box, "sea_level": 4, "mode": "raise", "confirm": True},
        ),
        (
            "terrain.repaint",
            {**common_box, "block": "universal_minecraft:sand", "confirm": True},
        ),
        ("entities.list", common_box),
        ("entities.remove", {**common_box, "base_name": "cow", "confirm": True}),
        (
            "entities.place",
            {
                "dimension": DIMENSION,
                "position": [1.0, 5.0, 1.0],
                "namespace": "minecraft",
                "base_name": "cow",
                "confirm": True,
            },
        ),
        ("data.level_read", {}),
        ("data.level_write", {"fields": {"level_name": "X"}, "confirm": True}),
        ("data.game_rules_read", {}),
        ("data.game_rules_write", {"rules": {"doFire": "false"}, "confirm": True}),
    ]:
        params = {"world_id": "does-not-exist", **params}
        response = sidecar.call(method, params)
        assert response["error"]["code"] == "world_not_found", (method, response)
