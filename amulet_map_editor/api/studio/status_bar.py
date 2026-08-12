"""The workspace status bar: live state, revision, selection, camera, and view.

The design draws this strip as a row of small readouts, but every one of them
reports something the workspace actually knows and three of them change it: the
revision pill opens the project history, the speed slider moves the renderer's
own camera, and the segmented control switches its projection.  Nothing here is
painted decoration -- a control that looks operable and is not is the defect
this shell exists to remove, and a status bar is exactly where that defect hides
best.

Every number the bar shows is read from the world the user has open, through
:mod:`amulet_map_editor.api.studio.context`, and re-read whenever that world
changes.  With no world open the bar says so rather than keeping the last
world's figures on screen, because a stale number and a live one look identical.

The bar keeps a fixed height, so every string it shows is collapsed onto one
line: bilingual copy arrives as two lines and would otherwise be cut in half.
The full text stays reachable through each control's tooltip and accessible
name.

This module also holds the shared readers the navigator and the properties pane
use -- the viewport canvas the world context is attached to, and the project's
own local-history events -- so the three panes can never disagree about the same
fact.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api import local_history
from amulet_map_editor.api.studio import context, tokens
from amulet_map_editor.api.studio.copy import studio_label, studio_text
from amulet_map_editor.api.studio.widgets import (
    Divider,
    StudioButton,
    elide,
    invoke,
    paint_context,
    point_size,
)

log = logging.getLogger(__name__)

#: The design's status bar height, in design pixels.
BAR_HEIGHT = 34

#: The renderer advances the camera by ``move_speed`` blocks on every 33ms
#: frame, so blocks per second is that value scaled by the frame rate.  The
#: conversion is the editor's own, kept in one place so this slider and the
#: editor's own speed dialog can never report different numbers for the same
#: camera.
CAMERA_FRAME_MS = 33

#: The camera speed slider's bounds, in blocks per second.  The ceiling is well
#: above the renderer's shipped speed so the slider can reach it rather than
#: silently clamping the value the editor is actually flying at.
MIN_CAMERA_SPEED = 1
MAX_CAMERA_SPEED = 200

#: The blocks-per-second the renderer ships with, derived from its own
#: ``move_speed`` of 2.0 rather than chosen here.
DEFAULT_CAMERA_SPEED = 61

#: The two projections the segmented control switches between.
PROJECTIONS: Tuple[Tuple[str, str], ...] = (("3d", "3D"), ("top", "Top"))

#: How many of a project's local-history events are read back at once.  A
#: project that has more than this says so rather than pretending the older
#: ones do not exist.
MAX_PROJECT_REVISIONS = 200

#: The status dot's ink per tone.  A tone never rewrites the message: it only
#: says how loudly to draw the dot beside it.
_TONES: Tuple[str, ...] = ("ready", "busy", "warning", "error")

_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL)


def single_line(text: str) -> str:
    """Collapse a possibly bilingual string onto one line for a fixed-height bar.

    Bilingual mode returns an English line above a Cantonese one.  A 34px bar
    cannot show two lines, and silently painting only the first would hide half
    the copy from a bilingual reader, so both are joined with the separator the
    design already uses between facts.
    """
    parts = [part.strip() for part in str(text).splitlines() if part.strip()]
    return " · ".join(parts)


# ----------------------------------------------------------------------
# shared readers: the renderer canvas and the project's own history
# ----------------------------------------------------------------------


def studio_canvas() -> Any:
    """Return the viewport canvas the world context is attached to, or ``None``.

    The context module is the one place that is handed the renderer, so the
    panes ask it rather than each keeping their own reference that could go
    stale the moment a world is closed.  A public accessor is preferred when
    the context grows one; until then the attribute it stores the canvas in is
    read directly, which is still one reader rather than three.
    """
    getter = getattr(context, "canvas", None)
    if callable(getter):
        try:
            return getter()
        except Exception:  # noqa: BLE001 - a canvas mid-teardown answers this
            return None
    return getattr(context, "_canvas", None)


def project_key_for(ctx: Optional[context.WorldContext] = None) -> str:
    """Return the key one project's own records are stored under.

    A world's folder identifies it better than its name does -- two worlds can
    share a name and no two share a path -- so the path is preferred and the
    name is the fallback for a world that reports no path.
    """
    if ctx is None:
        ctx = context.current()
    if not ctx.open:
        return ""
    return str(ctx.path or ctx.name or "")


def project_record_ids(project_key: str) -> Tuple[str, ...]:
    """Return the local-history record ids one project writes its work under."""
    key = str(project_key)
    if not key:
        return ()
    return (f"studio-project-{key}", f"studio-note-{key}")


def history_store() -> Any:
    """Return the local history store, or ``None`` when it cannot be opened.

    A profile that cannot hold a repository is a real state -- a read-only
    home directory, no ``git`` on the path -- and it is reported to the caller
    so a surface can say the history is unavailable instead of showing an empty
    list that reads as a project with no history.
    """
    return local_history.LocalHistory.try_create()


_history_cache: Dict[str, Tuple[Any, ...]] = {}
_history_available: Dict[str, bool] = {}


def invalidate_project_history(project_key: str = "") -> None:
    """Forget the read-back events for one project, or for every project."""
    key = str(project_key)
    if key:
        _history_cache.pop(key, None)
        _history_available.pop(key, None)
        return
    _history_cache.clear()
    _history_available.clear()


def project_history_events(
    project_key: str, *, refresh: bool = False
) -> Tuple[Tuple[Any, ...], bool]:
    """Return one project's history events, newest first, and whether it read.

    The second value separates "this project has recorded nothing yet" from
    "the history could not be read at all", which are different things to tell
    the user and would otherwise both render as an empty list.

    Reading walks every event file the profile holds, so the result is kept
    until :func:`invalidate_project_history` drops it rather than being redone
    on every repaint.
    """
    key = str(project_key)
    if not key:
        return (), True
    if not refresh and key in _history_cache:
        return _history_cache[key], _history_available.get(key, True)
    wanted = set(project_record_ids(key))
    store = history_store()
    if store is None:
        _history_cache[key] = ()
        _history_available[key] = False
        return (), False
    try:
        found = store.events(limit=MAX_PROJECT_REVISIONS)
    except Exception:  # noqa: BLE001 - a corrupt event never breaks a pane
        log.exception("Could not read the local history for project %r", key)
        _history_cache[key] = ()
        _history_available[key] = False
        return (), False
    events = tuple(event for event in found if event.record_id in wanted)
    _history_cache[key] = events
    _history_available[key] = True
    return events, True


def restore_history_event(event_id: str) -> Any:
    """Restore one history event by appending a new one, or return ``None``.

    Restoring never rewrites the entry it restored from: the store writes the
    earlier state back as a fresh event, so the state being replaced stays in
    the list and stays restorable in its turn.
    """
    store = history_store()
    if store is None:
        return None
    restored = store.safe_restore(str(event_id))
    if restored is not None:
        invalidate_project_history()
    return restored


# ----------------------------------------------------------------------
# shared readers: the camera
# ----------------------------------------------------------------------


def blocks_per_second(move_speed: float) -> int:
    """Return a renderer ``move_speed`` as whole blocks per second."""
    return int(round(float(move_speed) * 1000 / CAMERA_FRAME_MS))


def move_speed_for(blocks: float) -> float:
    """Return the renderer ``move_speed`` that flies at ``blocks`` per second."""
    return float(blocks) * CAMERA_FRAME_MS / 1000


def camera_speed(canvas: Any = None) -> Optional[int]:
    """Return how fast the renderer's camera is flying, or ``None``.

    ``None`` says there is no camera to ask, which is why the slider disables
    itself rather than showing a number that would move nothing.
    """
    target = studio_canvas() if canvas is None else canvas
    try:
        return blocks_per_second(target.camera.move_speed)
    except Exception:  # noqa: BLE001 - no canvas, or one without a camera yet
        return None


def set_camera_speed(value: int, canvas: Any = None) -> bool:
    """Fly the renderer's camera at ``value`` blocks per second."""
    target = studio_canvas() if canvas is None else canvas
    try:
        target.camera.move_speed = move_speed_for(value)
    except Exception as err:  # noqa: BLE001 - a canvas being torn down
        log.debug("The camera speed could not be set: %s", err)
        return False
    return True


