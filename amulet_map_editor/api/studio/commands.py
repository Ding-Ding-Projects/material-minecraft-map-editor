"""Every non-surface action the Studio can run, as one addressable registry.

A *command* is something the shell does: save, undo, switch a view, flip the
theme.  A *surface* is a window it opens, and lives in
:mod:`amulet_map_editor.api.studio.surfaces`.  Keeping the two apart is what
lets a ribbon button, a context-menu row, and a palette result all name one
target without any of them having to know how the target is carried out.

This module is deliberately pure data plus lookup: no wxPython at import time,
so the registry can be read, searched, and asserted on without a display.  The
one function that genuinely needs wx -- :func:`accelerator_table` -- imports it
where it is used.

**Accelerators are never invented here.**  :data:`ACCELERATORS` mirrors the
shared table in :mod:`amulet_map_editor.api.studio.context_menu`, which is what
the right-click menus actually draw beside each row.  That module imports wx at
module scope, so it cannot be read from here at import time; the mirror is
therefore checked rather than assumed -- :func:`mismatched_accelerators` reports
any disagreement, so the drawn shortcut and the installed one cannot drift apart
unnoticed.  A command with no real binding carries an empty string, because a
shortcut printed beside an action that does not respond to it is worse than no
shortcut at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from amulet_map_editor.api.studio.search import SearchState

__all__ = [
    "ACCELERATORS",
    "ALIASES",
    "COMMANDS",
    "COMMAND_GROUPS",
    "CHAR_HOOK_ACCELERATORS",
    "CONDITIONS",
    "CONDITION_REASONS",
    "REQUIREMENTS",
    "Command",
    "accelerator",
    "accelerator_entries",
    "accelerator_table",
    "command",
    "group",
    "keys",
    "label_for",
    "mismatched_accelerators",
    "requirements",
    "resolve",
    "search",
    "unavailable_hint",
    "unmet_reason",
]


@dataclass(frozen=True)
class Command:
    """One action the shell can run, as every surface refers to it."""

    key: str
    label: str
    group: str
    accel: str = ""

    def search_text(self) -> str:
        """Return every word a palette or menu search should find this by."""
        return " ".join(
            part for part in (self.label, self.group, self.accel, self.key) if part
        )

    def accessible_name(self) -> str:
        """Return the screen-reader name for a control that runs this."""
        parts = [self.label, self.group]
        if self.accel:
            parts.append(self.accel)
        return " — ".join(part for part in parts if part)


#: The command groups, in the order a grouped listing shows them.
COMMAND_GROUPS: Tuple[str, ...] = (
    "Project",
    "Editing",
    "Selection",
    "Chunks",
    "Transform",
    "Operations",
    "View",
    "Application",
)


#: Every keyboard binding the application really has, for commands and for
#: surfaces alike.  The two kinds of key share one namespace because they never
#: collide and because a reader asking "what does Ctrl+Shift+H do" should not
#: have to know which kind answers.  Mirrors ``context_menu.ACCELERATORS``.
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
        # the palette, reachable from anywhere including a focused text field
        "openPalette": "Ctrl+Shift+F",
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


#: Bindings delivered by a character hook on the top-level window rather than
#: by the accelerator table.  An accelerator is swallowed by a focused text
#: control, and "from anywhere in the application" has to include the moment
#: the user is typing, so these keys are deliberately left out of the table to
#: avoid firing the same action twice.
CHAR_HOOK_ACCELERATORS: Tuple[str, ...] = ("openPalette", "palette")


#: ``key``, ``label``, ``group`` for every command, in registry order.
_DEFINITIONS: Tuple[Tuple[str, str, str], ...] = (
    # -- Project -------------------------------------------------------------
    ("save", "Save changes", "Project"),
    ("openProject", "Open a project", "Project"),
    ("closeProject", "Close this project", "Project"),
    ("openBackstage", "Open the project screen", "Project"),
    ("backToWorkspace", "Back to the workspace", "Project"),
    ("export", "Export the selection", "Project"),
    ("setExportFormat", "Choose the structure export format", "Project"),
    ("importFile", "Import a structure file", "Project"),
    ("importChunks", "Import chunks from another world", "Project"),
    ("convertWorld", "Convert this world to another platform", "Project"),
    ("openOperationsFolder", "Open the operations folder", "Project"),
    ("openInEditor", "Open the exported folder in the external editor", "Project"),
    # -- Editing -------------------------------------------------------------
    ("undo", "Undo", "Editing"),
    ("redo", "Redo", "Editing"),
    ("copy", "Copy the selected area", "Editing"),
    ("cut", "Cut the selected area", "Editing"),
    ("paste", "Paste the copied area", "Editing"),
    ("delete", "Delete the blocks in the selection", "Editing"),
    ("selectAll", "Select all", "Editing"),
    # -- Selection -----------------------------------------------------------
    ("addBox", "Add a selection box", "Selection"),
    ("removeBox", "Remove the active selection box", "Selection"),
    ("duplicateBox", "Duplicate the active selection box", "Selection"),
    ("deselectAllBoxes", "Deselect every selection box", "Selection"),
    ("moveBox", "Move the active selection box", "Selection"),
    ("movePoint1", "Move selection point 1", "Selection"),
    ("movePoint2", "Move selection point 2", "Selection"),
    (
        "setSelectionBounds",
        "Move the active selection box to the typed coordinates",
        "Selection",
    ),
    # -- Chunks --------------------------------------------------------------
    ("createChunks", "Create the empty chunks in the selection", "Chunks"),
    ("deleteChunks", "Delete the selected chunks", "Chunks"),
    ("deleteUnselectedChunks", "Delete every unselected chunk", "Chunks"),
    # -- Transform -----------------------------------------------------------
    ("rotate", "Rotate the selection", "Transform"),
    ("flip", "Flip the selection", "Transform"),
    # -- Operations ----------------------------------------------------------
    ("runOperation", "Run the selected operation", "Operations"),
    ("reloadPlugins", "Reload the Python operations", "Operations"),
    # -- View ----------------------------------------------------------------
    ("projection", "Switch the viewport projection", "View"),
    ("frameDimension", "Frame this dimension in the viewport", "View"),
    ("cameraSpeed", "Set the camera speed", "View"),
    ("setDimension", "Switch dimension", "View"),
    ("togglePane", "Show or hide the properties pane", "View"),
    ("toggleRibbon", "Collapse or expand the ribbon", "View"),
    ("toggleTheme", "Switch between the light and dark themes", "View"),
    ("setDensity", "Set the interface density", "View"),
    # -- Application ---------------------------------------------------------
    ("openPalette", "Tell me what to do", "Application"),
    ("openPrefs", "Open options", "Application"),
    ("openNotifications", "Open the notification history", "Application"),
    ("openHistory", "Open the version history", "Application"),
    ("openChangelog", "Open the changelog", "Application"),
    ("openDocs", "Open the documentation", "Application"),
    ("openMemory", "Open the Memory Console", "Application"),
    ("openRegex", "Open the regular expression builder", "Application"),
    ("updateRestart", "Restart to install the staged update", "Application"),
)


COMMANDS: Tuple[Command, ...] = tuple(
    Command(key, label, group_name, ACCELERATORS.get(key, ""))
    for key, label, group_name in _DEFINITIONS
)

_BY_KEY: Mapping[str, Command] = MappingProxyType(
    {entry.key: entry for entry in COMMANDS}
)


#: Second names for a command, resolved by :func:`resolve` before dispatch.
#:
#: They exist because two surfaces written at different times spell the same
#: action differently -- the backstage says ``close_project`` where the ribbon
#: says ``closeProject`` -- and because renaming a key in somebody else's module
#: would silently break the button that uses it.  An alias never appears in a
#: listing: one action deserves exactly one row in the palette.
#:
#: ``deselectBox`` is here rather than in :data:`_DEFINITIONS` because the 3D
#: editor's ``ACT_DESELECT_BOX`` and this registry's ``removeBox`` do the same
#: thing to the same selection -- both drop the last box from it -- and two rows
#: in the palette for one action would be two names for one outcome.  The
#: viewport menu keeps its own label, which is the design's wording for it.
ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "deselectBox": "removeBox",
        "saveProject": "save",
        "save_project": "save",
        "close_project": "closeProject",
        "export_selection": "export",
        "convert_world": "convertWorld",
        "update_restart": "updateRestart",
        "open_backstage": "openBackstage",
        "back_to_workspace": "backToWorkspace",
        "select_all": "selectAll",
        "toggle_pane": "togglePane",
        "toggle_ribbon": "toggleRibbon",
        "toggle_theme": "toggleTheme",
        "set_density": "setDensity",
        "set_dimension": "setDimension",
        "camera_speed": "cameraSpeed",
    }
)


#: The conditions a command can require before it is able to do anything.
#:
#: These are deliberately about the *world*, not about the interface: whether a
#: level is open, whether the 3D editor is attached to it, whether the user has
#: drawn a selection, whether anything has been copied, and how deep the level's
#: own undo stack is.  The shell reads each one from the live editor rather than
#: from Studio state, so a control is disabled because the world cannot answer
#: the command, never because a panel has not been told about it yet.
CONDITIONS: Tuple[str, ...] = (
    "project",
    "editor",
    "selection",
    "clipboard",
    "undo",
    "redo",
)


#: Why each condition being unmet stops a command, phrased as the clause a
#: disabled control puts in its tooltip.  A control the user cannot press has to
#: say which condition it is waiting for; "unavailable" on its own reads as a
#: defect in the application rather than as a state of their world.
CONDITION_REASONS: Mapping[str, str] = MappingProxyType(
    {
        "project": "no world is open",
        "editor": "this world has no 3D editor attached",
        "selection": "nothing is selected",
        "clipboard": "nothing has been copied yet",
        "undo": "there is nothing to undo",
        "redo": "there is nothing to redo",
    }
)


#: What each command needs before it can run, in the order it should be
#: reported.  A command absent from this table needs nothing and is therefore
#: always available: switching a theme, opening the palette, and reading the
#: changelog do not depend on a world.
#:
#: ``editor`` implies ``project`` and is listed alone where it applies, because
#: naming both would make a disabled tile say two things when the first one is
#: the whole story.
REQUIREMENTS: Mapping[str, Tuple[str, ...]] = MappingProxyType(
    {
        # -- Project ---------------------------------------------------------
        "save": ("editor",),
        "closeProject": ("project",),
        "convertWorld": ("project",),
        "openInEditor": ("project",),
        "export": ("editor", "selection"),
        "importFile": ("editor",),
        "importChunks": ("editor", "selection"),
        # -- Editing ---------------------------------------------------------
        "undo": ("editor", "undo"),
        "redo": ("editor", "redo"),
        "copy": ("editor", "selection"),
        "cut": ("editor", "selection"),
        "paste": ("editor", "clipboard"),
        "delete": ("editor", "selection"),
        "selectAll": ("editor",),
        "goto": ("editor",),
        # -- Selection -------------------------------------------------------
        "addBox": ("editor",),
        "removeBox": ("editor", "selection"),
        "duplicateBox": ("editor", "selection"),
        "deselectAllBoxes": ("editor", "selection"),
        "moveBox": ("editor", "selection"),
        "movePoint1": ("editor", "selection"),
        "movePoint2": ("editor", "selection"),
        # There has to be a box before its corners can be typed: the six boxes
        # in Selection > Coordinates describe the active selection box, and with
        # nothing selected there is no box for them to describe.
        "setSelectionBounds": ("editor", "selection"),
        # -- Chunks ----------------------------------------------------------
        "createChunks": ("editor", "selection"),
        "deleteChunks": ("editor", "selection"),
        "deleteUnselectedChunks": ("editor", "selection"),
        # -- Transform -------------------------------------------------------
        "rotate": ("editor", "selection"),
        "flip": ("editor", "selection"),
        # -- Operations ------------------------------------------------------
        # ``editor`` alone, and not ``("editor", "selection")`` like its
        # neighbours, is a decision rather than an omission.  This command does
        # two things: it brings the Operation tool to the front, and it runs
        # whatever that tool has chosen.  Only the second half needs a
        # selection -- every operation is handed ``selection.selection_group``
        # and an empty group means it acts on nothing -- and gating the whole
        # command would leave the user unable to reach the list of operations
        # until after they had selected something, which is the wrong way
        # round.  So the requirement stays at ``editor`` and
        # ``StudioShell._run_active_operation`` declines the *run* when nothing
        # is selected, naming the tool's own Run button so an operation that
        # genuinely ignores the selection is still reachable.
        "runOperation": ("editor",),
        "reloadPlugins": ("editor",),
        # -- View ------------------------------------------------------------
        "setDimension": ("project",),
        "frameDimension": ("editor",),
    }
)


def resolve(key: object) -> str:
    """Return the canonical key for ``key``, following one alias hop.

    An unknown key comes back unchanged so the caller can report exactly what
    it was asked for rather than a value this function invented.
    """
    name = str(key or "").strip()
    return ALIASES.get(name, name)


#: Readable names for the keys :data:`REQUIREMENTS` covers that are surfaces
#: rather than commands.  The shell routes ``goto`` to the editor's own camera
#: dialog, so it needs a precondition and a sentence like any command, but it
#: has no row in :data:`COMMANDS` to take a label from.
_SURFACE_LABELS: Mapping[str, str] = MappingProxyType({"goto": "Teleport the camera"})


def label_for(key: object) -> str:
    """Return the visible name for a command or a routed surface key."""
    resolved = resolve(key)
    entry = _BY_KEY.get(resolved)
    if entry is not None:
        return entry.label
    return _SURFACE_LABELS.get(resolved, resolved)


def requirements(key: object) -> Tuple[str, ...]:
    """Return what ``key`` needs before it can run, aliases included."""
    return REQUIREMENTS.get(resolve(key), ())


def unmet_reason(condition: str) -> str:
    """Return the clause naming why ``condition`` stops a command.

    An unknown condition returns a statement that says exactly that, rather
    than an empty string a caller would splice into a sentence and produce
    "Save changes is unavailable: ." from.
    """
    name = str(condition)
    return CONDITION_REASONS.get(name, f"the condition {name!r} is not met")


def unavailable_hint(key: object, unmet: Iterable[str]) -> str:
    """Return the tooltip a control shows while ``key`` cannot be run.

    ``unmet`` is the conditions that failed, in report order.  The result names
    the command and every condition it is waiting for, because a user looking at
    a greyed-out tile is asking exactly one question and this is the answer to
    it.  An empty ``unmet`` returns an empty string: a command that can run has
    nothing to explain and keeps the hint it shipped with.
    """
    reasons = [unmet_reason(name) for name in unmet]
    if not reasons:
        return ""
    label = label_for(key)
    if len(reasons) == 1:
        return f"{label} is unavailable: {reasons[0]}."
    joined = ", ".join(reasons[:-1]) + f", and {reasons[-1]}"
    return f"{label} is unavailable: {joined}."


def command(key: object) -> Optional[Command]:
    """Return the command registered under ``key``, aliases included."""
    return _BY_KEY.get(resolve(key))


def keys() -> Tuple[str, ...]:
    """Return every canonical command key, in registry order."""
    return tuple(entry.key for entry in COMMANDS)


def group(name: str) -> Tuple[Command, ...]:
    """Return every command in one group, in registry order."""
    wanted = str(name)
    return tuple(entry for entry in COMMANDS if entry.group == wanted)


def search(state: SearchState) -> Tuple[Command, ...]:
    """Return the commands matching a search field's current query."""
    return tuple(state.filter(COMMANDS, key=lambda entry: entry.search_text()))


