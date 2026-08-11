"""The app-owned Material 3 regex builder.

Every search field in the application opens this one builder, so it has to
carry a whole search back and forth rather than only a pattern: the field's
current pattern, the flag letters it evaluates with, and the sample text the
user was checking against.  Losing any of those on the way out means the field
comes back configured differently from the way the user left the builder.

It is the modal route.  A search bar prefers its anchored popover, beside the
field the user is already typing in; this window is what opens where that
popover cannot fit, and what a surface with no Studio search bar of its own
opens directly.

Two things changed when it was drawn in Material rather than in native
controls, and both were visible defects rather than restyling:

* It opened **182 pixels wide**.  ``SetSizerAndFit`` sized the window to its
  contents and the ``SetMinSize`` after it only constrained later dragging, so
  the builder appeared as a column too narrow to read a pattern in until the
  user resized it by hand.  The size is now set as well as floored.
* It called itself a builder while offering nothing to build with.  The token
  row is the guided construction the design asks for: a digit, a character
  class, a group, an alternation or a quantifier goes in at the caret, so the
  syntax is reachable by somebody who does not already know it by heart.

The match preview is drawn from the evaluation the validation line was already
running, so it costs nothing and answers the question the validation line
could not: not whether the pattern compiles, but what it actually catches.
"""

from __future__ import annotations

import re

import wx

from amulet_map_editor.api.regex_builder import RegexBuilder
from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.widgets import StudioButton, StudioCheckBox
from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.api.wx.ui.material_dialog import (
    DialogChrome,
    TextField,
    heading,
    studio,
)

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

#: How many matches the preview names before it summarises the rest.  A sample
#: with four hundred matches in it should not push the buttons off the window.
PREVIEW_LIMIT = 6

