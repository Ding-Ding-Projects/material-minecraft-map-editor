"""Material 3-inspired preferences and command palette surfaces.

The controls intentionally use native wx widgets so the surface remains usable
on headless and accessibility-enabled Windows desktops.  Colour, spacing and
typography are sourced from one persisted :mod:`api.preferences` record.
"""

from __future__ import annotations

from datetime import date
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple
import re
import uuid

import wx
import wx.adv
from wx.lib.wordwrap import wordwrap

from amulet_map_editor.api import (
    appearance_presets,
    appearance_editor,
    changelog,
    external_editor,
    export_actions,
    local_history,
    preferences,
    scheduled_sources,
    settings_search,
    school_mode,
)
from amulet_map_editor.api import lang
from amulet_map_editor.api import scheduled_settings as schedules
from amulet_map_editor.api.regex_builder import (
    RegexBuilder,
    RegexEvaluationController,
    RegexResult,
    plain_text_match_indices,
)
from amulet_map_editor.api.wx.material3 import (
    active_material_palette,
    apply_material3,
)
from amulet_map_editor.api.wx.nonblocking import notify
from amulet_map_editor.api.wx.ui.path_dialog import choose_path
from amulet_map_editor.api.wx.ui.regex_dialog import RegexBuilderDialog
from amulet_map_editor.api.wx.ui.simple import MaterialDateTimeField


def _track_responsive_text(parent: wx.Window, control: wx.StaticText) -> wx.StaticText:
    setattr(control, "_preferences_source_label", control.GetLabel())
    controls = list(getattr(parent, "_preferences_responsive_text", ()))
    controls.append(control)
    setattr(parent, "_preferences_responsive_text", controls)
    return control


def _set_responsive_label(control: wx.StaticText, text: str) -> None:
    """Update dynamic copy without making a later resize restore stale text."""

    setattr(control, "_preferences_source_label", text)
    control.SetLabel(text)


def _walk_children(parent: wx.Window) -> Iterable[wx.Window]:
    """Yield native descendants so width-constrained inputs can shrink safely."""

    pending = list(parent.GetChildren())
    while pending:
        child = pending.pop(0)
        yield child
        pending.extend(child.GetChildren())


def _label(parent: wx.Window, text: str, help_text: str) -> wx.StaticText:
    control = wx.StaticText(parent, label=text)
    control.SetName(text)
    control.SetToolTip(help_text)
    return _track_responsive_text(parent, control)


def _chrome_copy(key: str, mode: str, *, compact: bool = False) -> str:
    """Compose command/changelog chrome from the persisted language resources."""

    english = lang.get(f"preferences.en.{key}")
    cantonese = lang.get(f"preferences.zh.{key}")
    if mode == "cantonese":
        return cantonese
    if mode == "bilingual":
        return f"{english}{chr(10) if compact else ' · '}{cantonese}"
    return english


def _setting_copy(key: str, mode: str, *, description: bool = False) -> str:
    spec = next(
        spec for spec in settings_search.PREFERENCES_SETTING_SPECS if spec.key == key
    )
    localized = spec.localized(mode)
    return localized.description if description else localized.label


class _SearchResultsAccessible(wx.Accessible):
    """Expose custom wrapped rows as one selectable accessibility list."""

    def __init__(self, window: "WrappedSearchResults") -> None:
        super().__init__(window)
        self._window = window

    def GetChildCount(self):
        return wx.ACC_OK, len(self._window._rows)

    def GetRole(self, childId):
        if childId == 0:
            return wx.ACC_OK, wx.ROLE_SYSTEM_LIST
        if 1 <= childId <= len(self._window._rows):
            return wx.ACC_OK, wx.ROLE_SYSTEM_LISTITEM
        return wx.ACC_FAIL, wx.ROLE_SYSTEM_CLIENT

    def GetName(self, childId):
        if childId == 0:
            return wx.ACC_OK, self._window.GetName()
        if 1 <= childId <= len(self._window._rows):
            return wx.ACC_OK, self._window._rows[childId - 1][1].GetLabel()
        return wx.ACC_FAIL, ""

    def GetState(self, childId):
        if childId == 0:
            state = wx.ACC_STATE_SYSTEM_FOCUSABLE
            if self._window.HasFocus():
                state |= wx.ACC_STATE_SYSTEM_FOCUSED
            return wx.ACC_OK, state
        if 1 <= childId <= len(self._window._rows):
            state = wx.ACC_STATE_SYSTEM_SELECTABLE | wx.ACC_STATE_SYSTEM_FOCUSABLE
            if childId - 1 == self._window.GetSelection():
                state |= wx.ACC_STATE_SYSTEM_SELECTED
                if self._window.HasFocus():
                    state |= wx.ACC_STATE_SYSTEM_FOCUSED
            return wx.ACC_OK, state
        return wx.ACC_FAIL, 0

    def GetLocation(self, elementId):
        if elementId == 0:
            return wx.ACC_OK, self._window.GetScreenRect()
        if 1 <= elementId <= len(self._window._rows):
            return wx.ACC_OK, self._window._rows[elementId - 1][0].GetScreenRect()
        return wx.ACC_FAIL, wx.Rect()

    def Select(self, childId, selectFlags):
        if not 1 <= childId <= len(self._window._rows):
            return wx.ACC_FAIL
        if selectFlags & (wx.ACC_SEL_TAKEFOCUS | wx.ACC_SEL_TAKESELECTION):
            self._window.SetSelection(childId - 1)
            self._window.SetFocus()
            return wx.ACC_OK
        if selectFlags & wx.ACC_SEL_REMOVESELECTION:
            self._window.SetSelection(wx.NOT_FOUND)
            return wx.ACC_OK
        return wx.ACC_NOT_IMPLEMENTED

    def GetSelections(self):
        selection = self._window.GetSelection()
        return wx.ACC_OK, ([] if selection == wx.NOT_FOUND else [selection + 1])

    def GetDefaultAction(self, childId):
        if 1 <= childId <= len(self._window._rows):
            return wx.ACC_OK, self._window._default_action_name
        return wx.ACC_FAIL, ""

    def DoDefaultAction(self, childId):
        if not 1 <= childId <= len(self._window._rows):
            return wx.ACC_FAIL
        self._window.SetSelection(childId - 1)
        self._window.SetFocus()
        self._window.ActivateSelection()
        return wx.ACC_OK


class WrappedSearchResults(wx.ScrolledWindow):
    """Keyboard-operable settings results whose full text wraps at narrow widths."""

    def __init__(
        self,
        parent: wx.Window,
        activate: Callable[[wx.Event | None], None],
        default_action_name: str,
    ) -> None:
        super().__init__(parent, style=wx.VSCROLL)
        self.SetScrollRate(0, 12)
        self._activate = activate
        self._default_action_name = default_action_name
        self._selection = wx.NOT_FOUND
        self._rows: List[Tuple[wx.Panel, wx.StaticText]] = []
        self._stack = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self._stack)
        self._accessible = _SearchResultsAccessible(self)
        self.SetAccessible(self._accessible)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)

    def Set(self, items: Sequence[str]) -> None:  # noqa: N802 - mirrors wx.ListBox
        self.Freeze()
        try:
            for child_id in range(1, len(self._rows) + 1):
                wx.Accessible.NotifyEvent(
                    wx.ACC_EVENT_OBJECT_DESTROY,
                    self,
                    wx.OBJID_CLIENT,
                    child_id,
                )
            self._stack.Clear(True)
            self._rows = []
            self._selection = wx.NOT_FOUND
            for index, item in enumerate(items):
                row = wx.Panel(self)
                row.SetName(item)
                row.SetMinSize(wx.Size(1, -1))
                label = wx.StaticText(row, label=item)
                label.SetName(item)
                setattr(label, "_preferences_source_label", item)
                row_sizer = wx.BoxSizer(wx.VERTICAL)
                row_sizer.Add(label, 1, wx.EXPAND | wx.ALL, 8)
                row.SetSizer(row_sizer)
                for target in (row, label):
                    target.Bind(
                        wx.EVT_LEFT_DOWN,
                        lambda event, selected=index: self._on_click(event, selected),
                    )
                    target.Bind(
                        wx.EVT_LEFT_DCLICK,
                        lambda event, selected=index: self._on_double_click(
                            event, selected
                        ),
                    )
                self._rows.append((row, label))
                self._stack.Add(row, 0, wx.EXPAND | wx.BOTTOM, 2)
                wx.Accessible.NotifyEvent(
                    wx.ACC_EVENT_OBJECT_CREATE,
                    self,
                    wx.OBJID_CLIENT,
                    index + 1,
                )
            wx.Accessible.NotifyEvent(
                wx.ACC_EVENT_OBJECT_REORDER,
                self,
                wx.OBJID_CLIENT,
                0,
            )
            apply_material3(self)
            self._paint_selection()
            self._reflow()
        finally:
            self.Thaw()

    def SetSelection(self, index: int) -> None:  # noqa: N802 - mirrors wx.ListBox
        previous = self._selection
        if not 0 <= index < len(self._rows):
            self._selection = wx.NOT_FOUND
        else:
            self._selection = index
            if hasattr(self, "ScrollChildIntoView"):
                self.ScrollChildIntoView(self._rows[index][0])
        self._paint_selection()
        if previous != wx.NOT_FOUND and previous != self._selection:
            wx.Accessible.NotifyEvent(
                wx.ACC_EVENT_OBJECT_SELECTIONREMOVE,
                self,
                wx.OBJID_CLIENT,
                previous + 1,
            )
        if self._selection != wx.NOT_FOUND:
            wx.Accessible.NotifyEvent(
                wx.ACC_EVENT_OBJECT_SELECTION,
                self,
                wx.OBJID_CLIENT,
                self._selection + 1,
            )

    def GetSelection(self) -> int:  # noqa: N802 - mirrors wx.ListBox
        return self._selection

    def ActivateSelection(self) -> None:  # noqa: N802 - accessible list action
        if self._selection == wx.NOT_FOUND:
            return
        self._activate(None)
        wx.Accessible.NotifyEvent(
            wx.ACC_EVENT_OBJECT_FOCUS,
            self,
            wx.OBJID_CLIENT,
            self._selection + 1,
        )

    def _paint_selection(self) -> None:
        palette = active_material_palette()
        normal_background = palette["surface"]
        normal_text = palette["on_surface"]
        selected_background = palette["primary_container"]
        selected_text = palette["on_primary_container"]
        for index, (row, label) in enumerate(self._rows):
            selected = index == self._selection
            row.SetBackgroundColour(
                selected_background if selected else normal_background
            )
            label.SetBackgroundColour(
                selected_background if selected else normal_background
            )
            label.SetForegroundColour(selected_text if selected else normal_text)
            row.Refresh()

    def _on_click(self, event: wx.MouseEvent, index: int) -> None:
        self.SetSelection(index)
        self.SetFocus()
        event.Skip()

    def _on_double_click(self, event: wx.MouseEvent, index: int) -> None:
        self.SetSelection(index)
        self.SetFocus()
        self.ActivateSelection()

    def _on_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_HOME, wx.WXK_END):
            last = len(self._rows) - 1
            if last < 0:
                return
            if key == wx.WXK_HOME:
                target = 0
            elif key == wx.WXK_END:
                target = last
            elif key == wx.WXK_UP:
                target = max(0, (self._selection if self._selection >= 0 else 1) - 1)
            else:
                target = min(last, self._selection + 1)
            self.SetSelection(target)
            return
        event.Skip()

    def _on_size(self, event: wx.SizeEvent) -> None:
        self._reflow()
        event.Skip()

    def _reflow(self) -> None:
        client = self.GetClientSize()
        wrap_width = max(100, client.width - 20)
        dc = wx.ClientDC(self)
        for row, label in self._rows:
            source = getattr(label, "_preferences_source_label", label.GetLabel())
            dc.SetFont(label.GetFont())
            label.SetLabel(wordwrap(source, wrap_width, dc, breakLongWords=True))
            label.SetMinSize(wx.DefaultSize)
            label.InvalidateBestSize()
            label.SetMinSize(wx.Size(1, label.GetBestSize().height + 4))
            row.Layout()
        height = max(client.height, self._stack.CalcMin().height)
        self.SetVirtualSize(wx.Size(max(1, client.width), height))
        self.Layout()


