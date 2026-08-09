"""Native notification-history dialog backed by :mod:`api.notifications`."""

from __future__ import annotations

import wx

from amulet_map_editor.api import notifications


class NotificationHistoryDialog(wx.Dialog):
    def __init__(self, parent: wx.Window):
        super().__init__(parent, title="Notification history", size=wx.Size(760, 520))
        self._items = []
        root = wx.BoxSizer(wx.VERTICAL)
        search_row = wx.BoxSizer(wx.HORIZONTAL)
        self.search = wx.TextCtrl(self, name="Notification history search")
        self.search.SetHint("Search title and message")
        self.regex = wx.CheckBox(self, label="Regex")
        self.regex.SetToolTip("Use the full bounded regular-expression search mode.")
        search_row.Add(self.search, 1, wx.EXPAND | wx.RIGHT, 8)
        search_row.Add(self.regex, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(search_row, 0, wx.EXPAND | wx.ALL, 12)

        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.SetName("Notification history list")
        for index, label in enumerate(("State", "Severity", "Title", "Message", "Time (UTC)")):
            self.list.InsertColumn(index, label)
        root.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.dismiss = wx.Button(self, label="Dismiss selected")
        self.dismiss_all = wx.Button(self, label="Dismiss all visible")
        self.export = wx.Button(self, label="Export Markdown")
        close = wx.Button(self, id=wx.ID_CLOSE, label="Close")
        for button in (self.dismiss, self.dismiss_all, self.export, close):
            actions.Add(button, 0, wx.RIGHT, 8)
        root.Add(actions, 0, wx.ALL, 12)
        self.SetSizer(root)
        self.search.Bind(wx.EVT_TEXT, self._refresh)
        self.regex.Bind(wx.EVT_CHECKBOX, self._refresh)
        self.dismiss.Bind(wx.EVT_BUTTON, self._dismiss_selected)
        self.dismiss_all.Bind(wx.EVT_BUTTON, self._dismiss_visible)
        self.export.Bind(wx.EVT_BUTTON, self._export)
        close.Bind(wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_CLOSE))
        self._refresh()

    def _refresh(self, _event=None) -> None:
        try:
            self._items = notifications.search(
                self.search.GetValue(), regex=self.regex.GetValue()
            )
        except ValueError as exc:
            self._items = []
            self.search.SetToolTip(str(exc))
        self.list.DeleteAllItems()
        for item in self._items:
            index = self.list.InsertItem(self.list.GetItemCount(), "dismissed" if item.dismissed else "active")
            values = (item.severity, item.title, item.body, item.created_at)
            for column, value in enumerate(values, start=1):
                self.list.SetItem(index, column, value)
        self.dismiss.Enable(bool(self._items))
        self.dismiss_all.Enable(bool(self._items))

    def _dismiss_selected(self, _event) -> None:
        index = self.list.GetFirstSelected()
        if index != -1:
            notifications.bulk_dismiss((self._items[index].notification_id,))
            self._refresh()

    def _dismiss_visible(self, _event) -> None:
        notifications.bulk_dismiss(item.notification_id for item in self._items)
        self._refresh()

    def _export(self, _event) -> None:
        with wx.FileDialog(
            self,
            "Export notification history",
            wildcard="Markdown files (*.md)|*.md",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            with open(dialog.GetPath(), "w", encoding="utf-8", newline="\n") as stream:
                stream.write(notifications.export_markdown(self._items))
