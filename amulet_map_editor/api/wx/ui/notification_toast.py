"""Material 3 non-blocking notification toast for the desktop shell.

A toast carries a sentence somebody has to be able to read.  Wrapping it at a
number decided when the class was written cannot do that: the toast is stretched
across whatever width the shell currently has, so a fixed wrap is too wide on a
narrow window -- where the tail of every line runs off the right-hand edge and
the message stops mid-word -- and too narrow on a wide one, where it wraps into
a column with half the toast empty beside it.

So the body is wrapped to the width the toast is actually given, re-wrapped when
that width changes, and bounded: a message longer than :data:`MAX_BODY_LINES`
lines is cut at a word with a real ellipsis rather than at whatever character
the edge landed on, and the whole message stays in the tooltip and in the
accessible name so nothing said is ever unreachable.
"""

from __future__ import annotations

import wx

from amulet_map_editor.api import notification_copy
from amulet_map_editor.api.wx.material3 import apply_material3

#: How many lines of body a toast will grow to before the rest goes to the
#: tooltip.  A toast is a glance, not a document, and one tall enough to cover
#: the surface it is reporting on has stopped being non-blocking in practice.
MAX_BODY_LINES = 6

#: The width the toast asks for, and the widest it will ask for however wide
#: the shell is.  Long measures are hard to read and the toast is a strip
#: across the top of a window that can be very wide indeed.
PREFERRED_WIDTH = 420
MAX_WIDTH = 720

#: Padding inside the toast, and the room the dismiss button needs beside the
#: copy.  Both are subtracted from the toast's own width to get the width the
#: message may actually use.
PADDING = 12
BUTTON_GAP = 8


def wrap_lines(dc: wx.DC, font: wx.Font, text: str, available: int) -> list[str]:
    """Return ``text`` broken into lines no wider than ``available``.

    A standalone function rather than a method, so any surface that owns a
    :class:`wx.StaticText` and needs correct re-wrapping can measure with its
    own device context instead of going through ``wx.StaticText.Wrap`` --
    which on wxWidgets 3.3.3 does nothing on a second call once the label has
    already been wrapped once, per :meth:`NotificationToast._rewrap`.  A word
    wider than the whole line is broken across lines by character rather than
    left to hang off the right-hand edge.
    """
    dc.SetFont(font)
    limit = max(1, available)
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            while dc.GetTextExtent(word)[0] > limit and len(word) > 1:
                cut = len(word)
                while cut > 1 and dc.GetTextExtent(word[:cut])[0] > limit:
                    cut -= 1
                if current:
                    lines.append(current)
                    current = ""
                lines.append(word[:cut])
                word = word[cut:]
            candidate = f"{current} {word}" if current else word
            if not current or dc.GetTextExtent(candidate)[0] <= limit:
                current = candidate
                continue
            lines.append(current)
            current = word
        if current:
            lines.append(current)
    return lines or [""]


