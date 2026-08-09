import wx
from amulet_map_editor import lang
from amulet_map_editor.api.wx.material3 import apply_material3


class WarningDialog(wx.Dialog):
    def __init__(self, parent: wx.Window):
        # The shared M3 helper installs the custom title bar; requesting the
        # native caption here would flash legacy Windows chrome during startup.
        super().__init__(parent, style=wx.NO_BORDER | wx.RESIZE_BORDER)
        self.SetTitle(lang.get("warning_dialog.title"))

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        content = wx.StaticText(
            self,
            wx.ID_ANY,
            lang.get("warning_dialog.content"),
            style=wx.ALIGN_CENTER_HORIZONTAL,
        )
        content.Wrap(750)
        main_sizer.Add(content, 1, wx.ALL | wx.EXPAND, 5)

        button_sizer = wx.StdDialogButtonSizer()
        main_sizer.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 4)

        self._do_not_show = wx.CheckBox(
            self, wx.ID_ANY, lang.get("warning_dialog.do_not_show_again")
        )
        button_sizer.Add(self._do_not_show, 0, wx.ALIGN_CENTER_VERTICAL, 0)

        self._understand_button = wx.Button(
            self, wx.ID_ANY, lang.get("warning_dialog.i_understand")
        )
        self._understand_button.SetDefault()
        button_sizer.Add(self._understand_button, 0, 0, 0)

        button_sizer.Realize()

        self.SetSizer(main_sizer)
        main_sizer.Fit(self)

        self.SetAffirmativeId(self._understand_button.GetId())

        self.Layout()
        # Apply synchronously as well as through the global window-create hook:
        # startup is the first user-visible decision surface and must not flash
        # the legacy caption/white native dialog before the M3 chrome arrives.
        apply_material3(self)

    @property
    def do_not_show_again(self) -> bool:
        return self._do_not_show.GetValue()
