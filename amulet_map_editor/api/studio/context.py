"""The one place Amulet Studio asks what world is currently open.

Every Studio surface that shows a number about the user's world reads it from
here rather than from a constant written beside the layout.  The module holds a
single :class:`WorldContext` -- an immutable snapshot of whatever
``amulet.api.level.BaseLevel`` the shell last handed over -- and hands it out
through :func:`current`.

Three rules shape the whole module:

* **Nothing is invented.**  A value that cannot be read from the open level is
  left empty and the reason is recorded in :attr:`WorldContext.reasons`, so a
  surface can say *why* it has nothing to show instead of showing a plausible
  number.
* **Nothing raises.**  A world can be half-written, locked, from a format this
  build does not fully understand, or simply missing the field being asked for.
  Every read goes through :class:`_Reader`, which turns a failure into an empty
  value plus a recorded reason.
* **Nothing here needs a display.**  The module imports neither ``wx`` nor
  ``amulet`` at module scope, so a test, a build step, or a documentation pass
  can import it and read the contract without a world or a window.

The shell owns the lifetime: it calls :func:`set_level` when a world opens and
:func:`clear` when the last one closes.  Panes that want to redraw when either
happens call :func:`subscribe`.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)

#: A block position.
Coord = Tuple[int, int, int]

#: A subscriber, called with the context that has just replaced the old one.
Listener = Callable[["WorldContext"], None]

#: The most files :func:`_disk_usage` will stat before it stops and says so.
#: A large modded world can hold hundreds of thousands of files and the walk
#: happens while the user is waiting for the world to open.
DISK_WALK_LIMIT = 250_000

#: The most chunk coordinates counted per dimension before the count is
#: reported as a floor rather than a total.
CHUNK_SCAN_LIMIT = 2_000_000


@dataclass(frozen=True)
class SelectionBox:
    """One axis-aligned box of the current selection, in block coordinates.

    This mirrors the parts of ``amulet.api.selection.SelectionBox`` the Studio
    displays.  It is a local type so that reading the context never requires
    amulet-core to be importable, and so the value a surface renders cannot
    change underneath it while the user is dragging a corner.
    """

    min: Coord = (0, 0, 0)
    max: Coord = (0, 0, 0)

    @property
    def size(self) -> Coord:
        """Return the box's extent along each axis."""
        return (
            self.max[0] - self.min[0],
            self.max[1] - self.min[1],
            self.max[2] - self.min[2],
        )

    @property
    def volume(self) -> int:
        """Return how many blocks the box contains."""
        size_x, size_y, size_z = self.size
        return abs(size_x * size_y * size_z)

    @property
    def footprint(self) -> int:
        """Return how many blocks the box covers looking straight down."""
        size_x, _size_y, size_z = self.size
        return abs(size_x * size_z)

    @property
    def diagonal(self) -> float:
        """Return the straight-line distance between the two corners."""
        size_x, size_y, size_z = self.size
        return math.sqrt(size_x**2 + size_y**2 + size_z**2)

    def chunk_coords(self, sub_chunk_size: int = 16) -> Tuple[Tuple[int, int], ...]:
        """Return every chunk column this box touches."""
        if sub_chunk_size <= 0 or self.volume == 0:
            return ()
        min_cx = self.min[0] // sub_chunk_size
        min_cz = self.min[2] // sub_chunk_size
        max_cx = (self.max[0] - 1) // sub_chunk_size
        max_cz = (self.max[2] - 1) // sub_chunk_size
        return tuple(
            (cx, cz)
            for cx in range(min_cx, max_cx + 1)
            for cz in range(min_cz, max_cz + 1)
        )


@dataclass(frozen=True)
class DimensionInfo:
    """What the open world reports about one of its dimensions."""

    name: str
    min_y: Optional[int] = None
    max_y: Optional[int] = None
    chunk_count: int = 0
    #: ``False`` when the chunk count could not be read at all, which is a
    #: different statement from a dimension that genuinely holds no chunks.
    counted: bool = True
    #: ``True`` when :data:`CHUNK_SCAN_LIMIT` stopped the count early, so
    #: ``chunk_count`` is a floor rather than a total.
    truncated: bool = False

    @property
    def has_range(self) -> bool:
        return self.min_y is not None and self.max_y is not None

    @property
    def height(self) -> int:
        """Return how many blocks tall the dimension is, or ``0`` if unknown."""
        if not self.has_range:
            return 0
        return int(self.max_y) - int(self.min_y)


