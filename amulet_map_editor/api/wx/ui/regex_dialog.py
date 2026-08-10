"""Small app-owned Material 3 regex builder dialog."""

from __future__ import annotations

import wx

from amulet_map_editor.api.regex_builder import RegexBuilder
from amulet_map_editor.api.wx.material3 import apply_material3


class RegexBuilderDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window,
        pattern: str = "",
        regex_enabled: bool = False,
        flags: int = 0,
    ):
        super().__init__(
            parent, title="Search pattern", style=wx.NO_BORDER | wx.RESIZE_BORDER
        )
        self.pattern = pattern
        self.regex_enabled = regex_enabled
        self.flags = flags

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(
            wx.StaticText(self, label="Pattern"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 16
        )
        self.pattern_input = wx.TextCtrl(self, value=pattern, style=wx.TE_PROCESS_ENTER)
        root.Add(self.pattern_input, 0, wx.ALL | wx.EXPAND, 8)
        self.regex_toggle = wx.CheckBox(self, label="Use regular expression")
        self.regex_toggle.SetValue(regex_enabled)
        root.Add(self.regex_toggle, 0, wx.LEFT | wx.RIGHT, 16)
        self.ignore_case = wx.CheckBox(self, label="Ignore case")
        self.ignore_case.SetValue(bool(flags & 0x02))
        root.Add(self.ignore_case, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        root.Add(
            wx.StaticText(self, label="Sample text (optional)"),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            16,
        )
        self.sample = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        root.Add(self.sample, 1, wx.ALL | wx.EXPAND, 8)
        self.validation = wx.StaticText(self, label="Type a pattern to validate it.")
        root.Add(self.validation, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)

        buttons = wx.StdDialogButtonSizer()
        apply_button = wx.Button(self, wx.ID_OK, "Apply")
        cancel_button = wx.Button(self, wx.ID_CANCEL, "Cancel")
        buttons.AddButton(apply_button)
        buttons.AddButton(cancel_button)
        buttons.Realize()
        root.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        self.SetSizerAndFit(root)
        self.SetMinSize((420, 360))
        self.pattern_input.Bind(wx.EVT_TEXT, self._validate)
        self.regex_toggle.Bind(wx.EVT_CHECKBOX, self._validate)
        self.ignore_case.Bind(wx.EVT_CHECKBOX, self._validate)
        apply_button.Bind(wx.EVT_BUTTON, self._apply)
        self._validate(None)
        apply_material3(self)

    def _builder(self) -> RegexBuilder:
        flags = 0x02 if self.ignore_case.GetValue() else 0
        return RegexBuilder(
            self.pattern_input.GetValue()[:4096],
            flags=flags,
            regex_enabled=self.regex_toggle.GetValue(),
        )

    def _validate(self, _event: wx.Event | None) -> None:
        result = self._builder().evaluate(self.sample.GetValue()[:100_000])
        if result.valid:
            count = len(result.matches)
            self.validation.SetLabel(f"Valid pattern · {count} sample match(es)")
        else:
            self.validation.SetLabel(f"Invalid pattern: {result.error}")

    def _apply(self, _event: wx.Event) -> None:
        result = self._builder().validate()
        if not result.valid:
            self._validate(None)
            return
        self.pattern = self.pattern_input.GetValue()[:4096]
        self.regex_enabled = self.regex_toggle.GetValue()
        self.flags = 0x02 if self.ignore_case.GetValue() else 0
        self.EndModal(wx.ID_OK)
