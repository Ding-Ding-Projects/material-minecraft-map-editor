"""The bridge between a declarative :class:`Spec` and the world that is open.

:mod:`amulet_map_editor.api.studio.spec` describes what a surface looks like;
:mod:`amulet_map_editor.api.studio.context` says what the user's world actually
contains.  This module joins them: :func:`bind` takes a surface description and
returns the same description with its sections rewritten from the live world.

A surface opts in by registering a binder::

    @register("gamerules")
    def _bind_game_rules(spec: Spec, ctx: WorldContext) -> Spec:
        ...

That registry is the extension point.  A surface with no binder is returned
untouched, so adding one surface never disturbs another, and a binder that
raises is logged and its surface falls back to the description it started with
rather than taking the window down.

Two rules apply to every binder in this module and every binder added later:

* **A value is read or it is absent.**  Where the world can answer, the section
  is rewritten with what it said.  Where it cannot -- no world open, nothing
  selected, a field this platform does not store -- the section is replaced by
  :func:`empty_section`, which states plainly that there is nothing to show and
  why.  No binder ever supplies a stand-in number.
* **A binder rewrites data, not chrome.**  Titles, widths, footer actions, and
  the surface's own prose belong to the spec.  A binder replaces the sections
  that carry records.
"""

from __future__ import annotations

import datetime
import logging
import os
import struct
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional, Tuple

from amulet_map_editor.api.studio import context
from amulet_map_editor.api.studio.context import DimensionInfo, WorldContext
from amulet_map_editor.api.studio.context import SelectionBox as StudioBox
from amulet_map_editor.api.studio.spec import (
    Check,
    Field,
    Row,
    Section,
    Select,
    Spec,
    sec,
)

log = logging.getLogger(__name__)

#: A surface binder: given the shipped description and the open world, return
#: the description the user should actually see.
Binder = Callable[[Spec, WorldContext], Spec]

#: Every registered binder, keyed by the surface key it rewrites.
BINDERS: Dict[str, Binder] = {}

#: What a surface says when there is no world to read from at all.
NO_WORLD = (
    "No world is open. Open a world from the project screen and this window "
    "will show what it contains."
)

#: What a selection-driven surface says when nothing is selected yet.
NO_SELECTION = (
    "Nothing is selected. Draw a selection box in the viewport and reopen this "
    "window to measure what is inside it."
)

#: The most chunks a histogram will read before it declines and says so, rather
#: than freezing the window on a continent-sized selection.
HISTOGRAM_CHUNK_LIMIT = 4096

#: The most block types listed individually before the tail is summarised.
HISTOGRAM_ROW_LIMIT = 40

#: The most chunks the inspector lists before it says how many more there are.
INSPECTOR_ROW_LIMIT = 400

#: Documented build ranges for the game versions a world is commonly converted
#: to.  These are facts about those versions, not about the open world; the
#: comparison against the open world is computed live and labelled as such.
CONVERSION_TARGETS: Tuple[Tuple[str, int, int], ...] = (
    ("java 1.12.2", 0, 256),
    ("java 1.17.1", 0, 256),
    ("java 1.21", -64, 320),
    ("bedrock 1.16.220", 0, 256),
    ("bedrock 1.21", -64, 320),
)


def register(key: str) -> Callable[[Binder], Binder]:
    """Register a binder for the surface named ``key``.

    Registering a second binder for a key replaces the first and says so in the
    log: two binders for one surface means one of them is silently doing
    nothing, which is a defect in the wiring rather than a preference.
    """

    def decorator(binder: Binder) -> Binder:
        if key in BINDERS:
            log.warning(
                "Studio surface %r already had a live binder; replacing it", key
            )
        BINDERS[str(key)] = binder
        return binder

    return decorator


def bound_keys() -> Tuple[str, ...]:
    """Return every surface key that currently reads from the open world."""
    return tuple(sorted(BINDERS))


def bind(spec: Optional[Spec], ctx: Optional[WorldContext] = None) -> Optional[Spec]:
    """Return ``spec`` rewritten from the world in ``ctx``.

    ``ctx`` defaults to :func:`context.current`, so an ordinary caller opening
    a surface writes ``bind(spec)``.  A surface with no binder, and a binder
    that fails, both return the original description unchanged -- a window that
    shows its shipped layout is a far better outcome than a window that does
    not open.
    """
    if spec is None:
        return None
    binder = BINDERS.get(spec.key)
    if binder is None:
        return spec
    if ctx is None:
        ctx = context.current()
    try:
        bound = binder(spec, ctx)
    except Exception:  # noqa: BLE001 - one surface never breaks the shell
        log.exception("The live binder for surface %r failed", spec.key)
        return spec
    if not isinstance(bound, Spec):
        log.error("The live binder for surface %r returned %r", spec.key, type(bound))
        return spec
    return bound


