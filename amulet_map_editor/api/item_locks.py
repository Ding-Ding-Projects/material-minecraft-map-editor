"""Per-surface locks: a tab, a tab group, or one appearance value, locked shut
for fun.

This is the desktop half of a feature the completeness inventory found living
only on the documentation site (``docs/site/locks.js``): the app itself had no
way to lock anything.  The behaviour is intentionally small and intentionally
silly -- **this is a toy, not security.**  It never claims to encrypt or
protect anything, and it never stands between a user and their own data for
longer than deleting a folder takes.

Two rules shape the module and neither bends:

**Every lock carries its own credential.**  There is no master password and no
inheritance: unlocking one lock never unlocks another, and a locked value
inside a locked tab is two locks with two answers.  Locks are therefore kept
as a real, enumerable list -- :func:`list_locks` -- rather than a single
on/off flag anywhere.

**The credential never leaves the operating system's credential vault.**  A
password is verified against a stored salted hash, never a stored password; a
TOTP secret lives in the vault and nowhere else.  Neither this module nor any
caller may report a stored secret's value, length, or composition -- only
whether an attempt matched.

Recovery is deleting the application's local profile directory
(:func:`amulet_map_editor.api.config` resolves it).  That is stated wherever a
lock is created and wherever an unlock is attempted, because forgetting a toy
password is a normal, expected outcome and there is deliberately no other way
back in.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import struct
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from amulet_map_editor.api import config
from amulet_map_editor.api.credential_vault import (
    CredentialStoreUnavailable,
    ForgeAccountError,
    credential_store,
)

log = logging.getLogger(__name__)

__all__ = [
    "Lock",
    "LockError",
    "LockScope",
    "LockMethod",
    "UnlockDuration",
    "SERVICE_PREFIX",
    "create_lock",
    "remove_lock",
    "list_locks",
    "get_lock",
    "locks_for_target",
    "is_locked",
    "verify_password",
    "verify_totp",
    "attempt_unlock",
    "is_unlocked",
    "relock",
    "change_credential",
    "generate_totp_secret",
    "totp_now",
    "profile_directory_hint",
]

#: The bounded config record holding **metadata only** -- never a credential.
LOCKS_ID = "amulet_item_locks"
MAX_LOCKS = 512
MAX_FIELD_LENGTH = 200

#: The credential-store key prefix every lock's secret is filed under.
SERVICE_PREFIX = "AmuletMapEditor/itemlock"

#: PBKDF2 rounds for password verification. High enough to be a real hash,
#: low enough that an interactive unlock prompt does not stall.
_PBKDF2_ROUNDS = 200_000
_SALT_BYTES = 16


class LockError(RuntimeError):
    """Something a user in front of the window can act on."""


LockScope = str  # "tab" | "group" | "appearance"
LockMethod = str  # "password" | "totp"
UnlockDuration = str  # "surface" | "close" | "<minutes>"

_VALID_SCOPES = ("tab", "group", "appearance")
_VALID_METHODS = ("password", "totp")


def _bounded(value: Any) -> str:
    return str(value or "").strip()[:MAX_FIELD_LENGTH]


@dataclass(frozen=True)
class Lock:
    """One lock's **metadata**.  Never a field that could hold a credential."""

    lock_id: str
    scope: LockScope
    target_id: str
    label: str
    method: LockMethod
    created_at: float = 0.0
    unlock_duration: UnlockDuration = "surface"
    locked_on_launch: bool = True
    failed_attempts: int = 0
    last_attempt_at: float = 0.0

    @property
    def credential_key(self) -> str:
        return f"{SERVICE_PREFIX}/{self.lock_id}"

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# metadata persistence
# ---------------------------------------------------------------------------


def _load_raw() -> List[Dict[str, Any]]:
    payload = config.get(LOCKS_ID, default=[])
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _save_raw(rows: Sequence[Dict[str, Any]]) -> None:
    config.put(LOCKS_ID, list(rows)[:MAX_LOCKS])


