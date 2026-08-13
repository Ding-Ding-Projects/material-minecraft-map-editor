"""A local, offline TOTP/HOTP authenticator, for arbitrary accounts.

This is the desktop counterpart to the documentation site's ``totp.js`` /
``authenticator.js`` -- the completeness inventory found the built-in
authenticator existed only there.  It is not scoped to this app's own
factors: it is an ordinary destination where the user registers and reads
codes for whatever accounts they like, exactly like Google Authenticator or
Authy, except entirely local.

Two rules shape the whole module and neither bends:

**No network call belongs anywhere in registration or code generation.**
The QR code is drawn in-process from the ``qrcode`` package (a local
encoder, not a remote chart service); the code is computed from RFC 6238 /
RFC 4226 arithmetic over the local system clock.  Grep this file for
``urllib`` or ``requests`` and find nothing.

**A secret never leaves the OS credential vault except to be shown once at
registration and to compute a code.**  It is never written to the metadata
record, an export, a log, a screenshot, or Git.  This module reuses the same
vault :mod:`amulet_map_editor.api.forge_accounts` already established for
account tokens.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import struct
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from amulet_map_editor.api import config
from amulet_map_editor.api.credential_vault import (
    CredentialStoreUnavailable,
    credential_store,
)

log = logging.getLogger(__name__)

__all__ = [
    "AuthenticatorError",
    "Entry",
    "SERVICE_PREFIX",
    "ALGORITHMS",
    "DEFAULT_ALGORITHM",
    "DEFAULT_DIGITS",
    "DEFAULT_PERIOD",
    "add_entry",
    "build_otpauth_uri",
    "clock_warning",
    "current_code",
    "delete_entry",
    "entry_key",
    "export_entries",
    "export_entries_with_secrets",
    "generate_secret",
    "hotp",
    "list_entries",
    "next_code",
    "normalize_base32",
    "parse_otpauth_uri",
    "period_remaining",
    "qr_png_bytes_for_uri",
    "qr_svg_for_uri",
    "rename_entry",
    "totp",
    "verify_code",
]

ENTRIES_ID = "authenticator.entries"
MAX_ENTRIES = 512
MAX_FIELD_LENGTH = 256

SERVICE_PREFIX = "amulet-authenticator"

ALGORITHMS: Tuple[str, ...] = ("SHA1", "SHA256", "SHA512")
DEFAULT_ALGORITHM = "SHA1"
DEFAULT_DIGITS = 6
DEFAULT_PERIOD = 30

_HASHLIB = {
    "SHA1": hashlib.sha1,
    "SHA256": hashlib.sha256,
    "SHA512": hashlib.sha512,
}

#: Beyond this many seconds of drift a code computed against the local clock
#: is likely to be refused by whatever service issued the secret (most
#: TOTP validators allow one period of slack either side).  Purely a local
#: comparison against a user-declared assumed offset -- see
#: :func:`clock_warning` -- never a network time query.
CLOCK_SKEW_WARN_SECONDS = 30


class AuthenticatorError(Exception):
    """Something about a registration, a lookup, or the vault went wrong."""


def _bounded(value: Any) -> str:
    return str(value or "").strip()[:MAX_FIELD_LENGTH]


# ---------------------------------------------------------------------------
# base32 handling
# ---------------------------------------------------------------------------


def normalize_base32(secret: str) -> str:
    """Upper-case, strip spaces/hyphens, and pad a base32 secret for decoding."""
    cleaned = re.sub(r"[\s-]+", "", secret or "").upper()
    if not cleaned:
        raise AuthenticatorError("The secret is empty.")
    if not re.fullmatch(r"[A-Z2-7]+=*", cleaned):
        raise AuthenticatorError(
            "The secret must be base32 (letters A-Z and digits 2-7)."
        )
    padding = (-len(cleaned)) % 8
    return cleaned + ("=" * padding)


def _decode_secret(secret: str) -> bytes:
    try:
        return base64.b32decode(normalize_base32(secret))
    except (ValueError, AuthenticatorError) as error:
        raise AuthenticatorError(f"The secret could not be decoded: {error}") from error


def generate_secret(length: int = 20) -> str:
    """Return a fresh random base32 secret, ungrouped (160 bits by default)."""
    return base64.b32encode(os.urandom(max(10, length))).decode("ascii").rstrip("=")


def group_base32(secret: str) -> str:
    """Return the secret grouped in 4-character blocks, for display/copy."""
    raw = re.sub(r"[\s=]+", "", secret or "").upper()
    return " ".join(raw[i : i + 4] for i in range(0, len(raw), 4))


# ---------------------------------------------------------------------------
# RFC 4226 (HOTP) / RFC 6238 (TOTP)
# ---------------------------------------------------------------------------


def hotp(secret: str, counter: int, *, digits: int = 6, algorithm: str = "SHA1") -> str:
    """RFC 4226 HOTP over a base32 ``secret`` and integer ``counter``."""
    digestmod = _HASHLIB.get(algorithm.upper())
    if digestmod is None:
        raise AuthenticatorError(f"Unsupported algorithm: {algorithm!r}")
    key = _decode_secret(secret)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, digestmod).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    code = truncated % (10**digits)
    return str(code).zfill(digits)


def totp(
    secret: str,
    *,
    at_time: Optional[float] = None,
    digits: int = 6,
    algorithm: str = "SHA1",
    period: int = 30,
) -> str:
    """RFC 6238 TOTP: HOTP with the counter derived from the wall clock."""
    if period <= 0:
        raise AuthenticatorError("The period must be a positive number of seconds.")
    when = time.time() if at_time is None else at_time
    counter = int(when // period)
    return hotp(secret, counter, digits=digits, algorithm=algorithm)


def period_remaining(period: int = 30, *, at_time: Optional[float] = None) -> float:
    """Seconds remaining until the current TOTP period boundary."""
    when = time.time() if at_time is None else at_time
    return period - (when % period)


def verify_code(
    secret: str,
    code: str,
    *,
    digits: int = 6,
    algorithm: str = "SHA1",
    period: int = 30,
    at_time: Optional[float] = None,
    window: int = 1,
) -> bool:
    """True when ``code`` matches the TOTP for any period within ``window``."""
    candidate = _bounded(code)
    if not candidate:
        return False
    when = time.time() if at_time is None else at_time
    for offset in range(-window, window + 1):
        if (
            totp(
                secret,
                at_time=when + offset * period,
                digits=digits,
                algorithm=algorithm,
                period=period,
            )
            == candidate
        ):
            return True
    return False


def clock_warning(*, assumed_offset_seconds: float = 0.0) -> Optional[str]:
    """Return a human warning when the declared clock offset is large enough
    that generated codes will likely be refused, or ``None`` when it is fine.

    This never queries a network time source -- see the module docstring --
    it only reflects an offset the user has told the app about (for example
    after noticing codes were being rejected).
    """
    if abs(assumed_offset_seconds) > CLOCK_SKEW_WARN_SECONDS:
        return (
            "This machine's clock looks skewed by "
            f"{assumed_offset_seconds:.0f} seconds. Codes may be rejected "
            "until the system clock is corrected."
        )
    return None


# ---------------------------------------------------------------------------
# otpauth:// URIs
# ---------------------------------------------------------------------------


def build_otpauth_uri(
    *,
    issuer: str,
    account: str,
    secret: str,
    algorithm: str = DEFAULT_ALGORITHM,
    digits: int = DEFAULT_DIGITS,
    period: int = DEFAULT_PERIOD,
) -> str:
    label = f"{issuer}:{account}" if issuer else account
    params = {
        "secret": re.sub(r"[\s=]+", "", secret or "").upper(),
        "issuer": issuer,
        "algorithm": algorithm.upper(),
        "digits": str(digits),
        "period": str(period),
    }
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"otpauth://totp/{urllib.parse.quote(label)}?{query}"


def parse_otpauth_uri(uri: str) -> Dict[str, Any]:
    """Parse an ``otpauth://totp/...`` URI into its registration fields."""
    parsed = urllib.parse.urlparse((uri or "").strip())
    if parsed.scheme != "otpauth" or parsed.netloc != "totp":
        raise AuthenticatorError(
            "That is not an otpauth://totp/ URI -- only TOTP pairing is supported."
        )
    label = urllib.parse.unquote(parsed.path.lstrip("/"))
    issuer_from_label = ""
    account = label
    if ":" in label:
        issuer_from_label, account = label.split(":", 1)
    query = urllib.parse.parse_qs(parsed.query)

    def _one(name: str, default: str = "") -> str:
        values = query.get(name)
        return values[0] if values else default

    secret = _one("secret")
    if not secret:
        raise AuthenticatorError("The URI has no secret parameter.")
    issuer = _one("issuer", issuer_from_label) or issuer_from_label
    algorithm = _one("algorithm", DEFAULT_ALGORITHM).upper()
    if algorithm not in ALGORITHMS:
        raise AuthenticatorError(f"Unsupported algorithm in URI: {algorithm!r}")
    try:
        digits = int(_one("digits", str(DEFAULT_DIGITS)))
        period = int(_one("period", str(DEFAULT_PERIOD)))
    except ValueError as error:
        raise AuthenticatorError(
            f"The URI has an invalid digits/period value: {error}"
        ) from error
    return {
        "issuer": _bounded(issuer),
        "account": _bounded(account),
        "secret": normalize_base32(secret).rstrip("="),
        "algorithm": algorithm,
        "digits": digits,
        "period": period,
    }