@dataclass(frozen=True)
class DiskEntry:
    """One top-level part of the world folder and what it costs on disk."""

    label: str
    files: int = 0
    size: int = 0


@dataclass(frozen=True)
class WorldContext:
    """An immutable snapshot of the world the user currently has open.

    Every field is either read from the level or left at its empty default with
    a reason recorded in :attr:`reasons`.  There is no third state, and no
    field ever holds a stand-in value.
    """

    open: bool = False
    name: str = ""
    path: str = ""
    platform: str = ""
    version: str = ""
    #: The format's own version string, e.g. ``"Java 1.12.2"``.
    game_version: str = ""
    #: Java's ``DataVersion``; ``None`` on a platform that does not store one.
    data_version: Optional[int] = None

    dimensions: Tuple[str, ...] = ()
    dimension: str = ""
    dimension_info: Tuple[DimensionInfo, ...] = ()

    selection_boxes: Tuple[SelectionBox, ...] = ()
    selection_volume: int = 0

    #: Chunks stored in :attr:`dimension`.  Per-dimension counts live in
    #: :attr:`dimension_info`.
    chunk_count: int = 0
    sub_chunk_size: int = 16

    size_on_disk: int = 0
    disk_breakdown: Tuple[DiskEntry, ...] = ()

    seed: str = ""
    game_rules: Dict[str, str] = field(default_factory=dict)

    spawn: Optional[Coord] = None
    time: Optional[int] = None
    day_time: Optional[int] = None
    last_played: Optional[int] = None

    game_mode: str = ""
    difficulty: str = ""
    generator: str = ""
    raining: Optional[bool] = None
    thundering: Optional[bool] = None
    hardcore: Optional[bool] = None
    allow_commands: Optional[bool] = None

    #: Why a field above is empty, keyed by the field name.  A field that read
    #: cleanly is absent from this mapping.
    reasons: Dict[str, str] = field(default_factory=dict)

    #: The live level this snapshot was taken from, for the surfaces that must
    #: read chunks themselves.  Excluded from equality and ``repr`` so a
    #: context stays comparable and printable; ``None`` when no world is open.
    level: Any = field(default=None, compare=False, repr=False)

    # -- derived reads -------------------------------------------------

    @property
    def has_selection(self) -> bool:
        return bool(self.selection_boxes) and self.selection_volume > 0

    @property
    def weather(self) -> str:
        """Return the current weather, or ``""`` when it was not recorded."""
        if self.thundering:
            return "thunder"
        if self.raining:
            return "rain"
        if self.raining is None and self.thundering is None:
            return ""
        return "clear"

    def reason(self, key: str) -> str:
        """Return why ``key`` is empty, or ``""`` when it read cleanly."""
        return self.reasons.get(key, "")

    def dimension_named(self, name: str) -> Optional[DimensionInfo]:
        """Return the record for ``name``, or ``None`` when it has none."""
        for info in self.dimension_info:
            if info.name == name:
                return info
        return None

    def current_dimension(self) -> Optional[DimensionInfo]:
        """Return the record for the selected dimension."""
        return self.dimension_named(self.dimension)

    def selection_bounds(self) -> Optional[Tuple[Coord, Coord]]:
        """Return one box enclosing the whole selection, or ``None``."""
        if not self.selection_boxes:
            return None
        lows = [box.min for box in self.selection_boxes]
        highs = [box.max for box in self.selection_boxes]
        return (
            (
                min(point[0] for point in lows),
                min(point[1] for point in lows),
                min(point[2] for point in lows),
            ),
            (
                max(point[0] for point in highs),
                max(point[1] for point in highs),
                max(point[2] for point in highs),
            ),
        )

    def selection_chunks(self) -> Tuple[Tuple[int, int], ...]:
        """Return every chunk column the selection touches, without repeats."""
        seen: List[Tuple[int, int]] = []
        found = set()
        for box in self.selection_boxes:
            for coord in box.chunk_coords(self.sub_chunk_size):
                if coord not in found:
                    found.add(coord)
                    seen.append(coord)
        return tuple(seen)


