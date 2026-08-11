"""Live binders for the Amulet Studio data, container, and worldgen surfaces.

:mod:`amulet_map_editor.api.studio.live` owns the bridge between a declarative
:class:`~amulet_map_editor.api.studio.spec.Spec` and the world that is open.
This module registers the binders for the family of surfaces that answer
questions about a world's *stored* side -- its scoreboard, its map items, its
players, the signs and command blocks inside it, the containers, the biomes,
the ores, the seed-derived grids, and the boundaries the world records.

Every binder here obeys the same three rules:

* **Nothing is invented.**  A value appears because it was read from the open
  world, and a surface with nothing to read says so and names the reason --
  which file was looked for, which platform does not store it, which chunk
  could not be read.  A plausible number in place of an absent one is the one
  thing this module must never produce.
* **A read never raises.**  A world can be half-written, from a version this
  build only partly understands, or simply missing the field being asked for.
  Every read is guarded and turns into an empty state rather than an exception,
  because a surface that fails to open tells the user less than a surface that
  opens and says what it could not find.
* **A binder rewrites records, not chrome.**  Titles, widths, footer actions,
  and the surface's own prose belong to the spec.  Sections that are pure
  controls -- a resolution picker, an overlay checkbox -- are carried through
  from the shipped description rather than rebuilt.

Nothing here imports wx, so the whole module can be imported, exercised, and
asserted on without a display.  amulet-core and numpy are imported inside the
functions that need them, so a build step or a test that only reads the
contract never pays for them.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from amulet_map_editor.api.studio.context import WorldContext
from amulet_map_editor.api.studio.live import (
    closed,
    empty_section,
    format_bytes,
    format_int,
    register,
)
from amulet_map_editor.api.studio.spec import Field, Row, Section, Spec, sec

log = logging.getLogger(__name__)

#: The most chunks any one of these surfaces reads in a single pass.  A world
#: can hold hundreds of thousands, and a surface that tried to read them all
#: would hang the window; the count actually read is always reported alongside
#: the total, so a partial answer is never presented as a complete one.
CHUNK_SCAN_LIMIT = 256

#: The most records listed individually before the tail is summarised.
ROW_LIMIT = 120

#: How far out from the centre the slime-chunk grid is computed, in chunks.
SLIME_RADIUS = 12

#: The most slime chunks listed, nearest first.
SLIME_ROW_LIMIT = 24

#: The block-entity base names that carry sign text, across every version
#: Amulet's universal palette normalises to.
SIGN_NAMES = ("sign", "hanging_sign", "wall_sign", "standing_sign")

#: The 1.12-era per-structure files.  From 1.13 the same information moved into
#: each chunk's own ``Structures`` tag, which is read separately.
LEGACY_STRUCTURE_FILES = (
    "Village.dat",
    "Fortress.dat",
    "Mineshaft.dat",
    "Stronghold.dat",
    "Temple.dat",
    "Monument.dat",
    "Mansion.dat",
    "EndCity.dat",
    "Igloo.dat",
    "Shipwreck.dat",
    "Buried_Treasure.dat",
    "Ocean_Ruin.dat",
)

#: What a surface says when the world's platform keeps a record somewhere this
#: window cannot read.  The platform is named so the message is a fact about
#: the open world rather than a shrug.
NOT_ON_PLATFORM = (
    "{what} is not stored as a file this window can read on {platform} worlds, "
    "so there is nothing here to show."
)


# ----------------------------------------------------------------------
# reading nbt without trusting any of it
# ----------------------------------------------------------------------


def _py(tag: Any) -> Any:
    """Return the plain Python value behind an amulet-nbt tag."""
    if tag is None:
        return None
    value = getattr(tag, "py_data", None)
    return tag if value is None else value


def _get(compound: Any, *names: str) -> Any:
    """Return the first of ``names`` present in ``compound``, else ``None``."""
    if compound is None:
        return None
    for name in names:
        try:
            if name in compound:
                return compound[name]
        except Exception:  # noqa: BLE001 - an unusual tag is not fatal
            return None
    return None


def _compound(parent: Any, *names: str) -> Any:
    """Return a nested compound tag, or ``None`` when it is absent."""
    tag = _get(parent, *names)
    return tag if hasattr(tag, "items") else None


def _sequence(parent: Any, *names: str) -> Tuple[Any, ...]:
    """Return a list tag's members, or ``()`` when it is absent."""
    tag = _get(parent, *names)
    if tag is None or isinstance(tag, (str, bytes)):
        return ()
    try:
        return tuple(tag)
    except TypeError:
        return ()


def _text(parent: Any, *names: str) -> str:
    """Return a tag as text, or ``""`` when it is absent."""
    value = _py(_get(parent, *names))
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _number(parent: Any, *names: str) -> Optional[float]:
    """Return a tag as a number, or ``None`` when it is absent."""
    value = _py(_get(parent, *names))
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _whole(parent: Any, *names: str) -> Optional[int]:
    """Return a tag as a whole number, or ``None`` when it is absent."""
    value = _number(parent, *names)
    return None if value is None else int(value)


def _flag(parent: Any, *names: str) -> Optional[bool]:
    """Return a tag as a flag, or ``None`` when it is absent."""
    value = _number(parent, *names)
    return None if value is None else bool(value)


def _load_nbt(path: str) -> Any:
    """Return the root compound of an NBT file, or ``None`` when unreadable."""
    if not path or not os.path.isfile(path):
        return None
    try:
        import amulet_nbt

        return amulet_nbt.load(path).compound
    except Exception as error:  # noqa: BLE001 - a corrupt file is reported, not raised
        log.debug("Studio could not read the NBT file %s: %s", path, error)
        return None


def _component_text(node: Any) -> str:
    """Return the readable text of one Minecraft JSON text component."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_component_text(part) for part in node)
    if isinstance(node, dict):
        text = str(node.get("text", ""))
        for child in node.get("extra", ()) or ():
            text += _component_text(child)
        return text
    return ""


def _plain(value: Any) -> str:
    """Return a stored string as the text a player would read on the sign.

    Minecraft has stored sign and custom-name text as raw text, as a quoted
    string, and as a JSON text component, depending on the version.  All three
    are unwrapped here so one surface can list signs from any of them without
    showing the user the markup around the words.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text[0] in "{[" or (text[0] == '"' and text[-1] == '"'):
        try:
            return _component_text(json.loads(text)).strip()
        except (ValueError, TypeError):
            return text
    return text


# ----------------------------------------------------------------------
# shared shapes
# ----------------------------------------------------------------------


def _sections(spec: Spec, *sections: Optional[Section]) -> Spec:
    """Return ``spec`` carrying exactly ``sections``, dropping any that are None."""
    return replace(spec, sections=tuple(item for item in sections if item is not None))


def _kept(spec: Spec, title: str) -> Optional[Section]:
    """Return the shipped section titled ``title``, so controls survive binding."""
    for section in spec.sections:
        if section.title == title:
            return section
    return None


def _note(text: str) -> Section:
    """Return the trailing note a bound surface signs its readings with."""
    return sec("", "note", hint=text)


def _where(ctx: WorldContext) -> str:
    """Return the world the values were read from, as a person would name it."""
    return ctx.path or ctx.name or "the open world"


def _world_file(ctx: WorldContext, *parts: str) -> str:
    """Return a path inside the open world folder, or ``""`` when there is none."""
    if not ctx.path:
        return ""
    return os.path.join(ctx.path, *parts)


def _shown(value: Any) -> str:
    """Return a read value as text, and an absent one as an empty string.

    ``str(value or "")`` is the obvious spelling and it is wrong: a stored
    zero -- a map centred on the origin, a food level of nothing, a score of
    nought -- is a real reading, and rendering it as blank would report the
    world as silent about something it states plainly.
    """
    return "" if value is None else str(value)


def _plural(count: int, singular: str, plural: str = "") -> str:
    """Return ``count`` with the right noun, so a count of one still reads."""
    word = singular if abs(count) == 1 else (plural or f"{singular}s")
    return f"{format_int(count)} {word}"


def _percent(part: int, whole: int) -> str:
    """Return ``part`` of ``whole`` as a percentage, or ``""`` when undefined."""
    if not whole:
        return ""
    return f"{(part / whole) * 100:.1f}%"


def _coords(x: Any, y: Any = None, z: Any = None) -> str:
    """Return a coordinate triple the way the game shows one."""
    parts = [x, y, z] if y is not None else [x, z]
    return ", ".join(str(int(part)) for part in parts if part is not None)


