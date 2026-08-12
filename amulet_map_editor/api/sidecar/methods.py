"""The sidecar's real methods, over the core's real modules.

Every entry in :data:`METHODS` calls straight into the same portable core
module a wx surface would call -- :mod:`amulet_map_editor.api.preferences`,
:mod:`amulet_map_editor.api.lang`, :mod:`amulet_map_editor.api.converter`.
Nothing here is a stub: a method only exists in this table because its
implementation exists and is already exercised by the wx application today.

None of these modules touch a secret. The authenticator and the forge/OAuth
account store both live behind the OS credential vault and are deliberately
left off this table until a lane gives them their own bounded, tested
methods -- the sidecar must never become the first place a secret is
serialized to a pipe.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable, Dict

from amulet_map_editor.api import lang as LANG
from amulet_map_editor.api import preferences as PREFERENCES
from amulet_map_editor.api.converter import registry as CONVERTER_REGISTRY
from amulet_map_editor.api.sidecar.protocol import ERR_INVALID_PARAMS, ProtocolError
from amulet_map_editor.api.sidecar.world_methods import WORLD_METHODS

MethodHandler = Callable[[Dict[str, Any]], Any]


def _preferences_read(_params: Dict[str, Any]) -> Dict[str, Any]:
    return asdict(PREFERENCES.load())


#: Only fields a caller may ever set through the sidecar. Deliberately a
#: fixed allowlist rather than "every field on the dataclass", so a new
#: preference field is opt-in to remote mutation rather than automatically
#: exposed the day it is added.
_WRITABLE_PREFERENCE_FIELDS = frozenset(
    {
        "display_name",
        "language_mode",
        "funny_level_english",
        "funny_level_cantonese",
        "show_dialog_emojis",
        "theme",
        "density",
        "accent",
        "ui_font",
        "ui_scale",
        "external_editor_path",
        "auto_stage_updates",
    }
)


def _preferences_write(params: Dict[str, Any]) -> Dict[str, Any]:
    unknown = set(params) - _WRITABLE_PREFERENCE_FIELDS
    if unknown:
        raise ProtocolError(
            ERR_INVALID_PARAMS,
            f"Unknown or non-writable preference field(s): {sorted(unknown)}",
        )
    try:
        updated = PREFERENCES.update(**params)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return asdict(updated)


def _language_get(_params: Dict[str, Any]) -> Dict[str, Any]:
    return {"language_id": LANG.get_language()}


def _language_set(params: Dict[str, Any]) -> Dict[str, Any]:
    language_id = params.get("language_id")
    if not isinstance(language_id, str) or not language_id:
        raise ProtocolError(
            ERR_INVALID_PARAMS, "'language_id' must be a non-empty string"
        )
    LANG.set_language(language_id)
    return {"language_id": LANG.get_language()}


def _language_list(_params: Dict[str, Any]) -> Dict[str, Any]:
    return {"language_ids": list(LANG.get_languages())}


def _converter_formats(_params: Dict[str, Any]) -> Dict[str, Any]:
    adapters = [
        {
            "id": adapter.id,
            "source_format": adapter.source_format,
            "target_format": adapter.target_format,
            "display_name": adapter.display_name,
            "lossy": adapter.lossy,
            "loss_disclosure": adapter.loss_disclosure,
            "metadata_behaviour": adapter.metadata_behaviour,
        }
        for adapter in CONVERTER_REGISTRY.ADAPTERS
    ]
    return {"adapters": adapters}


def _protocol_ping(_params: Dict[str, Any]) -> Dict[str, Any]:
    """A cheap round-trip check the host can use to prove the sidecar is alive."""
    return {"ok": True}


#: method name -> handler. The dispatcher (see :mod:`server`) looks a method
#: up here and nowhere else, so an unregistered method name is always a
#: structured "unknown_method" error rather than an ``AttributeError``.
METHODS: Dict[str, MethodHandler] = {
    "protocol.ping": _protocol_ping,
    "preferences.read": _preferences_read,
    "preferences.write": _preferences_write,
    "language.get": _language_get,
    "language.set": _language_set,
    "language.list": _language_list,
    "converter.formats": _converter_formats,
    **WORLD_METHODS,
}
