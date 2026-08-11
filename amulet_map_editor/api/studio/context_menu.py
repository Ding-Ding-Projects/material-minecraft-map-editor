"""Searchable right-click menus for every Amulet Studio surface.

A platform ``wx.Menu`` cannot be searched, cannot show a regular-expression
builder, and cannot be styled to match the rest of the shell, so Studio draws
its own: a 300px popover with an uppercase title, a search field carrying the
regex opt-in and the shared ``.*`` builder, an honest feedback line reading
``"11 of 19 commands · Filtering by plain text."``, and a scrolling item list
whose keyboard accelerators are right-aligned in a monospaced face.

**The three menus the design draws are transcribed from it.**  ``viewport``,
``navigator``, and ``ribbon`` carry the design's own titles, its own row labels
in its own order, and its own accelerator text.  Where the design states an
accelerator it is written here exactly as the design states it, and where the
design states none the row shows none: a shortcut invented to fill a gap is a
key the user is trained to press for nothing.  The remaining menus below cover
surfaces the design's prototype never wired a right-click to -- the properties
pane, the selection-box list, the status bar, tabs, tab groups, and a recent
project -- and every element in this shell has a context menu, so they stay.

**A row is never dropped for being unwired.**  A destination this build has not
registered leaves the row exactly where the design put it, disabled, carrying a
tooltip that names what is unmet: a menu that quietly loses a command teaches
the reader the product does not have it.

**Accelerators the shell installs come from one table.**  :data:`ACCELERATORS`
is the single source for those bindings: the retained menus read it to draw
their text, and :func:`accelerator_table_entries` turns the same rows into the
``wx.AcceleratorTable`` the shell installs, so the drawn key and the bound key
cannot drift.  :func:`viewport_accelerator` reads the user-configurable 3D
editor key groups live for the surfaces that report them.

**Selects are decorated the way the design decorates them.**  The design builds
every dropdown through one function, and :func:`decorate_select` is that
function: the stored choice or the first option, the shared query applied with
the regex opt-in the user chose, a swatch derived from the option's leading
identifier, and the chosen row drawn in the primary container.  Opening a list
clears its query and keeps its regex mode -- :func:`restore_search` and
:func:`remember_regex_mode` -- which is what the design's ``open`` does.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import (
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

import wx

from amulet_map_editor.api.studio import tokens, widgets
from amulet_map_editor.api.studio.search import SearchState

log = logging.getLogger(__name__)

__all__ = [
    "ACCELERATORS",
    "CTX_MENUS",
    "GroupChoice",
    "MenuItem",
    "SearchableContextMenu",
    "SelectOption",
    "accelerator",
    "accelerator_table_entries",
    "decorate_select",
    "menu",
    "menu_feedback",
    "open_context_menu",
    "open_group_picker",
    "option_swatch",
    "remember_regex_mode",
    "restore_search",
    "select_feedback",
    "select_value",
    "tab_groups",
    "unavailable_clause",
    "unavailable_hint",
    "viewport_accelerator",
]

#: Local menu actions that neither open a surface nor run a shell command.
ACTION_APPEARANCE = "editAppearance"
ACTION_MOVE_INTO_GROUP = "moveIntoGroup"

#: The design's four one-way layout rows.  The shell registers *toggles* for
#: the ribbon and the properties pane, and a row labelled "Collapse the ribbon"
#: that expands an already-collapsed ribbon is a lie, so the menu carries these
#: out itself against the live window: one setter, one direction, each time.
ACTION_COLLAPSE_RIBBON = "collapseRibbon"
ACTION_EXPAND_RIBBON = "expandRibbon"
ACTION_SHOW_PANE = "showPane"
ACTION_HIDE_PANE = "hidePane"

#: ``action`` -> ``(method the host window exposes, the value to pass)``.
_LAYOUT_ACTIONS: Mapping[str, Tuple[str, bool]] = MappingProxyType(
    {
        ACTION_COLLAPSE_RIBBON: ("set_collapsed", True),
        ACTION_EXPAND_RIBBON: ("set_collapsed", False),
        ACTION_SHOW_PANE: ("show_properties", True),
        ACTION_HIDE_PANE: ("show_properties", False),
    }
)

#: How far up the window tree a layout action looks for its host before giving
#: up.  Bounded so a detached or cyclic parent chain cannot spin.
_MAX_ANCESTORS = 32


# ----------------------------------------------------------------------------
# the shared accelerator table
# ----------------------------------------------------------------------------

#: Every accelerator the shell installs, keyed by the command or surface key it
#: fires.  Command keys and surface keys share this namespace because they never
#: collide, and because a reader asking "what does Ctrl+Shift+H do" should not
#: have to know which of the two kinds of key answers.
ACCELERATORS: Mapping[str, str] = MappingProxyType(
    {
        # editing commands
        "save": "Ctrl+S",
        "undo": "Ctrl+Z",
        "redo": "Ctrl+Y",
        "copy": "Ctrl+C",
        "cut": "Ctrl+X",
        "paste": "Ctrl+V",
        "delete": "Delete",
        "selectAll": "Ctrl+A",
        # shell state
        "togglePane": "Ctrl+Alt+P",
        "toggleRibbon": "Ctrl+F1",
        # surfaces
        "palette": "Ctrl+Shift+F",
        "goto": "Ctrl+G",
        "history": "Ctrl+Shift+H",
        "nbt": "Ctrl+Shift+N",
        "notifications": "Ctrl+Shift+O",
        "regex": "Ctrl+Shift+R",
        "tabManager": "Ctrl+Shift+T",
        "docs": "F1",
    }
)

#: Modifier names understood on the left of an accelerator string.
_MODIFIERS: Mapping[str, int] = MappingProxyType(
    {"CTRL": wx.ACCEL_CTRL, "SHIFT": wx.ACCEL_SHIFT, "ALT": wx.ACCEL_ALT}
)

#: Named keys understood on the right of an accelerator string.
_NAMED_KEYS: Mapping[str, int] = MappingProxyType(
    {
        "DELETE": wx.WXK_DELETE,
        "DEL": wx.WXK_DELETE,
        "INSERT": wx.WXK_INSERT,
        "ENTER": wx.WXK_RETURN,
        "RETURN": wx.WXK_RETURN,
        "ESC": wx.WXK_ESCAPE,
        "ESCAPE": wx.WXK_ESCAPE,
        "TAB": wx.WXK_TAB,
        "SPACE": wx.WXK_SPACE,
        "HOME": wx.WXK_HOME,
        "END": wx.WXK_END,
        "F1": wx.WXK_F1,
        "F2": wx.WXK_F2,
        "F3": wx.WXK_F3,
        "F4": wx.WXK_F4,
        "F5": wx.WXK_F5,
        "F6": wx.WXK_F6,
        "F7": wx.WXK_F7,
        "F8": wx.WXK_F8,
        "F9": wx.WXK_F9,
        "F10": wx.WXK_F10,
        "F11": wx.WXK_F11,
        "F12": wx.WXK_F12,
    }
)


def accelerator(*, command: str = "", surface: str = "") -> str:
    """Return the accelerator text for one command or surface key.

    Returns an empty string when nothing is bound, which is the honest answer:
    a menu row with no accelerator says nothing, whereas an invented one trains
    somebody to press a key that does not work.
    """
    key = command or surface
    return ACCELERATORS.get(str(key), "") if key else ""


def parse_accelerator(text: str) -> Optional[Tuple[int, int]]:
    """Return ``(modifier flags, key code)`` for an accelerator string.

    ``None`` means the string names a key this platform cannot express as an
    accelerator, so the caller installs nothing rather than binding the wrong
    key.  The design's pointer bindings -- ``RMB``, ``Ctrl+LMB`` -- land here
    too: a mouse gesture is drawn beside its row and is never installed as a
    keyboard accelerator.
    """
    parts = [part.strip() for part in str(text).split("+") if part.strip()]
    if not parts:
        return None
    flags = wx.ACCEL_NORMAL
    for part in parts[:-1]:
        modifier = _MODIFIERS.get(part.upper())
        if modifier is None:
            return None
        flags |= modifier
    final = parts[-1]
    named = _NAMED_KEYS.get(final.upper())
    if named is not None:
        return flags, named
    if len(final) == 1:
        return flags, ord(final.upper())
    return None


def accelerator_table_entries(
    identifiers: Mapping[str, int],
) -> List[Tuple[int, int, int]]:
    """Build ``wx.AcceleratorTable`` rows from :data:`ACCELERATORS`.

    ``identifiers`` maps a command or surface key to the ``wx`` id the shell
    has bound a handler to.  Only keys present in both mappings produce a row,
    so a binding is installed exactly when there is something for it to fire —
    which is what keeps the drawn accelerator and the working one identical.
    """
    entries: List[Tuple[int, int, int]] = []
    for key, text in ACCELERATORS.items():
        identifier = identifiers.get(key)
        if identifier is None:
            continue
        parsed = parse_accelerator(text)
        if parsed is None:
            log.warning("Accelerator %r for %r cannot be installed", text, key)
            continue
        entries.append((parsed[0], parsed[1], int(identifier)))
    return entries


#: How the 3D editor's serialised key names read in a menu.
_KEY_NAMES: Mapping[str, str] = MappingProxyType(
    {
        "MOUSE_LEFT": "LMB",
        "MOUSE_MIDDLE": "MMB",
        "MOUSE_RIGHT": "RMB",
        "MOUSE_AUX_1": "Mouse 4",
        "MOUSE_AUX_2": "Mouse 5",
        "MOUSE_WHEEL_SCROLL_UP": "Scroll up",
        "MOUSE_WHEEL_SCROLL_DOWN": "Scroll down",
        "CTRL": "Ctrl",
        "SHIFT": "Shift",
        "ALT": "Alt",
        "SPACE": "Space",
        "TAB": "Tab",
        "ESCAPE": "Esc",
    }
)


def _active_keybinds() -> Mapping[str, Tuple[Sequence[str], str]]:
    """Return the 3D editor's live key group, or an empty mapping.

    The viewport's bindings are user-configurable, so they are read rather than
    assumed.  Every failure route returns nothing, which makes the affected
    readout show no accelerator instead of the shipped default the user may
    well have replaced.
    """
    try:
        from amulet_map_editor.api import config
        from amulet_map_editor.programs.edit.api.key_config import (
            DefaultKeybindGroupId,
            PresetKeybinds,
        )
    except Exception:  # pragma: no cover - optional editor package
        return {}
    try:
        edit_config = config.get("amulet_edit", {}) or {}
        group_id = edit_config.get("keybind_group", DefaultKeybindGroupId)
        user_groups = edit_config.get("user_keybinds", {}) or {}
        group = user_groups.get(group_id) or PresetKeybinds.get(group_id)
        if not group:
            group = PresetKeybinds.get(DefaultKeybindGroupId, {})
        return group or {}
    except Exception:  # pragma: no cover - a hand-edited profile
        log.exception("Could not read the active 3D editor key group")
        return {}


def viewport_accelerator(action: str) -> str:
    """Return the live binding for a 3D editor action such as ``ACT_MOVE_UP``.

    An unknown or unreadable action returns an empty string rather than the
    shipped default, because the shipped default is exactly what a user who
    rebound the action no longer presses.
    """
    binding = _active_keybinds().get(str(action))
    if not binding:
        return ""
    try:
        modifiers, key = binding
    except (TypeError, ValueError):
        return ""
    parts = [_KEY_NAMES.get(str(part), str(part)) for part in tuple(modifiers)]
    parts.append(_KEY_NAMES.get(str(key), str(key)))
    return "+".join(part for part in parts if part)


# ----------------------------------------------------------------------------
# menu definitions
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class MenuItem:
    """One row of a searchable context menu.

    A row names exactly one destination: a ``surface`` to open, a ``command``
    for the shell to run, or a local ``action`` the menu performs itself.
    ``accel`` is what the row draws on its right; for the design's own menus it
    is the design's own text, and for the rest it is filled from the shared
    table unless the caller states one.
    """

    label: str
    accel: str = ""
    surface: str = ""
    command: str = ""
    action: str = ""
    hint: str = ""

    @property
    def haystack(self) -> str:
        """Return the text this row is searched by."""
        return " ".join(part for part in (self.label, self.hint, self.accel) if part)


def _item(
    label: str,
    *,
    surface: str = "",
    command: str = "",
    action: str = "",
    accel: Optional[str] = None,
    hint: str = "",
) -> MenuItem:
    """Build a row, resolving its accelerator from the shared table.

    Passing ``accel`` states the binding outright, which is how every row the
    design specifies is written: the design's text wins over the table, and an
    empty string means the design draws no accelerator on that row.
    """
    resolved = (
        accel if accel is not None else accelerator(command=command, surface=surface)
    )
    return MenuItem(
        label=label,
        accel=resolved,
        surface=surface,
        command=command,
        action=action,
        hint=hint,
    )


#: The row every menu ends with, wired to the app's element appearance editor.
_APPEARANCE = _item(
    "Edit appearance…",
    accel="",
    action=ACTION_APPEARANCE,
    hint="Change the colours and typography of this element",
)

#: The anchored group picker offered by the tab and tab-group menus.  It is a
#: picker rather than an inline list of groups: a menu that grows one row per
#: group becomes unusable as soon as a workspace has more than a handful.
_MOVE_INTO_GROUP = _item(
    "Move… into group…",
    action=ACTION_MOVE_INTO_GROUP,
    hint="Choose a tab group, or create one",
)


# -- the three menus the design draws ----------------------------------------


def _viewport_menu() -> Tuple[MenuItem, ...]:
    """The design's ``ctxMenus.viewport``: nineteen rows, in its order."""
    return (
        _item("Inspect block", accel="RMB", surface="nbt"),
        _item("Teleport camera here", accel="", surface="goto"),
        _item("Add selection box here", accel="Ctrl+LMB", command="addBox"),
        _item("Deselect active box", accel="Esc", command="deselectBox"),
        _item("Deselect all boxes", accel="Ctrl+Shift+D", command="deselectAllBoxes"),
        _item("Toggle projection", accel="P", command="projection"),
        _item("Measure from here", accel="", surface="measure"),
        _item("Layer slice at this height", accel="", surface="layerSlice"),
        _item("Light levels here", accel="", surface="lightOverlay"),
        _item("Trace redstone circuit", accel="", surface="redstoneTrace"),
        _item("Entity browser", accel="", surface="entityBrowser"),
        _item("Chunk inspector", accel="", surface="chunkInspector"),
        _item("Add waypoint here", accel="", surface="waypoints"),
        _item("Set world spawn here", accel="", surface="spawnPoints"),
        _item("Build portal pair from here", accel="", surface="portalBuilder"),
        _item("Start rail tunnel here", accel="", surface="railTunnel"),
        _item("Render layers…", accel="", surface="renderLayers"),
        _item("View settings…", accel="", surface="viewControls"),
        _APPEARANCE,
    )