# ----------------------------------------------------------------------
# shared building blocks
# ----------------------------------------------------------------------


def empty_section(title: str, message: str) -> Section:
    """Return the honest "nothing to show, and here is why" block.

    Every surface uses this rather than an empty list, because an empty list
    reads as a surface that failed to load and this reads as a surface that
    looked and found nothing.
    """
    return sec(title, "note", hint=str(message))


def closed(spec: Spec, message: str = NO_WORLD) -> Spec:
    """Return ``spec`` reduced to a single note saying no world is open."""
    return replace(spec, sections=(empty_section(spec.title, message),))


def format_bytes(size: int) -> str:
    """Return a byte count as text a person reads, in binary units."""
    try:
        value = float(size)
    except (TypeError, ValueError):
        return ""
    if value < 1024:
        return f"{int(value)} bytes"
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        value /= 1024.0
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TiB"


def format_int(value: Optional[int]) -> str:
    """Return an integer with thousands separators, or ``""`` when absent."""
    if value is None:
        return ""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return ""


def format_timestamp(seconds: Optional[int]) -> str:
    """Return an epoch time as a local date, or ``""`` when it is not recorded."""
    if not seconds:
        return ""
    try:
        moment = datetime.datetime.fromtimestamp(int(seconds))
    except (OSError, OverflowError, TypeError, ValueError):
        return ""
    return moment.strftime("%d %b %Y, %H:%M")


def rule_type(value: str) -> str:
    """Return the kind of value a game rule holds, judged from the value itself.

    Minecraft stores every Java game rule as text, so the type is read back out
    of what the world wrote rather than from a table of rule names that would
    drift from the game.
    """
    text = str(value).strip().lower()
    if text in ("true", "false", "0b", "1b"):
        return "Boolean"
    try:
        int(text)
    except ValueError:
        return "Text"
    return "Integer"


def _plural(count: int, singular: str, plural: str = "") -> str:
    """Return ``count`` with the right noun, so a count of one still reads."""
    word = singular if abs(count) == 1 else (plural or f"{singular}s")
    return f"{format_int(count)} {word}"


def _missing_chunk_phrases(ungenerated: int, unreadable: int) -> List[str]:
    """Return the phrases naming chunks the count could not include.

    A chunk that was never generated and a chunk that failed to read are
    different facts and are reported separately, because merging them would
    hide a corrupt region behind an ordinary empty one.
    """
    phrases: List[str] = []
    if ungenerated:
        verb = "is" if ungenerated == 1 else "are"
        phrases.append(f"{format_int(ungenerated)} {verb} not generated")
    if unreadable:
        phrases.append(f"{format_int(unreadable)} could not be read")
    return phrases


def _percent(part: int, whole: int) -> str:
    """Return ``part`` of ``whole`` as a percentage, or ``""`` when undefined."""
    if not whole:
        return ""
    return f"{(part / whole) * 100:.1f}%"


def _dimension_range(info: Optional[DimensionInfo]) -> str:
    """Return a dimension's build range as text, or an honest absence."""
    if info is None or not info.has_range:
        return "range not reported"
    return f"{info.min_y} to {info.max_y}"


def _platform_label(ctx: WorldContext) -> str:
    """Return "platform version" for the open world, however much it reported."""
    parts = [part for part in (ctx.platform, ctx.version) if part]
    return " ".join(parts) if parts else "platform not reported"


def _sections(spec: Spec, *sections: Optional[Section]) -> Spec:
    """Return ``spec`` carrying exactly ``sections``, dropping any that are None."""
    return replace(spec, sections=tuple(s for s in sections if s is not None))


def _source_note(ctx: WorldContext, detail: str) -> Section:
    """Return the trailing note naming where the values above were read from."""
    where = ctx.path or ctx.name or "the open world"
    return sec("", "note", hint=f"{detail} Read from {where}.")


# ----------------------------------------------------------------------
# level.dat
# ----------------------------------------------------------------------