def _java_only(spec: Spec, ctx: WorldContext, what: str) -> Optional[Spec]:
    """Return the honest empty surface when ``what`` is a Java-only record."""
    platform = (ctx.platform or "").lower()
    if platform in ("", "java"):
        return None
    return _sections(
        spec,
        empty_section(
            spec.title,
            NOT_ON_PLATFORM.format(what=what, platform=ctx.platform or "this"),
        ),
    )


# ----------------------------------------------------------------------
# reading chunks
# ----------------------------------------------------------------------


@dataclass
class Scan:
    """What one bounded pass over the world's chunks actually managed to read."""

    scope: str
    limit: int
    available: int = 0
    read: int = 0
    ungenerated: int = 0
    unreadable: int = 0

    @property
    def truncated(self) -> bool:
        """Whether more chunks exist than this pass was allowed to read."""
        return self.available > self.limit

    def note(self, ctx: WorldContext) -> str:
        """Return the sentence naming exactly what this pass covered."""
        parts = [
            f"Read {_plural(self.read, 'chunk')} of "
            f"{_plural(self.available, 'chunk')} in {self.scope}."
        ]
        if self.ungenerated:
            verb = "is" if self.ungenerated == 1 else "are"
            parts.append(f"{format_int(self.ungenerated)} {verb} not generated.")
        if self.unreadable:
            parts.append(f"{format_int(self.unreadable)} could not be read.")
        if self.truncated:
            parts.append(
                f"This window reads {format_int(self.limit)} chunks at a time; "
                "draw a selection to count a smaller region exactly."
            )
        parts.append(f"Read from {_where(ctx)}.")
        return " ".join(parts)


def _scan(ctx: WorldContext, limit: int = CHUNK_SCAN_LIMIT) -> Tuple[Any, Scan]:
    """Return the chunk coordinates to read and the record the read fills in.

    A drawn selection is what the user means when one exists; without one the
    whole open dimension is the scope, bounded by ``limit`` and reported as
    bounded rather than presented as a total.
    """
    if ctx.has_selection:
        coords: Sequence[Tuple[int, int]] = ctx.selection_chunks()
        scope = "the current selection"
    else:
        try:
            coords = tuple(sorted(set(ctx.level.all_chunk_coords(ctx.dimension))))
        except Exception as error:  # noqa: BLE001 - an unreadable region folder
            log.debug("Studio could not list chunks for %s: %s", ctx.dimension, error)
            coords = ()
        scope = ctx.dimension or "the open dimension"
    record = Scan(scope=scope, limit=limit, available=len(coords))
    return tuple(coords)[:limit], record


def _chunks(
    ctx: WorldContext, coords: Sequence[Tuple[int, int]], record: Scan
) -> Iterator[Tuple[int, int, Any]]:
    """Yield every chunk that could be read, counting the ones that could not."""
    for cx, cz in coords:
        try:
            chunk = ctx.level.get_chunk(cx, cz, ctx.dimension)
        except Exception as error:  # noqa: BLE001 - absent and broken both land here
            if type(error).__name__ == "ChunkDoesNotExist":
                record.ungenerated += 1
            else:
                record.unreadable += 1
                log.debug("Studio could not read chunk %s, %s: %s", cx, cz, error)
            continue
        record.read += 1
        yield cx, cz, chunk


def _nothing_read(spec: Spec, ctx: WorldContext, record: Scan, subject: str) -> Section:
    """Return the honest empty block for a pass that found no chunks at all."""
    if not record.available:
        why = (
            f"{record.scope} holds no generated chunks, so there are no "
            f"{subject} to read."
        )
    else:
        why = (
            f"None of the {_plural(record.read + record.ungenerated, 'chunk')} "
            f"read in {record.scope} could be opened, so no {subject} were found."
        )
    return empty_section(spec.title, f"{why} Read from {_where(ctx)}.")


def _block_namer(ctx: WorldContext):
    """Return a function naming a universal block in the world's own version.

    Amulet stores every chunk in a universal palette, so a raw palette entry is
    a name the user has never seen in the game.  Translating it back to the
    version the world is saved in is what makes these surfaces read like the
    world rather than like the editor's internals; a block that will not
    translate keeps its universal name and is reported as untranslatable, which
    is exactly what the block-state audit exists to find.
    """
    translator = None
    try:
        platform, version = ctx.level.level_wrapper.max_world_version
        translator = ctx.level.translation_manager.get_version(platform, version).block
    except Exception as error:  # noqa: BLE001 - a world with no translator is fine
        log.debug("Studio has no block translator for this world: %s", error)

    cache: Dict[Any, Tuple[str, str, bool]] = {}

    def name_of(block: Any) -> Tuple[str, str, bool]:
        """Return ``(name, full state, translated)`` for one palette entry."""
        key = getattr(block, "full_blockstate", None) or str(block)
        cached = cache.get(key)
        if cached is not None:
            return cached
        namespaced = str(getattr(block, "namespaced_name", key))
        result = (namespaced, str(key), False)
        if translator is not None:
            try:
                converted = translator.from_universal(block)[0]
                result = (
                    str(getattr(converted, "namespaced_name", None) or converted),
                    str(getattr(converted, "full_blockstate", None) or converted),
                    True,
                )
            except Exception:  # noqa: BLE001 - a state this version has no name for
                result = (namespaced, str(key), False)
        cache[key] = result
        return result

    return name_of


def _biome_namer(ctx: WorldContext):
    """Return a function naming a universal biome in the world's own version."""
    translator = None
    try:
        platform, version = ctx.level.level_wrapper.max_world_version
        translator = ctx.level.translation_manager.get_version(platform, version).biome
    except Exception as error:  # noqa: BLE001 - a world with no translator is fine
        log.debug("Studio has no biome translator for this world: %s", error)

    def name_of(biome: Any) -> str:
        universal = str(biome)
        if translator is None:
            return universal
        try:
            return str(translator.from_universal(universal))
        except Exception:  # noqa: BLE001 - a biome this version does not have
            return universal

    return name_of


def _block_entities(chunk: Any) -> Iterator[Any]:
    """Yield a chunk's block entities without letting one bad chunk stop the pass."""
    try:
        yield from chunk.block_entities
    except Exception as error:  # noqa: BLE001 - a chunk mid-decode answers this
        log.debug("Studio could not list block entities: %s", error)


def _tags(entity: Any) -> Any:
    """Return the compound holding one entity's own game tags.

    Amulet nests a translated entity's original tags under ``utags``; a value
    that has not been through the translator keeps them at the root.  Both are
    accepted so a surface reads the same whichever route the world took.
    """
    root = getattr(entity, "nbt", None)
    compound = getattr(root, "compound", None)
    if compound is None:
        return None
    inner = _compound(compound, "utags")
    return inner if inner is not None else compound


def _base_name(entity: Any) -> str:
    """Return an entity's base name, without its namespace."""
    return str(getattr(entity, "base_name", "") or "")


# ----------------------------------------------------------------------
# scoreboard
# ----------------------------------------------------------------------