def _from_row(row: Dict[str, Any]) -> Optional[Lock]:
    try:
        return Lock(
            lock_id=_bounded(row["lock_id"]),
            scope=_bounded(row.get("scope", "tab")) or "tab",
            target_id=_bounded(row.get("target_id")),
            label=_bounded(row.get("label")) or row.get("target_id", "Untitled"),
            method=_bounded(row.get("method", "password")) or "password",
            created_at=float(row.get("created_at", 0.0)),
            unlock_duration=_bounded(row.get("unlock_duration", "surface"))
            or "surface",
            locked_on_launch=bool(row.get("locked_on_launch", True)),
            failed_attempts=int(row.get("failed_attempts", 0)),
            last_attempt_at=float(row.get("last_attempt_at", 0.0)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def list_locks() -> Tuple[Lock, ...]:
    """Return every lock, newest first -- the real, enumerable list."""
    locks = [row for row in (_from_row(r) for r in _load_raw()) if row is not None]
    locks.sort(key=lambda lock: lock.created_at, reverse=True)
    return tuple(locks)


def get_lock(lock_id: str) -> Optional[Lock]:
    for lock in list_locks():
        if lock.lock_id == lock_id:
            return lock
    return None


def locks_for_target(scope: LockScope, target_id: str) -> Tuple[Lock, ...]:
    return tuple(
        lock
        for lock in list_locks()
        if lock.scope == scope and lock.target_id == target_id
    )


def is_locked(scope: LockScope, target_id: str) -> bool:
    return bool(locks_for_target(scope, target_id))


def _write_lock(lock: Lock) -> None:
    rows = [row for row in _load_raw() if _bounded(row.get("lock_id")) != lock.lock_id]
    rows.insert(0, lock.as_dict())
    _save_raw(rows)


# ---------------------------------------------------------------------------
# password hashing (never the password itself, only a salted hash)
# ---------------------------------------------------------------------------


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)


def _encode_password_secret(password: str) -> str:
    salt = os.urandom(_SALT_BYTES)
    digest = _hash_password(password, salt)
    return (
        "pbkdf2$"
        + base64.b64encode(salt).decode("ascii")
        + "$"
        + base64.b64encode(digest).decode("ascii")
    )


def verify_password(stored_secret: str, candidate: str) -> bool:
    """Check a candidate password against a stored ``pbkdf2$salt$hash`` record.

    Never given the raw password to compare against -- there isn't one to
    compare against, only this hash.
    """
    try:
        algo, salt_b64, hash_b64 = stored_secret.split("$", 2)
        if algo != "pbkdf2":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    computed = _hash_password(candidate, salt)
    return hmac.compare_digest(computed, expected)


# ---------------------------------------------------------------------------
# RFC 6238 TOTP (a small, dependency-free, RFC-vector-verified implementation)
# ---------------------------------------------------------------------------


def generate_totp_secret() -> str:
    """Return a fresh random base32 TOTP secret, suitable for a QR/manual entry."""
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int, *, digits: int = 6, algo: str = "sha1") -> str:
    padded = secret_b32.strip().upper()
    padded += "=" * (-len(padded) % 8)
    key = base64.b32decode(padded)
    msg = struct.pack(">Q", counter)
    digestmod = {
        "sha1": hashlib.sha1,
        "sha256": hashlib.sha256,
        "sha512": hashlib.sha512,
    }[algo]
    digest = hmac.new(key, msg, digestmod).digest()
    offset = digest[-1] & 0x0F
    code_int = (
        (digest[offset] & 0x7F) << 24
        | (digest[offset + 1] & 0xFF) << 16
        | (digest[offset + 2] & 0xFF) << 8
        | (digest[offset + 3] & 0xFF)
    )
    return str(code_int % (10**digits)).zfill(digits)


