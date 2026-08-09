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
from amulet_map_editor.api.regex_builder import RegexBuilder

TAB_STATE_VERSION = 1
MAX_TABS = 256
MAX_GROUPS = 64
MAX_ID_LENGTH = 96
MAX_TITLE_LENGTH = 256
MAX_GROUP_NAME_LENGTH = 96


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
                item.tab_id, item.title, group_id, item.pinned, len(tabs_by_id)
            )
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
    """A match carrying enough location data for keyboard teleportation."""

    tab_id: str | None
    title: str
    group_id: str | None
    group_name: str | None
    pinned: bool
    scope: str
    dock: TabDock


def _bounded_text(value: str, limit: int, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"{label} is limited to {limit} characters")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} cannot contain control characters")
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
        return self.state

    def set_dock(self, dock: TabDock | str) -> TabState:
        self.state = TabState(
            self.state.version,
            TabDock(dock),
            self.state.tabs,
            self.state.groups,
            self.state.active_tab_id,
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

    def _results(
        self,
        values: Iterable[tuple[Tab | None, TabGroup | None, str]],
        builder: RegexBuilder,
    ) -> tuple[TabSearchResult, ...]:
        try:
            compiled = builder.compile()
        except (re.error, ValueError) as exc:
            # Public workspace searches have one stable validation exception
            # regardless of the Python version's concrete ``re`` subclass.
            raise ValueError(str(exc)) from exc
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
                    self.state.dock,
                )
            )
        return tuple(results)

    def search_strip(
        self, query: str, *, regex: bool = False, flags: int = re.IGNORECASE
    ) -> tuple[TabSearchResult, ...]:
        groups = {group.group_id: group for group in self.state.groups}
        return self._results(
            ((tab, groups.get(tab.group_id), "strip") for tab in self.state.tabs),
            RegexBuilder(query, flags, regex),
        )

    def search_group(
        self,
        group_id: str,
        query: str,
        *,
        regex: bool = False,
        flags: int = re.IGNORECASE,
    ) -> tuple[TabSearchResult, ...]:
        group = next(
            (item for item in self.state.groups if item.group_id == group_id), None
        )
        if group is None:
            raise ValueError(f"Unknown group id: {group_id}")
        return self._results(
            (
                (tab, group, "group")
                for tab in self.state.tabs
                if tab.group_id == group_id
            ),
            RegexBuilder(query, flags, regex),
        )

    def search_group_names(
        self, query: str, *, regex: bool = False, flags: int = re.IGNORECASE
    ) -> tuple[TabSearchResult, ...]:
        return self._results(
            ((None, group, "group_names") for group in self.state.groups),
            RegexBuilder(query, flags, regex),
        )

    def search_master(
        self, query: str, *, regex: bool = False, flags: int = re.IGNORECASE
    ) -> tuple[TabSearchResult, ...]:
        groups = {group.group_id: group for group in self.state.groups}
        return self._results(
            ((tab, groups.get(tab.group_id), "master") for tab in self.state.tabs),
            RegexBuilder(query, flags, regex),
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
