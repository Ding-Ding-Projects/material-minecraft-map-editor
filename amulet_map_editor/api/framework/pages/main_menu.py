"""The legacy start page, kept as a thin shim in front of the backstage.

Amulet Studio's backstage is the start screen now: it owns the template
gallery, the searchable recent table, project information, conversion, the
surface index, and the update state.  This page stays for one reason -- it is
still the world notebook's first tab, so the notebook keeps a page when no
world is open, the tab manager keeps something to manage, and a build whose
Studio shell could not be created still starts somewhere usable.

Everything a user does here is therefore handed to the backstage when one
exists: opening a project switches to its Open destination, and selecting this
tab shows the project screen rather than this card.  The card itself is the
fallback for the no-Studio case, which is also the only case in which it is
ever visible.
"""

import webbrowser
import logging

import wx
import wx.adv

from amulet_map_editor.api import image, lang, preferences
from amulet_map_editor.api.wx.components import MaterialButton, MaterialCard
from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.api.wx.modeless import show_modeless_dialog
from amulet_map_editor.api.wx.ui.documentation import DocumentationDialog
from .base_page import BasePageUI
from amulet_map_editor.api.wx.ui.select_world import open_level_from_dialog
from ._legal import LicenceDialog

log = logging.getLogger(__name__)


class AmuletMainMenu(wx.Panel, BasePageUI):
    def __init__(self, parent: wx.Window):
        super().__init__(parent)

        root_sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(root_sizer)
        root_sizer.AddStretchSpacer(1)

        self._start_card = MaterialCard(self, name="Get started card")
        self._start_card.SetMinSize(wx.Size(520, -1))
        card_sizer = wx.BoxSizer(wx.VERTICAL)
        self._start_card.SetSizer(card_sizer)
        root_sizer.Add(
            self._start_card,
            0,
            wx.ALIGN_CENTER_HORIZONTAL | wx.LEFT | wx.RIGHT,
            24,
        )

        hero = wx.BoxSizer(wx.HORIZONTAL)
        card_sizer.Add(hero, 0, wx.ALL | wx.EXPAND, 28)
        icon = wx.StaticBitmap(
            self._start_card,
            wx.ID_ANY,
            image.logo.amulet_logo.bitmap(64, 64),
            (0, 0),
            (64, 64),
        )
        hero.Add(icon, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 18)
        hero_copy = wx.BoxSizer(wx.VERTICAL)
        hero.Add(hero_copy, 1, wx.ALIGN_CENTER_VERTICAL)
        self._amulet_name = wx.StaticText(
            self._start_card, name="Main menu title heading"
        )
        hero_copy.Add(self._amulet_name, 0, wx.BOTTOM | wx.EXPAND, 6)
        self._hero_subtitle = wx.StaticText(
            self._start_card, name="Main menu supporting text"
        )
        hero_copy.Add(self._hero_subtitle, 0, wx.EXPAND)

        actions = wx.BoxSizer(wx.VERTICAL)
        card_sizer.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 28)
        self._open_world_button = MaterialButton(
            self._start_card, "", variant="filled", name="Open world"
        )
        self._open_world_button.Bind(wx.EVT_BUTTON, self._open_world)
        actions.Add(self._open_world_button, 0, wx.BOTTOM | wx.EXPAND, 10)

        self._user_manual_button = MaterialButton(
            self._start_card, "", variant="tonal", name="Offline user manual"
        )
        self._user_manual_button.Bind(wx.EVT_BUTTON, self._documentation)
        actions.Add(self._user_manual_button, 0, wx.BOTTOM | wx.EXPAND, 16)

        community_actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(community_actions, 0, wx.EXPAND)
        self._bug_tracker_button = MaterialButton(
            self._start_card, "", variant="outlined", name="Bug tracker"
        )
        self._bug_tracker_button.Bind(wx.EVT_BUTTON, self._bugs)
        community_actions.Add(self._bug_tracker_button, 1, wx.RIGHT | wx.EXPAND, 6)

        self._discord_button = MaterialButton(
            self._start_card, "", variant="outlined", name="Community"
        )
        self._discord_button.Bind(wx.EVT_BUTTON, self._discord)
        community_actions.Add(self._discord_button, 1, wx.LEFT | wx.EXPAND, 6)

        card_sizer.Add(
            wx.StaticLine(self._start_card), 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 28
        )
        utility_actions = wx.BoxSizer(wx.HORIZONTAL)
        card_sizer.Add(utility_actions, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 18)
        self._lang_button = MaterialButton(
            self._start_card, "", variant="text", name="Choose language"
        )
        self._lang_button.Bind(wx.EVT_BUTTON, self._select_language)
        utility_actions.Add(self._lang_button, 0, wx.RIGHT, 8)
        self._licence_button = MaterialButton(
            self._start_card, "", variant="text", name="Third-party licenses"
        )
        self._licence_button.Bind(wx.EVT_BUTTON, self._show_licences)
        utility_actions.Add(self._licence_button, 0, wx.LEFT, 8)

        root_sizer.AddStretchSpacer(1)

        self._load_strings()
        apply_material3(self)

    def refresh_display_identity(self) -> None:
        """Refresh the already-created heading from persisted preferences."""
        self._amulet_name.SetLabel(preferences.load().display_name)
        self._start_card.Layout()
        self.Layout()

    def _load_strings(self):
        self.refresh_display_identity()
        self._hero_subtitle.SetLabel(lang.get("main_menu.hero_subtitle"))
        self._hero_subtitle.Wrap(400)
        self._open_world_button.SetLabel(lang.get("main_menu.open_world"))
        self._open_world_button.SetToolTip(
            lang.get("main_menu.open_world_backup_tooltip")
        )
        self._user_manual_button.SetLabel(lang.get("main_menu.user_manual"))
        self._user_manual_button.SetToolTip(lang.get("app.browser_open_tooltip"))
        self._bug_tracker_button.SetLabel(lang.get("main_menu.bug_tracker"))
        self._bug_tracker_button.SetToolTip(lang.get("app.browser_open_tooltip"))
        self._discord_button.SetLabel(lang.get("main_menu.discord"))
        self._discord_button.SetToolTip(lang.get("app.browser_open_tooltip"))
        self._lang_button.SetLabel(lang.get("language_select.title"))
        self._licence_button.SetLabel(lang.get("main_menu.licence_title"))
        self._licence_button.SetToolTip(lang.get("main_menu.licence_tooltip"))
        self.Layout()

    def _documentation(self, _event):
        # Keep the user manual available offline and inside the app's own M3 UI.
        show_modeless_dialog(self, "documentation", DocumentationDialog)

    @staticmethod
    def _bugs(_):
        webbrowser.open(
            "https://github.com/Amulet-Team/Amulet-Map-Editor/issues?q=is%3Aissue"
        )

    @staticmethod
    def _discord(_):
        webbrowser.open("https://www.amuletmc.com/discord")

    def _studio_shell(self):
        """Return the Studio shell hosting this frame, or ``None``.

        Read from the frame on each call rather than cached: this page is
        constructed before the shell is, so a value captured at build time would
        be ``None`` forever and the shim would keep ignoring a backstage that
        exists by the time anybody presses anything.
        """
        return getattr(self.GetTopLevelParent(), "_studio", None)

    def _show_backstage(self, tab: str = "home") -> bool:
        """Show a backstage destination, reporting whether one was there."""
        shell = self._studio_shell()
        if shell is None:
            return False
        shell.show_backstage(tab)
        return True

    def _open_world(self, _event) -> None:
        """Open a world through the backstage, or through the picker directly."""
        if self._show_backstage("open"):
            return
        open_level_from_dialog(self)

    def enable(self):
        self.GetTopLevelParent().create_menu()
        # Selecting this tab means "no world is in front of me", which is what
        # the backstage exists to answer. The card below is only ever shown by
        # a build with no Studio shell.
        self._show_backstage("home")

    def _select_language(self, evt):
        with LangSelectDialog(self) as dialog:
            dialog.CentreOnScreen()
            log.debug(f"Showing LangSelectDialog at {dialog.GetRect()}")
            if dialog.ShowModal() == wx.ID_OK:
                lang.set_language(dialog.get_language())
        self._load_strings()
        parent = self.GetTopLevelParent()
        if hasattr(parent, "refresh_display_identity"):
            parent.refresh_display_identity()

    def _show_licences(self, evt) -> None:
        show_modeless_dialog(self, "third-party-licences", LicenceDialog)


