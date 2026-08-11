"""The Material 3 browser for the app-owned local history repository.

Search, filter, export, and restore the events the application records for
every settings change, every record it owns, and every restore of either.  A
restore is itself recorded, so nothing here removes history -- undoing an undo
is a further event rather than a rewrite.

The rows are a
:class:`~amulet_map_editor.api.wx.ui.material_dialog.RecordTable`.  A native
list contributes nothing to a capture, which meant the one part of this window
worth checking -- the events themselves -- was the one part no screenshot could
show.

The action filter is a
:class:`~amulet_map_editor.api.studio.widgets.SearchableChoice`, so the
dropdown carries its own search field and regex builder like every other
dropdown in the product; the two date bounds stay
``wx.adv.DatePickerCtrl``, deliberately, because this design system has no
calendar of its own yet and a half-built one would be worse than the
platform's.  That is the one native control left in this window, and it is the
one thing here a capture cannot show.
"""

from __future__ import annotations

from datetime import datetime, timezone

import wx
import wx.adv

from amulet_map_editor.api import export_actions, local_history
from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.widgets import (
    SearchableChoice,
    StudioButton,
    StudioCheckBox,
)
from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.api.wx.modeless import finish_dialog
from amulet_map_editor.api.wx.ui.material_dialog import (
    DialogChrome,
    RecordTable,
    TextField,
    card,
    heading,
    studio,
)
from amulet_map_editor.api.wx.ui.path_dialog import choose_path
from amulet_map_editor.api.wx.ui.regex_dialog import RegexBuilderDialog

#: The filter's own vocabulary.  ``All actions`` is a filter state rather than
#: an action, which is why it is named here rather than read from the store.
ALL_ACTIONS = "All actions"
ACTION_CHOICES = (ALL_ACTIONS, "created", "updated", "deleted", "restored")