@register("scoreboard")
def _bind_scoreboard(spec: Spec, ctx: WorldContext) -> Spec:
    """List the objectives, teams, and scores this world actually stores."""
    if not ctx.open:
        return closed(spec)
    unsupported = _java_only(spec, ctx, "The scoreboard")
    if unsupported is not None:
        return unsupported

    path = _world_file(ctx, "data", "scoreboard.dat")
    root = _load_nbt(path)
    data = _compound(root, "data") if root is not None else None
    if data is None:
        return _sections(
            spec,
            empty_section(
                "Objectives",
                f"This world has no readable data{os.sep}scoreboard.dat, so it "
                "stores no scoreboard objectives, teams, or scores. A world "
                f"gains one the first time a scoreboard command runs in it. "
                f"Looked in {_where(ctx)}.",
            ),
        )

    objectives = _sequence(data, "Objectives")
    scores = _sequence(data, "PlayerScores")
    teams = _sequence(data, "Teams")

    slots: Dict[str, List[str]] = {}
    display = _compound(data, "DisplaySlots")
    if display is not None:
        try:
            for slot, value in display.items():
                slots.setdefault(str(_py(value)), []).append(str(slot))
        except Exception:  # noqa: BLE001 - a malformed slot block names nothing
            slots = {}

    counts: Dict[str, int] = {}
    for score in scores:
        counts[_text(score, "Objective")] = counts.get(_text(score, "Objective"), 0) + 1

    objective_rows = []
    for objective in objectives:
        name = _text(objective, "Name")
        criteria = _text(objective, "CriteriaName") or "no criteria recorded"
        detail = f"criteria {criteria}"
        shown = slots.get(name)
        if shown:
            detail += " · displayed in " + ", ".join(sorted(shown))
        display_name = _plain(_text(objective, "DisplayName"))
        if display_name and display_name != name:
            detail += f" · shown as {display_name}"
        objective_rows.append(
            Row(name=name, detail=detail, tag=_plural(counts.get(name, 0), "score"))
        )

    objectives_section = (
        sec("Objectives", "list", rows=objective_rows)
        if objective_rows
        else empty_section(
            "Objectives",
            "This world's scoreboard.dat records no objectives.",
        )
    )

    team_rows = []
    for team in teams:
        name = _text(team, "Name")
        members = _sequence(team, "Players")
        colour = _text(team, "TeamColor")
        friendly = _flag(team, "AllowFriendlyFire")
        parts = [_plural(len(members), "member")]
        if colour:
            parts.append(f"colour {colour}")
        if friendly is not None:
            parts.append("friendly fire " + ("on" if friendly else "off"))
        team_rows.append(Row(name=name, detail=" · ".join(parts), tag="team"))
    teams_section = (
        sec("Teams", "list", rows=team_rows)
        if team_rows
        else empty_section("Teams", "This world's scoreboard.dat records no teams.")
    )

    score_rows = [
        Row(
            name=_text(score, "Name"),
            detail=_text(score, "Objective"),
            tag=_shown(_whole(score, "Score")),
        )
        for score in sorted(scores, key=lambda item: -(_whole(item, "Score") or 0))[
            :ROW_LIMIT
        ]
    ]
    scores_section = (
        sec("Scores", "list", rows=score_rows)
        if score_rows
        else empty_section(
            "Scores", "No holder has a score against any objective in this world."
        )
    )

    return _sections(
        spec,
        objectives_section,
        teams_section,
        scores_section,
        _note(
            f"{_plural(len(objectives), 'objective')}, "
            f"{_plural(len(teams), 'team')} and "
            f"{_plural(len(scores), 'score')} read from {path}."
        ),
    )


# ----------------------------------------------------------------------
# map items
# ----------------------------------------------------------------------

#: Java stores a map's dimension as a number in older versions and as a
#: dimension name from 1.16 onwards.  Only the numbers the game documents are
#: named; anything else is shown exactly as the file stores it.
_MAP_DIMENSIONS = {0: "overworld", -1: "the_nether", 1: "the_end"}


@register("mapItems")
def _bind_map_items(spec: Spec, ctx: WorldContext) -> Spec:
    """List the map items this world stores, with their real centres and scales."""
    if not ctx.open:
        return closed(spec)
    unsupported = _java_only(spec, ctx, "Map item data")
    if unsupported is not None:
        return unsupported

    folder = _world_file(ctx, "data")
    names: List[str] = []
    if folder and os.path.isdir(folder):
        names = sorted(
            (
                name
                for name in os.listdir(folder)
                if name.startswith("map_") and name.endswith(".dat")
            ),
            key=lambda name: (len(name), name),
        )
    if not names:
        return _sections(
            spec,
            empty_section(
                "Maps",
                f"This world stores no map_*.dat files in its data folder, so no "
                f"map item has ever been made in it. Looked in "
                f"{folder or _where(ctx)}.",
            ),
        )

    rows: List[Row] = []
    first: Optional[Any] = None
    first_name = ""
    for name in names[:ROW_LIMIT]:
        path = os.path.join(folder, name)
        data = _compound(_load_nbt(path), "data")
        if data is None:
            rows.append(
                Row(
                    name=name[:-4],
                    detail="stored, but its NBT could not be read",
                    tag="unreadable",
                )
            )
            continue
        if first is None:
            first, first_name = data, name[:-4]
        raw_dimension = _get(data, "dimension")
        plain = _py(raw_dimension)
        if isinstance(plain, (int, float)) and not isinstance(plain, bool):
            dimension = _MAP_DIMENSIONS.get(int(plain), str(int(plain)))
        else:
            dimension = str(plain) if plain is not None else "dimension not recorded"
        scale = _whole(data, "scale")
        centre_x = _whole(data, "xCenter")
        centre_z = _whole(data, "zCenter")
        parts = [dimension]
        if scale is not None:
            parts.append(f"scale {scale}")
        if centre_x is not None and centre_z is not None:
            parts.append(f"centre {centre_x}, {centre_z}")
        if _flag(data, "locked"):
            parts.append("locked")
        banners = _sequence(data, "banners")
        if banners:
            parts.append(_plural(len(banners), "banner"))
        try:
            size = format_bytes(os.path.getsize(path))
        except OSError:
            size = "size unknown"
        rows.append(Row(name=name[:-4], detail=" · ".join(parts), tag=size))

    fields: List[Field] = []
    if first is not None:
        colours = _py(_get(first, "colors"))
        painted = 0
        stored = 0
        try:
            stored = len(colours)
            painted = sum(1 for value in colours if value)
        except TypeError:
            stored = 0
        fields = [
            Field(label="Map", value=first_name),
            Field(label="Scale", value=str(_whole(first, "scale") or "")),
            Field(label="Centre x", value=str(_whole(first, "xCenter") or "")),
            Field(label="Centre z", value=str(_whole(first, "zCenter") or "")),
            Field(
                label="Banners tracked",
                value=str(len(_sequence(first, "banners"))),
            ),
            Field(
                label="Painted pixels",
                value=(
                    f"{format_int(painted)} of {format_int(stored)}" if stored else ""
                ),
                placeholder="this map stores no colour data",
            ),
        ]

    counter = _compound(_load_nbt(os.path.join(folder, "idcounts.dat")), "data")
    highest = _whole(counter, "map") if counter is not None else None
    trailing = f"{_plural(len(names), 'map file')} read from {folder}."
    if highest is not None:
        trailing += f" idcounts.dat records the highest map id as {highest}."
    trailing += (
        " The colour bytes stored in each file are the map as the game last "
        "drew it; nothing here is re-rendered from the world."
    )

    return _sections(
        spec,
        sec("Maps", "list", rows=rows),
        (
            sec("Selected map", "fields", fields=fields)
            if fields
            else empty_section(
                "Selected map", "No map file in this world could be read."
            )
        ),
        _note(trailing),
    )


# ----------------------------------------------------------------------
# player data
# ----------------------------------------------------------------------

#: The inventory slot ranges Minecraft uses, and the name a player knows them
#: by.  A slot outside every range is counted under "Other slots" rather than
#: dropped, so the totals shown always add up to what the file contains.
_INVENTORY_RANGES = (
    ("Hotbar", 0, 8, 9),
    ("Main inventory", 9, 35, 27),
    ("Armour", 100, 103, 4),
    ("Off hand", -106, -106, 1),
)


def _player_nbt(ctx: WorldContext, player_id: str) -> Any:
    """Return one player's stored compound, from wherever this world keeps it."""
    if player_id in ("~local_player", "local_player"):
        wrapper = getattr(ctx.level, "level_wrapper", None)
        root = getattr(wrapper, "root_tag", None)
        compound = getattr(root, "compound", None)
        data = _compound(compound, "Data")
        return _compound(data if data is not None else compound, "Player")
    return _load_nbt(_world_file(ctx, "playerdata", f"{player_id}.dat"))


def _inventory_rows(compound: Any) -> List[Row]:
    """Return one row per inventory region, counting the slots actually stored."""
    rows: List[Row] = []
    items = _sequence(compound, "Inventory")
    slots = [_whole(item, "Slot") for item in items]
    accounted = 0
    for label, low, high, capacity in _INVENTORY_RANGES:
        used = sum(1 for slot in slots if slot is not None and low <= slot <= high)
        accounted += used
        rows.append(
            Row(
                name=label,
                detail=f"{capacity} slots · {used} occupied",
                tag=str(used),
            )
        )
    other = len(slots) - accounted
    if other > 0:
        rows.append(
            Row(
                name="Other slots",
                detail="stored at slot numbers outside the ranges above",
                tag=str(other),
            )
        )
    ender = _sequence(compound, "EnderItems")
    rows.append(
        Row(
            name="Ender chest",
            detail=f"27 slots · {len(ender)} occupied",
            tag=str(len(ender)),
        )
    )
    return rows