#: The context every surface sees when there is no world open.
EMPTY = WorldContext()


class _Reader:
    """Runs one guarded read and records why it failed rather than raising."""

    def __init__(self) -> None:
        self.reasons: Dict[str, str] = {}

    def read(self, key: str, getter: Callable[[], Any], default: Any = None) -> Any:
        """Return ``getter()``, or ``default`` with the failure recorded."""
        try:
            value = getter()
        except Exception as err:  # noqa: BLE001 - a world may fail any read
            reason = f"{type(err).__name__}: {err}" if str(err) else type(err).__name__
            self.reasons[key] = reason
            log.debug("Studio world context could not read %s: %s", key, reason)
            return default
        if value is None:
            self.reasons.setdefault(key, "the world does not record this value")
        return value

    def note(self, key: str, reason: str) -> None:
        """Record ``reason`` for ``key`` without attempting a read."""
        self.reasons[key] = reason


# ----------------------------------------------------------------------
# level.dat readers
# ----------------------------------------------------------------------

#: Java stores its rules in one compound; Bedrock stores each rule as its own
#: top-level key, so the names it may use have to be known to be looked for.
#: Only the ones actually present in the file are ever reported.
_BEDROCK_GAME_RULE_NAMES: Tuple[str, ...] = (
    "commandBlockOutput",
    "commandBlocksEnabled",
    "doDayLightCycle",
    "doEntityDrops",
    "doFireTick",
    "doImmediateRespawn",
    "doInsomnia",
    "doLimitedCrafting",
    "doMobLoot",
    "doMobSpawning",
    "doTileDrops",
    "doWeatherCycle",
    "drowningDamage",
    "fallDamage",
    "fireDamage",
    "freezeDamage",
    "functionCommandLimit",
    "keepInventory",
    "maxCommandChainLength",
    "mobGriefing",
    "naturalRegeneration",
    "playersSleepingPercentage",
    "pvp",
    "randomTickSpeed",
    "recipesUnlock",
    "respawnBlocksExplode",
    "sendCommandFeedback",
    "showBorderEffect",
    "showCoordinates",
    "showDeathMessages",
    "showTags",
    "spawnRadius",
    "tntExplodes",
)

#: The vanilla game-mode ids, in the order Minecraft numbers them.
GAME_MODES: Tuple[str, ...] = ("survival", "creative", "adventure", "spectator")

#: The vanilla difficulty ids, in the order Minecraft numbers them.
DIFFICULTIES: Tuple[str, ...] = ("peaceful", "easy", "normal", "hard")


def _py(tag: Any) -> Any:
    """Return the plain Python value behind an amulet-nbt tag."""
    if tag is None:
        return None
    value = getattr(tag, "py_data", None)
    return tag if value is None else value


def _level_dat_compound(wrapper: Any) -> Any:
    """Return the compound holding the world's own level.dat fields.

    Java nests everything under ``Data``; Bedrock keeps it at the root.  The
    caller gets whichever this world actually uses, or ``None``.
    """
    root = getattr(wrapper, "root_tag", None)
    compound = getattr(root, "compound", None)
    if compound is None:
        return None
    try:
        if "Data" in compound:
            nested = compound.get_compound("Data")
            if nested is not None and len(nested):
                return nested
    except Exception:  # noqa: BLE001 - a malformed root is just not nested
        return compound
    return compound


def _tag(compound: Any, *names: str) -> Any:
    """Return the first of ``names`` present in ``compound``, else ``None``."""
    if compound is None:
        return None
    for name in names:
        try:
            if name in compound:
                return compound[name]
        except Exception:  # noqa: BLE001 - an unusual compound is not fatal
            return None
    return None