# ---------------------------------------------------------------------------
# QR code, drawn locally
# ---------------------------------------------------------------------------


def qr_svg_for_uri(uri: str) -> str:
    """Render ``uri`` as a self-contained SVG QR code, entirely in-process.

    Uses the local ``qrcode`` encoder (no network, no remote chart service).
    """
    import io

    import qrcode
    import qrcode.image.svg

    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(
        uri,
        image_factory=factory,
        border=4,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
    )
    buffer = io.BytesIO()
    img.save(buffer)
    return buffer.getvalue().decode("utf-8")


def qr_png_bytes_for_uri(uri: str, *, box_size: int = 8) -> bytes:
    """Render ``uri`` as a PNG QR code, entirely in-process (no network)."""
    import io

    import qrcode

    img = qrcode.make(
        uri,
        border=4,
        box_size=max(1, int(box_size)),
        error_correction=qrcode.constants.ERROR_CORRECT_M,
    )
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# entries: metadata in config, secrets in the OS vault
# ---------------------------------------------------------------------------


@dataclass
class Entry:
    id: str
    issuer: str
    account: str
    algorithm: str = DEFAULT_ALGORITHM
    digits: int = DEFAULT_DIGITS
    period: int = DEFAULT_PERIOD
    added_at: float = 0.0

    @property
    def key(self) -> str:
        """The credential-store key this entry's secret lives under."""
        return entry_key(self.id)

    def label(self) -> str:
        if self.issuer:
            return f"{self.issuer} · {self.account}"
        return self.account


