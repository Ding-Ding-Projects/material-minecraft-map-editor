"""The workspace properties pane: what is selected, what changed, and why.

Three tabs share one column.  **Properties** lists the facts the workspace
holds about the current selection.  **History** lists the project's revisions
and restores one, which appends a new revision rather than rewinding -- the
state you restored from stays undoable, which is the whole point of the
per-project repository.  **Notes** is a real note stored with the project, not
a scratch box that empties when the window closes.

The pane's own search filters the rows in front of it and reports an honest
count, including the empty one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api import config, local_history
from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.copy import studio_text
from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.studio.status_bar import (
    clear_container,
    open_studio_menu,
    single_line,
)
from amulet_map_editor.api.studio.widgets import (
    SearchBar,
    SectionLabel,
    StudioButton,
    elide,
    invoke,
    paint_context,
    point_size,
)

log = logging.getLogger(__name__)

#: The design's properties pane width, in design pixels.
PANEL_WIDTH = 308

#: Narrower than this and a label and its monospaced value start colliding.
MIN_PANEL_WIDTH = 240

#: Config record holding one note per project.  Notes are project content, so
#: they are bounded and stored beside the profile rather than inside the user's
#: world directory.
NOTES_CONFIG_ID = "amulet_studio_project_notes"
MAX_NOTE_LENGTH = 20000

#: The tabs across the top of the pane.
PANE_TABS: Tuple[Tuple[str, str], ...] = (
    ("properties", "Properties"),
    ("history", "History"),
    ("notes", "Notes"),
)

_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL)


@dataclass(frozen=True)
class PropertySection:
    """One titled block of label-and-value rows."""

    title: str
    rows: Tuple[Tuple[str, str], ...] = ()

    def matches(self, state: SearchState) -> "PropertySection":
        """Return this section with only the rows the query keeps."""
        if not state.is_active():
            return self
        if state.matches(self.title):
            return self
        kept = tuple(row for row in self.rows if state.matches(f"{row[0]} {row[1]}"))
        return PropertySection(self.title, kept)


@dataclass(frozen=True)
class ProjectRevision:
    """One commit in the project's own Git repository."""

    commit: str
    message: str
    meta: str
    head: bool = False

    def haystack(self) -> str:
        """Return everything a search over the history should look at."""
        return f"{self.commit} {self.message} {self.meta}"


#: The revisions the design's project history shows, newest first.
DEFAULT_REVISIONS: Tuple[ProjectRevision, ...] = (
    ProjectRevision(
        "a91f0c7",
        "Fill selection with deepslate",
        "a91f0c7 · 10 Aug 2026, 09:41 · 12 chunks",
        head=True,
    ),
    ProjectRevision(
        "5d3e118",
        "Move box 1 to -2, 98, -49",
        "5d3e118 · 10 Aug 2026, 09:22 · 1 box",
    ),
    ProjectRevision(
        "c72ba40",
        "Paste spawn arch structure",
        "c72ba40 · 10 Aug 2026, 08:58 · 384 blocks",
    ),
    ProjectRevision(
        "1e6f9d2",
        "Delete unselected chunks",
        "1e6f9d2 · 09 Aug 2026, 21:14 · 96 chunks",
    ),
    ProjectRevision(
        "7ab4c05",
        "Import Debug 1.14 chunk backup",
        "7ab4c05 · 09 Aug 2026, 20:02 · 48 chunks",
    ),
    ProjectRevision(
        "0004aa1",
        "Initial project commit",
        "0004aa1 · 09 Aug 2026, 19:40 · world snapshot",
    ),
)

#: The sections the design's pane shows for the selected box.
DEFAULT_SECTIONS: Tuple[PropertySection, ...] = (
    PropertySection(
        "Selection",
        (
            ("Minimum", "-2, 98, -49"),
            ("Maximum", "13, 99, -32"),
            ("Size", "16x2x18"),
            ("Volume", "576 blocks"),
        ),
    ),
    PropertySection(
        "Dimension",
        (
            ("Dimension", "minecraft:overworld"),
            ("Height range", "-64 to 320"),
            ("Loaded chunks", "812"),
        ),
    ),
    PropertySection(
        "Revision",
        (
            ("Head", "a91f0c7"),
            ("Message", "Fill selection with deepslate"),
            ("Committed", "10 Aug 2026, 09:41"),
            ("Revisions", "1,284 commits"),
        ),
    ),
)


