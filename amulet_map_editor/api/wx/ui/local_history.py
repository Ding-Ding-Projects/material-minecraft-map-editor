"""Native Material 3 browser for the app-owned local history repository."""

from __future__ import annotations

from datetime import datetime, time, timezone

import wx
import wx.adv

from amulet_map_editor.api import export_actions, local_history, preferences
from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.api.wx.ui.path_dialog import choose_path
from amulet_map_editor.api.wx.ui.regex_dialog import RegexBuilderDialog


class LocalHistoryDialog(wx.Dialog):
    """Search, filter, export, and restore local app history events."""

    def __init__(self, parent: wx.Window):
        super().__init__(
            parent,
            title="Local history",
            size=wx.Size(940, 620),
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        self._store = local_history.LocalHistory.try_create()
        self._events = ()
        self._regex_flags = 0
        self._last_export: str | None = None

        root = wx.BoxSizer(wx.VERTICAL)
        filters = wx.BoxSizer(wx.HORIZONTAL)
        self.search = wx.TextCtrl(self, name="Local history search")
        self.search.SetHint("Search record, type, or action")
        self.regex = wx.CheckBox(self, label="Regex")
        self.regex_button = wx.Button(self, label="Regex…")
        self.regex_button.SetName("Local history search regex builder")
        self.action = wx.Choice(
            self,
            choices=["All actions", "created", "updated", "deleted", "restored"],
        )
        self.action.SetSelection(0)
        self.since = wx.adv.DatePickerCtrl(self, style=wx.adv.DP_DROPDOWN)
        self.until = wx.adv.DatePickerCtrl(self, style=wx.adv.DP_DROPDOWN)
        for control in (self.since, self.until):
            control.SetName("Local history date filter")
        filters.Add(self.search, 1, wx.EXPAND | wx.RIGHT, 8)
        filters.Add(self.regex, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        filters.Add(self.regex_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        filters.Add(self.action, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        filters.Add(self.since, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        filters.Add(self.until, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(filters, 0, wx.EXPAND | wx.ALL, 12)

        self.feedback = wx.StaticText(self, label="")
        self.feedback.SetName("Local history filter status")
        root.Add(self.feedback, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.SetName("Local history events")
        for index, label in enumerate(("Action", "Record", "Type", "Timestamp", "Event")):
            self.list.InsertColumn(index, label)
        root.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.restore = wx.Button(self, label="Restore selected")
        self.restore.Enable(False)
        self.export = wx.Button(self, label="Export visible")
        self.open_export = wx.Button(self, label="Open export in VS Code")
        self.open_export.Enable(False)
        close = wx.Button(self, id=wx.ID_CLOSE, label="Close")
        for button in (self.restore, self.export, self.open_export, close):
            actions.Add(button, 0, wx.RIGHT, 8)
        root.Add(actions, 0, wx.ALL, 12)
        self.SetSizer(root)

        self.search.Bind(wx.EVT_TEXT, self._refresh)
        self.regex.Bind(wx.EVT_CHECKBOX, self._refresh)
        self.regex_button.Bind(wx.EVT_BUTTON, self._open_regex_builder)
        self.action.Bind(wx.EVT_CHOICE, self._refresh)
        self.since.Bind(wx.adv.EVT_DATE_CHANGED, self._refresh)
        self.until.Bind(wx.adv.EVT_DATE_CHANGED, self._refresh)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._selection_changed)
        self.restore.Bind(wx.EVT_BUTTON, self._restore_selected)
        self.export.Bind(wx.EVT_BUTTON, self._export_visible)
        self.open_export.Bind(wx.EVT_BUTTON, self._open_export)
        close.Bind(wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_CLOSE))
        apply_material3(self)
        self._refresh()

    def _open_regex_builder(self, _event) -> None:
        with RegexBuilderDialog(
            self,
            pattern=self.search.GetValue(),
            regex_enabled=self.regex.GetValue(),
            flags=self._regex_flags,
            sample="updated settings",
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.search.ChangeValue(dialog.pattern)
            self.regex.SetValue(dialog.regex_enabled)
            self._regex_flags = dialog.flags
        self._refresh()

    def _date_bounds(self):
        since = self.since.GetValue()
        until = self.until.GetValue()
        return (
            datetime(
                since.GetYear(), since.GetMonth() + 1, since.GetDay(), tzinfo=timezone.utc
            )
            if since.IsValid()
            else None,
            datetime(
                until.GetYear(),
                until.GetMonth() + 1,
                until.GetDay(),
                23,
                59,
                59,
                tzinfo=timezone.utc,
            )
            if until.IsValid()
            else None,
        )

    def _refresh(self, _event=None) -> None:
        if self._store is None:
            self.feedback.SetLabel("Local history is unavailable for this profile.")
            self._events = ()
        else:
            action = self.action.GetStringSelection()
            since, until = self._date_bounds()
            try:
                self._events = self._store.events(
                    self.search.GetValue()[:256],
                    actions=None if action == "All actions" else (action,),
                    since=since,
                    until=until,
                    regex=self.regex.GetValue(),
                )
                self.feedback.SetLabel(f"{len(self._events)} matching history events")
            except (ValueError, local_history.LocalHistoryError) as exc:
                self._events = ()
                self.feedback.SetLabel(f"Invalid history filter: {exc}")
        self.list.DeleteAllItems()
        for event in self._events:
            row = self.list.InsertItem(self.list.GetItemCount(), event.action)
            for column, value in enumerate(
                (event.record_id, event.record_type, event.timestamp, event.event_id), 1
            ):
                self.list.SetItem(row, column, value)
        for column, width in enumerate((90, 220, 120, 190, 260)):
            self.list.SetColumnWidth(column, width)
        self.restore.Enable(False)

    def _selection_changed(self, _event) -> None:
        self.restore.Enable(self.list.GetFirstSelected() != -1)

    def _restore_selected(self, _event) -> None:
        index = self.list.GetFirstSelected()
        if index < 0 or index >= len(self._events) or self._store is None:
            return
        try:
            self._store.restore(self._events[index].event_id)
        except local_history.LocalHistoryError as exc:
            self.feedback.SetLabel(f"Restore failed: {exc}")
            return
        self.feedback.SetLabel("Restored as a new history event")
        self._refresh()

    def _export_visible(self, _event) -> None:
        if self._store is None:
            return
        target = choose_path(self, "Export local history", wildcard="JSON files (*.json)|*.json", save=True)
        if target is None:
            return
        action = self.action.GetStringSelection()
        since, until = self._date_bounds()
        self._store.export(
            target,
            format="json",
            query=self.search.GetValue()[:256],
            actions=None if action == "All actions" else (action,),
            since=since,
            until=until,
            regex=self.regex.GetValue(),
        )
        self._last_export = target
        self.open_export.Enable(True)

    def _open_export(self, _event) -> None:
        if self._last_export:
            result = export_actions.open_exported_path(self._last_export)
            self.feedback.SetLabel(result.message)


__all__ = ["LocalHistoryDialog"]
