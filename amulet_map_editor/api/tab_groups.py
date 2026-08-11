"""Reusable browser-style tab and group state for user-facing surfaces.

This module is deliberately independent of wx.  Native surfaces can project the
state onto a notebook or a future Material tab strip without coupling persistence
and search semantics to a particular widget toolkit.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import re
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from amulet_map_editor.api import config
from amulet_map_editor.api.regex_builder import MAX_PATTERN_LENGTH, RegexBuilder

TAB_STATE_VERSION = 1
MAX_TABS = 256
MAX_GROUPS = 64
MAX_ID_LENGTH = 96
MAX_TITLE_LENGTH = 256
MAX_GROUP_NAME_LENGTH = 96
#: Every surface that has ever persisted tab state, so the master search can
#: reach a window or workspace that is not the one asking.
TAB_INDEX_ID = "amulet_tabs_index"
MAX_SURFACES = 64


class TabDock(str, Enum):
    """Supported tab-strip edges; left is the default for new surfaces."""

    LEFT = "left"
    TOP = "top"
    RIGHT = "right"
    BOTTOM = "bottom"


@dataclass(frozen=True)
class Tab:
    tab_id: str
    title: str
    group_id: str | None = None
    pinned: bool = False
    order: int = 0

    def normalised(self) -> "Tab":
        tab_id = _bounded_text(self.tab_id, MAX_ID_LENGTH, "tab id")
        title = _bounded_text(self.title, MAX_TITLE_LENGTH, "tab title")
        group_id = (
            None
            if self.group_id is None
            else _bounded_text(self.group_id, MAX_ID_LENGTH, "group id")
        )
        return Tab(tab_id, title, group_id, bool(self.pinned), max(0, int(self.order)))


@dataclass(frozen=True)
class TabGroup:
    group_id: str
    name: str
    collapsed: bool = False
    order: int = 0

    def normalised(self) -> "TabGroup":
        return TabGroup(
            _bounded_text(self.group_id, MAX_ID_LENGTH, "group id"),
            _bounded_text(self.name, MAX_GROUP_NAME_LENGTH, "group name"),
            bool(self.collapsed),
            max(0, int(self.order)),
        )


@dataclass(frozen=True)
class TabState:
    """Versioned serialisable state for one tab surface."""

    version: int = TAB_STATE_VERSION
    dock: TabDock = TabDock.LEFT
    tabs: tuple[Tab, ...] = ()
    groups: tuple[TabGroup, ...] = ()
    active_tab_id: str | None = None

    def normalised(self) -> "TabState":
        groups_by_id: dict[str, TabGroup] = {}
        for group in sorted(self.groups, key=lambda item: (item.order, item.group_id)):
            try:
                item = group.normalised()
            except (TypeError, ValueError, OverflowError):
                continue
            if item.group_id not in groups_by_id and len(groups_by_id) < MAX_GROUPS:
                groups_by_id[item.group_id] = item

        tabs_by_id: dict[str, Tab] = {}
        for tab in sorted(self.tabs, key=lambda item: (item.order, item.tab_id)):
            try:
                item = tab.normalised()
            except (TypeError, ValueError, OverflowError):
                continue
            if item.tab_id in tabs_by_id or len(tabs_by_id) >= MAX_TABS:
                continue
            group_id = item.group_id if item.group_id in groups_by_id else None
            tabs_by_id[item.tab_id] = Tab(
                item.tab_id, item.title, group_id, item.pinned, item.order
            )
        # Pinned tabs form a stable protected region before ordinary tabs, even
        # when an older profile stored them interleaved.
        ordered_tabs = sorted(
            tabs_by_id.values(),
            key=lambda item: (not item.pinned, item.order, item.tab_id),
        )
        tabs_by_id = {
            item.tab_id: Tab(item.tab_id, item.title, item.group_id, item.pinned, index)
            for index, item in enumerate(ordered_tabs)
        }
        active = self.active_tab_id if self.active_tab_id in tabs_by_id else None
        if active is None and tabs_by_id:
            active = next(iter(tabs_by_id))
        try:
            dock = TabDock(self.dock)
        except ValueError:
            dock = TabDock.LEFT
        return TabState(
            TAB_STATE_VERSION,
            dock,
            tuple(tabs_by_id.values()),
            tuple(groups_by_id.values()),
            active,
        )

    def to_dict(self) -> dict[str, Any]:
        state = self.normalised()
        return {
            "version": TAB_STATE_VERSION,
            "dock": state.dock.value,
            "tabs": [asdict(tab) for tab in state.tabs],
            "groups": [asdict(group) for group in state.groups],
            "active_tab_id": state.active_tab_id,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "TabState":
        if not isinstance(raw, Mapping):
            return cls()
        try:
            dock = TabDock(raw.get("dock", TabDock.LEFT.value))
        except (TypeError, ValueError):
            dock = TabDock.LEFT
        raw_tabs = raw.get("tabs", ())
        raw_groups = raw.get("groups", ())
        tabs: list[Tab] = []
        for index, item in enumerate(
            raw_tabs if isinstance(raw_tabs, Sequence) else ()
        ):
            if not isinstance(item, Mapping):
                continue
            try:
                tabs.append(
                    Tab(
                        str(item.get("tab_id", "")),
                        str(item.get("title", "")),
                        item.get("group_id"),
                        bool(item.get("pinned", False)),
                        int(item.get("order", index)),
                    )
                )
            except (TypeError, ValueError, OverflowError):
                continue
        groups: list[TabGroup] = []
        for index, item in enumerate(
            raw_groups if isinstance(raw_groups, Sequence) else ()
        ):
            if not isinstance(item, Mapping):
                continue
            try:
                groups.append(
                    TabGroup(
                        str(item.get("group_id", "")),
                        str(item.get("name", "")),
                        bool(item.get("collapsed", False)),
                        int(item.get("order", index)),
                    )
                )
            except (TypeError, ValueError, OverflowError):
                continue
        active = raw.get("active_tab_id")
        return cls(
            TAB_STATE_VERSION,
            dock,
            tabs,
            groups,
            active if isinstance(active, str) else None,
        ).normalised()


@dataclass(frozen=True)
class TabSearchResult:
    """A match carrying enough location data for keyboard teleportation.

    A result names the window or workspace it lives in, the strip edge that
    window projects, the group and that group's collapsed preference, whether
    the tab is pinned, and the visible label -- everything a reader needs to
    tell two identically-titled tabs in two windows apart.
    """

    tab_id: str | None
    title: str
    group_id: str | None
    group_name: str | None
    pinned: bool
    scope: str
    dock: TabDock
    surface_id: str = ""
    group_collapsed: bool = False
    active: bool = False

    def location(self) -> str:
        """Return the honest one-line location of this match."""

        surface = self.surface_id or "unrecorded window"
        strip = f"{self.dock.value} strip"
        if self.tab_id is None:
            state = "collapsed" if self.group_collapsed else "expanded"
            return " · ".join((surface, strip, f"group “{self.title}”", state))
        group = f"group “{self.group_name}”" if self.group_name else "no group"
        if self.group_collapsed:
            group = f"{group} (collapsed)"
        return " · ".join(
            (
                surface,
                strip,
                group,
                "pinned" if self.pinned else "not pinned",
                self.title,
            )
        )


@dataclass(frozen=True)
class TabReveal:
    """What actually happened when a search result was activated.

    Revealing a tab inside a collapsed group never writes ``collapsed`` back:
    the group's stored preference is the user's, and a search that quietly
    expanded it would destroy a layout choice as a side effect of looking
    something up.  ``group_collapsed`` reports that preference unchanged so the
    caller can expand its own view for as long as the result is on screen.
    """

    surface_id: str
    tab_id: str
    title: str
    group_id: str | None
    group_name: str | None
    group_collapsed: bool
    activated: bool
    reason: str = ""


@dataclass(frozen=True)
class BulkClosePreview:
    """The exact set a bulk close would touch, before anything is closed.

    Both bulk closes share one compiled predicate and the inverse simply
    negates it, so the flags, the casing, and the scope cannot drift apart
    between "containing" and "not containing".
    """

    query: str
    regex: bool
    invert: bool
    include_pinned: bool
    considered: int
    matched: tuple[Tab, ...] = ()
    protected_pinned: tuple[Tab, ...] = ()
    error: str = ""

    @property
    def mode(self) -> str:
        """Return the match mode in the words the confirmation shows."""

        return (
            f"{'regex' if self.regex else 'plain text'} "
            f"{'not containing' if self.invert else 'containing'}"
        )

    def is_runnable(self) -> bool:
        """Return whether this preview may be authorised at all."""

        return not self.error and bool(self.matched)

    def describe(self) -> str:
        """Return the reviewable count line, including every honest refusal."""

        if self.error:
            return self.error
        line = (
            f"{len(self.matched)} of {self.considered} tab(s) match "
            f"{self.mode} “{self.query}”."
        )
        if self.protected_pinned:
            line += (
                f" {len(self.protected_pinned)} pinned tab(s) excluded: "
                "include them deliberately."
            )
        if not self.matched:
            line += " Nothing would close."
        return line


def _bounded_text(value: str, limit: int, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"{label} is limited to {limit} characters")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} cannot contain control characters")
    return value


def regex_flags(flags: int | str | None = re.IGNORECASE) -> int:
    """Return ``re`` flags from an int or from a search field's flag text.

    A :class:`~amulet_map_editor.api.studio.search.SearchState` carries its
    flags as the text the regex builder shows the user (``"iu"``, ``"ims"``).
    Accepting that text here means a surface can hand over the flags its own
    field is displaying instead of translating them itself, which is how the
    displayed flags and the evaluated ones drift apart.
    """

    if flags is None:
        return re.UNICODE
    if isinstance(flags, int):
        return flags
    value = re.UNICODE
    text = str(flags)
    if "i" in text:
        value |= re.IGNORECASE
    if "m" in text:
        value |= re.MULTILINE
    if "s" in text:
        value |= re.DOTALL
    if "x" in text:
        value |= re.VERBOSE
    return value


def tab_strip_aria(dock: TabDock | str = TabDock.LEFT) -> dict[str, str]:
    """Return stable ARIA attributes for a tab strip projection."""

    try:
        dock = TabDock(dock)
    except ValueError:
        dock = TabDock.LEFT
    vertical = dock in (TabDock.LEFT, TabDock.RIGHT)
    return {
        "role": "tablist",
        "aria-orientation": "vertical" if vertical else "horizontal",
    }


def tab_aria(tab: Tab, *, active: bool, position: int, panel_id: str) -> dict[str, str]:
    """Return ARIA attributes for one tab; labels remain the user's real title."""

    return {
        "role": "tab",
        "aria-selected": "true" if active else "false",
        "aria-posinset": str(position + 1),
        "aria-controls": panel_id,
        "tabindex": "0" if active else "-1",
        "data-tab-id": tab.tab_id,
    }


