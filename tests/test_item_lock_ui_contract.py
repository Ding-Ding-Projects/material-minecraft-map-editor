"""Construct the lock UI for real, on a real frame, and read the captured PNG.

Source text can prove the popovers exist; it proves nothing about whether they
paint. This builds the real "Lock…" popover, the real unlock popover, and the
real manage-locks dialog in a real ``wx.Frame``, drives them with a fake
credential store so no real vault is touched, and captures the composited
result.
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import amulet_map_editor  # noqa: E402

assert amulet_map_editor.__file__.startswith(REPO)

from amulet_map_editor.api import forge_accounts, item_locks  # noqa: E402
from amulet_map_editor.api.studio import widgets  # noqa: E402
from amulet_map_editor.api.wx.ui import item_locks as item_locks_ui  # noqa: E402
from scripts.capture_surface import capture_composite  # noqa: E402
from scripts.capture_surface import settle as capture_surface_settle  # noqa: E402

OFFSCREEN = wx.Point(-31900, -31900)


def _show_offscreen(self, *_args, **_kwargs):
    self.SetPosition(OFFSCREEN)
    self.Show()


class _FakeStore:
    name = "fake"
    available = True
    explanation = "in-memory test double"

    def __init__(self):
        self._data = {}

    def write(self, key, secret):
        self._data[key] = secret

    def read(self, key):
        return self._data.get(key)

    def delete(self, key):
        self._data.pop(key, None)

    def exists(self, key):
        return key in self._data


@pytest.fixture(scope="module")
def app():
    existing = wx.App.Get()
    created = existing is None and wx.App()
    yield existing or created
    if created:
        created.Destroy()


@pytest.fixture
def frame(app):
    os.environ.setdefault("CONFIG_DIR", tempfile.mkdtemp(prefix="amulet-locks-ui-"))
    win = wx.Frame(None, size=(700, 700))
    win.SetPosition(OFFSCREEN)
    win.Show()
    capture_surface_settle(win)
    yield win
    win.Destroy()


@pytest.fixture(autouse=True)
def fake_vault(frame):
    tmp = tempfile.TemporaryDirectory()
    os.environ["CONFIG_DIR"] = tmp.name
    from amulet_map_editor.api import config

    config.invalidate()
    store = _FakeStore()
    forge_accounts._store = store
    item_locks.credential_store = lambda: store
    yield store
    forge_accounts._store = None
    tmp.cleanup()


def test_create_lock_popup_renders(frame, fake_vault, tmp_path):
    anchor = wx.Panel(frame)
    anchor.SetSize((80, 30))
    anchor.Show()
    popup = item_locks_ui._CreateLockPopup(
        frame, anchor, "tab", "tab-1", "Build notes", lambda lock: None
    )
    popup.layout()
    popup.SetPosition(OFFSCREEN)
    popup.Show()
    capture_surface_settle(popup)
    out = str(tmp_path / "create_lock.png")
    result = capture_composite(popup, out)
    assert not result["skipped"], result["skipped"]
    assert os.path.getsize(out) > 0
    popup.Destroy()


def test_unlock_popup_matches_and_mismatches(frame, fake_vault, tmp_path):
    lock = item_locks.create_lock(
        "tab", "tab-1", "Build notes", "password", password="hunter2"
    )
    anchor = wx.Panel(frame)
    anchor.SetSize((80, 30))
    anchor.Show()
    unlocked = []
    popup = item_locks_ui._UnlockPopup(
        frame, anchor, lock, lambda: unlocked.append(True)
    )
    popup.layout()
    popup.SetPosition(OFFSCREEN)
    popup.Show()
    capture_surface_settle(popup)
    out = str(tmp_path / "unlock_prompt.png")
    result = capture_composite(popup, out)
    assert not result["skipped"], result["skipped"]
    assert os.path.getsize(out) > 0

    popup.field.text.SetValue("wrong")
    popup._submit()
    assert not unlocked
    assert item_locks.get_lock(lock.lock_id).failed_attempts == 1

    popup.field.text.SetValue("hunter2")
    popup._submit()
    assert unlocked == [True]
    popup.Destroy()


def test_manage_locks_dialog_lists_and_searches(frame, fake_vault, tmp_path):
    item_locks.create_lock("tab", "tab-1", "Build notes", "password", password="a")
    item_locks.create_lock(
        "appearance", "accent-colour", "Accent colour", "password", password="b"
    )
    dialog = item_locks_ui.ManageLocksDialog(frame)
    dialog.Show()
    capture_surface_settle(dialog)
    out = str(tmp_path / "manage_locks.png")
    result = capture_composite(dialog, out)
    assert not result["skipped"], result["skipped"]
    assert os.path.getsize(out) > 0
    assert "2 of 2 locks" in dialog.feedback.GetLabel()

    dialog.state.query = "Accent"
    dialog._rebuild()
    assert "1 of 2 locks" in dialog.feedback.GetLabel()
    dialog.Destroy()


def test_menu_rows_offer_lock_then_unlock_then_remove(frame, fake_vault):
    anchor = wx.Panel(frame)
    rows = item_locks_ui.lock_menu_rows(frame, anchor, "tab", "tab-9", "Scratch")
    assert [label for label, _ in rows] == ["Lock…"]

    item_locks.create_lock("tab", "tab-9", "Scratch", "password", password="x")
    rows = item_locks_ui.lock_menu_rows(frame, anchor, "tab", "tab-9", "Scratch")
    labels = [label for label, _ in rows]
    assert labels == ["Unlock…", "Remove lock…"]