class NotificationToast(wx.Panel):
    """A bounded toast that never steals focus or blocks the active surface."""

    def __init__(
        self, parent: wx.Window, title: str, body: str, severity: str, on_dismiss
    ):
        super().__init__(parent, style=wx.NO_BORDER)
        self._on_dismiss = on_dismiss
        self._title = str(title)
        self._body = str(body)
        self._wrapped_at = 0
        root = wx.BoxSizer(wx.HORIZONTAL)
        copy = wx.BoxSizer(wx.VERTICAL)
        heading = wx.StaticText(self, label=self._title)
        heading.SetName("Notification toast title")
        self._heading = heading
        message = wx.StaticText(self, label=self._body)
        message.SetName("Notification toast message")
        self._message = message
        copy.Add(heading, 0, wx.EXPAND | wx.BOTTOM, 2)
        copy.Add(message, 0, wx.EXPAND)
        root.Add(copy, 1, wx.EXPAND | wx.ALL, PADDING)
        close = wx.Button(
            self,
            label=notification_copy.notification_text("action.dismiss", styled=False),
        )
        close.SetName("Dismiss notification toast")
        close.Bind(wx.EVT_BUTTON, lambda _event: self.dismiss())
        self._close = close
        root.Add(close, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, BUTTON_GAP)
        self.SetSizer(root)
        # Whatever is cut from the drawing stays reachable from the control,
        # and the accessible name always carries the whole message.
        full = f"{self._title}\n{self._body}".strip()
        self.SetToolTip(full)
        message.SetToolTip(self._body)
        self.SetName(full or "Notification")
        self.SetMinSize(wx.Size(self._preferred_width(), -1))
        self.Bind(wx.EVT_SIZE, self._on_size)
        self._rewrap(self._preferred_width())
        self._timer = None
        if severity not in {"error", "warning"}:
            self._timer = wx.CallLater(6000, self.dismiss)
        apply_material3(self)

    # -- geometry ------------------------------------------------------------
    def _preferred_width(self) -> int:
        """Return the width to ask for, never wider than the display allows.

        A toast is inserted into the shell's own sizer, so it inherits the
        window's width -- and a window dragged onto a smaller display, or one
        opened on a 1024-pixel screen, would otherwise be asked for a toast
        wider than the display it is on.
        """
        width = PREFERRED_WIDTH
        try:
            index = wx.Display.GetFromWindow(self)
            area = wx.Display(index if index != wx.NOT_FOUND else 0).GetClientArea()
            width = min(width, max(240, area.width - 48))
        except Exception:  # pragma: no cover - platform boundary
            pass
        return width

    def _text_width(self) -> int:
        """Return how much width the copy column genuinely has.

        A toast that has not been laid out yet reports a placeholder client
        size -- twenty pixels square, in this shell -- and wrapping to that
        produces a one-word column that then has to be undone.  A width that
        cannot even hold the padding and the dismiss button is not a width, so
        the preferred one is used until a real one arrives.
        """
        button = self._close.GetBestSize().width if self._close else 0
        chrome = PADDING * 2 + button + BUTTON_GAP
        width = self.GetClientSize().width
        if width <= chrome:
            width = self._preferred_width()
        return max(120, min(width, MAX_WIDTH) - chrome)

    def _on_size(self, event: wx.SizeEvent) -> None:
        self._rewrap(self.GetClientSize().width)
        event.Skip()

    def _rewrap(self, width: int) -> None:
        """Re-flow the title and the body for the width the toast now has.

        The wrapping is done here rather than by ``wx.StaticText.Wrap``.  That
        method takes the control's *current* label as its input, so it has to
        be handed an unwrapped one every time -- and on wxWidgets 3.3.3 a
        second call after the label has been restored does nothing at all: the
        first re-flow works, and the one after it leaves the message on a
        single line 1850 pixels wide inside a toast 804 pixels wide, which is
        the sentence that runs off the edge and stops mid-word.  Measuring the
        breaks here makes the result the same on every call and the same in a
        test as on screen.
        """
        if width <= 0 or width == self._wrapped_at:
            return
        self._wrapped_at = width
        available = self._text_width()
        self._heading.SetLabel("\n".join(self._wrap_lines(self._title, available)))
        self._message.SetLabel(self.wrapped_body(available))
        self.InvalidateBestSize()
        self.Layout()

    def _wrap_lines(self, text: str, available: int) -> list[str]:
        """Return ``text`` broken into lines no wider than ``available``.

        A word wider than the whole line is broken across lines by character.
        Leaving it alone -- which is what every wrap that only splits on spaces
        does -- is how a file path or a block identifier hangs off the right of
        a toast with no way to read the rest of it.
        """
        dc = wx.ClientDC(self)
        return wrap_lines(dc, self._message.GetFont(), text, available)

    def wrapped_body(self, available: int) -> str:
        """Return the body wrapped to ``available`` and bounded in height.

        Past :data:`MAX_BODY_LINES` the cut lands between words with a real
        ellipsis rather than at whatever character the edge happened to fall
        on, and the whole message is still in the tooltip and the accessible
        name.
        """
        if not self._body.strip():
            return self._body
        lines = self._wrap_lines(self._body, available)
        if len(lines) <= MAX_BODY_LINES:
            return "\n".join(lines)
        dc = wx.ClientDC(self)
        dc.SetFont(self._message.GetFont())
        kept = lines[:MAX_BODY_LINES]
        last = kept[-1].split()
        while last and dc.GetTextExtent(f"{' '.join(last)}…")[0] > available:
            last.pop()
        kept[-1] = f"{' '.join(last)}…" if last else "…"
        return "\n".join(kept)

    def dismiss(self) -> None:
        if self._timer is not None and self._timer.IsRunning():
            self._timer.Stop()
        if self._on_dismiss is not None:
            callback, self._on_dismiss = self._on_dismiss, None
            callback(self)


__all__ = ["NotificationToast", "MAX_BODY_LINES", "wrap_lines"]