@register("levelDat")
def _bind_level_dat(spec: Spec, ctx: WorldContext) -> Spec:
    """Show the world's own level.dat fields, and only the ones it stores."""
    if not ctx.open:
        return closed(spec)

    absent = "not stored in this level.dat"
    spawn = ctx.spawn
    fields = [
        Field(label="Level name", value=ctx.name, placeholder=absent),
        Field(label="Seed", value=ctx.seed, placeholder=absent),
        Field(
            label="Spawn x",
            value="" if spawn is None else str(spawn[0]),
            placeholder=absent,
        ),
        Field(
            label="Spawn y",
            value="" if spawn is None else str(spawn[1]),
            placeholder=absent,
        ),
        Field(
            label="Spawn z",
            value="" if spawn is None else str(spawn[2]),
            placeholder=absent,
        ),
        Field(
            label="Time",
            value="" if ctx.time is None else str(ctx.time),
            placeholder=absent,
        ),
    ]

    selects: List[Select] = []
    if ctx.game_mode:
        selects.append(
            Select(
                label="Default game mode",
                options=context.GAME_MODES,
                value=ctx.game_mode,
            )
        )
    if ctx.difficulty:
        selects.append(
            Select(
                label="Difficulty",
                options=context.DIFFICULTIES,
                value=ctx.difficulty,
            )
        )
    if ctx.generator:
        options = (ctx.generator,) + tuple(
            name
            for name in ("default", "flat", "largeBiomes", "amplified", "customized")
            if name != ctx.generator
        )
        selects.append(Select(label="Generator", options=options, value=ctx.generator))
    if ctx.weather:
        selects.append(
            Select(
                label="Weather",
                options=("clear", "rain", "thunder"),
                value=ctx.weather,
            )
        )
    rules_section: Section
    if selects:
        rules_section = sec("Rules", "selects", selects=selects)
    else:
        rules_section = empty_section(
            "Rules",
            "This level.dat records no game mode, difficulty, generator, or "
            "weather, so there is nothing here to change.",
        )

    checks: List[Check] = []
    if ctx.allow_commands is not None:
        checks.append(
            Check(
                label="Allow commands",
                hint="Enables cheats in single player.",
                value=bool(ctx.allow_commands),
            )
        )
    if ctx.hardcore is not None:
        checks.append(
            Check(
                label="Hardcore",
                hint="Death locks the world to spectator.",
                value=bool(ctx.hardcore),
            )
        )
    if ctx.raining is not None:
        checks.append(
            Check(
                label="Raining",
                hint="The weather state stored in the file.",
                value=bool(ctx.raining),
            )
        )
    if ctx.thundering is not None:
        checks.append(
            Check(
                label="Thundering",
                hint="Set alongside rain during a storm.",
                value=bool(ctx.thundering),
            )
        )
    flags_section: Section
    if checks:
        flags_section = sec("Flags", "checks", checks=checks)
    else:
        flags_section = empty_section(
            "Flags", "This level.dat records none of the flags this window edits."
        )

    version = ctx.game_version or _platform_label(ctx)
    return _sections(
        spec,
        sec("World", "fields", fields=fields),
        rules_section,
        flags_section,
        _source_note(ctx, f"{version}."),
    )


# ----------------------------------------------------------------------
# game rules
# ----------------------------------------------------------------------


@register("gamerules")
def _bind_game_rules(spec: Spec, ctx: WorldContext) -> Spec:
    """List the rules this world stores, with the values it stores for them."""
    if not ctx.open:
        return closed(spec)
    search = sec("", "search", hint="Search game rules")
    if not ctx.game_rules:
        reason = ctx.reason("level_dat")
        detail = f" ({reason})" if reason else ""
        return _sections(
            spec,
            search,
            empty_section(
                "Rules",
                f"This world stores no game rules in its level.dat{detail}. "
                "A rule the file does not contain is not shown with a default.",
            ),
        )
    rows = [
        Row(
            name=name,
            detail=rule_type(value),
            tag=str(value),
        )
        for name, value in sorted(ctx.game_rules.items(), key=lambda item: item[0])
    ]
    return _sections(
        spec,
        search,
        sec("Rules", "list", rows=rows),
        _source_note(
            ctx,
            f"{len(rows)} rules stored by this world. Rules its platform does "
            "not store are absent rather than shown with a default.",
        ),
    )


# ----------------------------------------------------------------------
# world information
# ----------------------------------------------------------------------


