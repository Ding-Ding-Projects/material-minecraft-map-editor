"""App-owned, responsive Material 3 regex builder for native search fields."""

from __future__ import annotations

import re
from typing import Optional, Tuple

import wx
from wx.lib.wordwrap import wordwrap

from amulet_map_editor.api import preferences, settings_search
from amulet_map_editor.api.regex_builder import (
    RegexBuilder,
    RegexEvaluationController,
    RegexResult,
)
from amulet_map_editor.api.wx.material3 import (
    active_material_palette,
    apply_material3,
)

_GUIDED_PARTS = (
    "literal",
    "class",
    "start",
    "end",
    "group",
    "alternation",
    "zero-or-more",
    "one-or-more",
    "optional",
    "repeat",
)


class RegexBuilderDialog(wx.Dialog):
    """Full localized Python-regex builder with terminable live evaluation."""

    def __init__(
        self,
        parent: wx.Window,
        pattern: str = "",
        regex_enabled: bool = False,
        flags: int = 0,
        sample: str = "",
        language_mode: Optional[str] = None,
    ):
        self.language_mode = language_mode or preferences.load().language_mode
        super().__init__(
            parent,
            title=self._copy("builder.window.title"),
            size=wx.Size(620, 640),
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        self.pattern = pattern
        self.regex_enabled = regex_enabled
        self.flags = flags
        self._last_signature: Optional[Tuple[str, bool, int, str]] = None
        self._last_result: Optional[RegexResult] = None
        self._apply_when_valid = False
        self._regex_controller = RegexEvaluationController(
            lambda callback: wx.CallAfter(callback)
        )

        root = wx.BoxSizer(wx.VERTICAL)
        content = wx.ScrolledWindow(self, style=wx.VSCROLL)
        content.SetScrollRate(0, 12)
        self._content = content
        body = wx.BoxSizer(wx.VERTICAL)

        self._heading_text = self._copy("builder.title")
        self.heading = wx.StaticText(content, label=self._heading_text)
        self.heading.SetName(self._heading_text)
        body.Add(self.heading, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)
        self._description_text = self._copy("builder.description")
        self.description = wx.StaticText(content, label=self._description_text)
        self.description.SetName(self._description_text)
        body.Add(self.description, 0, wx.EXPAND | wx.ALL, 16)

        body.Add(
            wx.StaticText(content, label=self._copy("builder.pattern")),
            0,
            wx.LEFT | wx.RIGHT,
            16,
        )
        self.pattern_input = wx.TextCtrl(
            content, value=pattern[:4096], style=wx.TE_PROCESS_ENTER
        )
        self.pattern_input.SetName(self._copy("builder.pattern"))
        body.Add(self.pattern_input, 0, wx.ALL | wx.EXPAND, 8)

        mode_row = wx.BoxSizer(wx.VERTICAL)
        self.regex_toggle = wx.CheckBox(
            content, label=self._copy("builder.use.regex", compact=True)
        )
        self.regex_toggle.SetName(self._copy("builder.use.regex"))
        self.regex_toggle.SetValue(regex_enabled)
        self.ignore_case = wx.CheckBox(
            content, label=self._copy("builder.ignore.case", compact=True)
        )
        self.ignore_case.SetName(self._copy("builder.ignore.case"))
        self.ignore_case.SetValue(bool(flags & re.IGNORECASE))
        self.multiline = wx.CheckBox(
            content, label=self._copy("builder.multiline", compact=True)
        )
        self.multiline.SetName(self._copy("builder.multiline"))
        self.multiline.SetValue(bool(flags & re.MULTILINE))
        self.dot_all = wx.CheckBox(
            content, label=self._copy("builder.dotall", compact=True)
        )
        self.dot_all.SetName(self._copy("builder.dotall"))
        self.dot_all.SetValue(bool(flags & re.DOTALL))
        for control in (
            self.regex_toggle,
            self.ignore_case,
            self.multiline,
            self.dot_all,
        ):
            mode_row.Add(control, 0, wx.RIGHT | wx.BOTTOM, 12)
        body.Add(mode_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 16)

        self._guided_text = self._copy("builder.guided")
        self.guided_label = wx.StaticText(content, label=self._guided_text)
        self.guided_label.SetToolTip(self._copy("builder.guided.help"))
        body.Add(self.guided_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)
        guided = wx.BoxSizer(wx.VERTICAL)
        self.guided_buttons = []
        for kind in _GUIDED_PARTS:
            key = f"builder.{kind.replace('-', '.')}"
            label = self._copy(key, compact=True)
            button = wx.Button(content, label=label)
            button.SetName(self._copy(key))
            button.Bind(
                wx.EVT_BUTTON,
                lambda _event, part=kind: self._insert_guided_part(part),
            )
            self.guided_buttons.append(button)
            guided.Add(button, 0, wx.EXPAND | wx.RIGHT | wx.BOTTOM, 8)
        body.Add(guided, 0, wx.EXPAND | wx.ALL, 8)

        body.Add(
            wx.StaticText(content, label=self._copy("builder.sample")),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            16,
        )
        self.sample = wx.TextCtrl(
            content, value=sample[:100_000], style=wx.TE_MULTILINE
        )
        self.sample.SetName(self._copy("builder.sample"))
        self.sample.SetMinSize(wx.Size(-1, 110))
        body.Add(self.sample, 1, wx.ALL | wx.EXPAND, 8)

        self._validation_text = self._copy("builder.prompt")
        self.validation = wx.StaticText(content, label=self._validation_text)
        self.validation.SetName(self._copy("builder.prompt"))
        body.Add(
            self.validation,
            0,
            wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND,
            16,
        )
        self.match_output = wx.TextCtrl(
            content,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            name=self._copy("builder.valid", count=0),
        )
        self.match_output.SetMinSize(wx.Size(-1, 120))
        body.Add(self.match_output, 1, wx.ALL | wx.EXPAND, 8)

        content.SetSizer(body)
        content.FitInside()
        root.Add(content, 1, wx.EXPAND)

        action_row = wx.BoxSizer(wx.VERTICAL)
        self.copy_button = wx.Button(
            self, label=self._copy("builder.copy", compact=True)
        )
        self.copy_button.SetName(self._copy("builder.copy"))
        action_row.Add(self.copy_button, 0, wx.EXPAND | wx.RIGHT | wx.BOTTOM, 8)
        root.Add(action_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)

        buttons = wx.StdDialogButtonSizer()
        self.apply_button = wx.Button(
            self, wx.ID_OK, self._copy("builder.apply", compact=True)
        )
        self.apply_button.SetName(self._copy("builder.apply"))
        cancel_button = wx.Button(
            self, wx.ID_CANCEL, self._copy("builder.cancel", compact=True)
        )
        cancel_button.SetName(self._copy("builder.cancel"))
        buttons.AddButton(self.apply_button)
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
                control.Bind(wx.EVT_TEXT, self._schedule_validate)
                if isinstance(control, wx.TextCtrl)
                else control.Bind(wx.EVT_CHECKBOX, self._schedule_validate)
            )
        self.pattern_input.Bind(wx.EVT_TEXT_ENTER, self._apply)
        self.copy_button.Bind(wx.EVT_BUTTON, self._copy_pattern)
        self.apply_button.Bind(wx.EVT_BUTTON, self._apply)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self._schedule_validate(None, immediate=True)
        # wxMSW must finish creating the native dialog before its M3 title bar
        # replaces the platform caption, especially on isolated desktops.
        wx.CallAfter(self._apply_material_and_reflow)
        self.pattern_input.SetFocus()

    def _copy(
        self,
        key: str,
        *,
        compact: bool = False,
        joiner: Optional[str] = None,
        **values: object,
    ) -> str:
        return settings_search.localized_copy(
            key,
            self.language_mode,
            bilingual_separator=(
                joiner if joiner is not None else ("\n" if compact else " · ")
            ),
            **values,
        )

    def _on_size(self, event: wx.SizeEvent) -> None:
        self._reflow()
        event.Skip()

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._regex_controller.close()
        event.Skip()

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self._regex_controller.close()
        event.Skip()

    def _apply_material_and_reflow(self) -> None:
        """Style first so wrapping measures the final persisted UI font."""

        apply_material3(self)
        self._reflow()

    def _reflow(self) -> None:
        for _pass in range(2):
            self.Layout()
            width = max(180, self._content.GetClientSize().width - 40)
            dc = wx.ClientDC(self._content)
            for control in self._content.GetChildren():
                if isinstance(control, (wx.TextCtrl, wx.Button)):
                    minimum = control.GetMinSize()
                    height = max(minimum.height, control.GetBestSize().height)
                    control.SetMinSize(wx.Size(1, height))
            for control, text in (
                (self.heading, self._heading_text),
                (self.description, self._description_text),
                (self.guided_label, self._guided_text),
                (self.validation, self._validation_text),
            ):
                dc.SetFont(control.GetFont())
                control.SetLabel(wordwrap(text, width, dc, breakLongWords=True))
                control.SetMinSize(wx.DefaultSize)
                control.InvalidateBestSize()
                best = control.GetBestSize()
                control.SetMinSize(wx.Size(1, best.height + 12))
            self._content.Layout()
            self._content.FitInside()
            virtual = self._content.GetVirtualSize()
            self._content.SetVirtualSize(
                wx.Size(max(1, self._content.GetClientSize().width), virtual.height)
            )
        self.Layout()
        virtual = self._content.GetVirtualSize()
        self._content.SetVirtualSize(
            wx.Size(max(1, self._content.GetClientSize().width), virtual.height)
        )
        self._content.Refresh()

    def _set_validation(self, text: str) -> None:
        self._validation_text = text
        self.validation.SetLabel(text)

    def _insert_guided_part(self, kind: str) -> None:
        start, end = self.pattern_input.GetSelection()
        raw = self.pattern_input.GetValue()
        selected = raw[start:end]
        atom = selected or "expression"
        alternation = (
            f"(?:{selected})"
            if "|" in selected
            else f"(?:{selected or 'left'}|{'alternative' if selected else 'right'})"
        )
        replacements = {
            "literal": re.escape(selected or "literal"),
            "class": f"[{selected or 'abc'}]",
            "start": "^",
            "end": "$",
            "group": f"({atom})",
            "alternation": alternation,
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

    def _signature(self) -> Tuple[str, bool, int, str]:
        builder = self._builder()
        return (
            builder.pattern,
            builder.regex_enabled,
            builder.flags,
            self.sample.GetValue()[:100_000],
        )

    def _schedule_validate(
        self, _event: Optional[wx.Event], *, immediate: bool = False
    ) -> None:
        signature = self._signature()
        self._last_signature = None
        self._last_result = None
        self.apply_button.Disable()
        palette = active_material_palette()
        self._set_validation(self._copy("builder.checking"))
        self.validation.SetForegroundColour(palette["on_surface_variant"])
        self.match_output.ChangeValue("")
        self._reflow()
        builder = self._builder()
        self._regex_controller.submit(
            builder.request((signature[3],), capture_matches=True),
            lambda result, expected=signature: self._accept_validation(
                expected, result
            ),
            immediate=immediate,
        )

    def _accept_validation(
        self, signature: Tuple[str, bool, int, str], result: RegexResult
    ) -> None:
        if signature != self._signature():
            return
        self._last_signature = signature
        self._last_result = result
        palette = active_material_palette()
        if result.timed_out:
            self._set_validation(self._copy("builder.timeout"))
            self.validation.SetForegroundColour(palette["error"])
            self.match_output.ChangeValue("")
            self._apply_when_valid = False
            self._reflow()
            return
        if not result.valid:
            self._set_validation(
                self._copy("builder.invalid", error=result.error or "")
            )
            self.validation.SetForegroundColour(palette["error"])
            self.match_output.ChangeValue("")
            self._apply_when_valid = False
            self._reflow()
            return

        count = len(result.matches)
        self._set_validation(self._copy("builder.valid", count=count))
        self.validation.SetForegroundColour(palette["primary"])
        lines = []
        for index, match in enumerate(result.matches[:50], 1):
            groups = result.groups[index - 1]
            suffix = (
                self._copy("builder.groups", joiner="", groups=groups) if groups else ""
            )
            lines.append(f"{index}. {match!r}{suffix}")
        if result.truncated or count > 50:
            lines.append(self._copy("builder.additional"))
        self.match_output.ChangeValue("\n".join(lines) or self._copy("builder.nomatch"))
        self.apply_button.Enable()
        self._reflow()
        if self._apply_when_valid:
            self._finish_apply()

    def _copy_pattern(self, _event: wx.Event) -> None:
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(
                    wx.TextDataObject(self.pattern_input.GetValue())
                )
                self._set_validation(self._copy("builder.copied"))
            finally:
                wx.TheClipboard.Close()
        else:
            self._set_validation(self._copy("builder.clipboard"))
        self._reflow()

    def _apply(self, _event: wx.Event) -> None:
        if (
            self._last_signature == self._signature()
            and self._last_result is not None
            and self._last_result.valid
            and not self._last_result.timed_out
        ):
            self._finish_apply()
            return
        self._apply_when_valid = True
        self._schedule_validate(None, immediate=True)

    def _finish_apply(self) -> None:
        self.pattern = self.pattern_input.GetValue()[:4096]
        self.regex_enabled = self.regex_toggle.GetValue()
        self.flags = self._builder().flags
        self._regex_controller.close()
        self.EndModal(wx.ID_OK)
