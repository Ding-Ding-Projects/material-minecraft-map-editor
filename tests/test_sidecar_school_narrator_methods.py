"""Tests for the sidecar's School-mode and TTS-narrator methods.

Spawns the REAL sidecar child process (matching the convention in
``test_sidecar_protocol.py``) and calls straight into
``amulet_map_editor.api.school_mode`` and ``amulet_map_editor.api.tts_narrator``
through the wire methods registered in
``amulet_map_editor/api/sidecar/methods.py`` -- proving the renderer-facing
seam actually reaches the real, already-tested Python modules rather than a
stub.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test_sidecar_protocol import SidecarProcess  # noqa: E402  (reuse the real client)


@pytest.fixture()
def sidecar():
    proc = SidecarProcess()
    try:
        yield proc
    finally:
        proc.close()


def test_school_status_starts_disabled_with_no_credential(sidecar: SidecarProcess) -> None:
    response = sidecar.call("school.status")
    result = response["result"]
    assert result["enabled"] is False
    assert result["mode_name"] == "School mode"
    assert result["has_unlock_credential"] is False
    # The salt/digest never leaves the process.
    assert "credential_salt" not in result
    assert "credential_digest" not in result


def test_school_enable_requires_a_credential_first(sidecar: SidecarProcess) -> None:
    response = sidecar.call("school.enable")
    assert response["error"]["code"] == "invalid_params"


def test_school_full_lifecycle_set_credential_enable_wrong_unlock_then_right_unlock(
    sidecar: SidecarProcess,
) -> None:
    set_cred = sidecar.call(
        "school.set_credential", {"credential": "correct-horse"}, request_id=2
    )
    assert set_cred["result"]["has_unlock_credential"] is True

    renamed = sidecar.call(
        "school.set_mode_name", {"mode_name": "Focus mode"}, request_id=3
    )
    assert renamed["result"]["mode_name"] == "Focus mode"

    enabled = sidecar.call("school.enable", request_id=4)
    assert enabled["result"]["enabled"] is True

    wrong = sidecar.call("school.unlock", {"credential": "nope"}, request_id=5)
    assert wrong["result"]["unlocked"] is False
    assert wrong["result"]["enabled"] is True

    right = sidecar.call(
        "school.unlock", {"credential": "correct-horse"}, request_id=6
    )
    assert right["result"]["unlocked"] is True
    assert right["result"]["enabled"] is False

    reset = sidecar.call("school.reset_mode_name", request_id=7)
    assert reset["result"]["mode_name"] == "School mode"


def test_narrator_read_defaults_to_disabled(sidecar: SidecarProcess) -> None:
    response = sidecar.call("narrator.read")
    result = response["result"]
    assert result["enabled"] is False
    assert result["language"] == "english"


def test_narrator_write_round_trips_and_normalises(sidecar: SidecarProcess) -> None:
    write_response = sidecar.call(
        "narrator.write", {"enabled": True, "language": "both"}
    )
    result = write_response["result"]
    assert result["enabled"] is True
    assert result["language"] == "both"

    read_response = sidecar.call("narrator.read", request_id=2)
    assert read_response["result"]["enabled"] is True
    assert read_response["result"]["language"] == "both"


def test_narrator_write_rejects_unknown_field(sidecar: SidecarProcess) -> None:
    response = sidecar.call("narrator.write", {"totally_not_a_field": 1})
    assert response["error"]["code"] == "invalid_params"