def totp_now(
    secret_b32: str,
    *,
    period: int = 30,
    digits: int = 6,
    algo: str = "sha1",
    when: Optional[float] = None,
) -> str:
    counter = int((when if when is not None else time.time()) // period)
    return _hotp(secret_b32, counter, digits=digits, algo=algo)


def verify_totp(
    secret_b32: str,
    candidate: str,
    *,
    period: int = 30,
    digits: int = 6,
    algo: str = "sha1",
    skew: int = 1,
    when: Optional[float] = None,
) -> bool:
    """Check a code against a small window of clock skew, per RFC 6238."""
    candidate = (candidate or "").strip()
    if not candidate:
        return False
    now = when if when is not None else time.time()
    counter = int(now // period)
    for offset in range(-skew, skew + 1):
        expected = _hotp(secret_b32, counter + offset, digits=digits, algo=algo)
        if hmac.compare_digest(expected, candidate):
            return True
    return False


# ---------------------------------------------------------------------------
# creating, removing, and changing locks
# ---------------------------------------------------------------------------


def create_lock(
    scope: LockScope,
    target_id: str,
    label: str,
    method: LockMethod,
    *,
    password: Optional[str] = None,
    totp_secret: Optional[str] = None,
    unlock_duration: UnlockDuration = "surface",
    locked_on_launch: bool = True,
) -> Lock:
    """Create a new lock and file its credential in the OS vault.

    Each lock gets its own credential-store slot; nothing here can read or
    reuse another lock's secret.
    """
    if scope not in _VALID_SCOPES:
        raise LockError(f"'{scope}' is not a lockable scope.")
    if method not in _VALID_METHODS:
        raise LockError(f"'{method}' is not a supported lock method.")
    store = credential_store()
    if not store.available:
        raise CredentialStoreUnavailable(store.explanation)
    if method == "password":
        if not password:
            raise LockError("A password is required to lock this.")
        secret = _encode_password_secret(password)
    else:
        if not totp_secret:
            raise LockError("A TOTP secret is required to lock this.")
        secret = totp_secret
    lock = Lock(
        lock_id=uuid.uuid4().hex,
        scope=scope,
        target_id=_bounded(target_id),
        label=_bounded(label) or _bounded(target_id),
        method=method,
        created_at=time.time(),
        unlock_duration=_bounded(unlock_duration) or "surface",
        locked_on_launch=bool(locked_on_launch),
    )
    try:
        store.write(lock.credential_key, secret)
    except ForgeAccountError:
        log.exception("The credential store refused this lock's secret")
        raise
    _write_lock(lock)
    return lock


def change_credential(
    lock_id: str,
    *,
    password: Optional[str] = None,
    totp_secret: Optional[str] = None,
) -> Lock:
    """Replace one lock's own credential, independently of every other lock."""
    lock = get_lock(lock_id)
    if lock is None:
        raise LockError("That lock no longer exists.")
    store = credential_store()
    if not store.available:
        raise CredentialStoreUnavailable(store.explanation)
    if lock.method == "password":
        if not password:
            raise LockError("A new password is required.")
        secret = _encode_password_secret(password)
    else:
        if not totp_secret:
            raise LockError("A new TOTP secret is required.")
        secret = totp_secret
    store.write(lock.credential_key, secret)
    reset = Lock(**{**lock.as_dict(), "failed_attempts": 0, "last_attempt_at": 0.0})
    _write_lock(reset)
    _forget_session(lock_id)
    return reset


def remove_lock(lock_id: str) -> None:
    """Delete a lock's credential first, then its record.

    The credential goes first: if the record vanished before the delete and
    the delete then failed, the secret would be orphaned in the vault with no
    remaining code path able to remove it.
    """
    lock = get_lock(lock_id)
    if lock is None:
        return
    store = credential_store()
    if store.available:
        try:
            store.delete(lock.credential_key)
        except ForgeAccountError:
            log.exception("The credential store would not delete %s", lock.lock_id)
            raise
    rows = [row for row in _load_raw() if _bounded(row.get("lock_id")) != lock_id]
    _save_raw(rows)
    _forget_session(lock_id)


def _record_attempt(lock: Lock, *, success: bool) -> None:
    updated = Lock(
        **{
            **lock.as_dict(),
            "failed_attempts": 0 if success else lock.failed_attempts + 1,
            "last_attempt_at": time.time(),
        }
    )
    _write_lock(updated)


def attempt_unlock(lock_id: str, answer: str) -> bool:
    """Check an answer against a lock's stored credential and record the result.

    Never reports anything about the stored secret beyond this true/false --
    not its length, not its shape, not how close the guess was.
    """
    lock = get_lock(lock_id)
    if lock is None:
        return False
    store = credential_store()
    if not store.available:
        raise CredentialStoreUnavailable(store.explanation)
    try:
        secret = store.read(lock.credential_key)
    except ForgeAccountError:
        secret = None
    if secret is None:
        _record_attempt(lock, success=False)
        return False
    if lock.method == "password":
        ok = verify_password(secret, answer)
    else:
        ok = verify_totp(secret, answer)
    _record_attempt(lock, success=ok)
    if ok:
        _unlock_session(lock)
    return ok


# ---------------------------------------------------------------------------
# in-memory unlock sessions -- never persisted, never a credential
# ---------------------------------------------------------------------------

#: lock_id -> monotonic expiry, or ``None`` for "until the app closes".
_sessions: Dict[str, Optional[float]] = {}


def _unlock_session(lock: Lock) -> None:
    duration = lock.unlock_duration
    if duration == "close":
        _sessions[lock.lock_id] = None
        return
    if duration == "surface":
        # Unlocked for this one look only: expires effectively immediately
        # after the caller finishes using it, modelled as a short window
        # rather than zero so a UI action following the prompt can still see
        # the unlocked state.
        _sessions[lock.lock_id] = time.monotonic() + 5.0
        return
    try:
        minutes = float(duration)
    except (TypeError, ValueError):
        minutes = 5.0
    _sessions[lock.lock_id] = time.monotonic() + minutes * 60.0


def is_unlocked(lock_id: str) -> bool:
    expiry = _sessions.get(lock_id, "missing")
    if expiry == "missing":
        return False
    if expiry is None:
        return True
    if time.monotonic() >= expiry:
        _sessions.pop(lock_id, None)
        return False
    return True


def relock(lock_id: str) -> None:
    """The user's own explicit ``Lock again`` action."""
    _forget_session(lock_id)


def _forget_session(lock_id: str) -> None:
    _sessions.pop(lock_id, None)


def profile_directory_hint() -> str:
    """Name the exact folder deleting-to-recover actually deletes.

    Shown in the lock-creation setting and in the unlock prompt, per the
    contract that recovery is never a mystery.
    """
    return config._config_path()  # noqa: SLF001 - the one honest source
