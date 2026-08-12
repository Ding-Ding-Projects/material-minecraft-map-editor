"""Tests for the sidecar's appearance-preset, item-lock, and authenticator
methods -- spawning the REAL child process over its real stdio pipes, exactly
like ``test_sidecar_protocol.py`` and ``test_sidecar_edit_methods.py``.

These prove the wire seam, not just the Python core underneath it: a request
shaped the way the renderer bridge will actually shape it, dispatched through
the real ``methods.METHODS`` table inside a genuinely separate process, and a
response read back off the pipe. Locks and the authenticator round-trip a
real secret through the real OS credential vault, so those two tests are
skipped outright when that vault is unavailable on the host running the
suite, rather than silently passing on a code path that never touched a
vault.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test_sidecar_protocol import SidecarProcess  # noqa: E402  (reuse the real client)

from amulet_map_editor.api.forge_accounts import credential_store  # noqa: E402

_VAULT_AVAILABLE = credential_store().available
requires_vault = pytest.mark.skipif(
    not _VAULT_AVAILABLE, reason="OS credential vault is unavailable on this host"
)


@pytest.fixture
def sidecar(tmp_path):
    process = SidecarProcess(config_dir=str(tmp_path))
    try:
        yield process
    finally:
        process.close()


def _result(process, method, params=None, request_id=1):
    """Call a method and return its ``result``, failing loudly on an error
    envelope instead of returning it silently -- these tests assert success
    paths, and a swallowed error here would read as a passing assertion on
    ``None``.
    """
    response = process.call(method, params, request_id=request_id)
    assert "error" not in response, response
    return response["result"]


def test_appearance_presets_round_trip(sidecar):
    saved = _result(
        sidecar,
        "appearance.presets.save",
        {
            "name": "Midnight",
            "values": {
                "version": 1,
                "theme": "dark",
                "density": "compact",
                "accent": "#00FF00",
                "ui_font": "Segoe UI",
                "ui_scale": 1.25,
            },
        },
    )
    assert saved["preset"]["name"] == "Midnight"
    assert saved["preset"]["values"]["theme"] == "dark"

    listed = _result(sidecar, "appearance.presets.list")
    names = [preset["name"] for preset in listed["presets"]]
    assert "Midnight" in names

    applied = _result(sidecar, "appearance.presets.apply", {"name": "Midnight"})
    assert applied["preferences"]["theme"] == "dark"
    assert applied["preferences"]["accent"] == "#00FF00"

    exported = _result(sidecar, "appearance.presets.export", {"name": "Midnight"})
    assert "amulet-appearance-preset" in exported["export"]

    deleted = _result(sidecar, "appearance.presets.delete", {"name": "Midnight"})
    assert deleted["deleted"] is True

    reset = _result(sidecar, "appearance.reset_all")
    assert reset["preferences"]["theme"] == "system"


def test_appearance_presets_apply_unknown_name_is_structured_error(sidecar):
    response = sidecar.call("appearance.presets.apply", {"name": "Nope"})
    assert "error" in response, response
    assert "Nope" in response["error"]["message"]


@requires_vault
def test_lock_full_lifecycle_through_real_vault(sidecar):
    created = _result(
        sidecar,
        "locks.create",
        {
            "scope": "tab",
            "target_id": "tab-1",
            "label": "My tab",
            "method": "password",
            "password": "correct horse battery staple",
        },
    )
    lock_id = created["lock"]["lock_id"]
    assert created["lock"]["is_unlocked"] is False

    wrong = _result(
        sidecar, "locks.attempt_unlock", {"lock_id": lock_id, "answer": "nope"}
    )
    assert wrong["unlocked"] is False

    right = _result(
        sidecar,
        "locks.attempt_unlock",
        {"lock_id": lock_id, "answer": "correct horse battery staple"},
    )
    assert right["unlocked"] is True

    listed = _result(sidecar, "locks.list")
    match = next(row for row in listed["locks"] if row["lock_id"] == lock_id)
    assert match["is_unlocked"] is True
    assert listed["recovery_hint"]

    relocked = _result(sidecar, "locks.relock", {"lock_id": lock_id})
    assert relocked["relocked"] is True

    removed = _result(sidecar, "locks.remove", {"lock_id": lock_id})
    assert removed["removed"] is True
    listed_after = _result(sidecar, "locks.list")
    assert all(row["lock_id"] != lock_id for row in listed_after["locks"])


@requires_vault
def test_authenticator_full_lifecycle_through_real_vault(sidecar):
    secret = _result(sidecar, "auth.generate_secret")["secret"]
    assert secret

    uri = _result(
        sidecar,
        "auth.build_uri",
        {"issuer": "Amulet", "account": "test@example.com", "secret": secret},
    )
    assert uri["uri"].startswith("otpauth://totp/")

    entry = _result(
        sidecar,
        "auth.add_entry",
        {"issuer": "Amulet", "account": "test@example.com", "secret": secret},
    )["entry"]
    assert entry["label"] == "Amulet · test@example.com"

    listed = _result(sidecar, "auth.list_entries")
    assert any(row["id"] == entry["id"] for row in listed["entries"])

    code = _result(sidecar, "auth.current_code", {"entry_id": entry["id"]})
    assert len(code["code"]) == 6
    assert code["code"].isdigit()

    exported = _result(sidecar, "auth.export")
    row = next(item for item in exported["entries"] if item["id"] == entry["id"])
    assert "secret" not in row
    assert "omitted" in row["note"]

    renamed = _result(
        sidecar,
        "auth.rename_entry",
        {"entry_id": entry["id"], "issuer": "Amulet Renamed", "account": "test@example.com"},
    )
    assert renamed["renamed"] is True

    deleted = _result(sidecar, "auth.delete_entry", {"entry_id": entry["id"]})
    assert deleted["deleted"] is True
    listed_after = _result(sidecar, "auth.list_entries")
    assert all(row["id"] != entry["id"] for row in listed_after["entries"])
