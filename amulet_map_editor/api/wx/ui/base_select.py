import wx
from wx.lib import newevent
import re
from typing import Tuple, List, Optional

import PyMCTranslate

from amulet_map_editor.api.image import COLOUR_PICKER
from amulet_map_editor.api import lang, preferences
from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.api.regex_builder import RegexBuilder, plain_text_match_indices
from amulet_map_editor.api.wx.ui.regex_dialog import RegexBuilderDialog


def _copy(key: str, mode: str) -> str:
    english = lang.get(f"base_select.en.{key}")
    cantonese = lang.get(f"base_select.zh.{key}")
    if mode == "cantonese":
        return cantonese
    if mode == "bilingual":
        return f"{english} · {cantonese}"
    return english


(
    ItemNamespaceChangeEvent,
    EVT_ITEM_NAMESPACE_CHANGE,
) = newevent.NewCommandEvent()  # the namespace entry changed
(
    ItemNameChangeEvent,
    EVT_ITEM_NAME_CHANGE,
) = newevent.NewCommandEvent()  # the name entry changed
(
    ItemChangeEvent,
    EVT_ITEM_CHANGE,
) = (
    newevent.NewCommandEvent()
)  # the name or namespace changed. Generated after EVT_ITEM_NAME_CHANGE
(
    PickEvent,
    EVT_PICK,
) = newevent.NewCommandEvent()  # The pick button was pressed