class LangSelectDialog(wx.Dialog):
    def __init__(self, *args, **kwds):
        # begin wxGlade: LangSelectDialog.__init__
        # Start borderless so the shared Material 3 title bar is the first
        # painted chrome instead of the platform caption.
        kwds["style"] = kwds.get("style", 0) | wx.NO_BORDER | wx.RESIZE_BORDER
        wx.Dialog.__init__(self, *args, **kwds)
        self.SetTitle(lang.get("language_select.title"))

        sizer_1 = wx.BoxSizer(wx.VERTICAL)

        self._label = wx.StaticText(
            self,
            label=preferences.resolve_display_name(lang.get("language_select.help")),
        )
        sizer_1.Add(self._label, 0, wx.ALIGN_CENTER)

        self.hyperlink_1 = wx.adv.HyperlinkCtrl(
            self,
            wx.ID_ANY,
            lang.get("language_select.contribute"),
            "https://github.com/Amulet-Team/Amulet-Map-Editor#contributing",
        )
        sizer_1.Add(self.hyperlink_1, 0, wx.ALIGN_CENTER)

        self._lang_list_box = wx.ListBox(self, choices=lang.get_languages())
        self._lang_list_box.SetSelection(
            self._lang_list_box.FindString(lang.get_language())
        )
        sizer_1.Add(self._lang_list_box, 1, wx.EXPAND, 0)

        sizer_2 = wx.StdDialogButtonSizer()
        sizer_1.Add(sizer_2, 0, wx.ALIGN_RIGHT | wx.ALL, 4)

        self._button_ok = wx.Button(self, wx.ID_OK, lang.get("language_select.ok"))
        self._button_ok.SetDefault()
        sizer_2.AddButton(self._button_ok)

        self._button_cancel = wx.Button(
            self, wx.ID_CANCEL, lang.get("language_select.cancel")
        )
        sizer_2.AddButton(self._button_cancel)

        sizer_2.Realize()

        self.SetSizer(sizer_1)
        sizer_1.Fit(self)

        self.SetAffirmativeId(self._button_ok.GetId())
        self.SetEscapeId(self._button_cancel.GetId())

        self.Layout()
        apply_material3(self)

    def get_language(self):
        return self._lang_list_box.GetStringSelection()
