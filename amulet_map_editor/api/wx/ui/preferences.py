"""Material 3-inspired preferences and command palette surfaces.

The controls intentionally use native wx widgets so the surface remains usable
on headless and accessibility-enabled Windows desktops.  Colour, spacing and
typography are sourced from one persisted :mod:`api.preferences` record.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple
import re
import uuid

import wx

from amulet_map_editor.api import appearance_presets, preferences
from amulet_map_editor.api import lang
from amulet_map_editor.api import scheduled_settings as schedules
from amulet_map_editor.api.regex_builder import RegexBuilder
from amulet_map_editor.api.wx.material3 import apply_material3


def _label(parent: wx.Window, text: str, help_text: str) -> wx.StaticText:
    control = wx.StaticText(parent, label=text)
    control.SetToolTip(help_text)
    return control


class PreferencesDialog(wx.Dialog):
    """Tabbed settings dialog with language, funny-level, and appearance controls."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent, title="Preferences", size=wx.Size(620, 480))
        self._prefs = preferences.load()
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
        grid.Add(
            _label(
                page,
                "Language mode",
                "Choose English, playful Hong Kong-style Cantonese, or both.",
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.language = wx.Choice(
            page, choices=["English", "Playful Cantonese", "Bilingual"]
        )
        self.language.SetSelection(
            preferences.LANGUAGE_MODES.index(self._prefs.language_mode)
        )
        grid.Add(self.language, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                "English funny level",
                "Styles every English message, including warnings; facts stay unchanged.",
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
                "Cantonese funny level",
                "Styles every Cantonese message, including errors; facts stay unchanged.",
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
                "Dialog emojis",
                "Show a relevant decorative emoji in dialogs without changing control labels.",
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.dialog_emojis = wx.CheckBox(
            page, label="Show emojis in dialogs and message boxes"
        )
        self.dialog_emojis.SetValue(self._prefs.show_dialog_emojis)
        grid.Add(self.dialog_emojis, 1, wx.EXPAND)
        page.SetSizer(wx.BoxSizer(wx.VERTICAL))
        page.GetSizer().Add(grid, 0, wx.EXPAND | wx.ALL, 18)
        self._tabs.AddPage(page, "Language", True)

    def _build_appearance_tab(self) -> None:
        page = wx.ScrolledWindow(self._tabs, style=wx.VSCROLL)
        page.SetScrollRate(0, 12)
        root = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(0, 2, 12, 16)
        grid.AddGrowableCol(1, 1)
        grid.Add(
            _label(
                page, "Theme", "Select light, dark, or follow the operating system."
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.theme = wx.Choice(page, choices=["Light", "Dark", "System"])
        self.theme.SetSelection(preferences.THEMES.index(self._prefs.theme))
        grid.Add(self.theme, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                "Density",
                "Controls spacing throughout tabs, panels, and dialogs.",
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.density = wx.Choice(page, choices=["Compact", "Comfortable", "Spacious"])
        self.density.SetSelection(
            ("compact", "comfortable", "spacious").index(self._prefs.density)
        )
        grid.Add(self.density, 1, wx.EXPAND)
        grid.Add(
            _label(page, "Accent colour", "Material 3 seed colour in #RRGGBB form."),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.accent = wx.TextCtrl(page, value=self._prefs.accent)
        grid.Add(self.accent, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                "UI font",
                "Optional installed font family; blank uses the platform default.",
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.font = wx.FontPickerCtrl(page)
        self._set_appearance_font(self._prefs.ui_font)
        self.font.Bind(wx.EVT_FONTPICKER_CHANGED, self._select_appearance_font)
        grid.Add(self.font, 1, wx.EXPAND)
        grid.Add(
            _label(
                page,
                "UI scale",
                "Bounded scale for text and controls, persisted across restarts.",
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
                "Named appearance presets",
                "Save, load, import, or export the five appearance values above.",
            ),
            0,
            wx.BOTTOM,
            6,
        )
        preset_row = wx.BoxSizer(wx.HORIZONTAL)
        self.appearance_preset_list = wx.Choice(page, choices=[])
        self.appearance_preset_list.SetName("Named appearance presets")
        self.appearance_preset_name = wx.TextCtrl(page)
        self.appearance_preset_name.SetHint("Preset name")
        self.appearance_preset_name.SetName("New appearance preset name")
        preset_row.Add(self.appearance_preset_list, 1, wx.EXPAND | wx.RIGHT, 8)
        preset_row.Add(self.appearance_preset_name, 1, wx.EXPAND)
        root.Add(preset_row, 0, wx.EXPAND | wx.BOTTOM, 8)

        preset_actions = wx.WrapSizer(wx.HORIZONTAL)
        self.appearance_preset_load = wx.Button(page, label="Load selected")
        self.appearance_preset_save = wx.Button(page, label="Save preset")
        self.appearance_preset_update = wx.Button(page, label="Update selected")
        self.appearance_preset_export = wx.Button(page, label="Export selected…")
        self.appearance_preset_import = wx.Button(page, label="Import preset…")
        for control in (
            self.appearance_preset_load,
            self.appearance_preset_save,
            self.appearance_preset_update,
            self.appearance_preset_export,
            self.appearance_preset_import,
        ):
            preset_actions.Add(control, 0, wx.RIGHT | wx.BOTTOM, 8)
        root.Add(preset_actions, 0, wx.EXPAND)

        reset_row = wx.WrapSizer(wx.HORIZONTAL)
        self.appearance_reset_property = wx.Choice(
            page,
            choices=["Theme", "Density", "Accent colour", "UI font", "UI scale"],
        )
        self.appearance_reset_property.SetSelection(0)
        self.appearance_reset_property.SetName("Appearance property to reset")
        self.appearance_reset_selected = wx.Button(page, label="Reset selected value")
        self.appearance_reset_all = wx.Button(page, label="Reset all appearance")
        reset_row.Add(self.appearance_reset_property, 1, wx.EXPAND | wx.RIGHT, 8)
        reset_row.Add(self.appearance_reset_selected, 0, wx.RIGHT, 8)
        reset_row.Add(self.appearance_reset_all, 0)
        root.Add(reset_row, 0, wx.EXPAND | wx.TOP, 4)

        self.appearance_status = wx.StaticText(page, label="")
        self.appearance_status.SetName("Appearance preset status")
        self.appearance_status.Wrap(540)
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
        self.appearance_preset_import.Bind(
            wx.EVT_BUTTON, self._import_appearance_preset
        )
        self.appearance_reset_selected.Bind(
            wx.EVT_BUTTON, self._reset_appearance_property
        )
        self.appearance_reset_all.Bind(wx.EVT_BUTTON, self._reset_appearance_form)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(root, 1, wx.EXPAND | wx.ALL, 18)
        page.SetSizer(outer)
        page.FitInside()
        self._appearance_tab_index = self._tabs.GetPageCount()
        self._tabs.AddPage(page, "Appearance")
        self._appearance_library_controls = (
            self.appearance_preset_list,
            self.appearance_preset_name,
            self.appearance_preset_load,
            self.appearance_preset_save,
            self.appearance_preset_update,
            self.appearance_preset_export,
            self.appearance_preset_import,
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

    def _show_appearance_message(self, message: str, error: bool = False) -> None:
        self.appearance_status.SetLabel(message)
        self.appearance_status.SetForegroundColour(
            wx.Colour(180, 40, 40) if error else wx.Colour(40, 120, 70)
        )
        self.appearance_status.Wrap(540)

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

    def _select_appearance_font(self, _event: wx.Event) -> None:
        self._appearance_font_uses_platform_default = False

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

    def _refresh_appearance_presets(self, selected_name: str = "") -> None:
        self._appearance_presets = list(appearance_presets.load_presets())
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

    def _export_appearance_preset(self, _event: wx.Event) -> None:
        preset = self._selected_appearance_preset()
        if preset is None:
            self._show_appearance_message("Select a preset to export.", error=True)
            return
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", preset.name).strip("-.")
        with wx.FileDialog(
            self,
            "Export appearance preset",
            defaultFile=(safe_name or "appearance-preset") + ".json",
            wildcard="JSON files (*.json)|*.json",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = Path(dialog.GetPath())
        try:
            path.write_text(
                appearance_presets.export_preset(preset),
                encoding="utf-8",
                newline="\n",
            )
        except OSError as exc:
            self._show_appearance_message(f"Preset was not exported: {exc}", error=True)
            return
        self._show_appearance_message(f'Exported "{preset.name}" to {path}.')

    def _import_appearance_preset(self, _event: wx.Event) -> None:
        with wx.FileDialog(
            self,
            "Import appearance preset",
            wildcard="JSON files (*.json)|*.json",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = Path(dialog.GetPath())
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
        page = wx.ScrolledWindow(self._tabs, style=wx.VSCROLL)
        page.SetScrollRate(0, 12)
        root = wx.BoxSizer(wx.VERTICAL)

        explanation = wx.StaticText(page, label=self._schedule_text("explanation"))
        explanation.Wrap(540)
        root.Add(explanation, 0, wx.EXPAND | wx.BOTTOM, 10)

        self.schedule_list = wx.ListBox(page)
        self.schedule_list.SetMinSize(wx.Size(-1, 88))
        root.Add(self.schedule_list, 0, wx.EXPAND | wx.BOTTOM, 8)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.schedule_new = wx.Button(page, label=self._schedule_text("add"))
        self.schedule_remove = wx.Button(page, label=self._schedule_text("remove"))
        self.schedule_up = wx.Button(page, label=self._schedule_text("moveup"))
        self.schedule_down = wx.Button(page, label=self._schedule_text("movedown"))
        actions.Add(self.schedule_new, 0, wx.RIGHT, 8)
        actions.Add(self.schedule_remove, 0, wx.RIGHT, 8)
        actions.Add(self.schedule_up, 0, wx.RIGHT, 8)
        actions.Add(self.schedule_down, 0)
        root.Add(actions, 0, wx.BOTTOM, 12)

        grid = wx.FlexGridSizer(0, 2, 8, 12)
        grid.AddGrowableCol(1, 1)

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

        weekday_panel = wx.Panel(page)
        weekday_sizer = wx.WrapSizer(wx.HORIZONTAL)
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

        self.schedule_start_date = wx.TextCtrl(page)
        self.schedule_start_date.SetHint("YYYY-MM-DD")
        add_row("startdate", self.schedule_start_date)
        self.schedule_end_date = wx.TextCtrl(page)
        self.schedule_end_date.SetHint("YYYY-MM-DD")
        add_row("enddate", self.schedule_end_date)
        self.schedule_start_time = wx.TextCtrl(page)
        self.schedule_start_time.SetHint("HH:MM")
        add_row("starttime", self.schedule_start_time)
        self.schedule_end_time = wx.TextCtrl(page)
        self.schedule_end_time.SetHint("HH:MM")
        add_row("endtime", self.schedule_end_time)

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
        self.schedule_validation.Wrap(540)
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

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(root, 1, wx.EXPAND | wx.ALL, 18)
        page.SetSizer(outer)
        page.FitInside()
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

    def _mark_schedule_dirty(self, _event: wx.Event) -> None:
        if not self._schedule_loading:
            self._schedule_form_dirty = True

    def _show_schedule_message(self, message: str, error: bool = False) -> None:
        self.schedule_validation.SetLabel(message)
        self.schedule_validation.SetForegroundColour(
            wx.Colour(180, 40, 40) if error else wx.Colour(40, 120, 70)
        )
        self.schedule_validation.Wrap(540)

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
            values=values,
        )

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

    def _toggle_every_day(self, _event: wx.Event) -> None:
        every_day = self.schedule_every_day.GetValue()
        for checkbox in self.schedule_weekdays:
            if every_day:
                checkbox.SetValue(True)
            checkbox.Enable(not every_day)

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
        page = wx.Panel(self._tabs)
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(
            _label(
                page,
                "Regex builder",
                "Plain text is safest by default; enable regex only when you need groups or quantifiers.",
            ),
            0,
            wx.BOTTOM,
            8,
        )
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
        result = RegexBuilder(
            self.regex.GetValue(), flags, self.regex_mode.GetValue()
        ).validate()
        self.regex_result.SetLabel(
            "Valid pattern" if result.valid else f"Invalid pattern: {result.error}"
        )
        self.regex_result.SetForegroundColour(
            wx.Colour(40, 120, 70) if result.valid else wx.Colour(180, 40, 40)
        )

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
            appearance = self._appearance_values_from_form()
        except appearance_presets.AppearancePresetValidationError as exc:
            self._show_appearance_message(
                f"Appearance settings were not saved: {exc}", error=True
            )
            self._tabs.SetSelection(self._appearance_tab_index)
            return
        preferences.save(
            preferences.Preferences(
                language_mode=language_mode,
                funny_level_english=self.funny_en.GetValue(),
                funny_level_cantonese=self.funny_yue.GetValue(),
                show_dialog_emojis=self.dialog_emojis.GetValue(),
                theme=appearance.theme,
                density=appearance.density,
                accent=appearance.accent,
                ui_font=appearance.ui_font,
                ui_scale=appearance.ui_scale,
            )
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
        self.EndModal(wx.ID_OK)


class CommandPaletteDialog(wx.Dialog):
    """Keyboard-friendly command palette (Ctrl+Shift+F) with plain/regex search."""

    def __init__(
        self, parent: wx.Window, commands: Iterable[Tuple[str, Callable[[], None]]]
    ):
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
        builder = RegexBuilder(
            self.query.GetValue(), regex_enabled=self.regex.GetValue()
        )
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