def _navigator_menu() -> Tuple[MenuItem, ...]:
    """The design's ``ctxMenus.navigator``: ten rows, in its order."""
    return (
        _item("Frame this dimension", accel="", command="frameDimension"),
        _item("Add selection box", accel="", command="addBox"),
        _item("Duplicate selection box", accel="", command="duplicateBox"),
        _item("Delete selection box", accel="Del", command="removeBox"),
        _item("Chunk inspector", accel="", surface="chunkInspector"),
        _item("Biome map", accel="", surface="biomeMap"),
        _item("Structure library", accel="", surface="schematicLibrary"),
        _item("Pending imports", accel="", surface="pendingImports"),
        _item("World info", accel="", surface="worldInfo"),
        _APPEARANCE,
    )


def _ribbon_menu() -> Tuple[MenuItem, ...]:
    """The design's ``ctxMenus.ribbon``: nine rows, in its order."""
    return (
        _item("Collapse the ribbon", accel="", action=ACTION_COLLAPSE_RIBBON),
        _item("Expand the ribbon", accel="", action=ACTION_EXPAND_RIBBON),
        _item("Show the properties pane", accel="", action=ACTION_SHOW_PANE),
        _item("Hide the properties pane", accel="", action=ACTION_HIDE_PANE),
        _item("Customize tool settings…", accel="", surface="toolSettings"),
        _item("Key configuration…", accel="", surface="controls"),
        _item("Options…", accel="", surface="prefs"),
        _item("Command palette", accel="Ctrl+Shift+F", surface="palette"),
        _APPEARANCE,
    )


