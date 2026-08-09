"""Material 3-inspired preferences and command palette surfaces.

The controls intentionally use native wx widgets so the surface remains usable
on headless and accessibility-enabled Windows desktops.  Colour, spacing and
typography are sourced from one persisted :mod:`api.preferences` record.
"""

from __future__ import annotations

from typing import Callable, Iterable, List, Tuple
import re

import wx

from amulet_map_editor.api import preferences
from amulet_map_editor.api.regex_builder import RegexBuilder


def _label(parent: wx.Window, text: str, help_text: str) -> wx.StaticText:
    control = wx.StaticText(parent, label=text)
    control.SetToolTip(help_text)
    return control


class PreferencesDialog(wx.Dialog):
    """Tabbed settings dialog with language, funny-level, and appearance controls."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent, title="Preferences", size=wx.Size(620, 480))
        self._prefs = preferences.load()
        root = wx.BoxSizer(wx.VERTICAL)
        self._tabs = wx.Notebook(self)
        self._build_language_tab()
        self._build_appearance_tab()
        self._build_search_tab()
        root.Add(self._tabs, 1, wx.EXPAND | wx.ALL, 12)
        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        reset = wx.Button(self, label="Reset to shipped values")
        reset.Bind(wx.EVT_BUTTON, self._reset)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(reset, 0, wx.LEFT | wx.BOTTOM, 12)
        row.AddStretchSpacer()
        row.Add(buttons, 0, wx.RIGHT | wx.BOTTOM, 12)
        root.Add(row, 0, wx.EXPAND)
        self.SetSizer(root)
        self.Bind(wx.EVT_BUTTON, self._save, id=wx.ID_OK)

    def _build_language_tab(self) -> None:
        page = wx.Panel(self._tabs)
        grid = wx.FlexGridSizer(0, 2, 12, 16)
        grid.AddGrowableCol(1, 1)
        grid.Add(_label(page, "Language mode", "Choose English, playful Hong Kong-style Cantonese, or both."), 0, wx.ALIGN_CENTER_VERTICAL)
        self.language = wx.Choice(page, choices=["English", "Playful Cantonese", "Bilingual"])
        self.language.SetSelection(preferences.LANGUAGE_MODES.index(self._prefs.language_mode))
        grid.Add(self.language, 1, wx.EXPAND)
        grid.Add(_label(page, "English funny level", "Styles every English message, including warnings; facts stay unchanged."), 0, wx.ALIGN_CENTER_VERTICAL)
        self.funny_en = wx.Slider(page, minValue=1, maxValue=5, value=self._prefs.funny_level_english, style=wx.SL_LABELS)
        grid.Add(self.funny_en, 1, wx.EXPAND)
        grid.Add(_label(page, "Cantonese funny level", "Styles every Cantonese message, including errors; facts stay unchanged."), 0, wx.ALIGN_CENTER_VERTICAL)
        self.funny_yue = wx.Slider(page, minValue=1, maxValue=5, value=self._prefs.funny_level_cantonese, style=wx.SL_LABELS)
        grid.Add(self.funny_yue, 1, wx.EXPAND)
        grid.Add(_label(page, "Dialog emojis", "Show a relevant decorative emoji in dialogs without changing control labels."), 0, wx.ALIGN_CENTER_VERTICAL)
        self.dialog_emojis = wx.CheckBox(page, label="Show emojis in dialogs and message boxes")
        self.dialog_emojis.SetValue(self._prefs.show_dialog_emojis)
        grid.Add(self.dialog_emojis, 1, wx.EXPAND)
        page.SetSizer(wx.BoxSizer(wx.VERTICAL))
        page.GetSizer().Add(grid, 0, wx.EXPAND | wx.ALL, 18)
        self._tabs.AddPage(page, "Language", True)

    def _build_appearance_tab(self) -> None:
        page = wx.Panel(self._tabs)
        grid = wx.FlexGridSizer(0, 2, 12, 16)
        grid.AddGrowableCol(1, 1)
        grid.Add(_label(page, "Theme", "Select light, dark, or follow the operating system."), 0, wx.ALIGN_CENTER_VERTICAL)
        self.theme = wx.Choice(page, choices=["Light", "Dark", "System"])
        self.theme.SetSelection(preferences.THEMES.index(self._prefs.theme))
        grid.Add(self.theme, 1, wx.EXPAND)
        grid.Add(_label(page, "Density", "Controls spacing throughout tabs, panels, and dialogs."), 0, wx.ALIGN_CENTER_VERTICAL)
        self.density = wx.Choice(page, choices=["Compact", "Comfortable", "Spacious"])
        self.density.SetSelection(("compact", "comfortable", "spacious").index(self._prefs.density))
        grid.Add(self.density, 1, wx.EXPAND)
        grid.Add(_label(page, "Accent colour", "Material 3 seed colour in #RRGGBB form."), 0, wx.ALIGN_CENTER_VERTICAL)
        self.accent = wx.TextCtrl(page, value=self._prefs.accent)
        grid.Add(self.accent, 1, wx.EXPAND)
        grid.Add(_label(page, "UI font", "Optional installed font family; blank uses the platform default."), 0, wx.ALIGN_CENTER_VERTICAL)
        self.font = wx.FontPickerCtrl(page)
        if self._prefs.ui_font:
            self.font.SetSelectedFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName=self._prefs.ui_font))
        grid.Add(self.font, 1, wx.EXPAND)
        grid.Add(_label(page, "UI scale", "Bounded scale for text and controls, persisted across restarts."), 0, wx.ALIGN_CENTER_VERTICAL)
        self.scale = wx.Slider(page, minValue=80, maxValue=200, value=int(self._prefs.ui_scale * 100), style=wx.SL_LABELS)
        grid.Add(self.scale, 1, wx.EXPAND)
        page.SetSizer(wx.BoxSizer(wx.VERTICAL))
        page.GetSizer().Add(grid, 0, wx.EXPAND | wx.ALL, 18)
        self._tabs.AddPage(page, "Appearance")

    def _build_search_tab(self) -> None:
        page = wx.Panel(self._tabs)
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(_label(page, "Regex builder", "Plain text is safest by default; enable regex only when you need groups or quantifiers."), 0, wx.BOTTOM, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.regex = wx.TextCtrl(page)
        self.regex.SetHint("Search settings, tabs, or commands")
        self.regex_mode = wx.CheckBox(page, label="Regex")
        self.regex_flags = wx.CheckBox(page, label="Ignore case")
        row.Add(self.regex, 1, wx.EXPAND | wx.RIGHT, 8)
        row.Add(self.regex_mode, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.regex_flags, 0, wx.ALIGN_CENTER_VERTICAL)
        box.Add(row, 0, wx.EXPAND)
        self.regex_result = wx.StaticText(page, label="Type to validate a pattern.")
        box.Add(self.regex_result, 0, wx.TOP, 10)
        self.regex.Bind(wx.EVT_TEXT, self._validate_regex)
        self.regex_mode.Bind(wx.EVT_CHECKBOX, self._validate_regex)
        self.regex_flags.Bind(wx.EVT_CHECKBOX, self._validate_regex)
        page.SetSizer(box)
        self._tabs.AddPage(page, "Search")

    def _validate_regex(self, _event: wx.Event) -> None:
        flags = 0x02 if self.regex_flags.GetValue() else 0
        result = RegexBuilder(self.regex.GetValue(), flags, self.regex_mode.GetValue()).validate()
        self.regex_result.SetLabel("Valid pattern" if result.valid else f"Invalid pattern: {result.error}")
        self.regex_result.SetForegroundColour(wx.Colour(40, 120, 70) if result.valid else wx.Colour(180, 40, 40))

    def _reset(self, _event: wx.Event) -> None:
        self._prefs = preferences.reset()
        self.EndModal(wx.ID_CANCEL)

    def _save(self, _event: wx.Event) -> None:
        language_mode = preferences.LANGUAGE_MODES[self.language.GetSelection()]
        theme = preferences.THEMES[self.theme.GetSelection()]
        font = self.font.GetSelectedFont().GetFaceName()
        preferences.save(preferences.Preferences(
            language_mode=language_mode,
            funny_level_english=self.funny_en.GetValue(),
            funny_level_cantonese=self.funny_yue.GetValue(),
            show_dialog_emojis=self.dialog_emojis.GetValue(),
            theme=theme,
            density=("compact", "comfortable", "spacious")[self.density.GetSelection()],
            accent=self.accent.GetValue(),
            ui_font=font,
            ui_scale=self.scale.GetValue() / 100.0,
        ))
        self.EndModal(wx.ID_OK)


class CommandPaletteDialog(wx.Dialog):
    """Keyboard-friendly command palette (Ctrl+Shift+F) with plain/regex search."""

    def __init__(self, parent: wx.Window, commands: Iterable[Tuple[str, Callable[[], None]]]):
        super().__init__(parent, title="Command palette", size=wx.Size(560, 420))
        self._commands: List[Tuple[str, Callable[[], None]]] = list(commands)
        root = wx.BoxSizer(wx.VERTICAL)
        self.query = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.query.SetHint("Search commands and destinations")
        self.regex = wx.CheckBox(self, label="Regex")
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.query, 1, wx.EXPAND | wx.RIGHT, 8)
        row.Add(self.regex, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(row, 0, wx.EXPAND | wx.ALL, 12)
        self.results = wx.ListBox(self)
        root.Add(self.results, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.SetSizer(root)
        self._refresh()
        self.query.Bind(wx.EVT_TEXT, lambda evt: self._refresh())
        self.regex.Bind(wx.EVT_CHECKBOX, lambda evt: self._refresh())
        self.query.Bind(wx.EVT_TEXT_ENTER, self._run)
        self.results.Bind(wx.EVT_LISTBOX_DCLICK, self._run)

    def _refresh(self) -> None:
        builder = RegexBuilder(self.query.GetValue(), regex_enabled=self.regex.GetValue())
        try:
            matches = builder.search([name for name, _ in self._commands])
        except (re.error, ValueError):
            matches = []
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
