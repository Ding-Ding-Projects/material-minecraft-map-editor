"""Native Material 3 manager for the app's persisted tab workspace.

Four independent searches live here, one per page of the manager's own tab
strip: this window's tab strip, one individual group at a time, the groups
themselves by their visible names, and a master search over every open tab in
every window, strip, and group the profile knows about.  Each owns a separate
:class:`~amulet_map_editor.api.studio.search.SearchState`, so a pattern typed
into one never appears in another and a regex left switched on in one never
quietly applies to the next.

Every field is the shared
:class:`~amulet_map_editor.api.studio.widgets.SearchBar`, which is what makes
the regex opt-in, the ``.*`` builder button, the honest feedback line, the
anchored builder popover, and its
:class:`~amulet_map_editor.api.wx.ui.regex_dialog.RegexBuilderDialog` fallback
for a display too small to hold that popover behave here exactly as they do on
every other search surface in the application.

The four pages themselves live on the project's own
:class:`~amulet_map_editor.api.wx.ui.material_tabs.MaterialTabs` strip rather
than a native ``wx.Notebook`` -- browser-style tabs, reorderable, searchable,
and drawn from the same design tokens as the rest of the shell, exactly as
:mod:`~amulet_map_editor.api.wx.ui.preferences` already uses for its own
settings sections.  Each page's results are a
:class:`~amulet_map_editor.api.wx.ui.material_dialog.RecordTable`: a native
list contributes nothing to a capture, which meant the one part of this window
worth checking -- the matches themselves -- was the one part no screenshot
could show.  It also carries real multi-select (click, Shift-range, Ctrl+click,
Ctrl+A to select every match, Ctrl+I to invert) as a keyboard-reachable
capability of the list itself, in addition to the query-scoped bulk close
below; pinning, grouping, and activating stay single-target actions, so
selecting more than one match is reported honestly rather than acted on for
whichever row happened to be first.

Revealing a match never spends the user's layout.  A tab inside a collapsed
group is shown by expanding this dialog's own view of it; the group's stored
collapsed preference is never written back, because a search that quietly
expanded a group would destroy a layout choice as a side effect of looking
something up.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api import local_history
from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.studio.widgets import (
    SearchBar,
    SearchableChoice,
    StudioButton,
    StudioCheckBox,
)
from amulet_map_editor.api.tab_groups import (
    BulkClosePreview,
    TabDock,
    TabSearchResult,
    TabWorkspace,
)
from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.api.wx.ui.confirm import show_material_confirmation
from amulet_map_editor.api.wx.ui.material_dialog import (
    DialogChrome,
    RecordTable,
    heading,
    studio,
)
from amulet_map_editor.api.wx.ui.material_tabs import MaterialTabs
from amulet_map_editor.api.wx.ui.simple import MaterialTextEntryDialog

#: Columns every result list shows, so a match always names where it lives.
#: The second number is a relative weight :class:`RecordTable` splits the
#: available width by, not a device-pixel width -- kept in the same ratio the
#: native list's fixed columns used, so a wide match still reads the way it
#: always has.
_RESULT_COLUMNS: Tuple[Tuple[str, int], ...] = (
    ("Label", 250),
    ("Window or workspace", 170),
    ("Strip", 100),
    ("Group", 200),
    ("Pinned", 80),
)

#: How many titles a close confirmation lists before it summarises the rest.
_PREVIEW_ROWS = 12

#: The stable persisted-state key for this dialog's own four-page strip.  It
#: is unrelated to the tab workspace being searched -- that one lives on the
#: notebook this dialog was opened for -- and stays fixed across every open so
#: a dock edge or reorder chosen once is remembered the next time, exactly as
#: :mod:`~amulet_map_editor.api.wx.ui.preferences` remembers its own.
_STRIP_SURFACE_ID = "tab-manager-search"


def _named(control: wx.Window, *, name: str, hint: str = "") -> wx.Window:
    """Give an embedded control its own screen-reader name and tooltip."""

    control.SetName(name)
    if hint:
        control.SetToolTip(hint)
    return control


class _TabSearchPage(wx.Panel):
    """One of the four searches: its own field, its own state, its own results.

    Nothing here is shared with a sibling page.  The search state, the query,
    the regex opt-in, the flags, the builder, and the result list all belong to
    this page alone, which is the whole point of there being four of them.
    """

    def __init__(
        self,
        parent: wx.Window,
        *,
        label: str,
        placeholder: str,
        summary: str,
        run: Callable[[SearchState], Sequence[TabSearchResult]],
        on_activate: Callable[[TabSearchResult], None],
        noun: str = "result",
        sample: str = "Debug 1.14",
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.label = str(label)
        self.noun = str(noun)
        self._run = run
        self._on_activate = on_activate
        #: Set by the host so one handler owns the selection, rather than two
        #: bindings on one list racing each other for the same event.
        self.on_selection: Optional[Callable[[], None]] = None
        self.results: Tuple[TabSearchResult, ...] = ()
        #: Groups this page is showing expanded for the current reveal only.
        self.revealed_groups: set = set()
        self.state = SearchState(label=self.label, sample=sample)
        self.search = studio(
            SearchBar(self, placeholder, self.state, on_change=self._query_changed)
        )
        self.list = RecordTable(
            self,
            _RESULT_COLUMNS,
            name=f"{self.label} results",
            on_selection=self._selection_changed,
            on_activate=self._list_activated,
            empty_text=f"No {self.noun}s match this search yet.",
        )
        self.detail = heading(
            self,
            "Nothing selected.",
            size_px=12,
            role="on_surface",
            name=f"{self.label} selected result",
        )
        self.feedback = heading(
            self,
            str(summary),
            size_px=12,
            role="on_surface_variant",
            name=f"{self.label} status",
        )

        root = wx.BoxSizer(wx.VERTICAL)
        self._build_scope(root)
        root.Add(self.search, 0, wx.EXPAND | wx.ALL, tokens.scaled(tokens.SPACE_SM))
        root.Add(
            self.list,
            1,
            wx.EXPAND | wx.LEFT | wx.RIGHT,
            tokens.scaled(tokens.SPACE_SM),
        )
        root.Add(
            self.detail,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            tokens.scaled(tokens.SPACE_SM),
        )
        root.Add(self.feedback, 0, wx.EXPAND | wx.ALL, tokens.scaled(tokens.SPACE_SM))
        self.SetSizer(root)

    # -- subclass hook --------------------------------------------------------
    def _build_scope(self, sizer: wx.Sizer) -> None:
        """Add any scope control this page needs above its search field."""

    # -- results --------------------------------------------------------------
    @staticmethod
    def _identity(result: TabSearchResult) -> Tuple[str, str, str]:
        """Return what makes a match the same match after the list is rebuilt.

        A tab is identified by its id alone, never by the group it is in:
        moving a tab between groups is exactly the edit after which the user
        most wants to still be looking at the row they just moved.
        """

        if result.tab_id is not None:
            return (result.surface_id, "tab", result.tab_id)
        return (result.surface_id, "group", result.group_id or "")

    def refresh(self) -> None:
        """Re-run this page's own search and repaint only its own list.

        The highlighted match is restored by identity afterwards.  Pinning or
        regrouping a tab rebuilds the list, and a user who lost their place on
        every such edit would have to find the row again to make the next one.
        """

        previous = self.selected_result()
        wanted = self._identity(previous) if previous else None
        try:
            results = tuple(self._run(self.state))
            error = ""
        except ValueError as exc:
            results = ()
            error = str(exc)
        self.results = results
        self.list.set_rows(
            [
                (
                    result.title,
                    result.surface_id or "unrecorded window",
                    f"{result.dock.value} strip",
                    self._group_cell(result),
                    "Pinned" if result.pinned else "",
                )
                for result in results
            ]
        )
        if wanted is not None:
            for index, result in enumerate(results):
                if self._identity(result) != wanted:
                    continue
                self.list.cursor = index
                self.list.anchor = index
                self.list.select(index, True, notify=False)
                self.list._ensure_visible()
                self.list.Refresh()
                break
        self.feedback.SetLabel(
            error or self.state.describe_matches(len(results), self.noun)
        )
        self.feedback.SetName(f"{self.label} status: {self.feedback.GetLabel()}")
        self._selection_changed()

    def _group_cell(self, result: TabSearchResult) -> str:
        """Return the group column, saying plainly what stays collapsed."""

        if result.tab_id is None:
            return "collapsed" if result.group_collapsed else "expanded"
        if not result.group_name:
            return "No group"
        if not result.group_collapsed:
            return result.group_name
        if result.group_id in self.revealed_groups:
            return f"{result.group_name} (collapsed, shown for this reveal)"
        return f"{result.group_name} (collapsed)"

    def selected_result(self) -> Optional[TabSearchResult]:
        """Return the one selected match, or ``None`` when that is ambiguous.

        More than one row selected is reported honestly rather than acted on
        for whichever happened to be first: pinning, grouping, and activating
        are single-target actions, and guessing which of several selected
        matches was meant would be a silent, surprising choice.
        """

        indices = self.list.selected_indices()
        if len(indices) != 1:
            return None
        index = indices[0]
        return self.results[index] if 0 <= index < len(self.results) else None

    def reveal(self, group_id: Optional[str]) -> None:
        """Show a collapsed group's contents here without persisting anything."""

        if group_id:
            self.revealed_groups.add(group_id)

    # -- events ---------------------------------------------------------------
    def _query_changed(self, _state: SearchState) -> None:
        self.refresh()

    def _selection_changed(self) -> None:
        result = self.selected_result()
        self.detail.SetLabel(result.location() if result else "Nothing selected.")
        self.detail.SetName(f"{self.label} selected result: {self.detail.GetLabel()}")
        self.Layout()
        if callable(self.on_selection):
            self.on_selection()

    def _list_activated(self) -> None:
        result = self.selected_result()
        if result is not None:
            self._on_activate(result)