# -- surfaces the design's prototype never wired a right-click to -------------
#
# Every element in this shell carries a context menu, and these surfaces exist
# whether or not the prototype demonstrated a menu on them.  Their rows are
# this project's, not the design's, and their accelerators come from the shared
# table rather than from a design line.


def _tab_menu() -> Tuple[MenuItem, ...]:
    return (
        _MOVE_INTO_GROUP,
        _item("Tabs and groups…", surface="tabManager"),
        _item(
            "Rename this tab…",
            surface="tabManager",
            accel="",
            hint="Rename through the tab manager",
        ),
        _item(
            "Pin or unpin this tab",
            surface="tabManager",
            accel="",
            hint="Pinned tabs stay visible when ordinary tabs overflow",
        ),
        _item("Close tabs containing text…", surface="tabManager", accel=""),
        _item("Close tabs not containing text…", surface="tabManager", accel=""),
        _APPEARANCE,
    )


def _tab_group_menu() -> Tuple[MenuItem, ...]:
    return (
        _MOVE_INTO_GROUP,
        _item("Rename this group…", surface="tabManager", accel=""),
        _item("Collapse or expand this group", surface="tabManager", accel=""),
        _item("Tabs and groups…", surface="tabManager"),
        _item("Close tabs containing text…", surface="tabManager", accel=""),
        _item("Close tabs not containing text…", surface="tabManager", accel=""),
        _APPEARANCE,
    )


def _pane_menu() -> Tuple[MenuItem, ...]:
    return (
        _item("Hide the properties pane", action=ACTION_HIDE_PANE),
        _item("Inspector…", surface="inspector"),
        _item("World information…", surface="worldInfo"),
        _item("Project history…", surface="history"),
        _item("Notification history…", surface="notifications"),
        _item("Pending imports…", surface="pendingImports"),
        _APPEARANCE,
    )


def _recent_menu() -> Tuple[MenuItem, ...]:
    return (
        _item("Copy the project path", command="copy"),
        _item("Open the project folder in Visual Studio Code", command="openInEditor"),
        _item("Import chunks from this world…", command="importChunks"),
        _item("Project information…", surface="worldInfo"),
        _item("Project history…", surface="history"),
        _item("Validate and repair…", surface="validateRepair"),
        _APPEARANCE,
    )


def _boxes_menu() -> Tuple[MenuItem, ...]:
    return (
        _item("Add a selection box", command="addBox"),
        _item("Remove the active box", command="removeBox"),
        _item("Select all", command="selectAll"),
        _item("Move point 1", command="movePoint1"),
        _item("Move point 2", command="movePoint2"),
        _item("Move the active box", command="moveBox"),
        _item("Export the selection…", command="export"),
        _item("Measure…", surface="measure"),
        _APPEARANCE,
    )


def _status_bar_menu() -> Tuple[MenuItem, ...]:
    return (
        _item("Undo", command="undo"),
        _item("Redo", command="redo"),
        _item("Project history…", surface="history"),
        _item("Change dimension…", command="setDimension"),
        _item("Camera speed…", command="cameraSpeed"),
        _item("View settings…", surface="viewControls"),
        _item("Notification history…", surface="notifications"),
        _APPEARANCE,
    )


#: Every searchable context menu, keyed by the surface that raises it.  The
#: value is the menu's uppercase title and its rows.  The first three are the
#: design's, title and rows alike; the rest cover surfaces it never wired one to.
CTX_MENUS: Dict[str, Tuple[str, Tuple[MenuItem, ...]]] = {
    "viewport": ("Viewport", _viewport_menu()),
    "navigator": ("Navigator", _navigator_menu()),
    "ribbon": ("Ribbon", _ribbon_menu()),
    "tab": ("Tab", _tab_menu()),
    "tabGroup": ("Tab group", _tab_group_menu()),
    "pane": ("Properties pane", _pane_menu()),
    "recent": ("Recent project", _recent_menu()),
    "boxes": ("Selection boxes", _boxes_menu()),
    "statusbar": ("Status bar", _status_bar_menu()),
}


