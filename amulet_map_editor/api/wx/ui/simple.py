"""A collection of classes for wx objects to abstract away
the repeated code and make working with wx a bit more simple."""

import logging
import wx
import wx.adv
from wx.lib.scrolledpanel import ScrolledPanel
from typing import Iterable, Union, Any, List, Optional, Sequence, Dict, Tuple
from amulet_map_editor.api.wx.material3 import apply_material3

log = logging.getLogger(__name__)


class SimpleSizer:
    def __init__(self, sizer_dir=wx.VERTICAL):
        self._sizer = self.sizer = wx.BoxSizer(sizer_dir)

    def add_object(self, obj, space=1, options=wx.ALL):
        self.sizer.Add(obj, space, options, 5)
        # Panels are commonly populated after construction. Re-apply the
        # semantic roles at the insertion point so late controls do not miss
        # the shared Material 3 sizing and contrast contract.
        if isinstance(obj, wx.Window):
            apply_material3(obj)


class SimplePanel(wx.Panel, SimpleSizer):
    def __init__(self, parent: wx.Window, sizer_dir=wx.VERTICAL):
        wx.Panel.__init__(
            self,
            parent,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.TAB_TRAVERSAL,
        )
        SimpleSizer.__init__(self, sizer_dir)
        self.SetSizer(self.sizer)
        apply_material3(self)


class SimpleScrollablePanel(ScrolledPanel, SimpleSizer):
    """A scrolled panel that automatically sets itself up."""

    def __init__(self, parent: wx.Window, sizer_dir=wx.VERTICAL, **kwargs):
        ScrolledPanel.__init__(self, parent, **kwargs)
        SimpleSizer.__init__(self, sizer_dir)
        self.SetSizer(self.sizer)
        self.SetupScrolling()
        self.SetAutoLayout(1)
        apply_material3(self)

    def DoGetBestSize(self):
        sizer = self.GetSizer()
        if sizer is None:
            return -1, -1
        else:
            sx, sy = sizer.CalcMin()
            return (
                sx + wx.SystemSettings.GetMetric(wx.SYS_VSCROLL_X),
                sy,
            )


class SimpleChoice(wx.Choice):
    """A wrapper for wx.Choice that sets up the UI for you."""

    def __init__(
        self,
        parent: wx.Window,
        choices: Sequence[str] = (),
        default: Optional[str] = None,
    ):
        super().__init__(parent, choices=choices)
        apply_material3(self)
        if choices:
            if default is not None and default in choices:
                self.SetSelection(choices.index(default))
            else:
                self.SetSelection(0)

    def GetCurrentString(self) -> str:
        return self.GetString(self.GetSelection())


StringableType = Any


class SimpleChoiceAny(wx.Choice):
    """An extension for wx.Choice that enables showing and returning objects that are not strings."""

    def __init__(self, parent: wx.Window, sort=True, reverse=False):
        super().__init__(parent)
        apply_material3(self)
        self._values: List[Any] = []  # the data hidden behind the string
        self._keys: List[str] = []  # the strings shown to the user
        self._sorted = sort
        self._reverse = reverse

    @property
    def keys(self) -> Tuple[str, ...]:
        """Get the string values displayed to the user"""
        return tuple(self._keys)

    @property
    def values(self) -> Tuple[Any, ...]:
        """Get the data hidden behind the string value"""
        return tuple(self._values)

    @property
    def items(self) -> Tuple[Tuple[str, Any], ...]:
        """Get the string value and the data hidden behind the value"""
        return tuple(zip(self._keys, self._values))

    def SetItems(
        self,
        items: Union[Iterable[StringableType], Dict[StringableType, Any]],
        default: StringableType = None,
    ):
        """Set items. Does not have to be strings.
        If items is a dictionary the string of the values are show to the user and the key is returned from GetAny
        If it is just an iterable the string of the values are shown and the raw equivalent input is returned.
        """
        if not items:
            return
        if isinstance(items, dict):
            items: List[Tuple[str, Any]] = [
                (str(value), key) for key, value in items.items()
            ]
            if self._sorted:
                items = sorted(items, key=lambda x: x[0], reverse=self._reverse)
            self._keys = [key.strip() for key, _ in items]
            self._values = [value for _, value in items]
        else:
            if self._sorted:
                self._values = list(sorted(items))
                if self._reverse:
                    self._values.reverse()
            else:
                self._values = list(items)
            self._keys = [str(v).strip() for v in self._values]
        super().SetItems(self._keys)
        if default is not None and default in self._values:
            self.SetSelection(self._values.index(default))
        else:
            self.SetSelection(0)

    def SetValue(self, value: Any):
        if value in self._keys:
            self.SetSelection(self._keys.index(value))

    def GetAny(self) -> Optional[Any]:
        """Return the value currently selected in the form before it was converted to a string"""
        log.warning(
            "SimpleChoiceAny.GetAny is being depreciated and will be removed in the future. Please use SimpleChoiceAny.GetCurrentObject instead",
            exc_info=True,
        )
        return self.GetCurrentObject()

    def GetCurrentObject(self) -> Optional[Any]:
        """Return the value currently selected in the form before it was converted to a string"""
        if self._values:
            return self._values[self.GetSelection()]

    def GetCurrentString(self) -> str:
        """Get the string form of the value currently selected."""
        return self.GetString(self.GetSelection())


