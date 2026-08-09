"""App-owned, responsive Material 3 regex builder for native search fields."""

from __future__ import annotations

import re

import wx
from wx.lib.wordwrap import wordwrap

from amulet_map_editor.api.regex_builder import RegexBuilder
from amulet_map_editor.api.wx.material3 import apply_material3

_GUIDED_PARTS = (
    ("Literal", "literal"),
    ("Character class", "class"),
    ("Start ^", "start"),
    ("End $", "end"),
    ("Group (…) ", "group"),
    ("Alternation |", "alternation"),
    ("Zero or more *", "zero-or-more"),
    ("One or more +", "one-or-more"),
    ("Optional ?", "optional"),
    ("Repeat {n}", "repeat"),
)


class RegexBuilderDialog(wx.Dialog):
    """Full bounded Python-regex builder shared by native search controls."""

    def __init__(
        self,
        parent: wx.Window,
        pattern: str = "",
        regex_enabled: bool = False,
        flags: int = 0,
        sample: str = "",
    ):
        super().__init__(
            parent,
            title="Search pattern",
            size=wx.Size(620, 640),
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        self.pattern = pattern
        self.regex_enabled = regex_enabled
        self.flags = flags

        root = wx.BoxSizer(wx.VERTICAL)
        content = wx.ScrolledWindow(self, style=wx.VSCROLL)
        content.SetScrollRate(0, 12)
        self._content = content
        body = wx.BoxSizer(wx.VERTICAL)

        self._heading_text = "Build a search pattern"
        self.heading = wx.StaticText(content, label=self._heading_text)
        self.heading.SetName("Regex builder heading")
        body.Add(self.heading, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)
        self._description_text = (
            "Plain text remains the default. Regex mode uses Python re with "
            "bounded input, nested-quantifier protection, live matches, and "
            "capture-group feedback."
        )
        self.description = wx.StaticText(content, label=self._description_text)
        self.description.SetName("Regex dialect and safety explanation")
        body.Add(self.description, 0, wx.EXPAND | wx.ALL, 16)

        body.Add(wx.StaticText(content, label="Pattern"), 0, wx.LEFT | wx.RIGHT, 16)
        self.pattern_input = wx.TextCtrl(
            content, value=pattern[:4096], style=wx.TE_PROCESS_ENTER
        )
        self.pattern_input.SetName("Regex pattern")
        body.Add(self.pattern_input, 0, wx.ALL | wx.EXPAND, 8)

        mode_row = wx.BoxSizer(wx.VERTICAL)
        self.regex_toggle = wx.CheckBox(content, label="Use regular expression")
        self.regex_toggle.SetName("Regex mode")
        self.regex_toggle.SetValue(regex_enabled)
        self.ignore_case = wx.CheckBox(content, label="Ignore case")
        self.ignore_case.SetName("Regex ignore case flag")
        self.ignore_case.SetValue(bool(flags & re.IGNORECASE))
        self.multiline = wx.CheckBox(content, label="Multiline anchors")
        self.multiline.SetName("Regex multiline flag")
        self.multiline.SetValue(bool(flags & re.MULTILINE))
        self.dot_all = wx.CheckBox(content, label="Dot matches newlines")
        self.dot_all.SetName("Regex dot all flag")
        self.dot_all.SetValue(bool(flags & re.DOTALL))
        for control in (
            self.regex_toggle,
            self.ignore_case,
            self.multiline,
            self.dot_all,
        ):
            mode_row.Add(control, 0, wx.RIGHT | wx.BOTTOM, 12)
        body.Add(mode_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 16)

        guided_label = wx.StaticText(content, label="Guided construction")
        guided_label.SetToolTip(
            "Insert literals, classes, anchors, groups, alternation, and quantifiers at the caret."
        )
        body.Add(guided_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)
        guided = wx.BoxSizer(wx.VERTICAL)
        self.guided_buttons = []
        for label, kind in _GUIDED_PARTS:
            button = wx.Button(content, label=label)
            button.SetName(f"Regex builder insert {kind}")
            button.Bind(
                wx.EVT_BUTTON,
                lambda _event, part=kind: self._insert_guided_part(part),
            )
            self.guided_buttons.append(button)
            guided.Add(button, 0, wx.RIGHT | wx.BOTTOM, 8)
        body.Add(guided, 0, wx.EXPAND | wx.ALL, 8)

        body.Add(
            wx.StaticText(content, label="Sample text"),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            16,
        )
        self.sample = wx.TextCtrl(
            content, value=sample[:100_000], style=wx.TE_MULTILINE
        )
        self.sample.SetName("Regex sample text")
        self.sample.SetMinSize(wx.Size(-1, 110))
        body.Add(self.sample, 1, wx.ALL | wx.EXPAND, 8)

        self.validation = wx.StaticText(content, label="Type a pattern to validate it.")
        self.validation.SetName("Regex validation")
        body.Add(
            self.validation,
            0,
            wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND,
            16,
        )
        self.match_output = wx.TextCtrl(
            content,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            name="Regex live matches and capture groups",
        )
        self.match_output.SetMinSize(wx.Size(-1, 120))
        body.Add(self.match_output, 1, wx.ALL | wx.EXPAND, 8)

        content.SetSizer(body)
        content.FitInside()
        root.Add(content, 1, wx.EXPAND)

        action_row = wx.BoxSizer(wx.VERTICAL)
        self.copy_button = wx.Button(self, label="Copy pattern")
        self.copy_button.SetName("Copy regex pattern")
        action_row.Add(self.copy_button, 0, wx.RIGHT | wx.BOTTOM, 8)
        root.Add(action_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)

        buttons = wx.StdDialogButtonSizer()
        apply_button = wx.Button(self, wx.ID_OK, "Apply")
        cancel_button = wx.Button(self, wx.ID_CANCEL, "Cancel")
        buttons.AddButton(apply_button)
        buttons.AddButton(cancel_button)
        buttons.Realize()
        root.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 16)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(320, 380))

        for control in (
            self.pattern_input,
            self.regex_toggle,
            self.ignore_case,
            self.multiline,
            self.dot_all,
            self.sample,
        ):
            (
                control.Bind(wx.EVT_TEXT, self._validate)
                if isinstance(control, wx.TextCtrl)
                else control.Bind(wx.EVT_CHECKBOX, self._validate)
            )
        self.pattern_input.Bind(wx.EVT_TEXT_ENTER, self._apply)
        self.copy_button.Bind(wx.EVT_BUTTON, self._copy_pattern)
        apply_button.Bind(wx.EVT_BUTTON, self._apply)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self._validate(None)
        # wxMSW must finish creating the native dialog before its M3 title bar
        # replaces the platform caption, especially on isolated desktops.
        wx.CallAfter(self._apply_material_and_reflow)
        self.pattern_input.SetFocus()

    def _on_size(self, event: wx.SizeEvent) -> None:
        self._reflow()
        event.Skip()

    def _apply_material_and_reflow(self) -> None:
        """Style first so wrapping measures the final persisted UI font."""

        apply_material3(self)
        self._reflow()

    def _reflow(self) -> None:
        width = max(220, self.GetClientSize().width - 48)
        dc = wx.ClientDC(self._content)
        for control, text in (
            (self.heading, self._heading_text),
            (self.description, self._description_text),
            (self.validation, " ".join(self.validation.GetLabel().splitlines())),
        ):
            dc.SetFont(control.GetFont())
            control.SetLabel(wordwrap(text, width, dc, breakLongWords=True))
            control.SetMinSize(wx.DefaultSize)
            control.InvalidateBestSize()
            best = control.GetBestSize()
            control.SetMinSize(wx.Size(1, best.height + 12))
        self._content.Layout()
        self._content.FitInside()
        self.Layout()
        self._content.Refresh()

    def _insert_guided_part(self, kind: str) -> None:
        start, end = self.pattern_input.GetSelection()
        raw = self.pattern_input.GetValue()
        selected = raw[start:end]
        atom = selected or "expression"
        replacements = {
            "literal": re.escape(selected or "literal"),
            "class": f"[{selected or 'abc'}]",
            "start": "^",
            "end": "$",
            "group": f"({atom})",
            "alternation": f"{selected or 'left|right'}",
            "zero-or-more": f"(?:{atom})*",
            "one-or-more": f"(?:{atom})+",
            "optional": f"(?:{atom})?",
            "repeat": f"(?:{atom}){{2}}",
        }
        replacement = replacements[kind]
        self.pattern_input.Replace(start, end, replacement)
        caret = start + len(replacement)
        self.pattern_input.SetInsertionPoint(caret)
        self.pattern_input.SetFocus()

    def _builder(self) -> RegexBuilder:
        flags = 0
        if self.ignore_case.GetValue():
            flags |= re.IGNORECASE
        if self.multiline.GetValue():
            flags |= re.MULTILINE
        if self.dot_all.GetValue():
            flags |= re.DOTALL
        return RegexBuilder(
            self.pattern_input.GetValue()[:4096],
            flags=flags,
            regex_enabled=self.regex_toggle.GetValue(),
        )

    def _validate(self, _event: wx.Event | None) -> None:
        result = self._builder().evaluate(self.sample.GetValue()[:100_000])
        if not result.valid:
            self.validation.SetLabel(f"Invalid pattern: {result.error}")
            self.validation.SetForegroundColour(wx.Colour(180, 40, 40))
            self.match_output.ChangeValue("")
            self._reflow()
            return
        count = len(result.matches)
        self.validation.SetLabel(f"Valid pattern · {count} sample match(es)")
        self.validation.SetForegroundColour(wx.Colour(40, 120, 70))
        lines = []
        for index, match in enumerate(result.matches[:50], 1):
            groups = result.groups[index - 1]
            suffix = f" · groups: {groups!r}" if groups else ""
            lines.append(f"{index}. {match!r}{suffix}")
        if count > 50:
            lines.append(f"… {count - 50} additional match(es) not displayed")
        self.match_output.ChangeValue("\n".join(lines) or "No sample matches")
        self._reflow()

    def _copy_pattern(self, _event: wx.Event) -> None:
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(
                    wx.TextDataObject(self.pattern_input.GetValue())
                )
                self.validation.SetLabel("Pattern copied to the clipboard.")
            finally:
                wx.TheClipboard.Close()
        else:
            self.validation.SetLabel("Clipboard is currently unavailable.")
        self._reflow()

    def _apply(self, _event: wx.Event) -> None:
        result = self._builder().validate()
        if not result.valid:
            self._validate(None)
            return
        self.pattern = self.pattern_input.GetValue()[:4096]
        self.regex_enabled = self.regex_toggle.GetValue()
        self.flags = self._builder().flags
        self.EndModal(wx.ID_OK)