class BaseSelect(wx.Panel):
    TypeName = "?"

    def __init__(
        self,
        parent: wx.Window,
        translation_manager: PyMCTranslate.TranslationManager,
        platform: str,
        version_number: Tuple[int, int, int],
        force_blockstate: bool = None,
        namespace: str = None,
        default_name: str = None,
        show_pick: bool = False,
    ):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self._language_mode = preferences.load().language_mode
        self._sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self._sizer)

        self._translation_manager = translation_manager

        self._platform: Optional[str] = None
        self._version_number: Optional[Tuple[int, int, int]] = None
        self._force_blockstate: Optional[bool] = force_blockstate

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._sizer.Add(sizer, 0, wx.EXPAND | wx.ALL, 5)
        text = wx.StaticText(
            self,
            label=_copy("namespace", self._language_mode),
            style=wx.ALIGN_CENTER,
        )
        sizer.Add(text, 1, wx.ALIGN_CENTER_VERTICAL)
        self._namespace_combo = wx.ComboBox(self)
        sizer.Add(self._namespace_combo, 2)
        self._set_version((platform, version_number, force_blockstate or False))
        self._populate_namespace()
        self.set_namespace(namespace)

        self._namespace_combo.Bind(
            wx.EVT_TEXT, lambda evt: self._post_namespace_change()
        )
        self._do_text_event = (
            True  # some widgets create events. This is used to suppress them
        )

        self.Bind(EVT_ITEM_NAMESPACE_CHANGE, self._on_namespace_change)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self._sizer.Add(sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        header_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(header_sizer, 0, wx.EXPAND | wx.BOTTOM, 5)
        header_sizer.Add(
            wx.StaticText(
                self,
                label=_copy("name", self._language_mode).format(
                    type_name=self.TypeName.capitalize()
                ),
                style=wx.ALIGN_CENTER,
            ),
            1,
            wx.ALIGN_CENTER_VERTICAL,
        )
        search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        header_sizer.Add(search_sizer, 2, wx.EXPAND)
        self._search = wx.SearchCtrl(self)
        self._search.SetHint(_copy("search", self._language_mode))
        search_sizer.Add(self._search, 1, wx.ALIGN_CENTER_VERTICAL)
        self._regex_button = wx.Button(self, label=_copy("regex", self._language_mode))
        self._regex_button.SetToolTip(_copy("regex.help", self._language_mode))
        search_sizer.Add(self._regex_button, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 6)
        self._search_regex_enabled = False
        self._search_flags = 0
        self._regex_button.Bind(wx.EVT_BUTTON, self._open_regex_builder)
        self._search.Bind(wx.EVT_TEXT, self._on_search_change)
        if show_pick:
            pick_button = wx.BitmapButton(self, bitmap=COLOUR_PICKER.bitmap(22, 22))
            search_sizer.Add(pick_button, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 5)
            pick_button.Bind(
                wx.EVT_BUTTON,
                lambda evt: wx.PostEvent(self, PickEvent(self.GetId(), widget=self)),
            )
        self._list_box = wx.ListBox(self, style=wx.LB_SINGLE)
        self._search_feedback = wx.StaticText(self, label="")
        self._search_feedback.SetName(_copy("search", self._language_mode))
        sizer.Add(self._search_feedback, 0, wx.EXPAND | wx.BOTTOM, 4)
        sizer.Add(self._list_box, 1, wx.EXPAND)

        self._names: List[str] = []
        self._populate_item_name()
        self.set_name(default_name)
        self._list_box.Bind(wx.EVT_LISTBOX, lambda evt: self._post_item_change())
        apply_material3(self)

    def _post_namespace_change(self):
        if self._do_text_event:
            wx.PostEvent(
                self, ItemNamespaceChangeEvent(self.GetId(), namespace=self.namespace)
            )
        self._do_text_event = True

    def _post_item_change(self):
        wx.PostEvent(self, ItemNameChangeEvent(self.GetId(), name=self.name)),
        wx.PostEvent(
            self,
            ItemChangeEvent(self.GetId(), namespace=self.namespace, name=self.name),
        )

    @property
    def version(self) -> Tuple[str, Tuple[int, int, int], bool]:
        return self._platform, self._version_number, self._force_blockstate

    @version.setter
    def version(self, version: Tuple[str, Tuple[int, int, int], bool]):
        self._set_version(version)
        self._populate_namespace()
        self.namespace = None

    def _set_version(self, version: Tuple[str, Tuple[int, int, int], bool]):
        assert (
            version[0] in self._translation_manager.platforms()
            and version[1] in self._translation_manager.version_numbers(version[0])
            and isinstance(version[2], bool)
        ), f"{version} is not a valid version"
        self._platform, self._version_number, self._force_blockstate = version

    @property
    def namespace(self) -> str:
        return self._namespace_combo.GetValue()

    @namespace.setter
    def namespace(self, namespace: str):
        self.set_namespace(namespace)
        wx.PostEvent(
            self, ItemNamespaceChangeEvent(self.GetId(), namespace=self.namespace)
        )

    def set_namespace(self, namespace: str):
        namespace = namespace or "minecraft"
        if isinstance(namespace, str):
            if namespace in self._namespace_combo.GetItems():
                self._namespace_combo.SetSelection(
                    self._namespace_combo.GetItems().index(namespace)
                )
            else:
                self._namespace_combo.ChangeValue(namespace)

    @property
    def name(self) -> str:
        name: str = self._list_box.GetString(self._list_box.GetSelection())
        if self._list_box.GetSelection() == 0 and name.startswith('"'):
            name = name[1:-1]
        return name

    @name.setter
    def name(self, name: str):
        if self.set_name(name):
            self._post_item_change()

    def set_name(self, name: str) -> bool:
        name = name or ""
        self._search.ChangeValue(name)
        return self._update_item_name(name)

    def _populate_namespace(self):
        raise NotImplementedError("This method should be overridden in child classes.")

    def _populate_item_name(self):
        raise NotImplementedError("This method should be overridden in child classes.")

    def _on_namespace_change(self, evt):
        self._populate_item_name()
        self.name = None
        evt.Skip()

    def _on_search_change(self, evt):
        search_str = evt.GetString()
        if self._update_item_name(search_str):
            self._post_item_change()

    def _open_regex_builder(self, _event):
        with RegexBuilderDialog(
            self,
            self._search.GetValue(),
            self._search_regex_enabled,
            self._search_flags,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self._search_regex_enabled = dialog.regex_enabled
            self._search_flags = dialog.flags
            self._search.ChangeValue(dialog.pattern)
            self._update_item_name(dialog.pattern)

    def _update_item_name(self, search_str: str) -> bool:
        try:
            if self._search_regex_enabled:
                names = RegexBuilder(
                    search_str[:4096],
                    flags=self._search_flags,
                    regex_enabled=True,
                ).search(self._names)
            else:
                indices = plain_text_match_indices(
                    self._names,
                    search_str[:4096],
                    ignore_case=bool(self._search_flags & re.IGNORECASE),
                )
                names = [self._names[index] for index in indices]
            self._search_feedback.SetLabel("")
        except TimeoutError:
            self._search_feedback.SetLabel(_copy("timeout", self._language_mode))
            names = []
        except (re.error, ValueError):
            self._search_feedback.SetLabel(_copy("invalid", self._language_mode))
            names = []
        if search_str not in names:
            names.insert(0, f'"{search_str}"')

        index = 0
        selection = self._list_box.GetSelection()
        if selection != wx.NOT_FOUND:
            current_string = self._list_box.GetString(selection)
            if current_string in names:
                index = names.index(current_string)

        self._list_box.SetItems(names)
        if index:
            # if the previously selected string is in the list select that
            self._list_box.SetSelection(index)
            return False
        elif search_str in names:
            # if the searched text perfectly matches select that
            self._list_box.SetSelection(names.index(search_str))
            return True
        elif len(self._list_box.GetItems()) >= 2:
            self._list_box.SetSelection(1)
            return True
        else:
            self._list_box.SetSelection(0)
            return True
