"""Small app-owned Material 3 regex builder dialog.

Every search field in the application opens this one builder, so it has to
carry a whole search back and forth rather than only a pattern: the field's
current pattern, the flag letters it evaluates with, and the sample text the
user was checking against.  Losing any of those on the way out means the field
comes back configured differently from the way the user left the builder.
"""

from __future__ import annotations

import re

import wx

from amulet_map_editor.api.regex_builder import RegexBuilder
from amulet_map_editor.api.wx.material3 import apply_material3

#: The flag letters this builder understands, and the ``re`` flag each carries.
#: Anything else a caller supplies is dropped rather than guessed at, and the
#: validation line says so.
FLAG_MEANINGS = {
    "i": re.IGNORECASE,
    "m": re.MULTILINE,
    "s": re.DOTALL,
    "x": re.VERBOSE,
    "u": re.UNICODE,
}

MAX_FLAGS_LENGTH = 8


def flags_to_text(flags: int) -> str:
    """Return the flag letters matching an ``re`` flag integer."""
    return "".join(
        letter for letter, value in FLAG_MEANINGS.items() if int(flags) & value
    )


def text_to_flags(text: str) -> int:
    """Return the ``re`` flag integer for a string of flag letters."""
    value = 0
    for letter in str(text or "").lower():
        value |= FLAG_MEANINGS.get(letter, 0)
    return value


def unknown_flags(text: str) -> str:
    """Return the letters in ``text`` this builder cannot honour."""
    seen = []
    for letter in str(text or "").lower():
        if letter not in FLAG_MEANINGS and letter not in seen:
            seen.append(letter)
    return "".join(seen)


class RegexBuilderDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window,
        pattern: str = "",
        regex_enabled: bool = False,
        flags: int = 0,
        sample: str = "",
        flags_text: str = "",
    ):
        super().__init__(
            parent, title="Search pattern", style=wx.NO_BORDER | wx.RESIZE_BORDER
        )
        self.pattern = pattern
        self.regex_enabled = regex_enabled
        self.flags_text = str(flags_text or flags_to_text(flags))
        self.flags = text_to_flags(self.flags_text)
        self.sample = str(sample)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(
            wx.StaticText(self, label="Pattern"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 16
        )
        self.pattern_input = wx.TextCtrl(self, value=pattern, style=wx.TE_PROCESS_ENTER)
        self.pattern_input.SetName("Search pattern")
        self.pattern_input.SetMaxLength(500)
        root.Add(self.pattern_input, 0, wx.ALL | wx.EXPAND, 8)
        self.regex_toggle = wx.CheckBox(self, label="Use regular expression")
        self.regex_toggle.SetValue(regex_enabled)
        self.regex_toggle.SetName("Use regular expression")
        root.Add(self.regex_toggle, 0, wx.LEFT | wx.RIGHT, 16)
        root.Add(
            wx.StaticText(self, label="Flags (i m s x u)"),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            16,
        )
        self.flags_input = wx.TextCtrl(self, value=self.flags_text)
        self.flags_input.SetName("Regular expression flags")
        self.flags_input.SetMaxLength(MAX_FLAGS_LENGTH)
        root.Add(self.flags_input, 0, wx.ALL | wx.EXPAND, 8)
        root.Add(
            wx.StaticText(self, label="Sample text (optional)"),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            16,
        )
        self.sample_input = wx.TextCtrl(self, value=self.sample, style=wx.TE_MULTILINE)
        self.sample_input.SetName("Sample text")
        root.Add(self.sample_input, 1, wx.ALL | wx.EXPAND, 8)
        self.validation = wx.StaticText(self, label="Type a pattern to validate it.")
        self.validation.SetName("Pattern validation")
        root.Add(self.validation, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)

        buttons = wx.StdDialogButtonSizer()
        apply_button = wx.Button(self, wx.ID_OK, "Apply")
        cancel_button = wx.Button(self, wx.ID_CANCEL, "Cancel")
        buttons.AddButton(apply_button)
        buttons.AddButton(cancel_button)
        buttons.Realize()
        root.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        self.SetSizerAndFit(root)
        self.SetMinSize((420, 400))
        self.pattern_input.Bind(wx.EVT_TEXT, self._validate)
        self.regex_toggle.Bind(wx.EVT_CHECKBOX, self._validate)
        self.flags_input.Bind(wx.EVT_TEXT, self._validate)
        self.sample_input.Bind(wx.EVT_TEXT, self._validate)
        apply_button.Bind(wx.EVT_BUTTON, self._apply)
        self._validate(None)
        apply_material3(self)

    def _flag_text(self) -> str:
        """Return the flag letters currently typed, lowercased and bounded."""
        return self.flags_input.GetValue()[:MAX_FLAGS_LENGTH].lower()

    def _builder(self) -> RegexBuilder:
        return RegexBuilder(
            self.pattern_input.GetValue()[:4096],
            flags=text_to_flags(self._flag_text()),
            regex_enabled=self.regex_toggle.GetValue(),
        )

    def _validate(self, _event: wx.Event | None) -> None:
        result = self._builder().evaluate(self.sample_input.GetValue()[:100_000])
        ignored = unknown_flags(self._flag_text())
        if result.valid:
            count = len(result.matches)
            message = f"Valid pattern · {count} sample match(es)"
        else:
            message = f"Invalid pattern: {result.error}"
        if ignored:
            message += f" · ignoring unknown flag(s): {ignored}"
        self.validation.SetLabel(message)

    def _apply(self, _event: wx.Event) -> None:
        result = self._builder().validate()
        if not result.valid:
            self._validate(None)
            return
        self.pattern = self.pattern_input.GetValue()[:4096]
        self.regex_enabled = self.regex_toggle.GetValue()
        self.flags_text = "".join(
            letter for letter in self._flag_text() if letter in FLAG_MEANINGS
        )
        self.flags = text_to_flags(self.flags_text)
        self.sample = self.sample_input.GetValue()[:100_000]
        self.EndModal(wx.ID_OK)