@register("worldInfo")
def _bind_world_info(spec: Spec, ctx: WorldContext) -> Spec:
    """Show identity, size on disk, dimensions, time, and spawn, all as read."""
    if not ctx.open:
        return closed(spec)

    identity = [
        Row("World name", ctx.name or "not recorded", "level.dat"),
        Row("Folder", ctx.path or "not recorded", "path"),
        Row("Platform", _platform_label(ctx), "format"),
    ]
    if ctx.game_version:
        identity.append(Row("Game version", ctx.game_version, "version"))
    if ctx.data_version is not None:
        identity.append(Row("Data version", str(ctx.data_version), "version"))
    identity.append(
        Row("Seed", ctx.seed or ctx.reason("seed") or "not recorded", "seed")
    )
    last_played = format_timestamp(ctx.last_played)
    identity.append(Row("Last played", last_played or "not recorded", "time"))

    disk_rows = [
        Row(
            entry.label,
            (
                f"{format_int(entry.files)} files · {format_bytes(entry.size)}"
                if entry.files != 1
                else format_bytes(entry.size)
            ),
            "on disk",
        )
        for entry in ctx.disk_breakdown
    ]
    disk_section: Section
    if disk_rows:
        disk_rows.append(Row("Total", format_bytes(ctx.size_on_disk), "on disk"))
        disk_section = sec("Size on disk", "list", rows=disk_rows)
    else:
        disk_section = empty_section(
            "Size on disk",
            ctx.reason("size_on_disk")
            or "The world folder could not be read, so its size is unknown.",
        )

    dimension_rows = []
    for info in ctx.dimension_info:
        chunks = (
            f"{format_int(info.chunk_count)} chunks" + ("+" if info.truncated else "")
            if info.counted
            else "chunk count unavailable"
        )
        dimension_rows.append(
            Row(info.name, f"y {_dimension_range(info)} · {chunks}", "dimension")
        )
    dimensions_section: Section
    if dimension_rows:
        dimensions_section = sec("Dimensions", "list", rows=dimension_rows)
    else:
        dimensions_section = empty_section(
            "Dimensions", "This world reports no dimensions."
        )

    selects: List[Select] = []
    if ctx.day_time is not None:
        tick = int(ctx.day_time) % 24000
        selects.append(
            Select(
                label="Time of day",
                options=(
                    f"Tick {tick}",
                    "Dawn (0)",
                    "Noon (6000)",
                    "Dusk (12000)",
                    "Midnight (18000)",
                ),
                value=f"Tick {tick}",
            )
        )
    if ctx.weather:
        selects.append(
            Select(
                label="Weather",
                options=("clear", "rain", "thunder"),
                value=ctx.weather,
            )
        )
    if ctx.difficulty:
        selects.append(
            Select(
                label="Difficulty",
                options=context.DIFFICULTIES,
                value=ctx.difficulty,
            )
        )
    weather_section: Section
    if selects:
        weather_section = sec("Time and weather", "selects", selects=selects)
    else:
        weather_section = empty_section(
            "Time and weather", "This world records no time, weather, or difficulty."
        )

    spawn_section: Section
    if ctx.spawn is None:
        spawn_section = empty_section(
            "Spawn", ctx.reason("spawn") or "This world records no spawn point."
        )
    else:
        spawn_section = sec(
            "Spawn",
            "fields",
            fields=[
                Field(label="Spawn x", value=str(ctx.spawn[0])),
                Field(label="Spawn y", value=str(ctx.spawn[1])),
                Field(label="Spawn z", value=str(ctx.spawn[2])),
            ],
        )

    return _sections(
        spec,
        sec("", "search", hint="Search world properties"),
        sec("Identity", "list", rows=identity),
        disk_section,
        dimensions_section,
        weather_section,
        spawn_section,
    )


# ----------------------------------------------------------------------
# height limits
# ----------------------------------------------------------------------


