"""The startup and world-loading surface.

Before this existed the application showed its own half-built skeleton while it
worked: empty panels, unpainted controls, a status bar reporting into a window
nobody could read yet.  A partially drawn interface is the worst thing to show
during a wait, because it is indistinguishable from a broken one -- the reader
cannot tell whether the application is loading or has failed.

So the wait gets a surface of its own.  It names what is happening, shows real
progress for the stages that can report it, and says plainly when a stage fails
rather than sitting on a spinner that means nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

import wx

from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.copy import studio_label, studio_text
from amulet_map_editor.api.studio.widgets import (
    StudioButton,
    _Themed,
    elide,
    invoke,
    paint_context,
)

log = logging.getLogger(__name__)

#: The states a stage can be in.  "failed" is deliberately as ordinary as the
#: others: a load that fails must look like a reported outcome, not an absence.
PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


def draw_determinate_bar(
    dc: wx.DC, rect: wx.Rect, fraction: float, palette: tokens.StudioPalette
) -> None:
    """Draw a track with ``fraction`` of it filled.

    A fraction of zero draws the empty track and stops.  That is the appearance
    of "nothing has happened yet", and it is deliberately *not* the appearance
    of :func:`draw_indeterminate_band` -- see that function.
    """
    radius = rect.height // 2
    tokens.draw_round_rect(dc, rect, radius, palette.surface_container_high, None)
    if fraction <= 0:
        return
    filled = wx.Rect(
        rect.x, rect.y, max(rect.height, int(rect.width * fraction)), rect.height
    )
    tokens.draw_round_rect(dc, filled, radius, palette.primary, None)


def draw_indeterminate_band(
    dc: wx.DC,
    rect: wx.Rect,
    pulse: float,
    palette: tokens.StudioPalette,
    *,
    still: bool = False,
) -> None:
    """Draw work that cannot report a fraction, and must not look like zero.

    "Cannot say" is not "nothing yet", so this never draws a bar filled from
    the left: a reader who sees one reads a percentage off it, and here there
    is no percentage to read.  Instead a short band travels the track.

    ``still`` is the reduced-motion appearance, and it is the case worth
    stating.  A stationary band would be the exact shape of a partly-filled
    determinate bar and would be read as one, so motion off does not mean "the
    same picture, frozen": the track is drawn as evenly spaced segments across
    its whole width, which cannot be read as a fill level at all.
    """
    tokens.draw_round_rect(dc, rect, 2, palette.surface_container_high, None)
    if rect.width <= 0 or rect.height <= 0:
        return
    if still:
        segment = max(tokens.scaled(8), rect.width // 12)
        gap = max(tokens.scaled(5), segment // 2)
        x = rect.x
        while x < rect.GetRight():
            width = min(segment, rect.GetRight() - x)
            if width <= 0:
                break
            tokens.draw_round_rect(
                dc, wx.Rect(x, rect.y, width, rect.height), 2, palette.primary, None
            )
            x += segment + gap
        return
    span = max(tokens.scaled(40), rect.width // 4)
    start = rect.x + int((rect.width + span) * pulse) - span
    # The band is the *intersection* of its travel with the track, so it grows
    # in from the left edge and shrinks out at the right one.  Clamping the
    # left edge while keeping the full width -- which is the obvious way to
    # write this -- pins the band at the left for the first fifth of every
    # cycle, so an indeterminate indicator spends that fifth apparently
    # stationary.  A progress indicator that stops moving is read as work that
    # has stopped, which is the one thing this band exists to deny.
    left = max(rect.x, start)
    right = min(rect.GetRight(), start + span)
    # The intersection above is exactly zero width at ``pulse == 0.0`` -- the
    # seam where one lap ends and the next begins -- and a row starts life at
    # exactly that pulse, before its first tick has ever run.  A band that is
    # genuinely invisible there paints the same pixels as an empty determinate
    # bar at fraction zero, which is precisely the confusion this function
    # exists to prevent.  So the band keeps a minimum floor width at the edge
    # it is arriving from or departing to, rather than ever vanishing.
    floor = min(rect.width, max(tokens.scaled(6), 2))
    if right - left < floor:
        if pulse < 0.5:
            left = rect.x
            right = min(rect.GetRight(), rect.x + floor)
        else:
            right = rect.GetRight()
            left = max(rect.x, right - floor)
    if right > left:
        tokens.draw_round_rect(
            dc,
            wx.Rect(left, rect.y, right - left, rect.height),
            2,
            palette.primary,
            None,
        )


@dataclass
class Stage:
    """One named step of a load, with an honest state and optional progress."""

    key: str
    label: str
    detail: str = ""
    state: str = PENDING
    #: ``None`` means this stage cannot report a fraction, which is different
    #: from reporting zero.  An indeterminate stage draws a moving band; a
    #: stage at 0.0 draws an empty bar, and those must not look the same.
    fraction: Optional[float] = None
    error: str = ""

    def is_finished(self) -> bool:
        return self.state in (DONE, FAILED)


@dataclass
class LoadingModel:
    """What the loading surface is currently showing."""

    title: str = "Starting"
    subtitle: str = ""
    stages: List[Stage] = field(default_factory=list)

    def stage(self, key: str) -> Optional[Stage]:
        for item in self.stages:
            if item.key == key:
                return item
        return None

    def overall(self) -> float:
        """Return the whole load's progress, counting unreportable stages."""
        if not self.stages:
            return 0.0
        total = 0.0
        for item in self.stages:
            if item.state == DONE:
                total += 1.0
            elif item.state == RUNNING and item.fraction is not None:
                total += max(0.0, min(1.0, item.fraction))
        return total / len(self.stages)

    def failed(self) -> Sequence[Stage]:
        return [item for item in self.stages if item.state == FAILED]


