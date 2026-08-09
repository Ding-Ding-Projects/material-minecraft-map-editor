"""Native notification-history dialog backed by :mod:`api.notifications`."""

from __future__ import annotations

import wx

from amulet_map_editor.api import export_actions, notifications, preferences, lang
from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.api.wx.ui.path_dialog import choose_path
from amulet_map_editor.api.wx.ui.regex_dialog import RegexBuilderDialog


def _copy(key: str, mode: str) -> str:
    english = lang.get(f"notifications.en.{key}")
    cantonese = lang.get(f"notifications.zh.{key}")
    if mode == "cantonese":
        return cantonese
    if mode == "bilingual":
        return f"{english} · {cantonese}"
    return english


class NotificationHistoryDialog(wx.Dialog):
    def __init__(self, parent: wx.Window):
        self._language_mode = preferences.load().language_mode
        super().__init__(
            parent,
            title=_copy("title", self._language_mode),
            size=wx.Size(760, 520),
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        self._items = []
        root = wx.BoxSizer(wx.VERTICAL)
        search_row = wx.BoxSizer(wx.HORIZONTAL)
        self.search = wx.TextCtrl(self, name="Notification history search")
        self.search.SetHint(_copy("search_hint", self._language_mode))
        self.regex = wx.CheckBox(self, label=_copy("regex", self._language_mode))
        self.regex.SetToolTip(_copy("regex_help", self._language_mode))
        self.regex_button = wx.Button(self, label="Regex…")
        self.regex_button.SetName("Notification search regex builder")
        self.regex_button.SetToolTip("Build a bounded regular-expression search")
        search_row.Add(self.search, 1, wx.EXPAND | wx.RIGHT, 8)
        search_row.Add(self.regex, 0, wx.ALIGN_CENTER_VERTICAL)
        search_row.Add(self.regex_button, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 6)
        root.Add(search_row, 0, wx.EXPAND | wx.ALL, 12)

        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_MULTIPLE_SEL)
        self.list.SetName("Notification history list")
        for index, label in enumerate(
            (
                _copy("state", self._language_mode),
                _copy("severity", self._language_mode),
                _copy("column_title", self._language_mode),
                _copy("message", self._language_mode),
                _copy("time", self._language_mode),
            )
        ):
            self.list.InsertColumn(index, label)
        root.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.dismiss = wx.Button(
            self, label=_copy("dismiss_selected", self._language_mode)
        )
        self.dismiss_all = wx.Button(
            self, label=_copy("dismiss_visible", self._language_mode)
        )
        self.select_all = wx.Button(
            self, label=_copy("select_all", self._language_mode)
        )
        self.invert_selection = wx.Button(
            self, label=_copy("invert_selection", self._language_mode)
        )
        self.export = wx.Button(self, label=_copy("export", self._language_mode))
        self.open_export = wx.Button(
            self, label=_copy("open_export", self._language_mode)
        )
        self.open_export.Enable(False)
        close = wx.Button(
            self, id=wx.ID_CLOSE, label=_copy("close", self._language_mode)
        )
        for button in (
            self.select_all,
            self.invert_selection,
            self.dismiss,
            self.dismiss_all,
            self.export,
            self.open_export,
            close,
        ):
            actions.Add(button, 0, wx.RIGHT, 8)
        self.export_status = wx.StaticText(self, label="")
        self.export_status.SetName("Notification export status")
        root.Add(actions, 0, wx.ALL, 12)
        root.Add(self.export_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(root)
        self._search_flags = 0
        self.search.Bind(wx.EVT_TEXT, self._refresh)
        self.regex.Bind(wx.EVT_CHECKBOX, self._refresh)
        self.regex_button.Bind(wx.EVT_BUTTON, self._open_regex_builder)
        self.select_all.Bind(wx.EVT_BUTTON, self._select_all)
        self.invert_selection.Bind(wx.EVT_BUTTON, self._invert_selection)
        self.list.Bind(wx.EVT_KEY_DOWN, self._list_key_down)
        self.dismiss.Bind(wx.EVT_BUTTON, self._dismiss_selected)
        self.dismiss_all.Bind(wx.EVT_BUTTON, self._dismiss_visible)
        self.export.Bind(wx.EVT_BUTTON, self._export)
        self.open_export.Bind(wx.EVT_BUTTON, self._open_export)
        close.Bind(wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_CLOSE))
        self._refresh()
        apply_material3(self)

    def _open_regex_builder(self, _event) -> None:
        with RegexBuilderDialog(
            self,
            pattern=self.search.GetValue(),
            regex_enabled=self.regex.GetValue(),
            flags=self._search_flags,
            sample="Notification title or message",
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.search.ChangeValue(dialog.pattern)
            self.regex.SetValue(dialog.regex_enabled)
            self._search_flags = dialog.flags
        self._refresh()

    def _refresh(self, _event=None) -> None:
        try:
            self._items = notifications.search(
                self.search.GetValue()[:4096],
                regex=self.regex.GetValue(),
                flags=self._search_flags,
            )
        except ValueError as exc:
            self._items = []
            self.search.SetToolTip(str(exc))
        self.list.DeleteAllItems()
        for item in self._items:
            index = self.list.InsertItem(
                self.list.GetItemCount(), "dismissed" if item.dismissed else "active"
            )
            values = (item.severity, item.title, item.body, item.created_at)
            for column, value in enumerate(values, start=1):
                self.list.SetItem(index, column, value)
        # Keep the real text readable at the captured 1140px surface and at
        # narrower windows: reserve fixed room for state/severity, then divide
        # the remaining width between message and timestamp instead of letting
        # wx truncate every column to its label width.
        width = max(520, self.list.GetClientSize().width)
        self.list.SetColumnWidth(0, 92)
        self.list.SetColumnWidth(1, 92)
        self.list.SetColumnWidth(2, max(140, int(width * 0.22)))
        self.list.SetColumnWidth(3, max(180, int(width * 0.43)))
        self.list.SetColumnWidth(4, max(170, int(width * 0.20)))
        self.dismiss.Enable(bool(self._items))
        self.dismiss_all.Enable(bool(self._items))

    def _dismiss_selected(self, _event) -> None:
        selected = []
        index = self.list.GetNextItem(-1, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
        while index != -1:
            if 0 <= index < len(self._items):
                selected.append(self._items[index].notification_id)
            index = self.list.GetNextItem(
                index, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED
            )
        if selected:
            notifications.bulk_dismiss(selected)
            self._refresh()

    def _select_all(self, _event) -> None:
        for index in range(self.list.GetItemCount()):
            self.list.Select(index)

    def _invert_selection(self, _event) -> None:
        for index in range(self.list.GetItemCount()):
            self.list.Select(index, not self.list.IsSelected(index))

    def _list_key_down(self, event: wx.KeyEvent) -> None:
        """Keep notification bulk dismissal reachable without a pointer."""

        if event.ControlDown() and event.GetKeyCode() == ord("A"):
            self._select_all(event)
            return
        if event.ControlDown() and event.GetKeyCode() == ord("I"):
            self._invert_selection(event)
            return
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._dismiss_selected(event)
            return
        event.Skip()

    def _dismiss_visible(self, _event) -> None:
        notifications.bulk_dismiss(item.notification_id for item in self._items)
        self._refresh()

    def _export(self, _event) -> None:
        target = choose_path(
            self,
            _copy("export_dialog", self._language_mode),
            wildcard="Markdown files (*.md)|*.md",
            save=True,
        )
        if target is None:
            return
        with open(target, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(notifications.export_markdown(self._items))
        self._last_export_path = target
        self.open_export.Enable(True)
        self.export_status.SetLabel(
            _copy("exported_to", self._language_mode).format(
                path=self._last_export_path
            )
        )

    def _open_export(self, _event) -> None:
        target = getattr(self, "_last_export_path", None)
        if not target:
            return
        action = export_actions.open_exported_path(target)
        self.export_status.SetLabel(action.message)
