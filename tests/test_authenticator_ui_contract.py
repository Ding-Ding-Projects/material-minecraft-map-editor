"""Build the real authenticator dialogs and capture the composited PNGs.

Source text can prove the widgets exist; it proves nothing about whether the
dialog actually paints, whether a registered entry actually shows a live
code, or whether the QR bitmap actually rendered. This constructs the real
``wx.Dialog`` subclasses, drives a real registration, and reads the captured
PNGs back.
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

from amulet_map_editor.api import config  # noqa: E402
from amulet_map_editor.api import authenticator as auth  # noqa: E402
from amulet_map_editor.api.forge_accounts import credential_store  # noqa: E402
from amulet_map_editor.api.wx.ui.authenticator_dialog import (  # noqa: E402
    AuthenticatorDialog,
    RegisterEntryDialog,
)
from scripts.capture_surface import capture_composite  # noqa: E402


@pytest.fixture(scope="module")
def app():
    existing = wx.App.Get()
    created = existing is None and wx.App()
    yield existing or created
    if created:
        created.Destroy()


@pytest.fixture
def frame(app, monkeypatch):
    tmp = tempfile.mkdtemp(prefix="amulet-authenticator-ui-")
    monkeypatch.setattr(config, "_path", tmp)
    config.invalidate()
    win = wx.Frame(None, size=(900, 700))
    win.Show()
    yield win
    win.Destroy()
    config.invalidate()


def _capture_dir() -> str:
    out = os.path.join(tempfile.gettempdir(), "amulet-authenticator-captures")
    os.makedirs(out, exist_ok=True)
    return out


def test_authenticator_dialog_renders_empty_state(frame):
    dialog = AuthenticatorDialog(frame)
    try:
        dialog.Show()
        report = capture_composite(
            dialog, os.path.join(_capture_dir(), "empty_state.png")
        )
        assert report["descendants"] > 5
        assert os.path.getsize(report["path"]) > 0
    finally:
        dialog.Destroy()


@pytest.mark.skipif(
    not credential_store().available, reason="No OS credential vault on this runner"
)
def test_registration_dialog_renders_qr_and_secret(frame):
    dialog = RegisterEntryDialog(frame)
    try:
        dialog.Show()
        dialog.issuer_field.SetValue("CaptureIssuer")
        dialog.account_field.SetValue("capture@example.com")
        dialog._refresh_qr()
        assert dialog.qr_bitmap.GetBitmap().IsOk()
        assert "CaptureIssuer" in dialog.qr_alt.text
        report = capture_composite(
            dialog, os.path.join(_capture_dir(), "registration.png")
        )
        assert report["descendants"] > 5
    finally:
        dialog.Destroy()


@pytest.mark.skipif(
    not credential_store().available, reason="No OS credential vault on this runner"
)
def test_registered_entry_shows_a_live_code_row(frame):
    entry = auth.add_entry(
        issuer="LiveCapture", account="row@example.com", secret=auth.generate_secret()
    )
    try:
        dialog = AuthenticatorDialog(frame)
        try:
            dialog.Show()
            assert len(dialog._rows) == 1
            row = dialog._rows[0]
            assert row.code_label.text.isdigit()
            assert len(row.code_label.text) == entry.digits
            report = capture_composite(
                dialog, os.path.join(_capture_dir(), "with_entry.png")
            )
            assert report["descendants"] > 5
        finally:
            dialog.Destroy()
    finally:
        auth.delete_entry(entry.id)