def menu(key: str) -> Optional[Tuple[str, Tuple[MenuItem, ...]]]:
    """Return one menu's title and rows, or ``None`` when the key is unknown."""
    return CTX_MENUS.get(str(key))


# ----------------------------------------------------------------------------
# whether a row can actually be run
# ----------------------------------------------------------------------------


def _registered_surface(key: str) -> bool:
    """Return whether this build has a window registered under ``key``.

    An index that cannot be read answers ``True``: greying out every row of
    every menu because a registry import failed would turn one fault into the
    appearance of a broken application.
    """
    try:
        from amulet_map_editor.api.studio import surfaces
    except Exception:  # pragma: no cover - registry import boundary
        log.debug("The surface index is unavailable", exc_info=True)
        return True
    try:
        return surfaces.surface(key) is not None
    except Exception:  # pragma: no cover - registry boundary
        log.debug("Could not look up the surface %r", key, exc_info=True)
        return True


def _registered_command(key: str) -> bool:
    """Return whether this build has a command registered under ``key``."""
    try:
        from amulet_map_editor.api.studio import commands
    except Exception:  # pragma: no cover - registry import boundary
        log.debug("The command registry is unavailable", exc_info=True)
        return True
    try:
        return commands.command(key) is not None
    except Exception:  # pragma: no cover - registry boundary
        log.debug("Could not look up the command %r", key, exc_info=True)
        return True


def unavailable_clause(item: MenuItem) -> str:
    """Return what is unmet for ``item``, or an empty string when nothing is.

    One clause, written once: the tooltip wraps it in a sentence naming the row
    and the accessible name appends it after the word "unavailable", so a
    pointer user and a screen-reader user are told the same thing.
    """
    if item.command and not _registered_command(item.command):
        return f"this build has no command connected to “{item.command}” yet"
    if item.surface and not _registered_surface(item.surface):
        return f"this build has no window registered under “{item.surface}” yet"
    if item.action in _LAYOUT_ACTIONS:
        return "nothing in this window can carry it out right now"
    return ""


def unavailable_hint(item: MenuItem) -> str:
    """Return the sentence a row shows while it cannot be run.

    The row stays where the design put it, so the tooltip has to answer the one
    question a greyed-out row raises: what is missing.  It names the row and the
    thing this build has not registered, rather than saying "unavailable" and
    leaving the reader to decide whether the application is broken.
    """
    clause = unavailable_clause(item)
    return f"{item.label} is unavailable: {clause}." if clause else ""


def _layout_host(start: Optional[wx.Window], method: str) -> Optional[wx.Window]:
    """Return the nearest ancestor of ``start`` exposing ``method``.

    The ribbon owns ``set_collapsed`` and the workspace owns
    ``show_properties``, and a menu raised on either is a descendant of both, so
    walking upwards finds the right window without this module having to know
    which class it is.
    """
    window = start
    for _step in range(_MAX_ANCESTORS):
        if window is None:
            return None
        if callable(getattr(window, method, None)):
            return window
        try:
            window = window.GetParent()
        except RuntimeError:  # pragma: no cover - destroyed mid-walk
            return None
    return None


# ----------------------------------------------------------------------------
# how a select is decorated
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectOption:
    """One row of a decorated select, exactly as the design assembles it."""

    label: str
    swatch: str = ""
    selected: bool = False

    @property
    def has_swatch(self) -> bool:
        """Return whether this row draws a colour swatch before its label."""
        return bool(self.swatch)


def option_swatch(option: object) -> str:
    """Return the swatch colour for one option, or an empty string.

    The design takes the option's leading word and looks it up in the block
    colour table, so ``"minecraft:stone [facing=north]"`` swatches as stone and
    ``"Nearest"`` swatches as nothing at all.
    """
    head = str(option).split(" ")[0]
    try:
        from amulet_map_editor.api.studio import blocks
    except Exception:  # pragma: no cover - colour table boundary
        log.debug("The block colour table is unavailable", exc_info=True)
        return ""
    return str(blocks.BLOCK_COLOURS.get(head, "") or "")


def select_value(options: Sequence[str], chosen: str = "") -> str:
    """Return the value a select shows: the stored choice, or its first option.

    A select never shows nothing while it has options, which is the design's
    rule and the reason a freshly built list reads as configured rather than as
    waiting for the user to notice it is empty.
    """
    text = str(chosen or "")
    if text:
        return text
    return str(options[0]) if options else ""


def select_feedback(state: SearchState) -> str:
    """Return the line the design shows beneath a select's search field.

    A select reports its search mode and nothing else -- the count sits in the
    list itself, which is right there.  A menu says how many of its rows
    survived, because a filtered menu can be short enough to look complete.
    """
    return state.feedback()


def menu_feedback(state: SearchState, shown: int, total: int, noun: str) -> str:
    """Return the design's counted feedback line, ``"3 of 19 commands · …"``."""
    plural = noun if total == 1 else f"{noun}s"
    return f"{shown} of {total} {plural} · {state.feedback()}"


def decorate_select(
    options: Sequence[str],
    chosen: str = "",
    state: Optional[SearchState] = None,
    *,
    swatches: Optional[Mapping[str, str]] = None,
) -> Tuple[SelectOption, ...]:
    """Decorate a select's options the way the design's own builder does.

    The rows that survive ``state`` keep the list's order, each carries the
    swatch its leading identifier resolves to unless ``swatches`` states one,
    and the chosen row is marked so it can be drawn in the primary container.
    ``state`` being ``None`` or empty decorates every option, which is what an
    unopened list shows.
    """
    values = [str(option) for option in options]
    value = select_value(values, chosen)
    surviving = state.filter(values) if state is not None else list(values)
    table = dict(swatches or {})
    return tuple(
        SelectOption(
            label=option,
            swatch=str(table.get(option, "") or "") or option_swatch(option),
            selected=option == value,
        )
        for option in surviving
    )


#: The regex opt-in each searchable list was last left in, keyed by the list.
#: The design keeps the mode in application state and clears only the query when
#: a list opens, so a user who turned regex on does not have to turn it on again
#: every single time they right-click.
_REGEX_MODES: Dict[str, bool] = {}


def remember_regex_mode(key: str, state: SearchState) -> None:
    """Record the regex opt-in ``state`` is now in, for the next open."""
    _REGEX_MODES[str(key)] = bool(state.regex)


def restore_search(key: str, state: SearchState) -> None:
    """Prepare a list's search the way the design's ``open`` does.

    The query is cleared, because a stale filter makes a freshly opened list
    look as though half of it has gone; the regex opt-in is restored, because
    that one is a preference rather than a leftover.
    """
    state.reset()
    state.regex = bool(_REGEX_MODES.get(str(key), state.regex))


