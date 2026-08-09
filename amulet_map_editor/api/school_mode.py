"""Shared, local School-mode state and unlock contract.

The record is intentionally separate from product preferences so every
surface can share one local switch without copying a credential into its own
profile.  Only a salted verifier is persisted; the unlock value never leaves
the caller or appears in logs/exports.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import secrets
from typing import Any, Dict
import unicodedata

from amulet_map_editor.api import config

STATE_ID = "shared_school_mode"
STATE_VERSION = 1
DEFAULT_MODE_NAME = "School mode"
MAX_MODE_NAME_LENGTH = 64
MIN_CREDENTIAL_LENGTH = 4
MAX_CREDENTIAL_LENGTH = 128


@dataclass
class SchoolModeState:
    version: int = STATE_VERSION
    mode_name: str = DEFAULT_MODE_NAME
    enabled: bool = False
    credential_salt: str = ""
    credential_digest: str = ""


def validate_mode_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("School-mode name must be text.")
    value = value.strip()
    if not value:
        raise ValueError("School-mode name cannot be empty.")
    if len(value) > MAX_MODE_NAME_LENGTH:
        raise ValueError(
            f"School-mode name must be {MAX_MODE_NAME_LENGTH} characters or fewer."
        )
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("School-mode name cannot contain control characters.")
    return value


def _validate_credential(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Unlock credential must be text.")
    if not MIN_CREDENTIAL_LENGTH <= len(value) <= MAX_CREDENTIAL_LENGTH:
        raise ValueError(
            "Unlock credential must be between "
            f"{MIN_CREDENTIAL_LENGTH} and {MAX_CREDENTIAL_LENGTH} characters."
        )
    return value


def _digest(credential: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", credential.encode("utf-8"), salt, 120_000
    ).hex()


def load() -> SchoolModeState:
    raw: Dict[str, Any] = config.get(STATE_ID, {})
    if not isinstance(raw, dict):
        raw = {}
    state = SchoolModeState(
        version=raw.get("version", STATE_VERSION),
        mode_name=raw.get("mode_name", DEFAULT_MODE_NAME),
        enabled=raw.get("enabled", False),
        credential_salt=raw.get("credential_salt", ""),
        credential_digest=raw.get("credential_digest", ""),
    )
    try:
        state.mode_name = validate_mode_name(state.mode_name)
    except ValueError:
        state.mode_name = DEFAULT_MODE_NAME
    state.version = STATE_VERSION
    state.enabled = bool(state.enabled)
    if not isinstance(state.credential_salt, str):
        state.credential_salt = ""
    if not isinstance(state.credential_digest, str):
        state.credential_digest = ""
    return state


def _save(state: SchoolModeState) -> SchoolModeState:
    state.mode_name = validate_mode_name(state.mode_name)
    state.version = STATE_VERSION
    state.enabled = bool(state.enabled)
    config.put(STATE_ID, asdict(state))
    return state


def set_mode_name(name: str) -> SchoolModeState:
    state = load()
    state.mode_name = validate_mode_name(name)
    return _save(state)


def set_unlock_credential(credential: str) -> SchoolModeState:
    credential = _validate_credential(credential)
    state = load()
    salt = secrets.token_bytes(16)
    state.credential_salt = salt.hex()
    state.credential_digest = _digest(credential, salt)
    return _save(state)


def has_unlock_credential() -> bool:
    state = load()
    return bool(state.credential_salt and state.credential_digest)


def unlock(credential: str) -> bool:
    """Disable School mode only after verifying the shared local credential."""
    state = load()
    if not has_unlock_credential():
        return False
    try:
        salt = bytes.fromhex(state.credential_salt)
        candidate = _digest(_validate_credential(credential), salt)
    except (ValueError, TypeError):
        return False
    if not hmac.compare_digest(candidate, state.credential_digest):
        return False
    state.enabled = False
    _save(state)
    return True


def enable() -> SchoolModeState:
    """Enable the mode; callers must have configured an unlock credential."""
    state = load()
    if not has_unlock_credential():
        raise ValueError("Configure an unlock credential before enabling School mode.")
    state.enabled = True
    return _save(state)


def reset_name() -> SchoolModeState:
    state = load()
    state.mode_name = DEFAULT_MODE_NAME
    return _save(state)


def presentation_preferences(preferences: Any) -> Any:
    """Return a copy forced to the English-only School-mode presentation."""
    state = load()
    if not state.enabled:
        return preferences
    values = dict(preferences.__dict__)
    values.update(
        language_mode="english",
        funny_level_english=1,
        funny_level_cantonese=1,
        show_dialog_emojis=False,
    )
    return type(preferences)(**values).normalised()