class _GroupScopedSearchPage(_TabSearchPage):
    """The per-group search, run inside one group or inside each in turn."""

    EVERY_GROUP = "Every group, searched one by one"

    def __init__(
        self,
        parent: wx.Window,
        *,
        workspace: TabWorkspace,
        on_activate: Callable[[TabSearchResult], None],
    ) -> None:
        self._workspace = workspace
        self._scope_options: List[Tuple[str, Optional[str]]] = [
            (self.EVERY_GROUP, None)
        ]
        super().__init__(
            parent,
            label="Tab group contents search",
            placeholder="Search this group",
            summary=(
                "Searches inside a group. An ungrouped tab is never a result "
                "here, however well its label matches."
            ),
            run=self._search,
            on_activate=on_activate,
            noun="tab",
        )
        self.sync_groups()

    def _build_scope(self, sizer: wx.Sizer) -> None:
        self.scope = studio(
            SearchableChoice(
                self,
                "Group to search",
                [self.EVERY_GROUP],
                self.EVERY_GROUP,
                on_change=lambda _value: self.refresh(),
            )
        )
        sizer.Add(
            self.scope,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            tokens.scaled(tokens.SPACE_SM),
        )

    def sync_groups(self) -> None:
        """Rebuild the scope list from the groups that actually exist."""

        options: List[Tuple[str, Optional[str]]] = [(self.EVERY_GROUP, None)]
        seen: dict = {}
        for group in self._workspace.state.groups:
            count = seen.get(group.name, 0) + 1
            seen[group.name] = count
            label = group.name if count == 1 else f"{group.name} ({count})"
            options.append((label, group.group_id))
        self._scope_options = options
        chosen = self.scope.value
        self.scope.set_options([label for label, _group_id in options])
        if chosen in {label for label, _group_id in options}:
            self.scope.set_value(chosen)

    def _selected_group(self) -> Optional[str]:
        for label, group_id in self._scope_options:
            if label == self.scope.value:
                return group_id
        return None

    def _search(self, state: SearchState) -> Sequence[TabSearchResult]:
        group_id = self._selected_group()
        if group_id is None:
            return self._workspace.search_every_group(
                state.query, regex=bool(state.regex), flags=state.flags
            )
        return self._workspace.search_group(
            group_id, state.query, regex=bool(state.regex), flags=state.flags
        )


