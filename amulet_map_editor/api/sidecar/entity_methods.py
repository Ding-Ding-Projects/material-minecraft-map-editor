"""Sidecar methods for the Entities and Data ribbon tabs.

Two families of method live here, matching the two ribbon tabs this module
owns:

* **Entities** -- ``entities.list`` (read-only: every entity whose position
  falls inside a selection box) and ``entities.remove`` (destructive:
  removes every entity in a selection matching a namespace/base-name
  filter). Both walk the real chunk entity lists amulet-core already loads
  (``chunk.entities``, the same list the wx application's own entity plugins
  read and replace) rather than reimplementing entity storage.
* **Data** -- ``data.level_read``/``data.level_write`` and
  ``data.game_rules_read``/``data.game_rules_write`` for the world's
  ``level.dat`` (``world.level_wrapper.root_tag``, the exact NBT object the
  format wrapper serializes on ``world.save``). Reads never require
  ``confirm``; writes always do, and a write only ever mutates the in-memory
  NBT tag -- it reaches disk only on a subsequent ``world.save``, exactly
  the same "nothing writes until world.save" contract
  :mod:`amulet_map_editor.api.sidecar.edit_methods` documents for block
  edits.

Every method reuses the shared handle/dimension/confirm/selection helpers
from :mod:`amulet_map_editor.api.sidecar.edit_methods` so this module cannot
disagree with the write path about what a ready handle, a known dimension or
a confirmed write looks like.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from amulet_map_editor.api.sidecar.edit_methods import (
    _get_ready_handle,
    _require_confirm,
    _require_dimension,
    _require_edit_backend,
    _require_selection_box,
)
from amulet_map_editor.api.sidecar.protocol import ERR_INVALID_PARAMS, ProtocolError

try:  # pragma: no cover - exercised via the "not installed" degrade test
    import amulet_nbt as _amulet_nbt
    from amulet.api.chunk import Chunk as _Chunk
    from amulet.api.entity import Entity as _Entity

    _AMULET_NBT_IMPORT_ERROR: Optional[str] = None
except Exception as exc:  # noqa: BLE001 - any import-time failure degrades
    _amulet_nbt = None  # type: ignore[assignment]
    _Chunk = None  # type: ignore[assignment]
    _Entity = None  # type: ignore[assignment]
    _AMULET_NBT_IMPORT_ERROR = str(exc)

#: Structured error codes specific to this module.
ERR_GAME_RULE_UNKNOWN = "game_rule_unknown"

#: Only fields this module will write into ``Data`` in ``level.dat``.
#: Deliberately a fixed allowlist -- exactly like ``methods.py``'s own
#: ``_WRITABLE_PREFERENCE_FIELDS`` -- so a new NBT key an older Minecraft
#: version relies on is opt-in to remote mutation, never automatically
#: exposed the day someone notices it in a save file.
_WRITABLE_LEVEL_FIELDS = frozenset(
    {"level_name", "difficulty", "hardcore", "raining", "thundering"}
)


# --------------------------------------------------------------- entities


def _entity_dict(entity) -> Dict[str, Any]:
    x, y, z = entity.location
    return {
        "namespace": entity.namespace,
        "base_name": entity.base_name,
        "x": x,
        "y": y,
        "z": z,
    }


def _chunk_range(box) -> "tuple[int, int, int, int]":
    min_x, _min_y, min_z = box.min
    max_x, _max_y, max_z = box.max
    cx_min, cx_max = min_x // 16, (max_x - 1) // 16
    cz_min, cz_max = min_z // 16, (max_z - 1) // 16
    return cx_min, cx_max, cz_min, cz_max


def _entities_list(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_edit_backend()
    handle = _get_ready_handle(params)
    dimension = _require_dimension(params, handle)
    box = _require_selection_box(params)

    world = handle.world
    min_x, min_y, min_z = box.min
    max_x, max_y, max_z = box.max
    cx_min, cx_max, cz_min, cz_max = _chunk_range(box)

    entities: List[Dict[str, Any]] = []
    for cx in range(cx_min, cx_max + 1):
        for cz in range(cz_min, cz_max + 1):
            try:
                chunk = world.get_chunk(cx, cz, dimension)
            except (
                Exception
            ):  # noqa: BLE001 - a missing/unloadable chunk has no entities
                continue
            for entity in chunk.entities:
                x, y, z = entity.location
                if min_x <= x < max_x and min_y <= y < max_y and min_z <= z < max_z:
                    entities.append(_entity_dict(entity))

    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "entities": entities,
        "count": len(entities),
    }


def _entities_remove(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_edit_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "entities.remove")
    dimension = _require_dimension(params, handle)
    box = _require_selection_box(params)

    namespace = params.get("namespace")
    base_name = params.get("base_name")
    if namespace is not None and not isinstance(namespace, str):
        raise ProtocolError(ERR_INVALID_PARAMS, "'namespace' must be a string")
    if base_name is not None and not isinstance(base_name, str):
        raise ProtocolError(ERR_INVALID_PARAMS, "'base_name' must be a string")
    if not namespace and not base_name:
        raise ProtocolError(
            ERR_INVALID_PARAMS,
            "provide 'namespace' and/or 'base_name' to filter which entities "
            "to remove -- entities.remove never removes an unfiltered selection",
        )

    world = handle.world
    min_x, min_y, min_z = box.min
    max_x, max_y, max_z = box.max
    cx_min, cx_max, cz_min, cz_max = _chunk_range(box)

    removed = 0
    try:
        for cx in range(cx_min, cx_max + 1):
            for cz in range(cz_min, cz_max + 1):
                try:
                    chunk = world.get_chunk(cx, cz, dimension)
                except (
                    Exception
                ):  # noqa: BLE001 - nothing to remove from a missing chunk
                    continue
                kept = []
                changed = False
                for entity in chunk.entities:
                    x, y, z = entity.location
                    in_box = (
                        min_x <= x < max_x and min_y <= y < max_y and min_z <= z < max_z
                    )
                    matches = (
                        in_box
                        and (not namespace or entity.namespace == namespace)
                        and (not base_name or entity.base_name == base_name)
                    )
                    if matches:
                        removed += 1
                        changed = True
                        continue
                    kept.append(entity)
                if changed:
                    chunk.entities = kept
                    chunk.changed = True
    except Exception:
        world.restore_last_undo_point()
        raise

    if removed:
        world.create_undo_point()

    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "removed": removed,
    }


def _entities_place(params: Dict[str, Any]) -> Dict[str, Any]:
    """Place one entity at an exact world position.

    Wires the ribbon's "Place" command (Entities tab). The target chunk is
    created if it does not already exist -- placing an entity in an empty
    chunk of air is a legitimate thing to do, the same way ``world.fill``
    creates missing chunks under its selection.
    """
    _require_edit_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "entities.place")
    dimension = _require_dimension(params, handle)

    position = params.get("position")
    if (
        not isinstance(position, (list, tuple))
        or len(position) != 3
        or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in position
        )
    ):
        raise ProtocolError(
            ERR_INVALID_PARAMS, "'position' must be a [x, y, z] array of numbers"
        )
    x, y, z = (float(v) for v in position)

    namespace = params.get("namespace")
    base_name = params.get("base_name")
    if not isinstance(namespace, str) or not namespace:
        raise ProtocolError(
            ERR_INVALID_PARAMS, "'namespace' must be a non-empty string"
        )
    if not isinstance(base_name, str) or not base_name:
        raise ProtocolError(
            ERR_INVALID_PARAMS, "'base_name' must be a non-empty string"
        )

    world = handle.world
    cx, cz = int(x) // 16, int(z) // 16
    try:
        chunk = world.get_chunk(cx, cz, dimension)
    except Exception:  # noqa: BLE001 - no such chunk yet; create one to hold the entity
        chunk = _Chunk(cx, cz)
        world.put_chunk(chunk, dimension)
        chunk = world.get_chunk(cx, cz, dimension)

    entity = _Entity(namespace, base_name, x, y, z, _amulet_nbt.NamedTag())
    chunk.entities = list(chunk.entities) + [entity]
    chunk.changed = True
    world.create_undo_point()

    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "placed": _entity_dict(entity),
    }


# -------------------------------------------------------------------- data


def _require_nbt_backend() -> None:
    if _amulet_nbt is None:
        raise ProtocolError(
            "edit_backend_unavailable",
            "The NBT library (amulet-nbt) is not installed in this "
            f"sidecar's interpreter. Import failure: {_AMULET_NBT_IMPORT_ERROR}",
        )


def _level_data_tag(handle):
    root = handle.world.level_wrapper.root_tag
    data = root.tag.get("Data")
    if data is None:
        raise ProtocolError(
            "level_data_missing",
            "This world's level.dat has no 'Data' compound tag",
        )
    return data


def _data_level_read(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_edit_backend()
    _require_nbt_backend()
    handle = _get_ready_handle(params)
    data = _level_data_tag(handle)

    def _string(key: str) -> Optional[str]:
        tag = data.get(key)
        return tag.py_str if tag is not None else None

    def _number(key: str) -> Optional[float]:
        tag = data.get(key)
        return tag.py_data if tag is not None else None

    return {
        "world_id": handle.world_id,
        "level_name": _string("LevelName"),
        "data_version": _number("DataVersion"),
        "difficulty": _number("Difficulty"),
        "hardcore": (
            bool(_number("hardcore")) if data.get("hardcore") is not None else None
        ),
        "raining": (
            bool(_number("raining")) if data.get("raining") is not None else None
        ),
        "thundering": (
            bool(_number("thundering")) if data.get("thundering") is not None else None
        ),
        "day_time": _number("DayTime"),
    }


def _data_level_write(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_edit_backend()
    _require_nbt_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "data.level_write")
    data = _level_data_tag(handle)

    fields = params.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise ProtocolError(
            ERR_INVALID_PARAMS,
            "'fields' must be a non-empty object of level.dat fields to set",
        )
    unknown = set(fields) - _WRITABLE_LEVEL_FIELDS
    if unknown:
        raise ProtocolError(
            ERR_INVALID_PARAMS,
            f"Unknown or non-writable level.dat field(s): {sorted(unknown)}",
        )

    updated = []
    if "level_name" in fields:
        value = fields["level_name"]
        if not isinstance(value, str) or not value:
            raise ProtocolError(
                ERR_INVALID_PARAMS, "'level_name' must be a non-empty string"
            )
        data["LevelName"] = _amulet_nbt.StringTag(value)
        updated.append("level_name")
    if "difficulty" in fields:
        value = fields["difficulty"]
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not (0 <= value <= 3)
        ):
            raise ProtocolError(
                ERR_INVALID_PARAMS, "'difficulty' must be an integer 0-3"
            )
        data["Difficulty"] = _amulet_nbt.ByteTag(value)
        updated.append("difficulty")
    for bool_field, nbt_key in (
        ("hardcore", "hardcore"),
        ("raining", "raining"),
        ("thundering", "thundering"),
    ):
        if bool_field in fields:
            value = fields[bool_field]
            if not isinstance(value, bool):
                raise ProtocolError(
                    ERR_INVALID_PARAMS, f"'{bool_field}' must be a boolean"
                )
            data[nbt_key] = _amulet_nbt.ByteTag(1 if value else 0)
            updated.append(bool_field)

    return {"world_id": handle.world_id, "updated": updated}


def _data_game_rules_read(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_edit_backend()
    _require_nbt_backend()
    handle = _get_ready_handle(params)
    data = _level_data_tag(handle)

    game_rules = data.get("GameRules")
    rules = {}
    if game_rules is not None:
        for key in game_rules.keys():
            rules[key] = game_rules[key].py_str
    return {"world_id": handle.world_id, "game_rules": rules}


def _data_game_rules_write(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_edit_backend()
    _require_nbt_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "data.game_rules_write")
    data = _level_data_tag(handle)

    rules = params.get("rules")
    if not isinstance(rules, dict) or not rules:
        raise ProtocolError(
            ERR_INVALID_PARAMS,
            "'rules' must be a non-empty object of game rule name -> string value",
        )
    for key, value in rules.items():
        if not isinstance(key, str) or not key:
            raise ProtocolError(
                ERR_INVALID_PARAMS, "every game rule name must be a non-empty string"
            )
        if not isinstance(value, str):
            raise ProtocolError(
                ERR_INVALID_PARAMS,
                f"game rule {key!r} must be a string value ('true'/'false' or a number as text)",
            )

    game_rules = data.get("GameRules")
    if game_rules is None:
        game_rules = _amulet_nbt.CompoundTag()
        data["GameRules"] = game_rules
    for key, value in rules.items():
        game_rules[key] = _amulet_nbt.StringTag(value)

    return {"world_id": handle.world_id, "updated": sorted(rules)}


#: Method name -> handler, merged into the sidecar's dispatch table by
#: :mod:`amulet_map_editor.api.sidecar.methods`.
ENTITY_METHODS: Dict[str, Any] = {
    "entities.list": _entities_list,
    "entities.remove": _entities_remove,
    "entities.place": _entities_place,
    "data.level_read": _data_level_read,
    "data.level_write": _data_level_write,
    "data.game_rules_read": _data_game_rules_read,
    "data.game_rules_write": _data_game_rules_write,
}
