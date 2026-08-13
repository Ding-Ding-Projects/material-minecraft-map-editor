"""Tests for the sidecar's read-only world-access methods.

Like ``test_sidecar_protocol.py``, these spawn the REAL child process
(``python -m amulet_map_editor.api.sidecar``) and talk to it over its actual
stdin/stdout pipes. A handler called in-process would prove the world-open
logic and nothing about the boundary it actually has to survive: an
untrusted path arriving as JSON over a pipe, a background load racing the
next request, a handle id that only makes sense to the process that minted
it.
"""

from __future__ import annotations

import os
import sys
import tempfile
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


@pytest.fixture()
def sidecar(tmp_path, monkeypatch):
    # Isolate the real recents store the same way CONFIG_DIR isolates
    # preferences -- otherwise "recents.list" would read the developer's
    # own profile.
    monkeypatch.setenv("AMULET_RECENTS_DIR", str(tmp_path / "recents"))
    proc = SidecarProcess()
    try:
        yield proc
    finally:
        proc.close()


@pytest.fixture(scope="module")
def real_world_path(tmp_path_factory) -> str:
    """A genuine, minimal Java world on disk, built the same way amulet does."""
    from amulet.level.formats.anvil_world import AnvilFormat

    root = tmp_path_factory.mktemp("sidecar-world")
    world_path = root / "world"
    fmt = AnvilFormat(str(world_path))
    fmt.create_and_open("java", (1, 20, 4), overwrite=True)
    fmt.close()
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


def test_world_open_round_trip_returns_real_identity(
    sidecar: SidecarProcess, real_world_path: str
) -> None:
    opened = sidecar.call("world.open", {"path": real_world_path})
    assert "error" not in opened, opened
    assert opened["result"]["status"] == "pending"
    world_id = opened["result"]["world_id"]
    assert world_id

    status = _poll_open_status(sidecar, world_id)
    assert status["status"] == "ready"
    assert status["world_id"] == world_id
    assert status["path"] == real_world_path
    assert status["platform"] == "java"
    # The Java wrapper's own "version" is the data-version integer baked
    # into level.dat (3700 for 1.20.4), not the (major, minor, patch) tuple
    # passed to create_and_open -- report whatever amulet itself reports.
    assert status["version"] == 3700
    assert "minecraft:overworld" in status["dimensions"]

    closed = sidecar.call("world.close", {"world_id": world_id}, request_id=2)
    assert closed["result"] == {"world_id": world_id, "status": "closed"}

    # A closed handle is really gone -- a follow-up call must not find it.
    follow_up = sidecar.call("world.open_status", {"world_id": world_id}, request_id=3)
    assert follow_up["error"]["code"] == "world_not_found"


def test_world_dimensions_reports_real_bounds(
    sidecar: SidecarProcess, real_world_path: str
) -> None:
    opened = sidecar.call("world.open", {"path": real_world_path})
    world_id = opened["result"]["world_id"]
    _poll_open_status(sidecar, world_id)

    response = sidecar.call("world.dimensions", {"world_id": world_id}, request_id=2)
    assert "error" not in response, response
    dimensions = response["result"]["dimensions"]
    names = {entry["dimension"] for entry in dimensions}
    assert {"minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"} <= names
    overworld = next(e for e in dimensions if e["dimension"] == "minecraft:overworld")
    assert overworld["bounds"]["min"] == [-30000000, 0, -30000000]
    assert overworld["bounds"]["max"] == [30000000, 256, 30000000]

    sidecar.call("world.close", {"world_id": world_id}, request_id=3)


def test_world_open_does_not_block_other_requests(
    sidecar: SidecarProcess, real_world_path: str
) -> None:
    """A slow open must not stall the stdio loop for unrelated requests.

    ``world.open`` hands the real load to a background thread and answers
    "pending" immediately, so a ping sent right behind it must come back
    fast regardless of how long the real load takes.
    """
    start = time.time()
    opened = sidecar.call("world.open", {"path": real_world_path})
    ping = sidecar.call("protocol.ping", request_id=2)
    elapsed = time.time() - start

    assert opened["result"]["status"] == "pending"
    assert ping["result"] == {"ok": True}
    # Generous bound: this only has to prove the ping was not made to wait
    # for the *whole* world load (which involves NBT parsing and would take
    # much longer under load), not that background GIL contention is zero.
    assert (
        elapsed < 8.0
    ), f"world.open + ping took {elapsed:.2f}s -- the open blocked the pipe"

    _poll_open_status(sidecar, opened["result"]["world_id"])
    sidecar.call(
        "world.close", {"world_id": opened["result"]["world_id"]}, request_id=3
    )