def _int(compound: Any, *names: str) -> Optional[int]:
    value = _py(_tag(compound, *names))
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _text(compound: Any, *names: str) -> str:
    value = _py(_tag(compound, *names))
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _bool(compound: Any, *names: str) -> Optional[bool]:
    value = _int(compound, *names)
    return None if value is None else bool(value)


def _read_seed(compound: Any) -> str:
    """Return the world seed as text, from wherever this version stores it.

    Java 1.16 moved the seed from ``Data/RandomSeed`` into
    ``Data/WorldGenSettings/seed``; Bedrock keeps ``RandomSeed`` throughout.
    The seed is returned as text because a 64-bit seed is routinely shown, and
    copied, in full rather than being arithmetic.
    """
    seed = _int(compound, "RandomSeed")
    if seed is None and compound is not None:
        try:
            if "WorldGenSettings" in compound:
                seed = _int(compound.get_compound("WorldGenSettings"), "seed")
        except Exception:  # noqa: BLE001 - an absent settings block is normal
            seed = None
    return "" if seed is None else str(seed)


def _read_game_rules(compound: Any, platform: str) -> Dict[str, str]:
    """Return every game rule this world actually stores, as text.

    A rule the file does not contain is absent from the result rather than
    present with a default, because a defaulted rule would claim the world says
    something it does not.
    """
    rules: Dict[str, str] = {}
    if compound is None:
        return rules
    try:
        if "GameRules" in compound:
            for key, value in compound.get_compound("GameRules").items():
                plain = _py(value)
                rules[str(key)] = "" if plain is None else str(plain)
    except Exception:  # noqa: BLE001 - a malformed rule block yields nothing
        pass
    if rules or platform != "bedrock":
        return rules
    for name in _BEDROCK_GAME_RULE_NAMES:
        value = _py(_tag(compound, name))
        if value is None:
            continue
        if isinstance(value, bool):
            rules[name] = "true" if value else "false"
        elif isinstance(value, int) and name.startswith(("do", "show", "is")):
            rules[name] = "true" if value else "false"
        else:
            rules[name] = str(value)
    return rules


def _read_generator(compound: Any) -> str:
    """Return the world generator's name, or ``""`` when it is not recorded."""
    name = _text(compound, "generatorName")
    if name:
        return name
    generator = _int(compound, "Generator")
    if generator is None:
        return ""
    # Bedrock stores the generator as a number; these are its documented ids.
    bedrock = {0: "old", 1: "infinite", 2: "flat", 5: "void"}
    return bedrock.get(generator, str(generator))


def _read_last_played(compound: Any) -> Optional[int]:
    """Return when the world was last played, as whole seconds since 1970.

    Java records milliseconds and Bedrock records seconds, so the raw number is
    normalised here rather than in each surface that shows a date.
    """
    raw = _int(compound, "LastPlayed")
    if raw is None or raw <= 0:
        return None
    # Any plausible millisecond timestamp is far beyond a plausible second one.
    return raw // 1000 if raw > 100_000_000_000 else raw


# ----------------------------------------------------------------------
# disk and chunk readers
# ----------------------------------------------------------------------


def _disk_usage(path: str) -> Tuple[int, Tuple[DiskEntry, ...], bool]:
    """Return the world's size, its top-level breakdown, and whether it capped.

    The breakdown is by the entries directly inside the world folder, which is
    what a user recognises: ``region``, ``playerdata``, ``db``, ``level.dat``.
    """
    if not path or not os.path.isdir(path):
        return 0, (), False
    entries: List[DiskEntry] = []
    total = 0
    seen = 0
    truncated = False
    for name in sorted(os.listdir(path)):
        target = os.path.join(path, name)
        files = 0
        size = 0
        if os.path.isdir(target):
            for _root, _dirs, filenames in os.walk(target):
                for filename in filenames:
                    try:
                        size += os.path.getsize(os.path.join(_root, filename))
                    except OSError:
                        continue
                    files += 1
                    seen += 1
                if seen >= DISK_WALK_LIMIT:
                    truncated = True
                    break
        else:
            try:
                size = os.path.getsize(target)
            except OSError:
                continue
            files = 1
            seen += 1
        entries.append(DiskEntry(label=name, files=files, size=size))
        total += size
        if truncated:
            break
    return total, tuple(entries), truncated