def camera_projection(canvas: Any = None) -> str:
    """Return the renderer's projection as this bar's key, or ``""``."""
    target = studio_canvas() if canvas is None else canvas
    try:
        from amulet_map_editor.api.opengl.camera import Projection
    except Exception:  # noqa: BLE001 - a build with no OpenGL bindings
        return ""
    try:
        return "top" if target.camera.projection_mode is Projection.TOP_DOWN else "3d"
    except Exception:  # noqa: BLE001 - no canvas to ask
        return ""


def set_camera_projection(key: str, canvas: Any = None) -> bool:
    """Switch the renderer between its perspective and top-down projections."""
    target = studio_canvas() if canvas is None else canvas
    try:
        from amulet_map_editor.api.opengl.camera import Projection
    except Exception:  # noqa: BLE001 - a build with no OpenGL bindings
        return False
    try:
        target.camera.projection_mode = (
            Projection.TOP_DOWN if str(key) == "top" else Projection.PERSPECTIVE
        )
    except Exception as err:  # noqa: BLE001 - a canvas being torn down
        log.debug("The camera projection could not be set: %s", err)
        return False
    return True


# ----------------------------------------------------------------------
# shared readers: the selection
# ----------------------------------------------------------------------


def selection_text(ctx: Optional[context.WorldContext] = None) -> str:
    """Return the selection readout for the world that is open.

    The delta is the distance between the first and last block a box contains,
    which is one less than its extent, because that is the number a person
    reads off two opposite corners in the viewport.
    """
    if ctx is None:
        ctx = context.current()
    if not ctx.open:
        return "No world open"
    bounds = ctx.selection_bounds()
    if bounds is None or not ctx.selection_boxes:
        return "No selection"
    low, high = bounds
    extent = tuple(max(0, high[axis] - low[axis]) for axis in range(3))
    delta = tuple(max(0, value - 1) for value in extent)
    size = "x".join(str(value) for value in extent)
    volume = f"{ctx.selection_volume:,} blocks"
    if len(ctx.selection_boxes) > 1:
        # The extent is the box that encloses every selection box, while the
        # volume is the blocks the boxes actually cover.  Those are different
        # numbers whenever there is more than one box, so the label says which
        # is which rather than leaving them side by side to be misread.
        return f"{len(ctx.selection_boxes)} boxes · bounds {size} · {volume}"
    return f"dx={delta[0]}, dy={delta[1]}, dz={delta[2]} · {size} · {volume}"