@register("heightLimits")
def _bind_height_limits(spec: Spec, ctx: WorldContext) -> Spec:
    """Show the build range of each dimension, and what a conversion would clip."""
    if not ctx.open:
        return closed(spec)

    platform = _platform_label(ctx)
    current_rows = [
        Row(info.name, platform, _dimension_range(info)) for info in ctx.dimension_info
    ]
    current_section: Section
    if current_rows:
        current_section = sec("Current world", "list", rows=current_rows)
    else:
        current_section = empty_section(
            "Current world", "This world reports no dimensions to take a range from."
        )

    ranged = [info for info in ctx.dimension_info if info.has_range]
    target_section: Section
    if not ranged:
        target_section = empty_section(
            "Conversion targets",
            "No dimension reported a build range, so there is nothing to "
            "compare a conversion target against.",
        )
    else:
        world_min = min(int(info.min_y) for info in ranged)
        world_max = max(int(info.max_y) for info in ranged)
        target_rows = []
        for name, low, high in CONVERSION_TARGETS:
            clipped = []
            if world_min < low:
                clipped.append(f"below y {low}")
            if world_max > high:
                clipped.append(f"at or above y {high}")
            if clipped:
                detail = "Would discard blocks " + " and ".join(clipped)
            else:
                detail = f"Holds this world's whole {world_min} to {world_max} range"
            target_rows.append(Row(name, detail, f"{low} to {high}"))
        target_section = sec("Conversion targets", "list", rows=target_rows)

    return _sections(
        spec,
        current_section,
        target_section,
        sec(
            "",
            "note",
            hint=(
                "The current ranges are read from the open world. The target "
                "ranges are the documented build limits of those game versions, "
                "and the verdict beside each one is computed against this world."
            ),
        ),
    )


# ----------------------------------------------------------------------
# block histogram
# ----------------------------------------------------------------------


def _block_namer(ctx: WorldContext) -> Callable[[Any], Tuple[str, str]]:
    """Return a function naming a universal block in the world's own version.

    Amulet stores every chunk in its own universal palette, so the raw palette
    entry is a name the user has never seen in the game.  Translating it back
    to the version the world is actually saved in is what makes the histogram
    read like the world rather than like the editor's internals.  A block that
    will not translate keeps its universal name and says so.
    """
    translator = None
    try:
        platform, version = ctx.level.level_wrapper.max_world_version
        translator = ctx.level.translation_manager.get_version(platform, version).block
    except Exception as err:  # noqa: BLE001 - a world with no translator is fine
        log.debug("Studio histogram has no block translator: %s", err)

    cache: Dict[Any, Tuple[str, str]] = {}

    def name_of(block: Any) -> Tuple[str, str]:
        key = getattr(block, "full_blockstate", None) or str(block)
        cached = cache.get(key)
        if cached is not None:
            return cached
        namespaced = str(getattr(block, "namespaced_name", key))
        detail = "universal palette entry"
        if translator is not None:
            try:
                converted = translator.from_universal(block)[0]
                namespaced = str(
                    getattr(converted, "namespaced_name", None) or converted
                )
                detail = str(getattr(converted, "full_blockstate", None) or namespaced)
            except Exception:  # noqa: BLE001 - a block this version lacks
                detail = f"{key} · no equivalent in this version"
        cache[key] = (namespaced, detail)
        return cache[key]

    return name_of


def _clip_to_dimension(
    ctx: WorldContext,
) -> Tuple[Tuple[StudioBox, ...], bool]:
    """Return the selection clipped to the dimension's build range.

    The second value says whether any clipping happened, so a surface can tell
    the user that part of what they selected is outside the world rather than
    quietly counting it.  A dimension that reports no range clips nothing.
    """
    info = ctx.current_dimension()
    if info is None or not info.has_range:
        return ctx.selection_boxes, False
    low, high = int(info.min_y), int(info.max_y)
    kept: List[StudioBox] = []
    clipped = False
    for box in ctx.selection_boxes:
        min_y = max(box.min[1], low)
        max_y = min(box.max[1], high)
        if min_y != box.min[1] or max_y != box.max[1]:
            clipped = True
        if max_y <= min_y:
            continue
        kept.append(
            StudioBox(
                min=(box.min[0], min_y, box.min[2]),
                max=(box.max[0], max_y, box.max[2]),
            )
        )
    return tuple(kept), clipped


def _boxes_chunks(
    boxes: Tuple[StudioBox, ...], sub_chunk_size: int
) -> Tuple[Tuple[int, int], ...]:
    """Return every chunk column ``boxes`` touch, each one once."""
    seen: List[Tuple[int, int]] = []
    found = set()
    for box in boxes:
        for coord in box.chunk_coords(sub_chunk_size):
            if coord not in found:
                found.add(coord)
                seen.append(coord)
    return tuple(seen)


