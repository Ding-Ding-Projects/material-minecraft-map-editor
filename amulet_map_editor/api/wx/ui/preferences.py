"""Material 3 preferences, command palette, and changelog surfaces.

Every control on these surfaces is drawn by the product rather than by the
operating system.  That was not true until recently and the difference is not
cosmetic: a settings window built from native widgets showed the platform's own
title bar with the platform's own window buttons across the top of a frameless
application, native notebook tabs, native text boxes where a theme and a
density belong in a real select, an accent colour presented as the bare string
``#6750A4`` with no swatch and no picker behind it, and a native scrollbar down
the edge of the page.

It also photographed as almost nothing.  A native control on a desktop with no
compositor answers a capture with an empty rectangle, so the same window that
looked passable on screen came back from the capture harness as a handful of
blank boxes -- which is why "the tests are green" was never evidence that this
surface rendered.

The replacements live in :mod:`amulet_map_editor.api.wx.ui.material_forms` and
:mod:`amulet_map_editor.api.wx.ui.material_tabs`.  They answer to the same
``wx`` vocabulary the handlers below already speak -- ``GetValue``,
``SetSelection``, ``Set``, ``wx.EVT_TEXT``, ``wx.EVT_CHOICE`` -- so what
changed here is what is drawn and what is explained, not what any control does.
Colour, spacing and typography are sourced from one persisted
:mod:`api.preferences` record.
"""

from __future__ import annotations

import logging
import os

from datetime import date
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple
import re
import uuid

import wx
import wx.adv

from amulet_map_editor.api import (
    appearance_presets,
    appearance_editor,
    changelog,
    external_editor,
    export_actions,
    local_history,
    preferences,
    scheduled_sources,
    school_mode,
    text_overlay,
)
from amulet_map_editor.api import config, lang
from amulet_map_editor.api import scheduled_settings as schedules
from amulet_map_editor.api.regex_builder import RegexBuilder
from amulet_map_editor.api.studio import widgets as studio
from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.api.wx.nonblocking import notify
from amulet_map_editor.api.wx.ui import material_forms as forms
from amulet_map_editor.api.wx.ui.material_tabs import MaterialTabs
from amulet_map_editor.api.wx.ui.path_dialog import choose_path
from amulet_map_editor.api.wx.ui.regex_dialog import RegexBuilderDialog
from amulet_map_editor.api.wx.ui.simple import MaterialDateTimeField

log = logging.getLogger(__name__)


def _label(parent: wx.Window, text: str, help_text: str) -> studio.StudioText:
    """Return one painted caption.

    It replaces ``wx.StaticText``, which took its ink from a native foreground
    colour rather than a palette role -- so a theme change left it behind --
    and which painted through the platform, so a capture of this surface came
    back with every label missing.  ``SetLabel``, ``GetLabel`` and
    ``SetForegroundColour`` keep their spelling, so the callers below are
    unchanged.
    """
    control = studio.StudioText(parent, text, size_px=13, role="on_surface", name=text)
    control.SetToolTip(help_text)
    return control


def _stored_preferences() -> dict:
    """Return the raw persisted preference record, for the provenance lines.

    A key absent from this dict is a value nobody has written, so the dialog is
    showing what the application was compiled with.  Saying which of the two a
    reader is looking at is the whole point of a provenance line; guessing it
    from the value would be wrong exactly when the stored value happens to
    equal the shipped one.
    """
    raw = config.get(preferences.PREFERENCES_ID, {})
    return raw if isinstance(raw, dict) else {}


#: :mod:`text_overlay` persists the validated *contents* of an overlay so
#: they survive a restart, but deliberately not the path they were loaded
#: from -- that path is not part of the bounded schema it caches.  This
#: separate, UI-owned identifier remembers it purely so Reload keeps working
#: without asking the user to browse again, and so the field is not blank the
#: next time this dialog opens.
_OVERLAY_SOURCE_PATH_ID = "text_overlay_source_path"


def _overlay_source_path() -> str:
    """Return the path the active overlay was most recently loaded from."""
    raw = config.get(_OVERLAY_SOURCE_PATH_ID, "")
    return raw if isinstance(raw, str) else ""


def _set_overlay_source_path(path: str) -> None:
    config.put(_OVERLAY_SOURCE_PATH_ID, path)


def _overlay_cache_path() -> str:
    """Return where the validated overlay is cached, mirroring :mod:`config`.

    This re-derives the same directory :mod:`config` resolves ``CONFIG_DIR``
    into rather than reaching into its private path helper, so a test that
    points ``CONFIG_DIR`` at a temporary profile still sees this line agree
    with where :mod:`config` actually wrote the file.
    """
    root = os.path.abspath(os.path.join(os.environ.get("CONFIG_DIR") or "."))
    return os.path.join(root, text_overlay.OVERLAY_CACHE_ID + ".config")


def _chrome_copy(key: str, mode: str) -> str:
    """Compose command/changelog chrome from the persisted language resources."""

    english = lang.get(f"preferences.en.{key}")
    cantonese = lang.get(f"preferences.zh.{key}")
    if mode == "cantonese":
        return cantonese
    if mode == "bilingual":
        return f"{english} · {cantonese}"
    return english


