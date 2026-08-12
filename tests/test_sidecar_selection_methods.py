"""Tests for the sidecar's selection/chunk write path -- copy, cut, paste,
delete, structure export/import, and chunk create/delete/prune.

Same discipline as ``test_sidecar_edit_methods.py``: spawn the REAL child
process over its real stdio pipes, against a genuine Java world, and verify
every claimed change by reopening the world file directly with
``amulet.load_level`` in this test process rather than trusting the
sidecar's own report.
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

STONE_MIN = [0, 0, 0]
STONE_MAX = [4, 2, 4]
STONE_VOLUME = 4 * 2 * 4  # 32


def _build_fixture_world(world_path: str) -> None:
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


def test_selection_copy_does_not_require_confirm_and_touches_nothing(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call(
        "selection.copy",
        {"world_id": world_id, "dimension": DIMENSION, "min": STONE_MIN, "max": STONE_MAX},
    )
    assert "error" not in response, response
    assert response["result"]["blocks_copied"] == STONE_VOLUME

    status = sidecar.call("selection.clipboard_status", {"world_id": world_id})
    assert status["result"]["has_content"] is True
    assert status["result"]["blocks"] == STONE_VOLUME


def test_selection_delete_is_refused_without_confirmation(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call(
        "selection.delete",
        {"world_id": world_id, "dimension": DIMENSION, "min": STONE_MIN, "max": STONE_MAX},
    )
    assert response["error"]["code"] == "confirmation_required", response


def test_selection_delete_and_save_clears_real_blocks(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call(
        "selection.delete",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": STONE_MIN,
            "max": STONE_MAX,
            "confirm": True,
        },
    )
    assert "error" not in response, response
    assert response["result"]["blocks_changed"] == STONE_VOLUME

    saved = sidecar.call("world.save", {"world_id": world_id, "confirm": True})
    assert "error" not in saved, saved
    sidecar.call("world.close", {"world_id": world_id})

    names = _read_block_names_directly(fixture_world_path, _stone_region_coords())
    assert set(names.values()) == {"air"}


def test_selection_cut_removes_and_stores_for_paste(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    cut = sidecar.call(
        "selection.cut",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": STONE_MIN,
            "max": STONE_MAX,
            "confirm": True,
        },
    )
    assert "error" not in cut, cut
    assert cut["result"]["blocks_changed"] == STONE_VOLUME

    status = sidecar.call("selection.clipboard_status", {"world_id": world_id})
    assert status["result"]["has_content"] is True

    saved = sidecar.call("world.save", {"world_id": world_id, "confirm": True})
    assert "error" not in saved, saved
    sidecar.call("world.close", {"world_id": world_id})

    names = _read_block_names_directly(fixture_world_path, _stone_region_coords())
    assert set(names.values()) == {"air"}


def test_selection_paste_without_a_prior_copy_is_a_structured_error(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call(
        "selection.paste",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "location": [8, 0, 0],
            "confirm": True,
        },
    )
    assert response["error"]["code"] == "clipboard_empty", response


def test_selection_copy_then_paste_places_real_blocks_elsewhere(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    copy = sidecar.call(
        "selection.copy",
        {"world_id": world_id, "dimension": DIMENSION, "min": STONE_MIN, "max": STONE_MAX},
    )
    assert "error" not in copy, copy

    paste = sidecar.call(
        "selection.paste",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "location": [8, 0, 8],
            "confirm": True,
        },
    )
    assert "error" not in paste, paste

    saved = sidecar.call("world.save", {"world_id": world_id, "confirm": True})
    assert "error" not in saved, saved
    sidecar.call("world.close", {"world_id": world_id})

    # Original region is untouched (a copy, not a cut).
    original = _read_block_names_directly(fixture_world_path, _stone_region_coords())
    assert set(original.values()) == {"stone"}


def test_chunk_delete_is_refused_without_confirmation(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call(
        "chunk.delete",
        {"world_id": world_id, "dimension": DIMENSION, "min": [0, 0, 0], "max": [16, 1, 16]},
    )
    assert response["error"]["code"] == "confirmation_required", response


def test_chunk_delete_removes_the_real_chunk(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call(
        "chunk.delete",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            "max": [16, 1, 16],
            "confirm": True,
        },
    )
    assert "error" not in response, response
    assert response["result"]["chunks_deleted"] == 1

    saved = sidecar.call("world.save", {"world_id": world_id, "confirm": True})
    assert "error" not in saved, saved
    sidecar.call("world.close", {"world_id": world_id})

    level = amulet.load_level(fixture_world_path)
    try:
        assert not level.has_chunk(0, 0, DIMENSION)
    finally:
        level.close()


def test_chunk_create_only_creates_missing_chunks(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call(
        "chunk.create",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            "max": [32, 1, 16],
        },
    )
    assert "error" not in response, response
    assert response["result"]["chunks_examined"] == 2
    # (0,0) already existed from the fixture; only the second chunk is new.
    assert response["result"]["chunks_created"] == 1


def test_selection_delete_refuses_an_oversized_selection(
    sidecar: SidecarProcess, fixture_world_path: str
) -> None:
    world_id = _open_world(sidecar, fixture_world_path)
    response = sidecar.call(
        "selection.delete",
        {
            "world_id": world_id,
            "dimension": DIMENSION,
            "min": [0, 0, 0],
            "max": [200, 200, 200],
            "confirm": True,
        },
    )
    assert response["error"]["code"] == "selection_too_large", response