def dimension_text(ctx: Optional[context.WorldContext] = None) -> str:
    """Return the dimension being edited, or an honest absence."""
    if ctx is None:
        ctx = context.current()
    if not ctx.open:
        return "No dimension"
    return ctx.dimension or "This world reports no dimensions"


def world_status_text(ctx: Optional[context.WorldContext] = None) -> str:
    """Return what the bar's leftmost readout says about the open world."""
    if ctx is None:
        ctx = context.current()
    if not ctx.open:
        return studio_text("No world is open", "而家未開世界")
    parts = [ctx.name or "Unnamed world"]
    version = ctx.game_version or " ".join(
        part for part in (ctx.platform, ctx.version) if part
    )
    if version:
        parts.append(version)
    return " · ".join(parts)


def open_studio_menu(
    window: wx.Window,
    key: str,
    position: wx.Point,
    on_surface: Optional[Callable[[str], None]],
    on_command: Optional[Callable[[str], None]],
) -> None:
    """Open one of the shared searchable context menus over ``window``.

    The menus live in a module another part of the shell owns and construct a
    popup window, so the import is deferred: importing it here would make this
    module need a display before it could even be read.
    """
    try:
        from amulet_map_editor.api.studio import context_menu
    except ImportError:
        log.debug("The shared Studio context menus are not available")
        return
    try:
        context_menu.open_context_menu(
            window, key, position, on_surface=on_surface, on_command=on_command
        )
    except Exception:
        log.exception("Could not open the %r context menu", key)


def clear_container(
    sizer: wx.Sizer, panel: wx.Window, keep: Sequence[wx.Window] = ()
) -> None:
    """Empty a rebuilt list without destroying a window in mid-event.

    Every list in the workspace is rebuilt from inside the click of one of its
    own rows, and destroying a window while it is still handling an event is
    how wx tears the ground out from under itself.  The old rows are detached
    from the layout now and destroyed once the handler has returned, so the
    rebuilt list is correct immediately and nothing is deleted too early.
    """
    sizer.Clear(delete_windows=False)
    for child in list(panel.GetChildren()):
        if any(child is protected for protected in keep):
            continue
        try:
            if child.IsBeingDeleted():
                continue
            child.Hide()
            destroy_later = getattr(child, "DestroyLater", None)
            if callable(destroy_later):
                destroy_later()
            else:  # pragma: no cover - wxPython older than 4.0.4
                wx.CallAfter(child.Destroy)
        except RuntimeError:
            # The window has already gone; there is nothing left to tidy.
            continue