@register("playerData")
def _bind_player_data(spec: Spec, ctx: WorldContext) -> Spec:
    """List the players this world stores, and open the first one's record."""
    if not ctx.open or ctx.level is None:
        return closed(spec)

    try:
        ids = sorted(ctx.level.all_player_ids())
    except Exception as error:  # noqa: BLE001 - report it rather than showing a list
        return _sections(
            spec,
            empty_section(
                "Players",
                f"This world's player records could not be read: "
                f"{type(error).__name__}: {error}.",
            ),
        )
    if not ids:
        return _sections(
            spec,
            empty_section(
                "Players",
                "This world stores no player records. A single-player world "
                "gains one in level.dat the first time it is played, and a "
                "server world writes one file per player into playerdata. "
                f"Looked in {_where(ctx)}.",
            ),
        )

    rows: List[Row] = []
    records: Dict[str, Any] = {}
    dimensions: Dict[str, str] = {}
    for player_id in ids[:ROW_LIMIT]:
        compound = _player_nbt(ctx, player_id)
        records[player_id] = compound
        parts: List[str] = []
        try:
            player = ctx.level.get_player(player_id)
            dimensions[player_id] = str(player.dimension)
            parts.append(
                "at "
                + ", ".join(f"{value:.1f}" for value in player.location)
                + f" · {player.dimension}"
            )
        except Exception as error:  # noqa: BLE001 - one player, not the list
            log.debug("Studio could not read player %s: %s", player_id, error)
            parts.append("position not readable")
        level_value = _whole(compound, "XpLevel")
        if level_value is not None:
            parts.append(f"level {level_value}")
        health = _number(compound, "Health")
        if health is not None:
            parts.append(f"health {health:g}")
        rows.append(
            Row(
                name=player_id,
                detail=" · ".join(parts),
                tag=(
                    "level.dat"
                    if player_id in ("~local_player", "local_player")
                    else "playerdata"
                ),
            )
        )

    chosen_id = ids[0]
    chosen = records.get(chosen_id)
    position_section: Section
    state_section: Section
    inventory_section: Section
    if chosen is None:
        why = (
            f"The stored record for {chosen_id} could not be read, so its "
            "position, state, and inventory are not shown."
        )
        position_section = empty_section("Position", why)
        state_section = empty_section("State", why)
        inventory_section = empty_section("Inventory", why)
    else:
        position = [_py(part) for part in _sequence(chosen, "Pos")]
        # The stored tag is a number on Java and a name on Bedrock, so the
        # level's own reading of it is preferred: showing a player as being in
        # dimension "0" is technically what the file says and tells the reader
        # nothing.
        dimension = dimensions.get(chosen_id) or _text(chosen, "Dimension")
        position_section = sec(
            "Position",
            "fields",
            fields=[
                Field(
                    label=axis,
                    value=(f"{position[index]:.2f}" if index < len(position) else ""),
                    placeholder="not stored",
                )
                for index, axis in enumerate(("x", "y", "z"))
            ]
            + [Field(label="Dimension", value=dimension, placeholder="not stored")],
        )
        game_mode = _whole(chosen, "playerGameType")
        from amulet_map_editor.api.studio import context as context_module

        mode_name = ""
        if game_mode is not None and 0 <= game_mode < len(context_module.GAME_MODES):
            mode_name = context_module.GAME_MODES[game_mode]
        elif game_mode is not None:
            mode_name = str(game_mode)
        health = _number(chosen, "Health")
        state_section = sec(
            "State",
            "fields",
            fields=[
                Field(
                    label="Health",
                    value="" if health is None else f"{health:g}",
                    placeholder="not stored",
                ),
                Field(
                    label="Food",
                    value=_shown(_whole(chosen, "foodLevel")),
                    placeholder="not stored",
                ),
                Field(
                    label="XP level",
                    value=_shown(_whole(chosen, "XpLevel")),
                    placeholder="not stored",
                ),
                Field(label="Game mode", value=mode_name, placeholder="not stored"),
            ],
        )
        inventory_section = sec("Inventory", "list", rows=_inventory_rows(chosen))

    return _sections(
        spec,
        sec("Players", "list", rows=rows),
        position_section,
        state_section,
        inventory_section,
        _note(
            f"{_plural(len(ids), 'player record')} stored by this world. The "
            f"position, state, and inventory above are {chosen_id}'s, read from "
            f"{_where(ctx)}."
        ),
    )


# ----------------------------------------------------------------------
# signs
# ----------------------------------------------------------------------


def _sign_lines(tags: Any) -> List[str]:
    """Return the readable lines of one sign, whichever shape it is stored in."""
    lines: List[str] = []
    for side in ("front_text", "back_text"):
        side_tags = _compound(tags, side)
        if side_tags is None:
            continue
        for key in ("java_json", "messages", "Text"):
            entries = _sequence(side_tags, key)
            if not entries:
                continue
            # Amulet's universal sign carries five entries where a sign has
            # four lines: the first is the side's own state rather than text.
            # Dropping it keeps line three on line three, which matters more
            # than it sounds -- a shifted list silently retitles every sign in
            # the world by one line.
            if key == "java_json" and len(entries) == 5:
                entries = entries[1:]
            lines.extend(_plain(_py(entry)) for entry in entries)
            break
    if not lines:
        for key in ("Text1", "Text2", "Text3", "Text4"):
            value = _get(tags, key)
            if value is not None:
                lines.append(_plain(_py(value)))
    return lines


@register("signSearch")
def _bind_sign_search(spec: Spec, ctx: WorldContext) -> Spec:
    """List every sign in the scanned chunks, with the text actually on it."""
    if not ctx.open or ctx.level is None:
        return closed(spec)
    search = sec("", "search", hint="Search sign text on every line")
    coords, record = _scan(ctx)
    if not coords:
        return _sections(spec, search, _nothing_read(spec, ctx, record, "signs"))

    found: List[Tuple[Tuple[int, int, int], List[str]]] = []
    for _cx, _cz, chunk in _chunks(ctx, coords, record):
        for entity in _block_entities(chunk):
            if _base_name(entity) not in SIGN_NAMES:
                continue
            found.append(((entity.x, entity.y, entity.z), _sign_lines(_tags(entity))))
    found.sort(key=lambda item: item[0])

    if not found:
        return _sections(
            spec,
            search,
            empty_section(
                "Signs",
                f"No sign was found in the {_plural(record.read, 'chunk')} read "
                f"in {record.scope}.",
            ),
            _note(record.note(ctx)),
        )

    rows = [
        Row(
            name=_coords(*position),
            detail=(
                " / ".join(line for line in lines if line) or "every line is blank"
            ),
            tag="sign",
        )
        for position, lines in found[:ROW_LIMIT]
    ]
    first = found[0][1]
    fields = [
        Field(
            label=f"Line {index + 1}",
            value=first[index] if index < len(first) else "",
            placeholder="blank on this sign",
        )
        for index in range(4)
    ]
    trailing = record.note(ctx)
    if len(found) > len(rows):
        trailing = (
            f"Showing the first {format_int(len(rows))} of "
            f"{format_int(len(found))} signs. " + trailing
        )
    return _sections(
        spec,
        search,
        sec("Signs", "list", rows=rows),
        sec("Selected sign", "fields", fields=fields),
        _kept(spec, "Style"),
        _note(trailing),
    )


# ----------------------------------------------------------------------
# command blocks
# ----------------------------------------------------------------------