def tab_keyboard_target(
    key: str, *, dock: TabDock | str, current: int, count: int
) -> int | None:
    """Return the next roving-focus index for the strip's current axis."""

    if count <= 0:
        return None
    try:
        dock = TabDock(dock)
    except ValueError:
        dock = TabDock.LEFT
    previous = {"ArrowUp"} if dock in (TabDock.LEFT, TabDock.RIGHT) else {"ArrowLeft"}
    following = (
        {"ArrowDown"} if dock in (TabDock.LEFT, TabDock.RIGHT) else {"ArrowRight"}
    )
    if key in previous:
        return (current - 1) % count
    if key in following:
        return (current + 1) % count
    if key == "Home":
        return 0
    if key == "End":
        return count - 1
    return None


class TabWorkspace:
    """Stateful, persisted tab/group operations and four independent searches."""

    def __init__(self, surface_id: str, state: TabState | None = None):
        self.surface_id = _bounded_text(surface_id, MAX_ID_LENGTH, "surface id")
        self.state = (state or self.load(self.surface_id)).normalised()

    @staticmethod
    def config_id(surface_id: str) -> str:
        return (
            "amulet_tabs_" + re.sub(r"[^A-Za-z0-9_.-]", "_", surface_id)[:MAX_ID_LENGTH]
        )

    @classmethod
    def load(cls, surface_id: str) -> TabState:
        return TabState.from_dict(config.get(cls.config_id(surface_id), {}))

    def save(self) -> TabState:
        self.state = self.state.normalised()
        config.put(self.config_id(self.surface_id), self.state.to_dict())
        self.register_surface(self.surface_id)
        return self.state

    # -- the surface index behind the master search ---------------------------
    @classmethod
    def known_surfaces(cls) -> tuple[str, ...]:
        """Return every window or workspace with persisted tab state.

        An unreadable or hand-edited index yields the surfaces it can still
        parse rather than an exception; the master search then says how many
        surfaces it actually reached instead of pretending it saw them all.
        """

        raw = config.get(TAB_INDEX_ID, ())
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            return ()
        surfaces: list[str] = []
        for item in raw:
            try:
                value = _bounded_text(item, MAX_ID_LENGTH, "surface id")
            except (TypeError, ValueError):
                continue
            if value not in surfaces and len(surfaces) < MAX_SURFACES:
                surfaces.append(value)
        return tuple(surfaces)

    @classmethod
    def register_surface(cls, surface_id: str) -> tuple[str, ...]:
        """Record a surface so other windows' searches can find its tabs."""

        value = _bounded_text(surface_id, MAX_ID_LENGTH, "surface id")
        surfaces = cls.known_surfaces()
        if value in surfaces or len(surfaces) >= MAX_SURFACES:
            return surfaces
        surfaces = surfaces + (value,)
        config.put(TAB_INDEX_ID, list(surfaces))
        return surfaces

    def surfaces(self) -> tuple[tuple[str, TabState], ...]:
        """Return every reachable surface's state, this one's live copy first.

        This workspace answers from memory so a master search sees edits that
        have not been saved yet; every other surface is read from its own
        persisted profile.
        """

        ordered = [self.surface_id] + [
            item for item in self.known_surfaces() if item != self.surface_id
        ]
        found: list[tuple[str, TabState]] = []
        for surface_id in ordered[:MAX_SURFACES]:
            if surface_id == self.surface_id:
                found.append((surface_id, self.state.normalised()))
                continue
            try:
                found.append((surface_id, self.load(surface_id).normalised()))
            except (TypeError, ValueError, OverflowError):
                # A profile written by a newer or damaged build is skipped
                # rather than silently reported as an empty window.
                continue
        return tuple(found)

    def set_dock(self, dock: TabDock | str) -> TabState:
        self.state = TabState(
            self.state.version,
            TabDock(dock),
            self.state.tabs,
            self.state.groups,
            self.state.active_tab_id,
        ).normalised()
        return self.save()

    def activate_tab(self, tab_id: str) -> TabState:
        """Select a tab after a search result is activated or restored."""

        if not any(item.tab_id == tab_id for item in self.state.tabs):
            raise ValueError(f"Unknown tab id: {tab_id}")
        self.state = TabState(
            self.state.version,
            self.state.dock,
            self.state.tabs,
            self.state.groups,
            tab_id,
        ).normalised()
        return self.save()

    def add_tab(
        self,
        title: str,
        *,
        tab_id: str | None = None,
        group_id: str | None = None,
        pinned: bool = False,
    ) -> Tab:
        if len(self.state.tabs) >= MAX_TABS:
            raise ValueError(f"A surface supports at most {MAX_TABS} tabs")
        candidate = tab_id or uuid4().hex
        tab = Tab(candidate, title, group_id, pinned, len(self.state.tabs)).normalised()
        if any(existing.tab_id == tab.tab_id for existing in self.state.tabs):
            raise ValueError(f"Tab id already exists: {tab.tab_id}")
        tabs = self.state.tabs + (tab,)
        self.state = TabState(
            self.state.version,
            self.state.dock,
            tabs,
            self.state.groups,
            (
                tab.tab_id
                if self.state.active_tab_id is None
                else self.state.active_tab_id
            ),
        ).normalised()
        self.save()
        return next(item for item in self.state.tabs if item.tab_id == tab.tab_id)

    def add_group(
        self, name: str, *, group_id: str | None = None, collapsed: bool = False
    ) -> TabGroup:
        if len(self.state.groups) >= MAX_GROUPS:
            raise ValueError(f"A surface supports at most {MAX_GROUPS} groups")
        group = TabGroup(
            group_id or uuid4().hex, name, collapsed, len(self.state.groups)
        ).normalised()
        if any(existing.group_id == group.group_id for existing in self.state.groups):
            raise ValueError(f"Group id already exists: {group.group_id}")
        self.state = TabState(
            self.state.version,
            self.state.dock,
            self.state.tabs,
            self.state.groups + (group,),
            self.state.active_tab_id,
        ).normalised()
        self.save()
        return next(
            item for item in self.state.groups if item.group_id == group.group_id
        )

    def move_tab(self, tab_id: str, group_id: str | None) -> TabState:
        if group_id is not None and not any(
            group.group_id == group_id for group in self.state.groups
        ):
            raise ValueError(f"Unknown group id: {group_id}")
        tabs = tuple(
            Tab(
                item.tab_id,
                item.title,
                group_id if item.tab_id == tab_id else item.group_id,
                item.pinned,
                item.order,
            )
            for item in self.state.tabs
        )
        if not any(item.tab_id == tab_id for item in self.state.tabs):
            raise ValueError(f"Unknown tab id: {tab_id}")
        self.state = TabState(
            self.state.version,
            self.state.dock,
            tabs,
            self.state.groups,
            self.state.active_tab_id,
        ).normalised()
        return self.save()

    def set_pinned(self, tab_id: str, pinned: bool) -> TabState:
        if not any(item.tab_id == tab_id for item in self.state.tabs):
            raise ValueError(f"Unknown tab id: {tab_id}")
        tabs = tuple(
            Tab(
                item.tab_id,
                item.title,
                item.group_id,
                pinned if item.tab_id == tab_id else item.pinned,
                item.order,
            )
            for item in self.state.tabs
        )
        self.state = TabState(
            self.state.version,
            self.state.dock,
            tabs,
            self.state.groups,
            self.state.active_tab_id,
        ).normalised()
        return self.save()

    def reorder_tab(self, tab_id: str, target_index: int) -> TabState:
        """Reorder within the tab's pinned/unpinned region without crossing it."""

        selected = next(
            (item for item in self.state.tabs if item.tab_id == tab_id), None
        )
        if selected is None:
            raise ValueError(f"Unknown tab id: {tab_id}")
        region = [item for item in self.state.tabs if item.pinned == selected.pinned]
        region.remove(selected)
        target_index = max(0, min(int(target_index), len(region)))
        region.insert(target_index, selected)
        # Keep the protected pinned region first while retaining each region's order.
        pinned = [
            item for item in self.state.tabs if item.pinned and item.tab_id != tab_id
        ]
        unpinned = [
            item
            for item in self.state.tabs
            if not item.pinned and item.tab_id != tab_id
        ]
        if selected.pinned:
            pinned = region
        else:
            unpinned = region
        ordered = pinned + unpinned
        tabs = tuple(
            Tab(item.tab_id, item.title, item.group_id, item.pinned, index)
            for index, item in enumerate(ordered)
        )
        self.state = TabState(
            self.state.version,
            self.state.dock,
            tabs,
            self.state.groups,
            self.state.active_tab_id,
        ).normalised()
        return self.save()

    def reorder_group(self, group_id: str, target_index: int) -> TabState:
        """Reorder named groups while leaving their collapsed state untouched."""

        selected = next(
            (item for item in self.state.groups if item.group_id == group_id), None
        )
        if selected is None:
            raise ValueError(f"Unknown group id: {group_id}")
        groups = [item for item in self.state.groups if item.group_id != group_id]
        target_index = max(0, min(int(target_index), len(groups)))
        groups.insert(target_index, selected)
        groups = [
            TabGroup(item.group_id, item.name, item.collapsed, index)
            for index, item in enumerate(groups)
        ]
        self.state = TabState(
            self.state.version,
            self.state.dock,
            self.state.tabs,
            tuple(groups),
            self.state.active_tab_id,
        ).normalised()
        return self.save()

    def set_group_collapsed(self, group_id: str, collapsed: bool) -> TabState:
        if not any(item.group_id == group_id for item in self.state.groups):
            raise ValueError(f"Unknown group id: {group_id}")
        groups = tuple(
            TabGroup(
                item.group_id,
                item.name,
                collapsed if item.group_id == group_id else item.collapsed,
                item.order,
            )
            for item in self.state.groups
        )
        self.state = TabState(
            self.state.version,
            self.state.dock,
            self.state.tabs,
            groups,
            self.state.active_tab_id,
        ).normalised()
        return self.save()

    # -- revealing a match without spending the user's layout ------------------
    def reveal_tab(self, tab_id: str, *, surface_id: str | None = None) -> TabReveal:
        """Activate a matched tab, leaving every collapsed preference intact.

        A result in another window is reported rather than activated: this
        process owns one surface's selection, and writing a selection into a
        profile another live window is holding would be overwritten the moment
        that window saved.
        """

        target = surface_id or self.surface_id
        if target != self.surface_id:
            state = self.load(target).normalised()
            tab = next((item for item in state.tabs if item.tab_id == tab_id), None)
            if tab is None:
                raise ValueError(f"Unknown tab id: {tab_id}")
            group = next(
                (item for item in state.groups if item.group_id == tab.group_id), None
            )
            return TabReveal(
                target,
                tab.tab_id,
                tab.title,
                tab.group_id,
                group.name if group else None,
                bool(group.collapsed) if group else False,
                False,
                f"That tab is open in “{target}”; raise it in that window.",
            )
        tab = next((item for item in self.state.tabs if item.tab_id == tab_id), None)
        if tab is None:
            raise ValueError(f"Unknown tab id: {tab_id}")
        self.activate_tab(tab.tab_id)
        group = next(
            (item for item in self.state.groups if item.group_id == tab.group_id), None
        )
        collapsed = bool(group.collapsed) if group else False
        return TabReveal(
            self.surface_id,
            tab.tab_id,
            tab.title,
            tab.group_id,
            group.name if group else None,
            collapsed,
            True,
            (
                f"Group “{group.name}” stays collapsed in your saved layout."
                if collapsed and group
                else ""
            ),
        )

    # -- searching -------------------------------------------------------------
    @staticmethod
    def _compiled(query: str, regex: bool, flags: int | str):
        """Compile one bounded pattern, or refuse with a stable exception."""

        try:
            return RegexBuilder(
                str(query)[:MAX_PATTERN_LENGTH], regex_flags(flags), regex
            ).compile()
        except (re.error, ValueError) as exc:
            # Public workspace searches have one stable validation exception
            # regardless of the Python version's concrete ``re`` subclass.
            raise ValueError(str(exc)) from exc

    @staticmethod
    def _results(
        surface_id: str,
        state: TabState,
        values: Iterable[tuple[Tab | None, TabGroup | None, str]],
        compiled,
    ) -> tuple[TabSearchResult, ...]:
        results: list[TabSearchResult] = []
        for tab, group, scope in values:
            title = tab.title if tab else group.name if group else ""
            if compiled.search(title) is None:
                continue
            results.append(
                TabSearchResult(
                    tab.tab_id if tab else None,
                    title,
                    tab.group_id if tab else (group.group_id if group else None),
                    group.name if group else None,
                    tab.pinned if tab else False,
                    scope,
                    state.dock,
                    surface_id,
                    bool(group.collapsed) if group else False,
                    bool(tab and tab.tab_id == state.active_tab_id),
                )
            )
        return tuple(results)

    def search_strip(
        self, query: str, *, regex: bool = False, flags: int | str = re.IGNORECASE
    ) -> tuple[TabSearchResult, ...]:
        """Search this surface's own tab strip, and nothing beyond it."""

        groups = {group.group_id: group for group in self.state.groups}
        return self._results(
            self.surface_id,
            self.state,
            ((tab, groups.get(tab.group_id), "strip") for tab in self.state.tabs),
            self._compiled(query, regex, flags),
        )

    def search_group(
        self,
        group_id: str,
        query: str,
        *,
        regex: bool = False,
        flags: int | str = re.IGNORECASE,
    ) -> tuple[TabSearchResult, ...]:
        """Search inside one individual tab group."""

        group = next(
            (item for item in self.state.groups if item.group_id == group_id), None
        )
        if group is None:
            raise ValueError(f"Unknown group id: {group_id}")
        return self._results(
            self.surface_id,
            self.state,
            (
                (tab, group, "group")
                for tab in self.state.tabs
                if tab.group_id == group_id
            ),
            self._compiled(query, regex, flags),
        )

    def search_every_group(
        self, query: str, *, regex: bool = False, flags: int | str = re.IGNORECASE
    ) -> tuple[TabSearchResult, ...]:
        """Run the per-group search inside each group in turn.

        This is the group search applied to every individual group rather than
        a strip search wearing a group label: an ungrouped tab is never a
        result here, however well its title matches.
        """

        compiled = self._compiled(query, regex, flags)
        results: list[TabSearchResult] = []
        for group in self.state.groups:
            results.extend(
                self._results(
                    self.surface_id,
                    self.state,
                    (
                        (tab, group, "group")
                        for tab in self.state.tabs
                        if tab.group_id == group.group_id
                    ),
                    compiled,
                )
            )
        return tuple(results)

    def search_group_names(
        self, query: str, *, regex: bool = False, flags: int | str = re.IGNORECASE
    ) -> tuple[TabSearchResult, ...]:
        """Search the groups themselves by their visible names and labels."""

        return self._results(
            self.surface_id,
            self.state,
            ((None, group, "group_names") for group in self.state.groups),
            self._compiled(query, regex, flags),
        )

    def search_master(
        self, query: str, *, regex: bool = False, flags: int | str = re.IGNORECASE
    ) -> tuple[TabSearchResult, ...]:
        """Search every open tab across every window, strip, and group."""

        compiled = self._compiled(query, regex, flags)
        results: list[TabSearchResult] = []
        for surface_id, state in self.surfaces():
            groups = {group.group_id: group for group in state.groups}
            results.extend(
                self._results(
                    surface_id,
                    state,
                    ((tab, groups.get(tab.group_id), "master") for tab in state.tabs),
                    compiled,
                )
            )
        return tuple(results)

    # -- bulk closing ----------------------------------------------------------
    def close_preview(
        self,
        query: str,
        *,
        regex: bool = False,
        flags: int | str = re.IGNORECASE,
        invert: bool = False,
        include_pinned: bool = False,
    ) -> BulkClosePreview:
        """Return exactly which tabs a bulk close would take, and which it will not.

        Matching reads the visible label and only the visible label; a tab's
        contents are never inspected.  ``invert`` negates this same compiled
        predicate rather than building a second one, so the two bulk closes
        cannot disagree about flags, casing, or scope.
        """

        text = str(query)[:MAX_PATTERN_LENGTH]
        considered = len(self.state.tabs)
        if not text.strip():
            return BulkClosePreview(
                text,
                regex,
                invert,
                include_pinned,
                considered,
                error="Enter a query first: an empty one would match every tab.",
            )
        try:
            compiled = self._compiled(text, regex, flags)
        except ValueError as exc:
            return BulkClosePreview(
                text,
                regex,
                invert,
                include_pinned,
                considered,
                error=f"Invalid bulk-close query: {exc}",
            )
        matched: list[Tab] = []
        protected: list[Tab] = []
        for tab in self.state.tabs:
            hit = compiled.search(tab.title) is not None
            if invert:
                hit = not hit
            if not hit:
                continue
            if tab.pinned and not include_pinned:
                protected.append(tab)
                continue
            matched.append(tab)
        return BulkClosePreview(
            text,
            regex,
            invert,
            include_pinned,
            considered,
            tuple(matched),
            tuple(protected),
        )


def apply_wx_tab_accessibility(
    control: Any, *, tab: Tab, active: bool, position: int, panel_id: str
) -> dict[str, str]:
    """Best-effort wx projection; return attributes for tests or other toolkits."""

    attrs = tab_aria(tab, active=active, position=position, panel_id=panel_id)
    if control is not None:
        if hasattr(control, "SetName"):
            control.SetName(tab.title)
        if hasattr(control, "SetHelpText"):
            control.SetHelpText("Pinned tab" if tab.pinned else "Tab")
    return attrs