class BarLabel(wx.Control):
    """One read-only line of bar text, in the interface or monospaced face.

    It is a control rather than a ``wx.StaticText`` because the bar's ink comes
    from the live palette and the text has to elide rather than clip when the
    window narrows; both are painted here so a theme change or a resize leaves
    the row readable instead of truncated mid-character.
    """

    def __init__(
        self,
        parent: wx.Window,
        text: str = "",
        *,
        mono: bool = False,
        name: str = "",
        size_px: int = 12,
        emphasis: bool = False,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self._text = ""
        self._mono = bool(mono)
        self._size_px = int(size_px)
        self._label = str(name)
        self._emphasis = bool(emphasis)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.set_text(text)

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def _font(self) -> wx.Font:
        weight = _MEDIUM if self._emphasis else wx.FONTWEIGHT_NORMAL
        if self._mono:
            return tokens.mono_font_px(self, point_size(self._size_px), weight)
        return tokens.font_px(self, point_size(self._size_px), weight)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(self._font())
        width, height = dc.GetTextExtent(self._text or " ")
        return wx.Size(width + tokens.scaled(2), max(height, tokens.scaled(16)))

    def text(self) -> str:
        """Return the string currently shown."""
        return self._text

    def set_text(self, text: str) -> None:
        """Replace the text, its accessible name, and the space it asks for."""
        self._text = single_line(text)
        self.SetName(self._label or self._text or "Status")
        if self._text:
            self.SetToolTip(self._text)
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def refresh_theme(self) -> None:
        """Re-measure for the current density and repaint in the live palette."""
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        gcdc.SetFont(self._font())
        gcdc.SetTextForeground(
            palette.on_surface if self._emphasis else palette.on_surface_variant
        )
        gcdc.DrawText(
            elide(gcdc, self._text, width), 0, (height - gcdc.GetCharHeight()) // 2
        )
        del gcdc


class StatusReadout(wx.Control):
    """The tone dot and the status message it belongs to, drawn as one line."""

    DOT = 7

    def __init__(self, parent: wx.Window, text: str, *, tone: str = "ready") -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self._text = single_line(text)
        self._tone = tone if tone in _TONES else "ready"
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self._announce()
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def _announce(self) -> None:
        self.SetName(f"Status, {self._tone}: {self._text}")
        self.SetToolTip(self._text)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font_px(self, point_size(12)))
        width, height = dc.GetTextExtent(self._text or " ")
        return wx.Size(
            width + tokens.scaled(self.DOT) + tokens.scaled(8),
            max(height, tokens.scaled(16)),
        )

    def set_status(self, text: str, tone: str = "ready") -> None:
        """Replace the message and the tone of the dot beside it."""
        self._text = single_line(text)
        self._tone = tone if tone in _TONES else "ready"
        self._announce()
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def text(self) -> str:
        """Return the message currently shown."""
        return self._text

    def tone(self) -> str:
        """Return the current tone name."""
        return self._tone

    def refresh_theme(self) -> None:
        """Re-measure and repaint against the live palette."""
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _dot_colour(self, palette: tokens.StudioPalette) -> wx.Colour:
        if self._tone == "error":
            return palette.error
        if self._tone == "warning":
            return tokens.blend(palette.error, palette.primary, 0.35)
        if self._tone == "busy":
            return tokens.blend(palette.primary, palette.on_surface, 0.20)
        return palette.primary

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        dot = tokens.scaled(self.DOT)
        gcdc.SetBrush(wx.Brush(self._dot_colour(palette)))
        gcdc.SetPen(wx.TRANSPARENT_PEN)
        gcdc.DrawEllipse(0, (height - dot) // 2, dot, dot)
        left = dot + tokens.scaled(8)
        gcdc.SetFont(tokens.font_px(self, point_size(12)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        gcdc.DrawText(
            elide(gcdc, self._text, max(0, width - left)),
            left,
            (height - gcdc.GetCharHeight()) // 2,
        )
        del gcdc


#: What the revision pill says when the project has recorded nothing yet.  A
#: project with no history is a real and common state -- a world opened and not
#: yet edited -- and saying so is the difference between an empty history and a
#: history nobody could read.
NO_REVISIONS = "No revisions yet"

#: What it says when the profile could not hold a history repository at all.
NO_HISTORY_STORE = "History unavailable"


class RevisionPill(StudioButton):
    """The tinted monospaced button that names the head revision.

    Both the breadcrumb bar and the status bar show the same fact, so they show
    it through the same control: one place decides how a revision reads, and
    clicking either one lands on the same project history.

    A pill with no commit to name says so.  It never falls back to a plausible
    looking identifier, because a seven-character hash is exactly the kind of
    value a reader has no way of checking.
    """

    def __init__(
        self,
        parent: wx.Window,
        commit: str = "",
        count: int = 0,
        *,
        glyph: str = "⟲",
        suffix: str = "",
        on_click: Optional[Callable[[], None]] = None,
        height: int = 24,
    ) -> None:
        self.commit = str(commit)
        self.count = int(count)
        self.suffix = str(suffix)
        self.available = True
        super().__init__(
            parent,
            self._compose(),
            variant="pill",
            glyph=glyph,
            hint="Project history · unlimited undo",
            on_click=on_click,
            height=height,
        )
        # The identifier is a hash, and a hash is unreadable in a proportional
        # face; the shared button paints its label monospaced when asked.  The
        # label is set again afterwards so the button is measured in the face
        # it will actually be drawn in.
        self._mono = True
        self.SetLabel(self._compose())
        self._rename()

    def _compose(self) -> str:
        if not self.available:
            return NO_HISTORY_STORE
        if not self.commit or self.count <= 0:
            return NO_REVISIONS
        label = f"{self.commit} · {self.count}"
        return f"{label} {self.suffix}".rstrip() if self.suffix else label

    def _rename(self) -> None:
        if not self.available:
            self.SetName(
                "The project history could not be read from this profile. "
                "Opens the project history."
            )
            return
        if not self.commit or self.count <= 0:
            self.SetName(
                "No revision has been recorded for this project yet. "
                "Opens the project history."
            )
            return
        plural = "revision" if self.count == 1 else "revisions"
        self.SetName(
            f"Head revision {self.commit}, {self.count} {plural}. "
            "Opens the project history."
        )

    def set_revision(self, commit: str, count: int, *, available: bool = True) -> None:
        """Show a new head revision and revision count.

        ``available`` says whether the history could be read at all, so an
        unreadable profile reads differently from a project that has simply not
        been edited yet.
        """
        self.commit = str(commit)
        self.count = int(count)
        self.available = bool(available)
        self.SetLabel(self._compose())
        self._rename()

    def _state_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour, Optional[wx.Colour]]:
        if not self.IsEnabled():
            return (
                palette.surface_container,
                tokens.blend(palette.on_surface_variant, palette.surface, 0.45),
                None,
            )
        fill = palette.tint
        if self._pressed:
            fill = tokens.blend(palette.surface_container_high, palette.primary, 0.16)
        elif self._hovered:
            fill = palette.surface_container_high
        return fill, palette.on_primary_container, None


class _Segment(StudioButton):
    """One half of a segmented control, filled while it is the chosen one."""

    def __init__(
        self,
        parent: wx.Window,
        key: str,
        label: str,
        *,
        selected: bool,
        on_click: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.key = str(key)
        self.selected = bool(selected)
        self._on_select = on_click
        super().__init__(
            parent,
            label,
            variant="pill",
            on_click=self._choose,
            height=20,
            hint=f"Show the {label} view",
        )
        self._sync_name()

    def _choose(self) -> None:
        invoke(self._on_select, self.key)

    def _sync_name(self) -> None:
        state = "selected" if self.selected else "not selected"
        self.SetName(f"{self.GetLabel()} view, {state}")

    def set_selected(self, selected: bool) -> None:
        """Set the chosen state without running the callback."""
        self.selected = bool(selected)
        self._sync_name()
        self.Refresh()

    def _state_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour, Optional[wx.Colour]]:
        if self.selected:
            fill = palette.primary
            if self._pressed:
                fill = tokens.blend(fill, palette.on_primary, 0.18)
            elif self._hovered:
                fill = tokens.blend(fill, palette.on_primary, 0.10)
            return fill, palette.on_primary, None
        fill: Optional[wx.Colour] = None
        if self._pressed:
            fill = tokens.blend(
                palette.surface_container_high, palette.on_surface, 0.12
            )
        elif self._hovered:
            fill = tokens.blend(
                palette.surface_container_high, palette.on_surface, 0.06
            )
        return fill, palette.on_surface_variant, None


class SegmentedToggle(wx.Panel):
    """A rounded track holding one button per option, one of them chosen."""

    def __init__(
        self,
        parent: wx.Window,
        options: Sequence[Tuple[str, str]],
        value: str,
        *,
        on_change: Optional[Callable[[str], None]] = None,
        name: str = "View",
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_change = on_change
        self.value = str(value)
        self.SetName(name)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.segments: Dict[str, _Segment] = {}
        row = wx.BoxSizer(wx.HORIZONTAL)
        pad = tokens.scaled(2)
        for key, label in options:
            segment = _Segment(
                self, key, label, selected=key == self.value, on_click=self._choose
            )
            self.segments[key] = segment
            row.Add(segment, 0, wx.ALL, pad)
        self.SetSizer(row)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Fit()

    def _choose(self, key: str) -> None:
        self.set_value(key, notify=True)

    def set_value(self, key: str, *, notify: bool = False) -> None:
        """Choose an option, optionally reporting the change to the owner."""
        if key not in self.segments:
            return
        self.value = key
        for name, segment in self.segments.items():
            segment.set_selected(name == key)
        if notify:
            invoke(self.on_change, key)

    def refresh_theme(self) -> None:
        """Repaint the track and every segment on it."""
        for segment in self.segments.values():
            segment.refresh_theme()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.RADIUS_PILL,
            palette.surface_container_high,
        )
        del gcdc


class StatusBar(wx.Panel):
    """The 34px strip under the viewport, wired to the world it describes.

    The bar holds no copy of the truth.  Its readouts are re-read from the open
    world every time that world changes, its speed slider moves the renderer's
    own camera, and its projection toggle switches the renderer's own
    projection, so what it shows and what the editor is doing cannot drift
    apart.  The owner may still push a message of its own -- saved or unsaved
    is the workspace's fact, not the world's -- and those setters remain.
    """

    HEIGHT = BAR_HEIGHT

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_history: Optional[Callable[[], None]] = None,
        on_speed: Optional[Callable[[int], None]] = None,
        on_projection: Optional[Callable[[str], None]] = None,
        on_surface: Optional[Callable[[str], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
        status: str = "",
        commit: str = "",
        revisions: int = 0,
        selection: str = "",
        dimension: str = "",
        speed: Optional[int] = None,
        projection: str = "",
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_history = on_history
        self.on_speed = on_speed
        self.on_projection = on_projection
        self.on_surface = on_surface
        self.on_command = on_command
        self.SetName("Workspace status bar")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        ctx = context.current()
        live_speed = camera_speed()
        self.readout = StatusReadout(
            self, status or world_status_text(ctx), tone="ready"
        )
        self.revision = RevisionPill(
            self, commit, revisions, on_click=self._open_history
        )
        self.selection = BarLabel(
            self,
            selection or selection_text(ctx),
            mono=True,
            name="Selection size",
        )
        self.dimension = BarLabel(
            self, dimension or dimension_text(ctx), name="Active dimension"
        )
        self.speed_caption = BarLabel(self, studio_label("Speed"), name="Camera speed")
        self.speed_slider = wx.Slider(
            self,
            value=self._clamp_speed(
                speed if speed is not None else (live_speed or DEFAULT_CAMERA_SPEED)
            ),
            minValue=MIN_CAMERA_SPEED,
            maxValue=MAX_CAMERA_SPEED,
            style=wx.SL_HORIZONTAL,
        )
        self.speed_slider.SetName("Camera speed in blocks per second")
        self.speed_slider.SetToolTip(
            single_line(
                studio_text(
                    "How fast the camera flies, in blocks per second.",
                    "鏡頭飛得幾快，每秒幾多格。",
                )
            )
        )
        self.speed_slider.SetMinSize(wx.Size(tokens.scaled(96), -1))
        self.speed_slider.Bind(wx.EVT_SLIDER, self._on_speed)
        self.speed_value = BarLabel(
            self,
            f"{self.speed()} b/s",
            mono=True,
            name="Camera speed readout",
        )
        chosen_projection = str(projection) or camera_projection() or "3d"
        self.projection_toggle = SegmentedToggle(
            self,
            PROJECTIONS,
            chosen_projection if chosen_projection in dict(PROJECTIONS) else "3d",
            on_change=self._on_projection,
            name="Viewport projection",
        )
        self._rules = [Divider(self, vertical=True) for _ in range(3)]

        gap = tokens.scaled(tokens.SPACE_SM + 4)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.readout, 0, wx.ALIGN_CENTER_VERTICAL)
        row.Add(self.revision, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        row.AddStretchSpacer(1)
        row.Add(self.selection, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        row.Add(self._rules[0], 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        row.Add(self.dimension, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        row.Add(self._rules[1], 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        row.Add(self.speed_caption, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        row.Add(
            self.speed_slider,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_SM),
        )
        row.Add(
            self.speed_value,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_SM),
        )
        row.Add(self._rules[2], 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        row.Add(self.projection_toggle, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)
        frame = wx.BoxSizer(wx.HORIZONTAL)
        frame.Add(row, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, tokens.scaled(12))
        self.SetSizer(frame)
        self.SetMinSize(wx.Size(-1, tokens.scaled(self.HEIGHT)))

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        context.subscribe(self._on_world_context)
        self._apply_theme()
        self.apply_context(ctx)

    # -- the open world ------------------------------------------------------
    def _on_world_context(self, ctx: context.WorldContext) -> None:
        """Take a world change from any thread onto the one wx paints on."""
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:
            return
        if wx.IsMainThread():
            self.apply_context(ctx)
        else:
            wx.CallAfter(self.apply_context, ctx)

    def apply_context(self, ctx: Optional[context.WorldContext] = None) -> None:
        """Re-read every readout from the world that is open right now."""
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:
            return
        if ctx is None:
            ctx = context.current()
        self.readout.set_status(world_status_text(ctx), "ready" if ctx.open else "busy")
        self.selection.set_text(selection_text(ctx))
        self.dimension.set_text(dimension_text(ctx))
        self.refresh_revision(ctx)
        self.sync_camera()
        self.Layout()

    def refresh_revision(self, ctx: Optional[context.WorldContext] = None) -> None:
        """Re-read the head revision and revision count from the project."""
        key = project_key_for(ctx)
        if not key:
            self.revision.set_revision("", 0)
            self.revision.Enable(False)
            return
        events, available = project_history_events(key)
        self.revision.Enable(True)
        self.revision.set_revision(
            events[0].event_id[:7] if events else "",
            len(events),
            available=available,
        )

    def sync_camera(self) -> None:
        """Show what the renderer's camera is actually doing, or disable both.

        A slider that moves nothing is the defect this bar exists to remove, so
        with no renderer attached it is disabled and says why rather than
        sitting there at a number that controls nothing.
        """
        canvas = studio_canvas()
        live_speed = camera_speed(canvas)
        if live_speed is None:
            self.speed_slider.Enable(False)
            self.speed_slider.SetToolTip(
                single_line(
                    studio_text(
                        "No renderer is attached, so there is no camera to speed "
                        "up or slow down.",
                        "而家未接住個繪圖器，所以冇鏡頭可以加減速。",
                    )
                )
            )
            self.speed_value.set_text("no camera")
        else:
            self.speed_slider.Enable(True)
            self.speed_slider.SetToolTip(
                single_line(
                    studio_text(
                        "How fast the camera flies, in blocks per second.",
                        "鏡頭飛得幾快，每秒幾多格。",
                    )
                )
            )
            self.speed_slider.SetValue(self._clamp_speed(live_speed))
            self.speed_value.set_text(f"{self._clamp_speed(live_speed)} b/s")
        projection = camera_projection(canvas)
        if projection:
            self.projection_toggle.set_value(projection)

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            context.unsubscribe(self._on_world_context)
        event.Skip()

    # -- state ---------------------------------------------------------------
    @staticmethod
    def _clamp_speed(value: int) -> int:
        try:
            number = int(round(float(value)))
        except (TypeError, ValueError):
            return DEFAULT_CAMERA_SPEED
        return max(MIN_CAMERA_SPEED, min(MAX_CAMERA_SPEED, number))

    def set_status_text(self, text: str, tone: str = "ready") -> None:
        """Replace the message and dot beside it, then re-lay the row out."""
        self.readout.set_status(text, tone)
        self.Layout()

    def status_text(self) -> str:
        """Return the message currently shown."""
        return self.readout.text()

    def set_revision(self, commit: str, count: int) -> None:
        """Show a new head revision on the pill.

        The bar reads the head from the project's own history, so this is for
        an owner that already has the answer; the next world change re-reads it
        from the record either way.
        """
        self.revision.set_revision(commit, count)
        self.Layout()

    def set_selection(self, text: str) -> None:
        """Show the selection delta and size, monospaced."""
        self.selection.set_text(text)
        self.Layout()

    def set_dimension(self, text: str) -> None:
        """Show which dimension the workspace is editing."""
        self.dimension.set_text(text)
        self.Layout()

    def speed(self) -> int:
        """Return the camera speed in blocks per second."""
        return int(self.speed_slider.GetValue())

    def set_speed(self, value: int, *, notify: bool = False) -> None:
        """Fly the renderer's camera at ``value`` blocks per second."""
        clamped = self._clamp_speed(value)
        self.speed_slider.SetValue(clamped)
        applied = set_camera_speed(clamped)
        self.speed_value.set_text(f"{clamped} b/s" if applied else "no camera")
        self.Layout()
        if notify:
            invoke(self.on_speed, clamped)

    def projection(self) -> str:
        """Return the chosen projection key: ``3d`` or ``top``."""
        return self.projection_toggle.value

    def set_projection(self, key: str, *, notify: bool = False) -> None:
        """Switch the renderer's projection, and the toggle showing it."""
        if key in dict(PROJECTIONS):
            set_camera_projection(key)
        self.projection_toggle.set_value(key, notify=notify)

    # -- events --------------------------------------------------------------
    def _open_history(self) -> None:
        if self.on_history is not None:
            invoke(self.on_history)
        else:
            invoke(self.on_surface, "history")

    def _on_speed(self, _event: wx.CommandEvent) -> None:
        value = self.speed()
        applied = set_camera_speed(value)
        self.speed_value.set_text(f"{value} b/s" if applied else "no camera")
        self.Layout()
        invoke(self.on_speed, value)

    def _on_projection(self, key: str) -> None:
        set_camera_projection(key)
        invoke(self.on_projection, key)

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        position = event.GetPosition()
        if position == wx.DefaultPosition:
            size = self.GetSize()
            position = self.ClientToScreen(wx.Point(size.width // 2, size.height // 2))
        open_studio_menu(self, "statusbar", position, self.on_surface, self.on_command)

    # -- appearance ----------------------------------------------------------
    def _apply_theme(self) -> None:
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface_container)
        self.speed_slider.SetBackgroundColour(palette.surface_container)
        self.speed_slider.SetForegroundColour(palette.primary)

    def refresh_theme(self) -> None:
        """Re-read the palette for the bar and everything sitting on it."""
        self._apply_theme()
        for child in self.GetChildren():
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        self.Layout()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = paint_context(self, palette.surface_container)
        width, _height = self.GetClientSize()
        gcdc.SetPen(wx.Pen(palette.outline_variant))
        gcdc.DrawLine(0, 0, width, 0)
        del gcdc


__all__ = [
    "BAR_HEIGHT",
    "CAMERA_FRAME_MS",
    "DEFAULT_CAMERA_SPEED",
    "MAX_CAMERA_SPEED",
    "MAX_PROJECT_REVISIONS",
    "MIN_CAMERA_SPEED",
    "NO_HISTORY_STORE",
    "NO_REVISIONS",
    "PROJECTIONS",
    "BarLabel",
    "RevisionPill",
    "SegmentedToggle",
    "StatusBar",
    "StatusReadout",
    "blocks_per_second",
    "camera_projection",
    "camera_speed",
    "clear_container",
    "dimension_text",
    "history_store",
    "invalidate_project_history",
    "move_speed_for",
    "open_studio_menu",
    "project_history_events",
    "project_key_for",
    "project_record_ids",
    "restore_history_event",
    "selection_text",
    "set_camera_projection",
    "set_camera_speed",
    "single_line",
    "studio_canvas",
    "world_status_text",
]