@register("commandFinder")
def _bind_command_finder(spec: Spec, ctx: WorldContext) -> Spec:
    """List the command blocks in the scanned chunks and the commands they hold."""
    if not ctx.open or ctx.level is None:
        return closed(spec)
    search = sec("", "search", hint="Search commands and coordinates")
    coords, record = _scan(ctx)
    if not coords:
        return _sections(
            spec, search, _nothing_read(spec, ctx, record, "command blocks")
        )

    name_of = _block_namer(ctx)
    found: List[Dict[str, Any]] = []
    for cx, cz, chunk in _chunks(ctx, coords, record):
        for entity in _block_entities(chunk):
            tags = _tags(entity)
            command = _text(tags, "Command")
            if not command:
                continue
            mode = ""
            try:
                block = chunk.get_block(
                    entity.x - cx * ctx.sub_chunk_size,
                    entity.y,
                    entity.z - cz * ctx.sub_chunk_size,
                )
                properties = getattr(block, "properties", {}) or {}
                mode = str(_py(properties.get("mode", ""))) if properties else ""
                if not mode:
                    mode = name_of(block)[0].split(":")[-1]
            except Exception as error:  # noqa: BLE001 - a block read is optional here
                log.debug("Studio could not read the block under a command: %s", error)
            found.append(
                {
                    "position": (entity.x, entity.y, entity.z),
                    "command": command,
                    "mode": mode,
                    "auto": _flag(tags, "auto"),
                    "name": _plain(_text(tags, "CustomName")),
                    "conditional": _flag(tags, "conditionMet"),
                    "track": _flag(tags, "TrackOutput"),
                }
            )
    found.sort(key=lambda item: item["position"])

    if not found:
        return _sections(
            spec,
            search,
            empty_section(
                "Command blocks",
                "No block entity in the "
                f"{_plural(record.read, 'chunk')} read in {record.scope} stores a "
                "command.",
            ),
            _note(record.note(ctx)),
        )

    rows = []
    for item in found[:ROW_LIMIT]:
        label = _coords(*item["position"])
        if item["mode"]:
            label += f" · {item['mode']}"
        rows.append(
            Row(
                name=label,
                detail=item["command"],
                tag=(
                    "always active"
                    if item["auto"]
                    else ("needs redstone" if item["auto"] is not None else "stored")
                ),
            )
        )
    first = found[0]
    fields = [
        Field(label="Command", value=first["command"]),
        Field(
            label="Custom name",
            value=first["name"],
            placeholder="no custom name stored",
        ),
        Field(label="Type", value=first["mode"], placeholder="block type not readable"),
        Field(
            label="Condition",
            value=(
                ""
                if first["conditional"] is None
                else ("conditional" if first["conditional"] else "unconditional")
            ),
            placeholder="not stored",
        ),
    ]
    trailing = record.note(ctx) + (
        " Amulet does not validate command syntax against a game build; the "
        "text above is exactly what the world stores."
    )
    if len(found) > len(rows):
        trailing = (
            f"Showing the first {format_int(len(rows))} of "
            f"{format_int(len(found))} command blocks. " + trailing
        )
    return _sections(
        spec,
        search,
        sec("Command blocks", "list", rows=rows),
        sec("Selected block", "fields", fields=fields),
        _note(trailing),
    )


# ----------------------------------------------------------------------
# containers
# ----------------------------------------------------------------------


@register("lootAudit")
def _bind_loot_audit(spec: Spec, ctx: WorldContext) -> Spec:
    """List every container in the scanned chunks and what is actually inside it."""
    if not ctx.open or ctx.level is None:
        return closed(spec)
    search = sec("", "search", hint="Search containers, loot tables, and items")
    coords, record = _scan(ctx)
    if not coords:
        return _sections(spec, search, _nothing_read(spec, ctx, record, "containers"))

    found: List[Tuple[Tuple[int, int, int], str, str, str]] = []
    tables = 0
    filled = 0
    for _cx, _cz, chunk in _chunks(ctx, coords, record):
        for entity in _block_entities(chunk):
            tags = _tags(entity)
            table = _text(tags, "LootTable")
            items = _sequence(tags, "Items")
            has_items_tag = _get(tags, "Items") is not None
            if not table and not has_items_tag:
                continue
            if table:
                tables += 1
                detail = f"LootTable: {table}"
                tag = "unrolled"
            elif items:
                filled += 1
                stacks = 0
                for item in items:
                    stacks += int(_whole(item, "Count") or 0)
                detail = f"{_plural(len(items), 'item stack')} · {stacks} items"
                tag = "filled"
            else:
                detail = "Empty"
                tag = "empty"
            found.append(
                (
                    (entity.x, entity.y, entity.z),
                    str(getattr(entity, "namespaced_name", "")),
                    detail,
                    tag,
                )
            )
    found.sort(key=lambda item: item[0])

    if not found:
        return _sections(
            spec,
            search,
            empty_section(
                "Containers",
                f"No container was found in the {_plural(record.read, 'chunk')} "
                f"read in {record.scope}. A block entity counts as a container "
                "here when it stores an item list or a loot table.",
            ),
            _note(record.note(ctx)),
        )

    rows = [
        Row(name=f"{name} at {_coords(*position)}", detail=detail, tag=tag)
        for position, name, detail, tag in found[:ROW_LIMIT]
    ]
    trailing = (
        f"{_plural(len(found), 'container')} found: {filled} hold items, "
        f"{tables} still carry an unrolled loot table, and "
        f"{len(found) - filled - tables} are empty. An unrolled loot table "
        "generates only when a player first opens the container. Types are "
        "named as Amulet stores them, in its universal palette. "
    ) + record.note(ctx)
    return _sections(
        spec,
        search,
        sec("Containers", "list", rows=rows),
        _note(trailing),
    )


# ----------------------------------------------------------------------
# entities
# ----------------------------------------------------------------------


@register("entityBrowser")
def _bind_entity_browser(spec: Spec, ctx: WorldContext) -> Spec:
    """Count the entities and block entities the scanned chunks actually hold."""
    if not ctx.open or ctx.level is None:
        return closed(spec)
    search = sec("", "search", hint="Search by type or coordinate")
    coords, record = _scan(ctx)
    if not coords:
        return _sections(spec, search, _nothing_read(spec, ctx, record, "entities"))

    entities: Dict[str, int] = {}
    named: Dict[str, int] = {}
    block_entities: Dict[str, int] = {}
    for _cx, _cz, chunk in _chunks(ctx, coords, record):
        try:
            members = list(chunk.entities)
        except Exception as error:  # noqa: BLE001 - one chunk, not the pass
            log.debug("Studio could not list entities: %s", error)
            members = []
        for entity in members:
            key = str(getattr(entity, "namespaced_name", "")) or "unnamed entity"
            entities[key] = entities.get(key, 0) + 1
            if _text(_tags(entity), "CustomName"):
                named[key] = named.get(key, 0) + 1
        for entity in _block_entities(chunk):
            key = str(getattr(entity, "namespaced_name", "")) or "unnamed block entity"
            block_entities[key] = block_entities.get(key, 0) + 1

    if not entities and not block_entities:
        return _sections(
            spec,
            search,
            _kept(spec, "Filters"),
            empty_section(
                "Entities",
                f"The {_plural(record.read, 'chunk')} read in {record.scope} hold "
                "no entities and no block entities.",
            ),
            _note(record.note(ctx)),
        )

    entity_rows = []
    for key, count in sorted(entities.items(), key=lambda item: (-item[1], item[0])):
        detail = f"{count} in {record.scope}"
        if named.get(key):
            detail += f" · {named[key]} named"
        entity_rows.append(Row(name=key, detail=detail, tag=str(count)))
    block_rows = [
        Row(name=key, detail=f"{count} in {record.scope}", tag=str(count))
        for key, count in sorted(
            block_entities.items(), key=lambda item: (-item[1], item[0])
        )
    ]

    entities_section = (
        sec("Entities", "list", rows=entity_rows[:ROW_LIMIT])
        if entity_rows
        else empty_section(
            "Entities",
            f"No entity was found in the {_plural(record.read, 'chunk')} read in "
            f"{record.scope}. Block entities are listed separately below.",
        )
    )
    block_section = (
        sec("Block entities", "list", rows=block_rows[:ROW_LIMIT])
        if block_rows
        else empty_section(
            "Block entities",
            f"No block entity was found in the {_plural(record.read, 'chunk')} "
            f"read in {record.scope}.",
        )
    )
    return _sections(
        spec,
        search,
        _kept(spec, "Filters"),
        entities_section,
        block_section,
        _note(
            f"{format_int(sum(entities.values()))} entities and "
            f"{format_int(sum(block_entities.values()))} block entities counted. "
            "Types are named as Amulet stores them, in its universal palette; "
            "one game version's own name for the same thing can differ. "
            + record.note(ctx)
        ),
    )


# ----------------------------------------------------------------------
# block state audit
# ----------------------------------------------------------------------


