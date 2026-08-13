"""Tests for the mesh boundary: batching multiple chunks into one background
request/one combined file, and proving that request does not stall the
sidecar's stdio loop for an unrelated call sitting behind it.

Like ``test_sidecar_world_methods.py``, these spawn the REAL child process
and talk to it over its actual stdin/stdout pipes -- an in-process call would
prove the meshing logic and nothing about the boundary (background thread +
poll, the combined-buffer file, a stale/unreleased batch) this lane owns.
"""

from __future__ import annotations

import os
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
pytest.importorskip(
    "minecraft_model_reader.api.resource_pack",
    reason="minecraft_model_reader is not installed in this interpreter",
)


@pytest.fixture()
def sidecar(tmp_path, monkeypatch):
    monkeypatch.setenv("AMULET_RECENTS_DIR", str(tmp_path / "recents"))
    proc = SidecarProcess()
    try:
        yield proc
    finally:
        proc.close()


@pytest.fixture(scope="module")
def populated_world_path(tmp_path_factory) -> str:
    """A real Java world with a few solid blocks in chunks (0,0) and (1,0),
    so meshing actually produces faces -- an empty superflat world would
    mesh to zero vertices and prove nothing about the byte-offset slicing
    the batch path is responsible for getting right.
    """
    from amulet.api.block import Block
    from amulet.api.level import World
    from amulet.level.formats.anvil_world import AnvilFormat

    root = tmp_path_factory.mktemp("sidecar-mesh-world")
    world_path = str(root / "world")
    fmt = AnvilFormat(world_path)
    fmt.create_and_open("java", (1, 20, 4), overwrite=True)
    fmt.close()

    world = World(world_path, AnvilFormat(world_path))
    dimension = "minecraft:overworld"
    block = Block("minecraft", "stone")
    for cx, cz in ((0, 0), (1, 0)):
        for x in range(cx * 16, cx * 16 + 16, 2):
            for z in range(cz * 16, cz * 16 + 16, 2):
                world.set_version_block(
                    x, 64, z, dimension, ("java", (1, 20, 4)), block
                )
    world.save()
    world.close()
    return world_path


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


def _poll_resource_pack(
    sidecar: SidecarProcess, world_id: str, timeout: float = 120.0
) -> None:
    deadline = time.time() + timeout
    while True:
        prep = sidecar.call(
            "viewport.prepare", {"world_id": world_id}, request_id="prep"
        )
        result = prep.get("result")
        assert result is not None, prep
        if result["status"] == "ready":
            return
        assert result["status"] != "failed", prep
        if time.time() > deadline:
            raise AssertionError("resource pack never became ready")
        time.sleep(0.2)


def _poll_batch(
    sidecar: SidecarProcess, batch_id: str, timeout: float = 60.0
) -> Dict[str, Any]:
    deadline = time.time() + timeout
    while True:
        response = sidecar.call(
            "viewport.chunk_mesh_batch_status",
            {"batch_id": batch_id},
            request_id="batch-poll",
        )
        result = response.get("result")
        assert result is not None, response
        if result["status"] != "pending":
            return result
        if time.time() > deadline:
            raise AssertionError(f"batch stayed pending: {result}")
        time.sleep(0.05)


@pytest.fixture()
def ready_world(sidecar: SidecarProcess, populated_world_path: str) -> Dict[str, Any]:
    opened = sidecar.call("world.open", {"path": populated_world_path})
    world_id = opened["result"]["world_id"]
    status = _poll_open_status(sidecar, world_id)
    dimension = status["dimensions"][0]
    _poll_resource_pack(sidecar, world_id)
    return {"world_id": world_id, "dimension": dimension}


