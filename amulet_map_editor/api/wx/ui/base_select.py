import wx
from wx.lib import newevent
import re
from typing import Tuple, List, Optional, Sequence

import PyMCTranslate

from amulet_map_editor.api import lang, preferences
from amulet_map_editor.api.studio import widgets as studio
from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.api.wx.ui import material_forms as forms
from amulet_map_editor.api.regex_builder import RegexBuilder
from amulet_map_editor.api.wx.ui.regex_dialog import RegexBuilderDialog


class _NamespaceCombo(wx.Panel):
    """A typed namespace field with a dropdown of namespaces seen so far.

    Stands in for ``wx.ComboBox`` -- the last one left anywhere in this
    project.  Its shape matches: typing is free text and posts
    ``wx.EVT_TEXT`` exactly as a plain text entry does (a namespace like a
    mod id is not required to be one of the known options), and the dropdown
    only ever offers namespaces :meth:`Set` was actually given -- there is no
    invented default in it.
    """

    def __init__(self, parent: wx.Window, name: str = "Namespace") -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self._items: List[str] = []
        self.field = forms.MaterialTextField(self, name=name)
        self._browse = studio.StudioButton(
            self,
            "▾",
            variant="outlined",
            hint="Choose a known namespace",
            name=f"{name} choices",
        )
        self._browse.SetMinSize(wx.Size(36, -1))
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.field, 1, wx.EXPAND | wx.RIGHT, 4)
        row.Add(self._browse, 0, wx.EXPAND)
        self.SetSizer(row)
        self._browse.Bind(wx.EVT_BUTTON, self._open_popup)

    def Bind(self, event, handler, source=None):  # noqa: N802 - wx API spelling
        if event == wx.EVT_TEXT:
            return self.field.Bind(event, handler, source)
        return super().Bind(event, handler, source)

    def Set(self, items: Sequence[str]) -> None:  # noqa: N802 - wx API spelling
        """Replace the known namespaces offered by the dropdown."""
        self._items = [str(item) for item in items]

    def GetItems(self) -> List[str]:  # noqa: N802 - wx API spelling
        return list(self._items)

    def GetValue(self) -> str:  # noqa: N802 - wx API spelling
        return self.field.GetValue()

    def ChangeValue(self, value: str) -> None:  # noqa: N802 - wx API spelling
        """Replace the text without raising ``wx.EVT_TEXT``."""
        self.field.ChangeValue(value)

    def SetSelection(self, index: int) -> None:  # noqa: N802 - wx API spelling
        """Choose a known namespace by index, silently, as ``wx.ComboBox`` does."""
        if 0 <= index < len(self._items):
            self.field.ChangeValue(self._items[index])

    def SetToolTip(self, tip) -> None:  # noqa: N802 - wx API spelling
        self.field.SetToolTip(tip)

    def _open_popup(self, _event: wx.Event) -> None:
        if not self._items:
            return
        popup = studio.AnchoredPopup(self, self._browse, width=220, max_height=260)
        listbox = forms.MaterialListBox(
            popup.content, self._items, name="Known namespaces"
        )
        popup.content_sizer.Add(listbox, 1, wx.EXPAND)

        def _choose(event: wx.CommandEvent) -> None:
            # A real value change, raised the same way typing one does, so
            # anything bound to this control's ``wx.EVT_TEXT`` fires exactly
            # as it would for a namespace picked from a real combo box.
            self.field.SetValue(listbox.GetStringSelection())
            popup.Dismiss()
            event.Skip()

        listbox.Bind(wx.EVT_LISTBOX, _choose)
        popup.popup()


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
        text = studio.StudioText(
            self,
            _copy("namespace", self._language_mode),
            size_px=13,
            role="on_surface",
        )
        sizer.Add(text, 1, wx.ALIGN_CENTER_VERTICAL)
        self._namespace_combo = _NamespaceCombo(
            self, name=_copy("namespace", self._language_mode)
        )
        sizer.Add(self._namespace_combo, 2, wx.EXPAND)
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
            studio.StudioText(
                self,
                _copy("name", self._language_mode).format(
                    type_name=self.TypeName.capitalize()
                ),
                size_px=13,
                role="on_surface",
            ),
            1,
            wx.ALIGN_CENTER_VERTICAL,
        )
        search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        header_sizer.Add(search_sizer, 2, wx.EXPAND)
        self._search = wx.SearchCtrl(self)
        self._search.SetHint(_copy("search", self._language_mode))
        search_sizer.Add(self._search, 1, wx.ALIGN_CENTER_VERTICAL)
        self._regex_button = studio.StudioButton(
            self,
            "Regex…",
            variant="outlined",
            hint="Build a bounded regular-expression search",
            name="Regex builder",
        )
        search_sizer.Add(self._regex_button, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 6)
        self._search_regex_enabled = False
        self._search_flags = 0
        self._regex_button.Bind(wx.EVT_BUTTON, self._open_regex_builder)
        self._search.Bind(wx.EVT_TEXT, self._on_search_change)
        if show_pick:
            pick_button = studio.StudioButton(
                self,
                "",
                variant="icon",
                glyph="🎨",
                hint="Pick from the world",
                name="Pick from the world",
            )
            search_sizer.Add(pick_button, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 5)
            pick_button.Bind(
                wx.EVT_BUTTON,
                lambda evt: wx.PostEvent(self, PickEvent(self.GetId(), widget=self)),
            )
        self._list_box = forms.MaterialListBox(self, name="Matching names")
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
            names = RegexBuilder(
                search_str[:4096],
                flags=self._search_flags,
                regex_enabled=self._search_regex_enabled,
            ).search(self._names)
        except (re.error, ValueError):
            names = []
        if search_str not in names:
            names.insert(0, f'"{search_str}"')

        index = 0
        selection = self._list_box.GetSelection()
        if selection != wx.NOT_FOUND:
            current_string = self._list_box.GetString(selection)
            if current_string in names:
                index = names.index(current_string)

        self._list_box.Set(names)
        if index:
            # if the previously selected string is in the list select that
            self._list_box.SetSelection(index)
            return False
        elif search_str in names:
            # if the searched text perfectly matches select that
            self._list_box.SetSelection(names.index(search_str))
            return True
        elif len(self._list_box.GetStrings()) >= 2:
            self._list_box.SetSelection(1)
            return True
        else:
            self._list_box.SetSelection(0)
            return True