@register("blockAudit")
def _bind_block_audit(spec: Spec, ctx: WorldContext) -> Spec:
    """Report the block states that will not translate back to this world's version."""
    if not ctx.open or ctx.level is None:
        return closed(spec)
    coords, record = _scan(ctx)
    if not coords:
        return _sections(spec, _nothing_read(spec, ctx, record, "block states"))

    import numpy

    name_of = _block_namer(ctx)
    counts: Dict[str, int] = {}
    reasons: Dict[str, str] = {}
    total = 0
    for _cx, _cz, chunk in _chunks(ctx, coords, record):
        try:
            array = numpy.asarray(chunk.blocks[:, :, :])
        except Exception as error:  # noqa: BLE001 - one chunk, not the pass
            log.debug("Studio could not read a chunk's blocks: %s", error)
            continue
        ids, occurrences = numpy.unique(array, return_counts=True)
        for runtime_id, occurrence in zip(ids.tolist(), occurrences.tolist()):
            total += occurrence
            try:
                block = chunk.block_palette[runtime_id]
            except Exception:  # noqa: BLE001 - a palette gap is not fatal
                continue
            name, state, translated = name_of(block)
            reason = ""
            if not translated:
                reason = "no equivalent in this world's own version"
            elif "unknown" in name:
                reason = "placeholder written where a block could not be read"
            elif not name.startswith(("minecraft:", "universal_minecraft:")):
                reason = "not a vanilla namespace"
            if not reason:
                continue
            counts[state] = counts.get(state, 0) + occurrence
            reasons[state] = reason

    version = ctx.game_version or ctx.version or "this world's version"
    if not counts:
        return _sections(
            spec,
            empty_section(
                "Findings",
                f"Every block state in the {_plural(record.read, 'chunk')} read "
                f"in {record.scope} translates cleanly to {version}. "
                f"{format_int(total)} blocks were checked.",
            ),
            _kept(spec, "Resolution"),
            _note(record.note(ctx)),
        )

    rows = [
        Row(
            name=state,
            detail=f"{_plural(count, 'block')} · {reasons.get(state, '')}",
            tag=_percent(count, total) or "unmapped",
        )
        for state, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )[:ROW_LIMIT]
    ]
    return _sections(
        spec,
        sec("Findings", "list", rows=rows),
        _kept(spec, "Resolution"),
        _note(
            f"{_plural(len(counts), 'block state')} out of "
            f"{format_int(total)} blocks would not translate cleanly to "
            f"{version}. " + record.note(ctx)
        ),
    )


# ----------------------------------------------------------------------
# biomes
# ----------------------------------------------------------------------


@register("biomeMap")
def _bind_biome_map(spec: Spec, ctx: WorldContext) -> Spec:
    """Count the biomes the scanned chunks actually store."""
    if not ctx.open or ctx.level is None:
        return closed(spec)
    coords, record = _scan(ctx)
    if not coords:
        return _sections(spec, _nothing_read(spec, ctx, record, "biomes"))

    import numpy

    name_of = _biome_namer(ctx)
    counts: Dict[str, int] = {}
    total = 0
    unit = "columns"
    for _cx, _cz, chunk in _chunks(ctx, coords, record):
        try:
            array = numpy.asarray(chunk.biomes)
        except Exception as error:  # noqa: BLE001 - one chunk, not the pass
            log.debug("Studio could not read a chunk's biomes: %s", error)
            continue
        if array.size == 0:
            continue
        if array.ndim == 3:
            unit = "cells"
        ids, occurrences = numpy.unique(array, return_counts=True)
        for biome_id, occurrence in zip(ids.tolist(), occurrences.tolist()):
            try:
                biome = chunk.biome_palette[biome_id]
            except Exception:  # noqa: BLE001 - a palette gap is not fatal
                continue
            name = name_of(biome)
            counts[name] = counts.get(name, 0) + occurrence
            total += occurrence

    if not counts:
        return _sections(
            spec,
            empty_section(
                "Distribution",
                f"None of the {_plural(record.read, 'chunk')} read in "
                f"{record.scope} stores biome data.",
            ),
            _kept(spec, "View"),
            _note(record.note(ctx)),
        )

    rows = [
        Row(
            name=name,
            detail=f"{format_int(count)} {unit}",
            tag=_percent(count, total),
        )
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[
            :ROW_LIMIT
        ]
    ]
    return _sections(
        spec,
        sec("Distribution", "list", rows=rows),
        _kept(spec, "View"),
        _note(
            f"{_plural(len(counts), 'biome')} across {format_int(total)} {unit}. "
            + record.note(ctx)
        ),
    )


# ----------------------------------------------------------------------
# ores
# ----------------------------------------------------------------------


def _is_ore(name: str) -> bool:
    """Return whether a block name is one of the game's ore blocks."""
    base = name.split(":")[-1]
    return base.endswith("_ore") or base in ("ancient_debris", "glowing_obsidian")


@register("oreAudit")
def _bind_ore_audit(spec: Spec, ctx: WorldContext) -> Spec:
    """Count every ore block in the scanned chunks and find the layer it peaks at."""
    if not ctx.open or ctx.level is None:
        return closed(spec)
    coords, record = _scan(ctx)
    if not coords:
        return _sections(spec, _nothing_read(spec, ctx, record, "ores"))

    info = ctx.current_dimension()
    if info is None or not info.has_range:
        return _sections(
            spec,
            empty_section(
                "Per Y layer",
                f"{ctx.dimension or 'This dimension'} does not report a build "
                "range, so there is no set of layers to count ores across.",
            ),
        )
    low, high = int(info.min_y), int(info.max_y)

    import numpy

    name_of = _block_namer(ctx)
    layers: Dict[str, Any] = {}
    for _cx, _cz, chunk in _chunks(ctx, coords, record):
        try:
            array = numpy.asarray(chunk.blocks[:, low:high, :])
        except Exception as error:  # noqa: BLE001 - one chunk, not the pass
            log.debug("Studio could not read a chunk's blocks: %s", error)
            continue
        for runtime_id in numpy.unique(array).tolist():
            try:
                block = chunk.block_palette[runtime_id]
            except Exception:  # noqa: BLE001 - a palette gap is not fatal
                continue
            name = name_of(block)[0]
            if not _is_ore(name):
                continue
            per_y = (array == runtime_id).sum(axis=(0, 2))
            if name in layers:
                layers[name] = layers[name] + per_y
            else:
                layers[name] = per_y.astype("int64")

    if not layers:
        return _sections(
            spec,
            empty_section(
                "Per Y layer",
                f"No ore block was found in the {_plural(record.read, 'chunk')} "
                f"read in {record.scope}, between y {low} and y {high}.",
            ),
            _kept(spec, "Overlay"),
            _note(record.note(ctx)),
        )

    rows = []
    for name, per_y in sorted(
        layers.items(), key=lambda item: (-int(item[1].sum()), item[0])
    ):
        total = int(per_y.sum())
        peak = low + int(per_y.argmax())
        rows.append(
            Row(
                name=name,
                detail=f"peak at y {peak} · {_plural(total, 'block')} in "
                f"{record.scope}",
                tag=format_int(total),
            )
        )
    return _sections(
        spec,
        sec("Per Y layer", "list", rows=rows[:ROW_LIMIT]),
        sec(
            "Range",
            "fields",
            fields=[
                Field(label="Min Y", value=str(low)),
                Field(label="Max Y", value=str(high)),
            ],
        ),
        _kept(spec, "Overlay"),
        _note(
            f"{_plural(len(layers), 'ore type')} counted across y {low} to "
            f"y {high}. " + record.note(ctx)
        ),
    )


# ----------------------------------------------------------------------
# slime chunks
# ----------------------------------------------------------------------

_MASK_48 = (1 << 48) - 1


def _signed(value: int, bits: int) -> int:
    """Return ``value`` as a signed integer of ``bits`` width, as Java stores it."""
    value &= (1 << bits) - 1
    if value >= 1 << (bits - 1):
        value -= 1 << bits
    return value


class _JavaRandom:
    """The exact ``java.util.Random`` sequence the game seeds its grids from.

    Reimplementing it is not a preference: the slime-chunk grid is defined by
    this generator, so any other source of randomness would produce a grid that
    looks plausible and matches no world in existence.
    """

    def __init__(self, seed: int) -> None:
        self._seed = (seed ^ 0x5DEECE66D) & _MASK_48

    def _next(self, bits: int) -> int:
        self._seed = (self._seed * 0x5DEECE66D + 0xB) & _MASK_48
        return _signed(self._seed >> (48 - bits), 32)

    def next_int(self, bound: int) -> int:
        """Return the next value in ``[0, bound)``, rejecting a biased draw."""
        if bound & (bound - 1) == 0:
            return (bound * self._next(31)) >> 31
        while True:
            bits = self._next(31)
            value = bits % bound
            if _signed(bits - value + (bound - 1), 32) >= 0:
                return value


def _is_slime_chunk(seed: int, cx: int, cz: int) -> bool:
    """Return whether the game would spawn slimes in this chunk.

    The mixed 32-bit and 64-bit arithmetic below is not a mistake being copied:
    it is what the game does, and evaluating it consistently in one width would
    produce a different grid.
    """
    value = (
        seed
        + _signed(_signed(cx * cx, 32) * 0x4C1906, 32)
        + _signed(cx * 0x5AC0DB, 32)
        + _signed(cz * cz, 32) * 0x4C1906
        + _signed(cz * 0x5F24F, 32)
    ) ^ 0x3AD8025F
    return _JavaRandom(_signed(value, 64)).next_int(10) == 0