class PreferencesDialog(wx.Dialog):
    """Tabbed settings dialog with language, funny-level, and appearance controls."""

    def __init__(self, parent: wx.Window):
        self._prefs = preferences.load()
        mode = self._prefs.language_mode
        super().__init__(
            parent,
            title=_chrome_copy("window.title", mode),
            size=wx.Size(760, 680),
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        # Preserve the complete single-line native title for window discovery,
        # while giving the narrow M3 title bar a truthful compact bilingual form.
        self._material_title_text = _chrome_copy("window.title", mode, compact=True)
        self._school = school_mode.load()
        controller_copy = {
            "failure_message": settings_search.localized_copy("worker.failure", mode),
            "timeout_message": settings_search.localized_copy("timeout", mode),
        }
        self._font_search_controller = RegexEvaluationController(
            wx.CallAfter, **controller_copy
        )
        self._preset_search_controller = RegexEvaluationController(
            wx.CallAfter, **controller_copy
        )
        self._settings_search_controller = RegexEvaluationController(
            wx.CallAfter, **controller_copy
        )
        self._font_search_flags = re.IGNORECASE
        self._preset_search_flags = re.IGNORECASE
        self._settings_search_flags = re.IGNORECASE
        self._appearance_load_error: Optional[str] = None
        try:
            self._appearance_presets = list(appearance_presets.load_presets())
        except appearance_presets.AppearancePresetValidationError as exc:
            self._appearance_presets = []
            self._appearance_load_error = str(exc)
        self._schedule_load_error: Optional[str] = None
        try:
            self._schedule_rules = list(schedules.load().rules)
        except schedules.ScheduleValidationError as exc:
            self._schedule_rules = []
            self._schedule_load_error = str(exc)
        root = wx.BoxSizer(wx.VERTICAL)
        self._tabs = wx.Notebook(self)
        self._build_language_tab()
        self._build_appearance_tab()
        self._build_schedule_tab()
        self._build_search_tab()
        if self._school.enabled:
            # School mode keeps its own control discoverable, but removes the
            # language/funny controls that are intentionally not applicable.
            self._tabs.RemovePage(self._tabs.FindPage(self._language_page))
        root.Add(self._tabs, 1, wx.EXPAND | wx.ALL, 12)
        buttons = wx.StdDialogButtonSizer()
        self.ok_button = wx.Button(
            self, wx.ID_OK, _chrome_copy("window.ok", mode, compact=True)
        )
        self.cancel_button = wx.Button(
            self,
            wx.ID_CANCEL,
            _chrome_copy("window.cancel", mode, compact=True),
        )
        buttons.AddButton(self.ok_button)
        buttons.AddButton(self.cancel_button)
        buttons.Realize()
        self.reset_button = wx.Button(
            self, label=_chrome_copy("window.reset", mode, compact=True)
        )
        self.reset_button.SetName(_chrome_copy("window.reset", mode))
        self.reset_button.Bind(wx.EVT_BUTTON, self._reset)
        row = wx.BoxSizer(wx.VERTICAL)
        row.Add(
            self.reset_button,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.ALIGN_LEFT,
            12,
        )
        row.Add(buttons, 0, wx.RIGHT | wx.BOTTOM | wx.ALIGN_RIGHT, 12)
        root.Add(row, 0, wx.EXPAND)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(360, 440))
        self.Bind(wx.EVT_BUTTON, self._save, id=wx.ID_OK)
        self.Bind(wx.EVT_SIZE, self._on_preferences_size)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_preferences_destroy)
        self._tabs.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._on_preferences_page_changed)
        # Dialogs can be opened after the frame's one-time shell styling pass.
        # Apply the same M3 roles locally so settings surfaces do not fall back
        # to the native palette when opened from the menu or command palette.
        # Defer native dialog-chrome replacement until wx has finished creating
        # the window. Applying it inside the constructor can make MSW lay out a
        # half-created HWND and terminate the process on isolated desktops.
        wx.CallAfter(apply_material3, self)
        wx.CallAfter(self._update_responsive_layout)

    def _on_preferences_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            for controller in (
                self._font_search_controller,
                self._preset_search_controller,
                self._settings_search_controller,
            ):
                controller.close()
        event.Skip()

    def _on_preferences_page_changed(self, event: wx.BookCtrlEvent) -> None:
        if (
            hasattr(self, "_search_page")
            and self._tabs.GetCurrentPage() is self._search_page
        ):
            self._refresh_settings_search(immediate=True)
        event.Skip()

    def _on_preferences_size(self, event: wx.SizeEvent) -> None:
        self._update_responsive_layout()
        event.Skip()

    def _update_responsive_layout(self) -> None:
        """Reflow labels and refresh virtual sizes without horizontal scrolling."""

        pages = (
            getattr(self, "_language_page", None),
            getattr(self, "_appearance_page", None),
            getattr(self, "_schedule_page", None),
            getattr(self, "_search_page", None),
        )
        # The first fit can add a vertical scrollbar and reduce the client width.
        # Repeating against that final width prevents a five-pixel horizontal
        # overhang at high display scales.
        for _pass in range(2):
            self.Layout()
            for page in pages:
                if page is None:
                    continue
                client_width = max(1, page.GetClientSize().width)
                wrap_width = max(180, client_width - 48)
                flexible_width = max(1, client_width - 36)
                dc = wx.ClientDC(page)
                for control in _walk_children(page):
                    if isinstance(
                        control,
                        (
                            wx.TextCtrl,
                            wx.Choice,
                            wx.ListBox,
                            wx.Slider,
                            wx.SpinCtrl,
                            wx.FontPickerCtrl,
                            wx.ColourPickerCtrl,
                            wx.adv.DatePickerCtrl,
                            wx.adv.TimePickerCtrl,
                        ),
                    ):
                        minimum = control.GetMinSize()
                        height = max(minimum.height, control.GetBestSize().height)
                        control.SetMinSize(wx.Size(1, height))
                        control.SetMaxSize(wx.Size(flexible_width, -1))
                for control in getattr(page, "_preferences_responsive_text", ()):
                    if not control:
                        continue
                    source = getattr(
                        control, "_preferences_source_label", control.GetLabel()
                    )
                    dc.SetFont(control.GetFont())
                    control.SetLabel(
                        wordwrap(source, wrap_width, dc, breakLongWords=True)
                    )
                    control.SetMinSize(wx.DefaultSize)
                    control.InvalidateBestSize()
                    control.SetMinSize(wx.Size(1, control.GetBestSize().height + 4))
                page.Layout()
                if isinstance(page, wx.ScrolledWindow):
                    page.FitInside()
                    virtual = page.GetVirtualSize()
                    page.SetVirtualSize(wx.Size(client_width, virtual.height))
                    page.Layout()
        self.Layout()
        for page in pages:
            if isinstance(page, wx.ScrolledWindow):
                virtual = page.GetVirtualSize()
                page.SetVirtualSize(
                    wx.Size(max(1, page.GetClientSize().width), virtual.height)
                )
                page.Layout()

    def _build_language_tab(self) -> None:
        mode = self._prefs.language_mode
        page = wx.ScrolledWindow(self._tabs, style=wx.VSCROLL)
        page.SetScrollRate(0, 12)
        grid = wx.FlexGridSizer(0, 1, 6, 0)
        grid.AddGrowableCol(0, 1)
        grid.Add(
            _label(
                page,
                _setting_copy("language-mode", mode),
                _setting_copy("language-mode", mode, description=True),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.language = wx.Choice(
            page,
            choices=[
                _chrome_copy("choice.language.english", mode),
                _chrome_copy("choice.language.cantonese", mode),
                _chrome_copy("choice.language.bilingual", mode),
            ],
        )
        self.language.SetSelection(
            preferences.LANGUAGE_MODES.index(self._prefs.language_mode)
        )
        grid.Add(self.language, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                _setting_copy("funny-english", mode),
                _setting_copy("funny-english", mode, description=True),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.funny_en = wx.Slider(
            page,
            minValue=1,
            maxValue=5,
            value=self._prefs.funny_level_english,
            style=wx.SL_LABELS,
        )
        grid.Add(self.funny_en, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                _setting_copy("funny-cantonese", mode),
                _setting_copy("funny-cantonese", mode, description=True),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.funny_yue = wx.Slider(
            page,
            minValue=1,
            maxValue=5,
            value=self._prefs.funny_level_cantonese,
            style=wx.SL_LABELS,
        )
        grid.Add(self.funny_yue, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                _setting_copy("dialog-emojis", mode),
                _setting_copy("dialog-emojis", mode, description=True),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.dialog_emojis = wx.CheckBox(
            page,
            label=_chrome_copy("language.show.emojis", mode, compact=True),
        )
        self.dialog_emojis.SetValue(self._prefs.show_dialog_emojis)
        grid.Add(self.dialog_emojis, 1, wx.EXPAND)
        page.SetSizer(wx.BoxSizer(wx.VERTICAL))
        page.GetSizer().Add(grid, 0, wx.EXPAND | wx.ALL, 18)
        self._language_page = page
        self._tabs.AddPage(
            page, settings_search.localized_copy("tab.language", mode), True
        )
        page.FitInside()

    def _build_appearance_tab(self) -> None:
        mode = self._prefs.language_mode
        page = wx.ScrolledWindow(self._tabs, style=wx.VSCROLL)
        page.SetScrollRate(0, 12)
        root = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(0, 1, 6, 0)
        grid.AddGrowableCol(0, 1)
        grid.Add(
            _label(
                page,
                _setting_copy("display-name", mode),
                _setting_copy("display-name", mode, description=True),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        identity_row = wx.BoxSizer(wx.VERTICAL)
        self.display_name = wx.TextCtrl(
            page,
            value=self._prefs.display_name,
            name=_setting_copy("display-name", mode),
        )
        self.display_name.SetMaxLength(preferences.MAX_DISPLAY_NAME_LENGTH)
        self.display_name_reset = wx.Button(
            page,
            label=_chrome_copy("appearance.reset.name", mode, compact=True),
        )
        self.display_name_reset.SetToolTip(
            _chrome_copy("appearance.reset.name.help", mode)
        )
        self.display_name_reset.Bind(wx.EVT_BUTTON, self._reset_display_name_form)
        identity_row.Add(self.display_name, 1, wx.EXPAND | wx.RIGHT, 8)
        identity_row.Add(self.display_name_reset, 0)
        grid.Add(identity_row, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                _setting_copy("school-enabled", mode),
                _setting_copy("school-enabled", mode, description=True),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        school_row = wx.BoxSizer(wx.VERTICAL)
        self.school_name = wx.TextCtrl(page, value=self._school.mode_name)
        self.school_name.SetMaxLength(school_mode.MAX_MODE_NAME_LENGTH)
        self.school_name.SetName(_setting_copy("school-name", mode))
        self.school_enabled = wx.CheckBox(
            page,
            label=_chrome_copy("appearance.school.enabled", mode, compact=True),
        )
        self.school_enabled.SetValue(self._school.enabled)
        school_row.Add(self.school_name, 1, wx.EXPAND | wx.RIGHT, 8)
        school_row.Add(self.school_enabled, 0)
        grid.Add(school_row, 1, wx.EXPAND)
        if self._school.enabled:
            active = wx.StaticText(
                page,
                label=_chrome_copy("appearance.school.active", mode),
            )
            active.SetName("School mode active status")
            grid.AddSpacer(1)
            grid.Add(active, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                _setting_copy("school-credential", mode),
                _setting_copy("school-credential", mode, description=True),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.school_credential = wx.TextCtrl(
            page,
            style=wx.TE_PASSWORD,
            name=_setting_copy("school-credential", mode),
        )
        self.school_credential.SetHint(_chrome_copy("appearance.credential.hint", mode))
        grid.Add(self.school_credential, 1, wx.EXPAND)
        grid.AddSpacer(1)
        self.identity_status = wx.StaticText(page, label="")
        self.identity_status.SetName("App display name validation")
        _track_responsive_text(page, self.identity_status)
        grid.Add(self.identity_status, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                _setting_copy("theme", mode),
                _setting_copy("theme", mode, description=True),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.theme = wx.Choice(
            page,
            choices=[
                _chrome_copy("choice.theme.light", mode),
                _chrome_copy("choice.theme.dark", mode),
                _chrome_copy("choice.theme.system", mode),
            ],
        )
        self.theme.SetSelection(preferences.THEMES.index(self._prefs.theme))
        grid.Add(self.theme, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                _setting_copy("density", mode),
                _setting_copy("density", mode, description=True),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.density = wx.Choice(
            page,
            choices=[
                _chrome_copy("choice.density.compact", mode),
                _chrome_copy("choice.density.comfortable", mode),
                _chrome_copy("choice.density.spacious", mode),
            ],
        )
        self.density.SetSelection(
            ("compact", "comfortable", "spacious").index(self._prefs.density)
        )
        grid.Add(self.density, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                _setting_copy("accent", mode),
                _setting_copy("accent", mode, description=True),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.accent = wx.TextCtrl(page, value=self._prefs.accent)
        self.accent.SetName("Accent colour HEX")
        self.accent.SetHint("#RRGGBB or #RRGGBBAA")
        grid.Add(self.accent, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                _chrome_copy("appearance.colour.translator", mode),
                _chrome_copy("appearance.colour.translator.help", mode),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        colour_row = wx.BoxSizer(wx.VERTICAL)
        self.accent_rgb = wx.TextCtrl(
            page, style=wx.TE_PROCESS_ENTER, name="Accent colour RGB"
        )
        self.accent_rgb.SetHint("RGB: 103, 80, 164")
        self.accent_hsl = wx.TextCtrl(
            page, style=wx.TE_PROCESS_ENTER, name="Accent colour HSL"
        )
        self.accent_hsl.SetHint("HSL: 262, 34%, 48%")
        self.accent_colour_picker = wx.ColourPickerCtrl(
            page, name="Accent colour picker"
        )
        self.accent_swatch = wx.StaticText(page, label="  ")
        self.accent_swatch.SetName("Accent colour preview")
        self.accent_contrast = wx.StaticText(page, label="")
        self.accent_contrast.SetName("Accent colour contrast readout")
        _track_responsive_text(page, self.accent_contrast)
        colour_row.Add(self.accent_rgb, 1, wx.EXPAND | wx.RIGHT, 6)
        colour_row.Add(self.accent_hsl, 1, wx.EXPAND | wx.RIGHT, 6)
        colour_row.Add(self.accent_colour_picker, 0, wx.RIGHT, 6)
        colour_row.Add(self.accent_swatch, 0, wx.EXPAND | wx.RIGHT, 6)
        colour_row.Add(self.accent_contrast, 0)
        grid.Add(colour_row, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                _setting_copy("ui-font", mode),
                _setting_copy("ui-font", mode, description=True),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.font = wx.FontPickerCtrl(page)
        self.font.SetName(_setting_copy("ui-font", mode))
        self._set_appearance_font(self._prefs.ui_font)
        self.font.Bind(wx.EVT_FONTPICKER_CHANGED, self._select_appearance_font)
        grid.Add(self.font, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                _chrome_copy("appearance.font.search.label", mode),
                _chrome_copy("appearance.font.search.help", mode),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        font_search_row = wx.BoxSizer(wx.VERTICAL)
        self.font_search = wx.TextCtrl(
            page, name=_chrome_copy("appearance.font.search.label", mode)
        )
        self.font_search.SetHint(_chrome_copy("appearance.font.search.hint", mode))
        self.font_regex = wx.CheckBox(
            page, label=_chrome_copy("appearance.regex", mode, compact=True)
        )
        self.font_regex.SetName(_chrome_copy("appearance.regex", mode))
        self.font_regex_button = wx.Button(
            page,
            label=_chrome_copy("appearance.regex.button", mode, compact=True),
        )
        self.font_regex_button.SetName(
            _chrome_copy("appearance.font.search.label", mode)
        )
        self.font_regex_button.SetToolTip(
            _chrome_copy("appearance.font.regex.help", mode)
        )
        self.font_choice = wx.Choice(page, choices=[])
        self.font_choice.SetName(_chrome_copy("appearance.font.search.label", mode))
        font_search_row.Add(self.font_search, 1, wx.EXPAND | wx.RIGHT, 8)
        font_search_row.Add(self.font_regex, 0, wx.RIGHT, 8)
        font_search_row.Add(self.font_regex_button, 0, wx.RIGHT, 8)
        font_search_row.Add(self.font_choice, 1, wx.EXPAND)
        grid.Add(font_search_row, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                _setting_copy("external-editor", mode),
                _setting_copy("external-editor", mode, description=True),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        editor_row = wx.BoxSizer(wx.VERTICAL)
        self.external_editor_path = wx.TextCtrl(
            page,
            value=external_editor.load_selected(),
            name=_setting_copy("external-editor", mode),
        )
        self.external_editor_path.SetHint(
            _chrome_copy("appearance.external.hint", mode)
        )
        self.external_editor_browse = wx.Button(
            page,
            label=_chrome_copy("appearance.external.browse", mode, compact=True),
        )
        self.external_editor_test = wx.Button(
            page,
            label=_chrome_copy("appearance.external.check", mode, compact=True),
        )
        editor_row.Add(self.external_editor_path, 1, wx.EXPAND | wx.RIGHT, 8)
        editor_row.Add(self.external_editor_browse, 0, wx.RIGHT, 8)
        editor_row.Add(self.external_editor_test, 0)
        grid.Add(editor_row, 1, wx.EXPAND)
        self.external_editor_status = wx.StaticText(page, label="")
        self.external_editor_status.SetName(_setting_copy("external-editor", mode))
        _track_responsive_text(page, self.external_editor_status)
        grid.AddSpacer(1)
        grid.Add(self.external_editor_status, 1, wx.EXPAND)
        self.font_preview = wx.StaticText(
            page, label=_chrome_copy("appearance.font.preview", mode)
        )
        self.font_preview.SetName(_chrome_copy("appearance.font.preview", mode))
        _track_responsive_text(page, self.font_preview)
        grid.AddSpacer(1)
        grid.Add(self.font_preview, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                _setting_copy("ui-scale", mode),
                _setting_copy("ui-scale", mode, description=True),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.scale = wx.Slider(
            page,
            minValue=80,
            maxValue=200,
            value=int(self._prefs.ui_scale * 100),
            style=wx.SL_LABELS,
        )
        grid.Add(self.scale, 1, wx.EXPAND)
        root.Add(grid, 0, wx.EXPAND | wx.BOTTOM, 18)

        root.Add(
            _label(
                page,
                _chrome_copy("appearance.presets.label", mode),
                _chrome_copy("appearance.presets.help", mode),
            ),
            0,
            wx.BOTTOM,
            6,
        )
        preset_row = wx.BoxSizer(wx.VERTICAL)
        self.appearance_preset_list = wx.Choice(page, choices=[])
        self.appearance_preset_list.SetName(
            _chrome_copy("appearance.presets.label", mode)
        )
        self.appearance_preset_name = wx.TextCtrl(page)
        self.appearance_preset_name.SetHint(
            _chrome_copy("appearance.presets.name.hint", mode)
        )
        self.appearance_preset_name.SetName(
            _chrome_copy("appearance.presets.name.hint", mode)
        )
        preset_row.Add(self.appearance_preset_list, 1, wx.EXPAND | wx.RIGHT, 8)
        preset_row.Add(self.appearance_preset_name, 1, wx.EXPAND)
        root.Add(preset_row, 0, wx.EXPAND | wx.BOTTOM, 8)

        preset_search_row = wx.BoxSizer(wx.VERTICAL)
        self.appearance_preset_search = wx.TextCtrl(page)
        self.appearance_preset_search.SetHint(
            _chrome_copy("appearance.presets.search.hint", mode)
        )
        self.appearance_preset_search.SetName(
            _chrome_copy("appearance.presets.search.hint", mode)
        )
        self.appearance_preset_regex = wx.CheckBox(
            page, label=_chrome_copy("appearance.regex", mode, compact=True)
        )
        self.appearance_preset_regex_button = wx.Button(
            page,
            label=_chrome_copy("appearance.regex.button", mode, compact=True),
        )
        self.appearance_preset_regex_button.SetName(
            _chrome_copy("appearance.regex.button", mode)
        )
        self.appearance_preset_regex_button.SetToolTip(
            _chrome_copy("appearance.presets.regex.help", mode)
        )
        preset_search_row.Add(self.appearance_preset_search, 1, wx.EXPAND | wx.RIGHT, 8)
        preset_search_row.Add(self.appearance_preset_regex, 0)
        preset_search_row.Add(
            self.appearance_preset_regex_button,
            0,
            wx.LEFT,
            6,
        )
        root.Add(preset_search_row, 0, wx.EXPAND | wx.BOTTOM, 8)

        preset_actions = wx.BoxSizer(wx.VERTICAL)
        self.appearance_preset_load = wx.Button(
            page,
            label=_chrome_copy("appearance.presets.load", mode, compact=True),
        )
        self.appearance_preset_save = wx.Button(
            page,
            label=_chrome_copy("appearance.presets.save", mode, compact=True),
        )
        self.appearance_preset_update = wx.Button(
            page,
            label=_chrome_copy("appearance.presets.update", mode, compact=True),
        )
        self.appearance_preset_export = wx.Button(
            page,
            label=_chrome_copy("appearance.presets.export", mode, compact=True),
        )
        self.appearance_preset_open = wx.Button(
            page,
            label=_chrome_copy("appearance.presets.open", mode, compact=True),
        )
        self.appearance_preset_open.Enable(False)
        self.appearance_preset_import = wx.Button(
            page,
            label=_chrome_copy("appearance.presets.import", mode, compact=True),
        )
        self.appearance_preset_delete = wx.Button(
            page,
            label=_chrome_copy("appearance.presets.delete", mode, compact=True),
        )
        for control in (
            self.appearance_preset_load,
            self.appearance_preset_save,
            self.appearance_preset_update,
            self.appearance_preset_export,
            self.appearance_preset_open,
            self.appearance_preset_import,
            self.appearance_preset_delete,
        ):
            preset_actions.Add(control, 0, wx.RIGHT | wx.BOTTOM, 8)
        root.Add(preset_actions, 0, wx.EXPAND)

        reset_row = wx.BoxSizer(wx.VERTICAL)
        self.appearance_reset_property = wx.Choice(
            page,
            choices=[
                _chrome_copy("appearance.reset.theme", mode),
                _chrome_copy("appearance.reset.density", mode),
                _chrome_copy("appearance.reset.accent", mode),
                _chrome_copy("appearance.reset.font", mode),
                _chrome_copy("appearance.reset.scale", mode),
            ],
        )
        self.appearance_reset_property.SetSelection(0)
        self.appearance_reset_property.SetName(
            _chrome_copy("appearance.reset.selected", mode)
        )
        self.appearance_reset_selected = wx.Button(
            page,
            label=_chrome_copy("appearance.reset.selected", mode, compact=True),
        )
        self.appearance_reset_all = wx.Button(
            page,
            label=_chrome_copy("appearance.reset.all", mode, compact=True),
        )
        self.appearance_reset_all.SetName(_chrome_copy("appearance.reset.all", mode))
        reset_row.Add(self.appearance_reset_property, 1, wx.EXPAND | wx.RIGHT, 8)
        reset_row.Add(self.appearance_reset_selected, 0, wx.RIGHT, 8)
        reset_row.Add(self.appearance_reset_all, 0)
        root.Add(reset_row, 0, wx.EXPAND | wx.TOP, 4)

        self.appearance_status = wx.StaticText(page, label="")
        self.appearance_status.SetName(_chrome_copy("appearance.presets.label", mode))
        _track_responsive_text(page, self.appearance_status)
        root.Add(self.appearance_status, 0, wx.EXPAND | wx.TOP, 10)

        self.appearance_preset_list.Bind(wx.EVT_CHOICE, self._select_appearance_preset)
        self.appearance_preset_load.Bind(wx.EVT_BUTTON, self._load_appearance_preset)
        self.appearance_preset_save.Bind(wx.EVT_BUTTON, self._save_appearance_preset)
        self.appearance_preset_update.Bind(
            wx.EVT_BUTTON, self._update_appearance_preset
        )
        self.appearance_preset_export.Bind(
            wx.EVT_BUTTON, self._export_appearance_preset
        )
        self.appearance_preset_open.Bind(wx.EVT_BUTTON, self._open_appearance_export)
        self.appearance_preset_import.Bind(
            wx.EVT_BUTTON, self._import_appearance_preset
        )
        self.appearance_preset_delete.Bind(
            wx.EVT_BUTTON, self._delete_appearance_preset
        )
        self.appearance_preset_search.Bind(
            wx.EVT_TEXT, lambda _event: self._refresh_appearance_presets()
        )
        self.appearance_preset_regex.Bind(
            wx.EVT_CHECKBOX, lambda _event: self._refresh_appearance_presets()
        )
        self.font_regex_button.Bind(wx.EVT_BUTTON, self._open_font_regex_builder)
        self.appearance_preset_regex_button.Bind(
            wx.EVT_BUTTON, self._open_preset_regex_builder
        )
        self.appearance_reset_selected.Bind(
            wx.EVT_BUTTON, self._reset_appearance_property
        )
        self.appearance_reset_all.Bind(wx.EVT_BUTTON, self._reset_appearance_form)
        self.accent.Bind(wx.EVT_TEXT, self._accent_hex_changed)
        self.accent_rgb.Bind(wx.EVT_TEXT_ENTER, self._accent_rgb_changed)
        self.accent_hsl.Bind(wx.EVT_TEXT_ENTER, self._accent_hsl_changed)
        self.accent_colour_picker.Bind(
            wx.EVT_COLOURPICKER_CHANGED, self._accent_picker_changed
        )
        self.font_search.Bind(wx.EVT_TEXT, self._filter_appearance_fonts)
        self.font_regex.Bind(wx.EVT_CHECKBOX, self._filter_appearance_fonts)
        self.font_choice.Bind(wx.EVT_CHOICE, self._select_font_choice)
        self.scale.Bind(wx.EVT_SLIDER, self._scale_appearance_preview)
        self.external_editor_browse.Bind(wx.EVT_BUTTON, self._browse_external_editor)
        self.external_editor_test.Bind(wx.EVT_BUTTON, self._test_external_editor)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(root, 1, wx.EXPAND | wx.ALL, 18)
        page.SetSizer(outer)
        page.FitInside()
        self._appearance_page = page
        self._appearance_tab_index = self._tabs.GetPageCount()
        self._tabs.AddPage(page, _chrome_copy("tab.appearance", mode))
        self._appearance_library_controls = (
            self.appearance_preset_list,
            self.appearance_preset_name,
            self.appearance_preset_search,
            self.appearance_preset_regex,
            self.appearance_preset_load,
            self.appearance_preset_save,
            self.appearance_preset_update,
            self.appearance_preset_export,
            self.appearance_preset_open,
            self.appearance_preset_import,
            self.appearance_preset_delete,
        )
        if self._appearance_load_error is None:
            self._refresh_appearance_presets()
        else:
            self.appearance_preset_list.Set([])
            for control in self._appearance_library_controls:
                control.Enable(False)
            self._show_appearance_message(
                "Stored presets could not be loaded and were left unchanged: "
                + self._appearance_load_error,
                error=True,
            )
        self._appearance_font_names = self._installed_font_names()
        self._filter_appearance_fonts()
        self._update_accent_controls(self._prefs.accent)

    def _reset_display_name_form(self, _event: wx.Event) -> None:
        self.display_name.SetValue(preferences.DEFAULT_DISPLAY_NAME)
        _set_responsive_label(
            self.identity_status, "The shipped name is staged. Choose OK to save it."
        )
        self.identity_status.SetForegroundColour(wx.Colour(40, 120, 70))

    def _browse_external_editor(self, _event: wx.Event) -> None:
        """Stage a user-selected Code executable without launching it."""
        value = choose_path(
            self,
            "Choose external editor executable",
            wildcard="Code executables (*.exe;*.cmd;code)|*.exe;*.cmd;code|All files (*.*)|*.*",
        )
        if not value:
            return
        result = external_editor.validate_editor_path(value)
        if not result.ok:
            _set_responsive_label(self.external_editor_status, result.message)
            self.external_editor_status.SetForegroundColour(wx.Colour(180, 40, 40))
            return
        self.external_editor_path.SetValue(str(Path(value).resolve()))
        _set_responsive_label(
            self.external_editor_status, "Editor path staged. Choose OK to save it."
        )
        self.external_editor_status.SetForegroundColour(wx.Colour(40, 120, 70))

    def _test_external_editor(self, _event: wx.Event) -> None:
        result = external_editor.validate_editor_path(
            self.external_editor_path.GetValue()
        )
        _set_responsive_label(self.external_editor_status, result.message)
        self.external_editor_status.SetForegroundColour(
            wx.Colour(40, 120, 70) if result.ok else wx.Colour(180, 40, 40)
        )

    def _show_appearance_message(self, message: str, error: bool = False) -> None:
        _set_responsive_label(self.appearance_status, message)
        self.appearance_status.SetForegroundColour(
            wx.Colour(180, 40, 40) if error else wx.Colour(40, 120, 70)
        )
        self._update_responsive_layout()

    def _set_appearance_font(self, font_name: str) -> None:
        font = (
            wx.Font(
                10,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_NORMAL,
                faceName=font_name,
            )
            if font_name
            else wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        )
        self.font.SetSelectedFont(font)
        self._appearance_font_uses_platform_default = not bool(font_name)
        if hasattr(self, "font_preview"):
            preview_font = font
            preview_font.SetPointSize(max(9, round(11 * self.scale.GetValue() / 100)))
            self.font_preview.SetFont(preview_font)

    def _select_appearance_font(self, _event: wx.Event) -> None:
        self._appearance_font_uses_platform_default = False
        self._update_font_preview(self.font.GetSelectedFont())

    def _open_font_regex_builder(self, _event) -> None:
        with RegexBuilderDialog(
            self,
            pattern=self.font_search.GetValue(),
            regex_enabled=self.font_regex.GetValue(),
            flags=getattr(self, "_font_search_flags", 0),
            sample=_chrome_copy("sample.font", self._prefs.language_mode),
            language_mode=self._prefs.language_mode,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.font_search.ChangeValue(dialog.pattern)
            self.font_regex.SetValue(dialog.regex_enabled)
            self._font_search_flags = dialog.flags
        self._filter_appearance_fonts(immediate=True)

    def _open_preset_regex_builder(self, _event) -> None:
        with RegexBuilderDialog(
            self,
            pattern=self.appearance_preset_search.GetValue(),
            regex_enabled=self.appearance_preset_regex.GetValue(),
            flags=getattr(self, "_preset_search_flags", 0),
            sample=_chrome_copy("sample.preset", self._prefs.language_mode),
            language_mode=self._prefs.language_mode,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.appearance_preset_search.ChangeValue(dialog.pattern)
            self.appearance_preset_regex.SetValue(dialog.regex_enabled)
            self._preset_search_flags = dialog.flags
        self._refresh_appearance_presets(immediate=True)

    @staticmethod
    def _installed_font_names() -> Tuple[str, ...]:
        try:
            enumerator = wx.FontEnumerator()
            enumerator.EnumerateFacenames()
            return appearance_editor.filter_font_names(enumerator.GetFacenames(), "")
        except (AttributeError, RuntimeError):
            return ()

    def _filter_appearance_fonts(
        self, _event: wx.Event | None = None, *, immediate: bool = False
    ) -> None:
        source_names = getattr(self, "_appearance_font_names", ())
        query = (
            self.font_search.GetValue().strip() if hasattr(self, "font_search") else ""
        )
        if not query:
            self._font_search_controller.cancel()
            self._apply_font_search_result(source_names)
            return
        flags = getattr(self, "_font_search_flags", 0)
        if not self.font_regex.GetValue():
            self._font_search_controller.cancel()
            indices = plain_text_match_indices(
                source_names,
                query,
                ignore_case=bool(flags & re.IGNORECASE),
            )
            self._apply_font_search_result(
                tuple(source_names[index] for index in indices)
            )
            return
        if getattr(self, "font_regex", None) is not None:
            builder = RegexBuilder(
                query[:4096],
                regex_enabled=True,
                flags=flags,
            )
            self.font_search.SetToolTip(
                settings_search.localized_copy("searching", self._prefs.language_mode)
            )
            self._font_search_controller.submit(
                builder.request(source_names),
                lambda result, source=tuple(source_names): self._finish_font_search(
                    source, result
                ),
                immediate=immediate,
            )
            return
        self._apply_font_search_result(())

    def _finish_font_search(
        self, source_names: Tuple[str, ...], result: RegexResult
    ) -> None:
        if result.timed_out:
            self.font_search.SetToolTip(
                settings_search.localized_copy("timeout", self._prefs.language_mode)
            )
            self._apply_font_search_result(())
            return
        if not result.valid:
            self.font_search.SetToolTip(
                settings_search.localized_copy(
                    "invalid",
                    self._prefs.language_mode,
                    error=result.error or "",
                )
            )
            self._apply_font_search_result(())
            return
        names = tuple(source_names[index] for index in result.matched_indices)
        self.font_search.SetToolTip(
            settings_search.localized_copy("builder.help", self._prefs.language_mode)
        )
        self._apply_font_search_result(names)

    def _apply_font_search_result(self, names: Tuple[str, ...]) -> None:
        self.font_choice.Set(list(names))
        current = self.font.GetSelectedFont().GetFaceName()
        if current in names:
            self.font_choice.SetStringSelection(current)

    def _select_font_choice(self, _event: wx.Event) -> None:
        name = self.font_choice.GetStringSelection().strip()
        if name:
            self._set_appearance_font(name)

    def _update_font_preview(self, font: wx.Font) -> None:
        if hasattr(self, "font_preview"):
            preview_font = font
            preview_font.SetPointSize(max(9, round(11 * self.scale.GetValue() / 100)))
            self.font_preview.SetFont(preview_font)

    def _scale_appearance_preview(self, _event: wx.Event) -> None:
        self._update_font_preview(self.font.GetSelectedFont())

    def _update_accent_controls(self, value: str) -> None:
        try:
            rgb = appearance_editor.parse_hex(value)
        except ValueError:
            return
        self._appearance_color_syncing = True
        try:
            self.accent.SetValue(appearance_editor.rgb_to_hex(rgb))
            self.accent_rgb.SetValue(appearance_editor.format_rgb(rgb))
            self.accent_hsl.SetValue(appearance_editor.format_hsl(rgb))
            self.accent_colour_picker.SetColour(wx.Colour(*rgb))
            self.accent_swatch.SetBackgroundColour(wx.Colour(*rgb))
            _set_responsive_label(
                self.accent_contrast, appearance_editor.contrast_summary(rgb)
            )
        finally:
            self._appearance_color_syncing = False

    def _accent_hex_changed(self, _event: wx.Event) -> None:
        if getattr(self, "_appearance_color_syncing", False):
            return
        try:
            self._update_accent_controls(self.accent.GetValue())
        except ValueError:
            pass

    def _accent_rgb_changed(self, _event: wx.Event) -> None:
        if getattr(self, "_appearance_color_syncing", False):
            return
        try:
            self._update_accent_controls(
                appearance_editor.rgb_to_hex(
                    appearance_editor.parse_rgb(self.accent_rgb.GetValue())
                )
            )
        except ValueError:
            self._show_appearance_message(
                "RGB must contain three values from 0 to 255.", error=True
            )

    def _accent_hsl_changed(self, _event: wx.Event) -> None:
        if getattr(self, "_appearance_color_syncing", False):
            return
        try:
            self._update_accent_controls(
                appearance_editor.rgb_to_hex(
                    appearance_editor.parse_hsl(self.accent_hsl.GetValue())
                )
            )
        except ValueError:
            self._show_appearance_message(
                "HSL must contain hue, saturation%, and lightness%.", error=True
            )

    def _accent_picker_changed(self, _event: wx.Event) -> None:
        if getattr(self, "_appearance_color_syncing", False):
            return
        colour = self.accent_colour_picker.GetColour()
        self._update_accent_controls(
            appearance_editor.rgb_to_hex((colour.Red(), colour.Green(), colour.Blue()))
        )

    def _appearance_values_from_form(self) -> appearance_presets.AppearanceValues:
        return appearance_presets.AppearanceValues(
            theme=preferences.THEMES[self.theme.GetSelection()],
            density=preferences.DENSITIES[self.density.GetSelection()],
            accent=self.accent.GetValue().strip(),
            ui_font=(
                ""
                if self._appearance_font_uses_platform_default
                else self.font.GetSelectedFont().GetFaceName()
            ),
            ui_scale=self.scale.GetValue() / 100.0,
        ).validated()

    def _set_appearance_form(self, values: appearance_presets.AppearanceValues) -> None:
        values = values.validated()
        self.theme.SetSelection(preferences.THEMES.index(values.theme))
        self.density.SetSelection(preferences.DENSITIES.index(values.density))
        self.accent.SetValue(values.accent)
        self._set_appearance_font(values.ui_font)
        self.scale.SetValue(round(values.ui_scale * 100))
        self._update_accent_controls(values.accent)

    def _refresh_appearance_presets(
        self, selected_name: str = "", *, immediate: bool = False
    ) -> None:
        source = tuple(appearance_presets.load_presets())
        query = self.appearance_preset_search.GetValue().strip()
        if not query:
            self._preset_search_controller.cancel()
            self._apply_preset_search_result(source, selected_name)
            return
        flags = getattr(self, "_preset_search_flags", 0)
        names = tuple(preset.name for preset in source)
        if not self.appearance_preset_regex.GetValue():
            self._preset_search_controller.cancel()
            indices = plain_text_match_indices(
                names, query, ignore_case=bool(flags & re.IGNORECASE)
            )
            self._apply_preset_search_result(
                tuple(source[index] for index in indices), selected_name
            )
            return
        builder = RegexBuilder(query[:4096], flags=flags, regex_enabled=True)
        self._preset_search_controller.submit(
            builder.request(names),
            lambda result, presets=source, selected=selected_name: self._finish_preset_search(
                presets, selected, result
            ),
            immediate=immediate,
        )

    def _finish_preset_search(
        self,
        source: Tuple[appearance_presets.AppearancePreset, ...],
        selected_name: str,
        result: RegexResult,
    ) -> None:
        if result.timed_out:
            self._show_appearance_message(
                settings_search.localized_copy("timeout", self._prefs.language_mode),
                error=True,
            )
            self._apply_preset_search_result((), selected_name)
            return
        if not result.valid:
            self._show_appearance_message(
                settings_search.localized_copy(
                    "invalid", self._prefs.language_mode, error=result.error or ""
                ),
                error=True,
            )
            self._apply_preset_search_result((), selected_name)
            return
        self._apply_preset_search_result(
            tuple(source[index] for index in result.matched_indices), selected_name
        )

    def _apply_preset_search_result(
        self,
        presets: Tuple[appearance_presets.AppearancePreset, ...],
        selected_name: str = "",
    ) -> None:
        self._appearance_presets = list(presets)
        labels = [preset.name for preset in self._appearance_presets]
        self.appearance_preset_list.Set(labels)
        if selected_name:
            selected = next(
                (
                    index
                    for index, label in enumerate(labels)
                    if label.casefold() == selected_name.casefold()
                ),
                wx.NOT_FOUND,
            )
            self.appearance_preset_list.SetSelection(selected)

    def _selected_appearance_preset(
        self,
    ) -> Optional[appearance_presets.AppearancePreset]:
        selected = self.appearance_preset_list.GetSelection()
        if 0 <= selected < len(self._appearance_presets):
            return self._appearance_presets[selected]
        return None

    def _select_appearance_preset(self, _event: wx.Event) -> None:
        preset = self._selected_appearance_preset()
        if preset is not None:
            self.appearance_preset_name.SetValue(preset.name)

    def _load_appearance_preset(self, _event: wx.Event) -> None:
        preset = self._selected_appearance_preset()
        if preset is None:
            self._show_appearance_message("Select a preset to load.", error=True)
            return
        self._set_appearance_form(preset.values)
        self.appearance_preset_name.SetValue(preset.name)
        self._show_appearance_message(
            f'Loaded "{preset.name}" into this dialog. Choose OK to apply it.'
        )

    def _save_appearance_preset(self, _event: wx.Event) -> None:
        try:
            values = self._appearance_values_from_form()
            name = self.appearance_preset_name.GetValue().strip()
            preset = appearance_presets.save_preset(name, values, replace=False)
            self._refresh_appearance_presets(preset.name)
        except (appearance_presets.AppearancePresetValidationError, OSError) as exc:
            self._show_appearance_message(f"Preset was not saved: {exc}", error=True)
            return
        self._show_appearance_message(f'Saved appearance preset "{preset.name}".')

    def _update_appearance_preset(self, _event: wx.Event) -> None:
        selected = self._selected_appearance_preset()
        if selected is None:
            self._show_appearance_message("Select a preset to update.", error=True)
            return
        try:
            values = self._appearance_values_from_form()
            preset = appearance_presets.save_preset(selected.name, values, replace=True)
            self._refresh_appearance_presets(preset.name)
        except (appearance_presets.AppearancePresetValidationError, OSError) as exc:
            self._show_appearance_message(f"Preset was not updated: {exc}", error=True)
            return
        self.appearance_preset_name.SetValue(preset.name)
        self._show_appearance_message(f'Updated appearance preset "{preset.name}".')

    def _delete_appearance_preset(self, _event: wx.Event) -> None:
        selected = self._selected_appearance_preset()
        if selected is None:
            self._show_appearance_message("Select a preset to delete.", error=True)
            return
        try:
            appearance_presets.delete_preset(selected.name)
            self._refresh_appearance_presets()
        except (appearance_presets.AppearancePresetValidationError, OSError) as exc:
            self._show_appearance_message(f"Preset was not deleted: {exc}", error=True)
            return
        self._show_appearance_message(f'Deleted appearance preset "{selected.name}".')

    def _export_appearance_preset(self, _event: wx.Event) -> None:
        preset = self._selected_appearance_preset()
        if preset is None:
            self._show_appearance_message("Select a preset to export.", error=True)
            return
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", preset.name).strip("-.")
        value = choose_path(
            self,
            "Export appearance preset",
            default_path=(safe_name or "appearance-preset") + ".json",
            wildcard="JSON files (*.json)|*.json",
            save=True,
        )
        if not value:
            return
        path = Path(value)
        try:
            path.write_text(
                appearance_presets.export_preset(preset),
                encoding="utf-8",
                newline="\n",
            )
        except OSError as exc:
            self._show_appearance_message(f"Preset was not exported: {exc}", error=True)
            return
        self._last_appearance_export = path
        self.appearance_preset_open.Enable(True)
        self._show_appearance_message(f'Exported "{preset.name}" to {path}.')

    def _open_appearance_export(self, _event: wx.Event) -> None:
        target = getattr(self, "_last_appearance_export", None)
        if target is None:
            return
        action = export_actions.open_exported_path(target)
        self._show_appearance_message(action.message, error=not action.ok)

    def _import_appearance_preset(self, _event: wx.Event) -> None:
        value = choose_path(
            self,
            "Import appearance preset",
            wildcard="JSON files (*.json)|*.json",
        )
        if not value:
            return
        path = Path(value)
        try:
            with path.open("rb") as stream:
                payload = stream.read(appearance_presets.MAX_IMPORT_BYTES + 1)
            preset = appearance_presets.import_preset(payload)
            self._refresh_appearance_presets(preset.name)
        except (appearance_presets.AppearancePresetValidationError, OSError) as exc:
            self._show_appearance_message(f"Preset was not imported: {exc}", error=True)
            return
        self._show_appearance_message(f'Imported appearance preset "{preset.name}".')

    def _reset_appearance_property(self, _event: wx.Event) -> None:
        property_name = appearance_presets.APPEARANCE_FIELDS[
            self.appearance_reset_property.GetSelection()
        ]
        defaults = appearance_presets.SHIPPED_APPEARANCE
        if property_name == "theme":
            self.theme.SetSelection(preferences.THEMES.index(defaults.theme))
        elif property_name == "density":
            self.density.SetSelection(preferences.DENSITIES.index(defaults.density))
        elif property_name == "accent":
            self.accent.SetValue(defaults.accent)
        elif property_name == "ui_font":
            self._set_appearance_font(defaults.ui_font)
        else:
            self.scale.SetValue(round(defaults.ui_scale * 100))
        self._show_appearance_message(
            "Reset the selected value in this dialog. Choose OK to apply it."
        )

    def _reset_appearance_form(self, _event: wx.Event) -> None:
        self._set_appearance_form(appearance_presets.SHIPPED_APPEARANCE)
        self._show_appearance_message(
            "Reset all appearance values in this dialog. Choose OK to apply them."
        )

    def _schedule_text(self, key: str, **values: object) -> str:
        text = lang.get(f"preferences.schedule.{key}")
        try:
            return text.format(**values)
        except (KeyError, ValueError):
            return text

    def _build_schedule_tab(self) -> None:
        mode = self._prefs.language_mode
        page = wx.ScrolledWindow(self._tabs, style=wx.VSCROLL)
        page.SetScrollRate(0, 12)
        root = wx.BoxSizer(wx.VERTICAL)

        explanation = wx.StaticText(page, label=self._schedule_text("explanation"))
        _track_responsive_text(page, explanation)
        root.Add(explanation, 0, wx.EXPAND | wx.BOTTOM, 10)

        self.schedule_list = wx.ListBox(page)
        self.schedule_list.SetMinSize(wx.Size(-1, 88))
        root.Add(self.schedule_list, 0, wx.EXPAND | wx.BOTTOM, 8)
        actions = wx.BoxSizer(wx.VERTICAL)
        self.schedule_new = wx.Button(page, label=self._schedule_text("add"))
        self.schedule_remove = wx.Button(page, label=self._schedule_text("remove"))
        self.schedule_up = wx.Button(page, label=self._schedule_text("moveup"))
        self.schedule_down = wx.Button(page, label=self._schedule_text("movedown"))
        actions.Add(self.schedule_new, 0, wx.RIGHT, 8)
        actions.Add(self.schedule_remove, 0, wx.RIGHT, 8)
        actions.Add(self.schedule_up, 0, wx.RIGHT, 8)
        actions.Add(self.schedule_down, 0)
        root.Add(actions, 0, wx.BOTTOM, 12)

        grid = wx.FlexGridSizer(0, 1, 5, 0)
        grid.AddGrowableCol(0, 1)

        def add_row(key: str, control: wx.Window) -> None:
            grid.Add(
                _label(
                    page,
                    self._schedule_text(key),
                    self._schedule_text(f"{key}.help"),
                ),
                0,
                wx.ALIGN_CENTER_VERTICAL,
            )
            grid.Add(control, 1, wx.EXPAND)

        self.schedule_enabled = wx.CheckBox(
            page, label=self._schedule_text("enabled.value")
        )
        add_row("enabled", self.schedule_enabled)
        self.schedule_label = wx.TextCtrl(page)
        add_row("label", self.schedule_label)
        self.schedule_priority = wx.SpinCtrl(page, min=-10000, max=10000, initial=0)
        add_row("priority", self.schedule_priority)

        self.schedule_source_kind = wx.Choice(
            page,
            choices=[
                self._schedule_text("source.local"),
                self._schedule_text("source.api"),
                self._schedule_text("source.homeassistant"),
            ],
        )
        self.schedule_source_kind.SetName("Scheduled source kind")
        add_row("source", self.schedule_source_kind)
        self.schedule_source_url = wx.TextCtrl(page)
        self.schedule_source_url.SetHint(self._schedule_text("source.url.hint"))
        self.schedule_source_url.SetName("Scheduled source URL")
        add_row("sourceurl", self.schedule_source_url)
        self.schedule_source_entity = wx.TextCtrl(page)
        self.schedule_source_entity.SetHint(self._schedule_text("source.entity.hint"))
        self.schedule_source_entity.SetName("Home Assistant entity")
        add_row("sourceentity", self.schedule_source_entity)
        self.schedule_source_refresh = wx.SpinCtrl(page, min=30, max=86400, initial=300)
        self.schedule_source_refresh.SetName("Scheduled source refresh seconds")
        add_row("sourcerefresh", self.schedule_source_refresh)

        weekday_panel = wx.Panel(page)
        weekday_sizer = wx.BoxSizer(wx.VERTICAL)
        self.schedule_every_day = wx.CheckBox(
            weekday_panel, label=self._schedule_text("everyday")
        )
        weekday_sizer.Add(self.schedule_every_day, 0, wx.RIGHT | wx.BOTTOM, 10)
        self.schedule_weekdays = []
        for name in (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ):
            checkbox = wx.CheckBox(
                weekday_panel, label=self._schedule_text(f"weekday.{name}")
            )
            self.schedule_weekdays.append(checkbox)
            weekday_sizer.Add(checkbox, 0, wx.RIGHT | wx.BOTTOM, 6)
        weekday_panel.SetSizer(weekday_sizer)
        add_row("weekdays", weekday_panel)

        self.schedule_start_date = MaterialDateTimeField(page, "date")
        add_row("startdate", self.schedule_start_date)
        self.schedule_end_date = MaterialDateTimeField(page, "date")
        add_row("enddate", self.schedule_end_date)
        self.schedule_start_time = MaterialDateTimeField(page, "time")
        add_row("starttime", self.schedule_start_time)
        self.schedule_end_time = MaterialDateTimeField(page, "time")
        add_row("endtime", self.schedule_end_time)
        for field, setting_key in (
            (self.schedule_start_date, "schedule-start-date"),
            (self.schedule_end_date, "schedule-end-date"),
            (self.schedule_start_time, "schedule-start-time"),
            (self.schedule_end_time, "schedule-end-time"),
        ):
            accessible_name = _setting_copy(setting_key, mode)
            field.SetName(accessible_name)
            field.text.SetName(accessible_name)
            field.picker.SetName(accessible_name)

        no_override = self._schedule_text("nooverride")
        self.schedule_language = wx.Choice(
            page,
            choices=[
                no_override,
                self._schedule_text("language.english"),
                self._schedule_text("language.cantonese"),
                self._schedule_text("language.bilingual"),
            ],
        )
        add_row("language", self.schedule_language)
        self.schedule_theme = wx.Choice(
            page,
            choices=[
                no_override,
                self._schedule_text("theme.light"),
                self._schedule_text("theme.dark"),
                self._schedule_text("theme.system"),
            ],
        )
        add_row("theme", self.schedule_theme)
        self.schedule_density = wx.Choice(
            page,
            choices=[
                no_override,
                self._schedule_text("density.compact"),
                self._schedule_text("density.comfortable"),
                self._schedule_text("density.spacious"),
            ],
        )
        add_row("density", self.schedule_density)
        self.schedule_accent = wx.TextCtrl(page)
        self.schedule_accent.SetHint(self._schedule_text("accent.hint"))
        add_row("accent", self.schedule_accent)
        root.Add(grid, 0, wx.EXPAND | wx.BOTTOM, 10)

        self.schedule_apply = wx.Button(page, label=self._schedule_text("apply"))
        root.Add(self.schedule_apply, 0, wx.BOTTOM, 8)
        self.schedule_validation = wx.StaticText(page, label="")
        _track_responsive_text(page, self.schedule_validation)
        root.Add(self.schedule_validation, 0, wx.EXPAND)

        self._schedule_controls = [
            self.schedule_list,
            self.schedule_new,
            self.schedule_remove,
            self.schedule_up,
            self.schedule_down,
            self.schedule_enabled,
            self.schedule_label,
            self.schedule_priority,
            self.schedule_source_kind,
            self.schedule_source_url,
            self.schedule_source_entity,
            self.schedule_source_refresh,
            self.schedule_every_day,
            *self.schedule_weekdays,
            self.schedule_start_date,
            self.schedule_end_date,
            self.schedule_start_time,
            self.schedule_end_time,
            self.schedule_language,
            self.schedule_theme,
            self.schedule_density,
            self.schedule_accent,
            self.schedule_apply,
        ]
        self._schedule_loading = False
        self._schedule_form_dirty = False
        self._schedule_selection = wx.NOT_FOUND
        self.schedule_list.Bind(wx.EVT_LISTBOX, self._select_schedule_rule)
        self.schedule_new.Bind(wx.EVT_BUTTON, self._new_schedule_rule)
        self.schedule_remove.Bind(wx.EVT_BUTTON, self._remove_schedule_rule)
        self.schedule_up.Bind(wx.EVT_BUTTON, lambda event: self._move_schedule_rule(-1))
        self.schedule_down.Bind(
            wx.EVT_BUTTON, lambda event: self._move_schedule_rule(1)
        )
        self.schedule_apply.Bind(wx.EVT_BUTTON, self._apply_schedule_rule)
        self.schedule_source_kind.Bind(wx.EVT_CHOICE, self._source_kind_changed)
        for control in (
            self.schedule_label,
            self.schedule_start_date,
            self.schedule_end_date,
            self.schedule_start_time,
            self.schedule_end_time,
            self.schedule_accent,
        ):
            control.Bind(wx.EVT_TEXT, self._mark_schedule_dirty)
        self.schedule_priority.Bind(wx.EVT_SPINCTRL, self._mark_schedule_dirty)
        self.schedule_priority.Bind(wx.EVT_TEXT, self._mark_schedule_dirty)
        self.schedule_every_day.Bind(wx.EVT_CHECKBOX, self._toggle_every_day)
        for control in (
            self.schedule_enabled,
            self.schedule_every_day,
            *self.schedule_weekdays,
        ):
            control.Bind(wx.EVT_CHECKBOX, self._mark_schedule_dirty)
        for control in (
            self.schedule_language,
            self.schedule_theme,
            self.schedule_density,
        ):
            control.Bind(wx.EVT_CHOICE, self._mark_schedule_dirty)
        for control in (self.schedule_source_url, self.schedule_source_entity):
            control.Bind(wx.EVT_TEXT, self._mark_schedule_dirty)
        self.schedule_source_refresh.Bind(wx.EVT_SPINCTRL, self._mark_schedule_dirty)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(root, 1, wx.EXPAND | wx.ALL, 18)
        page.SetSizer(outer)
        page.FitInside()
        self._schedule_page = page
        self._schedule_tab_index = self._tabs.GetPageCount()
        self._tabs.AddPage(page, self._schedule_text("tab"))
        self._refresh_schedule_list()
        self._load_schedule_form(None)
        if self._schedule_load_error is not None:
            for control in self._schedule_controls:
                control.Enable(False)
            self._show_schedule_message(
                self._schedule_text("loaderror", error=self._schedule_load_error),
                error=True,
            )

    def _mark_schedule_dirty(self, event: wx.Event) -> None:
        if not self._schedule_loading:
            self._schedule_form_dirty = True
        event.Skip()

    def _show_schedule_message(self, message: str, error: bool = False) -> None:
        _set_responsive_label(self.schedule_validation, message)
        self.schedule_validation.SetForegroundColour(
            wx.Colour(180, 40, 40) if error else wx.Colour(40, 120, 70)
        )
        self._update_responsive_layout()

    def _refresh_schedule_list(self) -> None:
        labels = [
            rule.label + ("" if rule.enabled else self._schedule_text("disabledsuffix"))
            for rule in self._schedule_rules
        ]
        self.schedule_list.Set(labels)
        if 0 <= self._schedule_selection < len(labels):
            self.schedule_list.SetSelection(self._schedule_selection)

    def _load_schedule_form(self, rule: Optional[schedules.ScheduleRule]) -> None:
        self._schedule_loading = True
        try:
            self.schedule_enabled.SetValue(True if rule is None else rule.enabled)
            self.schedule_label.SetValue("" if rule is None else rule.label)
            self.schedule_priority.SetValue(0 if rule is None else rule.priority)
            source = {} if rule is None else dict(rule.source or {})
            source_kind = source.get("kind", "local")
            self.schedule_source_kind.SetSelection(
                {"local": 0, "api": 1, "home_assistant": 2}.get(source_kind, 0)
            )
            self.schedule_source_url.SetValue(str(source.get("url", "")))
            self.schedule_source_entity.SetValue(str(source.get("entity_id", "")))
            self.schedule_source_refresh.SetValue(
                int(source.get("refresh_seconds", 300))
            )
            self._update_schedule_source_controls()
            active_weekdays = schedules.ALL_WEEKDAYS if rule is None else rule.weekdays
            every_day = active_weekdays == schedules.ALL_WEEKDAYS
            self.schedule_every_day.SetValue(every_day)
            for weekday, checkbox in enumerate(self.schedule_weekdays):
                checkbox.SetValue(weekday in active_weekdays)
                checkbox.Enable(not every_day)
            self.schedule_start_date.SetValue(
                "" if rule is None or rule.start_date is None else rule.start_date
            )
            self.schedule_end_date.SetValue(
                "" if rule is None or rule.end_date is None else rule.end_date
            )
            self.schedule_start_time.SetValue(
                "00:00" if rule is None else rule.start_time
            )
            self.schedule_end_time.SetValue("00:00" if rule is None else rule.end_time)
            values = None if rule is None else rule.values
            language = None if values is None else values.language_mode
            theme = None if values is None else values.theme
            density = None if values is None else values.density
            self.schedule_language.SetSelection(
                0 if language is None else schedules.LANGUAGE_MODES.index(language) + 1
            )
            self.schedule_theme.SetSelection(
                0 if theme is None else schedules.THEMES.index(theme) + 1
            )
            self.schedule_density.SetSelection(
                0 if density is None else schedules.DENSITIES.index(density) + 1
            )
            self.schedule_accent.SetValue(
                "" if values is None or values.accent is None else values.accent
            )
        finally:
            self._schedule_loading = False
            self._schedule_form_dirty = False

    def _select_schedule_rule(self, event: wx.CommandEvent) -> None:
        selected = event.GetSelection()
        if self._schedule_form_dirty and selected != self._schedule_selection:
            self.schedule_list.SetSelection(self._schedule_selection)
            self._show_schedule_message(self._schedule_text("unapplied"), error=True)
            return
        self._schedule_selection = selected
        self._load_schedule_form(self._schedule_rules[selected])
        self._show_schedule_message(self._schedule_text("loaded"))

    def _new_schedule_rule(self, _event: wx.Event) -> None:
        if self._schedule_form_dirty:
            self._show_schedule_message(self._schedule_text("unapplied"), error=True)
            return
        self._schedule_selection = wx.NOT_FOUND
        self.schedule_list.SetSelection(wx.NOT_FOUND)
        self._load_schedule_form(None)
        self._show_schedule_message(self._schedule_text("newready"))

    def _rule_from_schedule_form(self) -> schedules.ScheduleRule:
        current = (
            self._schedule_rules[self._schedule_selection]
            if 0 <= self._schedule_selection < len(self._schedule_rules)
            else None
        )
        language_selection = self.schedule_language.GetSelection()
        theme_selection = self.schedule_theme.GetSelection()
        density_selection = self.schedule_density.GetSelection()
        values = schedules.ScheduledValues(
            language_mode=(
                None
                if language_selection <= 0
                else schedules.LANGUAGE_MODES[language_selection - 1]
            ),
            theme=(
                None if theme_selection <= 0 else schedules.THEMES[theme_selection - 1]
            ),
            density=(
                None
                if density_selection <= 0
                else schedules.DENSITIES[density_selection - 1]
            ),
            accent=self.schedule_accent.GetValue().strip() or None,
        )
        source_kind = ("local", "api", "home_assistant")[
            self.schedule_source_kind.GetSelection()
        ]
        source = scheduled_sources.ScheduleSource(
            kind=source_kind,
            url=self.schedule_source_url.GetValue().strip(),
            entity_id=self.schedule_source_entity.GetValue().strip(),
            refresh_seconds=self.schedule_source_refresh.GetValue(),
        ).as_dict()
        return schedules.ScheduleRule(
            rule_id=(
                current.rule_id
                if current is not None
                else f"schedule-{uuid.uuid4().hex}"
            ),
            label=self.schedule_label.GetValue().strip(),
            enabled=self.schedule_enabled.GetValue(),
            priority=self.schedule_priority.GetValue(),
            weekdays=tuple(
                schedules.ALL_WEEKDAYS
                if self.schedule_every_day.GetValue()
                else tuple(
                    index
                    for index, checkbox in enumerate(self.schedule_weekdays)
                    if checkbox.GetValue()
                )
            ),
            start_date=self.schedule_start_date.GetValue().strip() or None,
            end_date=self.schedule_end_date.GetValue().strip() or None,
            start_time=self.schedule_start_time.GetValue().strip(),
            end_time=self.schedule_end_time.GetValue().strip(),
            source=source,
            values=values,
        )

    def _source_kind_changed(self, _event: wx.Event) -> None:
        if self.schedule_source_kind.GetSelection() == 0:
            self.schedule_source_url.ChangeValue("")
            self.schedule_source_entity.ChangeValue("")
        self._update_schedule_source_controls()
        self._mark_schedule_dirty(_event)

    def _update_schedule_source_controls(self) -> None:
        selected = self.schedule_source_kind.GetSelection()
        is_local = selected == 0
        is_home_assistant = selected == 2
        self.schedule_source_url.Enable(not is_local)
        self.schedule_source_entity.Enable(is_home_assistant)
        self.schedule_source_refresh.Enable(not is_local)

    def _apply_schedule_rule(self, _event: Optional[wx.Event] = None) -> bool:
        try:
            rule = self._rule_from_schedule_form()
        except schedules.ScheduleValidationError as exc:
            self._show_schedule_message(
                self._schedule_text("validationerror", error=exc), error=True
            )
            return False
        if 0 <= self._schedule_selection < len(self._schedule_rules):
            self._schedule_rules[self._schedule_selection] = rule
        else:
            self._schedule_rules.append(rule)
            self._schedule_selection = len(self._schedule_rules) - 1
        self._schedule_form_dirty = False
        self._refresh_schedule_list()
        self._show_schedule_message(self._schedule_text("applied"))
        return True

    def _remove_schedule_rule(self, _event: wx.Event) -> None:
        if self._schedule_form_dirty:
            self._show_schedule_message(self._schedule_text("unapplied"), error=True)
            return
        if not 0 <= self._schedule_selection < len(self._schedule_rules):
            self._show_schedule_message(self._schedule_text("selectremove"), error=True)
            return
        del self._schedule_rules[self._schedule_selection]
        self._schedule_selection = wx.NOT_FOUND
        self._load_schedule_form(None)
        self._refresh_schedule_list()
        self._show_schedule_message(self._schedule_text("removed"))

    def _toggle_every_day(self, event: wx.Event) -> None:
        every_day = self.schedule_every_day.GetValue()
        for checkbox in self.schedule_weekdays:
            if every_day:
                checkbox.SetValue(True)
            checkbox.Enable(not every_day)
        event.Skip()

    def _move_schedule_rule(self, offset: int) -> None:
        if self._schedule_form_dirty:
            self._show_schedule_message(self._schedule_text("unapplied"), error=True)
            return
        target = self._schedule_selection + offset
        if not (
            0 <= self._schedule_selection < len(self._schedule_rules)
            and 0 <= target < len(self._schedule_rules)
        ):
            self._show_schedule_message(self._schedule_text("selectmove"), error=True)
            return
        self._schedule_rules[self._schedule_selection], self._schedule_rules[target] = (
            self._schedule_rules[target],
            self._schedule_rules[self._schedule_selection],
        )
        self._schedule_selection = target
        self._refresh_schedule_list()
        self._show_schedule_message(self._schedule_text("moved"))

    def _build_search_tab(self) -> None:
        mode = self._prefs.language_mode
        page = wx.ScrolledWindow(self._tabs, style=wx.VSCROLL)
        page.SetScrollRate(0, 12)
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(
            _label(
                page,
                settings_search.localized_copy("section.label", mode),
                settings_search.localized_copy("section.description", mode),
            ),
            0,
            wx.BOTTOM,
            8,
        )
        row = wx.BoxSizer(wx.VERTICAL)
        self.regex = wx.TextCtrl(page)
        self.regex.SetName(settings_search.localized_copy("section.label", mode))
        self.regex.SetHint(settings_search.localized_copy("hint", mode))
        self.regex_mode = wx.CheckBox(
            page,
            label=settings_search.localized_copy(
                "regex", mode, bilingual_separator="\n"
            ),
        )
        self.regex_mode.SetName(settings_search.localized_copy("regex", mode))
        self.regex_flags = wx.CheckBox(
            page,
            label=settings_search.localized_copy(
                "ignorecase", mode, bilingual_separator="\n"
            ),
        )
        self.regex_flags.SetName(settings_search.localized_copy("ignorecase", mode))
        self.regex_flags.SetValue(True)
        self.regex_button = wx.Button(
            page,
            label=settings_search.localized_copy(
                "builder", mode, bilingual_separator="\n"
            ),
        )
        self.regex_button.SetName(settings_search.localized_copy("builder", mode))
        self.regex_button.SetToolTip(
            settings_search.localized_copy("builder.help", mode)
        )
        row.Add(self.regex, 1, wx.EXPAND | wx.RIGHT, 8)
        row.Add(self.regex_mode, 0, wx.RIGHT, 8)
        row.Add(self.regex_flags, 0, wx.RIGHT, 8)
        row.Add(self.regex_button, 0)
        box.Add(row, 0, wx.EXPAND)
        self.regex_result = wx.StaticText(
            page,
            label=settings_search.localized_copy("empty", mode),
        )
        self.regex_result.SetName(settings_search.localized_copy("empty", mode))
        _track_responsive_text(page, self.regex_result)
        box.Add(self.regex_result, 0, wx.TOP, 10)
        self.regex_results = WrappedSearchResults(
            page,
            self._activate_settings_search,
            settings_search.localized_copy("open", mode),
        )
        self.regex_results.SetName(settings_search.localized_copy("results", mode))
        self.regex_results.SetMinSize(wx.Size(1, 180))
        box.Add(self.regex_results, 1, wx.EXPAND | wx.TOP, 10)
        self.regex_open = wx.Button(
            page,
            label=settings_search.localized_copy(
                "open", mode, bilingual_separator="\n"
            ),
        )
        self.regex_open.SetName(settings_search.localized_copy("open", mode))
        box.Add(self.regex_open, 0, wx.TOP | wx.ALIGN_LEFT, 10)

        self._settings_search_controls = {
            spec.key: getattr(self, spec.control_name)
            for spec in settings_search.PREFERENCES_SETTING_SPECS
        }
        self._settings_search_pages = {
            "language": self._language_page,
            "appearance": self._appearance_page,
            "schedule": self._schedule_page,
        }
        self._settings_search_matches: Tuple[
            settings_search.SettingSearchDocument, ...
        ] = ()
        self._settings_search_fragments: Tuple[str, ...] = ()
        self.regex.Bind(wx.EVT_TEXT, self._validate_regex)
        self.regex_mode.Bind(wx.EVT_CHECKBOX, self._validate_regex)
        self.regex_flags.Bind(wx.EVT_CHECKBOX, self._validate_regex)
        self.regex_button.Bind(wx.EVT_BUTTON, self._open_search_regex_builder)
        self.regex_results.Bind(wx.EVT_KEY_DOWN, self._on_settings_result_key)
        self.regex_open.Bind(wx.EVT_BUTTON, self._activate_settings_search)
        self._bind_settings_search_sources()
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(box, 1, wx.EXPAND | wx.ALL, 18)
        page.SetSizer(outer)
        page.FitInside()
        self._search_page = page
        self._tabs.AddPage(page, settings_search.localized_copy("tab", mode))

    def _open_search_regex_builder(self, _event: wx.Event) -> None:
        with RegexBuilderDialog(
            self,
            pattern=self.regex.GetValue(),
            regex_enabled=self.regex_mode.GetValue(),
            flags=self._effective_settings_search_flags(),
            sample=_chrome_copy("sample.settings", self._prefs.language_mode),
            language_mode=self._prefs.language_mode,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.regex.ChangeValue(dialog.pattern)
            self.regex_mode.SetValue(dialog.regex_enabled)
            self._settings_search_flags = dialog.flags
            self.regex_flags.SetValue(bool(dialog.flags & re.IGNORECASE))
        self._refresh_settings_search(immediate=True)

    def _effective_settings_search_flags(self) -> int:
        flags = self._settings_search_flags & ~re.IGNORECASE
        if self.regex_flags.GetValue():
            flags |= re.IGNORECASE
        self._settings_search_flags = flags
        return flags

    def _settings_search_value(self, spec: settings_search.SettingSearchSpec) -> str:
        if spec.sensitive:
            return ""
        if spec.key == "schedule-weekdays":
            if self.schedule_every_day.GetValue():
                return settings_search.localized_copy(
                    "everyday", self._prefs.language_mode
                )
            weekdays = [
                control.GetLabel()
                for control in self.schedule_weekdays
                if control.GetValue()
            ]
            return ", ".join(weekdays)
        control = self._settings_search_controls[spec.key]
        if isinstance(control, (wx.Choice, wx.ListBox)):
            value = control.GetStringSelection()
        elif isinstance(control, wx.FontPickerCtrl):
            value = control.GetSelectedFont().GetFaceName()
        elif hasattr(control, "GetValue"):
            value = control.GetValue()
        else:
            value = ""
        if isinstance(value, bool):
            return settings_search.localized_copy(
                "on" if value else "off", self._prefs.language_mode
            )
        if spec.key == "ui-scale" and value != "":
            return f"{value}%"
        return str(value).strip()[:160]

    def _settings_search_documents(
        self,
    ) -> Tuple[settings_search.SettingSearchDocument, ...]:
        documents = []
        for spec in settings_search.PREFERENCES_SETTING_SPECS:
            page = self._settings_search_pages[spec.tab_id]
            if self._tabs.FindPage(page) == wx.NOT_FOUND:
                continue
            documents.append(
                settings_search.SettingSearchDocument(
                    spec,
                    current_value=self._settings_search_value(spec),
                    language_mode=self._prefs.language_mode,
                )
            )
        return tuple(documents)

    def _refresh_settings_search(self, *, immediate: bool = False) -> None:
        query = self.regex.GetValue()[:4096]
        if not query:
            self._settings_search_controller.cancel()
            self._settings_search_matches = ()
            self._settings_search_fragments = ()
            self.regex_results.Set([])
            self._set_settings_search_status("empty", "on_surface_variant")
            self._update_responsive_layout()
            return
        flags = self._effective_settings_search_flags()
        documents = self._settings_search_documents()
        values = tuple(document.searchable_text[:4096] for document in documents)
        if not self.regex_mode.GetValue():
            self._settings_search_controller.cancel()
            try:
                indices = plain_text_match_indices(
                    values,
                    query,
                    ignore_case=bool(flags & re.IGNORECASE),
                )
            except ValueError as exc:
                self._apply_settings_search_result(
                    documents, RegexResult(False, str(exc))
                )
                return
            result = RegexResult(
                True,
                matched_indices=indices,
                first_matches=tuple(query for _index in indices),
            )
            self._apply_settings_search_result(documents, result)
            return

        self._set_settings_search_status("searching", "on_surface_variant")
        self._settings_search_controller.submit(
            RegexBuilder(query, flags, True).request(values),
            lambda result, source=documents: self._apply_settings_search_result(
                source, result
            ),
            immediate=immediate,
        )

    def _apply_settings_search_result(
        self,
        documents: Tuple[settings_search.SettingSearchDocument, ...],
        result: RegexResult,
    ) -> None:
        if result.timed_out:
            self._settings_search_matches = ()
            self._settings_search_fragments = ()
            self.regex_results.Set([])
            self._set_settings_search_status("timeout", "error")
            self._update_responsive_layout()
            return
        if not result.valid:
            self._settings_search_matches = ()
            self._settings_search_fragments = ()
            self.regex_results.Set([])
            self._set_settings_search_status(
                "invalid", "error", error=result.error or ""
            )
            self._update_responsive_layout()
            return
        self._settings_search_matches = settings_search.documents_from_result(
            documents, result
        )
        self._settings_search_fragments = result.first_matches
        self.regex_results.Set(
            [document.result_label for document in self._settings_search_matches]
        )
        if self._settings_search_matches:
            self.regex_results.SetSelection(0)
        count = len(self._settings_search_matches)
        self._set_settings_search_status("count", "primary", count=count)
        self._update_responsive_layout()

    def _set_settings_search_status(
        self, key: str, role: str, **values: object
    ) -> None:
        _set_responsive_label(
            self.regex_result,
            settings_search.localized_copy(key, self._prefs.language_mode, **values),
        )
        self.regex_result.SetForegroundColour(active_material_palette()[role])

    def _activate_settings_search(self, _event: wx.Event | None = None) -> None:
        index = self.regex_results.GetSelection()
        if index == wx.NOT_FOUND or index >= len(self._settings_search_matches):
            self._set_settings_search_status("select", "error")
            self._update_responsive_layout()
            return
        document = self._settings_search_matches[index]
        fragment = (
            self._settings_search_fragments[index]
            if index < len(self._settings_search_fragments)
            else ""
        )
        control = self._settings_search_focus_control(document, fragment)
        page = self._settings_search_pages[document.spec.tab_id]
        page_index = self._tabs.FindPage(page)
        if page_index == wx.NOT_FOUND:
            self._set_settings_search_status("unavailable", "error")
            self._update_responsive_layout()
            return
        self._tabs.SetSelection(page_index)
        self._update_responsive_layout()
        if isinstance(page, wx.ScrolledWindow) and hasattr(page, "ScrollChildIntoView"):
            page.ScrollChildIntoView(control)
        wx.CallAfter(control.SetFocus)
        localized = document.localized_spec
        self._set_settings_search_status(
            "opened",
            "primary",
            label=localized.label,
            tab=localized.tab,
        )
        self._update_responsive_layout()

    def _settings_search_focus_control(
        self,
        document: settings_search.SettingSearchDocument,
        matched_fragment: str,
    ) -> wx.Window:
        control = self._settings_search_controls[document.spec.key]
        if isinstance(control, MaterialDateTimeField):
            return control.text if control.text.IsEnabled() else control.picker
        if document.spec.key == "schedule-weekdays":
            fragment = matched_fragment.casefold()
            for weekday in self.schedule_weekdays:
                label = weekday.GetLabel().casefold()
                if fragment and (fragment in label or label in fragment):
                    return weekday
        return control

    def _bind_settings_search_sources(self) -> None:
        controls = list(self._settings_search_controls.values())
        controls.extend(self.schedule_weekdays)
        for control in controls:
            if isinstance(control, MaterialDateTimeField):
                # MaterialDateTimeField emits EVT_TEXT after its picker and
                # typed values are synchronized; consuming the native picker
                # event directly can observe the previous value.
                control.Bind(wx.EVT_TEXT, self._settings_search_source_changed)
            elif isinstance(control, wx.TextCtrl):
                control.Bind(wx.EVT_TEXT, self._settings_search_source_changed)
            elif isinstance(control, wx.Choice):
                control.Bind(wx.EVT_CHOICE, self._settings_search_source_changed)
            elif isinstance(control, wx.ListBox):
                control.Bind(wx.EVT_LISTBOX, self._settings_search_source_changed)
            elif isinstance(control, wx.CheckBox):
                control.Bind(wx.EVT_CHECKBOX, self._settings_search_source_changed)
            elif isinstance(control, wx.Slider):
                control.Bind(wx.EVT_SLIDER, self._settings_search_source_changed)
            elif isinstance(control, wx.SpinCtrl):
                control.Bind(wx.EVT_SPINCTRL, self._settings_search_source_changed)
                control.Bind(wx.EVT_TEXT, self._settings_search_source_changed)
            elif isinstance(control, wx.FontPickerCtrl):
                control.Bind(
                    wx.EVT_FONTPICKER_CHANGED,
                    self._settings_search_source_changed,
                )

    def _settings_search_source_changed(self, event: wx.Event) -> None:
        if self.regex.GetValue():
            self._refresh_settings_search()
        event.Skip()

    def _on_settings_result_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() in (
            wx.WXK_RETURN,
            getattr(wx, "WXK_NUMPAD_ENTER", -1),
        ):
            self._activate_settings_search()
            return
        event.Skip()

    def _validate_regex(self, _event: wx.Event) -> None:
        self._refresh_settings_search()

    def _reset(self, _event: wx.Event) -> None:
        self._prefs = preferences.reset()
        self.EndModal(wx.ID_CANCEL)

    def _save(self, _event: wx.Event) -> None:
        if self._schedule_load_error is None:
            if self._schedule_form_dirty and not self._apply_schedule_rule():
                self._tabs.SetSelection(self._schedule_tab_index)
                return
            try:
                schedules.replace_rules(self._schedule_rules)
            except (schedules.ScheduleValidationError, OSError) as exc:
                self._show_schedule_message(
                    self._schedule_text("saveerror", error=exc), error=True
                )
                self._tabs.SetSelection(self._schedule_tab_index)
                return
        language_mode = preferences.LANGUAGE_MODES[self.language.GetSelection()]
        try:
            school_mode.set_mode_name(self.school_name.GetValue())
            credential = self.school_credential.GetValue()
            current_school = school_mode.load()
            if credential:
                school_mode.set_unlock_credential(credential)
            if self.school_enabled.GetValue() and not current_school.enabled:
                school_mode.enable()
            elif not self.school_enabled.GetValue() and current_school.enabled:
                if not credential or not school_mode.unlock(credential):
                    raise ValueError(
                        "Enter the current unlock credential to leave School mode."
                    )
        except ValueError as exc:
            notify(self, "Preferences not saved", str(exc), severity="warning")
            return
        try:
            display_name = preferences.validate_display_name(
                self.display_name.GetValue()
            )
        except ValueError as exc:
            _set_responsive_label(self.identity_status, str(exc))
            self.identity_status.SetForegroundColour(wx.Colour(180, 40, 40))
            self._tabs.SetSelection(self._appearance_tab_index)
            self.display_name.SetFocus()
            return
        try:
            appearance = self._appearance_values_from_form()
        except appearance_presets.AppearancePresetValidationError as exc:
            self._show_appearance_message(
                f"Appearance settings were not saved: {exc}", error=True
            )
            self._tabs.SetSelection(self._appearance_tab_index)
            return
        editor_value = self.external_editor_path.GetValue().strip()
        if editor_value:
            editor_result = external_editor.select_editor(editor_value)
            if not editor_result.ok:
                _set_responsive_label(
                    self.external_editor_status, editor_result.message
                )
                self.external_editor_status.SetForegroundColour(wx.Colour(180, 40, 40))
                self._tabs.SetSelection(self._appearance_tab_index)
                self.external_editor_path.SetFocus()
                return
            editor_value = external_editor.load_selected()
        else:
            external_editor.clear_selected()
        saved_preferences = preferences.save(
            preferences.Preferences(
                display_name=display_name,
                language_mode=language_mode,
                funny_level_english=self.funny_en.GetValue(),
                funny_level_cantonese=self.funny_yue.GetValue(),
                show_dialog_emojis=self.dialog_emojis.GetValue(),
                theme=appearance.theme,
                density=appearance.density,
                accent=appearance.accent,
                ui_font=appearance.ui_font,
                ui_scale=appearance.ui_scale,
                external_editor_path=self.external_editor_path.GetValue().strip(),
            )
        )
        # Settings are user-managed records too. History failure remains
        # non-blocking, but the snapshot belongs to the save path—not a viewer.
        local_history.safe_record(
            "preferences",
            asdict(saved_preferences),
            record_type="settings",
        )
        # Apply the persisted language and appearance choices immediately to
        # the owning frame; reopening the app is not required.
        lang.set_language(
            {
                "english": "en",
                "cantonese": "zh_TW",
                "bilingual": "en",
            }[language_mode]
        )
        apply_material3(self.GetParent())
        parent = self.GetParent()
        if hasattr(parent, "refresh_display_identity"):
            parent.refresh_display_identity(saved_preferences.display_name)
        self.EndModal(wx.ID_OK)


class CommandPaletteDialog(wx.Dialog):
    """Keyboard-friendly command palette (Ctrl+Shift+F) with plain/regex search."""

    def __init__(
        self, parent: wx.Window, commands: Iterable[Tuple[str, Callable[[], None]]]
    ):
        self._language_mode = preferences.load().language_mode
        super().__init__(
            parent,
            title=_chrome_copy("command_palette_title", self._language_mode),
            size=wx.Size(560, 420),
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        self._commands: List[Tuple[str, Callable[[], None]]] = list(commands)
        self._search_flags = 0
        root = wx.BoxSizer(wx.VERTICAL)
        self.query = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.query.SetHint(_chrome_copy("command_palette_search", self._language_mode))
        self.regex = wx.CheckBox(self, label=_chrome_copy("regex", self._language_mode))
        self.regex_button = wx.Button(
            self,
            label=_chrome_copy("appearance.regex.button", self._language_mode),
        )
        self.regex_button.SetName("Command palette regex builder")
        self.regex_button.SetToolTip("Build a bounded regular-expression search")
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.query, 1, wx.EXPAND | wx.RIGHT, 8)
        row.Add(self.regex, 0, wx.ALIGN_CENTER_VERTICAL)
        row.Add(self.regex_button, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 6)
        root.Add(row, 0, wx.EXPAND | wx.ALL, 12)
        self.feedback = wx.StaticText(self, label="")
        self.feedback.SetName(
            _chrome_copy("command_palette_search", self._language_mode)
        )
        root.Add(self.feedback, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.results = wx.ListBox(self)
        root.Add(self.results, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.SetSizer(root)
        self._refresh()
        self.query.Bind(wx.EVT_TEXT, lambda evt: self._refresh())
        self.regex.Bind(wx.EVT_CHECKBOX, lambda evt: self._refresh())
        self.regex_button.Bind(wx.EVT_BUTTON, self._open_regex_builder)
        self.query.Bind(wx.EVT_TEXT_ENTER, self._run)
        self.results.Bind(wx.EVT_LISTBOX_DCLICK, self._run)
        self.results.Bind(wx.EVT_KEY_DOWN, self._on_result_key)
        apply_material3(self)

    def _open_regex_builder(self, _event) -> None:
        with RegexBuilderDialog(
            self,
            pattern=self.query.GetValue(),
            regex_enabled=self.regex.GetValue(),
            flags=self._search_flags,
            sample=_chrome_copy("sample.command", self._language_mode),
            language_mode=self._language_mode,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.query.ChangeValue(dialog.pattern)
            self.regex.SetValue(dialog.regex_enabled)
            self._search_flags = dialog.flags
        self._refresh()

    def _refresh(self) -> None:
        query = self.query.GetValue()[:4096]
        try:
            names = [name for name, _ in self._commands]
            if self.regex.GetValue():
                matches = RegexBuilder(
                    query,
                    regex_enabled=True,
                    flags=self._search_flags,
                ).search(names)
            else:
                indices = plain_text_match_indices(
                    names,
                    query,
                    ignore_case=bool(self._search_flags & re.IGNORECASE),
                )
                matches = [names[index] for index in indices]
            self.feedback.SetLabel("")
        except TimeoutError:
            matches = []
            self.feedback.SetLabel(
                _chrome_copy("command_palette_timeout", self._language_mode)
            )
        except (re.error, ValueError):
            matches = []
            self.feedback.SetLabel(
                _chrome_copy("command_palette_invalid", self._language_mode)
            )
        self.results.Set(matches)
        if matches:
            self.results.SetSelection(0)

    def _run(self, _event: wx.Event) -> None:
        label = self.results.GetStringSelection()
        for name, callback in self._commands:
            if name == label:
                self.EndModal(wx.ID_OK)
                callback()
                return

    def _on_result_key(self, event: wx.KeyEvent) -> None:
        """Keep palette result navigation explicit and screen-reader friendly."""
        count = self.results.GetCount()
        if count == 0:
            event.Skip()
            return
        key = event.GetKeyCode()
        current = max(0, self.results.GetSelection())
        if key == wx.WXK_DOWN:
            self.results.SetSelection(min(count - 1, current + 1))
            return
        if key == wx.WXK_UP:
            self.results.SetSelection(max(0, current - 1))
            return
        if key == wx.WXK_HOME:
            self.results.SetSelection(0)
            return
        if key == wx.WXK_END:
            self.results.SetSelection(count - 1)
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._run(event)
            return
        event.Skip()


class ChangelogDialog(wx.Dialog):
    """Offline changelog browser with composable text and date filters."""

    def __init__(self, parent: wx.Window):
        self._language_mode = preferences.load().language_mode
        super().__init__(
            parent,
            title=_chrome_copy("changelog_title", self._language_mode),
            size=wx.Size(700, 520),
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        self._catalog = changelog.load_bundled_catalog()
        root = wx.BoxSizer(wx.VERTICAL)
        filters = wx.FlexGridSizer(0, 2, 8, 10)
        filters.AddGrowableCol(1, 1)
        filters.Add(
            wx.StaticText(
                self,
                label=_chrome_copy("changelog_search_label", self._language_mode),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.query = wx.TextCtrl(self)
        self.query.SetHint(_chrome_copy("changelog_search_hint", self._language_mode))
        filters.Add(self.query, 1, wx.EXPAND)
        filters.Add(
            wx.StaticText(
                self,
                label=_chrome_copy("changelog_start_date", self._language_mode),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.start_date = wx.TextCtrl(self)
        self.start_date.SetHint("YYYY-MM-DD")
        self.start_picker = wx.adv.DatePickerCtrl(
            self, style=wx.adv.DP_DROPDOWN | wx.adv.DP_ALLOWNONE
        )
        self.start_picker.SetValue(wx.DateTime())
        start_row = wx.BoxSizer(wx.HORIZONTAL)
        start_row.Add(self.start_date, 1, wx.EXPAND | wx.RIGHT, 6)
        start_row.Add(self.start_picker, 0, wx.EXPAND)
        filters.Add(start_row, 1, wx.EXPAND)
        filters.Add(
            wx.StaticText(
                self,
                label=_chrome_copy("changelog_end_date", self._language_mode),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.end_date = wx.TextCtrl(self)
        self.end_date.SetHint("YYYY-MM-DD")
        self.end_picker = wx.adv.DatePickerCtrl(
            self, style=wx.adv.DP_DROPDOWN | wx.adv.DP_ALLOWNONE
        )
        self.end_picker.SetValue(wx.DateTime())
        end_row = wx.BoxSizer(wx.HORIZONTAL)
        end_row.Add(self.end_date, 1, wx.EXPAND | wx.RIGHT, 6)
        end_row.Add(self.end_picker, 0, wx.EXPAND)
        filters.Add(end_row, 1, wx.EXPAND)
        self.regex = wx.CheckBox(self, label=_chrome_copy("regex", self._language_mode))
        self.regex_button = wx.Button(
            self,
            label=_chrome_copy("appearance.regex.button", self._language_mode),
        )
        self.regex_button.SetName("Changelog search regex builder")
        self.regex_button.SetToolTip("Build a bounded regular-expression search")
        filters.Add(self.regex, 0, wx.ALIGN_CENTER_VERTICAL)
        filters.Add(self.regex_button, 0, wx.ALIGN_CENTER_VERTICAL)
        self.feedback = wx.StaticText(self, label="")
        self.feedback.Wrap(560)
        filters.Add(self.feedback, 1, wx.EXPAND)
        filters.Add(
            wx.StaticText(
                self, label=_chrome_copy("changelog_action", self._language_mode)
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        action_values = [
            _chrome_copy("changelog_all_actions", self._language_mode),
            *(
                name
                for name, _count in changelog.available_actions(self._catalog.entries)
            ),
        ]
        self.action = wx.Choice(self, choices=action_values)
        self.action.SetSelection(0)
        filters.Add(self.action, 1, wx.EXPAND)
        root.Add(filters, 0, wx.EXPAND | wx.ALL, 12)
        self.results = wx.ListBox(self)
        self.results.SetMinSize(wx.Size(-1, 260))
        root.Add(self.results, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        export = wx.Button(
            self, label=_chrome_copy("changelog_export", self._language_mode)
        )
        export.Bind(wx.EVT_BUTTON, self._export)
        actions.Add(export, 0, wx.RIGHT, 8)
        self.open_export = wx.Button(
            self, label=_chrome_copy("open_export", self._language_mode)
        )
        self.open_export.Enable(False)
        self.open_export.Bind(wx.EVT_BUTTON, self._open_export)
        actions.Add(self.open_export, 0, wx.RIGHT, 8)
        copy = wx.Button(
            self, label=_chrome_copy("changelog_copy", self._language_mode)
        )
        copy.Bind(wx.EVT_BUTTON, self._copy)
        actions.Add(copy, 0, wx.RIGHT, 8)
        close = wx.Button(
            self, id=wx.ID_CLOSE, label=_chrome_copy("close", self._language_mode)
        )
        close.Bind(wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_CANCEL))
        actions.Add(close)
        root.Add(actions, 0, wx.ALIGN_RIGHT | wx.ALL, 12)
        self.SetSizer(root)
        self._search_flags = 0
        for control in (self.query, self.start_date, self.end_date):
            control.Bind(wx.EVT_TEXT, lambda _event: self._refresh())
        self.start_picker.Bind(
            wx.adv.EVT_DATE_CHANGED,
            lambda _event: self._picker_changed(self.start_picker, self.start_date),
        )
        self.end_picker.Bind(
            wx.adv.EVT_DATE_CHANGED,
            lambda _event: self._picker_changed(self.end_picker, self.end_date),
        )
        self.regex.Bind(wx.EVT_CHECKBOX, lambda _event: self._refresh())
        self.regex_button.Bind(wx.EVT_BUTTON, self._open_regex_builder)
        self.action.Bind(wx.EVT_CHOICE, lambda _event: self._refresh())
        self._refresh()
        apply_material3(self)

    def _open_regex_builder(self, _event) -> None:
        with RegexBuilderDialog(
            self,
            pattern=self.query.GetValue(),
            regex_enabled=self.regex.GetValue(),
            flags=self._search_flags,
            sample=_chrome_copy("sample.changelog", self._language_mode),
            language_mode=self._language_mode,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.query.ChangeValue(dialog.pattern)
            self.regex.SetValue(dialog.regex_enabled)
            self._search_flags = dialog.flags
        self._refresh()

    def _parse_date(self, control: wx.TextCtrl) -> Optional[date]:
        value = control.GetValue().strip()
        return date.fromisoformat(value) if value else None

    def _picker_changed(
        self, picker: wx.adv.DatePickerCtrl, field: wx.TextCtrl
    ) -> None:
        value = picker.GetValue()
        field.ChangeValue(
            f"{value.GetYear():04d}-{value.GetMonth() + 1:02d}-{value.GetDay():02d}"
            if value.IsValid()
            else ""
        )
        self._refresh()

    def _filtered(self) -> changelog.ChangelogCatalog:
        query = changelog.ChangelogQuery(
            start_date=self._parse_date(self.start_date),
            end_date=self._parse_date(self.end_date),
            actions=(
                ()
                if self.action.GetSelection() <= 0
                else (self.action.GetStringSelection(),)
            ),
            text=self.query.GetValue()[:4096],
        )
        matcher = None
        if self.regex.GetValue():
            builder = RegexBuilder(
                query.text, regex_enabled=True, flags=self._search_flags
            )
            values = []
            for entry in self._catalog.entries:
                values.append(entry.version)
                for change in entry.changes:
                    values.extend((change.summary, change.commit_sha))
            matched_values = set(builder.search(values))
            matcher = lambda value: value in matched_values
        return changelog.filter_changelog(self._catalog, query, text_matcher=matcher)

    def _refresh(self) -> None:
        try:
            filtered = self._filtered()
        except TimeoutError:
            self.feedback.SetLabel(
                _chrome_copy("changelog_timeout", self._language_mode)
            )
            self.results.Set([])
            return
        except (ValueError, changelog.ChangelogValidationError, re.error) as exc:
            self.feedback.SetLabel(
                f"{_chrome_copy('changelog_invalid', self._language_mode)}: {exc}"
            )
            self.results.Set([])
            return
        self.feedback.SetLabel(
            _chrome_copy("changelog_match_count", self._language_mode).format(
                count=len(filtered.entries)
            )
        )
        rows = [
            f"{entry.version} — {entry.released_on.isoformat()} — {entry.changes[0].summary}"
            for entry in filtered.entries
        ]
        self.results.Set(rows)
        if rows:
            self.results.SetSelection(0)

    def _export(self, _event: wx.Event) -> None:
        try:
            payload = changelog.export_markdown(self._filtered())
        except TimeoutError:
            self.feedback.SetLabel(
                _chrome_copy("changelog_timeout", self._language_mode)
            )
            return
        except (ValueError, changelog.ChangelogValidationError, re.error) as exc:
            self.feedback.SetLabel(
                f"{_chrome_copy('changelog_invalid', self._language_mode)}: {exc}"
            )
            return
        value = choose_path(
            self,
            "Export filtered changelog",
            default_path="changelog.md",
            wildcard="Markdown files (*.md)|*.md",
            save=True,
        )
        if not value:
            return
        path = Path(value)
        try:
            path.write_text(payload, encoding="utf-8", newline="\n")
        except OSError as exc:
            self.feedback.SetLabel(f"Could not export changelog: {exc}")
            return
        self._last_export_path = path
        self.open_export.Enable(True)
        self.feedback.SetLabel(f"Exported filtered changelog to {path}")

    def _open_export(self, _event: wx.Event) -> None:
        target = getattr(self, "_last_export_path", None)
        if target is None:
            return
        action = export_actions.open_exported_path(target)
        self.feedback.SetLabel(action.message)

    def _copy(self, _event: wx.Event) -> None:
        try:
            payload = changelog.export_markdown(self._filtered())
        except TimeoutError:
            self.feedback.SetLabel(
                _chrome_copy("changelog_timeout", self._language_mode)
            )
            return
        except (ValueError, changelog.ChangelogValidationError, re.error) as exc:
            self.feedback.SetLabel(
                f"{_chrome_copy('changelog_invalid', self._language_mode)}: {exc}"
            )
            return
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(payload))
            finally:
                wx.TheClipboard.Close()
            self.feedback.SetLabel("Copied filtered changelog to the clipboard")
        else:
            self.feedback.SetLabel("Could not open the clipboard")
