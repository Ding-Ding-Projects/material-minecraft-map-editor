"""The shell's one progress surface: a Material linear indicator, on top.

Saving a world is not a question.  Neither is closing one, extracting one, or
running an operation over one -- and yet every one of them used to open a
``wx.ProgressDialog``, which is application-modal: it takes focus, it disables
the window behind it, and it puts a second title bar in front of the interface
for as long as the work runs.  That is the shape this project reserves for a
decision the user has to make before anything else can happen, and progress is
not a decision.  It is information.

So progress moved here.  This is a linear progress indicator drawn *over* the
application rather than laid out inside it: it is positioned by the frame, like
the notification toasts in ``api/framework/amulet_ui.py``, so it takes no space
from the interface and reflows nothing when it appears or goes.  The interface
underneath stays live, and where a particular operation genuinely does make
something unavailable, the row says which thing rather than letting the window
sit frozen with no explanation.

Three distinctions are load-bearing here and each one is drawn, not described:

* **A fraction and no fraction look different.**  Work that can report how far
  along it is fills a bar; work that cannot draws a travelling band.  Both come
  from :mod:`amulet_map_editor.api.studio.loading`, which is where the same
  distinction was first made, so the startup screen and this overlay cannot
  drift into disagreeing about what "cannot say" looks like.
* **Cancellable and uncancellable look different.**  A row draws a Cancel
  control exactly when the work behind it can actually be stopped.
* **A failure and a completion look different.**  A finished row retires
  itself; a failed one turns red, keeps its message, and stays until somebody
  dismisses it.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import wx

from amulet_map_editor.api.progress import DONE, FAILED, RUNNING, ProgressTask
from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.copy import studio_label
from amulet_map_editor.api.studio.loading import (
    draw_determinate_bar,
    draw_indeterminate_band,
)
from amulet_map_editor.api.studio.widgets import (
    StudioButton,
    _Themed,
    elide,
    reduced_motion,
)

log = logging.getLogger(__name__)

#: How often the travelling band advances, in milliseconds.  Slow enough to
#: cost nothing during a yield loop, fast enough to read as motion.
PULSE_INTERVAL_MS = 60

#: The linear indicator's own thickness, and the room around a row's copy.
BAR_HEIGHT = 4
ROW_PADDING = 10
ROW_GAP = 6


class ProgressOverlay(wx.Panel, _Themed):
    """A stack of live progress rows, floated over the shell.

    The overlay owns no operations.  It is handed
    :class:`~amulet_map_editor.api.progress.ProgressTask` records and draws
    them; whoever is doing the work owns the record and updates it.  That is
    what lets a long save report from a worker thread without this class
    knowing anything about saving.
    """

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.TRANSPARENT_WINDOW | wx.TAB_TRAVERSAL)
        self._tasks: List[ProgressTask] = []
        self._buttons: Dict[str, StudioButton] = {}
        self._pulse = 0.0
        self._install("Progress")
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_tick, self._timer)
        self.Bind(wx.EVT_SIZE, self._on_size)
        # The overlay stops its own animation when it goes, rather than relying
        # on the frame's close path to do it. A wx.Timer left running against a
        # destroyed window keeps delivering events to a handler that is no
        # longer there, and the shell is not always taken down through
        # ``EVT_CLOSE`` -- a window destroyed directly never runs it. Two test
        # processes hung on exactly this before it was bound.
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_overlay_destroyed)
        self.Hide()

    def _on_overlay_destroyed(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self.stop()
        event.Skip()

    # -- state ---------------------------------------------------------------
    @property
    def tasks(self) -> List[ProgressTask]:
        """Return the live rows, newest last."""
        return list(self._tasks)

    @property
    def pulse(self) -> float:
        """Where the travelling band currently is, from 0 to 1."""
        return self._pulse

    def task(self, key: str) -> Optional[ProgressTask]:
        for item in self._tasks:
            if item.key == key:
                return item
        return None

    def publish(self, task: ProgressTask) -> None:
        """Show ``task``, replacing any earlier row with the same key."""
        if self.IsBeingDeleted():
            return
        existing = self.task(task.key)
        if existing is None:
            self._tasks.append(task)
        else:
            self._tasks[self._tasks.index(existing)] = task
        self._sync()

    def retire(self, key: str) -> None:
        """Drop a row.  A failed row is dropped only when explicitly dismissed."""
        if self.IsBeingDeleted():
            return
        task = self.task(key)
        if task is None:
            return
        self._tasks.remove(task)
        self._sync()

    def dismiss_all(self) -> None:
        """Drop every row, live or failed.  Used when the shell is going away."""
        self._tasks.clear()
        self._sync()

    # -- geometry ------------------------------------------------------------
    def row_height(self, task: ProgressTask) -> int:
        """Return the height ``task`` needs, so nothing it says is clipped."""
        lines = 1
        if task.detail:
            lines += 1
        if task.unavailable:
            lines += 1
        if task.state == FAILED and task.error:
            lines += 1
        return (
            tokens.scaled(BAR_HEIGHT)
            + tokens.scaled(ROW_PADDING) * 2
            + tokens.scaled(18)
            + tokens.scaled(15) * (lines - 1)
        )

    def best_height(self) -> int:
        """Return the whole overlay's height for the rows it currently holds."""
        if not self._tasks:
            return 0
        total = sum(self.row_height(task) for task in self._tasks)
        return total + tokens.scaled(ROW_GAP) * (len(self._tasks) - 1)

    def _row_rects(self) -> List[wx.Rect]:
        width = self.GetClientSize().width
        rects: List[wx.Rect] = []
        top = 0
        for task in self._tasks:
            height = self.row_height(task)
            rects.append(wx.Rect(0, top, width, height))
            top += height + tokens.scaled(ROW_GAP)
        return rects

    # -- children ------------------------------------------------------------
    def _sync(self) -> None:
        """Reconcile the cancel and dismiss controls with the live rows.

        A control is created and destroyed here rather than during a paint,
        because creating a window inside ``EVT_PAINT`` is how a repaint becomes
        a recursive one.
        """
        wanted = {
            task.key: task
            for task in self._tasks
            if task.cancellable or task.state == FAILED
        }
        for key in list(self._buttons):
            if key not in wanted:
                button = self._buttons.pop(key)
                try:
                    button.Destroy()
                except RuntimeError:  # pragma: no cover - already torn down
                    pass
        for key, task in wanted.items():
            label, name = self._button_copy(task)
            button = self._buttons.get(key)
            if button is None:
                # ``on_click`` reads the *current* task each time rather than
                # closing over this one, so a row that fails after its cancel
                # button was built dismisses instead of cancelling a finished
                # operation.
                button = StudioButton(
                    self,
                    label,
                    variant="text",
                    on_click=lambda key=key: self._activate(key),
                    name=name,
                )
                self._buttons[key] = button
            else:
                button.SetLabel(label)
                button.SetName(name)
        self._refresh_accessibility()
        show = bool(self._tasks)
        if show != self.IsShown():
            self.Show(show)
        if show:
            self.Raise()
        self._retune_timer()
        self._layout_buttons()
        self.Refresh()

    @staticmethod
    def _button_copy(task: ProgressTask) -> tuple:
        if task.state == FAILED:
            return (
                studio_label("Dismiss", "關閉"),
                f"Dismiss the failed operation: {task.title}",
            )
        return (studio_label("Cancel", "取消"), f"Cancel {task.title}")

    def _activate(self, key: str) -> None:
        task = self.task(key)
        if task is None:
            return
        if task.state == FAILED:
            self.retire(key)
            return
        if task.on_cancel is not None:
            task.on_cancel()

    def _layout_buttons(self) -> None:
        rects = self._row_rects()
        for task, rect in zip(self._tasks, rects):
            button = self._buttons.get(task.key)
            if button is None:
                continue
            size = button.GetBestSize()
            button.SetSize(size)
            button.SetPosition(
                wx.Point(
                    max(0, rect.width - size.width - tokens.scaled(ROW_PADDING)),
                    rect.y
                    + tokens.scaled(BAR_HEIGHT)
                    + tokens.scaled(ROW_PADDING) // 2,
                )
            )
            button.Raise()

    def _refresh_accessibility(self) -> None:
        """Keep the overlay's accessible name and value true as work moves.

        The name is the whole stack read as a sentence, which is what a screen
        reader announces when focus reaches the surface, and it is refreshed on
        every update so the value it carries is the current one rather than the
        one the row opened with.
        """
        if not self._tasks:
            self.SetName("Progress")
            return
        self.SetName(
            "Progress. " + " ".join(task.accessible_name() for task in self._tasks)
        )
        self.SetToolTip("\n".join(task.accessible_name() for task in self._tasks))

    # -- animation -----------------------------------------------------------
    def _retune_timer(self) -> None:
        """Animate only while something genuinely cannot report a fraction.

        A determinate bar moves when its number moves, so animating beside it
        would draw motion that means nothing, and a reader who asked for less
        motion gets none at all -- the indeterminate rows draw their still
        appearance instead, which is a different picture rather than a frozen
        one.
        """
        moving = any(
            task.state == RUNNING and not task.determinate for task in self._tasks
        )
        if moving and not reduced_motion():
            if not self._timer.IsRunning():
                self._timer.Start(PULSE_INTERVAL_MS)
        elif self._timer.IsRunning():
            self._timer.Stop()

    def _on_tick(self, _event: wx.TimerEvent) -> None:
        self._pulse = (self._pulse + 0.02) % 1.0
        self.Refresh()

    def _on_size(self, event: wx.SizeEvent) -> None:
        self._layout_buttons()
        self.Refresh()
        event.Skip()

    def stop(self) -> None:
        """Stop animating; the overlay is about to be destroyed."""
        if self._timer.IsRunning():
            self._timer.Stop()

    # -- painting ------------------------------------------------------------
    def _backdrop(self) -> wx.Colour:
        # An overlay paints its own surface.  Inheriting the parent's colour
        # would let whatever it is floating over read straight through the copy
        # on top of it.
        #
        # ``surface_container`` rather than ``surface_container_high`` for a
        # reason that only a capture showed: the shared determinate bar draws
        # its *unfilled* track in ``surface_container_high``, so a row painted
        # that colour made the empty part of the bar invisible -- and a bar at
        # zero percent then looked like no bar at all, which is the one
        # appearance "nothing yet" must not have.
        return tokens.palette().surface_container

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        with self._painting(dc, rect) as local:
            palette = tokens.palette()
            top = 0
            for task in self._tasks:
                height = self.row_height(task)
                self._draw_row(dc, wx.Rect(0, top, local.width, height), task, palette)
                top += height + tokens.scaled(ROW_GAP)

    def _draw_row(self, dc: wx.DC, rect: wx.Rect, task: ProgressTask, palette) -> None:
        failed = task.state == FAILED
        # There is no error-container role in this palette, and inventing one
        # here would put a colour in the interface that no theme, preset or
        # appearance editor can reach. Tinting the surface towards the error
        # role keeps the failed row obviously different while staying inside
        # the roles the rest of the shell is built from.
        #
        # ``blend(a, b, weight)`` mixes *b into a*, so the surface is first and
        # the error second. Written the other way round -- which is how it went
        # out the first time -- 0.12 means "twelve percent surface", and the
        # capture came back with the entire row in flat crimson and its detail
        # line unreadable on top of it.
        surface = (
            tokens.blend(palette.surface_container, palette.error, 0.12)
            if failed
            else palette.surface_container
        )
        dc.SetBrush(wx.Brush(surface))
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.DrawRectangle(rect)
        # A hairline along the bottom so the band reads as its own surface
        # rather than as part of whatever it is floating over.
        dc.SetPen(wx.Pen(palette.outline_variant))
        dc.DrawLine(rect.x, rect.GetBottom(), rect.GetRight(), rect.GetBottom())

        bar = wx.Rect(rect.x, rect.y, rect.width, tokens.scaled(BAR_HEIGHT))
        if failed:
            dc.SetBrush(wx.Brush(palette.error))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(bar)
        elif task.determinate:
            draw_determinate_bar(dc, bar, task.fraction or 0.0, palette)
        else:
            draw_indeterminate_band(
                dc, bar, self._pulse, palette, still=reduced_motion()
            )

        pad = tokens.scaled(ROW_PADDING)
        left = rect.x + pad
        line = rect.y + tokens.scaled(BAR_HEIGHT) + pad
        button = self._buttons.get(task.key)
        reserved = pad
        if button is not None:
            reserved += button.GetSize().width + tokens.scaled(8)
        column = max(tokens.scaled(80), rect.width - pad - reserved)

        # The reading goes beside the title rather than under it, so the two
        # facts a glance needs -- what is happening and how far along it is --
        # are on one line.
        reading = self._reading(task)
        dc.SetFont(tokens.font(self, 11, wx.FONTWEIGHT_BOLD))
        dc.SetTextForeground(palette.on_surface)
        reading_width = dc.GetTextExtent(reading)[0] if reading else 0
        dc.DrawText(
            elide(dc, task.title, max(tokens.scaled(40), column - reading_width - 12)),
            left,
            line,
        )
        if reading:
            dc.DrawText(reading, rect.x + rect.width - reserved - reading_width, line)
        line += tokens.scaled(18)

        dc.SetFont(tokens.font(self, 9))
        if task.detail:
            # The detail stays ordinary ink even on a failed row: the error
            # role is reserved for the error line itself, and red-on-red made
            # the one sentence naming what was being written unreadable.
            dc.SetTextForeground(palette.on_surface_variant)
            dc.DrawText(elide(dc, task.detail, column), left, line)
            line += tokens.scaled(15)
        if task.unavailable:
            # The detail stays ordinary ink even on a failed row: the error
            # role is reserved for the error line itself, and red-on-red made
            # the one sentence naming what was being written unreadable.
            dc.SetTextForeground(palette.on_surface_variant)
            dc.DrawText(elide(dc, task.unavailable, column), left, line)
            line += tokens.scaled(15)
        if failed and task.error:
            dc.SetTextForeground(palette.error)
            dc.DrawText(elide(dc, task.error.splitlines()[0], column), left, line)

    @staticmethod
    def _reading(task: ProgressTask) -> str:
        """Return the short reading drawn beside the title.

        Work with no fraction says so in words.  Leaving it blank would read as
        a percentage the interface forgot to fill in, and showing ``0%`` would
        be a measurement nobody took.
        """
        if task.state == FAILED:
            return studio_label("Failed", "失敗")
        if task.state == DONE:
            return studio_label("Done", "完成")
        percent = task.percent()
        if percent is None:
            return studio_label("Working…", "進行中…")
        return f"{percent}%"


__all__ = ["ProgressOverlay", "BAR_HEIGHT", "PULSE_INTERVAL_MS"]