def _count_chunks(level: Any, dimension: str) -> Tuple[int, bool]:
    """Return how many chunks ``dimension`` holds and whether the count capped."""
    count = 0
    for _coord in level.all_chunk_coords(dimension):
        count += 1
        if count >= CHUNK_SCAN_LIMIT:
            return count, True
    return count, False


def _read_dimensions(level: Any, reader: _Reader) -> Tuple[DimensionInfo, ...]:
    """Return one record per dimension, each read independently.

    A dimension whose bounds or chunk list cannot be read still appears, with
    the parts that did read; a whole world does not go blank because one of its
    dimensions is unreadable.
    """
    names = reader.read("dimensions", lambda: tuple(level.dimensions), ()) or ()
    records: List[DimensionInfo] = []
    for name in names:
        text = str(name)
        min_y: Optional[int] = None
        max_y: Optional[int] = None
        try:
            bounds = level.bounds(text)
            min_y = int(bounds.min_y)
            max_y = int(bounds.max_y)
        except Exception as err:  # noqa: BLE001 - one dimension, not the world
            reader.note(f"bounds:{text}", f"{type(err).__name__}: {err}")
        try:
            count, truncated = _count_chunks(level, text)
            counted = True
        except Exception as err:  # noqa: BLE001 - an unreadable region folder
            reader.note(f"chunks:{text}", f"{type(err).__name__}: {err}")
            count, truncated, counted = 0, False, False
        records.append(
            DimensionInfo(
                name=text,
                min_y=min_y,
                max_y=max_y,
                chunk_count=count,
                counted=counted,
                truncated=truncated,
            )
        )
    return tuple(records)


def _default_dimension(names: Sequence[str]) -> str:
    """Return the dimension a world should open on."""
    for name in names:
        if str(name).endswith("overworld"):
            return str(name)
    return str(names[0]) if names else ""


# ----------------------------------------------------------------------
# selection readers
# ----------------------------------------------------------------------


def _coerce_box(value: Any) -> Optional[SelectionBox]:
    """Return ``value`` as a :class:`SelectionBox`, or ``None`` if it is not one.

    Accepts this module's own box, an ``amulet.api.selection.SelectionBox``,
    and the ``(min, max)`` corner pair the canvas stores internally, so a
    caller never has to convert before pushing a selection in.
    """
    if isinstance(value, SelectionBox):
        return value
    low = getattr(value, "min", None)
    high = getattr(value, "max", None)
    if low is None or high is None:
        try:
            low, high = value
        except Exception:  # noqa: BLE001 - not a corner pair either
            return None
    try:
        low_point = tuple(int(part) for part in low)
        high_point = tuple(int(part) for part in high)
    except Exception:  # noqa: BLE001 - not a coordinate triple
        return None
    if len(low_point) != 3 or len(high_point) != 3:
        return None
    return SelectionBox(
        min=(
            min(low_point[0], high_point[0]),
            min(low_point[1], high_point[1]),
            min(low_point[2], high_point[2]),
        ),
        max=(
            max(low_point[0], high_point[0]),
            max(low_point[1], high_point[1]),
            max(low_point[2], high_point[2]),
        ),
    )


def _coerce_boxes(boxes: Optional[Iterable[Any]]) -> Tuple[SelectionBox, ...]:
    """Return every box in ``boxes`` this module understands."""
    if not boxes:
        return ()
    coerced = []
    for value in boxes:
        box = _coerce_box(value)
        if box is not None and box.volume:
            coerced.append(box)
    return tuple(coerced)


def _canvas_selection(canvas: Any) -> Optional[Tuple[SelectionBox, ...]]:
    """Return the canvas's current selection, or ``None`` when it has none.

    ``None`` and ``()`` mean different things here: ``None`` says the canvas
    could not be asked, ``()`` says it was asked and nothing is selected.
    """
    if canvas is None:
        return None
    try:
        group = canvas.selection.selection_group
        return _coerce_boxes(group.selection_boxes)
    except Exception as err:  # noqa: BLE001 - a canvas mid-teardown answers this
        log.debug("Studio world context could not read the selection: %s", err)
        return None