def test_chunk_mesh_batch_matches_individual_chunk_mesh(
    sidecar: SidecarProcess, ready_world: Dict[str, Any]
) -> None:
    """The batched combined buffer must slice byte-for-byte identically to
    what the existing single-chunk ``viewport.chunk_mesh`` produces for the
    same chunk -- batching is a transport optimisation, never a different
    answer."""
    world_id = ready_world["world_id"]
    dimension = ready_world["dimension"]

    single = sidecar.call(
        "viewport.chunk_mesh",
        {"world_id": world_id, "dimension": dimension, "cx": 0, "cz": 0},
        request_id=2,
    )
    assert single["result"]["exists"] is True
    assert single["result"]["vertex_count"] > 0

    kicked = sidecar.call(
        "viewport.chunk_mesh_batch",
        {
            "world_id": world_id,
            "dimension": dimension,
            "chunks": [[0, 0], [1, 0], [5, 5]],
        },
        request_id=3,
    )
    assert "error" not in kicked, kicked
    assert kicked["result"]["status"] == "pending"
    batch_id = kicked["result"]["batch_id"]

    ready = _poll_batch(sidecar, batch_id)
    assert ready["status"] == "ready", ready
    chunks = {tuple((c["cx"], c["cz"])): c for c in ready["chunks"]}

    zero_zero = chunks[(0, 0)]
    assert zero_zero["exists"] is True
    assert zero_zero["vertex_count"] == single["result"]["vertex_count"]
    assert zero_zero["opaque_vertex_count"] == single["result"]["opaque_vertex_count"]
    assert zero_zero["byte_offset"] == 0

    one_zero = chunks[(1, 0)]
    assert one_zero["exists"] is True
    assert one_zero["byte_offset"] == zero_zero["byte_length"]

    # (5, 5) was never touched -- no region file was ever generated for it,
    # so it genuinely does not exist, exactly what a single
    # ``viewport.chunk_mesh`` call reports for the same coordinate.
    far_single = sidecar.call(
        "viewport.chunk_mesh",
        {"world_id": world_id, "dimension": dimension, "cx": 5, "cz": 5},
        request_id=5,
    )
    assert far_single["result"]["exists"] is False
    far = chunks[(5, 5)]
    assert far["exists"] is False
    assert far["vertex_count"] == 0
    assert far["byte_length"] == 0

    with open(ready["path"], "rb") as fh:
        combined_bytes = fh.read()
    assert len(combined_bytes) == zero_zero["byte_length"] + one_zero["byte_length"]

    released = sidecar.call(
        "viewport.chunk_mesh_batch_release", {"batch_id": batch_id}, request_id=4
    )
    assert released["result"] == {"batch_id": batch_id, "released": True}
    assert not os.path.exists(ready["path"]), "release must delete the combined file"


def test_chunk_mesh_batch_does_not_block_other_requests(
    sidecar: SidecarProcess, ready_world: Dict[str, Any]
) -> None:
    """A batch request must answer 'pending' fast and let unrelated calls
    (a preferences read, an edit call, another ping) through the shared
    stdio pipe while the real meshing runs on its background thread --
    exactly the property ``test_world_open_does_not_block_other_requests``
    already proves for ``world.open``.
    """
    world_id = ready_world["world_id"]
    dimension = ready_world["dimension"]
    chunks = [[cx, cz] for cx in range(-2, 3) for cz in range(-2, 3)]  # 25 chunks

    start = time.time()
    kicked = sidecar.call(
        "viewport.chunk_mesh_batch",
        {"world_id": world_id, "dimension": dimension, "chunks": chunks},
        request_id=2,
    )
    ping = sidecar.call("protocol.ping", request_id=3)
    elapsed = time.time() - start

    assert kicked["result"]["status"] == "pending"
    assert ping["result"] == {"ok": True}
    assert (
        elapsed < 5.0
    ), f"batch kick-off + ping took {elapsed:.2f}s -- the batch blocked the pipe"

    ready = _poll_batch(sidecar, kicked["result"]["batch_id"])
    assert ready["status"] == "ready"
    assert len(ready["chunks"]) == 25


def test_chunk_mesh_batch_rejects_bad_params(
    sidecar: SidecarProcess, ready_world: Dict[str, Any]
) -> None:
    world_id = ready_world["world_id"]
    dimension = ready_world["dimension"]

    empty = sidecar.call(
        "viewport.chunk_mesh_batch",
        {"world_id": world_id, "dimension": dimension, "chunks": []},
        request_id=2,
    )
    assert empty["error"]["code"] == "invalid_params"

    bad_shape = sidecar.call(
        "viewport.chunk_mesh_batch",
        {"world_id": world_id, "dimension": dimension, "chunks": [[0, 0, 0]]},
        request_id=3,
    )
    assert bad_shape["error"]["code"] == "invalid_chunk_coord"

    too_many = sidecar.call(
        "viewport.chunk_mesh_batch",
        {
            "world_id": world_id,
            "dimension": dimension,
            "chunks": [[i, 0] for i in range(200)],
        },
        request_id=4,
    )
    assert too_many["error"]["code"] == "invalid_params"


def test_chunk_mesh_batch_status_of_unknown_batch_is_structured_error(
    sidecar: SidecarProcess,
) -> None:
    response = sidecar.call(
        "viewport.chunk_mesh_batch_status", {"batch_id": "not-a-real-batch"}
    )
    # mesh_methods.py reuses world_methods.py's ERR_NOT_FOUND constant (see
    # the import at the top of that module), so the wire code is the same
    # "world_not_found" string an unknown world_id reports -- a batch id and
    # a world id are both just "no such handle" from the caller's side.
    assert response["error"]["code"] == "world_not_found"


def test_chunk_mesh_batch_release_of_unknown_batch_is_a_no_op(
    sidecar: SidecarProcess,
) -> None:
    response = sidecar.call(
        "viewport.chunk_mesh_batch_release", {"batch_id": "not-a-real-batch"}
    )
    assert response["result"] == {"batch_id": "not-a-real-batch", "released": False}
