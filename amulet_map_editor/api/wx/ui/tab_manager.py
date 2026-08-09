"""Native Material 3 manager for the app's persisted tab workspace."""

from __future__ import annotations

import wx

from amulet_map_editor.api.tab_groups import TabDock, TabWorkspace
from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.api.wx.ui.regex_dialog import RegexBuilderDialog
from amulet_map_editor.api.wx.ui.simple import MaterialTextEntryDialog


class TabManagerDialog(wx.Dialog):
    """Search and organise the live notebook's tabs without hiding state."""

    def __init__(self, parent: wx.Window, notebook):
        super().__init__(
            parent,
            title="Tabs and groups",
            size=wx.Size(860, 600),
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        self._notebook = notebook
        self._workspace = TabWorkspace("main-window")
        self._regex_flags = 0
        self._sync_notebook()

        root = wx.BoxSizer(wx.VERTICAL)
        heading = wx.StaticText(self, label="Tabs and groups")
        heading.SetName("Tab manager heading")
        root.Add(heading, 0, wx.ALL | wx.EXPAND, 16)

        search_row = wx.BoxSizer(wx.HORIZONTAL)
        self.search = wx.TextCtrl(self, name="Tab manager search")
        self.search.SetHint("Search tabs and groups")
        self.regex = wx.CheckBox(self, label="Regex")
        self.regex_button = wx.Button(self, label="Regex…", name="Tab manager regex builder")
        self.regex_button.SetName("Tab manager regex builder")
        search_row.Add(self.search, 1, wx.EXPAND | wx.RIGHT, 8)
        search_row.Add(self.regex, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        search_row.Add(self.regex_button, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(search_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 16)

        options = wx.BoxSizer(wx.HORIZONTAL)
        options.Add(wx.StaticText(self, label="Tab strip edge"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.dock = wx.Choice(self, choices=[item.value.title() for item in TabDock])
        self.dock.SetName("Tab strip edge")
        self.dock.SetSelection([item for item in TabDock].index(self._workspace.state.dock))
        self.pin = wx.CheckBox(self, label="Pinned")
        self.group = wx.Choice(self, choices=["No group"] + [item.name for item in self._workspace.state.groups])
        self.group.SetName("Tab group")
        options.Add(self.dock, 0, wx.RIGHT, 16)
        options.Add(self.pin, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)
        options.Add(wx.StaticText(self, label="Group"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        options.Add(self.group, 1, wx.RIGHT, 8)
        self.new_group = wx.Button(self, label="New group")
        options.Add(self.new_group, 0)
        root.Add(options, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 16)

        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.SetName("Tabs and groups list")
        for index, label in enumerate(("Tab", "Group", "Pinned", "Active")):
            self.list.InsertColumn(index, label)
        root.Add(self.list, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 16)

        self.feedback = wx.StaticText(self, label="")
        self.feedback.SetName("Tab manager status")
        root.Add(self.feedback, 0, wx.ALL | wx.EXPAND, 16)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.activate = wx.Button(self, label="Activate selected")
        close = wx.Button(self, id=wx.ID_CLOSE, label="Close")
        actions.Add(self.activate, 0, wx.RIGHT, 8)
        actions.Add(close, 0)
        root.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.ALIGN_RIGHT, 16)
        self.SetSizer(root)

        self.search.Bind(wx.EVT_TEXT, self._refresh)
        self.regex.Bind(wx.EVT_CHECKBOX, self._refresh)
        self.regex_button.Bind(wx.EVT_BUTTON, self._open_regex_builder)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._selection_changed)
        self.dock.Bind(wx.EVT_CHOICE, self._dock_changed)
        self.pin.Bind(wx.EVT_CHECKBOX, self._pin_changed)
        self.group.Bind(wx.EVT_CHOICE, self._group_changed)
        self.new_group.Bind(wx.EVT_BUTTON, self._new_group)
        self.activate.Bind(wx.EVT_BUTTON, self._activate_selected)
        close.Bind(wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_CLOSE))
        apply_material3(self)
        self._refresh()

    def _sync_notebook(self) -> None:
        existing = {item.tab_id for item in self._workspace.state.tabs}
        for index in range(self._notebook.GetPageCount()):
            page = self._notebook.GetPage(index)
            tab_id = getattr(page, "path", None) or ("main-menu" if index == 0 else f"page-{index}")
            if tab_id not in existing:
                self._workspace.add_tab(self._notebook.GetPageText(index), tab_id=tab_id)
        self._workspace.state = self._workspace.state.normalised()

    def _matches(self, title: str) -> bool:
        query = self.search.GetValue()[:256]
        if not query:
            return True
        if self.regex.GetValue():
            import re

            try:
                return re.search(query, title, self._regex_flags) is not None
            except re.error:
                return False
        return query.casefold() in title.casefold()

    def _refresh(self, _event=None) -> None:
        self.list.DeleteAllItems()
        state = self._workspace.state
        groups = {item.group_id: item.name for item in state.groups}
        visible = [item for item in state.tabs if self._matches(item.title)]
        for item in visible:
            row = self.list.InsertItem(self.list.GetItemCount(), item.title)
            self.list.SetItem(row, 1, groups.get(item.group_id, "No group"))
            self.list.SetItem(row, 2, "Yes" if item.pinned else "No")
            self.list.SetItem(row, 3, "Yes" if item.tab_id == state.active_tab_id else "No")
            self.list.SetItemData(row, state.tabs.index(item))
        for column, width in enumerate((300, 220, 100, 100)):
            self.list.SetColumnWidth(column, width)
        self.feedback.SetLabel(f"{len(visible)} of {len(state.tabs)} tabs shown; strip edge is {state.dock.value}.")
        self._selection_changed()

    def _selected_tab(self):
        row = self.list.GetFirstSelected()
        if row < 0:
            return None
        index = self.list.GetItemData(row)
        return self._workspace.state.tabs[index]

    def _selection_changed(self, _event=None) -> None:
        item = self._selected_tab()
        self.activate.Enable(item is not None)
        self.pin.SetValue(item.pinned if item else False)
        self.group.SetSelection(0)
        if item and item.group_id:
            for index, group in enumerate(self._workspace.state.groups, 1):
                if group.group_id == item.group_id:
                    self.group.SetSelection(index)
                    break

    def _dock_changed(self, _event) -> None:
        self._workspace.set_dock(list(TabDock)[self.dock.GetSelection()])
        self._refresh()

    def _pin_changed(self, _event) -> None:
        item = self._selected_tab()
        if item:
            self._workspace.set_pinned(item.tab_id, self.pin.GetValue())
            self._refresh()

    def _group_changed(self, _event) -> None:
        item = self._selected_tab()
        if not item:
            return
        selection = self.group.GetSelection()
        group_id = None if selection <= 0 else self._workspace.state.groups[selection - 1].group_id
        self._workspace.move_tab(item.tab_id, group_id)
        self._refresh()

    def _new_group(self, _event) -> None:
        dialog = MaterialTextEntryDialog(self, "Group name")
        try:
            if dialog.ShowModal() == wx.ID_OK and dialog.GetValue().strip():
                self._workspace.add_group(dialog.GetValue().strip())
                self.group.Append(dialog.GetValue().strip())
                self._refresh()
        finally:
            dialog.Destroy()

    def _activate_selected(self, _event) -> None:
        item = self._selected_tab()
        if not item:
            return
        self._workspace.activate_tab(item.tab_id)
        for index in range(self._notebook.GetPageCount()):
            page = self._notebook.GetPage(index)
            tab_id = getattr(page, "path", None) or ("main-menu" if index == 0 else f"page-{index}")
            if tab_id == item.tab_id:
                self._notebook.SetSelection(index)
                self.EndModal(wx.ID_OK)
                return

    def _open_regex_builder(self, _event) -> None:
        with RegexBuilderDialog(
            self,
            pattern=self.search.GetValue(),
            regex_enabled=self.regex.GetValue(),
            flags=self._regex_flags,
            sample="World map",
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.search.ChangeValue(dialog.pattern)
            self.regex.SetValue(dialog.regex_enabled)
            self._regex_flags = dialog.flags
        self._refresh()


__all__ = ["TabManagerDialog"]