def renderer_stages() -> List[Stage]:
    """Return the stages the renderer actually reports, in the order it runs."""
    return [
        Stage(
            "packs",
            studio_label("Loading resource packs", "載入資源包"),
            studio_label("Vanilla plus any configured packs", "原版加已設定嘅資源包"),
        ),
        Stage(
            "atlas",
            studio_label("Creating texture atlas", "建立材質圖集"),
            studio_label("Packed per platform", "按平台打包"),
        ),
        Stage(
            "renderer",
            studio_label("Setting up renderer", "設定繪圖引擎"),
            studio_label(
                "OpenGL context and chunk generator", "OpenGL 內容同區塊產生器"
            ),
        ),
        Stage(
            "chunks",
            studio_label("Loading chunks", "載入區塊"),
            studio_label("The area around the camera first", "先載入鏡頭附近"),
        ),
    ]


class LoadingView(wx.Panel, _Themed):
    """A full-surface, honest progress screen for a slow start."""

    BAR_HEIGHT = 6
    ROW_HEIGHT = 46

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_background: Optional[Callable[[], None]] = None,
        on_retry: Optional[Callable[[], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.model = LoadingModel(stages=renderer_stages())
        self.on_background = on_background
        self.on_retry = on_retry
        self.on_cancel = on_cancel
        self._pulse = 0.0

        self.actions = wx.BoxSizer(wx.HORIZONTAL)
        self.background_button = StudioButton(
            self,
            studio_label("Run in background", "喺背景繼續"),
            variant="outlined",
            on_click=lambda: invoke(self.on_background),
            name="Continue loading in the background",
        )
        self.retry_button = StudioButton(
            self,
            studio_label("Retry", "重試"),
            variant="tonal",
            on_click=lambda: invoke(self.on_retry),
            name="Retry the failed loading stage",
        )
        self.retry_button.Hide()
        self.cancel_button = StudioButton(
            self,
            studio_label("Cancel", "取消"),
            variant="text",
            on_click=lambda: invoke(self.on_cancel),
            name="Cancel loading",
        )
        self.actions.Add(self.retry_button, 0, wx.RIGHT, tokens.SPACE_SM)
        self.actions.Add(self.background_button, 0, wx.RIGHT, tokens.SPACE_SM)
        self.actions.Add(self.cancel_button, 0)

        root = wx.BoxSizer(wx.VERTICAL)
        root.AddStretchSpacer()
        root.Add(self.actions, 0, wx.ALIGN_CENTRE)
        root.AddSpacer(tokens.scaled(tokens.SPACE_XL))
        self.SetSizer(root)

        self._install("Loading")
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_tick, self._timer)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(), event.Skip()))
        self._timer.Start(60)

    # -- state ---------------------------------------------------------------
    def set_title(self, title: str, subtitle: str = "") -> None:
        """Name what is loading, so a wait is never anonymous."""
        self.model.title = title
        self.model.subtitle = subtitle
        self.Refresh()

    def set_stage(
        self,
        key: str,
        *,
        state: Optional[str] = None,
        fraction: Optional[float] = None,
        detail: Optional[str] = None,
        error: str = "",
    ) -> None:
        """Update one stage. A failure is shown, never swallowed."""
        stage = self.model.stage(key)
        if stage is None:
            stage = Stage(key=key, label=key)
            self.model.stages.append(stage)
        if state is not None:
            stage.state = state
        if fraction is not None:
            stage.fraction = max(0.0, min(1.0, fraction))
        if detail is not None:
            stage.detail = detail
        if error:
            stage.error = error
            stage.state = FAILED
        self.retry_button.Show(bool(self.model.failed()))
        self.Layout()
        self.Refresh()

    def finished(self) -> bool:
        return all(stage.is_finished() for stage in self.model.stages)

    def stop(self) -> None:
        """Stop animating; the surface is about to be replaced."""
        if self._timer.IsRunning():
            self._timer.Stop()

    def _on_tick(self, _event: wx.TimerEvent) -> None:
        # Only animate while something is genuinely indeterminate, so a stalled
        # load does not keep drawing motion that implies progress.
        moving = any(
            stage.state == RUNNING and stage.fraction is None
            for stage in self.model.stages
        )
        if not moving:
            return
        self._pulse = (self._pulse + 0.02) % 1.0
        self.Refresh()

    # -- painting ------------------------------------------------------------
    def _backdrop(self) -> wx.Colour:
        return tokens.palette().surface

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the whole loading surface into ``dc`` at ``rect``."""
        palette = tokens.palette()
        # Fill first. A paint handler receives a cleared device context; a
        # direct render_to call does not, so without this the surface draws onto
        # whatever the target bitmap held and reads as a contrast failure that
        # does not exist on screen.
        dc.SetBrush(wx.Brush(palette.surface))
        dc.SetPen(wx.Pen(palette.surface))
        dc.DrawRectangle(rect)
        width, height = rect.width, rect.height
        centre = rect.x + width // 2
        column = min(tokens.scaled(520), width - tokens.scaled(64))
        left = centre - column // 2
        top = rect.y + max(tokens.scaled(64), height // 2 - tokens.scaled(210))

        mark = tokens.scaled(40)
        tokens.draw_round_rect(
            dc,
            wx.Rect(left, top, mark, mark),
            tokens.scaled(12),
            palette.primary,
            None,
        )

        dc.SetTextForeground(palette.on_surface)
        dc.SetFont(tokens.font(self, 20, wx.FONTWEIGHT_NORMAL))
        dc.DrawText(
            elide(dc, self.model.title, column - mark - 16), left + mark + 16, top + 2
        )

        if self.model.subtitle:
            dc.SetTextForeground(palette.on_surface_variant)
            dc.SetFont(tokens.font(self, 10))
            dc.DrawText(
                elide(dc, self.model.subtitle, column - mark - 16),
                left + mark + 16,
                top + tokens.scaled(26),
            )

        bar_top = top + mark + tokens.scaled(26)
        self._draw_bar(
            dc,
            wx.Rect(left, bar_top, column, tokens.scaled(self.BAR_HEIGHT)),
            self.model.overall(),
            palette,
        )

        row_top = bar_top + tokens.scaled(30)
        dc.SetFont(tokens.font(self, 10))
        for stage in self.model.stages:
            self._draw_stage(dc, stage, left, row_top, column, palette)
            row_top += tokens.scaled(self.ROW_HEIGHT)

        failures = self.model.failed()
        if failures:
            dc.SetTextForeground(palette.error)
            dc.SetFont(tokens.font(self, 10))
            message = studio_text(
                failures[0].error or "A loading stage failed.",
                "有一個載入步驟失敗咗。",
            ).splitlines()[0]
            dc.DrawText(elide(dc, message, column), left, row_top + tokens.scaled(6))

    def _draw_bar(self, dc: wx.DC, rect: wx.Rect, fraction: float, palette) -> None:
        draw_determinate_bar(dc, rect, fraction, palette)

    def _draw_stage(
        self, dc: wx.DC, stage: Stage, left: int, top: int, column: int, palette
    ) -> None:
        marks = {
            DONE: ("✓", palette.primary),
            RUNNING: ("●", palette.primary),
            FAILED: ("×", palette.error),
            PENDING: ("○", palette.outline),
        }
        glyph, colour = marks.get(stage.state, marks[PENDING])
        dc.SetTextForeground(colour)
        dc.SetFont(tokens.font(self, 11))
        dc.DrawText(glyph, left, top + tokens.scaled(2))

        dc.SetTextForeground(
            palette.on_surface if stage.state != PENDING else palette.on_surface_variant
        )
        dc.SetFont(tokens.font(self, 11))
        dc.DrawText(
            elide(dc, stage.label, column - tokens.scaled(24)),
            left + tokens.scaled(22),
            top,
        )

        detail = stage.error or stage.detail
        if detail:
            dc.SetTextForeground(
                palette.error if stage.error else palette.on_surface_variant
            )
            dc.SetFont(tokens.font(self, 9))
            dc.DrawText(
                elide(dc, detail, column - tokens.scaled(24)),
                left + tokens.scaled(22),
                top + tokens.scaled(16),
            )

        if stage.state == RUNNING:
            track = wx.Rect(
                left + tokens.scaled(22),
                top + tokens.scaled(32),
                column - tokens.scaled(22),
                tokens.scaled(4),
            )
            if stage.fraction is None:
                # Indeterminate: a travelling band, visibly different from an
                # empty bar, because "cannot say" is not "nothing yet".
                draw_indeterminate_band(dc, track, self._pulse, palette)
            else:
                self._draw_bar(dc, track, stage.fraction, palette)