class SimpleDialog(wx.Dialog):
    """A dialog with ok and cancel buttons set up."""

    def __init__(self, parent: wx.Window, title, sizer_dir=wx.VERTICAL):
        wx.Dialog.__init__(
            self, parent, title=title, style=wx.NO_BORDER | wx.RESIZE_BORDER
        )
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)
        self.sizer = wx.BoxSizer(sizer_dir)
        sizer.Add(self.sizer, 1, wx.EXPAND)
        self.bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.bottom_sizer, 0, wx.EXPAND)
        self.bottom_sizer.AddStretchSpacer()
        button_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        self.bottom_sizer.Add(button_sizer, flag=wx.ALL, border=5)
        apply_material3(self)


class MaterialTextEntryDialog(wx.Dialog):
    """Borderless M3 text-entry prompt for short app-owned values."""

    def __init__(self, parent: wx.Window, message: str, value: str = ""):
        super().__init__(parent, title=message, style=wx.NO_BORDER | wx.RESIZE_BORDER)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(self, label=message), 0, wx.ALL | wx.EXPAND, 16)
        self.value = wx.TextCtrl(self, value=value, style=wx.TE_PROCESS_ENTER)
        self.value.SetName("Text entry value")
        root.Add(self.value, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 16)
        root.Add(
            self.CreateButtonSizer(wx.OK | wx.CANCEL),
            0,
            wx.ALL | wx.ALIGN_RIGHT,
            16,
        )
        self.SetSizerAndFit(root)
        self.value.Bind(wx.EVT_TEXT_ENTER, lambda _event: self.EndModal(wx.ID_OK))
        apply_material3(self)
        self.value.SetFocus()

    def GetValue(self) -> str:
        return self.value.GetValue()


class MaterialDateTimeField(wx.Panel):
    """Typed schedule field with a native date/time picker companion."""

    def __init__(self, parent: wx.Window, kind: str):
        if kind not in ("date", "time"):
            raise ValueError("kind must be date or time")
        super().__init__(parent)
        self.kind = kind
        self._syncing_picker = False
        self.text = wx.TextCtrl(self)
        self.text.SetName(f"Schedule {kind} typed value")
        self.text.SetHint("YYYY-MM-DD" if kind == "date" else "HH:MM")
        if kind == "date":
            self.picker = wx.adv.DatePickerCtrl(
                self, style=wx.adv.DP_DROPDOWN | wx.adv.DP_SHOWCENTURY
            )
            self.picker.SetName("Schedule date picker")
            self.picker.Bind(wx.adv.EVT_DATE_CHANGED, self._picker_changed)
        else:
            self.picker = wx.adv.TimePickerCtrl(self)
            self.picker.SetName("Schedule time picker")
            self.picker.Bind(wx.adv.EVT_TIME_CHANGED, self._picker_changed)
        # Keep typed and native picker routes available without imposing a
        # fixed horizontal width on the narrow/high-scale Preferences page.
        column = wx.BoxSizer(wx.VERTICAL)
        column.Add(self.text, 0, wx.EXPAND | wx.BOTTOM, 6)
        column.Add(self.picker, 0, wx.ALIGN_LEFT)
        self.SetSizer(column)
        self.text.Bind(wx.EVT_TEXT, self._text_changed)
        apply_material3(self)

    def _text_changed(self, event: wx.Event) -> None:
        event.Skip()

    def _picker_changed(self, event: wx.Event) -> None:
        if self._syncing_picker:
            event.Skip()
            return
        value = self.picker.GetValue()
        if self.kind == "date":
            formatted = value.FormatISODate()
        else:
            formatted = value.Format("%H:%M")
        # SetValue emits EVT_TEXT only after the native value has been read and
        # the typed route is synchronized. Preferences search and schedule
        # persistence therefore observe the same new value in one event flow.
        self.text.SetValue(formatted)
        event.Skip()

    def SetValue(self, value: str) -> None:
        self.text.ChangeValue(str(value or ""))
        self._syncing_picker = True
        try:
            if self.kind == "date":
                parsed = __import__("datetime").date.fromisoformat(str(value))
                self.picker.SetValue(
                    wx.DateTime.FromDMY(parsed.day, parsed.month - 1, parsed.year)
                )
            else:
                hour, minute = (int(part) for part in str(value).split(":", 1))
                self.picker.SetValue(wx.DateTime.Now())
                self.picker.SetTime(hour, minute, 0)
        except (TypeError, ValueError):
            pass
        finally:
            self._syncing_picker = False

    def GetValue(self) -> str:
        return self.text.GetValue()

    def Bind(self, event, handler, source=None):
        if event == wx.EVT_TEXT:
            return self.text.Bind(event, handler, source)
        return super().Bind(event, handler, source)