@register("blockHistogram")
def _bind_block_histogram(spec: Spec, ctx: WorldContext) -> Spec:
    """Count every block inside the current selection, by reading the chunks."""
    if not ctx.open or ctx.level is None:
        return closed(spec)
    if not ctx.has_selection:
        return _sections(spec, empty_section("Selection", NO_SELECTION))

    # A selection may reach above or below the dimension's build range, where
    # there is no block at all.  Counting that emptiness as air would say the
    # world contains something it does not, so the box is clipped first and the
    # clip is reported rather than folded silently into the totals.
    boxes, clipped = _clip_to_dimension(ctx)
    if not boxes:
        info = ctx.current_dimension()
        return _sections(
            spec,
            empty_section(
                "Selection",
                f"The selection lies entirely outside the build range of "
                f"{ctx.dimension} (y {_dimension_range(info)}), so there are no "
                "blocks inside it to count.",
            ),
        )

    touched = _boxes_chunks(boxes, ctx.sub_chunk_size)
    if len(touched) > HISTOGRAM_CHUNK_LIMIT:
        return _sections(
            spec,
            empty_section(
                "Selection",
                f"The selection covers {format_int(len(touched))} chunks, more "
                f"than the {format_int(HISTOGRAM_CHUNK_LIMIT)} this window "
                "reads at once. Select a smaller region and it will be counted "
                "exactly rather than estimated.",
            ),
        )

    import numpy
    from amulet.api.selection import SelectionBox as AmuletBox
    from amulet.api.selection import SelectionGroup

    group = SelectionGroup([AmuletBox(box.min, box.max) for box in boxes])
    name_of = _block_namer(ctx)
    counts: Dict[str, int] = {}
    details: Dict[str, str] = {}
    counted_blocks = 0
    ungenerated = 0
    unreadable = 0

    for coord in touched:
        cx, cz = coord
        try:
            chunk = ctx.level.get_chunk(cx, cz, ctx.dimension)
        except Exception as err:  # noqa: BLE001 - missing and broken both land here
            if type(err).__name__ == "ChunkDoesNotExist":
                ungenerated += 1
            else:
                unreadable += 1
            continue
        for box in group.selection_boxes:
            chunk_box = box.intersection(
                AmuletBox(
                    (cx * ctx.sub_chunk_size, box.min_y, cz * ctx.sub_chunk_size),
                    (
                        (cx + 1) * ctx.sub_chunk_size,
                        box.max_y,
                        (cz + 1) * ctx.sub_chunk_size,
                    ),
                )
            )
            if not chunk_box.volume:
                continue
            slices = chunk_box.chunk_slice(cx, cz, ctx.sub_chunk_size)
            array = numpy.asarray(chunk.blocks[slices])
            ids, occurrences = numpy.unique(array, return_counts=True)
            for runtime_id, occurrence in zip(ids.tolist(), occurrences.tolist()):
                try:
                    block = chunk.block_palette[runtime_id]
                except Exception:  # noqa: BLE001 - a palette gap is not fatal
                    continue
                name, detail = name_of(block)
                counts[name] = counts.get(name, 0) + occurrence
                details.setdefault(name, detail)
                counted_blocks += occurrence

    if not counts:
        missing = _missing_chunk_phrases(ungenerated, unreadable)
        why = (
            f"None of the {_plural(len(touched), 'chunk')} the selection "
            "covers held any blocks to count"
        )
        if missing:
            why += ": " + " and ".join(missing)
        return _sections(spec, empty_section("Selection", why + "."))

    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    rows = [
        Row(
            name="Total blocks",
            detail=f"{format_int(counted_blocks)} blocks read from "
            f"{_plural(len(touched) - ungenerated - unreadable, 'chunk')}",
            tag="100%",
        )
    ]
    for name, count in ordered[:HISTOGRAM_ROW_LIMIT]:
        rows.append(
            Row(
                name=name,
                detail=f"{format_int(count)} blocks · {details.get(name, '')}".strip(
                    " ·"
                ),
                tag=_percent(count, counted_blocks),
            )
        )
    remainder = ordered[HISTOGRAM_ROW_LIMIT:]
    if remainder:
        rows.append(
            Row(
                name=f"{format_int(len(remainder))} more block types",
                detail=f"{format_int(sum(count for _n, count in remainder))} blocks",
                tag=_percent(sum(count for _n, count in remainder), counted_blocks),
            )
        )

    air = sum(count for name, count in counts.items() if name.endswith(":air"))
    non_air = counted_blocks - air
    sections: List[Section] = [
        sec("Selection", "list", rows=rows),
        sec(
            "Distribution",
            "progress",
            hint="Non-air fill",
            progress_label=_percent(non_air, counted_blocks) or "0.0%",
            progress_fraction=(non_air / counted_blocks) if counted_blocks else 0.0,
        ),
    ]
    remarks: List[str] = []
    if ungenerated or unreadable:
        remarks.append(
            "Of the chunks the selection covers, "
            + " and ".join(_missing_chunk_phrases(ungenerated, unreadable))
            + ". They contribute nothing to the counts above rather than being "
            "counted as air."
        )
    if clipped:
        info = ctx.current_dimension()
        remarks.append(
            f"The selection reaches outside the build range of {ctx.dimension} "
            f"(y {_dimension_range(info)}); only the part inside it was counted."
        )
    if remarks:
        sections.append(sec("", "note", hint=" ".join(remarks)))
    return _sections(spec, *sections)