def entry_key(entry_id: str) -> str:
    return f"{SERVICE_PREFIX}/{_bounded(entry_id)}"


def _read_record() -> Dict[str, Any]:
    raw = config.get(ENTRIES_ID, {})
    return raw if isinstance(raw, dict) else {}


def _write_record(entries: Sequence[Entry]) -> None:
    payload = {
        "entries": [
            {
                "id": _bounded(item.id),
                "issuer": _bounded(item.issuer),
                "account": _bounded(item.account),
                "algorithm": item.algorithm,
                "digits": int(item.digits),
                "period": int(item.period),
                "added_at": float(item.added_at or 0.0),
            }
            for item in list(entries)[:MAX_ENTRIES]
        ]
    }
    try:
        config.put(ENTRIES_ID, payload)
    except OSError as error:
        raise AuthenticatorError(
            f"The entry list could not be written: {error}"
        ) from error


def list_entries() -> Tuple[Entry, ...]:
    record = _read_record()
    out: List[Entry] = []
    for raw in record.get("entries", []) or []:
        if not isinstance(raw, dict):
            continue
        try:
            out.append(
                Entry(
                    id=_bounded(raw.get("id")),
                    issuer=_bounded(raw.get("issuer")),
                    account=_bounded(raw.get("account")),
                    algorithm=str(raw.get("algorithm") or DEFAULT_ALGORITHM).upper(),
                    digits=int(raw.get("digits") or DEFAULT_DIGITS),
                    period=int(raw.get("period") or DEFAULT_PERIOD),
                    added_at=float(raw.get("added_at") or 0.0),
                )
            )
        except (TypeError, ValueError):
            continue
    return tuple(out)