def accelerator(key: object) -> str:
    """Return the keyboard binding for a command or surface key.

    An empty string is the honest answer for anything unbound: a menu row that
    shows no shortcut teaches nothing, whereas one showing a key that does not
    work teaches something false.
    """
    return ACCELERATORS.get(resolve(key), "")


def mismatched_accelerators() -> Tuple[Tuple[str, str, str], ...]:
    """Return every key where this table and the menus' table disagree.

    Each row is ``(key, this module's text, context_menu's text)``, with an
    empty string where one of the two has no entry.  The palette prints what
    this module holds and the context menus print what theirs holds, so a
    disagreement means one of the two is lying to the reader; an empty result
    is the proof that they agree.  Keys in :data:`CHAR_HOOK_ACCELERATORS` that
    only exist here are excluded, because the menus have no command row for the
    palette itself.
    """
    try:
        from amulet_map_editor.api.studio import context_menu
    except Exception:  # pragma: no cover - the menus need wx, this module does not
        return ()
    theirs: Mapping[str, str] = getattr(context_menu, "ACCELERATORS", {})
    rows: List[Tuple[str, str, str]] = []
    for name in sorted(set(ACCELERATORS) | set(theirs)):
        mine = ACCELERATORS.get(name, "")
        other = theirs.get(name, "")
        if mine == other:
            continue
        if not other and name in CHAR_HOOK_ACCELERATORS:
            continue
        rows.append((name, mine, other))
    return tuple(rows)