#: The guided construction the design asks a builder for: each entry is the
#: literal inserted at the caret, what it means in words, and how many
#: characters to step back afterwards so the caret lands *inside* a pair.
PATTERN_TOKENS = (
    (r"\d", "Any digit", 0),
    (r"\w", "Any letter, digit, or underscore", 0),
    (r"\s", "Any whitespace", 0),
    (".", "Any single character", 0),
    ("[]", "Any one of these characters", 1),
    ("()", "Group, captured for later use", 1),
    ("|", "Either the left or the right", 0),
    ("+", "One or more of the last thing", 0),
    ("*", "Zero or more of the last thing", 0),
    ("?", "The last thing, optionally", 0),
    ("^", "The start of the text", 0),
    ("$", "The end of the text", 0),
)


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
    """The pattern, its flags, a sample to try it on, and what it matched."""

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

        self.chrome = DialogChrome(self, status_name="Pattern validation")
        self.chrome.add(heading(self.chrome.body, "Pattern", size_px=12))
        self.pattern_field = TextField(
            self.chrome.body,
            value=pattern,
            placeholder="chunk \\d+",
            name="Search pattern",
            mono=True,
        )
        #: The native entry inside the painted outline.  Kept as the attribute
        #: callers already had, so ``GetValue``, ``SetMaxLength`` and ``Bind``
        #: read exactly as they did before this window was drawn in Material.
        self.pattern_input = self.pattern_field.text
        self.pattern_input.SetMaxLength(500)
        self.chrome.add(self.pattern_field, 0, wx.EXPAND)
        self.chrome.gap(tokens.SPACE_XS)
        self.chrome.add(self._build_token_row(), 0, wx.EXPAND)
        self.chrome.gap()

        self.regex_toggle = studio(
            StudioCheckBox(
                self.chrome.body,
                "Use regular expression",
                value=regex_enabled,
                name="Use regular expression",
            )
        )
        self.regex_toggle.SetToolTip(
            "Plain text is the default. Turn this on to read the pattern as a "
            "regular expression."
        )
        self.chrome.add(self.regex_toggle, 0)
        self.chrome.gap()

        self.chrome.add(heading(self.chrome.body, "Flags (i m s x u)", size_px=12))
        self.flags_field = TextField(
            self.chrome.body,
            value=self.flags_text,
            placeholder="iu",
            name="Regular expression flags",
            mono=True,
        )
        self.flags_input = self.flags_field.text
        self.flags_input.SetMaxLength(MAX_FLAGS_LENGTH)
        self.chrome.add(self.flags_field, 0, wx.EXPAND)
        self.chrome.gap()

        self.chrome.add(heading(self.chrome.body, "Sample text (optional)", size_px=12))
        self.sample_field = TextField(
            self.chrome.body,
            value=self.sample,
            name="Sample text",
            multiline=True,
            height=110,
        )
        self.sample_input = self.sample_field.text
        self.chrome.add(self.sample_field, 1, wx.EXPAND)
        self.chrome.gap()

        self.validation = heading(
            self.chrome.body,
            "Type a pattern to validate it.",
            size_px=12,
            role="on_surface_variant",
            name="Pattern validation",
        )
        self.chrome.add(self.validation, 0, wx.EXPAND)
        self.preview = heading(
            self.chrome.body,
            "",
            size_px=12,
            role="on_surface",
            name="Pattern match preview",
        )
        self.chrome.add(self.preview, 0, wx.EXPAND)

        self.cancel_button = self.chrome.action(
            "Cancel",
            variant="text",
            on_click=self._cancel,
            name="Cancel and keep the search as it was",
        )
        self.apply_button = self.chrome.action(
            "Apply",
            variant="filled",
            on_click=self._apply,
            name="Apply this pattern to the search",
        )

        self.pattern_input.Bind(wx.EVT_TEXT, self._validate)
        self.regex_toggle.Bind(wx.EVT_CHECKBOX, self._validate)
        self.flags_input.Bind(wx.EVT_TEXT, self._validate)
        self.sample_input.Bind(wx.EVT_TEXT, self._validate)
        # A native dialog gave Enter and Escape their meanings through
        # ``wx.ID_OK`` and ``wx.ID_CANCEL``.  Owner-drawn buttons carry no
        # dialog ids, so the two keys are bound explicitly rather than quietly
        # lost -- Enter still applies, Escape still cancels, and neither is
        # taken from somebody typing a multi-line sample.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        # Both status lines are prose, so they rewrap when the window is
        # resized rather than running off its edge.
        self.Bind(wx.EVT_SIZE, self._on_resize)
        self._validate(None)

        # Fit, then floor, then size.  ``SetSizerAndFit`` alone opened this
        # window at the width of its narrowest child -- 182 pixels -- because a
        # minimum size constrains dragging and never the first appearance.
        self.SetMinSize(wx.Size(tokens.scaled(420), tokens.scaled(430)))
        self.SetSize(wx.Size(tokens.scaled(480), tokens.scaled(560)))
        self.Layout()
        apply_material3(self)

    # -- guided construction -------------------------------------------------
    def _build_token_row(self) -> wx.Sizer:
        """Return the row of literals a pattern can be assembled from."""

        # ``wx.WrapSizer``'s default flags include EXTEND_LAST_ON_EACH_LINE,
        # which stretched whichever token happened to land last on a row to the
        # full width of the window -- so ``$`` appeared as a bar across the
        # dialog while its neighbours were pills.  Only the leading-space rule
        # is wanted here.
        row = wx.WrapSizer(wx.HORIZONTAL, wx.REMOVE_LEADING_SPACES)
        self.token_buttons = []
        for literal, meaning, step_back in PATTERN_TOKENS:
            button = studio(
                StudioButton(
                    self.chrome.body,
                    literal,
                    variant="pill",
                    on_click=(
                        lambda text=literal, back=step_back: self._insert(text, back)
                    ),
                    name=f"Insert {meaning.lower()} ({literal})",
                    hint=f"{literal} — {meaning}",
                )
            )
            self.token_buttons.append(button)
            row.Add(
                button,
                0,
                wx.RIGHT | wx.BOTTOM,
                tokens.scaled(tokens.SPACE_XS),
            )
        return row

    def _insert(self, literal: str, step_back: int = 0) -> None:
        """Put ``literal`` in at the caret and leave the caret ready to type.

        A pair goes in whole and the caret lands between its halves, which is
        where the next character belongs; anything else lands after what was
        inserted.  Focus returns to the pattern either way, because a builder
        that makes the user click back into the field after every token is
        slower than typing the character.
        """

        start, end = self.pattern_input.GetSelection()
        self.pattern_input.Replace(start, end, literal)
        caret = max(0, start + len(literal) - step_back)
        # Focus first, caret second, and the order is the whole of it. Giving a
        # ``wx.TextCtrl`` focus on Windows selects all of its text, so a caret
        # placed before the focus call is immediately replaced by a
        # whole-field selection -- and the *next* token then overwrites the
        # pattern instead of extending it. Pressing two tokens in a row left
        # the field holding only the second one.
        self.pattern_input.SetFocus()
        self.pattern_input.SetInsertionPoint(caret)
        self.pattern_input.SetSelection(caret, caret)

    # -- evaluation ----------------------------------------------------------
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
        # Only the error red is pushed in.  Handing the ordinary colour back as
        # an explicit override would pin it to whichever palette was live when
        # the pattern last changed, so the line would keep the old theme's grey
        # after a theme change; ``set_role`` returns it to the palette.
        if result.valid:
            self.validation.set_role("on_surface_variant")
        else:
            self.validation.SetForegroundColour(tokens.palette().error)
        self.preview.SetLabel(self._preview_text(result))
        self._rewrap()
        self.Layout()

    def _preview_text(self, result) -> str:
        """Say what the pattern caught, not only whether it compiled."""

        if not result.valid:
            return "No matches while the pattern is invalid."
        if not self.pattern_input.GetValue().strip():
            return "Type a pattern to see what it matches."
        if not result.matches:
            return "No match in the sample text."
        shown = list(result.matches[:PREVIEW_LIMIT])
        more = len(result.matches) - len(shown)
        text = " · ".join(shown)
        if more > 0:
            text = f"{text} · +{more} more"
        groups = [group for group in result.groups if any(group)]
        if groups:
            first = ", ".join(part for part in groups[0] if part)
            text = f"{text}   groups: {first}"
        return f"Matched: {text}"

    # -- layout --------------------------------------------------------------
    def _rewrap(self) -> None:
        """Wrap both status lines to the body, so neither runs off the window."""

        width = self.chrome.body.GetClientSize().width - tokens.scaled(
            self.chrome.padding * 2
        )
        if width <= 0:
            return
        for line in (self.validation, self.preview):
            line.Wrap(width)

    def _on_resize(self, event: wx.SizeEvent) -> None:
        self._rewrap()
        event.Skip()

    # -- keyboard ------------------------------------------------------------
    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == wx.WXK_ESCAPE:
            self._cancel()
            return
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            # Enter belongs to the sample field while the caret is in it: that
            # box holds several lines of text on purpose.
            if wx.Window.FindFocus() is self.sample_input:
                event.Skip()
                return
            self._apply()
            return
        event.Skip()

    # -- result --------------------------------------------------------------
    def _cancel(self, _event: wx.Event | None = None) -> None:
        self.EndModal(wx.ID_CANCEL)

    def _apply(self, _event: wx.Event | None = None) -> None:
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


__all__ = [
    "FLAG_MEANINGS",
    "MAX_FLAGS_LENGTH",
    "PATTERN_TOKENS",
    "PREVIEW_LIMIT",
    "RegexBuilderDialog",
    "flags_to_text",
    "text_to_flags",
    "unknown_flags",
]