# ----------------------------------------------------------------------
# chunk inspector
# ----------------------------------------------------------------------


def _region_directory(ctx: WorldContext, dimension: str) -> str:
    """Return the region folder for ``dimension``, or ``""`` when there is none.

    The level's own dimension manager knows this, but it keeps it privately, so
    the private route is tried first and the documented Anvil folder layout is
    the fallback.  A world with neither -- Bedrock, a structure file -- gets an
    empty string and the caller lists chunks without sizes.
    """
    wrapper = getattr(ctx.level, "level_wrapper", None)
    try:
        internal = wrapper._dimension_name_map[dimension]
        manager = wrapper._levels[internal]
        directory = manager._layers["region"]._directory
        if os.path.isdir(directory):
            return str(directory)
    except Exception:  # noqa: BLE001 - a private route that moved is not fatal
        pass
    root = ctx.path
    if not root:
        return ""
    candidates = {
        "minecraft:overworld": os.path.join(root, "region"),
        "minecraft:the_nether": os.path.join(root, "DIM-1", "region"),
        "minecraft:the_end": os.path.join(root, "DIM1", "region"),
    }
    guess = candidates.get(dimension)
    if guess and os.path.isdir(guess):
        return guess
    if ":" in dimension:
        namespace, _, name = dimension.partition(":")
        custom = os.path.join(root, "dimensions", namespace, name, "region")
        if os.path.isdir(custom):
            return custom
    return ""