# ----------------------------------------------------------------------------
# tab groups for the move-into-group picker
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupChoice:
    """One tab group offered by the anchored picker."""

    group_id: str
    name: str
    colour: str
    members: int

    @property
    def detail(self) -> str:
        """Return the honest member count shown beside the group's name."""
        if self.members == 1:
            return "1 tab"
        return f"{self.members} tabs"


#: Identity colours for tab groups.  A stored group carries no colour of its
#: own, so one is derived from its identifier: stable across restarts, distinct
#: between neighbours, and never presented as something the user chose.
_GROUP_COLOURS: Tuple[str, ...] = (
    "#006A63",
    "#7D5260",
    "#3F5B8B",
    "#7A5B00",
    "#4F6B2E",
    "#7A4A2B",
    "#5B4A8A",
    "#2E6B6B",
)


def group_colour(group_id: str) -> str:
    """Return the colour used to identify one tab group.

    A colour the user set through the element appearance editor wins; failing
    that the identifier picks a stable entry from the palette above.
    """
    try:
        from amulet_map_editor.api.wx.ui import element_appearance

        override = element_appearance.load_overrides().get(f"tabgroup:{group_id}", {})
        chosen = str(override.get("background", "") or "")
        if chosen:
            return chosen
    except Exception:  # pragma: no cover - overrides are optional
        log.debug("No stored appearance for tab group %r", group_id, exc_info=True)
    digest = sum(ord(char) for char in str(group_id)) if group_id else 0
    return _GROUP_COLOURS[digest % len(_GROUP_COLOURS)]


def tab_groups(surface_id: str = "main-window") -> Tuple[GroupChoice, ...]:
    """Return the persisted tab groups of one surface, with member counts.

    Returns an empty tuple when the workspace has no groups yet or cannot be
    read; the picker shows its honest empty state rather than inventing one.
    """
    try:
        from amulet_map_editor.api.tab_groups import TabWorkspace

        state = TabWorkspace.load(surface_id).normalised()
    except Exception:  # pragma: no cover - unreadable or absent profile
        log.debug("Could not read tab groups for %r", surface_id, exc_info=True)
        return ()
    counts: Dict[str, int] = {}
    for item in state.tabs:
        if item.group_id:
            counts[item.group_id] = counts.get(item.group_id, 0) + 1
    return tuple(
        GroupChoice(
            group.group_id,
            group.name,
            group_colour(group.group_id),
            counts.get(group.group_id, 0),
        )
        for group in state.groups
    )


# ----------------------------------------------------------------------------
# widgets
# ----------------------------------------------------------------------------


