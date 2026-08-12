"""Entry lifecycle: the OS vault holds secrets, config holds metadata only,
and ordinary exports omit secrets and say so.
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import amulet_map_editor  # noqa: E402

assert amulet_map_editor.__file__.startswith(REPO)

from amulet_map_editor.api import config  # noqa: E402
from amulet_map_editor.api import authenticator as auth  # noqa: E402
from amulet_map_editor.api.forge_accounts import credential_store  # noqa: E402


@pytest.fixture
def isolated_config(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="amulet-authenticator-")
    monkeypatch.setattr(config, "_path", tmp)
    config.invalidate()
    yield tmp
    config.invalidate()


def _vault_available() -> bool:
    return credential_store().available


@pytest.mark.skipif(
    not _vault_available(), reason="No OS credential vault on this runner"
)
def test_add_list_delete_round_trip(isolated_config):
    secret = auth.generate_secret()
    entry = auth.add_entry(issuer="Example", account="tester", secret=secret)
    try:
        entries = auth.list_entries()
        assert any(e.id == entry.id for e in entries)
        code = auth.current_code(entry)
        assert code.isdigit() and len(code) == entry.digits
    finally:
        auth.delete_entry(entry.id)
    assert not any(e.id == entry.id for e in auth.list_entries())


@pytest.mark.skipif(
    not _vault_available(), reason="No OS credential vault on this runner"
)
def test_entries_survive_a_fresh_module_read(isolated_config):
    secret = auth.generate_secret()
    entry = auth.add_entry(issuer="Persisted", account="carried-over", secret=secret)
    try:
        # Simulate "restart" by dropping the in-process cache and re-reading.
        config.invalidate()
        entries = auth.list_entries()
        assert any(e.id == entry.id and e.account == "carried-over" for e in entries)
    finally:
        auth.delete_entry(entry.id)


@pytest.mark.skipif(
    not _vault_available(), reason="No OS credential vault on this runner"
)
def test_ordinary_export_omits_secrets_and_says_so(isolated_config):
    secret = auth.generate_secret()
    entry = auth.add_entry(issuer="NoLeak", account="nobody", secret=secret)
    try:
        exported = auth.export_entries()
        row = next(e for e in exported if e["id"] == entry.id)
        assert "secret" not in row
        assert "omitted" in row["note"].lower()
        # And the raw dump never contains the actual secret value either.
        assert secret.upper().rstrip("=") not in str(exported)
    finally:
        auth.delete_entry(entry.id)


@pytest.mark.skipif(
    not _vault_available(), reason="No OS credential vault on this runner"
)
def test_secrets_export_is_a_separate_explicit_action(isolated_config):
    """The gate itself lives in the UI (KeyGate); here we only prove the
    secrets-bearing export is a distinctly named function an accidental call
    to the ordinary export path could never reach."""
    secret = auth.generate_secret()
    entry = auth.add_entry(issuer="Explicit", account="gated", secret=secret)
    try:
        ordinary = auth.export_entries()
        assert not any("secret" in row for row in ordinary)
        explicit = auth.export_entries_with_secrets()
        row = next(e for e in explicit if e["id"] == entry.id)
        assert row["secret"] == secret.upper().rstrip("=")
    finally:
        auth.delete_entry(entry.id)


def test_rejects_unsupported_algorithm(isolated_config):
    with pytest.raises(auth.AuthenticatorError):
        auth.add_entry(
            issuer="Bad", account="algo", secret=auth.generate_secret(), algorithm="MD5"
        )


def test_delete_missing_entry_is_a_no_op(isolated_config):
    # Deleting something never registered must not raise.
    auth.delete_entry("does-not-exist")
    assert auth.list_entries() == ()
