"""Sidecar methods for appearance presets, per-surface toy locks, and the
built-in TOTP authenticator.

Every handler here calls straight into the already-tested portable core --
:mod:`amulet_map_editor.api.appearance_presets`,
:mod:`amulet_map_editor.api.item_locks`, :mod:`amulet_map_editor.api.authenticator`
-- exactly like the rest of the sidecar's method table. Nothing here reimplements
persistence, hashing, or TOTP arithmetic.

Secret handling stays deliberately narrow, per the module's own docstrings:

* A lock's password/TOTP secret and an authenticator entry's TOTP secret cross
  the pipe **once**, at creation/registration time, because the vault has to
  receive it from somewhere. After that, nothing here ever reads or returns a
  stored secret's value -- only ``True``/``False`` for an unlock attempt, and
  a live *code* for the authenticator (which is the feature, not the secret).
* ``locks.list`` and ``auth.list_entries`` return metadata only. The plain
  ``auth.export`` mirrors :func:`authenticator.export_entries`, which already
  omits secrets and says so in each row. The secrets-included export exists
  only as :func:`authenticator.export_entries_with_secrets` and is
  deliberately left off this table -- the renderer's super-confirmation gate
  guards that path, and gating a network method after the fact is not a gate.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from amulet_map_editor.api import appearance_presets as PRESETS
from amulet_map_editor.api import authenticator as AUTH
from amulet_map_editor.api import item_locks as LOCKS
from amulet_map_editor.api.forge_accounts import CredentialStoreUnavailable
from amulet_map_editor.api.sidecar.protocol import ERR_INVALID_PARAMS, ProtocolError

MethodHandler = Any


def _require_str(params: Dict[str, Any], name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(ERR_INVALID_PARAMS, f"'{name}' must be a non-empty string")
    return value


# ---------------------------------------------------------------------------
# appearance presets
# ---------------------------------------------------------------------------


def _appearance_presets_list(_params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        presets = PRESETS.load_presets()
    except PRESETS.AppearancePresetValidationError as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return {
        "presets": [preset.to_dict() for preset in presets],
        "shipped": asdict(PRESETS.SHIPPED_APPEARANCE),
    }


def _appearance_presets_save(params: Dict[str, Any]) -> Dict[str, Any]:
    name = _require_str(params, "name")
    values = params.get("values")
    try:
        appearance_values = (
            None if values is None else PRESETS.AppearanceValues.from_dict(values)
        )
        preset = PRESETS.save_preset(
            name, appearance_values, replace=bool(params.get("replace", False))
        )
    except PRESETS.AppearancePresetValidationError as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return {"preset": preset.to_dict()}


def _appearance_presets_delete(params: Dict[str, Any]) -> Dict[str, Any]:
    name = _require_str(params, "name")
    return {"deleted": PRESETS.delete_preset(name)}


def _appearance_presets_apply(params: Dict[str, Any]) -> Dict[str, Any]:
    name = _require_str(params, "name")
    try:
        prefs = PRESETS.apply_preset(name)
    except KeyError:
        raise ProtocolError(ERR_INVALID_PARAMS, f"No preset named {name!r}.")
    except PRESETS.AppearancePresetValidationError as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return {"preferences": asdict(prefs)}


def _appearance_reset_property(params: Dict[str, Any]) -> Dict[str, Any]:
    property_name = _require_str(params, "property")
    try:
        prefs = PRESETS.reset_property(property_name)
    except KeyError:
        raise ProtocolError(ERR_INVALID_PARAMS, f"'{property_name}' is not resettable.")
    return {"preferences": asdict(prefs)}


def _appearance_reset_all(_params: Dict[str, Any]) -> Dict[str, Any]:
    return {"preferences": asdict(PRESETS.reset_appearance())}


def _appearance_export(params: Dict[str, Any]) -> Dict[str, Any]:
    name = _require_str(params, "name")
    for preset in PRESETS.load_presets():
        if preset.name.casefold() == name.strip().casefold():
            return {"export": PRESETS.export_preset(preset)}
    raise ProtocolError(ERR_INVALID_PARAMS, f"No preset named {name!r}.")


def _appearance_import(params: Dict[str, Any]) -> Dict[str, Any]:
    payload = _require_str(params, "payload")
    try:
        preset = PRESETS.import_preset(payload, replace=bool(params.get("replace", False)))
    except PRESETS.AppearancePresetValidationError as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return {"preset": preset.to_dict()}


# ---------------------------------------------------------------------------
# item locks -- toy, per-surface, own credential each
# ---------------------------------------------------------------------------


def _lock_dict(lock: "LOCKS.Lock") -> Dict[str, Any]:
    return {
        "lock_id": lock.lock_id,
        "scope": lock.scope,
        "target_id": lock.target_id,
        "label": lock.label,
        "method": lock.method,
        "created_at": lock.created_at,
        "unlock_duration": lock.unlock_duration,
        "locked_on_launch": lock.locked_on_launch,
        "failed_attempts": lock.failed_attempts,
        "last_attempt_at": lock.last_attempt_at,
        "is_unlocked": LOCKS.is_unlocked(lock.lock_id),
    }


def _locks_list(_params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "locks": [_lock_dict(lock) for lock in LOCKS.list_locks()],
        "recovery_hint": LOCKS.profile_directory_hint(),
    }


def _locks_create(params: Dict[str, Any]) -> Dict[str, Any]:
    scope = _require_str(params, "scope")
    target_id = _require_str(params, "target_id")
    label = params.get("label", "") or ""
    method = _require_str(params, "method")
    try:
        lock = LOCKS.create_lock(
            scope,
            target_id,
            label,
            method,
            password=params.get("password"),
            totp_secret=params.get("totp_secret"),
            unlock_duration=params.get("unlock_duration", "surface"),
            locked_on_launch=bool(params.get("locked_on_launch", True)),
        )
    except CredentialStoreUnavailable as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    except LOCKS.LockError as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return {"lock": _lock_dict(lock)}


def _locks_attempt_unlock(params: Dict[str, Any]) -> Dict[str, Any]:
    lock_id = _require_str(params, "lock_id")
    answer = params.get("answer", "") or ""
    try:
        ok = LOCKS.attempt_unlock(lock_id, answer)
    except CredentialStoreUnavailable as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return {"unlocked": ok}


def _locks_relock(params: Dict[str, Any]) -> Dict[str, Any]:
    lock_id = _require_str(params, "lock_id")
    LOCKS.relock(lock_id)
    return {"relocked": True}


def _locks_remove(params: Dict[str, Any]) -> Dict[str, Any]:
    lock_id = _require_str(params, "lock_id")
    LOCKS.remove_lock(lock_id)
    return {"removed": True}


def _locks_change_credential(params: Dict[str, Any]) -> Dict[str, Any]:
    lock_id = _require_str(params, "lock_id")
    try:
        lock = LOCKS.change_credential(
            lock_id,
            password=params.get("password"),
            totp_secret=params.get("totp_secret"),
        )
    except CredentialStoreUnavailable as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    except LOCKS.LockError as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return {"lock": _lock_dict(lock)}


def _locks_generate_totp_secret(_params: Dict[str, Any]) -> Dict[str, Any]:
    return {"secret": LOCKS.generate_totp_secret()}


# ---------------------------------------------------------------------------
# built-in authenticator
# ---------------------------------------------------------------------------


def _entry_dict(entry: "AUTH.Entry") -> Dict[str, Any]:
    return {
        "id": entry.id,
        "issuer": entry.issuer,
        "account": entry.account,
        "algorithm": entry.algorithm,
        "digits": entry.digits,
        "period": entry.period,
        "added_at": entry.added_at,
        "label": entry.label(),
    }


def _auth_list_entries(_params: Dict[str, Any]) -> Dict[str, Any]:
    return {"entries": [_entry_dict(entry) for entry in AUTH.list_entries()]}


def _auth_generate_secret(params: Dict[str, Any]) -> Dict[str, Any]:
    length = params.get("length", 20)
    if not isinstance(length, int) or isinstance(length, bool):
        raise ProtocolError(ERR_INVALID_PARAMS, "'length' must be an integer")
    return {"secret": AUTH.generate_secret(length)}


def _auth_build_uri(params: Dict[str, Any]) -> Dict[str, Any]:
    issuer = params.get("issuer", "") or ""
    account = _require_str(params, "account")
    secret = _require_str(params, "secret")
    try:
        uri = AUTH.build_otpauth_uri(
            issuer=issuer,
            account=account,
            secret=secret,
            algorithm=params.get("algorithm", AUTH.DEFAULT_ALGORITHM),
            digits=int(params.get("digits", AUTH.DEFAULT_DIGITS)),
            period=int(params.get("period", AUTH.DEFAULT_PERIOD)),
        )
    except AUTH.AuthenticatorError as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return {"uri": uri, "grouped_secret": AUTH.group_base32(secret)}


def _auth_add_entry(params: Dict[str, Any]) -> Dict[str, Any]:
    account = _require_str(params, "account")
    secret = _require_str(params, "secret")
    issuer = params.get("issuer", "") or ""
    try:
        entry = AUTH.add_entry(
            issuer=issuer,
            account=account,
            secret=secret,
            algorithm=params.get("algorithm", AUTH.DEFAULT_ALGORITHM),
            digits=int(params.get("digits", AUTH.DEFAULT_DIGITS)),
            period=int(params.get("period", AUTH.DEFAULT_PERIOD)),
        )
    except CredentialStoreUnavailable as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    except AUTH.AuthenticatorError as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return {"entry": _entry_dict(entry)}


def _auth_rename_entry(params: Dict[str, Any]) -> Dict[str, Any]:
    entry_id = _require_str(params, "entry_id")
    issuer = params.get("issuer", "") or ""
    account = params.get("account", "") or ""
    try:
        AUTH.rename_entry(entry_id, issuer=issuer, account=account)
    except AUTH.AuthenticatorError as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return {"renamed": True}


def _auth_delete_entry(params: Dict[str, Any]) -> Dict[str, Any]:
    entry_id = _require_str(params, "entry_id")
    AUTH.delete_entry(entry_id)
    return {"deleted": True}


def _find_entry(entry_id: str) -> "AUTH.Entry":
    for entry in AUTH.list_entries():
        if entry.id == entry_id:
            return entry
    raise ProtocolError(ERR_INVALID_PARAMS, f"No authenticator entry with id {entry_id!r}.")


def _auth_current_code(params: Dict[str, Any]) -> Dict[str, Any]:
    entry = _find_entry(_require_str(params, "entry_id"))
    try:
        code = AUTH.current_code(entry)
    except (AUTH.AuthenticatorError, CredentialStoreUnavailable) as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return {
        "code": code,
        "next_code": AUTH.next_code(entry),
        "period_remaining": AUTH.period_remaining(entry.period),
        "period": entry.period,
    }


def _auth_export(_params: Dict[str, Any]) -> Dict[str, Any]:
    """Metadata-only export. Every row states that its secret was omitted."""
    return {"entries": AUTH.export_entries()}


def _auth_clock_warning(params: Dict[str, Any]) -> Dict[str, Any]:
    offset = params.get("assumed_offset_seconds", 0.0)
    if not isinstance(offset, (int, float)) or isinstance(offset, bool):
        raise ProtocolError(
            ERR_INVALID_PARAMS, "'assumed_offset_seconds' must be a number"
        )
    return {"warning": AUTH.clock_warning(assumed_offset_seconds=float(offset))}


SECURITY_METHODS: Dict[str, MethodHandler] = {
    "appearance.presets.list": _appearance_presets_list,
    "appearance.presets.save": _appearance_presets_save,
    "appearance.presets.delete": _appearance_presets_delete,
    "appearance.presets.apply": _appearance_presets_apply,
    "appearance.presets.export": _appearance_export,
    "appearance.presets.import": _appearance_import,
    "appearance.reset_property": _appearance_reset_property,
    "appearance.reset_all": _appearance_reset_all,
    "locks.list": _locks_list,
    "locks.create": _locks_create,
    "locks.attempt_unlock": _locks_attempt_unlock,
    "locks.relock": _locks_relock,
    "locks.remove": _locks_remove,
    "locks.change_credential": _locks_change_credential,
    "locks.generate_totp_secret": _locks_generate_totp_secret,
    "auth.list_entries": _auth_list_entries,
    "auth.generate_secret": _auth_generate_secret,
    "auth.build_uri": _auth_build_uri,
    "auth.add_entry": _auth_add_entry,
    "auth.rename_entry": _auth_rename_entry,
    "auth.delete_entry": _auth_delete_entry,
    "auth.current_code": _auth_current_code,
    "auth.export": _auth_export,
    "auth.clock_warning": _auth_clock_warning,
}
