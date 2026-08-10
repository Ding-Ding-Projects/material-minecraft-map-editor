"""Searchable right-click menus for every Amulet Studio surface.

A platform ``wx.Menu`` cannot be searched, cannot show a regular-expression
builder, and cannot be styled to match the rest of the shell, so Studio draws
its own: a 300px popover with an uppercase title, a search field carrying the
regex opt-in and the shared ``.*`` builder, an honest feedback line, and a
scrolling item list whose keyboard accelerators are right-aligned in a
monospaced face.

**Accelerators come from one table.**  :data:`ACCELERATORS` is the single
source for the shell-installed bindings: the menu reads it to draw the text,
and :func:`accelerator_table_entries` turns the same rows into the
``wx.AcceleratorTable`` the shell installs.  Because the drawing and the
binding are generated from one mapping they cannot drift.  Bindings that belong
to the user-configurable 3D editor key groups are read live from that
configuration by :func:`viewport_accelerator`, and an item whose binding cannot
be established shows no accelerator at all rather than a plausible guess.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

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
    "accelerator",
    "accelerator_table_entries",
    "menu",
    "open_context_menu",
    "open_group_picker",
    "tab_groups",
    "viewport_accelerator",
]

#: Local menu actions that neither open a surface nor run a shell command.
ACTION_APPEARANCE = "editAppearance"
ACTION_MOVE_INTO_GROUP = "moveIntoGroup"


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
    key.
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
    menu rows show no accelerator instead of the shipped default the user may
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
    ``accel`` is filled from the shared table unless the caller states one,
    which is how the drawn key and the installed key stay the same key.
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
    """Build a row, resolving its accelerator from the shared table."""
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


def _ribbon_menu() -> Tuple[MenuItem, ...]:
    return (
        _item(
            "Collapse or expand the ribbon",
            command="toggleRibbon",
            hint="Hide the command panel and keep the tab strip",
        ),
        _item("Show or hide the properties pane", command="togglePane"),
        _item("Command palette…", surface="palette"),
        _item("Options…", surface="prefs"),
        _item("Key configuration…", surface="controls"),
        _item("Regex builder…", surface="regex"),
        _item("Documentation…", surface="docs"),
        _item("Tabs and groups…", surface="tabManager"),
        _APPEARANCE,
    )


def _navigator_menu() -> Tuple[MenuItem, ...]:
    return (
        _item("Teleport the camera…", surface="goto"),
        _item("World information…", surface="worldInfo"),
        _item("Chunk inspector…", surface="chunkInspector"),
        _item("Render layers…", surface="renderLayers"),
        _item("Height limits…", surface="heightLimits"),
        _item("Force-loaded chunks…", surface="forceLoaded"),
        _item("Biome map…", surface="biomeMap"),
        _APPEARANCE,
    )


def _viewport_menu() -> Tuple[MenuItem, ...]:
    return (
        _item(
            "Inspect block…",
            surface="nbt",
            accel=viewport_accelerator("ACT_INSPECT_BLOCK"),
        ),
        _item("Copy the selection", command="copy"),
        _item("Cut the selection", command="cut"),
        _item("Paste here", command="paste"),
        _item("Delete the selected blocks", command="delete"),
        _item("Select all", command="selectAll"),
        _item("Add a selection box", command="addBox"),
        _item(
            "Toggle projection",
            command="projection",
            accel=viewport_accelerator("ACT_CHANGE_PROJECTION"),
        ),
        _item("Camera speed…", command="cameraSpeed"),
        _item("Teleport the camera…", surface="goto"),
        _item("View settings…", surface="viewControls"),
        _item("Render layers…", surface="renderLayers"),
        _item("Measure…", surface="measure"),
        _APPEARANCE,
    )


def _tab_menu() -> Tuple[MenuItem, ...]:
    return (
        _MOVE_INTO_GROUP,
        _item("Tabs and groups…", surface="tabManager"),
        _item(
            "Rename this tab…",
            surface="tabManager",
            hint="Rename through the tab manager",
        ),
        _item(
            "Pin or unpin this tab",
            surface="tabManager",
            hint="Pinned tabs stay visible when ordinary tabs overflow",
        ),
        _item("Close tabs containing text…", surface="tabManager"),
        _item("Close tabs not containing text…", surface="tabManager"),
        _APPEARANCE,
    )


def _tab_group_menu() -> Tuple[MenuItem, ...]:
    return (
        _MOVE_INTO_GROUP,
        _item("Rename this group…", surface="tabManager"),
        _item("Collapse or expand this group", surface="tabManager"),
        _item("Tabs and groups…", surface="tabManager"),
        _item("Close tabs containing text…", surface="tabManager"),
        _item("Close tabs not containing text…", surface="tabManager"),
        _APPEARANCE,
    )


def _pane_menu() -> Tuple[MenuItem, ...]:
    return (
        _item("Hide the properties pane", command="togglePane"),
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
#: value is the menu's uppercase title and its rows.
CTX_MENUS: Dict[str, Tuple[str, Tuple[MenuItem, ...]]] = {
    "ribbon": ("Ribbon", _ribbon_menu()),
    "navigator": ("Navigator", _navigator_menu()),
    "viewport": ("Viewport", _viewport_menu()),
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


def refresh_viewport_accelerators() -> None:
    """Re-read the 3D editor key group into the viewport menu.

    The viewport's bindings can change while the application is running -- the
    key configuration dialog writes them -- so the rows are rebuilt rather than
    left showing whatever was true when this module was first imported.
    """
    CTX_MENUS["viewport"] = ("Viewport", _viewport_menu())


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
    user hears the shortcut the sighted user reads.
    """

    HEIGHT = 32
    PADDING = 10

    def __init__(
        self,
        parent: wx.Window,
        item: MenuItem,
        *,
        on_activate: Optional[Callable[[MenuItem], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.item = item
        self.on_activate = on_activate
        name = item.label
        if item.accel:
            name = f"{name}, {item.accel}"
        self._install(name, listen=False)
        self._bind_interaction()
        if item.hint:
            self.SetToolTip(item.hint)
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        return wx.Size(tokens.scaled(200), tokens.scaled(self.HEIGHT))

    def activate(self) -> None:
        """Run this row's destination."""
        widgets.invoke(self.on_activate, self.item)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(7)
        if self._pressed:
            fill = tokens.blend(palette.surface_container_high, palette.on_surface, 0.1)
        elif self._hovered or self.HasFocus():
            fill = palette.surface_container_high
        else:
            fill = None
        if fill is not None:
            tokens.draw_round_rect(gcdc, rect, radius, fill)
        inner = tokens.scaled(self.PADDING)
        accel_width = 0
        if self.item.accel:
            gcdc.SetFont(tokens.mono_font(self, widgets.point_size(10)))
            gcdc.SetTextForeground(palette.on_surface_variant)
            accel_width = gcdc.GetTextExtent(self.item.accel)[0]
            accel_height = gcdc.GetCharHeight()
            gcdc.DrawText(
                self.item.accel,
                max(inner, width - inner - accel_width),
                (height - accel_height) // 2,
            )
            accel_width += tokens.scaled(12)
        gcdc.SetFont(tokens.font(self, widgets.point_size(12)))
        gcdc.SetTextForeground(palette.on_surface)
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
    pattern is reported instead of silently emptying the menu.
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

    def _rebuild(self) -> None:
        """Draw the rows that survive the query, plus an honest empty state."""
        for row in self._rows:
            self.list_sizer.Detach(row)
            row.Destroy()
        self._rows = []
        visible = self.visible_items()
        for item in visible:
            row = _MenuRow(self.list, item, on_activate=self._activate)
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
        self._highlight = 0
        self.list.FitInside()
        self.layout()

    def _on_search(self, _state: SearchState) -> None:
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
        """Size the popover to its content, bounded by the display."""
        area = self.work_area()
        self.header.Fit()
        self.list.FitInside()
        self.Fit()
        width = tokens.scaled(self.WIDTH)
        width = min(width, max(tokens.scaled(200), area.width - tokens.scaled(16)))
        content = self.GetBestSize().height
        limit = min(
            area.height - tokens.scaled(24),
            self.header.GetBestSize().height
            + tokens.scaled(self.LIST_HEIGHT)
            + tokens.scaled(self.MARGIN + self.PADDING) * 2
            + tokens.scaled(self.PADDING),
        )
        self.SetSize(wx.Size(width, min(content, limit)))
        self.Layout()

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
        self.Dismiss()
        if item.action == ACTION_APPEARANCE:
            self._open_appearance(target)
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

    def _open_appearance(self, target: Optional[wx.Window]) -> None:
        """Open the app's element appearance editor for the raised control."""
        if target is None:
            return
        try:
            from amulet_map_editor.api.wx.ui import element_appearance

            element_appearance.open_element_appearance(target)
        except Exception:  # pragma: no cover - dialog boundary
            log.exception("Could not open the element appearance editor")

    def _move_highlight(self, delta: int) -> None:
        if not self._rows:
            return
        self._highlight = max(0, min(len(self._rows) - 1, self._highlight + delta))
        row = self._rows[self._highlight]
        row.SetFocus()
        try:
            self.list.ScrollChildIntoView(row)
        except Exception:  # pragma: no cover - platform boundary
            log.debug("Could not scroll a menu row into view", exc_info=True)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == wx.WXK_ESCAPE:
            self.Dismiss()
            return
        if code == wx.WXK_DOWN:
            focus = wx.Window.FindFocus()
            if focus in self._rows:
                self._highlight = self._rows.index(focus)
                self._move_highlight(1)
            elif self._rows:
                self._highlight = 0
                self._rows[0].SetFocus()
            return
        if code == wx.WXK_UP:
            focus = wx.Window.FindFocus()
            if focus in self._rows:
                self._highlight = self._rows.index(focus)
                self._move_highlight(-1)
            return
        if code == wx.WXK_RETURN and self._rows:
            focus = wx.Window.FindFocus()
            if focus not in self._rows:
                self._rows[0].activate()
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
    if key == "viewport":
        refresh_viewport_accelerators()
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
    """One tab group in the picker: colour, name, and honest member count."""

    HEIGHT = 40
    SWATCH = 14
    PADDING = 10

    def __init__(
        self,
        parent: wx.Window,
        group: GroupChoice,
        *,
        on_choose: Optional[Callable[[GroupChoice], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.group = group
        self.on_choose = on_choose
        self._install(f"{group.name}, {group.detail}", listen=False)
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
        if self._pressed or self._hovered or self.HasFocus():
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
        gcdc.SetFont(tokens.font(self, widgets.point_size(13)))
        gcdc.SetTextForeground(palette.on_surface)
        detail_font = tokens.mono_font(self, widgets.point_size(11))
        gcdc.SetFont(detail_font)
        detail_width = gcdc.GetTextExtent(self.group.detail)[0]
        gcdc.SetTextForeground(palette.on_surface_variant)
        gcdc.DrawText(
            self.group.detail,
            max(text_left, width - inner - detail_width),
            (height - gcdc.GetCharHeight()) // 2,
        )
        gcdc.SetFont(tokens.font(self, widgets.point_size(13)))
        gcdc.SetTextForeground(palette.on_surface)
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
    """

    def __init__(
        self,
        parent: wx.Window,
        anchor: wx.Window,
        groups: Sequence[GroupChoice],
        *,
        on_choose: Optional[Callable[[Optional[GroupChoice]], None]] = None,
        on_create: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, anchor, width=300, max_height=360)
        self.groups = tuple(groups)
        self.on_choose = on_choose
        self.on_create = on_create
        self.state = SearchState(label="Tab groups")
        self._rows: List[_GroupRow] = []
        palette = tokens.palette()

        heading = widgets.SectionLabel(self.header, "Move into group")
        self.search = widgets.SearchBar(
            self.header,
            "Search tab groups",
            self.state,
            on_change=lambda _state: self._rebuild(),
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

    def _rebuild(self) -> None:
        for row in self._rows:
            self.content_sizer.Detach(row)
            row.Destroy()
        self._rows = []
        visible = self.visible_groups()
        for index, group in enumerate(visible):
            row = _GroupRow(self.content, group, on_choose=self._choose)
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
        self.content.FitInside()
        self.layout()

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
    on_choose: Optional[Callable[[Optional[GroupChoice]], None]] = None,
    on_create: Optional[Callable[[], None]] = None,
) -> _GroupPicker:
    """Open the anchored "Move… into group…" picker beside ``anchor``.

    ``groups`` defaults to the persisted groups of ``surface_id``, so a caller
    that has no list of its own still shows the real workspace rather than a
    placeholder.
    """
    choices = tuple(groups) if groups is not None else tab_groups(surface_id)
    picker = _GroupPicker(
        parent, anchor, choices, on_choose=on_choose, on_create=on_create
    )
    picker.on_dismiss = lambda: wx.CallAfter(picker.Destroy)
    picker.popup()
    return picker