def _canvas_dimension(canvas: Any) -> str:
    """Return the dimension the canvas is showing, or ``""``."""
    if canvas is None:
        return ""
    try:
        return str(canvas.dimension or "")
    except Exception as err:  # noqa: BLE001 - a canvas without a renderer yet
        log.debug("Studio world context could not read the dimension: %s", err)
        return ""


# ----------------------------------------------------------------------
# the snapshot itself
# ----------------------------------------------------------------------


def snapshot(
    level: Any,
    path: str = "",
    name: str = "",
    canvas: Any = None,
    dimension: str = "",
) -> WorldContext:
    """Return a :class:`WorldContext` read from ``level``.

    This is the whole of the reading logic and it is deliberately callable
    without touching module state, so a caller can snapshot a level it is not
    making current -- a test, a comparison, a second world.
    """
    if level is None:
        return EMPTY
    reader = _Reader()
    wrapper = reader.read("level_wrapper", lambda: level.level_wrapper)

    level_path = str(
        path or reader.read("path", lambda: level.level_path, "") or ""
    ).strip()
    world_name = str(
        name or reader.read("name", lambda: wrapper.level_name, "") or ""
    ).strip()
    if not world_name and level_path:
        world_name = os.path.basename(os.path.normpath(level_path))

    platform = str(reader.read("platform", lambda: wrapper.platform, "") or "")
    game_version = str(
        reader.read("game_version", lambda: wrapper.game_version_string, "") or ""
    )
    raw_version = reader.read("version", lambda: wrapper.version, None)
    if isinstance(raw_version, (tuple, list)):
        version = ".".join(str(part) for part in raw_version)
    elif raw_version is None:
        version = ""
    else:
        version = str(raw_version)
    # "Java 1.12.2" reads better than the format's internal 1343, so prefer the
    # printable form when the world offers one.
    printable_version = game_version.split(" ", 1)[-1] if " " in game_version else ""
    if printable_version:
        version = printable_version

    records = _read_dimensions(level, reader)
    names = tuple(record.name for record in records)
    chosen = str(dimension or "") or _canvas_dimension(canvas)
    if chosen not in names:
        chosen = _default_dimension(names)
    chosen_record = next((r for r in records if r.name == chosen), None)

    compound = reader.read("level_dat", lambda: _level_dat_compound(wrapper))
    if compound is None:
        reader.note("level_dat", "this world exposes no level.dat compound")

    seed = _read_seed(compound)
    if not seed:
        reader.note("seed", "the world does not record a seed in level.dat")

    spawn_x = _int(compound, "SpawnX")
    spawn_y = _int(compound, "SpawnY")
    spawn_z = _int(compound, "SpawnZ")
    spawn: Optional[Coord] = None
    if spawn_x is not None and spawn_y is not None and spawn_z is not None:
        spawn = (spawn_x, spawn_y, spawn_z)
    else:
        reader.note("spawn", "level.dat records no spawn point")

    game_mode_id = _int(compound, "GameType")
    game_mode = ""
    if game_mode_id is not None and 0 <= game_mode_id < len(GAME_MODES):
        game_mode = GAME_MODES[game_mode_id]
    elif game_mode_id is not None:
        game_mode = str(game_mode_id)
    else:
        reader.note("game_mode", "level.dat records no default game mode")

    difficulty_id = _int(compound, "Difficulty")
    difficulty = ""
    if difficulty_id is not None and 0 <= difficulty_id < len(DIFFICULTIES):
        difficulty = DIFFICULTIES[difficulty_id]
    elif difficulty_id is not None:
        difficulty = str(difficulty_id)
    else:
        reader.note("difficulty", "level.dat records no difficulty")

    total, breakdown, capped = reader.read(
        "size_on_disk", lambda: _disk_usage(level_path), (0, (), False)
    ) or (0, (), False)
    if capped:
        reader.note(
            "size_on_disk",
            f"stopped after {DISK_WALK_LIMIT:,} files; the total is a floor",
        )

    boxes = _canvas_selection(canvas)
    if boxes is None:
        boxes = ()
        if canvas is not None:
            reader.note("selection_boxes", "the viewport could not report a selection")

    generator = _read_generator(compound)
    if not generator:
        reader.note("generator", "level.dat records no world generator")

    return WorldContext(
        open=True,
        name=world_name,
        path=level_path,
        platform=platform,
        version=version,
        game_version=game_version,
        data_version=_int(compound, "DataVersion"),
        dimensions=names,
        dimension=chosen,
        dimension_info=records,
        selection_boxes=boxes,
        selection_volume=sum(box.volume for box in boxes),
        chunk_count=chosen_record.chunk_count if chosen_record else 0,
        sub_chunk_size=int(
            reader.read("sub_chunk_size", lambda: level.sub_chunk_size, 16) or 16
        ),
        size_on_disk=total,
        disk_breakdown=breakdown,
        seed=seed,
        game_rules=_read_game_rules(compound, platform),
        spawn=spawn,
        time=_int(compound, "Time", "currentTick"),
        day_time=_int(compound, "DayTime", "Time", "currentTick"),
        last_played=_read_last_played(compound),
        game_mode=game_mode,
        difficulty=difficulty,
        generator=generator,
        raining=_bool(compound, "raining", "rainLevel"),
        thundering=_bool(compound, "thundering", "lightningLevel"),
        hardcore=_bool(compound, "hardcore", "IsHardcore"),
        allow_commands=_bool(compound, "allowCommands", "commandsEnabled"),
        reasons=dict(reader.reasons),
        level=level,
    )