def _centre_chunk(ctx: WorldContext) -> Tuple[int, int, str]:
    """Return the chunk the grid is measured from, and what it was taken from."""
    bounds = ctx.selection_bounds()
    size = ctx.sub_chunk_size or 16
    if bounds is not None:
        low, high = bounds
        return (
            ((low[0] + high[0]) // 2) // size,
            ((low[2] + high[2]) // 2) // size,
            "the centre of the current selection",
        )
    if ctx.spawn is not None:
        return ctx.spawn[0] // size, ctx.spawn[2] // size, "the world spawn"
    return 0, 0, "the world origin, because nothing is selected and no spawn is stored"


@register("slimeChunks")
def _bind_slime_chunks(spec: Spec, ctx: WorldContext) -> Spec:
    """Compute the slime-chunk grid from this world's own seed."""
    if not ctx.open:
        return closed(spec)
    if not ctx.seed:
        return _sections(
            spec,
            empty_section(
                "Seed",
                "This world records no seed in its level.dat"
                + (f" ({ctx.reason('seed')})" if ctx.reason("seed") else "")
                + ", and the slime-chunk grid is derived entirely from the seed, "
                "so there is nothing to compute.",
            ),
        )
    try:
        seed = int(ctx.seed)
    except (TypeError, ValueError):
        return _sections(
            spec,
            empty_section(
                "Seed",
                f"This world's seed is stored as {ctx.seed!r}, which is not a "
                "whole number, so the slime-chunk grid cannot be computed from it.",
            ),
        )
    platform = (ctx.platform or "").lower()
    if platform not in ("", "java"):
        return _sections(
            spec,
            sec(
                "Seed",
                "fields",
                fields=[
                    Field(label="World seed", value=ctx.seed),
                    Field(label="Platform", value=ctx.platform),
                ],
            ),
            empty_section(
                "Nearest slime chunks",
                f"The slime-chunk grid shown here is the Java algorithm, and "
                f"{ctx.platform} generates its slime chunks differently. Amulet "
                "does not compute the grid for this platform, so no chunk is "
                "listed rather than a Java grid being shown for a world it does "
                "not describe.",
            ),
        )

    centre_x, centre_z, source = _centre_chunk(ctx)
    size = ctx.sub_chunk_size or 16
    found: List[Tuple[float, int, int]] = []
    for cx in range(centre_x - SLIME_RADIUS, centre_x + SLIME_RADIUS + 1):
        for cz in range(centre_z - SLIME_RADIUS, centre_z + SLIME_RADIUS + 1):
            if not _is_slime_chunk(seed, cx, cz):
                continue
            distance = math.hypot(cx - centre_x, cz - centre_z) * size
            found.append((distance, cx, cz))
    found.sort()

    searched = (SLIME_RADIUS * 2 + 1) ** 2
    if not found:
        rows_section: Section = empty_section(
            "Nearest slime chunks",
            f"None of the {format_int(searched)} chunks within {SLIME_RADIUS} "
            f"chunks of {source} is a slime chunk for seed {seed}.",
        )
    else:
        rows = []
        for distance, cx, cz in found[:SLIME_ROW_LIMIT]:
            centre = f"{cx * size + size // 2}, {cz * size + size // 2}"
            rows.append(
                Row(
                    name=f"chunk {cx}, {cz}",
                    detail=f"centre {centre}",
                    tag=("here" if distance == 0 else f"{distance:.0f} m"),
                )
            )
        rows_section = sec("Nearest slime chunks", "list", rows=rows)

    return _sections(
        spec,
        sec(
            "Seed",
            "fields",
            fields=[
                Field(label="World seed", value=ctx.seed),
                Field(label="Chunk radius", value=str(SLIME_RADIUS)),
                Field(label="Centred on chunk", value=f"{centre_x}, {centre_z}"),
                Field(label="Dimension", value=ctx.dimension or "not reported"),
            ],
        ),
        rows_section,
        _kept(spec, "Overlay"),
        _note(
            f"{_plural(len(found), 'slime chunk')} among the "
            f"{format_int(searched)} chunks within {SLIME_RADIUS} chunks of "
            f"{source}, computed from seed {seed} with the Java algorithm. The "
            "grid is a property of the seed, so it holds whether or not those "
            "chunks have been generated."
        ),
    )


# ----------------------------------------------------------------------
# seed
# ----------------------------------------------------------------------


@register("seedTools")
def _bind_seed_tools(spec: Spec, ctx: WorldContext) -> Spec:
    """Show the seed this world stores and what is derived from it."""
    if not ctx.open:
        return closed(spec)

    info = ctx.current_dimension()
    generated = info.chunk_count if info is not None and info.counted else 0
    seed_known = bool(ctx.seed)
    fields = [
        Field(
            label="Current seed",
            value=ctx.seed,
            placeholder=ctx.reason("seed") or "not stored in this level.dat",
        ),
        Field(label="New seed", value="", placeholder="leave blank to keep the seed"),
        Field(
            label="Generator",
            value=ctx.generator,
            placeholder=ctx.reason("generator") or "not stored",
        ),
        Field(label="Dimension", value=ctx.dimension, placeholder="not reported"),
    ]

    derived = [
        Row(
            name="Slime chunk grid",
            detail=(
                f"Computed from seed {ctx.seed}"
                if seed_known
                else "Cannot be computed: this world stores no seed"
            ),
            tag="derived" if seed_known else "unavailable",
        ),
        Row(
            name="Structure positions",
            detail=(
                "Predicted positions change with the seed; Amulet reads the "
                "structures the chunks already record rather than generating them"
            ),
            tag="derived",
        ),
        Row(
            name="Biome layout",
            detail=(
                (
                    f"{format_int(generated)} chunks are already generated in "
                    f"{ctx.dimension or 'this dimension'} and keep their terrain; "
                    "only chunks generated after a change would follow a new seed"
                )
                if info is not None
                else "This dimension does not report a chunk count"
            ),
            tag="partial",
        ),
    ]

    return _sections(
        spec,
        sec("Seed", "fields", fields=fields),
        sec("Derived", "list", rows=derived),
        _note(
            (
                f"Seed {ctx.seed} read from the level.dat in {_where(ctx)}."
                if seed_known
                else f"No seed is stored in the level.dat in {_where(ctx)}."
            )
            + " Changing a seed affects only chunks generated afterwards, and "
            "Amulet reports the border mismatch rather than hiding it."
        ),
    )


# ----------------------------------------------------------------------
# world border
# ----------------------------------------------------------------------

#: The border fields Java stores in level.dat, and the label each is shown
#: under.  A field the file does not contain is left out rather than shown with
#: the game's default, because a default would claim the world says something
#: it does not.
_BORDER_FIELDS = (
    ("Centre x", "BorderCenterX"),
    ("Centre z", "BorderCenterZ"),
    ("Diameter", "BorderSize"),
    ("Warning distance", "BorderWarningBlocks"),
    ("Warning time", "BorderWarningTime"),
)

_BORDER_DAMAGE_FIELDS = (
    ("Damage per block", "BorderDamagePerBlock"),
    ("Damage buffer", "BorderSafeZone"),
)


def _level_data(ctx: WorldContext) -> Any:
    """Return the compound holding this world's own level.dat fields."""
    wrapper = getattr(ctx.level, "level_wrapper", None)
    root = getattr(wrapper, "root_tag", None)
    compound = getattr(root, "compound", None)
    if compound is None:
        return None
    nested = _compound(compound, "Data")
    return nested if nested is not None else compound


def _number_text(value: Optional[float]) -> str:
    """Return a stored number the way the game writes it, without a false decimal."""
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


@register("worldBorder")
def _bind_world_border(spec: Spec, ctx: WorldContext) -> Spec:
    """Show the world border exactly as level.dat records it."""
    if not ctx.open:
        return closed(spec)
    data = _level_data(ctx)
    stored = {
        key: _number(data, key)
        for _label, key in _BORDER_FIELDS + _BORDER_DAMAGE_FIELDS
    }
    if not any(value is not None for value in stored.values()):
        return _sections(
            spec,
            empty_section(
                "Border",
                "This world's level.dat records no world border. A world gains "
                "the border fields the first time the border is moved from its "
                f"default, so there is nothing stored here to show. Read from "
                f"{_where(ctx)}.",
            ),
        )

    border_fields = [
        Field(
            label=label,
            value=_number_text(stored.get(key)),
            placeholder="not stored in this level.dat",
        )
        for label, key in _BORDER_FIELDS
    ]
    damage_fields = [
        Field(
            label=label,
            value=_number_text(stored.get(key)),
            placeholder="not stored in this level.dat",
        )
        for label, key in _BORDER_DAMAGE_FIELDS
    ]

    diameter = stored.get("BorderSize")
    centre_x = stored.get("BorderCenterX")
    centre_z = stored.get("BorderCenterZ")
    summary = ""
    if diameter is not None and centre_x is not None and centre_z is not None:
        half = diameter / 2.0
        summary = (
            f"The border runs from {_number_text(centre_x - half)}, "
            f"{_number_text(centre_z - half)} to "
            f"{_number_text(centre_x + half)}, "
            f"{_number_text(centre_z + half)}. "
        )
    lerp_target = _number(data, "BorderSizeLerpTarget")
    if lerp_target is not None and diameter is not None and lerp_target != diameter:
        summary += (
            f"The border is moving towards a diameter of {_number_text(lerp_target)}. "
        )

    return _sections(
        spec,
        sec("Border", "fields", fields=border_fields),
        sec("Damage", "fields", fields=damage_fields),
        _kept(spec, "Options"),
        _note(summary + f"Read from the level.dat in {_where(ctx)}."),
    )


# ----------------------------------------------------------------------
# force-loaded chunks
# ----------------------------------------------------------------------


@register("forceLoaded")
def _bind_force_loaded(spec: Spec, ctx: WorldContext) -> Spec:
    """List the chunks this world's own ticket file forces to stay loaded."""
    if not ctx.open:
        return closed(spec)
    unsupported = _java_only(spec, ctx, "Force-loaded chunk tickets")
    if unsupported is not None:
        return unsupported

    path = _world_file(ctx, "data", "chunks.dat")
    data = _compound(_load_nbt(path), "data")
    forced = _py(_get(data, "Forced")) if data is not None else None
    positions: List[Tuple[int, int]] = []
    if forced is not None:
        try:
            for packed in forced:
                value = int(packed)
                positions.append(
                    (_signed(value & 0xFFFFFFFF, 32), _signed(value >> 32, 32))
                )
        except TypeError:
            positions = []
    positions.sort()

    spawn_row = Row(
        name="World spawn",
        detail=(
            f"{_coords(*ctx.spawn)} · the chunks around it always tick"
            if ctx.spawn is not None
            else ctx.reason("spawn") or "this world records no spawn point"
        ),
        tag="spawn" if ctx.spawn is not None else "not stored",
    )

    if not positions:
        why = (
            f"This world has no readable data{os.sep}chunks.dat, so no chunk is "
            "held loaded by a ticket. The file is written the first time the "
            "forceload command is used, and only from Java 1.13 onwards."
            if data is None
            else "This world's chunks.dat records no forced chunks."
        )
        return _sections(
            spec,
            empty_section("Force loaded", f"{why} Looked in {path or _where(ctx)}."),
            sec("Summary", "list", rows=[spawn_row]),
        )

    rows = [
        Row(
            name=f"chunk {cx}, {cz}",
            detail=f"blocks {cx * 16}, {cz * 16} to {cx * 16 + 15}, {cz * 16 + 15}",
            tag="forced",
        )
        for cx, cz in positions[:ROW_LIMIT]
    ]
    summary = [
        Row(
            name="Forced chunks",
            detail=f"recorded for this world in data{os.sep}chunks.dat",
            tag=format_int(len(positions)),
        ),
        spawn_row,
    ]
    return _sections(
        spec,
        sec("Force loaded", "list", rows=rows),
        sec("Summary", "list", rows=summary),
        _note(
            f"{_plural(len(positions), 'forced chunk')} read from {path}. "
            "The ticket file is written per world, not per dimension, so every "
            "forced chunk this world holds is listed."
        ),
    )


# ----------------------------------------------------------------------
# structures
# ----------------------------------------------------------------------


def _structure_rows_from_chunks(ctx: WorldContext, coords, record) -> List[Row]:
    """Return one row per structure start the scanned chunks record."""
    rows: List[Row] = []
    seen = set()
    for cx, cz, chunk in _chunks(ctx, coords, record):
        structures = None
        try:
            structures = chunk.misc.get("structures")
        except Exception as error:  # noqa: BLE001 - one chunk, not the pass
            log.debug("Studio could not read a chunk's structures: %s", error)
        starts = _compound(structures, "Starts", "starts")
        if starts is None:
            continue
        try:
            members = list(starts.items())
        except Exception:  # noqa: BLE001 - a malformed start block lists nothing
            continue
        for key, start in members:
            identifier = _text(start, "id") or str(key)
            if identifier.upper() == "INVALID":
                continue
            box = _py(_get(start, "BB"))
            position = ""
            if box is not None:
                try:
                    corners = [int(part) for part in box]
                    if len(corners) >= 6:
                        position = _coords(
                            (corners[0] + corners[3]) // 2,
                            (corners[1] + corners[4]) // 2,
                            (corners[2] + corners[5]) // 2,
                        )
                except (TypeError, ValueError):
                    position = ""
            if not position:
                chunk_x = _whole(start, "ChunkX")
                chunk_z = _whole(start, "ChunkZ")
                if chunk_x is not None and chunk_z is not None:
                    position = f"{chunk_x * 16}, {chunk_z * 16}"
            marker = (identifier, position)
            if marker in seen:
                continue
            seen.add(marker)
            rows.append(
                Row(
                    name=identifier,
                    detail=f"{position or 'position not recorded'} · recorded in "
                    f"chunk {cx}, {cz}",
                    tag="generated",
                )
            )
    return rows


def _structure_rows_from_files(ctx: WorldContext) -> Tuple[List[Row], List[str]]:
    """Return the structures the 1.12-era per-structure files record."""
    rows: List[Row] = []
    read: List[str] = []
    folder = _world_file(ctx, "data")
    if not folder or not os.path.isdir(folder):
        return rows, read
    for name in LEGACY_STRUCTURE_FILES:
        path = os.path.join(folder, name)
        data = _compound(_load_nbt(path), "data")
        features = _compound(data, "Features")
        if features is None:
            continue
        read.append(name)
        try:
            members = list(features.items())
        except Exception:  # noqa: BLE001 - a malformed feature block lists nothing
            continue
        for _key, feature in members:
            identifier = _text(feature, "id") or name[:-4]
            chunk_x = _whole(feature, "ChunkX")
            chunk_z = _whole(feature, "ChunkZ")
            position = (
                f"{chunk_x * 16}, {chunk_z * 16}"
                if chunk_x is not None and chunk_z is not None
                else "position not recorded"
            )
            rows.append(
                Row(
                    name=identifier,
                    detail=f"{position} · recorded in {name}",
                    tag="generated",
                )
            )
    return rows, read


@register("structureLocator")
def _bind_structure_locator(spec: Spec, ctx: WorldContext) -> Spec:
    """List the structures this world has actually recorded, and only those."""
    if not ctx.open or ctx.level is None:
        return closed(spec)
    search = sec("", "search", hint="Search structure types and coordinates")
    coords, record = _scan(ctx)
    rows = _structure_rows_from_chunks(ctx, coords, record)
    legacy_rows, legacy_files = _structure_rows_from_files(ctx)
    rows.extend(legacy_rows)
    rows.sort(key=lambda row: (row.name, row.detail))

    where = (
        f"Read the structure references stored in the "
        f"{_plural(record.read, 'chunk')} scanned in {record.scope}"
    )
    if legacy_files:
        where += f", and the {', '.join(legacy_files)} files this world keeps"
    where += (
        ". Amulet reads the structures a world has already recorded; it does "
        "not run world generation, so a structure in a chunk that has never "
        "generated is not predicted here."
    )

    if not rows:
        return _sections(
            spec,
            search,
            _kept(spec, "Type"),
            empty_section(
                "Found",
                "No structure reference was found. "
                + where
                + f" Read from {_where(ctx)}.",
            ),
        )

    return _sections(
        spec,
        search,
        _kept(spec, "Type"),
        sec("Found", "list", rows=rows[:ROW_LIMIT]),
        _note(
            f"{_plural(len(rows), 'structure')} recorded by this world. "
            + where
            + f" Read from {_where(ctx)}."
        ),
    )


__all__ = [
    "CHUNK_SCAN_LIMIT",
    "LEGACY_STRUCTURE_FILES",
    "NOT_ON_PLATFORM",
    "ROW_LIMIT",
    "SIGN_NAMES",
    "SLIME_RADIUS",
    "SLIME_ROW_LIMIT",
    "Scan",
]