def _region_index(directory: str) -> Dict[Tuple[int, int], Tuple[int, int]]:
    """Return each stored chunk's byte length and save time from region headers.

    An Anvil region file begins with a 4 KiB location table -- 1024 entries of a
    three-byte sector offset and a one-byte sector count -- followed by a 4 KiB
    table of save timestamps.  Reading those 8 KiB gives a real size and a real
    date for every chunk in the file without decompressing any of them.
    """
    index: Dict[Tuple[int, int], Tuple[int, int]] = {}
    if not directory or not os.path.isdir(directory):
        return index
    for filename in sorted(os.listdir(directory)):
        if not filename.startswith("r.") or not filename.endswith(".mca"):
            continue
        parts = filename.split(".")
        if len(parts) != 4:
            continue
        try:
            region_x, region_z = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        try:
            with open(os.path.join(directory, filename), "rb") as handle:
                header = handle.read(8192)
        except OSError:
            continue
        if len(header) < 8192:
            continue
        locations = struct.unpack(">1024I", header[:4096])
        timestamps = struct.unpack(">1024I", header[4096:8192])
        for entry, (packed, saved) in enumerate(zip(locations, timestamps)):
            sectors = packed & 0xFF
            offset = packed >> 8
            if not offset or not sectors:
                continue
            cx = region_x * 32 + (entry % 32)
            cz = region_z * 32 + (entry // 32)
            index[(cx, cz)] = (sectors * 4096, saved)
    return index


@register("chunkInspector")
def _bind_chunk_inspector(spec: Spec, ctx: WorldContext) -> Spec:
    """List the chunks this dimension actually stores, with their real sizes."""
    if not ctx.open or ctx.level is None:
        return closed(spec)
    search = sec("", "search", hint="Search by chunk coordinate or status")

    info = ctx.current_dimension()
    if info is not None and not info.counted:
        why = ctx.reason(f"chunks:{ctx.dimension}") or "its region data is unreadable"
        return _sections(
            spec,
            search,
            empty_section(
                "Chunks",
                f"The chunk list for {ctx.dimension} could not be read: {why}.",
            ),
        )

    try:
        coords = sorted(set(ctx.level.all_chunk_coords(ctx.dimension)))
    except Exception as err:  # noqa: BLE001 - report it rather than showing a list
        return _sections(
            spec,
            search,
            empty_section(
                "Chunks",
                f"The chunk list for {ctx.dimension} could not be read: "
                f"{type(err).__name__}: {err}.",
            ),
        )

    if not coords:
        return _sections(
            spec,
            search,
            empty_section(
                "Chunks",
                f"{ctx.dimension} has no generated chunks in this world. "
                "Nothing has been written to its region files yet.",
            ),
        )

    index = _region_index(_region_directory(ctx, ctx.dimension))
    rows = []
    for cx, cz in coords[:INSPECTOR_ROW_LIMIT]:
        region = f"r.{cx >> 5}.{cz >> 5}"
        stored = index.get((cx, cz))
        if stored is None:
            detail = "stored · size not readable from the region header"
        else:
            size, saved = stored
            when = format_timestamp(saved)
            detail = f"{format_bytes(size)} allocated"
            if when:
                detail += f" · saved {when}"
        rows.append(
            Row(name=f"{region} · chunk {cx}, {cz}", detail=detail, tag="stored")
        )

    sections: List[Section] = [search, sec("Chunks", "list", rows=rows)]
    remainder = len(coords) - len(rows)
    trailing = (
        f"{format_int(len(coords))} chunks are stored in {ctx.dimension}. "
        "A chunk is listed because its region file records it; reading one can "
        "still fail, and Validate and repair decides what happens then."
    )
    if remainder > 0:
        trailing = (
            f"Showing the first {format_int(len(rows))} of "
            f"{format_int(len(coords))} chunks in {ctx.dimension}. " + trailing
        )
    sections.append(sec("", "note", hint=trailing))
    return _sections(spec, *sections)


# ----------------------------------------------------------------------
# measure
# ----------------------------------------------------------------------


@register("measure")
def _bind_measure(spec: Spec, ctx: WorldContext) -> Spec:
    """Report the real dimensions of whatever is selected right now."""
    if not ctx.open:
        return closed(spec)
    bounds = ctx.selection_bounds()
    if not ctx.has_selection or bounds is None:
        return _sections(spec, empty_section("Readouts", NO_SELECTION))

    low, high = bounds
    size = (high[0] - low[0], high[1] - low[1], high[2] - low[2])
    diagonal = (size[0] ** 2 + size[1] ** 2 + size[2] ** 2) ** 0.5
    chunks = ctx.selection_chunks()
    chunk_x = {coord[0] for coord in chunks}
    chunk_z = {coord[1] for coord in chunks}

    rows = [
        Row(
            name="Point to point",
            detail=f"{low[0]}, {low[1]}, {low[2]} to {high[0]}, {high[1]}, {high[2]}",
            tag=f"{diagonal:.1f} blocks",
        ),
        Row(
            name="Bounding volume",
            detail=f"{size[0]} × {size[1]} × {size[2]}",
            tag=f"{format_int(size[0] * size[1] * size[2])} blocks",
        ),
        Row(
            name="Footprint",
            detail=f"{size[0]} × {size[2]}",
            tag=f"{format_int(size[0] * size[2])} blocks",
        ),
        Row(
            name="Chunks touched",
            detail=f"{len(chunk_x)} × {len(chunk_z)} grid",
            tag=f"{format_int(len(chunks))} chunks",
        ),
    ]
    if len(ctx.selection_boxes) > 1:
        rows.append(
            Row(
                name="Selected volume",
                detail=f"{len(ctx.selection_boxes)} boxes, "
                "summed box by box rather than as one bounding volume",
                tag=f"{format_int(ctx.selection_volume)} blocks",
            )
        )

    return _sections(
        spec,
        sec("Readouts", "list", rows=rows),
        sec(
            "Units",
            "selects",
            selects=[
                Select(label="Distance", options=("Blocks", "Chunks", "Regions")),
                Select(
                    label="Anchor",
                    options=("Box corners", "Box centres", "Camera to cursor"),
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                f"Measured in {ctx.dimension or 'the open dimension'} from the "
                "selection currently drawn in the viewport."
            ),
        ),
    )


__all__ = [
    "BINDERS",
    "Binder",
    "CONVERSION_TARGETS",
    "HISTOGRAM_CHUNK_LIMIT",
    "HISTOGRAM_ROW_LIMIT",
    "INSPECTOR_ROW_LIMIT",
    "NO_SELECTION",
    "NO_WORLD",
    "bind",
    "bound_keys",
    "closed",
    "empty_section",
    "format_bytes",
    "format_int",
    "format_timestamp",
    "register",
    "rule_type",
]