@pytest.mark.parametrize(
    "bad_path,expected_code",
    [
        (None, "invalid_params"),
        ("", "invalid_params"),
        ("relative/path/to/world", "invalid_params"),
        ("C:/definitely/does/not/exist/anywhere", "world_path_not_found"),
    ],
)
def test_world_open_rejects_bad_paths_as_structured_errors(
    sidecar: SidecarProcess, bad_path, expected_code: str
) -> None:
    response = sidecar.call(
        "world.open", {"path": bad_path} if bad_path is not None else {}
    )
    assert response["error"]["code"] == expected_code, response
    # The sidecar must recover and keep serving subsequent requests.
    follow_up = sidecar.call("protocol.ping", request_id=2)
    assert follow_up["result"] == {"ok": True}


def test_world_open_rejects_a_special_file(
    sidecar: SidecarProcess, tmp_path: Path
) -> None:
    if os.name != "nt":
        # Named pipes/FIFOs are the interesting case on POSIX; exercised
        # only where the platform can cheaply create one.
        fifo_path = tmp_path / "not-a-world"
        os.mkfifo(fifo_path)
        response = sidecar.call("world.open", {"path": str(fifo_path)})
        assert response["error"]["code"] == "world_path_unsupported", response
    else:
        # On Windows, a reserved device name is the cheap "not a regular
        # file or directory" case without needing to create one.
        response = sidecar.call("world.open", {"path": "\\\\.\\NUL"})
        assert response["error"]["code"] in {
            "world_path_not_found",
            "world_path_unsupported",
        }, response


def test_world_open_on_a_non_world_directory_is_a_structured_load_failure(
    sidecar: SidecarProcess, tmp_path: Path
) -> None:
    empty_dir = tmp_path / "not-a-world-either"
    empty_dir.mkdir()
    opened = sidecar.call("world.open", {"path": str(empty_dir)})
    world_id = opened["result"]["world_id"]

    status = _poll_open_status(sidecar, world_id)
    assert status["status"] == "failed"
    assert status["error"]["code"] == "world_load_failed"


def test_world_close_of_unknown_handle_is_a_structured_error(
    sidecar: SidecarProcess,
) -> None:
    response = sidecar.call("world.close", {"world_id": "does-not-exist"})
    assert response["error"]["code"] == "world_not_found"


def test_world_dimensions_of_unknown_handle_is_a_structured_error(
    sidecar: SidecarProcess,
) -> None:
    response = sidecar.call("world.dimensions", {"world_id": "does-not-exist"})
    assert response["error"]["code"] == "world_not_found"


def test_recents_list_round_trip_is_the_real_store(sidecar: SidecarProcess) -> None:
    response = sidecar.call("recents.list")
    assert "error" not in response, response
    assert response["result"] == {"entries": []}


def test_world_backend_unavailable_degrades_to_a_structured_error(monkeypatch) -> None:
    """If amulet is not importable, every world.* method reports it plainly.

    This does not spawn the real sidecar process (that always has the real
    interpreter, which does have amulet installed in this checkout) -- it
    exercises the in-process degrade path directly, which is the part that
    actually branches on import success.
    """
    from amulet_map_editor.api.sidecar import world_methods as wm

    monkeypatch.setattr(wm, "_amulet_load_level", None)
    monkeypatch.setattr(wm, "_AMULET_IMPORT_ERROR", "simulated: not installed")

    with pytest.raises(Exception) as excinfo:
        wm._world_open({"path": "C:/whatever" if os.name == "nt" else "/whatever"})
    from amulet_map_editor.api.sidecar.protocol import ProtocolError

    assert isinstance(excinfo.value, ProtocolError)
    assert excinfo.value.code == wm.ERR_BACKEND_UNAVAILABLE
