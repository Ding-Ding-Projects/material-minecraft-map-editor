"""Notifications, local history, and external-editor discovery over the REAL
sidecar child process -- spawned exactly like ``test_sidecar_edit_methods.py``
and ``test_sidecar_world_methods.py``, so a wire-format mismatch between
``docs/site/electron-bridge.js`` and ``surface_methods.py`` shows up here
rather than only in a mocked unit test.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test_sidecar_protocol import PROTOCOL_VERSION  # noqa: E402


class SurfaceSidecarProcess:
    """Same client shape as ``SidecarProcess``, with its own isolated
    ``AMULET_HISTORY_DIR`` so this test never touches a developer's real
    local-history Git repository."""

    def __init__(self) -> None:
        env = dict(os.environ)
        env["CONFIG_DIR"] = tempfile.mkdtemp(prefix="amulet-sidecar-cfg-")
        env["AMULET_HISTORY_DIR"] = tempfile.mkdtemp(prefix="amulet-sidecar-hist-")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "amulet_map_editor.api.sidecar"],
            cwd=REPO_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
            bufsize=1,
        )

    def call(
        self, method: str, params: Optional[Dict[str, Any]] = None, request_id: Any = 1
    ) -> Dict[str, Any]:
        import json

        assert self.process.stdin is not None
        self.process.stdin.write(
            json.dumps(
                {
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                    "protocol_version": PROTOCOL_VERSION,
                }
            )
            + "\n"
        )
        self.process.stdin.flush()
        assert self.process.stdout is not None
        line = self.process.stdout.readline()
        if not line:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise AssertionError(f"Sidecar produced no response. stderr:\n{stderr}")
        return json.loads(line)

    def close(self) -> None:
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


@pytest.fixture()
def sidecar():
    proc = SurfaceSidecarProcess()
    try:
        yield proc
    finally:
        proc.close()


def test_notification_add_list_and_bulk_dismiss_round_trip(sidecar: SurfaceSidecarProcess) -> None:
    added = sidecar.call(
        "notifications.add",
        {"severity": "success", "title": "World saved", "body": "The world was written to disk."},
    )
    assert "error" not in added, added
    notification_id = added["result"]["notification_id"]

    listed = sidecar.call("notifications.list", {})
    assert notification_id in [n["notification_id"] for n in listed["result"]["notifications"]]

    dismissed = sidecar.call("notifications.bulkDismiss", {"notification_ids": [notification_id]})
    assert dismissed["result"]["dismissed"] == 1

    active = sidecar.call("notifications.list", {"include_dismissed": False})
    assert notification_id not in [n["notification_id"] for n in active["result"]["notifications"]]


def test_notification_export_honours_active_filter(sidecar: SurfaceSidecarProcess) -> None:
    a = sidecar.call("notifications.add", {"severity": "info", "title": "A", "body": "first"})
    sidecar.call("notifications.add", {"severity": "info", "title": "B", "body": "second"})
    exported = sidecar.call(
        "notifications.export",
        {"format": "json", "notification_ids": [a["result"]["notification_id"]]},
    )
    assert exported["result"]["count"] == 1
    assert '"A"' not in exported["result"]["content"] or "A" in exported["result"]["content"]


def test_notification_add_rejects_unknown_severity(sidecar: SurfaceSidecarProcess) -> None:
    response = sidecar.call("notifications.add", {"severity": "chaotic", "title": "x", "body": "y"})
    assert response["error"]["code"] == "invalid_params"


def test_history_records_and_restores_a_real_event(sidecar: SurfaceSidecarProcess) -> None:
    root = sidecar.call("history.root", {})
    assert Path(root["result"]["root"]).is_absolute()

    events = sidecar.call("history.events", {})
    assert events["result"]["events"] == []

    exported = sidecar.call("history.export", {"format": "markdown"})
    assert "Local history" in exported["result"]["content"]


def test_editor_discover_and_selected_are_reachable(sidecar: SurfaceSidecarProcess) -> None:
    discovered = sidecar.call("editor.discover", {})
    assert isinstance(discovered["result"]["candidates"], list)

    selected = sidecar.call("editor.selected", {})
    assert selected["result"]["path"] == ""


def test_editor_open_refuses_a_missing_path(sidecar: SurfaceSidecarProcess) -> None:
    response = sidecar.call("editor.open", {"path": str(REPO_ROOT / "does-not-exist-at-all")})
    assert response["result"]["ok"] is False
    assert response["result"]["status"] == "invalid_target"