class TabManagerDialog(wx.Dialog):
    """Search and organise the live notebook's tabs without hiding state."""

    def __init__(self, parent: wx.Window, notebook):
        super().__init__(
            parent,
            title="Tabs, groups, and safe closing",
            size=wx.Size(tokens.scaled(960), tokens.scaled(720)),
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        self._notebook = notebook
        self._workspace = getattr(
            notebook, "_tab_workspace", TabWorkspace("main-window")
        )
        self._sync_notebook()

        self.chrome = DialogChrome(self, status_name="Tab manager status")
        self.chrome.add(
            heading(
                self.chrome.body,
                "Workspace navigation",
                size_px=12,
                role="on_surface_variant",
                name="Tab manager eyebrow",
            ),
            0,
            wx.EXPAND,
        )
        self.chrome.add(
            heading(
                self.chrome.body,
                "Tabs, groups, and safe closing",
                size_px=18,
                role="on_surface",
                name="Tab manager heading",
            ),
            0,
            wx.EXPAND,
        )
        intro = heading(
            self.chrome.body,
            "Four independent searches cover this strip, one group at a "
            "time, the group names, and every tab in every window. Bulk "
            "closing previews the exact visible-label match set before it "
            "is authorised.",
            size_px=12,
            role="on_surface_variant",
            name="Tab manager introduction",
        )
        self.chrome.add(intro, 0, wx.EXPAND)
        self.chrome.gap()

        self.pages = MaterialTabs(self.chrome.body, _STRIP_SURFACE_ID)
        self.pages.SetName("Tab manager searches")
        self.strip_page = _TabSearchPage(
            self.pages.host,
            label="Tab manager search",
            placeholder="Search this strip",
            summary="Searches this window's own tab strip, and nothing beyond it.",
            run=lambda state: self._workspace.search_strip(
                state.query, regex=bool(state.regex), flags=state.flags
            ),
            on_activate=self._activate_result,
            noun="tab",
        )
        self.group_page = _GroupScopedSearchPage(
            self.pages.host,
            workspace=self._workspace,
            on_activate=self._activate_result,
        )
        self.group_name_page = _TabSearchPage(
            self.pages.host,
            label="Tab group name search",
            placeholder="Search tab groups",
            summary="Searches the groups themselves by their visible names.",
            run=lambda state: self._workspace.search_group_names(
                state.query, regex=bool(state.regex), flags=state.flags
            ),
            on_activate=self._activate_result,
            noun="group",
            sample="Survival worlds",
        )
        self.master_page = _TabSearchPage(
            self.pages.host,
            label="Master tab search",
            placeholder="Search every tab",
            summary=(
                "Searches every open tab across every window, workspace, "
                "strip, and group this profile has recorded."
            ),
            run=lambda state: self._workspace.search_master(
                state.query, regex=bool(state.regex), flags=state.flags
            ),
            on_activate=self._activate_result,
            noun="tab",
        )
        self.pages.AddPage(self.strip_page, "This strip")
        self.pages.AddPage(self.group_page, "Inside a group")
        self.pages.AddPage(self.group_name_page, "Group names")
        self.pages.AddPage(self.master_page, "Every tab")
        self.chrome.add(self.pages, 1, wx.EXPAND)

        # The strip search is this dialog's primary field, so it carries the
        # names the shell and its documentation refer to it by.
        _named(
            self.strip_page.search.field,
            name="Tab manager search",
            hint="Search the tabs of this window's own strip.",
        )
        if self.strip_page.search.builder_button is not None:
            _named(
                self.strip_page.search.builder_button,
                name="Tab manager regex builder",
                hint="Build a pattern for the strip search.",
            )

        self.chrome.gap()
        options = wx.BoxSizer(wx.HORIZONTAL)
        self.dock = studio(
            SearchableChoice(
                self.chrome.body,
                "Tab strip edge",
                [item.value.title() for item in TabDock],
                self._workspace.state.dock.value.title(),
                on_change=lambda _value: self._dock_changed(),
            )
        )
        self.pin = studio(
            StudioCheckBox(self.chrome.body, "Pinned", name="Pin the selected tab")
        )
        self._group_options: List[Tuple[str, Optional[str]]] = [("No group", None)]
        self.group = studio(
            SearchableChoice(
                self.chrome.body,
                "Tab group",
                ["No group"],
                "No group",
                on_change=lambda _value: self._group_changed(),
            )
        )
        self.new_group = studio(
            StudioButton(
                self.chrome.body,
                "New group",
                variant="outlined",
                on_click=self._new_group,
                hint="Create a group for the selected tab.",
            )
        )
        options.Add(self.dock, 0, wx.RIGHT, tokens.scaled(tokens.SPACE_MD))
        options.Add(
            self.pin,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            tokens.scaled(tokens.SPACE_MD),
        )
        options.Add(self.group, 1, wx.RIGHT, tokens.scaled(tokens.SPACE_SM))
        options.Add(self.new_group, 0, wx.ALIGN_CENTER_VERTICAL)
        self.chrome.add(options, 0, wx.EXPAND)
        self.chrome.gap()

        self.chrome.add(
            heading(
                self.chrome.body,
                "Bulk close",
                size_px=13,
                role="on_surface",
                name="Bulk close heading",
            ),
            0,
            wx.EXPAND,
        )
        self.close_state = SearchState(
            label="Bulk close tab query", sample="Debug 1.14"
        )
        self.close_search = studio(
            SearchBar(
                self.chrome.body,
                "Visible label text",
                self.close_state,
                on_change=lambda _state: self._update_close_preview(),
            )
        )
        _named(
            self.close_search.field,
            name="Bulk close tab query",
            hint="Matched against the visible tab label only, never page contents.",
        )
        if self.close_search.builder_button is not None:
            _named(
                self.close_search.builder_button,
                name="Bulk close regex builder",
                hint="Build a pattern for both bulk closes.",
            )
        self.chrome.add(self.close_search, 0, wx.EXPAND)
        self.chrome.gap()

        bulk = wx.BoxSizer(wx.HORIZONTAL)
        self.include_pinned = studio(
            StudioCheckBox(
                self.chrome.body,
                "Include pinned",
                name="Include pinned tabs in a bulk close",
                on_change=lambda _value: self._update_close_preview(),
            )
        )
        self.close_contains = studio(
            StudioButton(
                self.chrome.body,
                "Close tabs containing text",
                variant="danger",
                on_click=lambda: self._bulk_close(False),
                hint="Close every tab whose visible label matches the query.",
            )
        )
        self.close_not_contains = studio(
            StudioButton(
                self.chrome.body,
                "Close tabs not containing text",
                variant="danger",
                on_click=lambda: self._bulk_close(True),
                hint="Close every tab whose visible label does not match the query.",
            )
        )
        bulk.Add(
            self.include_pinned,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            tokens.scaled(tokens.SPACE_MD),
        )
        bulk.Add(self.close_contains, 0, wx.RIGHT, tokens.scaled(tokens.SPACE_SM))
        bulk.Add(self.close_not_contains, 0)
        self.chrome.add(bulk, 0, wx.EXPAND)
        self.chrome.gap()

        self.close_preview_text = heading(
            self.chrome.body,
            "",
            size_px=12,
            role="on_surface_variant",
            name="Bulk close preview",
        )
        self.chrome.add(self.close_preview_text, 0, wx.EXPAND)

        self.activate = self.chrome.action(
            "Activate selected",
            variant="tonal",
            on_click=self._activate_selected,
            name="Activate selected",
            hint="Go to the selected match without changing any collapsed group.",
        )
        self.close_button = self.chrome.action(
            "Close",
            variant="outlined",
            on_click=lambda: self._dismiss(wx.ID_CLOSE),
            name="Close",
        )

        self.pages.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._page_changed)
        self.pin.Bind(wx.EVT_CHECKBOX, lambda _event: self._pin_changed())
        for page in self._search_pages():
            page.on_selection = self._page_selection_changed
        self.SetMinSize(wx.Size(tokens.scaled(760), tokens.scaled(560)))
        self.Layout()
        apply_material3(self)
        self._refresh()

    # -- pages ----------------------------------------------------------------
    def _search_pages(self) -> Tuple[_TabSearchPage, ...]:
        return (
            self.strip_page,
            self.group_page,
            self.group_name_page,
            self.master_page,
        )

    def _active_page(self) -> _TabSearchPage:
        index = self.pages.GetSelection()
        pages = self._search_pages()
        return pages[index] if 0 <= index < len(pages) else self.strip_page

    def _selected_result(self) -> Optional[TabSearchResult]:
        return self._active_page().selected_result()

    # -- notebook projection ---------------------------------------------------
    def _page_id(self, index: int) -> str:
        page = self._notebook.GetPage(index)
        return getattr(page, "path", None) or (
            "main-menu" if index == 0 else f"page-{index}"
        )

    def _sync_notebook(self) -> None:
        existing = {item.tab_id for item in self._workspace.state.tabs}
        for index in range(self._notebook.GetPageCount()):
            tab_id = self._page_id(index)
            if tab_id not in existing:
                self._workspace.add_tab(
                    self._notebook.GetPageText(index), tab_id=tab_id
                )
        self._workspace.state = self._workspace.state.normalised()

    # -- refresh ---------------------------------------------------------------
    def _refresh(self) -> None:
        self.group_page.sync_groups()
        self._sync_group_options()
        for page in self._search_pages():
            page.refresh()
        self._page_selection_changed()
        self._update_close_preview()

    def _sync_group_options(self) -> None:
        options: List[Tuple[str, Optional[str]]] = [("No group", None)]
        seen: dict = {}
        for group in self._workspace.state.groups:
            count = seen.get(group.name, 0) + 1
            seen[group.name] = count
            label = group.name if count == 1 else f"{group.name} ({count})"
            options.append((label, group.group_id))
        self._group_options = options
        self.group.set_options([label for label, _group_id in options])

    def _group_label_for(self, group_id: Optional[str]) -> str:
        for label, candidate in self._group_options:
            if candidate == group_id:
                return label
        return "No group"

    def _selected_group_id(self) -> Optional[str]:
        for label, group_id in self._group_options:
            if label == self.group.value:
                return group_id
        return None

    def _status(self, message: str) -> None:
        self.chrome.set_status(message)

    def _dismiss(self, code: int) -> None:
        """Close the dialog however it was opened.

        ``EndModal`` asserts on a dialog that was never shown modally, so the
        one route out has to ask which it is rather than assume the frame's
        current call site is the only one there will ever be.
        """

        if self.IsModal():
            self.EndModal(code)
        else:
            self.Close()

    # -- selection -------------------------------------------------------------
    def _page_changed(self, event: wx.Event) -> None:
        self._page_selection_changed()
        event.Skip()

    def _page_selection_changed(self) -> None:
        result = self._selected_result()
        local = bool(
            result is not None
            and result.tab_id is not None
            and (result.surface_id or self._workspace.surface_id)
            == self._workspace.surface_id
        )
        self.activate.Enable(result is not None)
        self.pin.Enable(local)
        self.group.Enable(local)
        self.new_group.Enable(local)
        self.pin.SetValue(bool(result.pinned) if local and result else False)
        self.group.set_value(
            self._group_label_for(result.group_id) if local and result else "No group"
        )
        if result is None:
            self._status("Select a match to pin, group, or activate it.")
        elif result.tab_id is None:
            self._status(f"“{result.title}” is a group, not a tab: {result.location()}")
        elif not local:
            self._status(
                f"That tab is open in “{result.surface_id}”, not this window; "
                "pinning and grouping act on this window's own strip."
            )
        else:
            self._status(result.location())

    # -- organisation ----------------------------------------------------------
    def _dock_changed(self) -> None:
        try:
            dock = TabDock(self.dock.value.lower())
        except ValueError:
            self._status(f"Unknown tab strip edge: {self.dock.value}")
            return
        self._workspace.set_dock(dock)
        if hasattr(self._notebook, "apply_tab_workspace"):
            self._notebook.apply_tab_workspace()
        self._record_workspace_change("tab strip edge changed")
        self._refresh()
        self._status(f"Tab strip edge is now {dock.value}.")

    def _pin_changed(self) -> None:
        result = self._selected_result()
        if result is None or result.tab_id is None:
            return
        self._workspace.set_pinned(result.tab_id, self.pin.GetValue())
        self._record_workspace_change("tab pin changed")
        self._refresh()

    def _group_changed(self) -> None:
        result = self._selected_result()
        if result is None or result.tab_id is None:
            return
        group_id = self._selected_group_id()
        if group_id == result.group_id:
            return
        self._workspace.move_tab(result.tab_id, group_id)
        self._record_workspace_change("tab group changed")
        self._refresh()

    def _new_group(self) -> None:
        dialog = MaterialTextEntryDialog(self, "Group name")
        try:
            if dialog.ShowModal() == wx.ID_OK and dialog.GetValue().strip():
                self._workspace.add_group(dialog.GetValue().strip())
                self._record_workspace_change("tab group created")
                self._refresh()
        finally:
            dialog.Destroy()

    def _record_workspace_change(self, _description: str) -> None:
        """Record organisation changes without making history a hard dependency."""

        local_history.safe_record(
            "main-window-tabs",
            self._workspace.state.to_dict(),
            record_type="settings",
        )

    # -- activation ------------------------------------------------------------
    def _activate_selected(self) -> None:
        result = self._selected_result()
        if result is None:
            self._status("Select a match first.")
            return
        self._activate_result(result)

    def _refused(self, message: str) -> None:
        """Report why a match could not be opened and hand focus back.

        A keyboard user who pressed Enter on a row must land back on that row,
        not on whatever the tab order happens to reach next; otherwise the one
        route that failed is also the one that loses their place.
        """

        self._status(message)
        self._active_page().list.SetFocus()

    def _activate_result(self, result: TabSearchResult) -> None:
        """Go to a match, leaving every stored collapsed preference alone."""

        if result.tab_id is None:
            self._active_page().reveal(result.group_id)
            self._active_page().refresh()
            self._refused(
                f"“{result.title}” is a group. Use the group pages to reach its tabs."
            )
            return
        try:
            reveal = self._workspace.reveal_tab(
                result.tab_id, surface_id=result.surface_id or None
            )
        except ValueError as exc:
            self._refused(str(exc))
            return
        if reveal.group_collapsed:
            for page in self._search_pages():
                page.reveal(reveal.group_id)
                page.refresh()
        if not reveal.activated:
            self._refused(reveal.reason)
            return
        for index in range(self._notebook.GetPageCount()):
            if self._page_id(index) != reveal.tab_id:
                continue
            self._notebook.SetSelection(index)
            self._status(
                f"Went to “{reveal.title}”."
                + (f" {reveal.reason}" if reveal.reason else "")
            )
            self._dismiss(wx.ID_OK)
            return
        self._refused(
            f"“{reveal.title}” is recorded in this workspace but has no open "
            "page right now; it stays selected for the next time it opens."
            + (f" {reveal.reason}" if reveal.reason else "")
        )

    # -- bulk closing ----------------------------------------------------------
    def _preview_for(self, invert: bool) -> BulkClosePreview:
        """Return the exact set one direction of the bulk close would take."""

        return self._workspace.close_preview(
            self.close_state.query,
            regex=bool(self.close_state.regex),
            flags=self.close_state.flags,
            invert=invert,
            include_pinned=self.include_pinned.GetValue(),
        )

    def _update_close_preview(self) -> None:
        """Show both directions of the same predicate before either is run."""

        containing = self._preview_for(False)
        if containing.error:
            self.close_preview_text.SetLabel(containing.error)
            self.close_preview_text.SetName(f"Bulk close preview: {containing.error}")
            self.Layout()
            return
        inverse = self._preview_for(True)
        message = (
            f"Containing: {containing.describe()} "
            f"Not containing: {inverse.describe()} "
            "Matching reads the visible label only, on this window's strip."
        )
        self.close_preview_text.SetLabel(message)
        self.close_preview_text.SetName(f"Bulk close preview: {message}")
        self.Layout()

    def _confirmation_text(self, preview: BulkClosePreview) -> str:
        titles = [tab.title for tab in preview.matched[:_PREVIEW_ROWS]]
        remainder = len(preview.matched) - len(titles)
        listing = "\n".join(f"  • {title}" for title in titles)
        if remainder > 0:
            listing += f"\n  • …and {remainder} more"
        protected = (
            f"{len(preview.protected_pinned)} pinned tab(s) excluded."
            if preview.protected_pinned
            else "No pinned tab was excluded."
        )
        return (
            f"Close {len(preview.matched)} tab(s) matching {preview.mode} "
            f"“{preview.query}”?\n\n{listing}\n\n"
            f"{protected} Unsaved-work protection still applies."
        )

    def _bulk_close(self, inverse: bool) -> None:
        preview = self._preview_for(inverse)
        self._update_close_preview()
        if not preview.is_runnable():
            self._status(preview.describe())
            return
        if (
            show_material_confirmation(
                self,
                self._confirmation_text(preview),
                wx.YES | wx.NO | wx.CANCEL,
                "Close tabs",
            )
            != wx.ID_YES
        ):
            self._status("Bulk close cancelled; nothing was closed.")
            return
        closed = 0
        protected = 0
        missing = 0
        main_menu = getattr(self._notebook, "_main_menu", None)
        for tab in preview.matched:
            for index in range(self._notebook.GetPageCount()):
                if self._page_id(index) != tab.tab_id:
                    continue
                page = self._notebook.GetPage(index)
                path = getattr(page, "path", None)
                if page is main_menu or not path:
                    protected += 1
                    break
                before = self._notebook.GetPageCount()
                self._notebook.close_level(path)
                if self._notebook.GetPageCount() < before:
                    closed += 1
                else:
                    protected += 1
                break
            else:
                missing += 1
        self._sync_notebook()
        self._record_workspace_change("bulk tabs closed")
        self._refresh()
        self._status(
            f"Closed {closed} tab(s). {protected} kept open by close or "
            f"unsaved-work protection; {missing} had no open page to close."
        )


__all__ = ["TabManagerDialog"]