class PreferencesDialog(wx.Dialog):
    """Tabbed settings dialog with language, funny-level, and appearance controls."""

    def __init__(self, parent: wx.Window):
        super().__init__(
            parent,
            title="Preferences",
            # Wider and taller than the old surface, because the tab strip is
            # docked down the left edge and every settings element now carries
            # a help affordance and a value-source line under it. The window
            # stays resizable, and the pages scroll, so a smaller display is
            # still usable -- but opening onto a page whose first row is
            # already cut off is a bad first impression that costs nothing to
            # avoid.
            size=wx.Size(1000, 720),
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        self._prefs = preferences.load()
        self._school = school_mode.load()
        # ``_build_overlay_row`` sets this from the real cache; declared here
        # only so the attribute exists before that tab is built.
        self._overlay: Optional[text_overlay.TextOverlay] = None
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
        self._stored = _stored_preferences()
        # The project's rule is that a desktop window draws its own caption, so
        # the platform's title bar, system menu, and window boxes come off and
        # the product's own bar goes on. Leaving the native caption put a strip
        # of somebody else's design across the top of a frameless application.
        forms.make_frameless(self)
        root = wx.BoxSizer(wx.VERTICAL)
        self.title_bar = forms.MaterialDialogTitleBar(
            self,
            "Preferences",
            subtitle="Settings for this installation",
            maximise=True,
        )
        root.Add(self.title_bar, 0, wx.EXPAND)
        self._tabs = MaterialTabs(self, "preferences")
        self._build_language_tab()
        self._build_appearance_tab()
        self._build_schedule_tab()
        self._build_search_tab()
        if self._school.enabled:
            # School mode keeps its own control discoverable, but removes the
            # language/funny controls that are intentionally not applicable.
            self._tabs.RemovePage(self._tabs.GetPageIndex(self._language_page))
        root.Add(self._tabs, 1, wx.EXPAND)
        root.Add(self._build_action_bar(), 0, wx.EXPAND)
        self.SetSizer(root)
        self.Bind(wx.EVT_BUTTON, self._save, id=wx.ID_OK)
        # This dialog has already built its own caption above, so the shared
        # styling pass must not build a second one. Without this flag it did:
        # ``apply_material3`` fits any captionless dialog with the legacy
        # ``MaterialTitleBar``, which arrived on top of this one as a blank
        # 44-pixel strip -- blank because that bar's title is a native
        # ``wx.StaticText``, which is exactly what this surface stopped using.
        self._material3_dialog_chrome = True
        # Dialogs can be opened after the frame's one-time shell styling pass.
        # Apply the same M3 roles locally so settings surfaces do not fall back
        # to the native palette when opened from the menu or command palette.
        apply_material3(self)
        # ``apply_material3`` re-colours every child it walks, including the
        # painted ones, so the surfaces that own a role of their own are told
        # again afterwards. Without this the title bar's own text came back
        # drawn on plain-surface tiles laid over the container-coloured bar.
        self.title_bar.refresh_theme()
        self._tabs.refresh_theme()
        self.Layout()

    def _build_action_bar(self) -> wx.Sizer:
        """Build the painted OK / Cancel / reset row.

        ``CreateStdDialogButtonSizer`` builds native buttons and puts them in
        the platform's own order, which is exactly the chrome this surface is
        removing.  The dialog identifiers stay ``wx.ID_OK`` and
        ``wx.ID_CANCEL`` so the existing handler bindings and the modal return
        codes are unchanged.
        """
        self.reset_button = studio.StudioButton(
            self,
            "Reset to shipped values",
            variant="text",
            hint="Discard every stored preference and return to what the app ships with",
            name="Reset to shipped values",
        )
        self.reset_button.Bind(wx.EVT_BUTTON, self._reset)
        self.cancel_button = studio.StudioButton(
            self, "Cancel", variant="outlined", name="Cancel"
        )
        self.cancel_button.SetId(wx.ID_CANCEL)
        self.cancel_button.Bind(
            wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_CANCEL)
        )
        self.ok_button = studio.StudioButton(
            self, "Save preferences", variant="filled", name="Save preferences"
        )
        self.ok_button.SetId(wx.ID_OK)
        self.SetAffirmativeId(wx.ID_OK)
        self.SetEscapeId(wx.ID_CANCEL)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.reset_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 16)
        row.AddStretchSpacer()
        row.Add(self.cancel_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.ok_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(studio.Divider(self), 0, wx.EXPAND | wx.BOTTOM, 12)
        outer.Add(row, 0, wx.EXPAND | wx.BOTTOM, 14)
        return outer

    def _row(
        self,
        parent: wx.Window,
        label: str,
        explanation: str,
        *,
        key: str = "",
        default: object = "",
        unit: str = "",
        provenance: str = "",
    ) -> forms.SettingRow:
        """Return one settings element carrying its help and its value source."""
        if not provenance and key:
            provenance = forms.stored_provenance(self._stored, key, default, unit=unit)
        return forms.SettingRow(
            parent, label, explanation=explanation, provenance=provenance
        )

    def _build_language_tab(self) -> None:
        """Build the language mode, the two funny levels, and the emoji switch.

        The rows are stacked rather than laid out in a label/control grid.  A
        two-column grid puts a long localized label and its control on one
        line, which is where bilingual mode clips: the same row that fits in
        English does not fit with the Cantonese underneath it.
        """
        page = wx.Panel(self._tabs.host)
        column = wx.BoxSizer(wx.VERTICAL)

        language_row = self._row(
            page,
            "Language mode",
            "Chooses which language every label, message, and narrated line is "
            "written in. Bilingual shows English and Cantonese together, with "
            "the English kept prominent so a narrow window does not crowd.",
            key="language_mode",
            default="english",
        )
        self.language = forms.MaterialChoice(
            language_row.body,
            ["English", "Playful Cantonese", "Bilingual"],
            label="Language mode",
        )
        self.language.SetSelection(
            preferences.LANGUAGE_MODES.index(self._prefs.language_mode)
        )
        language_row.set_control(self.language, 0)
        column.Add(language_row, 0, wx.EXPAND | wx.BOTTOM, 18)

        english_row = self._row(
            page,
            "English funny level",
            "Styles every English message, including warnings and errors. Only "
            "the voice changes: what happened, what it affects, and what your "
            "options are stay exactly as precise at level 5 as at level 1.",
            key="funny_level_english",
            default=1,
        )
        self.funny_en = forms.MaterialSlider(
            english_row.body,
            value=self._prefs.funny_level_english,
            minValue=1,
            maxValue=5,
            name="English funny level",
        )
        english_row.set_control(self.funny_en)
        column.Add(english_row, 0, wx.EXPAND | wx.BOTTOM, 18)

        cantonese_row = self._row(
            page,
            "Cantonese funny level",
            "Styles every Cantonese message on the same scale, and independently "
            "of the English one. Humour never mocks you, your data, or your money.",
            key="funny_level_cantonese",
            default=1,
        )
        self.funny_yue = forms.MaterialSlider(
            cantonese_row.body,
            value=self._prefs.funny_level_cantonese,
            minValue=1,
            maxValue=5,
            name="Cantonese funny level",
        )
        cantonese_row.set_control(self.funny_yue)
        column.Add(cantonese_row, 0, wx.EXPAND | wx.BOTTOM, 18)

        emoji_row = self._row(
            page,
            "Dialog emojis",
            "Adds one relevant decorative emoji to dialogs and message boxes. "
            "Buttons, field labels, and accessible names never take one, so "
            "nothing a screen reader announces changes with this setting.",
            key="show_dialog_emojis",
            default=True,
        )
        self.dialog_emojis = studio.StudioCheckBox(
            emoji_row.body,
            "Show emojis in dialogs and message boxes",
            value=self._prefs.show_dialog_emojis,
            name="Show emojis in dialogs and message boxes",
        )
        emoji_row.set_control(self.dialog_emojis, 0)
        column.Add(emoji_row, 0, wx.EXPAND | wx.BOTTOM, 18)

        self._build_overlay_row(page, column)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(column, 1, wx.EXPAND | wx.ALL, 20)
        page.SetSizer(outer)
        self._language_page = page
        self._tabs.AddPage(page, "Language", True)

    def _build_overlay_row(self, page: wx.Window, column: wx.Sizer) -> None:
        """Build the display-text overlay's path field, actions, and status.

        This is a generic, content-agnostic mechanism: the application knows
        nothing about what any particular uploaded file says, only that it is
        a bounded JSON object mapping display text to a replacement. Load,
        Reload, and Remove all take effect immediately -- they never wait for
        Save preferences -- so the state line below is always live.
        """
        overlay_row = self._row(
            page,
            "Display-text overlay",
            "Loads a JSON file you choose from your own machine and swaps "
            "matching interface strings for the replacements it contains. "
            "Nothing about what a particular file says is known here, only "
            "its shape and size -- the count below is the only summary of "
            "its contents this dialog ever shows.",
        )
        self.overlay_path = forms.MaterialTextField(
            overlay_row.body,
            "Overlay file",
            _overlay_source_path(),
            placeholder="Optional: path to a display-text overlay JSON file",
            name="Display-text overlay file",
        )
        self.overlay_browse = studio.StudioButton(
            overlay_row.body,
            "Browse…",
            variant="outlined",
            name="Browse for overlay file",
        )
        self.overlay_load = studio.StudioButton(
            overlay_row.body, "Load", variant="tonal", name="Load overlay"
        )
        self.overlay_reload = studio.StudioButton(
            overlay_row.body, "Reload", variant="outlined", name="Reload overlay"
        )
        self.overlay_remove = studio.StudioButton(
            overlay_row.body, "Remove", variant="danger", name="Remove overlay"
        )
        overlay_row.set_control(self.overlay_path)
        overlay_row.add_extra(self.overlay_browse)
        overlay_row.add_extra(self.overlay_load)
        overlay_row.add_extra(self.overlay_reload)
        overlay_row.add_extra(self.overlay_remove)
        self.overlay_status = studio.StudioText(
            overlay_row,
            "",
            size_px=12,
            wrap_width=520,
            name="Display-text overlay status",
        )
        overlay_row.GetSizer().Add(self.overlay_status, 0, wx.EXPAND | wx.TOP, 4)
        self._overlay_row = overlay_row
        self.overlay_browse.Bind(wx.EVT_BUTTON, self._browse_overlay_path)
        self.overlay_load.Bind(wx.EVT_BUTTON, self._load_overlay)
        self.overlay_reload.Bind(wx.EVT_BUTTON, self._reload_overlay)
        self.overlay_remove.Bind(wx.EVT_BUTTON, self._remove_overlay)
        # A cache entry left over from an earlier run is read the same way the
        # running application would read it, so the dialog opens honestly
        # describing what is actually active rather than "nothing yet".
        self._overlay = text_overlay.load_cached_overlay()
        self._refresh_overlay_state()
        column.Add(overlay_row, 0, wx.EXPAND)

    def _refresh_overlay_state(self, error: str = "") -> None:
        """Reflect the overlay's real, current state -- live, never on restart.

        ``error`` is shown when the most recent action was refused; the
        overlay it describes otherwise is always whatever is genuinely
        active, which on a refusal is whatever was active before it.
        """
        overlay = self._overlay
        source = _overlay_source_path()
        if error:
            message = error
        elif overlay is None:
            message = "No overlay is loaded. The interface renders its shipped wording."
        else:
            count = len(overlay.replacements)
            plural = "" if count == 1 else "s"
            message = (
                f"Overlay loaded from {source} ({count} replacement{plural})."
                if source
                else f"Overlay active ({count} replacement{plural})."
            )
        self.overlay_status.SetLabel(message)
        self.overlay_status.SetForegroundColour(
            wx.Colour(180, 40, 40)
            if error
            else (
                wx.Colour(40, 120, 70)
                if overlay is not None
                else wx.Colour(110, 110, 110)
            )
        )
        self.overlay_status.Wrap(520)
        self._overlay_row.set_provenance(
            f"Cached at {_overlay_cache_path()}."
            if overlay is not None
            else "Nothing cached yet; the interface renders its shipped wording."
        )
        self.overlay_reload.Enable(bool(self.overlay_path.GetValue().strip()))
        self.overlay_remove.Enable(overlay is not None)
        self.Layout()

    def _browse_overlay_path(self, _event: wx.Event) -> None:
        """Stage a chosen path; Load below runs the exact same validation on it."""
        value = choose_path(
            self,
            "Choose a display-text overlay file",
            wildcard="JSON files (*.json)|*.json|All files (*.*)|*.*",
        )
        if not value:
            return
        self.overlay_path.SetValue(value)
        self._refresh_overlay_state()

    def _load_overlay(self, _event: wx.Event) -> None:
        """Load and activate the overlay now -- this never waits for OK."""
        path = self.overlay_path.GetValue().strip()
        if not path:
            self._refresh_overlay_state("Choose a file to load.")
            return
        try:
            overlay = text_overlay.load_overlay_file(path)
        except text_overlay.OverlayError as exc:
            # On refusal ``self._overlay`` (and the cache behind it) are left
            # exactly as they were: a bad reload must never clobber a good
            # overlay that was already active.
            self._refresh_overlay_state(str(exc))
            return
        self._overlay = overlay
        _set_overlay_source_path(path)
        self._refresh_overlay_state()

    def _reload_overlay(self, _event: wx.Event) -> None:
        """Re-read the overlay from the path shown in the field above.

        Editing the file externally and reloading is meant to be one click:
        this runs the exact same load Load does, against whatever path is
        currently staged there.
        """
        if not self.overlay_path.GetValue().strip():
            self._refresh_overlay_state(
                "No overlay has been loaded yet, so there is nothing to reload."
            )
            return
        self._load_overlay(_event)

    def _remove_overlay(self, _event: wx.Event) -> None:
        """Clear the overlay now; the interface returns to shipped wording."""
        text_overlay.clear_cached_overlay()
        self._overlay = None
        _set_overlay_source_path("")
        self.overlay_path.ChangeValue("")
        self._refresh_overlay_state()

    def _build_appearance_tab(self) -> None:
        """Build the identity, School mode, theme, colour, font, and preset rows.

        Every control here is painted.  Theme and density are real selects with
        their own search rather than text boxes somebody has to know the
        spelling of; the accent colour is a live swatch beside the continuous
        picker and its translator rather than a hex string in a field; and the
        page scrolls under a painted bar instead of the platform's own.
        """
        scroller = forms.MaterialScrolled(self._tabs.host, name="Appearance settings")
        # Every row is built on the scroller's content panel rather than on the
        # scroller itself. A sizer installed on a scrolled window is laid out
        # into the viewport, and a BoxSizer short of room silently takes the
        # shortfall out of whatever is last -- which here was every setting
        # below the fold, sized to zero height while still reporting IsShown().
        page = scroller.content
        root = wx.BoxSizer(wx.VERTICAL)

        identity = self._row(
            page,
            "App display name",
            "Changes only the name this application shows you -- the title bar, "
            "the About surface, its own messages. The package identity, the "
            "data folder, and the update feed keep the shipped name, so "
            "renaming can never orphan your stored profile, and a diagnostic "
            "report still says which software produced it.",
            key="display_name",
            default=preferences.DEFAULT_DISPLAY_NAME,
        )
        self.display_name = forms.MaterialTextField(
            identity.body,
            "App display name",
            self._prefs.display_name,
            name="App display name",
        )
        self.display_name.SetMaxLength(preferences.MAX_DISPLAY_NAME_LENGTH)
        self.display_name_reset = studio.StudioButton(
            identity.body,
            "Reset name",
            variant="outlined",
            hint="Restore the shipped name, Amulet.",
            name="Reset name",
        )
        self.display_name_reset.Bind(wx.EVT_BUTTON, self._reset_display_name_form)
        identity.set_control(self.display_name)
        identity.add_extra(self.display_name_reset)
        self.identity_status = studio.StudioText(
            identity, "", size_px=12, name="App display name validation"
        )
        identity.GetSizer().Add(self.identity_status, 0, wx.EXPAND | wx.TOP, 4)
        root.Add(identity, 0, wx.EXPAND | wx.BOTTOM, 18)

        school = self._row(
            page,
            "School mode",
            "A shared local presentation lock. While it is on, every app forces "
            "English, serious copy, and no dialog emojis, and the playful "
            "capabilities behave as though they were not installed. It is a "
            "user-experience lock, not a security boundary.",
            provenance=(
                "Stored in the shared local application-data record, not in "
                "this app's preferences file."
            ),
        )
        self.school_name = forms.MaterialTextField(
            school.body,
            "Mode name",
            self._school.mode_name,
            name="School mode name",
        )
        self.school_name.SetMaxLength(school_mode.MAX_MODE_NAME_LENGTH)
        self.school_enabled = studio.StudioCheckBox(
            school.body,
            "Enabled",
            value=self._school.enabled,
            name="School mode enabled",
        )
        school.set_control(self.school_name)
        school.add_extra(self.school_enabled)
        if self._school.enabled:
            active = studio.StudioText(
                school,
                "School mode is active: English-only serious presentation is enforced.",
                size_px=12,
                name="School mode active status",
            )
            school.GetSizer().Add(active, 0, wx.EXPAND | wx.TOP, 4)
        root.Add(school, 0, wx.EXPAND | wx.BOTTOM, 18)

        credential = self._row(
            page,
            "Unlock credential",
            "The local credential that leaves School mode. Only a salted "
            "verifier is stored, never the credential itself, and it never "
            "enters an export, a log, or this project's version history. "
            "Leaving the field blank keeps whatever credential is already set.",
            provenance=(
                "Held in the shared local record. Deleting that folder resets it."
            ),
        )
        self.school_credential = forms.MaterialTextField(
            credential.body,
            "Unlock credential",
            password=True,
            placeholder="4–128 characters; leave blank to keep the current credential",
            name="School mode unlock credential",
        )
        credential.set_control(self.school_credential)
        root.Add(credential, 0, wx.EXPAND | wx.BOTTOM, 18)

        theme_row = self._row(
            page,
            "Theme",
            "Light, dark, or whatever the operating system is currently set to. "
            "The choice is applied live: the shell, its panels, and every open "
            "dialog re-read the palette without a restart.",
            key="theme",
            default="system",
        )
        self.theme = forms.MaterialChoice(
            theme_row.body, ["Light", "Dark", "System"], label="Theme"
        )
        self.theme.SetSelection(preferences.THEMES.index(self._prefs.theme))
        theme_row.set_control(self.theme, 0)
        root.Add(theme_row, 0, wx.EXPAND | wx.BOTTOM, 18)

        density_row = self._row(
            page,
            "Density",
            "How much breathing room controls get. Compact fits more on a small "
            "display; spacious grows the touch targets. It changes spacing and "
            "control heights throughout tabs, panels, and dialogs.",
            key="density",
            default="comfortable",
        )
        self.density = forms.MaterialChoice(
            density_row.body, ["Compact", "Comfortable", "Spacious"], label="Density"
        )
        self.density.SetSelection(
            ("compact", "comfortable", "spacious").index(self._prefs.density)
        )
        density_row.set_control(self.density, 0)
        root.Add(density_row, 0, wx.EXPAND | wx.BOTTOM, 18)

        accent_row = self._row(
            page,
            "Accent colour",
            "The Material 3 seed colour every other role is derived from. The "
            "swatch opens the continuous picker with its spectrum, its entry in "
            "every supported colour space, its translator, and its contrast "
            "readout; the field beside it accepts #RRGGBB or #RRGGBBAA directly.",
            key="accent",
            default="#6750A4",
        )
        self.accent_colour_picker = forms.MaterialColourField(
            accent_row.body,
            self._prefs.accent,
            name="Accent colour picker",
            subject="Appearance",
        )
        self.accent = forms.MaterialTextField(
            accent_row.body,
            "Accent colour HEX",
            self._prefs.accent,
            placeholder="#RRGGBB or #RRGGBBAA",
            mono=True,
            name="Accent colour HEX",
        )
        accent_row.set_control(self.accent_colour_picker, 0)
        accent_row.add_extra(self.accent, 1)
        self.accent_swatch = studio.Swatch(
            accent_row, self._prefs.accent, name="Accent colour preview", size=20
        )
        self.accent_contrast = studio.StudioText(
            accent_row, "", size_px=12, name="Accent colour contrast readout"
        )
        contrast_row = wx.BoxSizer(wx.HORIZONTAL)
        contrast_row.Add(self.accent_swatch, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        contrast_row.Add(self.accent_contrast, 1, wx.ALIGN_CENTER_VERTICAL)
        accent_row.GetSizer().Add(contrast_row, 0, wx.EXPAND | wx.TOP, 6)
        root.Add(accent_row, 0, wx.EXPAND | wx.BOTTOM, 18)

        translator = self._row(
            page,
            "Colour translator",
            "The same accent colour, addressed as RGB or as HSL. Press Enter in "
            "either field and every other reading of the colour -- the hex "
            "field, the swatch, the picker, the contrast line -- updates to "
            "match, because all of them are one persisted value.",
            provenance="Two views of the accent colour above; nothing separate is stored.",
        )
        self.accent_rgb = forms.MaterialTextField(
            translator.body,
            "RGB",
            placeholder="RGB: 103, 80, 164",
            process_enter=True,
            mono=True,
            name="Accent colour RGB",
        )
        self.accent_hsl = forms.MaterialTextField(
            translator.body,
            "HSL",
            placeholder="HSL: 262, 34%, 48%",
            process_enter=True,
            mono=True,
            name="Accent colour HSL",
        )
        translator.set_control(self.accent_rgb)
        translator.add_extra(self.accent_hsl, 1)
        root.Add(translator, 0, wx.EXPAND | wx.BOTTOM, 18)

        font_row = self._row(
            page,
            "UI font",
            "The typeface the interface is drawn in. Opening it gives the full "
            "typography editor -- every installed and bundled face, size, "
            "weight, and the variable-font axes a face exposes -- with a "
            "CJK-safe fallback so bilingual copy never drops to boxes. Leaving "
            "it unset uses the platform default.",
            key="ui_font",
            default="",
        )
        self.font = forms.MaterialFontField(
            font_row.body, name="UI font picker", subject="Appearance"
        )
        self._set_appearance_font(self._prefs.ui_font)
        self.font.Bind(wx.EVT_FONTPICKER_CHANGED, self._select_appearance_font)
        font_row.set_control(self.font, 0)
        root.Add(font_row, 0, wx.EXPAND | wx.BOTTOM, 18)

        font_search_row = self._row(
            page,
            "Installed font search",
            "Searches the family names this machine actually has. Plain text is "
            "the default; the builder beside the field composes a bounded "
            "regular expression when you need groups or quantifiers. Choosing a "
            "result updates the live preview and the persisted UI font.",
            provenance="Reads the installed font list; nothing is stored by the search.",
        )
        self.font_search = forms.MaterialTextField(
            font_search_row.body,
            "Search installed fonts",
            placeholder="Search installed fonts",
            name="Installed font search",
        )
        self.font_regex = studio.StudioCheckBox(
            font_search_row.body, "Regex", name="Installed font regex mode"
        )
        self.font_regex_button = studio.StudioButton(
            font_search_row.body,
            "Regex…",
            variant="outlined",
            hint="Build a bounded regular-expression font search",
            name="Installed font regex builder",
        )
        self.font_choice = forms.MaterialChoice(
            font_search_row.body, [], label="Installed font choices"
        )
        font_search_row.set_control(self.font_search)
        font_search_row.add_extra(self.font_regex)
        font_search_row.add_extra(self.font_regex_button)
        font_search_row.add_extra(self.font_choice, 1)
        self.font_preview = studio.StudioText(
            font_search_row,
            "The quick brown fox jumps over the lazy dog · 蝦餃",
            size_px=14,
            role="on_surface",
            name="Live typography preview",
        )
        font_search_row.GetSizer().Add(self.font_preview, 0, wx.EXPAND | wx.TOP, 8)
        root.Add(font_search_row, 0, wx.EXPAND | wx.BOTTOM, 18)

        editor_row = self._row(
            page,
            "External editor",
            "Visual Studio Code, or a compatible Code executable. Anything this "
            "app exports can then be opened in it directly from the export: a "
            "file opens as a file, a folder opens as a workspace root so the "
            "tree is usable. Leaving it blank disables the handoff.",
            provenance=(
                "Stored separately from your preferences, in the external-editor record."
                if external_editor.load_selected()
                else "Not chosen yet — no external editor is configured."
            ),
        )
        self.external_editor_path = forms.MaterialTextField(
            editor_row.body,
            "Editor executable",
            external_editor.load_selected(),
            placeholder="Optional: path to code.cmd, code, or Code.exe",
            name="External editor executable",
        )
        self.external_editor_browse = studio.StudioButton(
            editor_row.body, "Browse…", variant="outlined", name="Browse for editor"
        )
        self.external_editor_test = studio.StudioButton(
            editor_row.body, "Check editor", variant="outlined", name="Check editor"
        )
        editor_row.set_control(self.external_editor_path)
        editor_row.add_extra(self.external_editor_browse)
        editor_row.add_extra(self.external_editor_test)
        self.external_editor_status = studio.StudioText(
            editor_row, "", size_px=12, name="External editor status"
        )
        editor_row.GetSizer().Add(self.external_editor_status, 0, wx.EXPAND | wx.TOP, 4)
        root.Add(editor_row, 0, wx.EXPAND | wx.BOTTOM, 18)

        auto_update_row = self._row(
            page,
            "Automatic update staging",
            "Downloads and validates a discovered update in the background, "
            "without a click, so restarting is the only thing you ever have "
            "to do. The banner then reads as staged and waiting rather than "
            "asking you to stage it. Restarting still always waits for your "
            "unsaved work, and the update stays unsigned either way. Turn "
            "this off to keep pressing Stage available update yourself.",
            key="auto_stage_updates",
            default=True,
        )
        self.auto_stage_updates = studio.StudioCheckBox(
            auto_update_row.body,
            "Automatically stage updates in the background",
            value=self._prefs.auto_stage_updates,
            name="Automatically stage updates in the background",
        )
        auto_update_row.set_control(self.auto_stage_updates, 0)
        root.Add(auto_update_row, 0, wx.EXPAND | wx.BOTTOM, 18)

        scale_row = self._row(
            page,
            "UI scale",
            "Scales text and controls together, between 80% and 200%. It is "
            "bounded on purpose: past those ends labels stop fitting the "
            "controls they name. The value persists across restarts.",
            key="ui_scale",
            default=100,
            unit="%",
        )
        self.scale = forms.MaterialSlider(
            scale_row.body,
            value=int(self._prefs.ui_scale * 100),
            minValue=80,
            maxValue=200,
            suffix="%",
            name="UI scale",
        )
        scale_row.set_control(self.scale)
        root.Add(scale_row, 0, wx.EXPAND | wx.BOTTOM, 18)

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
        self.appearance_preset_list = forms.MaterialChoice(
            page, [], label="Named appearance presets"
        )
        self.appearance_preset_name = forms.MaterialTextField(
            page,
            "Preset name",
            placeholder="Preset name",
            name="New appearance preset name",
        )
        preset_row.Add(self.appearance_preset_list, 1, wx.EXPAND | wx.RIGHT, 8)
        preset_row.Add(self.appearance_preset_name, 1, wx.EXPAND)
        root.Add(preset_row, 0, wx.EXPAND | wx.BOTTOM, 8)

        preset_search_row = wx.BoxSizer(wx.HORIZONTAL)
        self.appearance_preset_search = forms.MaterialTextField(
            page,
            "Search appearance presets",
            placeholder="Search appearance presets",
            name="Appearance preset search",
        )
        self.appearance_preset_regex = studio.StudioCheckBox(
            page, "Regex", name="Appearance preset regex mode"
        )
        self.appearance_preset_regex_button = studio.StudioButton(
            page,
            "Regex…",
            variant="outlined",
            hint="Build a bounded regular-expression preset search",
            name="Appearance preset regex builder",
        )
        preset_search_row.Add(self.appearance_preset_search, 1, wx.EXPAND | wx.RIGHT, 8)
        preset_search_row.Add(self.appearance_preset_regex, 0, wx.ALIGN_CENTER_VERTICAL)
        preset_search_row.Add(
            self.appearance_preset_regex_button,
            0,
            wx.LEFT | wx.ALIGN_CENTER_VERTICAL,
            6,
        )
        root.Add(preset_search_row, 0, wx.EXPAND | wx.BOTTOM, 8)

        preset_actions = wx.WrapSizer(wx.HORIZONTAL)
        self.appearance_preset_load = studio.StudioButton(
            page, "Load selected", variant="tonal", name="Load selected preset"
        )
        self.appearance_preset_save = studio.StudioButton(
            page, "Save preset", variant="tonal", name="Save preset"
        )
        self.appearance_preset_update = studio.StudioButton(
            page, "Update selected", variant="tonal", name="Update selected preset"
        )
        self.appearance_preset_export = studio.StudioButton(
            page, "Export selected…", variant="outlined", name="Export selected preset"
        )
        self.appearance_preset_open = studio.StudioButton(
            page,
            "Open export in VS Code",
            variant="outlined",
            name="Open export in VS Code",
        )
        self.appearance_preset_open.Enable(False)
        self.appearance_preset_import = studio.StudioButton(
            page, "Import preset…", variant="outlined", name="Import preset"
        )
        self.appearance_preset_delete = studio.StudioButton(
            page, "Delete selected", variant="danger", name="Delete selected preset"
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

        reset_row = wx.WrapSizer(wx.HORIZONTAL)
        self.appearance_reset_property = forms.MaterialChoice(
            page,
            ["Theme", "Density", "Accent colour", "UI font", "UI scale"],
            label="Appearance property to reset",
        )
        self.appearance_reset_property.SetSelection(0)
        self.appearance_reset_selected = studio.StudioButton(
            page,
            "Reset selected value",
            variant="outlined",
            name="Reset selected value",
        )
        self.appearance_reset_all = studio.StudioButton(
            page,
            "Reset all appearance",
            variant="outlined",
            name="Reset all appearance",
        )
        reset_row.Add(self.appearance_reset_property, 1, wx.EXPAND | wx.RIGHT, 8)
        reset_row.Add(self.appearance_reset_selected, 0, wx.RIGHT, 8)
        reset_row.Add(self.appearance_reset_all, 0)
        root.Add(reset_row, 0, wx.EXPAND | wx.TOP, 4)

        self.appearance_status = studio.StudioText(
            page, "", size_px=12, name="Appearance preset status"
        )
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
        outer.Add(root, 0, wx.EXPAND | wx.ALL, 20)
        page.SetSizer(outer)
        scroller.fit_content()
        self._appearance_page = scroller
        self._appearance_tab_index = self._tabs.GetPageCount()
        self._tabs.AddPage(scroller, "Appearance")
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
        self.identity_status.SetLabel(
            "The shipped name is staged. Choose OK to save it."
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
            self.external_editor_status.SetLabel(result.message)
            self.external_editor_status.SetForegroundColour(wx.Colour(180, 40, 40))
            return
        self.external_editor_path.SetValue(str(Path(value).resolve()))
        self.external_editor_status.SetLabel(
            "Editor path staged. Choose OK to save it."
        )
        self.external_editor_status.SetForegroundColour(wx.Colour(40, 120, 70))

    def _test_external_editor(self, _event: wx.Event) -> None:
        result = external_editor.validate_editor_path(
            self.external_editor_path.GetValue()
        )
        self.external_editor_status.SetLabel(result.message)
        self.external_editor_status.SetForegroundColour(
            wx.Colour(40, 120, 70) if result.ok else wx.Colour(180, 40, 40)
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
            sample="Installed font family",
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.font_search.ChangeValue(dialog.pattern)
            self.font_regex.SetValue(dialog.regex_enabled)
            self._font_search_flags = dialog.flags
        self._filter_appearance_fonts()

    def _open_preset_regex_builder(self, _event) -> None:
        with RegexBuilderDialog(
            self,
            pattern=self.appearance_preset_search.GetValue(),
            regex_enabled=self.appearance_preset_regex.GetValue(),
            flags=getattr(self, "_preset_search_flags", 0),
            sample="Appearance preset name",
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.appearance_preset_search.ChangeValue(dialog.pattern)
            self.appearance_preset_regex.SetValue(dialog.regex_enabled)
            self._preset_search_flags = dialog.flags
        self._refresh_appearance_presets()

    @staticmethod
    def _installed_font_names() -> Tuple[str, ...]:
        try:
            enumerator = wx.FontEnumerator()
            enumerator.EnumerateFacenames()
            return appearance_editor.filter_font_names(enumerator.GetFacenames(), "")
        except (AttributeError, RuntimeError):
            return ()

    def _filter_appearance_fonts(self, _event: wx.Event | None = None) -> None:
        source_names = getattr(self, "_appearance_font_names", ())
        query = (
            self.font_search.GetValue().strip() if hasattr(self, "font_search") else ""
        )
        if query and getattr(self, "font_regex", None) is not None:
            builder = RegexBuilder(
                query[:4096],
                regex_enabled=self.font_regex.GetValue(),
                flags=getattr(self, "_font_search_flags", 0),
            )
            try:
                names = tuple(name for name in source_names if builder.search([name]))
            except (ValueError, re.error) as exc:
                names = ()
                self.font_search.SetToolTip(f"Invalid font search: {exc}")
            else:
                self.font_search.SetToolTip(
                    "Regex font search"
                    if self.font_regex.GetValue()
                    else "Plain-text font search"
                )
        else:
            names = appearance_editor.filter_font_names(source_names, query)
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
            # A painted swatch carries its colour as a value it draws, not as a
            # native background the platform fills, so this is ``set_colour``
            # rather than ``SetBackgroundColour`` -- which a drawn control
            # accepts and then ignores, leaving the preview stuck on the old
            # colour while every other reading of it moved.
            self.accent_swatch.set_colour(wx.Colour(*rgb))
            self.accent_contrast.SetLabel(appearance_editor.contrast_summary(rgb))
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

    def _refresh_appearance_presets(self, selected_name: str = "") -> None:
        self._appearance_presets = list(appearance_presets.load_presets())
        query = self.appearance_preset_search.GetValue().strip()
        if query:
            builder = RegexBuilder(
                query[:4096],
                regex_enabled=self.appearance_preset_regex.GetValue(),
                flags=getattr(self, "_preset_search_flags", 0),
            )
            try:
                self._appearance_presets = [
                    preset
                    for preset in self._appearance_presets
                    if builder.search([preset.name])
                ]
            except (ValueError, re.error) as exc:
                self._show_appearance_message(
                    f"Invalid preset search: {exc}", error=True
                )
                self._appearance_presets = []
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
        """Build the scheduled-settings list, its editor, and its source controls.

        Every row here carries the same explanation-and-provenance treatment as
        the appearance page.  A schedule row is exactly the kind of setting
        where "did I set this, or is it just the shipped value?" is unanswerable
        from the value alone: a start time of ``00:00`` is both a plausible
        choice and the empty default.
        """
        scroller = forms.MaterialScrolled(self._tabs.host, name="Schedule settings")
        page = scroller.content
        root = wx.BoxSizer(wx.VERTICAL)

        explanation = studio.StudioText(
            page,
            self._schedule_text("explanation"),
            size_px=13,
            wrap_width=560,
            max_lines=8,
            name="Scheduled settings explanation",
        )
        root.Add(explanation, 0, wx.EXPAND | wx.BOTTOM, 10)

        self.schedule_list = forms.MaterialListBox(page, name="Schedule rules")
        self.schedule_list.SetMinSize(wx.Size(-1, 120))
        root.Add(self.schedule_list, 0, wx.EXPAND | wx.BOTTOM, 8)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.schedule_new = studio.StudioButton(
            page, self._schedule_text("add"), variant="tonal"
        )
        self.schedule_remove = studio.StudioButton(
            page, self._schedule_text("remove"), variant="danger"
        )
        self.schedule_up = studio.StudioButton(
            page, self._schedule_text("moveup"), variant="outlined"
        )
        self.schedule_down = studio.StudioButton(
            page, self._schedule_text("movedown"), variant="outlined"
        )
        actions.Add(self.schedule_new, 0, wx.RIGHT, 8)
        actions.Add(self.schedule_remove, 0, wx.RIGHT, 8)
        actions.Add(self.schedule_up, 0, wx.RIGHT, 8)
        actions.Add(self.schedule_down, 0)
        root.Add(actions, 0, wx.BOTTOM, 16)

        rows: List[forms.SettingRow] = []

        def add_row(key: str, control: wx.Window | None = None) -> forms.SettingRow:
            """Open one settings element; the control is built on its body."""
            row = self._row(
                page,
                self._schedule_text(key),
                self._schedule_text(f"{key}.help"),
                provenance=self._schedule_text("provenance"),
            )
            if control is not None:
                row.set_control(control)
            rows.append(row)
            root.Add(row, 0, wx.EXPAND | wx.BOTTOM, 14)
            return row

        enabled_row = add_row("enabled")
        self.schedule_enabled = studio.StudioCheckBox(
            enabled_row.body,
            self._schedule_text("enabled.value"),
            name=self._schedule_text("enabled"),
        )
        enabled_row.set_control(self.schedule_enabled, 0)

        label_row = add_row("label")
        self.schedule_label = forms.MaterialTextField(
            label_row.body, self._schedule_text("label"), name="Schedule rule label"
        )
        label_row.set_control(self.schedule_label)

        priority_row = add_row("priority")
        self.schedule_priority = forms.MaterialSpin(
            priority_row.body,
            min=-10000,
            max=10000,
            initial=0,
            name=self._schedule_text("priority"),
        )
        priority_row.set_control(self.schedule_priority, 0)

        source_row = add_row("source")
        self.schedule_source_kind = forms.MaterialChoice(
            source_row.body,
            [
                self._schedule_text("source.local"),
                self._schedule_text("source.api"),
                self._schedule_text("source.homeassistant"),
            ],
            label="Scheduled source kind",
        )
        source_row.set_control(self.schedule_source_kind, 0)

        url_row = add_row("sourceurl")
        self.schedule_source_url = forms.MaterialTextField(
            url_row.body,
            self._schedule_text("sourceurl"),
            placeholder=self._schedule_text("source.url.hint"),
            name="Scheduled source URL",
        )
        url_row.set_control(self.schedule_source_url)

        entity_row = add_row("sourceentity")
        self.schedule_source_entity = forms.MaterialTextField(
            entity_row.body,
            self._schedule_text("sourceentity"),
            placeholder=self._schedule_text("source.entity.hint"),
            name="Home Assistant entity",
        )
        entity_row.set_control(self.schedule_source_entity)

        refresh_row = add_row("sourcerefresh")
        self.schedule_source_refresh = forms.MaterialSpin(
            refresh_row.body,
            min=30,
            max=86400,
            initial=300,
            suffix="s",
            name="Scheduled source refresh seconds",
        )
        refresh_row.set_control(self.schedule_source_refresh, 0)

        weekday_row = add_row("weekdays")
        weekday_panel = wx.Panel(weekday_row.body)
        weekday_sizer = wx.WrapSizer(wx.HORIZONTAL)
        self.schedule_every_day = studio.StudioCheckBox(
            weekday_panel, self._schedule_text("everyday"), name="Every day"
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
            label = self._schedule_text(f"weekday.{name}")
            checkbox = studio.StudioCheckBox(weekday_panel, label, name=label)
            self.schedule_weekdays.append(checkbox)
            weekday_sizer.Add(checkbox, 0, wx.RIGHT | wx.BOTTOM, 6)
        weekday_panel.SetSizer(weekday_sizer)
        weekday_row.set_control(weekday_panel)

        # The date and time fields are the one control on this page that keeps
        # a native picker inside it. It belongs to ``ui.simple`` rather than to
        # this surface, and swapping it here would leave two different date
        # controls in the product; it is named in this file's handoff instead
        # of being half-migrated.
        start_date_row = add_row("startdate")
        self.schedule_start_date = MaterialDateTimeField(start_date_row.body, "date")
        start_date_row.set_control(self.schedule_start_date)
        end_date_row = add_row("enddate")
        self.schedule_end_date = MaterialDateTimeField(end_date_row.body, "date")
        end_date_row.set_control(self.schedule_end_date)
        start_time_row = add_row("starttime")
        self.schedule_start_time = MaterialDateTimeField(start_time_row.body, "time")
        start_time_row.set_control(self.schedule_start_time)
        end_time_row = add_row("endtime")
        self.schedule_end_time = MaterialDateTimeField(end_time_row.body, "time")
        end_time_row.set_control(self.schedule_end_time)

        no_override = self._schedule_text("nooverride")
        language_row = add_row("language")
        self.schedule_language = forms.MaterialChoice(
            language_row.body,
            [
                no_override,
                self._schedule_text("language.english"),
                self._schedule_text("language.cantonese"),
                self._schedule_text("language.bilingual"),
            ],
            label=self._schedule_text("language"),
        )
        language_row.set_control(self.schedule_language, 0)

        theme_row = add_row("theme")
        self.schedule_theme = forms.MaterialChoice(
            theme_row.body,
            [
                no_override,
                self._schedule_text("theme.light"),
                self._schedule_text("theme.dark"),
                self._schedule_text("theme.system"),
            ],
            label=self._schedule_text("theme"),
        )
        theme_row.set_control(self.schedule_theme, 0)

        density_row = add_row("density")
        self.schedule_density = forms.MaterialChoice(
            density_row.body,
            [
                no_override,
                self._schedule_text("density.compact"),
                self._schedule_text("density.comfortable"),
                self._schedule_text("density.spacious"),
            ],
            label=self._schedule_text("density"),
        )
        density_row.set_control(self.schedule_density, 0)

        accent_row = add_row("accent")
        self.schedule_accent = forms.MaterialTextField(
            accent_row.body,
            self._schedule_text("accent"),
            placeholder=self._schedule_text("accent.hint"),
            mono=True,
            name="Scheduled accent colour",
        )
        accent_row.set_control(self.schedule_accent)

        self.schedule_apply = studio.StudioButton(
            page, self._schedule_text("apply"), variant="filled"
        )
        root.Add(self.schedule_apply, 0, wx.BOTTOM, 8)
        self.schedule_validation = studio.StudioText(
            page, "", size_px=12, wrap_width=560, name="Schedule validation"
        )
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
        outer.Add(root, 0, wx.EXPAND | wx.ALL, 20)
        page.SetSizer(outer)
        scroller.fit_content()
        self._schedule_page = scroller
        self._schedule_tab_index = self._tabs.GetPageCount()
        self._tabs.AddPage(scroller, self._schedule_text("tab"))
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
        """Build the settings search field and its anchored regex builder."""
        page = wx.Panel(self._tabs.host)
        box = wx.BoxSizer(wx.VERTICAL)
        search_row = self._row(
            page,
            "Search settings",
            "Searches the settings on every tab of this window by name, "
            "description, and current value, and says plainly when a match "
            "sits on a tab you are not looking at. Plain text is the default; "
            "the builder beside the field composes a bounded regular "
            "expression when you need groups or quantifiers.",
            provenance="A search field; nothing about it is stored.",
        )
        self.regex = forms.MaterialTextField(
            search_row.body,
            "Search settings, tabs, or commands",
            placeholder="Search settings, tabs, or commands",
            name="Preferences settings search",
        )
        self.regex_mode = studio.StudioCheckBox(
            search_row.body, "Regex", name="Preferences search regex mode"
        )
        self.regex_flags = studio.StudioCheckBox(
            search_row.body,
            "Ignore case",
            # On by default, because every other search field in this product
            # defaults to ignore-case -- the shared SearchState ships with the
            # ``i`` flag set -- and a settings search that answers "no setting
            # matches 'density'" while a setting called Density is two rows up
            # reads as a broken search rather than as a case-sensitive one.
            value=True,
            name="Preferences search ignore case",
        )
        self.regex_button = studio.StudioButton(
            search_row.body,
            label="Regex…",
            variant="outlined",
            hint="Build a bounded regular-expression search",
            name="Preferences search regex builder",
        )
        search_row.set_control(self.regex)
        search_row.add_extra(self.regex_mode)
        search_row.add_extra(self.regex_flags)
        search_row.add_extra(self.regex_button)
        box.Add(search_row, 0, wx.EXPAND | wx.BOTTOM, 12)
        self.regex_result = studio.StudioText(
            page,
            "Type to validate a pattern.",
            size_px=12,
            wrap_width=560,
            name="Preferences search validation",
        )
        box.Add(self.regex_result, 0, wx.BOTTOM, 8)
        self.settings_matches = studio.StudioText(
            page,
            "",
            size_px=12,
            wrap_width=560,
            max_lines=24,
            name="Settings search results",
        )
        box.Add(self.settings_matches, 0, wx.EXPAND)
        self.regex.Bind(wx.EVT_TEXT, self._validate_regex)
        self.regex_mode.Bind(wx.EVT_CHECKBOX, self._validate_regex)
        self.regex_flags.Bind(wx.EVT_CHECKBOX, self._validate_regex)
        self.regex_button.Bind(wx.EVT_BUTTON, self._open_search_regex_builder)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(box, 1, wx.EXPAND | wx.ALL, 20)
        page.SetSizer(outer)
        self._search_page = page
        self._tabs.AddPage(page, "Search")
        # Populate on open rather than on the first keystroke. A results area
        # that is blank until typed into reads as a feature that does nothing;
        # it should say how many settings there are to search.
        self._refresh_settings_matches()

    def _settings_index(self) -> List[Tuple[str, str]]:
        """Return every searchable settings element as ``(tab, label)``.

        The list is hand-written against the rows this dialog builds rather
        than discovered by walking the window.  A walk would answer a rule like
        "every setting is searchable" on a page that had lost half its rows,
        because it can only find what is there; a written list fails when a row
        goes missing, which is the case worth catching.
        """
        return [
            ("Language", "Language mode"),
            ("Language", "English funny level"),
            ("Language", "Cantonese funny level"),
            ("Language", "Dialog emojis"),
            ("Language", "Display-text overlay"),
            ("Appearance", "App display name"),
            ("Appearance", "School mode"),
            ("Appearance", "Unlock credential"),
            ("Appearance", "Theme"),
            ("Appearance", "Density"),
            ("Appearance", "Accent colour"),
            ("Appearance", "Colour translator"),
            ("Appearance", "UI font"),
            ("Appearance", "Installed font search"),
            ("Appearance", "External editor"),
            ("Appearance", "UI scale"),
            ("Appearance", "Named appearance presets"),
            (self._schedule_text("tab"), self._schedule_text("enabled")),
            (self._schedule_text("tab"), self._schedule_text("label")),
            (self._schedule_text("tab"), self._schedule_text("priority")),
            (self._schedule_text("tab"), self._schedule_text("source")),
            (self._schedule_text("tab"), self._schedule_text("weekdays")),
            (self._schedule_text("tab"), self._schedule_text("startdate")),
            (self._schedule_text("tab"), self._schedule_text("starttime")),
            (self._schedule_text("tab"), self._schedule_text("language")),
            (self._schedule_text("tab"), self._schedule_text("theme")),
            (self._schedule_text("tab"), self._schedule_text("density")),
            (self._schedule_text("tab"), self._schedule_text("accent")),
            ("Search", "Search settings"),
        ]

    def _refresh_settings_matches(self) -> None:
        """Report which settings match, naming the tab each one lives on."""
        index = self._settings_index()
        query = self.regex.GetValue()[:4096].strip()
        if not query:
            self.settings_matches.SetLabel(
                f"{len(index)} settings on {len(set(tab for tab, _ in index))} tabs. "
                "Type to narrow them."
            )
            return
        builder = RegexBuilder(
            query,
            0x02 if self.regex_flags.GetValue() else 0,
            self.regex_mode.GetValue(),
        )
        try:
            matches = builder.search([label for _tab, label in index])
        except (re.error, ValueError) as exc:
            self.settings_matches.SetLabel(f"No results: {exc}")
            return
        found = [(tab, label) for tab, label in index if label in matches]
        if not found:
            self.settings_matches.SetLabel(
                f"No setting matches {query!r}. {len(index)} were searched."
            )
            return
        # Saying which tab a match sits on is the point: a result the user
        # cannot navigate to is a result that has not helped them.
        lines = "\n".join(f"{label} — on the {tab} tab" for tab, label in found)
        self.settings_matches.SetLabel(
            f"{len(found)} of {len(index)} settings:\n{lines}"
        )

    def _open_search_regex_builder(self, _event: wx.Event) -> None:
        with RegexBuilderDialog(
            self,
            pattern=self.regex.GetValue(),
            regex_enabled=self.regex_mode.GetValue(),
            flags=0x02 if self.regex_flags.GetValue() else 0,
            sample="settings, tabs, or commands",
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.regex.ChangeValue(dialog.pattern)
            self.regex_mode.SetValue(dialog.regex_enabled)
            self.regex_flags.SetValue(bool(dialog.flags & 0x02))
        self._validate_regex(None)

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
        self._refresh_settings_matches()

    def _reset(self, _event: wx.Event) -> None:
        self._prefs = preferences.reset()
        parent = self.GetParent()
        if hasattr(parent, "refresh_display_identity"):
            parent.refresh_display_identity(self._prefs.display_name)
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
            self.identity_status.SetLabel(str(exc))
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
                self.external_editor_status.SetLabel(editor_result.message)
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
                auto_stage_updates=self.auto_stage_updates.GetValue(),
            )
        )

        # Settings are user-managed records too, so a preference change is
        # recorded like any other edit and can be restored. This call belongs
        # here, where `saved_preferences` is in scope: it had been pasted into
        # the changelog viewer's refresh, which raised NameError every time that
        # window opened AND left preference changes with no history at all --
        # one misplaced block breaking two things that look unrelated.
        # A history failure must never block the preference change itself, which
        # is what safe_record guarantees.
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

        # apply_material3 restyles native controls, and the Studio shell opts
        # out of that traversal on purpose because it paints itself. Without
        # telling it, saving preferences moved zero owner-drawn widgets:
        # language, theme, density and accent were stored values that only took
        # effect on the next launch. A setting the user changed and cannot see
        # change reads as a setting that does not work.
        try:
            from amulet_map_editor.api.studio import tokens as studio_tokens

            studio_tokens.notify_theme_changed()
        except Exception:
            # The Studio layer is optional for a headless or partial install;
            # the native restyle above still applies.
            log.debug("Could not notify the Studio theme listeners", exc_info=True)

        studio = getattr(parent, "_studio", None)
        refresh = getattr(studio, "refresh_theme", None)
        if callable(refresh):
            try:
                refresh()
            except RuntimeError:
                log.debug("The Studio shell was closing during a refresh")

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
        forms.make_frameless(self)
        root = wx.BoxSizer(wx.VERTICAL)
        self.title_bar = forms.MaterialDialogTitleBar(
            self, _chrome_copy("command_palette_title", self._language_mode)
        )
        root.Add(self.title_bar, 0, wx.EXPAND)
        self.query = forms.MaterialTextField(
            self,
            _chrome_copy("command_palette_search", self._language_mode),
            placeholder=_chrome_copy("command_palette_search", self._language_mode),
            process_enter=True,
            name="Command palette search",
        )
        self.regex = studio.StudioCheckBox(
            self,
            _chrome_copy("regex", self._language_mode),
            name="Command palette regex mode",
        )
        self.regex_button = studio.StudioButton(
            self,
            label="Regex…",
            variant="outlined",
            hint="Build a bounded regular-expression search",
            name="Command palette regex builder",
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.query, 1, wx.EXPAND | wx.RIGHT, 8)
        row.Add(self.regex, 0, wx.ALIGN_CENTER_VERTICAL)
        row.Add(self.regex_button, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 6)
        root.Add(row, 0, wx.EXPAND | wx.ALL, 12)
        self.results = forms.MaterialListBox(self, name="Command palette results")
        root.Add(self.results, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(root)
        self._refresh()
        self.query.Bind(wx.EVT_TEXT, lambda evt: self._refresh())
        self.regex.Bind(wx.EVT_CHECKBOX, lambda evt: self._refresh())
        self.regex_button.Bind(wx.EVT_BUTTON, self._open_regex_builder)
        self.query.Bind(wx.EVT_TEXT_ENTER, self._run)
        self.results.Bind(wx.EVT_LISTBOX_DCLICK, self._run)
        self.results.Bind(wx.EVT_KEY_DOWN, self._on_result_key)
        self._material3_dialog_chrome = True
        apply_material3(self)
        self.title_bar.refresh_theme()

    def _open_regex_builder(self, _event) -> None:
        with RegexBuilderDialog(
            self,
            pattern=self.query.GetValue(),
            regex_enabled=self.regex.GetValue(),
            flags=self._search_flags,
            sample="Command, feature, or setting name",
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.query.ChangeValue(dialog.pattern)
            self.regex.SetValue(dialog.regex_enabled)
            self._search_flags = dialog.flags
        self._refresh()

    def _refresh(self) -> None:
        builder = RegexBuilder(
            self.query.GetValue()[:4096],
            regex_enabled=self.regex.GetValue(),
            flags=self._search_flags,
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

    def _on_result_key(self, event: wx.KeyEvent) -> None:
        """Keep palette result navigation explicit and screen-reader friendly.

        The painted list has its own arrow handling, but this stays: it is what
        the palette guarantees regardless of which list is underneath, and it
        keeps Enter running the highlighted command rather than closing the
        dialog through the default button.
        """
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
        forms.make_frameless(self)
        root = wx.BoxSizer(wx.VERTICAL)
        self.title_bar = forms.MaterialDialogTitleBar(
            self,
            _chrome_copy("changelog_title", self._language_mode),
            maximise=True,
        )
        root.Add(self.title_bar, 0, wx.EXPAND)
        # A stacked filter row rather than a label/control grid. Each Material
        # field carries its own floating label, so a separate caption column
        # says everything twice -- and a grid whose left column holds 20-pixel
        # captions beside 55-pixel fields cannot align either of them, which is
        # what left "Action" stranded halfway up its own row.
        filters = wx.BoxSizer(wx.VERTICAL)
        self.query = forms.MaterialTextField(
            self,
            _chrome_copy("changelog_search_label", self._language_mode),
            placeholder=_chrome_copy("changelog_search_hint", self._language_mode),
            name="Changelog search",
        )
        filters.Add(self.query, 0, wx.EXPAND | wx.BOTTOM, 10)

        dates = wx.BoxSizer(wx.HORIZONTAL)
        self.start_date = forms.MaterialTextField(
            self,
            _chrome_copy("changelog_start_date", self._language_mode),
            placeholder="YYYY-MM-DD",
            name="Changelog start date",
        )
        # The calendar itself stays native. wx.adv.DatePickerCtrl carries the
        # month and year jump, the keyboard model, and the locale's own date
        # parsing that this project's changelog contract requires, and a hand
        # drawn calendar would have to reproduce all of it. It is the one
        # control left on this surface that is the platform's, and it is named
        # here rather than left for somebody to find.
        self.start_picker = wx.adv.DatePickerCtrl(
            self, style=wx.adv.DP_DROPDOWN | wx.adv.DP_ALLOWNONE
        )
        self.start_picker.SetName("Changelog start date calendar")
        self.start_picker.SetValue(wx.DateTime())
        self.end_date = forms.MaterialTextField(
            self,
            _chrome_copy("changelog_end_date", self._language_mode),
            placeholder="YYYY-MM-DD",
            name="Changelog end date",
        )
        self.end_picker = wx.adv.DatePickerCtrl(
            self, style=wx.adv.DP_DROPDOWN | wx.adv.DP_ALLOWNONE
        )
        self.end_picker.SetName("Changelog end date calendar")
        self.end_picker.SetValue(wx.DateTime())
        dates.Add(self.start_date, 1, wx.EXPAND | wx.RIGHT, 6)
        dates.Add(self.start_picker, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        dates.Add(self.end_date, 1, wx.EXPAND | wx.RIGHT, 6)
        dates.Add(self.end_picker, 0, wx.ALIGN_CENTER_VERTICAL)
        filters.Add(dates, 0, wx.EXPAND | wx.BOTTOM, 10)

        action_values = [
            _chrome_copy("changelog_all_actions", self._language_mode),
            *(
                name
                for name, _count in changelog.available_actions(self._catalog.entries)
            ),
        ]
        self.action = forms.MaterialChoice(
            self,
            action_values,
            label=_chrome_copy("changelog_action", self._language_mode),
        )
        self.action.SetSelection(0)
        self.regex = studio.StudioCheckBox(
            self,
            _chrome_copy("regex", self._language_mode),
            name="Changelog regex mode",
        )
        self.regex_button = studio.StudioButton(
            self,
            label="Regex…",
            variant="outlined",
            hint="Build a bounded regular-expression search",
            name="Changelog search regex builder",
        )
        controls = wx.BoxSizer(wx.HORIZONTAL)
        controls.Add(self.action, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        controls.Add(self.regex, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        controls.Add(self.regex_button, 0, wx.ALIGN_CENTER_VERTICAL)
        filters.Add(controls, 0, wx.EXPAND | wx.BOTTOM, 8)

        self.feedback = studio.StudioText(
            self, "", size_px=12, wrap_width=560, name="Changelog feedback"
        )
        filters.Add(self.feedback, 0, wx.EXPAND)
        root.Add(filters, 0, wx.EXPAND | wx.ALL, 12)
        self.results = forms.MaterialListBox(self, name="Changelog entries")
        self.results.SetMinSize(wx.Size(-1, 260))
        root.Add(self.results, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        export = studio.StudioButton(
            self,
            _chrome_copy("changelog_export", self._language_mode),
            variant="tonal",
        )
        export.Bind(wx.EVT_BUTTON, self._export)
        actions.Add(export, 0, wx.RIGHT, 8)
        self.open_export = studio.StudioButton(
            self,
            _chrome_copy("open_export", self._language_mode),
            variant="outlined",
        )
        self.open_export.Enable(False)
        self.open_export.Bind(wx.EVT_BUTTON, self._open_export)
        actions.Add(self.open_export, 0, wx.RIGHT, 8)
        copy = studio.StudioButton(
            self,
            _chrome_copy("changelog_copy", self._language_mode),
            variant="outlined",
        )
        copy.Bind(wx.EVT_BUTTON, self._copy)
        actions.Add(copy, 0, wx.RIGHT, 8)
        close = studio.StudioButton(
            self, _chrome_copy("close", self._language_mode), variant="filled"
        )
        close.SetId(wx.ID_CLOSE)
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
        self._material3_dialog_chrome = True
        apply_material3(self)
        self.title_bar.refresh_theme()

    def _open_regex_builder(self, _event) -> None:
        with RegexBuilderDialog(
            self,
            pattern=self.query.GetValue(),
            regex_enabled=self.regex.GetValue(),
            flags=self._search_flags,
            sample="Version, release note, or commit SHA",
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
            matcher = lambda value: bool(builder.search([value]))
        return changelog.filter_changelog(self._catalog, query, text_matcher=matcher)

    def _refresh(self) -> None:
        try:
            filtered = self._filtered()
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
        except (ValueError, changelog.ChangelogValidationError, re.error) as exc:
            self.feedback.SetLabel(f"Invalid filter: {exc}")
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
        except (ValueError, changelog.ChangelogValidationError, re.error) as exc:
            self.feedback.SetLabel(f"Invalid filter: {exc}")
            return
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(payload))
            finally:
                wx.TheClipboard.Close()
            self.feedback.SetLabel("Copied filtered changelog to the clipboard")
        else:
            self.feedback.SetLabel("Could not open the clipboard")
