"""The Material 3 notification centre, backed by :mod:`api.notifications`.

Everything a dismissed notification can still be read from lives here, so the
window is a list first: a filter across every recorded notification, the
records themselves, the technical details behind whichever one is in focus, and
the bulk actions that act on the selection rather than on whatever happened to
be clicked last.

The rows are a
:class:`~amulet_map_editor.api.wx.ui.material_dialog.RecordTable` rather than a
native list.  That is not a restyle: photographed off-screen a native list
comes back as a white rectangle while the capture reports the row as drawn, so
the one part of this window worth checking was the one part nobody could check.

Every count on screen says what it counts.  "Dismiss selected" acts on the
selection and "Dismiss visible" acts on what the filter left showing; those are
different numbers the moment anything is typed into the search field, and a
bulk dismissal that acted on the wrong one would clear notifications the user
had filtered away and never seen.
"""

from __future__ import annotations

import wx

from amulet_map_editor.api import export_actions, notifications, preferences, lang
from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.widgets import StudioButton, StudioCheckBox
from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.api.wx.modeless import finish_dialog
from amulet_map_editor.api.wx.ui.material_dialog import (
    DialogChrome,
    RecordTable,
    TextField,
    heading,
    studio,
)
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
            # Scaled, like every other size in this window.  A constructor size
            # written in device pixels does not follow the display, so at 200%
            # the contents grow and the window does not -- and the difference
            # comes out of whatever the sizer squeezes first.
            size=wx.Size(tokens.scaled(760), tokens.scaled(560)),
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        self._items = []
        self._search_flags = 0
        self.chrome = DialogChrome(self, status_name="Notification export status")

        # -- the filter ------------------------------------------------------
        search_row = wx.BoxSizer(wx.HORIZONTAL)
        self.search_field = TextField(
            self.chrome.body,
            placeholder=_copy("search_hint", self._language_mode),
            name="Notification history search",
        )
        #: The native entry inside the painted outline, kept under the name it
        #: already had so ``GetValue``, ``ChangeValue`` and ``Bind`` read the
        #: same as they did before this window was drawn in Material.
        self.search = self.search_field.text
        self.regex = studio(
            StudioCheckBox(
                self.chrome.body,
                _copy("regex", self._language_mode),
                name=_copy("regex", self._language_mode),
            )
        )
        self.regex.SetToolTip(_copy("regex_help", self._language_mode))
        self.regex_button = studio(
            StudioButton(
                self.chrome.body,
                label="Regex…",
                variant="outlined",
                on_click=self._open_regex_builder,
                name="Notification search regex builder",
                hint="Build a bounded regular-expression search",
            )
        )
        search_row.Add(self.search_field, 1, wx.ALIGN_CENTER_VERTICAL)
        search_row.Add(
            self.regex,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_SM),
        )
        search_row.Add(
            self.regex_button,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_XS),
        )
        self.chrome.add(search_row, 0, wx.EXPAND)
        self.chrome.gap()

        # -- the records -----------------------------------------------------
        self.list = RecordTable(
            self.chrome.body,
            (
                (_copy("state", self._language_mode), 2),
                (_copy("severity", self._language_mode), 2),
                (_copy("column_title", self._language_mode), 4),
                (_copy("message", self._language_mode), 7),
                (_copy("time", self._language_mode), 5),
            ),
            name="Notification history list",
            on_selection=self._selection_changed,
            on_activate=self._dismiss_selected,
            # No empty-state line: this window's copy comes from the language
            # resources, and there is no key for one yet.  A blank surface is
            # what the native list showed, and it is honest; an English
            # sentence inside a window running in Cantonese would not be.
            empty_text="",
        )
        self.chrome.add(self.list, 1, wx.EXPAND)
        self.chrome.gap()

        # -- the details behind one record -----------------------------------
        self.chrome.add(
            heading(
                self.chrome.body,
                _copy("details", self._language_mode),
                size_px=12,
            )
        )
        self.details_field = TextField(
            self.chrome.body,
            value=_copy("no_details", self._language_mode),
            name="Notification technical details",
            multiline=True,
            read_only=True,
            height=110,
            mono=True,
        )
        self.details = self.details_field.text
        self.chrome.add(self.details_field, 0, wx.EXPAND)
        self.chrome.gap()

        # -- the bulk actions ------------------------------------------------
        actions = wx.WrapSizer(wx.HORIZONTAL, wx.REMOVE_LEADING_SPACES)
        self.select_all = self._bulk_button(
            _copy("select_all", self._language_mode), self._select_all
        )
        self.invert_selection = self._bulk_button(
            _copy("invert_selection", self._language_mode), self._invert_selection
        )
        self.dismiss = self._bulk_button(
            _copy("dismiss_selected", self._language_mode), self._dismiss_selected
        )
        self.dismiss_all = self._bulk_button(
            _copy("dismiss_visible", self._language_mode), self._dismiss_visible
        )
        self.export = self._bulk_button(
            _copy("export", self._language_mode), self._export
        )
        self.open_export = self._bulk_button(
            _copy("open_export", self._language_mode), self._open_export
        )
        self.open_export.Enable(False)
        self.copy_details = self._bulk_button(
            _copy("copy_details", self._language_mode), self._copy_details
        )
        self.copy_details.Enable(False)
        for button in (
            self.select_all,
            self.invert_selection,
            self.dismiss,
            self.dismiss_all,
            self.export,
            self.open_export,
            self.copy_details,
        ):
            actions.Add(
                button,
                0,
                wx.RIGHT | wx.BOTTOM,
                tokens.scaled(tokens.SPACE_XS),
            )
        self.chrome.add(actions, 0, wx.EXPAND)

        #: The footer status line, under the name this window already used for
        #: it, so a caller that sets an export message keeps working.
        self.export_status = self.chrome.status
        self.close_button = self.chrome.action(
            _copy("close", self._language_mode),
            variant="filled",
            on_click=self._close,
            name=_copy("close", self._language_mode),
        )

        self.search.Bind(wx.EVT_TEXT, self._refresh)
        self.regex.Bind(wx.EVT_CHECKBOX, self._refresh)
        # Escape dismisses this window, as it did while the close action was a
        # ``wx.ID_CLOSE`` button and wx supplied the binding.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self._refresh()
        self.SetMinSize(wx.Size(tokens.scaled(620), tokens.scaled(460)))
        self.Layout()
        apply_material3(self)

    # -- construction helpers ------------------------------------------------
    def _bulk_button(self, label: str, on_click) -> StudioButton:
        """Return one bulk action, opted out of the native styling pass."""

        return studio(
            StudioButton(
                self.chrome.body,
                label=str(label),
                variant="outlined",
                on_click=on_click,
                name=str(label),
            )
        )

    # -- search --------------------------------------------------------------
    def _open_regex_builder(self, _event=None) -> None:
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
        self.list.set_rows(
            [
                (
                    "dismissed" if item.dismissed else "active",
                    item.severity,
                    item.title,
                    item.body,
                    item.created_at,
                )
                for item in self._items
            ]
        )
        self.dismiss.Enable(bool(self._items))
        self.dismiss_all.Enable(bool(self._items))
        self._selection_changed()

    # -- selection -----------------------------------------------------------
    def _selection_changed(self, _event=None) -> None:
        selected = self.list.selected_indices()
        index = selected[0] if selected else -1
        item = self._items[index] if 0 <= index < len(self._items) else None
        details = item.details if item is not None else ""
        self.details.ChangeValue(details or _copy("no_details", self._language_mode))
        self.copy_details.Enable(bool(details))

    def _copy_details(self, _event=None) -> None:
        value = self.details.GetValue()
        if not self.copy_details.IsEnabled() or not value:
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(value))
            wx.TheClipboard.Close()

    def _dismiss_selected(self, _event=None) -> None:
        selected = [
            self._items[index].notification_id
            for index in self.list.selected_indices()
            if index < len(self._items)
        ]
        if selected:
            notifications.bulk_dismiss(selected)
            self._refresh()

    def _select_all(self, _event=None) -> None:
        self.list.select_all()

    def _invert_selection(self, _event=None) -> None:
        self.list.invert_selection()

    def _dismiss_visible(self, _event=None) -> None:
        notifications.bulk_dismiss(item.notification_id for item in self._items)
        self._refresh()

    # -- export --------------------------------------------------------------
    def _export(self, _event=None) -> None:
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
        self.chrome.set_status(
            _copy("exported_to", self._language_mode).format(
                path=self._last_export_path
            )
        )

    def _open_export(self, _event=None) -> None:
        target = getattr(self, "_last_export_path", None)
        if not target:
            return
        action = export_actions.open_exported_path(target)
        self.chrome.set_status(action.message)

    # -- dismissal -----------------------------------------------------------
    def _close(self, _event=None) -> None:
        """Close whichever way this window was opened.

        The notification centre is shown modeless from the shell and modally
        from a test or a nested surface.  ``EndModal`` on a modeless dialog is
        a wx assertion, and the helper that used to rescue that -- rebinding
        whatever button carried ``wx.ID_CLOSE`` -- cannot find an owner-drawn
        action, because a Studio button has no dialog id to find it by.
        """

        finish_dialog(self, wx.ID_CLOSE)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._close()
            return
        event.Skip()


__all__ = ["NotificationHistoryDialog"]