def load_notes() -> Dict[str, str]:
    """Return every stored project note, keyed by project."""
    raw = config.get(NOTES_CONFIG_ID, {})
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def note_for(project_key: str) -> str:
    """Return the note stored for one project, or an empty string."""
    return load_notes().get(str(project_key), "")


def store_note(project_key: str, text: str) -> bool:
    """Persist one project's note, returning whether it reached disk.

    An unwritable profile is reported to the caller rather than swallowed: a
    note the user believes was saved and was not is worse than being told the
    save failed.
    """
    key = str(project_key)
    if not key:
        return False
    try:
        notes = load_notes()
        notes[key] = str(text)[:MAX_NOTE_LENGTH]
        config.put(NOTES_CONFIG_ID, notes)
    except OSError:
        log.exception("Could not store the note for project %r", key)
        return False
    local_history.safe_record(
        f"studio-note-{key}",
        {"project": key, "characters": len(str(text)[:MAX_NOTE_LENGTH])},
        record_type="studio note",
    )
    return True


class PropertyRow(wx.Control):
    """One label on the left, one monospaced value on the right."""

    PADDING_X = 11
    PADDING_Y = 9

    def __init__(self, parent: wx.Window, label: str, value: str) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self.label = str(label)
        self.value = str(value)
        self.SetName(f"{self.label}: {self.value}")
        self.SetToolTip(f"{self.label}: {self.value}")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, point_size(12)))
        label_width, label_height = dc.GetTextExtent(self.label or " ")
        dc.SetFont(tokens.mono_font(self, point_size(12)))
        value_width, value_height = dc.GetTextExtent(self.value or " ")
        return wx.Size(
            label_width + value_width + tokens.scaled(self.PADDING_X * 2 + 10),
            max(label_height, value_height) + tokens.scaled(self.PADDING_Y) * 2,
        )

    def refresh_theme(self) -> None:
        """Re-measure for the live density and repaint."""
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface_container
        dc, gcdc = paint_context(
            self, backdrop if backdrop.IsOk() else palette.surface_container
        )
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(tokens.RADIUS_SM + 1),
            palette.surface,
            palette.outline_variant,
        )
        inset = tokens.scaled(self.PADDING_X)
        gcdc.SetFont(tokens.mono_font(self, point_size(12)))
        value = elide(gcdc, self.value, max(0, width - inset * 2))
        value_width = gcdc.GetTextExtent(value)[0]
        gcdc.SetTextForeground(palette.on_surface)
        gcdc.DrawText(
            value, width - inset - value_width, (height - gcdc.GetCharHeight()) // 2
        )
        gcdc.SetFont(tokens.font(self, point_size(12)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        available = max(0, width - inset * 2 - value_width - tokens.scaled(10))
        gcdc.DrawText(
            elide(gcdc, self.label, available),
            inset,
            (height - gcdc.GetCharHeight()) // 2,
        )
        del gcdc


class RevisionRow(wx.Panel):
    """One revision: what it changed, when, and a way back to it."""

    def __init__(
        self,
        parent: wx.Window,
        revision: ProjectRevision,
        *,
        on_restore: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.revision = revision
        self.on_restore = on_restore
        state = " (head)" if revision.head else ""
        self.SetName(f"Revision {revision.message}{state}, {revision.meta}")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.restore_button = StudioButton(
            self,
            studio_text("Restore"),
            variant="outlined",
            height=28,
            on_click=self._restore,
            hint=single_line(
                studio_text(
                    "Restoring writes a new revision, so this one stays undoable.",
                    "還原會寫多個新版本，所以呢個版本一樣仲可以還原返。",
                )
            ),
            name=f"Restore revision {revision.commit}",
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.AddStretchSpacer(1)
        row.Add(self.restore_button, 0, wx.ALIGN_CENTER_VERTICAL)
        frame = wx.BoxSizer(wx.VERTICAL)
        frame.AddSpacer(tokens.scaled(38))
        frame.Add(row, 0, wx.EXPAND | wx.ALL, tokens.scaled(10))
        self.SetSizer(frame)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self._apply_theme()

    def _restore(self) -> None:
        invoke(self.on_restore, self.revision.commit)

    def _apply_theme(self) -> None:
        self.SetBackgroundColour(tokens.palette().surface_container)

    def refresh_theme(self) -> None:
        """Re-read the palette for the row and its button."""
        self._apply_theme()
        self.restore_button.refresh_theme()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = paint_context(self, palette.surface_container)
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(tokens.RADIUS_SM + 1),
            palette.surface,
            palette.primary if self.revision.head else palette.outline_variant,
        )
        left = tokens.scaled(11)
        dot = tokens.scaled(9)
        top = tokens.scaled(14)
        gcdc.SetPen(wx.TRANSPARENT_PEN)
        gcdc.SetBrush(
            wx.Brush(palette.primary if self.revision.head else palette.outline_variant)
        )
        gcdc.DrawEllipse(left, top, dot, dot)
        text_left = left + dot + tokens.scaled(10)
        available = max(0, width - text_left - tokens.scaled(11))
        gcdc.SetFont(tokens.font(self, point_size(12), _MEDIUM))
        gcdc.SetTextForeground(palette.on_surface)
        gcdc.DrawText(
            elide(gcdc, self.revision.message, available), text_left, tokens.scaled(10)
        )
        gcdc.SetFont(tokens.mono_font(self, point_size(11)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        gcdc.DrawText(
            elide(gcdc, self.revision.meta, available),
            text_left,
            tokens.scaled(10) + gcdc.GetCharHeight() + tokens.scaled(4),
        )
        del gcdc


class TabPill(StudioButton):
    """One of the pane's pill tabs, filled while it is the open one."""

    def __init__(
        self,
        parent: wx.Window,
        key: str,
        label: str,
        *,
        selected: bool = False,
        on_click: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.key = str(key)
        self.selected = bool(selected)
        self._on_pick = on_click
        super().__init__(
            parent,
            label,
            variant="pill",
            on_click=self._pick,
            height=28,
            hint=f"Show {label}",
        )
        self._sync_name()

    def _pick(self) -> None:
        invoke(self._on_pick, self.key)

    def _sync_name(self) -> None:
        state = "selected" if self.selected else "not selected"
        self.SetName(f"{self.GetLabel()} tab, {state}")

    def set_selected(self, selected: bool) -> None:
        """Mark the tab as the open one, or not."""
        self.selected = bool(selected)
        self._sync_name()
        self.Refresh()

    def _state_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour, Optional[wx.Colour]]:
        if self.selected:
            fill = palette.primary_container
            if self._pressed:
                fill = tokens.blend(fill, palette.primary, 0.18)
            elif self._hovered:
                fill = tokens.blend(fill, palette.primary, 0.10)
            return fill, palette.on_primary_container, palette.primary_container
        fill: Optional[wx.Colour] = None
        if self._pressed:
            fill = tokens.blend(
                palette.surface_container_high, palette.on_surface, 0.10
            )
        elif self._hovered:
            fill = palette.surface_container_high
        return fill, palette.on_surface_variant, None


class PropertiesPane(wx.Panel):
    """The 308px column on the right of the workspace."""

    WIDTH = PANEL_WIDTH
    MIN_WIDTH = MIN_PANEL_WIDTH

    def __init__(
        self,
        parent: wx.Window,
        *,
        title: str = "Box 1",
        project_key: str = "",
        sections: Sequence[PropertySection] = DEFAULT_SECTIONS,
        revisions: Sequence[ProjectRevision] = DEFAULT_REVISIONS,
        on_close: Optional[Callable[[], None]] = None,
        on_action: Optional[Callable[[str], None]] = None,
        on_restore: Optional[Callable[[str], None]] = None,
        on_surface: Optional[Callable[[str], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_close = on_close
        self.on_action = on_action
        self.on_restore = on_restore
        self.on_surface = on_surface
        self.on_command = on_command
        self.sections: List[PropertySection] = list(sections)
        self.revisions: List[ProjectRevision] = list(revisions)
        self.project_key = str(project_key)
        self.tab = "properties"
        self.search_state = SearchState(label="Properties")
        self._note_dirty = False
        self.SetName("Properties pane")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        self.title_label = wx.StaticText(self, label=str(title))
        self.title_label.SetName("Properties pane title")
        self.appearance_button = StudioButton(
            self,
            "",
            variant="icon",
            glyph="✎",
            height=26,
            min_width=26,
            on_click=self.open_appearance_editor,
            hint="Edit appearance for this pane",
            name="Edit appearance",
        )
        self.close_button = StudioButton(
            self,
            "",
            variant="icon",
            glyph="×",
            height=26,
            min_width=26,
            on_click=self._close,
            hint="Close the properties pane",
            name="Close the properties pane",
        )
        self.tab_buttons: Dict[str, TabPill] = {}
        tab_row = wx.BoxSizer(wx.HORIZONTAL)
        for key, label in PANE_TABS:
            pill = TabPill(
                self, key, label, selected=key == self.tab, on_click=self.set_tab
            )
            self.tab_buttons[key] = pill
            tab_row.Add(pill, 0, wx.RIGHT, tokens.scaled(2))
        self.search = SearchBar(
            self,
            "Search these properties",
            self.search_state,
            on_change=self._on_search,
            compact=True,
        )
        self.scroller = wx.ScrolledWindow(self, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.scroller.SetScrollRate(0, tokens.scaled(12))
        self.scroller.SetName("Properties pane contents")
        self.body = wx.BoxSizer(wx.VERTICAL)
        self.scroller.SetSizer(self.body)
        self.status_label = wx.StaticText(self.scroller, label="")
        self.status_label.SetName("Properties pane search result")
        self.notes_field = wx.TextCtrl(
            self.scroller,
            value=note_for(self.project_key),
            style=wx.TE_MULTILINE | wx.TE_RICH2,
        )
        self.notes_field.SetName("Project note")
        self.notes_field.SetHint(
            single_line(
                studio_text(
                    "Write anything this project needs remembered.",
                    "呢個項目要記住嘅嘢，寫低喺度。",
                )
            )
        )
        self.notes_field.SetMaxLength(MAX_NOTE_LENGTH)
        self.notes_field.SetMinSize(wx.Size(-1, tokens.scaled(160)))
        self.notes_field.Bind(wx.EVT_TEXT, self._on_note_changed)
        self.notes_field.Bind(wx.EVT_KILL_FOCUS, self._on_note_focus_lost)
        self.notes_status = wx.StaticText(self.scroller, label="")
        self.notes_status.SetName("Project note status")
        self.action_button = StudioButton(
            self,
            "",
            variant="filled",
            on_click=self._run_action,
            name="Pane action",
        )

        header = wx.BoxSizer(wx.HORIZONTAL)
        header.Add(self.title_label, 1, wx.ALIGN_CENTER_VERTICAL)
        header.Add(
            self.appearance_button,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_SM),
        )
        header.Add(
            self.close_button,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_XS),
        )
        pad = tokens.scaled(tokens.SPACE_SM + 4)
        frame = wx.BoxSizer(wx.VERTICAL)
        frame.Add(header, 0, wx.EXPAND | wx.ALL, pad)
        frame.Add(tab_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, tokens.scaled(10))
        frame.Add(
            self.search,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            tokens.scaled(tokens.SPACE_MD - 2),
        )
        frame.Add(
            self.scroller,
            1,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            tokens.scaled(tokens.SPACE_MD - 2),
        )
        frame.Add(
            self.action_button,
            0,
            wx.EXPAND | wx.ALL,
            tokens.scaled(tokens.SPACE_MD - 2),
        )
        self.SetSizer(frame)
        self.SetMinSize(wx.Size(tokens.scaled(self.MIN_WIDTH), -1))
        self.SetSize(wx.Size(tokens.scaled(self.WIDTH), -1))

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.scroller.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self._apply_theme()
        self.rebuild()

    # -- content -------------------------------------------------------------
    def set_title(self, title: str) -> None:
        """Name what the pane is describing."""
        self.title_label.SetLabel(single_line(title))
        self.title_label.SetName(f"Properties for {single_line(title)}")
        self.Layout()

    def set_sections(self, sections: Sequence[PropertySection]) -> None:
        """Replace the Properties tab's rows."""
        self.sections = list(sections)
        if self.tab == "properties":
            self.rebuild()

    def set_revisions(self, revisions: Sequence[ProjectRevision]) -> None:
        """Replace the History tab's revisions."""
        self.revisions = list(revisions)
        if self.tab == "history":
            self.rebuild()

    def set_project(self, project_key: str, title: str = "") -> None:
        """Point the pane at another project, loading that project's note."""
        if self._note_dirty:
            self.save_note()
        self.project_key = str(project_key)
        self.notes_field.ChangeValue(note_for(self.project_key))
        self._note_dirty = False
        if title:
            self.set_title(title)
        self.rebuild()

    def set_tab(self, key: str) -> None:
        """Open one of the three tabs."""
        if key not in self.tab_buttons:
            return
        self.tab = key
        for name, pill in self.tab_buttons.items():
            pill.set_selected(name == key)
        self.search_state.label = dict(PANE_TABS)[key]
        self.rebuild()

    def rebuild(self) -> None:
        """Rebuild the open tab's body against the current search query."""
        state = self.search_state
        clear_container(
            self.body,
            self.scroller,
            keep=(self.status_label, self.notes_field, self.notes_status),
        )
        self.notes_field.Show(self.tab == "notes")
        self.notes_status.Show(self.tab == "notes")
        gap = tokens.scaled(tokens.SPACE_SM - 1)

        if self.tab == "properties":
            kept = 0
            for section in self.sections:
                filtered = section.matches(state)
                if not filtered.rows:
                    continue
                kept += len(filtered.rows)
                self.body.Add(
                    SectionLabel(self.scroller, filtered.title),
                    0,
                    wx.EXPAND | wx.BOTTOM,
                    tokens.scaled(tokens.SPACE_SM),
                )
                for label, value in filtered.rows:
                    self.body.Add(
                        PropertyRow(self.scroller, label, value),
                        0,
                        wx.EXPAND | wx.BOTTOM,
                        gap,
                    )
                self.body.AddSpacer(tokens.scaled(tokens.SPACE_SM))
            self.status_label.SetLabel(
                state.describe_matches(kept, "property") if state.is_active() else ""
            )
        elif self.tab == "history":
            matched = [
                revision
                for revision in self.revisions
                if state.matches(revision.haystack())
            ]
            for revision in matched:
                self.body.Add(
                    RevisionRow(self.scroller, revision, on_restore=self._restore),
                    0,
                    wx.EXPAND | wx.BOTTOM,
                    gap,
                )
            self.status_label.SetLabel(
                state.describe_matches(len(matched), "revision")
                if state.is_active()
                else f"{len(matched)} revisions · newest first"
            )
        else:
            self.body.Add(self.notes_field, 0, wx.EXPAND | wx.BOTTOM, gap)
            self.body.Add(self.notes_status, 0, wx.EXPAND | wx.BOTTOM, gap)
            self._set_note_status(
                studio_text(
                    "Stored with the project.",
                    "會同項目一齊存住。",
                )
            )
            self.status_label.SetLabel(
                single_line(
                    studio_text(
                        "The search filters the Properties and History tabs.",
                        "個搜尋係篩「屬性」同「歷史」嗰兩版。",
                    )
                )
                if state.is_active()
                else ""
            )

        self.status_label.Show(bool(self.status_label.GetLabel()))
        if self.status_label.GetLabel():
            self.body.Add(self.status_label, 0, wx.EXPAND | wx.TOP, gap)
        label, _handler = self._action_for_tab()
        self.action_button.SetLabel(label)
        self.action_button.SetName(single_line(label))
        self.scroller.FitInside()
        self.scroller.Layout()
        self.Layout()
        self._apply_theme()

    # -- actions -------------------------------------------------------------
    def _action_for_tab(self) -> Tuple[str, Callable[[], None]]:
        """Return the primary action for the open tab: its label and its work."""
        if self.tab == "history":
            return (
                studio_text("Open project history", "開項目歷史"),
                lambda: invoke(self.on_surface, "history"),
            )
        if self.tab == "notes":
            return (studio_text("Save note", "儲存筆記"), self.save_note)
        return (
            studio_text("Frame selection", "對準選取範圍"),
            lambda: invoke(self.on_action, "frame"),
        )

    def _run_action(self) -> None:
        _label, handler = self._action_for_tab()
        handler()

    def _restore(self, commit: str) -> None:
        invoke(self.on_restore, commit)

    def _close(self) -> None:
        invoke(self.on_close)

    def open_appearance_editor(self) -> None:
        """Open the shared per-element appearance editor for this pane."""
        try:
            from amulet_map_editor.api.wx.ui import element_appearance
        except ImportError:
            log.debug("The element appearance editor is not available")
            return
        try:
            element_appearance.open_element_appearance(self)
        except Exception:
            log.exception("Could not open the appearance editor for the pane")

    # -- notes ---------------------------------------------------------------
    def note(self) -> str:
        """Return the note text currently in the field."""
        return self.notes_field.GetValue()

    def save_note(self) -> bool:
        """Write the note to the project's record and say whether it landed."""
        if not self.project_key:
            self._set_note_status(
                studio_text(
                    "No project is open, so there is nowhere to store this note yet.",
                    "而家未開項目，所以呢個筆記暫時冇地方擺。",
                )
            )
            return False
        saved = store_note(self.project_key, self.note())
        self._note_dirty = not saved
        self._set_note_status(
            studio_text("Saved with the project.", "已經同項目一齊存好。")
            if saved
            else studio_text(
                "The note could not be written to your profile.",
                "呢個筆記寫唔入你個設定檔。",
            )
        )
        return saved

    def _set_note_status(self, text: str) -> None:
        self.notes_status.SetLabel(single_line(text))
        self.notes_status.SetName(f"Project note status: {single_line(text)}")
        self.Layout()

    def _on_note_changed(self, event: wx.CommandEvent) -> None:
        self._note_dirty = True
        self._set_note_status(
            studio_text("Unsaved changes.", "仲未儲存。"),
        )
        event.Skip()

    def _on_note_focus_lost(self, event: wx.FocusEvent) -> None:
        if self._note_dirty:
            self.save_note()
        event.Skip()

    # -- events --------------------------------------------------------------
    def _on_search(self, _state: SearchState) -> None:
        self.rebuild()

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        position = event.GetPosition()
        if position == wx.DefaultPosition:
            size = self.GetSize()
            position = self.ClientToScreen(wx.Point(size.width // 2, size.height // 3))
        open_studio_menu(self, "pane", position, self.on_surface, self.on_command)

    # -- appearance ----------------------------------------------------------
    def _apply_theme(self) -> None:
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface_container)
        self.scroller.SetBackgroundColour(palette.surface_container)
        self.title_label.SetForegroundColour(palette.on_surface)
        self.title_label.SetFont(tokens.font(self, point_size(14), _MEDIUM))
        for label in (self.status_label, self.notes_status):
            label.SetForegroundColour(palette.on_surface_variant)
            label.SetFont(tokens.font(self, point_size(11)))
        self.notes_field.SetBackgroundColour(palette.surface)
        self.notes_field.SetForegroundColour(palette.on_surface)
        self.notes_field.SetFont(tokens.font(self, point_size(12)))

    def refresh_theme(self) -> None:
        """Re-read the palette for the pane and every row in it."""
        self._apply_theme()
        for child in list(self.GetChildren()) + list(self.scroller.GetChildren()):
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        self.Layout()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = paint_context(self, palette.surface_container)
        width, height = self.GetClientSize()
        gcdc.SetPen(wx.Pen(palette.outline_variant))
        gcdc.DrawLine(0, 0, 0, height)
        tabs_bottom = self.search.GetPosition().y - tokens.scaled(tokens.SPACE_SM)
        if 0 < tabs_bottom < height:
            gcdc.DrawLine(0, tabs_bottom, width, tabs_bottom)
        del gcdc


__all__ = [
    "DEFAULT_REVISIONS",
    "DEFAULT_SECTIONS",
    "MAX_NOTE_LENGTH",
    "MIN_PANEL_WIDTH",
    "NOTES_CONFIG_ID",
    "PANE_TABS",
    "PANEL_WIDTH",
    "ProjectRevision",
    "PropertiesPane",
    "PropertyRow",
    "PropertySection",
    "RevisionRow",
    "TabPill",
    "load_notes",
    "note_for",
    "store_note",
]