def accelerator_entries(
    identifiers: Mapping[str, int],
) -> List[Tuple[int, int, int]]:
    """Build ``wx.AcceleratorTable`` rows for the ids the caller has bound.

    ``identifiers`` maps a command or surface key to the ``wx`` id a handler is
    bound to.  A row is produced only when the key has both a binding and an
    id, so an accelerator is installed exactly when there is something for it to
    fire.  Keys delivered by a character hook are skipped here on purpose --
    see :data:`CHAR_HOOK_ACCELERATORS`.
    """
    from amulet_map_editor.api.studio.context_menu import parse_accelerator

    entries: List[Tuple[int, int, int]] = []
    for name, text in ACCELERATORS.items():
        if name in CHAR_HOOK_ACCELERATORS:
            continue
        identifier = identifiers.get(name)
        if identifier is None:
            continue
        parsed = parse_accelerator(text)
        if parsed is None:
            continue
        entries.append((parsed[0], parsed[1], int(identifier)))
    return entries


def accelerator_table(identifiers: Mapping[str, int]) -> Any:
    """Return the ``wx.AcceleratorTable`` the frame installs.

    Kept here rather than in the shell so the one table the application runs on
    is built from the one table the menus draw from.
    """
    import wx

    return wx.AcceleratorTable(accelerator_entries(identifiers))


def bindable_keys() -> Tuple[str, ...]:
    """Return the keys the frame should create an id and a handler for."""
    return tuple(name for name in ACCELERATORS if name not in CHAR_HOOK_ACCELERATORS)


def as_dicts() -> Tuple[Dict[str, str], ...]:
    """Return the registry as plain dictionaries, for export and for tests."""
    return tuple(
        {
            "key": entry.key,
            "label": entry.label,
            "group": entry.group,
            "accel": entry.accel,
        }
        for entry in COMMANDS
    )