# ----------------------------------------------------------------------
# module state
# ----------------------------------------------------------------------

_lock = threading.RLock()
_context: WorldContext = EMPTY
_canvas: Any = None
_listeners: List[Listener] = []


def _publish(new_context: WorldContext) -> WorldContext:
    """Store ``new_context`` and tell every subscriber, guarding each one."""
    global _context
    with _lock:
        _context = new_context
        listeners = tuple(_listeners)
    for listener in listeners:
        try:
            listener(new_context)
        except Exception:  # noqa: BLE001 - one bad pane never breaks the rest
            log.exception("A world-context subscriber raised and was skipped")
    return new_context


def current() -> WorldContext:
    """Return the context for whatever world is open right now.

    When a viewport is attached, the selection and the shown dimension are
    re-read here, because both change far more often than a world opens and a
    surface asking for the context wants what is true at that moment.  The
    re-read is silent: it updates the snapshot without calling subscribers, so
    reading the context can never start a refresh loop.
    """
    global _context
    with _lock:
        snapshot_now = _context
        canvas = _canvas
    if not snapshot_now.open or canvas is None:
        return snapshot_now
    boxes = _canvas_selection(canvas)
    dimension = _canvas_dimension(canvas) or snapshot_now.dimension
    if boxes is None:
        boxes = snapshot_now.selection_boxes
    if boxes == snapshot_now.selection_boxes and dimension == snapshot_now.dimension:
        return snapshot_now
    record = snapshot_now.dimension_named(dimension)
    updated = replace(
        snapshot_now,
        selection_boxes=tuple(boxes),
        selection_volume=sum(box.volume for box in boxes),
        dimension=dimension,
        chunk_count=(
            record.chunk_count if record is not None else snapshot_now.chunk_count
        ),
    )
    with _lock:
        _context = updated
    return updated


def set_level(
    level: Any, path: str = "", name: str = "", canvas: Any = None
) -> WorldContext:
    """Record that ``level`` is the world the user is now working in.

    Called by the shell once a world has genuinely loaded.  Passing ``None``
    is the same as :func:`clear`, so a caller that reads a level out of a page
    that has already gone does not have to branch.
    """
    global _canvas
    if level is None:
        return clear()
    with _lock:
        if canvas is not None:
            _canvas = canvas
        active_canvas = _canvas
    return _publish(snapshot(level, path=path, name=name, canvas=active_canvas))