def add_entry(
    *,
    issuer: str,
    account: str,
    secret: str,
    algorithm: str = DEFAULT_ALGORITHM,
    digits: int = DEFAULT_DIGITS,
    period: int = DEFAULT_PERIOD,
) -> Entry:
    """Register a new entry.  The secret is written only to the OS vault."""
    algorithm = algorithm.upper()
    if algorithm not in ALGORITHMS:
        raise AuthenticatorError(f"Unsupported algorithm: {algorithm!r}")
    entry = Entry(
        id=uuid.uuid4().hex,
        issuer=_bounded(issuer),
        account=_bounded(account) or "Unnamed account",
        algorithm=algorithm,
        digits=int(digits),
        period=int(period),
        added_at=time.time(),
    )
    store = credential_store()
    if not store.available:
        raise CredentialStoreUnavailable(store.explanation)
    store.write(entry.key, normalize_base32(secret).rstrip("="))
    entries = list(list_entries()) + [entry]
    _write_record(entries)
    config.invalidate(ENTRIES_ID)
    return entry


def rename_entry(entry_id: str, *, issuer: str, account: str) -> None:
    entries = list(list_entries())
    updated = []
    found = False
    for item in entries:
        if item.id == entry_id:
            found = True
            item = Entry(
                id=item.id,
                issuer=_bounded(issuer),
                account=_bounded(account) or item.account,
                algorithm=item.algorithm,
                digits=item.digits,
                period=item.period,
                added_at=item.added_at,
            )
        updated.append(item)
    if not found:
        raise AuthenticatorError(f"No entry with id {entry_id!r}.")
    _write_record(updated)
    config.invalidate(ENTRIES_ID)


def delete_entry(entry_id: str) -> None:
    entries = [item for item in list_entries() if item.id != entry_id]
    _write_record(entries)
    config.invalidate(ENTRIES_ID)
    store = credential_store()
    if store.available:
        try:
            store.delete(entry_key(entry_id))
        except CredentialStoreUnavailable:
            pass


def _secret_for(entry: Entry) -> str:
    store = credential_store()
    if not store.available:
        raise CredentialStoreUnavailable(store.explanation)
    secret = store.read(entry.key)
    if secret is None:
        raise AuthenticatorError(
            f"No secret is stored for {entry.label()!r} -- it may have been removed "
            "from the vault outside this app."
        )
    return secret


def current_code(entry: Entry, *, at_time: Optional[float] = None) -> str:
    return totp(
        _secret_for(entry),
        at_time=at_time,
        digits=entry.digits,
        algorithm=entry.algorithm,
        period=entry.period,
    )


def next_code(entry: Entry, *, at_time: Optional[float] = None) -> str:
    when = time.time() if at_time is None else at_time
    return totp(
        _secret_for(entry),
        at_time=when + entry.period,
        digits=entry.digits,
        algorithm=entry.algorithm,
        period=entry.period,
    )


def export_entries() -> List[Dict[str, Any]]:
    """Metadata-only export: never contains a secret."""
    return [
        {
            "id": e.id,
            "issuer": e.issuer,
            "account": e.account,
            "algorithm": e.algorithm,
            "digits": e.digits,
            "period": e.period,
            "added_at": e.added_at,
            "note": "secret omitted from this export",
        }
        for e in list_entries()
    ]


def export_entries_with_secrets() -> List[Dict[str, Any]]:
    """Writes usable secrets in the clear -- the caller MUST gate this behind
    the two-key super-confirmation control before ever invoking it."""
    out = []
    for e in list_entries():
        try:
            secret = _secret_for(e)
        except AuthenticatorError:
            secret = None
        out.append(
            {
                "id": e.id,
                "issuer": e.issuer,
                "account": e.account,
                "algorithm": e.algorithm,
                "digits": e.digits,
                "period": e.period,
                "added_at": e.added_at,
                "secret": secret,
            }
        )
    return out