class _MenuRow(wx.Control, widgets._Interactive):
    """One activatable menu line: label on the left, accelerator on the right.

    The accelerator is drawn in the monospaced face so a column of them lines
    up, and it is folded into the control's accessible name so a screen-reader
    user hears the shortcut the sighted user reads.  A row whose destination
    this build has not registered is drawn disabled and says what is unmet in
    both its tooltip and its accessible name.
    """

    HEIGHT = 32
    PADDING = 10

    def __init__(
        self,
        parent: wx.Window,
        item: MenuItem,
        *,
        on_activate: Optional[Callable[[MenuItem], None]] = None,
        unavailable: str = "",
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.item = item
        self.on_activate = on_activate
        self.unavailable = str(unavailable)
        name = item.label
        if item.accel:
            name = f"{name}, {item.accel}"
        if self.unavailable:
            # A disabled window does not reliably raise a tooltip, so the reason
            # rides in the accessible name too rather than only in the tooltip.
            name = f"{name}, unavailable: {unavailable_clause(item)}"
        self._install(name, listen=False)
        self._bind_interaction()
        tooltip = self.unavailable or item.hint
        if tooltip:
            self.SetToolTip(tooltip)
        if self.unavailable:
            self.Enable(False)
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return self.IsEnabled()

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return self.IsEnabled()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        return wx.Size(tokens.scaled(200), tokens.scaled(self.HEIGHT))

    def activate(self) -> None:
        """Run this row's destination, unless it has none to run."""
        if not self.IsEnabled():
            return
        widgets.invoke(self.on_activate, self.item)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(7)
        enabled = self.IsEnabled()
        if not enabled:
            fill = None
        elif self._pressed:
            fill = tokens.blend(palette.surface_container_high, palette.on_surface, 0.1)
        elif self._hovered or self.HasFocus():
            fill = palette.surface_container_high
        else:
            fill = None
        if fill is not None:
            tokens.draw_round_rect(gcdc, rect, radius, fill)
        label_ink = palette.on_surface
        accel_ink = palette.on_surface_variant
        if not enabled:
            label_ink = tokens.blend(palette.on_surface, palette.surface, 0.55)
            accel_ink = tokens.blend(palette.on_surface_variant, palette.surface, 0.55)
        inner = tokens.scaled(self.PADDING)
        accel_width = 0
        if self.item.accel:
            gcdc.SetFont(tokens.mono_font(self, widgets.point_size(10)))
            gcdc.SetTextForeground(accel_ink)
            accel_width = gcdc.GetTextExtent(self.item.accel)[0]
            accel_height = gcdc.GetCharHeight()
            gcdc.DrawText(
                self.item.accel,
                max(inner, width - inner - accel_width),
                (height - accel_height) // 2,
            )
            accel_width += tokens.scaled(12)
        gcdc.SetFont(tokens.font(self, widgets.point_size(12)))
        gcdc.SetTextForeground(label_ink)
        available = max(0, width - inner * 2 - accel_width)
        label = widgets.elide(gcdc, self.item.label, available)
        gcdc.DrawText(label, inner, (height - gcdc.GetCharHeight()) // 2)
        if self.HasFocus():
            widgets.draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class SearchableContextMenu(wx.PopupTransientWindow):
    """The shell's only right-click menu: titled, searchable, and keyboard-run.

    Every menu carries its own :class:`~amulet_map_editor.api.studio.widgets.SearchBar`
    with the regex opt-in and the ``.*`` builder, so a long menu can be
    narrowed the same way every other list in the product is, and an invalid
    pattern is reported instead of silently emptying the menu.  Beneath the
    field sits the design's counted feedback line, so a menu narrowed to two
    rows still says how many it started with.
    """

    WIDTH = 300
    LIST_HEIGHT = 280
    MARGIN = 4
    PADDING = 8

    def __init__(
        self,
        parent: wx.Window,
        key: str,
        *,
        on_surface: Optional[Callable[[str], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
        on_action: Optional[Callable[[str, MenuItem], None]] = None,
        target: Optional[wx.Window] = None,
    ) -> None:
        super().__init__(parent, wx.BORDER_NONE)
        found = menu(key)
        if found is None:
            raise KeyError(f"There is no context menu named {key!r}")
        self.key = str(key)
        self.title, self.items = found
        self.on_surface = on_surface
        self.on_command = on_command
        self.on_action = on_action
        #: The control the menu was raised over: what "Edit appearance…" edits.
        self.target = target if target is not None else parent
        self.state = SearchState(label=f"{self.title} menu")
        restore_search(f"menu:{self.key}", self.state)
        self._rows: List[_MenuRow] = []
        self._highlight = 0

        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        inset = tokens.scaled(self.MARGIN) + tokens.scaled(self.PADDING)

        self.header = wx.Panel(self, style=wx.TAB_TRAVERSAL)
        self.header.SetBackgroundColour(palette.surface)
        self.heading = widgets.SectionLabel(self.header, self.title)
        self.search = widgets.SearchBar(
            self.header,
            "Search this menu",
            self.state,
            on_change=self._on_search,
            compact=True,
        )
        header_sizer = wx.BoxSizer(wx.VERTICAL)
        header_sizer.Add(self.heading, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(6))
        header_sizer.Add(self.search, 0, wx.EXPAND)
        self.header.SetSizer(header_sizer)

        self.list = wx.ScrolledWindow(self, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.list.SetBackgroundColour(palette.surface)
        self.list.SetScrollRate(0, tokens.scaled(10))
        self.list_sizer = wx.BoxSizer(wx.VERTICAL)
        self.list.SetSizer(self.list_sizer)
        self.empty = wx.StaticText(self.list, label="")
        self.empty.SetName(f"{self.title} menu results")
        self.empty.SetForegroundColour(palette.on_surface_variant)
        self.list_sizer.Add(self.empty, 0, wx.EXPAND | wx.ALL, tokens.scaled(6))

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self.header, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, inset)
        root.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, inset)
        self.SetSizer(root)

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self._rebuild()

    # -- content -------------------------------------------------------------
    def visible_items(self) -> Tuple[MenuItem, ...]:
        """Return the rows matching the current query."""
        return tuple(self.state.filter(self.items, key=lambda row: row.haystack))

    def can_run(self, item: MenuItem) -> str:
        """Return why ``item`` cannot be run, or an empty string when it can.

        A layout row is answered against the live window rather than a registry,
        because what carries it out is the ribbon or the workspace this menu was
        raised inside.
        """
        if item.action in _LAYOUT_ACTIONS:
            method = _LAYOUT_ACTIONS[item.action][0]
            if _layout_host(self.target, method) is None and (
                _layout_host(self.GetParent(), method) is None
            ):
                return unavailable_hint(item)
            return ""
        return unavailable_hint(item)

    def _rebuild(self) -> None:
        """Draw the rows that survive the query, plus an honest empty state."""
        for row in self._rows:
            self.list_sizer.Detach(row)
            row.Destroy()
        self._rows = []
        visible = self.visible_items()
        for item in visible:
            row = _MenuRow(
                self.list,
                item,
                on_activate=self._activate,
                unavailable=self.can_run(item),
            )
            self.list_sizer.Insert(
                len(self._rows), row, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(2)
            )
            self._rows.append(row)
        if visible:
            self.empty.SetLabel("")
            self.empty.Hide()
        else:
            self.empty.SetLabel(self.state.describe_matches(0, "menu item"))
            self.empty.Show()
        self._refresh_feedback(len(visible))
        self._highlight = 0
        self.list.FitInside()
        self.layout()

    def _refresh_feedback(self, shown: int) -> None:
        """Show the design's counted line under the search field."""
        feedback = getattr(self.search, "feedback", None)
        if feedback is None:  # pragma: no cover - the bar always builds one
            return
        try:
            feedback.SetLabel(
                menu_feedback(self.state, shown, len(self.items), "command")
            )
            self.search.Layout()
        except RuntimeError:  # pragma: no cover - destroyed mid-update
            return

    def _on_search(self, _state: SearchState) -> None:
        remember_regex_mode(f"menu:{self.key}", self.state)
        self._rebuild()

    # -- geometry ------------------------------------------------------------
    def work_area(self) -> wx.Rect:
        """Return the usable area of the display this menu will appear on."""
        try:
            index = wx.Display.GetFromWindow(self.GetParent())
            display = wx.Display(index if index != wx.NOT_FOUND else 0)
            return display.GetClientArea()
        except Exception:  # pragma: no cover - platform boundary
            return wx.Rect(0, 0, 1280, 800)

    def layout(self) -> None:
        """Size the popover to its content, bounded by the display.

        The row height comes from the item sizer's own minimum, never from
        ``GetBestSize()`` on the scrolling list.  A ``wx.ScrolledWindow``
        reports its *viewport* as its best size, so measuring it produced a
        16-pixel list against several hundred pixels of items and every menu in
        the application opened showing none of its rows.  This is the same trap
        ``AnchoredPopup.layout`` documents and solves; the two must stay in
        agreement, because a menu is a popover with rows.
        """
        area = self.work_area()
        self.header.Fit()
        header_height = self.header.GetBestSize().height

        # What the items actually need, independent of the viewport showing them.
        sizer = self.list.GetSizer()
        items_height = (
            sizer.GetMinSize().height
            if sizer is not None
            else self.list.GetBestSize().height
        )
        self.list.SetVirtualSize(wx.Size(-1, items_height))

        width = tokens.scaled(self.WIDTH)
        width = min(width, max(tokens.scaled(200), area.width - tokens.scaled(16)))

        chrome = tokens.scaled(self.MARGIN + self.PADDING) * 2 + tokens.scaled(
            self.PADDING
        )
        wanted = header_height + items_height + chrome
        limit = min(
            area.height - tokens.scaled(24),
            header_height + tokens.scaled(self.LIST_HEIGHT) + chrome,
        )
        # Clamping is what makes a long menu scroll rather than lose its tail:
        # the virtual size above stays at the full item height either way.
        self.SetSize(wx.Size(width, max(tokens.scaled(64), min(wanted, limit))))
        self.Layout()
        self.list.FitInside()

    def popup_at(self, position: wx.Point) -> None:
        """Show the menu at a screen point, clamped inside the display."""
        self.layout()
        area = self.work_area()
        size = self.GetSize()
        point = wx.Point(position)
        if point.x < 0 or point.y < 0:
            point = wx.Point(
                area.x + (area.width - size.width) // 2,
                area.y + (area.height - size.height) // 3,
            )
        point.x = max(area.x, min(point.x, area.x + area.width - size.width))
        point.y = max(area.y, min(point.y, area.y + area.height - size.height))
        self.SetPosition(point)
        self.Popup()
        try:
            self.search.field.text.SetFocus()
        except Exception:  # pragma: no cover - platform boundary
            log.debug("Could not focus the menu search field", exc_info=True)

    # -- behaviour -----------------------------------------------------------
    def _activate(self, item: MenuItem) -> None:
        """Run a row and dismiss the menu, in that order for a live target."""
        target = self.target
        parent = self.GetParent()
        self.Dismiss()
        if item.action == ACTION_APPEARANCE:
            self._open_appearance(target)
            return
        if item.action in _LAYOUT_ACTIONS:
            self._run_layout_action(item, target, parent)
            return
        if item.action:
            # Includes ACTION_MOVE_INTO_GROUP: the owner knows which tab was
            # right-clicked, so it -- not the menu -- opens the group picker.
            widgets.invoke(self.on_action, item.action, item)
            return
        if item.surface:
            widgets.invoke(self.on_surface, item.surface)
            return
        if item.command:
            widgets.invoke(self.on_command, item.command)

    def _run_layout_action(
        self, item: MenuItem, target: Optional[wx.Window], parent: Optional[wx.Window]
    ) -> None:
        """Collapse, expand, show, or hide, in the one direction the row names."""
        method, value = _LAYOUT_ACTIONS[item.action]
        host = _layout_host(target, method) or _layout_host(parent, method)
        if host is None:
            log.warning("Nothing in this window can %s for %r", method, item.label)
            return
        try:
            getattr(host, method)(value)
            host.Layout()
        except Exception:  # pragma: no cover - host boundary
            log.exception("The menu row %r could not change the layout", item.label)

    def _open_appearance(self, target: Optional[wx.Window]) -> None:
        """Open the app's element appearance editor for the raised control."""
        if target is None:
            return
        try:
            from amulet_map_editor.api.wx.ui import element_appearance

            element_appearance.open_element_appearance(target)
        except Exception:  # pragma: no cover - dialog boundary
            log.exception("Could not open the element appearance editor")

    def _focusable(self) -> List[_MenuRow]:
        """Return the rows the keyboard can actually land on."""
        return [row for row in self._rows if row.IsEnabled()]

    def _move_highlight(self, delta: int) -> None:
        rows = self._focusable()
        if not rows:
            return
        self._highlight = max(0, min(len(rows) - 1, self._highlight + delta))
        row = rows[self._highlight]
        row.SetFocus()
        try:
            self.list.ScrollChildIntoView(row)
        except Exception:  # pragma: no cover - platform boundary
            log.debug("Could not scroll a menu row into view", exc_info=True)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        rows = self._focusable()
        if code == wx.WXK_ESCAPE:
            self.Dismiss()
            return
        if code == wx.WXK_DOWN:
            focus = wx.Window.FindFocus()
            if focus in rows:
                self._highlight = rows.index(focus)
                self._move_highlight(1)
            elif rows:
                self._highlight = 0
                rows[0].SetFocus()
            return
        if code == wx.WXK_UP:
            focus = wx.Window.FindFocus()
            if focus in rows:
                self._highlight = rows.index(focus)
                self._move_highlight(-1)
            return
        if code == wx.WXK_RETURN and rows:
            focus = wx.Window.FindFocus()
            if focus not in rows:
                rows[0].activate()
                return
        event.Skip()

    def OnDismiss(self) -> None:  # noqa: N802 - wx API spelling
        """Hand the keyboard back, then retire the popup.

        A dismissed ``wx.PopupTransientWindow`` is only hidden, so it is
        destroyed after the current event finishes: leaving one per right-click
        alive would keep a theme listener and a search state for every menu the
        session ever opened.
        """
        try:
            if self.target is not None and not self.target.IsBeingDeleted():
                self.target.SetFocus()
        except RuntimeError:  # pragma: no cover - the window has gone
            pass
        wx.CallAfter(self._retire)

    def _retire(self) -> None:
        """Destroy the popup once wx has finished with the dismiss event."""
        try:
            if not self.IsBeingDeleted():
                self.Destroy()
        except RuntimeError:  # pragma: no cover - already gone
            pass

    def refresh_theme(self) -> None:
        """Re-read the palette for the menu and everything inside it."""
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface)
        for panel in (self.header, self.list):
            panel.SetBackgroundColour(palette.surface)
        self.empty.SetForegroundColour(palette.on_surface_variant)
        for child in (self.heading, self.search, *self._rows):
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        self._refresh_feedback(len(self._rows))
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface)
        width, height = self.GetClientSize()
        margin = tokens.scaled(self.MARGIN)
        card = wx.Rect(margin, margin, width - margin * 2, height - margin * 2)
        radius = tokens.scaled(tokens.RADIUS_MD)
        tokens.draw_elevation(gcdc, card, radius, 3, palette.dark)
        tokens.draw_round_rect(
            gcdc, card, radius, palette.surface, palette.outline_variant
        )
        del gcdc


def open_context_menu(
    parent: wx.Window,
    key: str,
    position: wx.Point,
    *,
    on_surface: Optional[Callable[[str], None]] = None,
    on_command: Optional[Callable[[str], None]] = None,
    on_action: Optional[Callable[[str, MenuItem], None]] = None,
    target: Optional[wx.Window] = None,
) -> Optional[SearchableContextMenu]:
    """Open one searchable context menu at a screen point.

    Returns the live menu so a caller can keep a reference while it is up, or
    ``None`` when ``key`` names no menu -- an unknown key must not take a
    right-click silently.
    """
    if menu(key) is None:
        log.warning("No context menu named %r", key)
        return None
    popup = SearchableContextMenu(
        parent,
        key,
        on_surface=on_surface,
        on_command=on_command,
        on_action=on_action,
        target=target,
    )
    popup.popup_at(position)
    return popup


# ----------------------------------------------------------------------------
# the move-into-group picker
# ----------------------------------------------------------------------------


class _GroupRow(wx.Control, widgets._Interactive):
    """One tab group in the picker: colour, name, and honest member count.

    The row the tab is already in is drawn in the primary container, which is
    the selection state the design gives every decorated select.
    """

    HEIGHT = 40
    SWATCH = 14
    PADDING = 10

    def __init__(
        self,
        parent: wx.Window,
        group: GroupChoice,
        *,
        selected: bool = False,
        on_choose: Optional[Callable[[GroupChoice], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.group = group
        self.selected = bool(selected)
        self.on_choose = on_choose
        name = f"{group.name}, {group.detail}"
        if self.selected:
            name = f"{name}, current group"
        self._install(name, listen=False)
        self._bind_interaction()
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        return wx.Size(tokens.scaled(240), tokens.scaled(self.HEIGHT))

    def activate(self) -> None:
        """Move the tab into this group."""
        widgets.invoke(self.on_choose, self.group)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(tokens.RADIUS_SM)
        label_ink = palette.on_surface
        detail_ink = palette.on_surface_variant
        if self.selected:
            tokens.draw_round_rect(gcdc, rect, radius, palette.primary_container)
            label_ink = palette.on_primary_container
            detail_ink = palette.on_primary_container
        elif self._pressed or self._hovered or self.HasFocus():
            tokens.draw_round_rect(gcdc, rect, radius, palette.surface_container_high)
        inner = tokens.scaled(self.PADDING)
        swatch = tokens.scaled(self.SWATCH)
        colour = widgets.colour_of(self.group.colour, palette.primary)
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(inner, (height - swatch) // 2, swatch, swatch),
            tokens.scaled(4),
            colour,
            palette.outline_variant,
        )
        text_left = inner + swatch + tokens.scaled(10)
        detail_font = tokens.mono_font(self, widgets.point_size(11))
        gcdc.SetFont(detail_font)
        detail_width = gcdc.GetTextExtent(self.group.detail)[0]
        gcdc.SetTextForeground(detail_ink)
        gcdc.DrawText(
            self.group.detail,
            max(text_left, width - inner - detail_width),
            (height - gcdc.GetCharHeight()) // 2,
        )
        gcdc.SetFont(tokens.font(self, widgets.point_size(13)))
        gcdc.SetTextForeground(label_ink)
        available = max(0, width - text_left - inner - detail_width - tokens.scaled(10))
        gcdc.DrawText(
            widgets.elide(gcdc, self.group.name, available),
            text_left,
            (height - gcdc.GetCharHeight()) // 2,
        )
        if self.HasFocus():
            widgets.draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class _GroupPicker(widgets.AnchoredPopup):
    """The anchored picker behind "Move… into group…".

    A menu that inlines one row per group grows without bound, so the move
    target is chosen here instead: the existing groups with their colour and
    member count, a path to create a new one, an honest empty state when there
    are none, and the same search field with the regex builder that every other
    list in the product carries.

    It is a searchable select, so it is decorated like one: the query is cleared
    on every open, the regex opt-in the user chose is kept, the feedback line
    reports the search mode, and the group the tab is already in is drawn as the
    selected row.
    """

    def __init__(
        self,
        parent: wx.Window,
        anchor: wx.Window,
        groups: Sequence[GroupChoice],
        *,
        current: str = "",
        on_choose: Optional[Callable[[Optional[GroupChoice]], None]] = None,
        on_create: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, anchor, width=300, max_height=360)
        self.groups = tuple(groups)
        self.current = str(current or "")
        self.on_choose = on_choose
        self.on_create = on_create
        self.state = SearchState(label="Tab groups")
        restore_search("select:tabGroups", self.state)
        self._rows: List[_GroupRow] = []
        palette = tokens.palette()

        heading = widgets.SectionLabel(self.header, "Move into group")
        self.search = widgets.SearchBar(
            self.header,
            "Search tab groups",
            self.state,
            on_change=self._on_search,
            compact=True,
        )
        header_sizer = wx.BoxSizer(wx.VERTICAL)
        header_sizer.Add(heading, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(6))
        header_sizer.Add(self.search, 0, wx.EXPAND)
        self.header.SetSizer(header_sizer)

        self.empty = wx.StaticText(self.content, label="")
        self.empty.SetName("Tab group results")
        self.empty.SetForegroundColour(palette.on_surface_variant)
        self.content_sizer.Add(self.empty, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(8))
        self.ungrouped = widgets.StudioButton(
            self.content,
            "Leave it ungrouped",
            variant="text",
            on_click=lambda: self._choose(None),
            name="Leave this tab ungrouped",
        )
        self.create = widgets.StudioButton(
            self.content,
            "Create a new group…",
            variant="outlined",
            on_click=self._create,
            name="Create a new tab group",
        )
        self.content_sizer.Add(
            self.ungrouped, 0, wx.EXPAND | wx.TOP, tokens.scaled(tokens.SPACE_SM)
        )
        self.content_sizer.Add(
            self.create, 0, wx.EXPAND | wx.TOP, tokens.scaled(tokens.SPACE_XS)
        )
        self._rebuild()

    def visible_groups(self) -> Tuple[GroupChoice, ...]:
        """Return the groups matching the picker's own query."""
        return tuple(
            self.state.filter(
                self.groups, key=lambda item: f"{item.name} {item.detail}"
            )
        )

    def decorated(self) -> Tuple[SelectOption, ...]:
        """Return the picker's rows as the design decorates a select's options.

        The picker draws its own rows, because a group carries a colour and a
        member count a plain option does not; this reports the same decoration
        the shared builder would produce, so the selection state and the
        surviving order can be checked without a display.
        """
        names = [group.name for group in self.groups]
        chosen = next(
            (group.name for group in self.groups if group.group_id == self.current), ""
        )
        swatches = {group.name: group.colour for group in self.groups}
        return decorate_select(names, chosen, self.state, swatches=swatches)

    def _rebuild(self) -> None:
        for row in self._rows:
            self.content_sizer.Detach(row)
            row.Destroy()
        self._rows = []
        visible = self.visible_groups()
        for index, group in enumerate(visible):
            row = _GroupRow(
                self.content,
                group,
                selected=bool(self.current) and group.group_id == self.current,
                on_choose=self._choose,
            )
            self.content_sizer.Insert(
                index, row, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(2)
            )
            self._rows.append(row)
        if not self.groups:
            self.empty.SetLabel(
                "No tab groups yet. Create one to move this tab into it."
            )
            self.empty.Show()
        elif not visible:
            self.empty.SetLabel(self.state.describe_matches(0, "tab group"))
            self.empty.Show()
        else:
            self.empty.SetLabel("")
            self.empty.Hide()
        self._refresh_feedback()
        self.content.FitInside()
        self.layout()

    def _refresh_feedback(self) -> None:
        """Show the line the design puts under a select's search field."""
        feedback = getattr(self.search, "feedback", None)
        if feedback is None:  # pragma: no cover - the bar always builds one
            return
        try:
            feedback.SetLabel(select_feedback(self.state))
            self.search.Layout()
        except RuntimeError:  # pragma: no cover - destroyed mid-update
            return

    def _on_search(self, _state: SearchState) -> None:
        remember_regex_mode("select:tabGroups", self.state)
        self._rebuild()

    def _choose(self, group: Optional[GroupChoice]) -> None:
        self.Dismiss()
        widgets.invoke(self.on_choose, group)

    def _create(self) -> None:
        self.Dismiss()
        widgets.invoke(self.on_create)


def open_group_picker(
    parent: wx.Window,
    anchor: wx.Window,
    *,
    groups: Optional[Sequence[GroupChoice]] = None,
    surface_id: str = "main-window",
    current: str = "",
    on_choose: Optional[Callable[[Optional[GroupChoice]], None]] = None,
    on_create: Optional[Callable[[], None]] = None,
) -> _GroupPicker:
    """Open the anchored "Move… into group…" picker beside ``anchor``.

    ``groups`` defaults to the persisted groups of ``surface_id``, so a caller
    that has no list of its own still shows the real workspace rather than a
    placeholder.  ``current`` is the group the tab is already in, drawn as the
    selected row so the picker says where the tab is before it is moved.
    """
    choices = tuple(groups) if groups is not None else tab_groups(surface_id)
    picker = _GroupPicker(
        parent,
        anchor,
        choices,
        current=current,
        on_choose=on_choose,
        on_create=on_create,
    )
    picker.on_dismiss = lambda: wx.CallAfter(picker.Destroy)
    picker.popup()
    return picker
