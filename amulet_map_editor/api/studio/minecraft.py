"""What the installed Minecraft libraries actually support, read rather than assumed.

Amulet Studio has to answer three kinds of question before it can show a
version-dependent surface: which platforms and versions can be read at all,
what the build range of a dimension is on one of them, and whether a block or
a feature exists there.  All three have the same failure mode if they are
written as constants -- the answers go stale the moment ``amulet-core`` or
``PyMCTranslate`` is updated, and the editor keeps offering a version list that
no longer matches the data underneath it.

So nothing here carries a version list.  The platforms and versions come from
the installed ``PyMCTranslate`` translation manager, the classic build range
comes from ``amulet-core``'s own default world bounds, and a feature is decided
by asking the installed block data whether its blocks exist in a given version.
Update the libraries and the editor gains the new versions with no code change.

When a library is missing or a version cannot be resolved, every function here
degrades to an empty answer rather than a plausible-looking one, and
:func:`support_report` says in one sentence exactly what is and is not
available.  A surface that shows any of this is expected to show that sentence
too, so a reader never has to guess whether a short list means "old Minecraft"
or "the library did not load".
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import (
    Any,
    Dict,
    FrozenSet,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Tuple,
)

log = logging.getLogger(__name__)

#: A Minecraft version as the translation manager reports it, e.g. ``(1, 21, 9)``.
Version = Tuple[int, ...]

# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------

OVERWORLD = "overworld"
THE_NETHER = "the_nether"
THE_END = "the_end"

#: The three dimensions every vanilla world has.  A data pack may add more, and
#: :func:`normalise_dimension` deliberately does not pretend to recognise them.
DIMENSIONS: Tuple[str, ...] = (OVERWORLD, THE_NETHER, THE_END)

#: Spellings a caller may reasonably hand us for the vanilla three.  Anything
#: outside this map is treated as a custom dimension and reported as such.
_DIMENSION_ALIASES: Dict[str, str] = {
    "overworld": OVERWORLD,
    "minecraft:overworld": OVERWORLD,
    "dim0": OVERWORLD,
    "the_nether": THE_NETHER,
    "nether": THE_NETHER,
    "minecraft:the_nether": THE_NETHER,
    "dim-1": THE_NETHER,
    "the_end": THE_END,
    "end": THE_END,
    "minecraft:the_end": THE_END,
    "dim1": THE_END,
}

#: The platforms a user actually edits a world in.  ``PyMCTranslate`` also
#: reports ``universal``, which is its intermediate format rather than a thing
#: anybody opens, so surfaces that offer a choice use this tuple and
#: :func:`supported_platforms` still reports everything that is installed.
EDITABLE_PLATFORMS: Tuple[str, ...] = ("java", "bedrock")

# ---------------------------------------------------------------------------
# Build ranges
#
# The numbers below are dimension geometry, not a version list: they mirror the
# thresholds ``amulet-core``'s own format wrappers switch on, so this module and
# a loaded world cannot disagree about where a build range changes.  Which side
# of a threshold a version falls on is read from the installed data every time.
# ---------------------------------------------------------------------------

#: Used only when ``amulet-core`` cannot be imported to supply its own default.
_FALLBACK_CLASSIC_RANGE: Tuple[int, int] = (0, 256)

#: The overworld range the 1.18 height change introduced.
_EXTENDED_OVERWORLD_RANGE: Tuple[int, int] = (-64, 320)

#: The nether has been a 128-block slab on every platform and every version.
_NETHER_RANGE: Tuple[int, int] = (0, 128)

#: Java switches the overworld bounds at this data version, exactly as the anvil
#: format wrapper does.  The data version of a release is read from the
#: installed translation data rather than assumed from its version number.
_JAVA_HEIGHT_CHANGE_DATA_VERSION = 2825

#: Bedrock's level format switches on the release version instead.
_BEDROCK_HEIGHT_CHANGE_VERSION: Version = (1, 18)


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Feature:
    """A named slice of modern Minecraft, decided by blocks that came with it.

    ``blocks`` are base names inside the ``minecraft`` namespace.  A feature is
    present in a version when the installed block data carries *every* one of
    them, which is a question the data can answer; "which update shipped this"
    is not, so it is never asked.
    """

    name: str
    label: str
    blocks: Tuple[str, ...]


def _feature(name: str, label: str, *blocks: str) -> Feature:
    return Feature(name=name, label=label, blocks=tuple(blocks))


#: Every feature a surface may gate on.  A name that is not here answers
#: ``False`` and logs once, so a typo in a gate shows up in the log rather than
#: quietly hiding a whole section forever.
FEATURES: Dict[str, Feature] = {
    feature.name: feature
    for feature in (
        _feature(
            "caves_and_cliffs",
            "deepslate, amethyst, and the extended build range",
            "deepslate",
            "calcite",
            "amethyst_block",
            "pointed_dripstone",
        ),
        _feature(
            "copper",
            "copper and its oxidation states",
            "copper_block",
            "oxidized_copper",
            "waxed_oxidized_copper",
        ),
        _feature(
            "deep_dark",
            "the deep dark and the sculk family",
            "sculk",
            "sculk_catalyst",
            "sculk_shrieker",
            "reinforced_deepslate",
        ),
        _feature(
            "mangrove_swamp",
            "mangrove and mud",
            "mangrove_planks",
            "mud",
            "packed_mud",
            "mud_bricks",
        ),
        _feature(
            "froglights",
            "froglights",
            "ochre_froglight",
            "verdant_froglight",
            "pearlescent_froglight",
        ),
        _feature(
            "bamboo_wood",
            "the bamboo wood set",
            "bamboo_planks",
            "bamboo_mosaic",
        ),
        _feature(
            "cherry_grove",
            "the cherry wood set",
            "cherry_planks",
            "cherry_log",
        ),
        _feature(
            "archaeology",
            "suspicious blocks and decorated pots",
            "suspicious_sand",
            "suspicious_gravel",
        ),
        _feature(
            "tuff_family",
            "the tuff building set",
            "tuff_bricks",
            "polished_tuff",
            "chiseled_tuff",
        ),
        _feature(
            "copper_building",
            "the copper building set",
            "chiseled_copper",
            "copper_grate",
            "copper_door",
        ),
        _feature("copper_bulb", "the copper bulb", "copper_bulb"),
        _feature("crafter", "the crafter", "crafter"),
        _feature(
            "trial_chambers",
            "trial chambers",
            "trial_spawner",
            "vault",
            "heavy_core",
        ),
        _feature(
            "pale_garden",
            "the pale garden and the creaking",
            "pale_oak_planks",
            "pale_moss_block",
            "creaking_heart",
        ),
        _feature("resin", "resin", "resin_block", "resin_bricks"),
        _feature("happy_ghast", "the happy ghast", "dried_ghast"),
        _feature(
            "copper_golem",
            "the copper golem and copper storage",
            "copper_golem_statue",
            "copper_chest",
            "copper_torch",
        ),
    )
}

#: Every gate name, sorted, so a test can assert the set rather than a sample.
FEATURE_NAMES: Tuple[str, ...] = tuple(sorted(FEATURES))


# ---------------------------------------------------------------------------
# Library discovery
# ---------------------------------------------------------------------------

_manager: Optional[Any] = None
_manager_loaded = False
_manager_error = ""

_translate_build = ""
_amulet_version = ""

_base_name_cache: Dict[Tuple[str, Version], FrozenSet[str]] = {}
_feature_since_cache: Dict[Tuple[str, str], Version] = {}
_unknown_features: set = set()
_entity_registry: Optional[bool] = None


@contextmanager
def _contained_logging() -> Iterator[None]:
    """Stop a third-party import from reconfiguring this application's logging.

    ``PyMCTranslate`` calls :func:`logging.basicConfig` as it is imported, which
    installs a stderr handler on the root logger and forces the whole
    application's level to ``INFO`` -- merely because a data module somewhere
    asked it a question.  Attaching a handler first makes that call a no-op,
    since ``basicConfig`` returns early when the root logger already has one,
    and removing it afterwards leaves the host's own configuration exactly as it
    was found.

    Nothing is hidden from an application that logs: its handlers still receive
    every record the library emits, because a null handler does not stop
    propagation.  The only case this quietens is the one where nothing was
    listening and the library would have written to stderr on its own
    initiative -- importing the surface registry as data, which has to stay
    silent.  What the library had to say about itself is reported in words by
    :func:`support_report` instead, on the surfaces that depend on it.
    """
    root = logging.getLogger()
    had_handlers = bool(root.handlers)
    level = root.level
    guard = logging.NullHandler()
    root.addHandler(guard)
    try:
        yield
    finally:
        root.removeHandler(guard)
        if not had_handlers and root.handlers:
            # Nothing was configured before, so whatever is attached now was
            # installed by the library rather than chosen by the application.
            for handler in list(root.handlers):
                root.removeHandler(handler)
            root.setLevel(level)


def translation_manager() -> Optional[Any]:
    """Return the installed translation manager, or ``None`` when there is none.

    The import is deferred and the result cached, so importing this module
    costs nothing and a missing library is discovered once rather than on every
    question.  The failure is kept in :func:`unavailable_reason` instead of
    being raised, because every caller here has an honest empty answer to give
    and none of them can fix a missing dependency.
    """
    global _manager, _manager_loaded, _manager_error, _translate_build
    if _manager_loaded:
        return _manager
    _manager_loaded = True
    with _contained_logging():
        try:
            import PyMCTranslate  # type: ignore
        except Exception as err:  # pragma: no cover - depends on the environment
            _manager_error = f"PyMCTranslate is not installed ({err})"
            log.warning("Studio version support: %s", _manager_error)
            return None
        _translate_build = str(getattr(PyMCTranslate, "build_number", "") or "")
        try:
            _manager = PyMCTranslate.new_translation_manager()
        except Exception as err:  # pragma: no cover - depends on the environment
            _manager = None
            _manager_error = (
                f"PyMCTranslate could not build a translation manager ({err})"
            )
            log.exception("Studio version support: %s", _manager_error)
    return _manager


def _core_version() -> str:
    """Return the installed ``amulet-core`` version string, or an empty string."""
    global _amulet_version
    if _amulet_version:
        return _amulet_version
    with _contained_logging():
        try:
            import amulet  # type: ignore
        except Exception:  # pragma: no cover - depends on the environment
            return ""
    _amulet_version = str(getattr(amulet, "__version__", "") or "")
    return _amulet_version


def unavailable_reason() -> str:
    """Return why version data is unavailable, or an empty string when it is not."""
    translation_manager()
    return _manager_error


def classic_range() -> Tuple[int, int]:
    """Return the pre-1.18 build range, read from ``amulet-core``'s own default.

    Reading it rather than writing ``0`` and ``256`` here means the editor and a
    loaded world agree about the classic range by construction; if amulet ever
    changes its default world bounds, this follows.
    """
    with _contained_logging():
        try:
            from amulet.api.wrapper import DefaultSelection  # type: ignore
        except Exception:  # pragma: no cover - depends on the environment
            return _FALLBACK_CLASSIC_RANGE
    try:
        return int(DefaultSelection.min_y), int(DefaultSelection.max_y)
    except Exception:  # pragma: no cover - depends on the environment
        return _FALLBACK_CLASSIC_RANGE


# ---------------------------------------------------------------------------
# Platforms and versions
# ---------------------------------------------------------------------------


def supported_platforms() -> Tuple[str, ...]:
    """Return every platform the installed translation data can read.

    This includes ``universal``, which is the intermediate format rather than a
    world anybody opens; surfaces that offer a choice filter it out through
    :data:`EDITABLE_PLATFORMS` rather than this function hiding an installed
    platform from a reader who asked what is installed.
    """
    manager = translation_manager()
    if manager is None:
        return ()
    try:
        with _contained_logging():
            platforms = manager.platforms()
        return tuple(sorted(str(platform) for platform in platforms))
    except Exception:  # pragma: no cover - depends on the environment
        log.exception("Studio version support: the platform list could not be read")
        return ()


def editable_platforms() -> Tuple[str, ...]:
    """Return the installed platforms a user can actually open a world on."""
    installed = supported_platforms()
    return tuple(name for name in EDITABLE_PLATFORMS if name in installed)


def _as_version(value: Any) -> Version:
    """Coerce whatever a caller passed into a version tuple, or ``()``."""
    if value is None:
        return ()
    if isinstance(value, str):
        parts: List[str] = value.split(".")
    elif isinstance(value, Sequence):
        parts = [str(part) for part in value]
    else:
        return ()
    numbers: List[int] = []
    for part in parts:
        try:
            numbers.append(int(str(part).strip()))
        except (TypeError, ValueError):
            return ()
    return tuple(numbers)


def versions_for(platform: str) -> Tuple[Version, ...]:
    """Return every version of ``platform`` the installed data can read, ascending."""
    manager = translation_manager()
    if manager is None:
        return ()
    try:
        with _contained_logging():
            numbers = manager.version_numbers(str(platform))
    except Exception:
        # An unknown platform is a question with an answer, not an error worth a
        # traceback: the caller gets an empty tuple and can say so.
        return ()
    resolved = []
    for number in numbers:
        version = _as_version(number)
        if version:
            resolved.append(version)
    return tuple(sorted(set(resolved)))


def latest(platform: str) -> Version:
    """Return the newest installed version of ``platform``, or ``()``."""
    versions = versions_for(platform)
    return versions[-1] if versions else ()


def oldest(platform: str) -> Version:
    """Return the oldest installed version of ``platform``, or ``()``."""
    versions = versions_for(platform)
    return versions[0] if versions else ()


def resolve_version(platform: str, version: Any) -> Version:
    """Return the installed version the translation manager would actually use.

    The manager rounds a request down to the nearest version it holds, so a
    caller asking about a version that is not installed gets an answer about a
    different one.  Resolving it here means a surface can say which version it
    really read instead of implying it had the one that was asked for.
    """
    known = versions_for(platform)
    if not known:
        return ()
    wanted = _as_version(version)
    if not wanted:
        return known[-1]
    if wanted in known:
        return wanted
    below = [candidate for candidate in known if candidate <= wanted]
    return below[-1] if below else known[0]


def version_text(version: Any) -> str:
    """Return a version as a reader would write it, or an honest dash."""
    resolved = _as_version(version)
    if not resolved:
        return "—"
    return ".".join(str(part) for part in resolved)


def data_version(platform: str, version: Any) -> Optional[int]:
    """Return the world data version of a release, read from the installed data."""
    manager = translation_manager()
    resolved = resolve_version(platform, version)
    if manager is None or not resolved:
        return None
    try:
        with _contained_logging():
            return int(manager.get_version(str(platform), resolved).data_version)
    except Exception:  # pragma: no cover - depends on the environment
        return None


# ---------------------------------------------------------------------------
# Build ranges per platform, version, and dimension
# ---------------------------------------------------------------------------


def normalise_dimension(dimension: str) -> str:
    """Return the canonical name of a vanilla dimension, or ``""`` for any other."""
    return _DIMENSION_ALIASES.get(str(dimension).strip().lower(), "")


def _overworld_is_extended(platform: str, version: Any) -> bool:
    """Return whether the 1.18 height change applies to this platform and version."""
    name = str(platform).lower()
    resolved = resolve_version(name, version) or _as_version(version)
    if name == "java":
        stored = data_version(name, version)
        if stored is not None:
            return stored >= _JAVA_HEIGHT_CHANGE_DATA_VERSION
    if not resolved:
        # Nothing was readable, so the extended range cannot be claimed.
        return False
    return resolved >= _BEDROCK_HEIGHT_CHANGE_VERSION


def height_range(platform: str, version: Any, dimension: str) -> Tuple[int, int]:
    """Return the ``(min_y, max_y)`` build range of a dimension on a version.

    ``max_y`` is exclusive, matching ``amulet-core``'s own selection bounds, so
    an overworld reported as ``(-64, 320)`` has its highest placeable block at
    ``319``.  A dimension this module does not recognise -- a data pack's own --
    falls back to the classic range, and :func:`height_range_note` says that is
    what happened rather than letting the numbers imply they were read.
    """
    name = normalise_dimension(dimension)
    if name == THE_NETHER:
        return _NETHER_RANGE
    if name == THE_END:
        return classic_range()
    if name == OVERWORLD and _overworld_is_extended(platform, version):
        return _EXTENDED_OVERWORLD_RANGE
    return classic_range()


def height_range_note(platform: str, version: Any, dimension: str) -> str:
    """Return one sentence naming where a build range came from.

    Every surface that shows a range shows this beside it.  The interesting
    cases are the ones a bare pair of numbers cannot distinguish: a version that
    is not installed and was rounded to one that is, a platform nothing is known
    about, and a custom dimension whose real range only its own dimension type
    can give.
    """
    requested = _as_version(version)
    resolved = resolve_version(platform, version)
    name = normalise_dimension(dimension)
    if not resolved:
        reason = unavailable_reason() or f"{platform} is not in the installed data"
        return f"Not read: {reason}"
    parts = [f"read at {platform} {version_text(resolved)}"]
    if requested and requested != resolved:
        parts.append(f"{version_text(requested)} is not installed")
    if not name:
        parts.append(
            "custom dimension shown at the classic range until its own "
            "dimension type is read"
        )
    elif name == OVERWORLD:
        stored = data_version(platform, resolved)
        if _overworld_is_extended(platform, resolved):
            parts.append("the 1.18 height change applies")
        else:
            parts.append("before the 1.18 height change")
        if stored is not None:
            parts.append(f"data version {stored}")
    return " · ".join(parts)


def height_ranges(
    platform: str, version: Any
) -> Tuple[Tuple[str, Tuple[int, int]], ...]:
    """Return the build range of every vanilla dimension on one version."""
    return tuple(
        (dimension, height_range(platform, version, dimension))
        for dimension in DIMENSIONS
    )


def range_text(bounds: Tuple[int, int]) -> str:
    """Return a build range the way the surfaces write it."""
    return f"{bounds[0]} to {bounds[1]}"


# ---------------------------------------------------------------------------
# Blocks and features
# ---------------------------------------------------------------------------


def _base_names(platform: str, version: Version) -> FrozenSet[str]:
    """Return every ``minecraft:`` base name the installed data holds for a version."""
    key = (str(platform), version)
    cached = _base_name_cache.get(key)
    if cached is not None:
        return cached
    manager = translation_manager()
    names: FrozenSet[str] = frozenset()
    if manager is not None and version:
        try:
            with _contained_logging():
                names = frozenset(
                    manager.get_version(str(platform), version).block.base_names(
                        "minecraft"
                    )
                )
        except Exception:  # pragma: no cover - depends on the environment
            log.exception(
                "Studio version support: block names for %s %s could not be read",
                platform,
                version_text(version),
            )
            names = frozenset()
    _base_name_cache[key] = names
    return names


def _base_name(block_id: str) -> str:
    """Return the base name of an identifier, dropping any namespace."""
    text = str(block_id).strip()
    return text.split(":", 1)[1] if ":" in text else text


def version_supports_block(platform: str, version: Any, block_id: str) -> bool:
    """Return whether the installed data can represent a block on that version."""
    resolved = resolve_version(platform, version)
    if not resolved:
        return False
    return _base_name(block_id) in _base_names(str(platform), resolved)


def supports_block(block_id: str, platform: str = "", version: Any = None) -> bool:
    """Return whether any installed platform can represent this block.

    With no platform given the question is asked of the newest installed
    version of each editable platform, which is what a picker wants to know:
    can this identifier be placed at all, by anything this install can write.
    """
    if platform:
        return version_supports_block(platform, version, block_id)
    return any(
        version_supports_block(name, latest(name), block_id)
        for name in editable_platforms()
    )


def unsupported_blocks(block_ids: Iterable[str]) -> Tuple[str, ...]:
    """Return the identifiers no installed platform can represent, in order."""
    missing = []
    for block_id in block_ids:
        if not supports_block(block_id):
            missing.append(str(block_id))
    return tuple(missing)


def version_has_feature(platform: str, version: Any, name: str) -> bool:
    """Return whether a version of a platform carries every block of a feature."""
    feature = FEATURES.get(str(name))
    if feature is None:
        if name not in _unknown_features:
            _unknown_features.add(str(name))
            log.warning("Studio version support: unknown feature gate %r", name)
        return False
    resolved = resolve_version(platform, version)
    if not resolved:
        return False
    names = _base_names(str(platform), resolved)
    return all(block in names for block in feature.blocks)


def has_feature(name: str) -> bool:
    """Return whether the installed data knows this feature at all.

    This is the question a module-level surface definition asks: should this
    content exist in the editor on this install.  Whether a *world* is new
    enough for it is :func:`version_has_feature`, which the surface asks once it
    knows which version it is looking at.
    """
    return any(
        version_has_feature(platform, latest(platform), name)
        for platform in editable_platforms()
    )


def feature_since(platform: str, name: str) -> Version:
    """Return the earliest installed version of ``platform`` carrying a feature.

    Availability is monotonic in the installed data -- a block that appears in
    one version appears in every later one -- so this bisects rather than
    walking every version, which keeps the cost of a surface that asks about a
    dozen features to a handful of database loads.
    """
    key = (str(platform), str(name))
    cached = _feature_since_cache.get(key)
    if cached is not None:
        return cached
    versions = versions_for(platform)
    found: Version = ()
    if versions and str(name) in FEATURES:
        low, high = 0, len(versions) - 1
        if version_has_feature(platform, versions[high], name):
            while low < high:
                middle = (low + high) // 2
                if version_has_feature(platform, versions[middle], name):
                    high = middle
                else:
                    low = middle + 1
            found = versions[low]
    _feature_since_cache[key] = found
    return found


def feature_note(name: str) -> str:
    """Return where a feature first appears on each editable platform.

    The wording is deliberately about the installed data rather than about
    Minecraft: this is what can be read here, which is the only thing that can
    be checked.
    """
    parts = []
    for platform in editable_platforms():
        since = feature_since(platform, name)
        if since:
            parts.append(f"{platform} {version_text(since)}")
    if not parts:
        reason = unavailable_reason()
        if reason:
            return f"not readable: {reason}"
        return "not in the installed translation data"
    return " · ".join(parts) + " and later"


def feature_label(name: str) -> str:
    """Return the reader-facing name of a feature, or the gate name itself."""
    feature = FEATURES.get(str(name))
    return feature.label if feature is not None else str(name)


def gated(name: str, *items: Any) -> Tuple[Any, ...]:
    """Return ``items`` when the installed data knows ``name``, and ``()`` when not.

    Surface definitions are module-level data, so this is how a section leaves
    out content the install cannot support instead of offering a chip that
    would resolve to nothing.  The surface still says why, through
    :func:`support_report`.
    """
    return tuple(items) if has_feature(name) else ()


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


def entity_registry_available() -> bool:
    """Return whether the installed data ships an entity registry to read.

    Some ``PyMCTranslate`` builds ship block data with no entity database.  When
    that is the case a mob list cannot be read from the install, and every
    surface that shows one has to say that its list is a catalogue gated on
    block data rather than something read from an entity registry.
    """
    global _entity_registry
    if _entity_registry is not None:
        return _entity_registry
    manager = translation_manager()
    _entity_registry = False
    if manager is not None:
        for platform in editable_platforms():
            version = latest(platform)
            if not version:
                continue
            try:
                with _contained_logging():
                    namespaces = manager.get_version(
                        platform, version
                    ).entity.namespaces()
            except Exception:  # pragma: no cover - depends on the environment
                continue
            if namespaces:
                _entity_registry = True
                break
    return _entity_registry


def entity_source_note() -> str:
    """Return one sentence naming where a mob list here actually comes from."""
    if entity_registry_available():
        return (
            "Mob names are read from the installed entity registry and gated on "
            "the version of the world being edited."
        )
    return (
        "This install ships no entity registry, so the mob list is a catalogue "
        "gated on the installed block data rather than read from the install. "
        "A world older than a mob's version is never offered it."
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _platform_span(platform: str) -> str:
    versions = versions_for(platform)
    if not versions:
        return ""
    return (
        f"{platform} {version_text(versions[0])} to {version_text(versions[-1])} "
        f"({len(versions)} versions)"
    )


def support_report() -> str:
    """Return one honest sentence naming the version support actually installed.

    Every surface that depends on version data shows this, because a short
    structure list or a missing block family is indistinguishable from an old
    Minecraft without it.
    """
    manager = translation_manager()
    if manager is None:
        return (
            "No Minecraft version data is available: "
            f"{unavailable_reason() or 'the translation library did not load'}. "
            "Version-dependent surfaces are empty rather than guessed."
        )
    libraries = []
    if _translate_build:
        libraries.append(f"PyMCTranslate build {_translate_build}")
    else:  # pragma: no cover - depends on the environment
        libraries.append("PyMCTranslate")
    core = _core_version()
    if core:
        libraries.append(f"amulet-core {core}")
    spans = [
        span for span in (_platform_span(name) for name in editable_platforms()) if span
    ]
    if not spans:
        return (
            f"{' and '.join(libraries)} loaded, but no editable platform is "
            "present in the installed data, so no version can be offered."
        )
    sentence = f"{' and '.join(libraries)} can read {', '.join(spans)}."
    if not entity_registry_available():
        sentence += (
            " This build ships no entity registry, so mob lists are gated on "
            "block data rather than read from it."
        )
    return sentence


__all__ = [
    "DIMENSIONS",
    "EDITABLE_PLATFORMS",
    "FEATURES",
    "FEATURE_NAMES",
    "Feature",
    "OVERWORLD",
    "THE_END",
    "THE_NETHER",
    "Version",
    "classic_range",
    "data_version",
    "editable_platforms",
    "entity_registry_available",
    "entity_source_note",
    "feature_label",
    "feature_note",
    "feature_since",
    "gated",
    "has_feature",
    "height_range",
    "height_range_note",
    "height_ranges",
    "latest",
    "normalise_dimension",
    "oldest",
    "range_text",
    "resolve_version",
    "support_report",
    "supported_platforms",
    "supports_block",
    "translation_manager",
    "unavailable_reason",
    "unsupported_blocks",
    "version_has_feature",
    "version_supports_block",
    "version_text",
    "versions_for",
]