def set_canvas(canvas: Any) -> WorldContext:
    """Attach the viewport the selection and dimension are read from."""
    global _canvas
    with _lock:
        _canvas = canvas
        snapshot_now = _context
    if not snapshot_now.open:
        return snapshot_now
    boxes = _canvas_selection(canvas) or ()
    dimension = _canvas_dimension(canvas) or snapshot_now.dimension
    record = snapshot_now.dimension_named(dimension)
    return _publish(
        replace(
            snapshot_now,
            selection_boxes=boxes,
            selection_volume=sum(box.volume for box in boxes),
            dimension=dimension,
            chunk_count=(
                record.chunk_count if record is not None else snapshot_now.chunk_count
            ),
        )
    )


def set_selection(boxes: Optional[Iterable[Any]]) -> WorldContext:
    """Record the selection the user has just drawn."""
    with _lock:
        snapshot_now = _context
    coerced = _coerce_boxes(boxes)
    if not snapshot_now.open:
        return snapshot_now
    return _publish(
        replace(
            snapshot_now,
            selection_boxes=coerced,
            selection_volume=sum(box.volume for box in coerced),
        )
    )


def set_dimension(dimension: str) -> WorldContext:
    """Record which dimension the user is looking at."""
    with _lock:
        snapshot_now = _context
    name = str(dimension or "")
    if not snapshot_now.open or name == snapshot_now.dimension:
        return snapshot_now
    record = snapshot_now.dimension_named(name)
    return _publish(
        replace(
            snapshot_now,
            dimension=name,
            chunk_count=(
                record.chunk_count if record is not None else snapshot_now.chunk_count
            ),
        )
    )


def refresh() -> WorldContext:
    """Re-read every field from the level that is already open.

    Used after an edit that changes what the world says about itself -- saving
    level.dat, generating chunks, editing game rules -- so the surfaces show
    the world as it is now rather than as it was when it opened.

    A selection pushed through :func:`set_selection` survives the re-read.
    Without a viewport there is nothing to read a selection back from, and
    silently emptying one the caller had just set would look like the refresh
    had cleared the user's selection.
    """
    with _lock:
        snapshot_now = _context
        canvas = _canvas
    if not snapshot_now.open or snapshot_now.level is None:
        return snapshot_now
    fresh = snapshot(
        snapshot_now.level,
        path=snapshot_now.path,
        name=snapshot_now.name,
        canvas=canvas,
        dimension=snapshot_now.dimension,
    )
    if canvas is None and snapshot_now.selection_boxes and not fresh.selection_boxes:
        fresh = replace(
            fresh,
            selection_boxes=snapshot_now.selection_boxes,
            selection_volume=snapshot_now.selection_volume,
        )
    return _publish(fresh)


def clear() -> WorldContext:
    """Record that no world is open and drop the reference to the last one."""
    global _canvas
    with _lock:
        _canvas = None
    return _publish(EMPTY)


def subscribe(callback: Listener) -> Listener:
    """Call ``callback`` with the new context whenever the open world changes.

    Returns the callback, so it can be used as a decorator.  Subscribing twice
    registers once; a pane that re-subscribes on every rebuild does not end up
    being told four times.
    """
    if not callable(callback):
        raise TypeError("A world-context subscriber must be callable")
    with _lock:
        if callback not in _listeners:
            _listeners.append(callback)
    return callback


def unsubscribe(callback: Listener) -> None:
    """Stop telling ``callback`` about world changes; unknown ones are ignored."""
    with _lock:
        if callback in _listeners:
            _listeners.remove(callback)


def subscribers() -> Tuple[Listener, ...]:
    """Return everything currently subscribed, for tests and diagnostics."""
    with _lock:
        return tuple(_listeners)


__all__ = [
    "CHUNK_SCAN_LIMIT",
    "DIFFICULTIES",
    "DISK_WALK_LIMIT",
    "DimensionInfo",
    "DiskEntry",
    "EMPTY",
    "GAME_MODES",
    "SelectionBox",
    "WorldContext",
    "clear",
    "current",
    "refresh",
    "set_canvas",
    "set_dimension",
    "set_level",
    "set_selection",
    "snapshot",
    "subscribe",
    "subscribers",
    "unsubscribe",
]