class LocalHistoryDialog(wx.Dialog):
    """Search, filter, export, and restore local app history events."""

    def __init__(self, parent: wx.Window):
        super().__init__(
            parent,
            title="Local history",
            # Scaled, like every other size in this window.  A constructor size
            # written in device pixels does not follow the display, so at 200%
            # the contents grow and the window does not -- and the difference
            # comes out of whatever the sizer squeezes first.
            size=wx.Size(tokens.scaled(940), tokens.scaled(640)),
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        self._store = local_history.LocalHistory.try_create()
        self._events = ()
        self._regex_flags = 0
        self._last_export: str | None = None

        self.chrome = DialogChrome(self, status_name="Local history filter status")

        # -- the filters -----------------------------------------------------
        filters = wx.BoxSizer(wx.HORIZONTAL)
        self.search_field = TextField(
            self.chrome.body,
            placeholder="Search record, type, or action",
            name="Local history search",
        )
        #: The native entry inside the painted outline, under the name callers
        #: already had, so ``GetValue`` and ``ChangeValue`` read unchanged.
        self.search = self.search_field.text
        self.regex = studio(
            StudioCheckBox(self.chrome.body, "Regex", name="Read the search as a regex")
        )
        self.regex.SetToolTip(
            "Plain text is the default. Turn this on to read the query as a "
            "regular expression."
        )
        self.regex_button = studio(
            StudioButton(
                self.chrome.body,
                label="Regex…",
                variant="outlined",
                on_click=self._open_regex_builder,
                name="Local history search regex builder",
                hint="Build a bounded regular-expression search",
            )
        )
        filters.Add(self.search_field, 1, wx.ALIGN_CENTER_VERTICAL)
        filters.Add(
            self.regex,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_SM),
        )
        filters.Add(
            self.regex_button,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_XS),
        )
        self.chrome.add(filters, 0, wx.EXPAND)
        self.chrome.gap()

        self.action = studio(
            SearchableChoice(
                self.chrome.body,
                "Action",
                ACTION_CHOICES,
                ALL_ACTIONS,
                on_change=lambda _value: self._refresh(),
            )
        )
        dates, date_row = card(
            self.chrome.body,
            role="surface_container",
            orientation=wx.HORIZONTAL,
            name="Local history date range",
        )
        self.since = wx.adv.DatePickerCtrl(dates, style=wx.adv.DP_DROPDOWN)
        self.until = wx.adv.DatePickerCtrl(dates, style=wx.adv.DP_DROPDOWN)
        self.since.SetToolTip("Only show events on or after this date")
        self.until.SetToolTip("Only show events on or before this date")
        for control in (self.since, self.until):
            control.SetName("Local history date filter")
        date_row.Add(
            heading(dates, "From", size_px=12, role="on_surface_variant"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            tokens.scaled(tokens.SPACE_XS),
        )
        date_row.Add(self.since, 0, wx.ALIGN_CENTER_VERTICAL)
        date_row.Add(
            heading(dates, "to", size_px=12, role="on_surface_variant"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT,
            tokens.scaled(tokens.SPACE_XS),
        )
        date_row.Add(self.until, 0, wx.ALIGN_CENTER_VERTICAL)

        second_row = wx.BoxSizer(wx.HORIZONTAL)
        second_row.Add(self.action, 0, wx.ALIGN_BOTTOM)
        second_row.Add(
            dates,
            0,
            wx.ALIGN_BOTTOM | wx.LEFT,
            tokens.scaled(tokens.SPACE_SM),
        )
        self.chrome.add(second_row, 0)
        self.chrome.gap()

        self.feedback = heading(
            self.chrome.body,
            "",
            size_px=12,
            role="on_surface_variant",
            name="Local history filter status",
        )
        self.chrome.add(self.feedback, 0, wx.EXPAND)
        self.chrome.gap(tokens.SPACE_XS)

        # -- the events ------------------------------------------------------
        self.list = RecordTable(
            self.chrome.body,
            (
                ("Action", 2),
                ("Record", 5),
                ("Type", 3),
                ("Timestamp", 4),
                ("Event", 5),
            ),
            name="Local history events",
            on_selection=self._update_selection_actions,
            on_activate=self._restore_selected,
            empty_text="No history events match these filters.",
        )
        self.chrome.add(self.list, 1, wx.EXPAND)
        self.chrome.gap()

        # -- the bulk actions ------------------------------------------------
        actions = wx.WrapSizer(wx.HORIZONTAL, wx.REMOVE_LEADING_SPACES)
        self.select_all = self._bulk_button("Select all", self._select_all)
        self.invert_selection = self._bulk_button(
            "Invert selection", self._invert_selection
        )
        self.restore = self._bulk_button("Restore selected", self._restore_selected)
        self.restore.Enable(False)
        self.export = self._bulk_button("Export visible", self._export_visible)
        self.open_export = self._bulk_button(
            "Open export in VS Code", self._open_export
        )
        self.open_export.Enable(False)
        for button in (
            self.select_all,
            self.invert_selection,
            self.restore,
            self.export,
            self.open_export,
        ):
            actions.Add(button, 0, wx.RIGHT | wx.BOTTOM, tokens.scaled(tokens.SPACE_XS))
        self.chrome.add(actions, 0, wx.EXPAND)

        self.close_button = self.chrome.action(
            "Close", variant="filled", on_click=self._close, name="Close local history"
        )

        self.search.Bind(wx.EVT_TEXT, self._refresh)
        self.regex.Bind(wx.EVT_CHECKBOX, self._refresh)
        self.since.Bind(wx.adv.EVT_DATE_CHANGED, self._refresh)
        self.until.Bind(wx.adv.EVT_DATE_CHANGED, self._refresh)
        # Escape dismisses this window, as it did while the close action was a
        # ``wx.ID_CLOSE`` button and wx supplied the binding.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.SetMinSize(wx.Size(tokens.scaled(760), tokens.scaled(520)))
        self.Layout()
        apply_material3(self)
        self._refresh()

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

    # -- filters -------------------------------------------------------------
    def _open_regex_builder(self, _event=None) -> None:
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

    def _selected_action(self) -> str:
        """Return the chosen action filter, or the all-actions sentinel."""

        return self.action.value or ALL_ACTIONS

    def _date_bounds(self):
        since = self.since.GetValue()
        until = self.until.GetValue()
        return (
            (
                datetime(
                    since.GetYear(),
                    since.GetMonth() + 1,
                    since.GetDay(),
                    tzinfo=timezone.utc,
                )
                if since.IsValid()
                else None
            ),
            (
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
                else None
            ),
        )

    def _refresh(self, _event=None) -> None:
        if self._store is None:
            self._set_feedback("Local history is unavailable for this profile.")
            self._events = ()
        else:
            action = self._selected_action()
            since, until = self._date_bounds()
            try:
                self._events = self._store.events(
                    self.search.GetValue()[:256],
                    actions=None if action == ALL_ACTIONS else (action,),
                    since=since,
                    until=until,
                    regex=self.regex.GetValue(),
                )
                self._set_feedback(f"{len(self._events)} matching history events")
            except (ValueError, local_history.LocalHistoryError) as exc:
                self._events = ()
                self._set_feedback(f"Invalid history filter: {exc}")
        self.list.set_rows(
            [
                (
                    event.action,
                    event.record_id,
                    event.record_type,
                    event.timestamp,
                    event.event_id,
                )
                for event in self._events
            ]
        )
        self._update_selection_actions()

    def _set_feedback(self, message: str) -> None:
        """Say what the filters left, above the list the filters produced.

        This line and the footer status answer different questions and are
        deliberately not the same text: this one says what is on screen right
        now, and the footer says what the last action actually did.
        """

        self.feedback.SetLabel(str(message))
        self.feedback.SetName(f"Local history filter status: {message}")
        width = self.chrome.body.GetClientSize().width - tokens.scaled(
            self.chrome.padding * 2
        )
        if width > 0:
            self.feedback.Wrap(width)
        self.Layout()

    # -- selection -----------------------------------------------------------
    def _selected_indices(self) -> list[int]:
        return self.list.selected_indices()

    def _update_selection_actions(self, _event=None) -> None:
        count = len(self._selected_indices())
        self.restore.Enable(count > 0)
        if self._events:
            self._set_feedback(
                f"{len(self._events)} matching history events · {count} selected"
            )

    def _select_all(self, _event=None) -> None:
        self.list.select_all()

    def _invert_selection(self, _event=None) -> None:
        self.list.invert_selection()

    def _restore_selected(self, _event=None) -> None:
        indices = [
            index for index in self._selected_indices() if index < len(self._events)
        ]
        if not indices or self._store is None:
            return
        restored = 0
        try:
            for index in indices:
                self._store.restore(self._events[index].event_id)
                restored += 1
        except local_history.LocalHistoryError as exc:
            self.chrome.set_status(f"Restored {restored}; restore failed: {exc}")
            return
        self._refresh()
        self.chrome.set_status(f"Restored {restored} event(s) as new history events")

    # -- export --------------------------------------------------------------
    def _export_visible(self, _event=None) -> None:
        if self._store is None:
            return
        target = choose_path(
            self,
            "Export local history",
            wildcard="JSON files (*.json)|*.json",
            save=True,
        )
        if target is None:
            return
        action = self._selected_action()
        since, until = self._date_bounds()
        self._store.export(
            target,
            format="json",
            query=self.search.GetValue()[:256],
            actions=None if action == ALL_ACTIONS else (action,),
            since=since,
            until=until,
            regex=self.regex.GetValue(),
        )
        self._last_export = target
        self.open_export.Enable(True)
        self.chrome.set_status(f"Exported the visible events to {target}")

    def _open_export(self, _event=None) -> None:
        if self._last_export:
            result = export_actions.open_exported_path(self._last_export)
            self.chrome.set_status(result.message)

    # -- dismissal -----------------------------------------------------------
    def _close(self, _event=None) -> None:
        """Close whichever way this window was opened.

        The browser is shown modally from the shell menu and modeless from the
        Studio surfaces, and ``EndModal`` on a modeless dialog is a wx
        assertion.  The helper that used to rescue that rebound whatever button
        carried ``wx.ID_CLOSE``, which an owner-drawn action has no id to be
        found by.
        """

        finish_dialog(self, wx.ID_CLOSE)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._close()
            return
        event.Skip()


__all__ = ["ACTION_CHOICES", "ALL_ACTIONS", "LocalHistoryDialog"]
